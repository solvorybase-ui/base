import pytest

from backend.review.candidate_repository import ReviewCandidate
import backend.review.session_service as service
from backend.review.session_repository import (
    add_review_session_item,
    create_prepared_review_session,
    mark_review_session_cancelled,
    mark_review_session_completed,
    release_active_review_session_items,
)


def candidate(number):
    return ReviewCandidate(
        variant_id=f"variant-{number}",
        scout_result_id=f"scout-{number}",
        family_name=f"Family {number}",
        brand_name=None,
        category=None,
        variant_name=f"Variant {number}",
        model_name=None,
        description=None,
    )


class FakeTransaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.connection.transaction_events.append("begin")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.connection.transaction_events.append(
            "rollback" if exc_type is not None else "commit"
        )


class FakeConnection:
    def __init__(self):
        self.transaction_events = []

    def transaction(self):
        return FakeTransaction(self)


def configure_service(monkeypatch, candidates, *, fail_at_position=None):
    events = []
    limits = []

    def fake_load(connection, *, limit):
        limits.append(limit)
        return candidates

    def fake_create(connection, *, diversity_context):
        events.append(("session", "prepared", diversity_context))
        return "session-1"

    def fake_add(connection, **kwargs):
        events.append(("item", kwargs))
        if kwargs["position"] == fail_at_position:
            raise RuntimeError("item insert failed")

    monkeypatch.setattr(service, "load_review_candidates", fake_load)
    monkeypatch.setattr(service, "create_prepared_review_session", fake_create)
    monkeypatch.setattr(service, "add_review_session_item", fake_add)
    return events, limits


def test_twenty_candidates_create_session_with_twenty_items(monkeypatch):
    connection = FakeConnection()
    events, _ = configure_service(
        monkeypatch, [candidate(index) for index in range(1, 21)]
    )

    result = service.build_review_session(connection)

    assert result == service.ReviewSessionBuildResult("session-1", 20)
    assert len([event for event in events if event[0] == "item"]) == 20


def test_seven_candidates_create_session_with_seven_items(monkeypatch):
    connection = FakeConnection()
    events, _ = configure_service(
        monkeypatch, [candidate(index) for index in range(1, 8)]
    )

    result = service.build_review_session(connection)

    assert result == service.ReviewSessionBuildResult("session-1", 7)
    assert len([event for event in events if event[0] == "item"]) == 7


def test_zero_candidates_do_not_create_session(monkeypatch):
    connection = FakeConnection()
    events, _ = configure_service(monkeypatch, [])

    result = service.build_review_session(connection)

    assert result is None
    assert events == []
    assert connection.transaction_events == []


def test_session_is_created_prepared(monkeypatch):
    connection = FakeConnection()
    events, _ = configure_service(monkeypatch, [candidate(1)])

    service.build_review_session(connection)

    assert events[0] == (
        "session",
        "prepared",
        service.DEFAULT_DIVERSITY_CONTEXT,
    )


def test_positions_are_exactly_one_through_n(monkeypatch):
    connection = FakeConnection()
    events, _ = configure_service(
        monkeypatch, [candidate(index) for index in range(1, 8)]
    )

    service.build_review_session(connection)

    positions = [event[1]["position"] for event in events[1:]]
    assert positions == list(range(1, 8))


def test_duplicate_variant_is_added_only_once(monkeypatch):
    connection = FakeConnection()
    repeated = candidate(1)
    events, _ = configure_service(
        monkeypatch, [repeated, candidate(2), repeated]
    )

    result = service.build_review_session(connection)

    item_events = [event for event in events if event[0] == "item"]
    assert result.item_count == 2
    assert [event[1]["product_variant_id"] for event in item_events] == [
        "variant-1",
        "variant-2",
    ]


def test_canonical_eligibility_loader_is_used(monkeypatch):
    connection = FakeConnection()
    _, limits = configure_service(monkeypatch, [candidate(1)])

    service.build_review_session(connection)

    assert limits == [20]


@pytest.mark.parametrize("inactive_status", ["completed", "cancelled"])
def test_candidate_returned_after_inactive_session_is_accepted(
    monkeypatch, inactive_status
):
    connection = FakeConnection()
    events, _ = configure_service(monkeypatch, [candidate(1)])

    result = service.build_review_session(connection)

    assert inactive_status not in {"prepared", "open", "in_progress"}
    assert result.item_count == 1
    assert events[1][1]["product_variant_id"] == "variant-1"


