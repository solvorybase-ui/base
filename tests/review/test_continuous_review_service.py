import pytest

import backend.review.continuous_service as service
from backend.review.decision_repository import CurrentReviewRef
from backend.review.session_read_repository import LockedReviewItem
from backend.review.session_service import ReviewSessionBuildResult

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


def open_pair(session_id="session-1"):
    session = type("Session", (), {"session_id": session_id, "item_count": 1})()
    return session, item()


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


def test_user_flow_requires_no_session_id(monkeypatch):
    configure_flow(monkeypatch, current=open_pair())
    state = service.load_continuous_review(Connection())
    assert state.item.review_session_item_id == "item-1"


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
