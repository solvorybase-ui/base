import pytest

import backend.review.continuous_service as service
from backend.review.decision_repository import CurrentReviewRef
from backend.review.session_read_repository import (
    LockedReviewItem,
    ReviewSessionProjection,
)
from backend.review.session_service import (
    DEFAULT_SESSION_SIZE,
    ReviewSessionBuildResult,
)

from tests.review.test_review_session_read_service import item


class Transaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.connection.events.append("begin")

    def __exit__(self, exc_type, exc, tb):
        self.connection.events.append("rollback" if exc_type else "commit")


class Connection:
    def __init__(self):
        self.events = []

    def transaction(self):
        return Transaction(self)


@pytest.fixture(autouse=True)
def default_open_count(monkeypatch):
    monkeypatch.setattr(service, "count_open_review_variants", lambda c: 1)


def open_pair(session_id="session-1", *, items=None):
    session_items = tuple(items or (item(),))
    session = ReviewSessionProjection(
        session_id, "prepared", len(session_items), session_items
    )
    return session, session_items[0]


def configure_flow(monkeypatch, *, finished=(), current=None, built=None):
    completed = []
    monkeypatch.setattr(service, "find_fully_decided_active_session_ids", lambda c: list(finished))
    monkeypatch.setattr(service, "complete_review_session", lambda c, *, session_id: completed.append(session_id))
    monkeypatch.setattr(service, "load_next_open_review_item", lambda c: current)
    monkeypatch.setattr(service, "build_review_session", lambda c: built)
    return completed


def test_existing_open_session_is_reused(monkeypatch):
    pair = open_pair()
    configure_flow(monkeypatch, current=pair)
    state = service.load_continuous_review(Connection())
    assert state.session is pair[0]
    assert state.item is pair[1]


def test_no_session_with_candidates_builds_standard_session(monkeypatch):
    calls = []
    pair = open_pair("session-new")
    responses = iter([None, pair])
    monkeypatch.setattr(service, "find_fully_decided_active_session_ids", lambda c: [])
    monkeypatch.setattr(service, "load_next_open_review_item", lambda c: next(responses))
    monkeypatch.setattr(service, "build_review_session", lambda c: calls.append("build") or ReviewSessionBuildResult("session-new", 20))
    state = service.load_continuous_review(Connection())
    assert calls == ["build"]
    assert state.session.session_id == "session-new"


def test_smaller_builder_session_is_accepted(monkeypatch):
    pair = open_pair("small")
    responses = iter([None, pair])
    monkeypatch.setattr(service, "find_fully_decided_active_session_ids", lambda c: [])
    monkeypatch.setattr(service, "load_next_open_review_item", lambda c: next(responses))
    monkeypatch.setattr(service, "build_review_session", lambda c: ReviewSessionBuildResult("small", 7))
    assert service.load_continuous_review(Connection()).item is not None


def test_no_candidates_creates_no_empty_session(monkeypatch):
    configure_flow(monkeypatch, current=None, built=None)
    state = service.load_continuous_review(Connection())
    assert state.is_empty
    assert state.session is None


def test_fully_decided_session_is_completed(monkeypatch):
    completed = configure_flow(monkeypatch, finished=("finished",), current=open_pair())
    service.load_continuous_review(Connection())
    assert completed == ["finished"]


def test_finished_session_then_builds_next_queue(monkeypatch):
    completed = []
    pair = open_pair("next")
    responses = iter([None, pair])
    monkeypatch.setattr(service, "find_fully_decided_active_session_ids", lambda c: ["old"])
    monkeypatch.setattr(service, "complete_review_session", lambda c, *, session_id: completed.append(session_id))
    monkeypatch.setattr(service, "load_next_open_review_item", lambda c: next(responses))
    monkeypatch.setattr(service, "build_review_session", lambda c: ReviewSessionBuildResult("next", 20))
    state = service.load_continuous_review(Connection())
    assert completed == ["old"]
    assert state.session.session_id == "next"


@pytest.mark.parametrize(
    ("candidate_count", "expected_session_sizes"),
    [
        (25, [20, 5]),
        (40, [20, 20]),
        (41, [20, 20, 1]),
        (20, [20]),
        (0, []),
    ],
)
def test_continuous_flow_uses_twenty_only_as_internal_session_size(
    monkeypatch, candidate_count, expected_session_sizes
):
    pending = candidate_count
    active = None
    completed = []
    built_sizes = []

    def find_finished(_connection):
        if active is not None and active["remaining"] == 0:
            return [active["session_id"]]
        return []

    def complete(_connection, *, session_id):
        nonlocal active
        completed.append(session_id)
        active = None

    def load_next(_connection):
        if active is None or active["remaining"] == 0:
            return None
        position = active["size"] - active["remaining"] + 1
        session = ReviewSessionProjection(
            active["session_id"],
            "prepared",
            active["size"],
            tuple(
                item(
                    item_id=(
                        f"{active['session_id']}-item-{item_position}"
                    ),
                    position=item_position,
                )
                for item_position in range(1, active["size"] + 1)
            ),
        )
        return session, session.items[position - 1]

    def build(_connection):
        nonlocal pending, active
        if pending == 0:
            return None
        size = min(DEFAULT_SESSION_SIZE, pending)
        pending -= size
        built_sizes.append(size)
        active = {
            "session_id": f"session-{len(built_sizes)}",
            "size": size,
            "remaining": size,
        }
        return ReviewSessionBuildResult(active["session_id"], size)

    monkeypatch.setattr(
        service, "find_fully_decided_active_session_ids", find_finished
    )
    monkeypatch.setattr(service, "complete_review_session", complete)
    monkeypatch.setattr(service, "load_next_open_review_item", load_next)
    monkeypatch.setattr(service, "build_review_session", build)

    displayed = 0
    while True:
        state = service.load_continuous_review(Connection())
        if state.is_empty:
            break
        displayed += 1
        active["remaining"] -= 1

    assert displayed == candidate_count
    assert built_sizes == expected_session_sizes
    assert len(completed) == len(expected_session_sizes)