def test_item_failure_rolls_back_whole_transaction(monkeypatch):
    connection = FakeConnection()
    configure_service(
        monkeypatch,
        [candidate(1), candidate(2), candidate(3)],
        fail_at_position=2,
    )

    with pytest.raises(RuntimeError, match="item insert failed"):
        service.build_review_session(connection)

    assert connection.transaction_events == ["begin", "rollback"]


def test_no_review_decision_is_created(monkeypatch):
    connection = FakeConnection()
    events, _ = configure_service(monkeypatch, [candidate(1)])

    service.build_review_session(connection)

    assert [event[0] for event in events] == ["session", "item"]


def test_candidate_order_is_preserved(monkeypatch):
    connection = FakeConnection()
    events, _ = configure_service(
        monkeypatch, [candidate(3), candidate(1), candidate(2)]
    )

    service.build_review_session(connection)

    assert [event[1]["product_variant_id"] for event in events[1:]] == [
        "variant-3",
        "variant-1",
        "variant-2",
    ]


def test_default_limit_is_twenty(monkeypatch):
    connection = FakeConnection()
    _, limits = configure_service(monkeypatch, [])

    service.build_review_session(connection)

    assert service.DEFAULT_SESSION_SIZE == 20
    assert limits == [20]


@pytest.mark.parametrize("invalid_limit", [0, 21])
def test_limit_must_be_between_one_and_twenty(invalid_limit):
    with pytest.raises(ValueError):
        service.build_review_session(
            FakeConnection(), limit=invalid_limit
        )


class RecordingCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        pass

    def execute(self, query, params=None):
        self.connection.calls.append((" ".join(query.split()), params))

    def fetchone(self):
        return ("session-1",)


class RecordingConnection:
    def __init__(self):
        self.calls = []

    def cursor(self):
        return RecordingCursor(self)


def test_repository_writes_only_session_and_session_items():
    connection = RecordingConnection()

    session_id = create_prepared_review_session(
        connection, diversity_context="standard_queue_builder"
    )
    add_review_session_item(
        connection,
        review_session_id=session_id,
        product_variant_id="variant-1",
        scout_result_id="scout-1",
        position=1,
    )

    sql = " ".join(query for query, _ in connection.calls)
    assert "INSERT INTO review_sessions" in sql
    assert "VALUES ('prepared', %s)" in sql
    assert "INSERT INTO review_session_items" in sql
    assert "INSERT INTO reviews" not in sql


def configure_lifecycle(monkeypatch, *, released_count=2, release_error=None):
    events = []

    def fake_complete(connection, *, review_session_id):
        events.append(("complete", review_session_id))

    def fake_cancel(connection, *, review_session_id):
        events.append(("cancel", review_session_id))

    def fake_release(connection, *, review_session_id):
        events.append(("release", review_session_id))
        if release_error is not None:
            raise release_error
        return released_count

    monkeypatch.setattr(
        service, "mark_review_session_completed", fake_complete
    )
    monkeypatch.setattr(
        service, "mark_review_session_cancelled", fake_cancel
    )
    monkeypatch.setattr(
        service, "release_active_review_session_items", fake_release
    )
    return events


def test_complete_updates_session_then_releases_items(monkeypatch):
    connection = FakeConnection()
    events = configure_lifecycle(monkeypatch, released_count=3)

    result = service.complete_review_session(
        connection, session_id="session-1"
    )

    assert events == [
        ("complete", "session-1"),
        ("release", "session-1"),
    ]
    assert result == service.ReviewSessionLifecycleResult("session-1", 3)
    assert connection.transaction_events == ["begin", "commit"]


def test_cancel_updates_session_then_releases_items(monkeypatch):
    connection = FakeConnection()
    events = configure_lifecycle(monkeypatch, released_count=4)

    result = service.cancel_review_session(
        connection, session_id="session-1"
    )

    assert events == [
        ("cancel", "session-1"),
        ("release", "session-1"),
    ]
    assert result == service.ReviewSessionLifecycleResult("session-1", 4)
    assert connection.transaction_events == ["begin", "commit"]