def test_user_flow_requires_no_session_id(monkeypatch):
    configure_flow(monkeypatch, current=open_pair())
    state = service.load_continuous_review(Connection())
    assert state.item.review_session_item_id == "item-1"


def test_global_progress_is_dynamic_and_independent_of_session_size(monkeypatch):
    session_items = tuple(
        item(item_id=f"item-{position}", position=position)
        for position in range(1, 21)
    )
    monkeypatch.setattr(service, "count_open_review_variants", lambda c: 79)
    configure_flow(monkeypatch, current=open_pair(items=session_items))

    state = service.load_continuous_review(Connection())

    assert state.open_count == 79
    assert state.session.item_count == 20


def test_new_selected_candidates_increase_open_count_on_next_load(monkeypatch):
    counts = iter((79, 80))
    monkeypatch.setattr(
        service, "count_open_review_variants", lambda c: next(counts)
    )
    configure_flow(monkeypatch, current=open_pair())

    assert service.load_continuous_review(Connection()).open_count == 79
    assert service.load_continuous_review(Connection()).open_count == 80


def test_prefetch_contains_only_next_two_open_items(monkeypatch):
    session_items = (
        item(item_id="item-1", position=1),
        item(item_id="item-2", position=2),
        item(item_id="item-3", position=3),
        item(item_id="item-4", position=4),
    )
    configure_flow(monkeypatch, current=open_pair(items=session_items))

    connection = Connection()
    monkeypatch.setattr(
        service,
        "record_review_decision",
        lambda *args, **kwargs: pytest.fail("prefetch wrote a decision"),
    )

    state = service.load_continuous_review(connection)

    assert [entry.review_session_item_id for entry in state.prefetch_items] == [
        "item-2",
        "item-3",
    ]
    assert connection.events == []


def test_prefetch_uses_only_one_item_when_one_remains(monkeypatch):
    session_items = (
        item(item_id="item-1", position=1),
        item(item_id="item-2", position=2),
    )
    configure_flow(monkeypatch, current=open_pair(items=session_items))

    state = service.load_continuous_review(Connection())

    assert tuple(entry.review_session_item_id for entry in state.prefetch_items) == (
        "item-2",
    )


def test_prefetch_skips_decided_items_and_does_not_mutate_projection(monkeypatch):
    decided = item(item_id="item-2", position=2, decision="hit")
    session_items = (
        item(item_id="item-1", position=1),
        decided,
        item(item_id="item-3", position=3),
    )
    pair = open_pair(items=session_items)
    configure_flow(monkeypatch, current=pair)

    state = service.load_continuous_review(Connection())

    assert tuple(entry.review_session_item_id for entry in state.prefetch_items) == (
        "item-3",
    )
    assert pair[0].items == session_items
    assert decided.current_decision == "hit"


def test_prefetch_is_empty_for_last_open_item(monkeypatch):
    configure_flow(monkeypatch, current=open_pair())

    state = service.load_continuous_review(Connection())

    assert state.prefetch_items == ()


def configure_decision(monkeypatch, *, locked=True, current=None):
    captured = {}
    monkeypatch.setattr(service, "find_fully_decided_active_session_ids", lambda c: [])
    monkeypatch.setattr(
        service,
        "lock_open_review_item",
        lambda c, *, review_session_item_id: LockedReviewItem(review_session_item_id, "session-1") if locked else None,
    )
    monkeypatch.setattr(service, "get_current_review", lambda c, *, review_session_item_id: current)

    def record(connection, **kwargs):
        captured.update(kwargs)
        return "result"

    monkeypatch.setattr(service, "record_review_decision", record)
    return captured


def test_decision_locks_and_delegates_to_existing_service(monkeypatch):
    captured = configure_decision(monkeypatch)
    connection = Connection()
    result = service.record_continuous_review_decision(
        connection,
        review_session_item_id="item-1",
        decision="hit",
        decided_by_user_ref="review_link:link-1",
    )
    assert result == "result"
    assert captured["decision"] == "hit"
    assert connection.events == ["begin", "commit"]


def test_stale_decided_item_does_not_write_second_review(monkeypatch):
    captured = configure_decision(monkeypatch, current=CurrentReviewRef("review-1", "hit"))
    connection = Connection()
    with pytest.raises(service.StaleReviewItemError):
        service.record_continuous_review_decision(
            connection,
            review_session_item_id="item-1",
            decision="later",
            decided_by_user_ref="review_link:link-1",
        )
    assert captured == {}
    assert connection.events == ["begin", "rollback"]


def test_released_or_inactive_item_is_stale(monkeypatch):
    captured = configure_decision(monkeypatch, locked=False)
    with pytest.raises(service.StaleReviewItemError):
        service.record_continuous_review_decision(
            Connection(), review_session_item_id="item-1", decision="hit",
            decided_by_user_ref="review_link:link-1",
        )
    assert captured == {}