@pytest.mark.parametrize(
    "operation_name", ["complete_review_session", "cancel_review_session"]
)
def test_release_error_rolls_back_status_and_item_release(
    monkeypatch, operation_name
):
    connection = FakeConnection()
    configure_lifecycle(
        monkeypatch,
        release_error=RuntimeError("item release failed"),
    )

    with pytest.raises(RuntimeError, match="item release failed"):
        getattr(service, operation_name)(
            connection, session_id="session-1"
        )

    assert connection.transaction_events == ["begin", "rollback"]


class LifecycleCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rowcount = connection.release_count
        self._returns_session = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        pass

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.connection.calls.append((normalized, params))
        self._returns_session = "RETURNING id" in normalized

    def fetchone(self):
        if self._returns_session and self.connection.session_exists:
            return ("session-1",)
        return None


class LifecycleConnection:
    def __init__(self, *, session_exists=True, release_count=2):
        self.calls = []
        self.session_exists = session_exists
        self.release_count = release_count

    def cursor(self):
        return LifecycleCursor(self)


def test_complete_repository_sets_completed_status_and_timestamp():
    connection = LifecycleConnection()

    mark_review_session_completed(
        connection, review_session_id="session-1"
    )

    sql, params = connection.calls[0]
    assert "SET status = 'completed'" in sql
    assert "completed_at = now()" in sql
    assert "cancelled_at = NULL" in sql
    assert "WHERE id = %s" in sql
    assert params == ("session-1",)


def test_cancel_repository_sets_cancelled_status_and_timestamp():
    connection = LifecycleConnection()

    mark_review_session_cancelled(
        connection, review_session_id="session-1"
    )

    sql, params = connection.calls[0]
    assert "SET status = 'cancelled'" in sql
    assert "cancelled_at = now()" in sql
    assert "completed_at = NULL" in sql
    assert "WHERE id = %s" in sql
    assert params == ("session-1",)


def test_lifecycle_rejects_missing_session():
    connection = LifecycleConnection(session_exists=False)

    with pytest.raises(LookupError, match="does not exist"):
        mark_review_session_completed(
            connection, review_session_id="missing"
        )


def test_release_updates_only_active_items_of_requested_session():
    connection = LifecycleConnection(release_count=3)

    count = release_active_review_session_items(
        connection, review_session_id="session-1"
    )

    sql, params = connection.calls[0]
    assert "UPDATE review_session_items" in sql
    assert "SET released_at = now()" in sql
    assert "WHERE review_session_id = %s" in sql
    assert "AND released_at IS NULL" in sql
    assert params == ("session-1",)
    assert count == 3


def test_already_released_items_are_not_changed():
    connection = LifecycleConnection(release_count=0)

    count = release_active_review_session_items(
        connection, review_session_id="session-1"
    )

    sql, _ = connection.calls[0]
    assert "released_at IS NULL" in sql
    assert count == 0


@pytest.mark.parametrize(
    "operation_name", ["complete_review_session", "cancel_review_session"]
)
def test_terminal_lifecycle_releases_unique_index_slot(
    monkeypatch, operation_name
):
    connection = FakeConnection()
    events = configure_lifecycle(monkeypatch, released_count=1)

    result = getattr(service, operation_name)(
        connection, session_id="session-1"
    )

    assert ("release", "session-1") in events
    assert result.released_item_count == 1


@pytest.mark.parametrize("active_status", ["prepared", "open", "in_progress"])
def test_active_statuses_are_not_changed_without_lifecycle_call(
    active_status
):
    connection = FakeConnection()

    assert active_status in {"prepared", "open", "in_progress"}
    assert connection.transaction_events == []


def test_lifecycle_repository_never_writes_reviews():
    connection = LifecycleConnection()

    mark_review_session_completed(
        connection, review_session_id="session-1"
    )
    release_active_review_session_items(
        connection, review_session_id="session-1"
    )

    sql = " ".join(query for query, _ in connection.calls)
    assert "UPDATE review_sessions" in sql
    assert "UPDATE review_session_items" in sql
    assert "INSERT INTO reviews" not in sql
    assert "UPDATE reviews" not in sql
