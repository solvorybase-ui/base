import pytest

from backend.review.decision_repository import (
    ActiveReviewBlockRef,
    CurrentReviewRef,
    ReviewSessionItemRef,
    create_no_hit_block,
    create_review,
    release_no_hit_block,
)
import backend.review.decision_service as service


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


def configure_service(
    monkeypatch,
    *,
    current=None,
    active_block=None,
    block_insert_error=None,
    block_release_error=None,
    item_exists=True,
):
    events = []

    def fake_item(connection, *, review_session_item_id):
        events.append(("get_item", review_session_item_id))
        if not item_exists:
            raise LookupError("review session item does not exist")
        return ReviewSessionItemRef(review_session_item_id, "variant-1")

    def fake_current(connection, *, review_session_item_id):
        events.append(("get_current", review_session_item_id))
        return current

    def fake_active_block(connection, *, product_variant_id):
        events.append(("get_block", product_variant_id))
        return active_block

    def fake_create_review(connection, **kwargs):
        events.append(("create_review", kwargs))
        return "review-new"

    def fake_create_block(connection, **kwargs):
        events.append(("create_block", kwargs))
        if block_insert_error:
            raise block_insert_error
        return "block-new"

    def fake_release_block(connection, **kwargs):
        events.append(("release_block", kwargs))
        if block_release_error:
            raise block_release_error

    monkeypatch.setattr(service, "get_review_session_item", fake_item)
    monkeypatch.setattr(service, "get_current_review", fake_current)
    monkeypatch.setattr(service, "get_active_no_hit_block", fake_active_block)
    monkeypatch.setattr(service, "create_review", fake_create_review)
    monkeypatch.setattr(service, "create_no_hit_block", fake_create_block)
    monkeypatch.setattr(service, "release_no_hit_block", fake_release_block)
    return events


@pytest.mark.parametrize("decision", ["hit", "later", "no_hit"])
def test_normal_decision_succeeds(monkeypatch, decision):
    connection = FakeConnection()
    events = configure_service(monkeypatch)

    result = service.record_review_decision(
        connection,
        review_session_item_id="item-1",
        decision=decision,
        decided_by_user_ref="user-1",
    )

    assert result.decision == decision
    assert result.product_variant_id == "variant-1"
    assert connection.transaction_events == ["begin", "commit"]
    assert any(event[0] == "create_review" for event in events)


def test_invalid_decision_is_rejected():
    with pytest.raises(ValueError, match="decision must"):
        service.record_review_decision(
            FakeConnection(),
            review_session_item_id="item-1",
            decision="maybe",
            decided_by_user_ref="user-1",
        )


def test_empty_user_reference_is_rejected():
    with pytest.raises(ValueError, match="decided_by_user_ref"):
        service.record_review_decision(
            FakeConnection(),
            review_session_item_id="item-1",
            decision="hit",
            decided_by_user_ref="  ",
        )


def test_unknown_session_item_is_rejected_and_rolled_back(monkeypatch):
    connection = FakeConnection()
    configure_service(monkeypatch, item_exists=False)

    with pytest.raises(LookupError, match="does not exist"):
        service.record_review_decision(
            connection,
            review_session_item_id="missing",
            decision="hit",
            decided_by_user_ref="user-1",
        )

    assert connection.transaction_events == ["begin", "rollback"]


def test_correction_appends_review_and_supersedes_current(monkeypatch):
    connection = FakeConnection()
    events = configure_service(
        monkeypatch, current=CurrentReviewRef("review-old", "later")
    )

    result = service.record_review_decision(
        connection,
        review_session_item_id="item-1",
        decision="hit",
        decided_by_user_ref="user-1",
        reason="Corrected after human review",
    )

    create_event = next(event for event in events if event[0] == "create_review")
    assert create_event[1]["supersedes_review_id"] == "review-old"
    assert create_event[1]["correction_reason"] == "Corrected after human review"
    assert result.supersedes_review_id == "review-old"


def test_correction_requires_reason_due_to_schema(monkeypatch):
    configure_service(
        monkeypatch, current=CurrentReviewRef("review-old", "later")
    )

    with pytest.raises(ValueError, match="reason is required"):
        service.record_review_decision(
            FakeConnection(),
            review_session_item_id="item-1",
            decision="hit",
            decided_by_user_ref="user-1",
        )


def test_no_hit_creates_block_referencing_new_review(monkeypatch):
    connection = FakeConnection()
    events = configure_service(monkeypatch)

    service.record_review_decision(
        connection,
        review_session_item_id="item-1",
        decision="no_hit",
        decided_by_user_ref="user-1",
    )

    block_event = next(event for event in events if event[0] == "create_block")
    assert block_event[1] == {
        "product_variant_id": "variant-1",
        "review_session_item_id": "item-1",
        "origin_review_id": "review-new",
    }


def test_block_insert_error_rolls_back_review(monkeypatch):
    connection = FakeConnection()
    configure_service(
        monkeypatch,
        block_insert_error=RuntimeError("block insert failed"),
    )

    with pytest.raises(RuntimeError, match="block insert failed"):
        service.record_review_decision(
            connection,
            review_session_item_id="item-1",
            decision="no_hit",
            decided_by_user_ref="user-1",
        )

    assert connection.transaction_events == ["begin", "rollback"]


def test_duplicate_active_no_hit_block_is_rejected(monkeypatch):
    connection = FakeConnection()
    events = configure_service(
        monkeypatch,
        active_block=ActiveReviewBlockRef("block-1", "review-old"),
    )

    with pytest.raises(ValueError, match="already exists"):
        service.record_review_decision(
            connection,
            review_session_item_id="item-1",
            decision="no_hit",
            decided_by_user_ref="user-1",
        )

    assert not any(event[0] == "create_review" for event in events)
    assert connection.transaction_events == ["begin", "rollback"]


@pytest.mark.parametrize("decision", ["hit", "later"])
def test_hit_and_later_create_no_block(monkeypatch, decision):
    events = configure_service(monkeypatch)

    service.record_review_decision(
        FakeConnection(),
        review_session_item_id="item-1",
        decision=decision,
        decided_by_user_ref="user-1",
    )

    assert not any(event[0] == "create_block" for event in events)


@pytest.mark.parametrize("new_decision", ["hit", "later"])
def test_admin_override_succeeds_and_appends_review(monkeypatch, new_decision):
    connection = FakeConnection()
    events = configure_service(
        monkeypatch,
        current=CurrentReviewRef("review-no-hit", "no_hit"),
        active_block=ActiveReviewBlockRef("block-1", "review-no-hit"),
    )

    result = service.override_no_hit_decision(
        connection,
        review_session_item_id="item-1",
        new_decision=new_decision,
        decided_by_user_ref="admin-1",
        reason="Administrative exception",
    )

    create_event = next(event for event in events if event[0] == "create_review")
    release_event = next(event for event in events if event[0] == "release_block")
    assert create_event[1]["supersedes_review_id"] == "review-no-hit"
    assert create_event[1]["decision"] == new_decision
    assert release_event[1] == {
        "review_block_id": "block-1",
        "released_by_user_ref": "admin-1",
        "release_reason": "Administrative exception",
    }
    assert result.supersedes_review_id == "review-no-hit"
    assert connection.transaction_events == ["begin", "commit"]


@pytest.mark.parametrize("new_decision", ["hit", "later"])
def test_admin_override_without_reason_is_rejected(new_decision):
    with pytest.raises(ValueError, match="reason"):
        service.override_no_hit_decision(
            FakeConnection(),
            review_session_item_id="item-1",
            new_decision=new_decision,
            decided_by_user_ref="admin-1",
            reason="  ",
        )


def test_admin_override_requires_active_block(monkeypatch):
    connection = FakeConnection()
    configure_service(
        monkeypatch,
        current=CurrentReviewRef("review-no-hit", "no_hit"),
    )

    with pytest.raises(ValueError, match="block is required"):
        service.override_no_hit_decision(
            connection,
            review_session_item_id="item-1",
            new_decision="hit",
            decided_by_user_ref="admin-1",
            reason="Administrative exception",
        )


@pytest.mark.parametrize("current_decision", [None, "hit", "later"])
def test_admin_override_requires_current_no_hit(monkeypatch, current_decision):
    current = (
        None
        if current_decision is None
        else CurrentReviewRef("review-current", current_decision)
    )
    configure_service(monkeypatch, current=current)

    with pytest.raises(ValueError, match="current decision must be no_hit"):
        service.override_no_hit_decision(
            FakeConnection(),
            review_session_item_id="item-1",
            new_decision="hit",
            decided_by_user_ref="admin-1",
            reason="Administrative exception",
        )


@pytest.mark.parametrize("new_decision", ["no_hit", "maybe"])
def test_admin_override_rejects_other_decisions(new_decision):
    with pytest.raises(ValueError, match="new_decision"):
        service.override_no_hit_decision(
            FakeConnection(),
            review_session_item_id="item-1",
            new_decision=new_decision,
            decided_by_user_ref="admin-1",
            reason="Administrative exception",
        )


def test_block_release_error_rolls_back_new_review(monkeypatch):
    connection = FakeConnection()
    configure_service(
        monkeypatch,
        current=CurrentReviewRef("review-no-hit", "no_hit"),
        active_block=ActiveReviewBlockRef("block-1", "review-no-hit"),
        block_release_error=RuntimeError("block release failed"),
    )

    with pytest.raises(RuntimeError, match="block release failed"):
        service.override_no_hit_decision(
            connection,
            review_session_item_id="item-1",
            new_decision="hit",
            decided_by_user_ref="admin-1",
            reason="Administrative exception",
        )

    assert connection.transaction_events == ["begin", "rollback"]


def test_normal_api_cannot_replace_current_no_hit(monkeypatch):
    configure_service(
        monkeypatch, current=CurrentReviewRef("review-no-hit", "no_hit")
    )

    with pytest.raises(ValueError, match="administrative override"):
        service.record_review_decision(
            FakeConnection(),
            review_session_item_id="item-1",
            decision="hit",
            decided_by_user_ref="user-1",
            reason="Not administrative",
        )


class RecordingCursor:
    def __init__(self, connection):
        self.connection = connection
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        pass

    def execute(self, query, params=None):
        sql = " ".join(query.split())
        self.connection.calls.append((sql, params))
        if "INSERT INTO reviews" in sql:
            self.result = ("review-1",)
        elif "INSERT INTO review_blocks" in sql:
            self.result = ("block-1",)
        elif "UPDATE review_blocks" in sql:
            self.result = ("block-1",)

    def fetchone(self):
        return self.result


class RecordingConnection:
    def __init__(self):
        self.calls = []

    def cursor(self):
        return RecordingCursor(self)


def test_repository_appends_history_without_review_update_or_delete():
    connection = RecordingConnection()

    create_review(
        connection,
        review_session_item_id="item-1",
        decision="hit",
        decided_by_user_ref="user-1",
        reason="Correction",
        supersedes_review_id="review-old",
        correction_reason="Correction",
    )

    sql = " ".join(query for query, _ in connection.calls)
    assert "INSERT INTO reviews" in sql
    assert "UPDATE reviews" not in sql
    assert "DELETE FROM reviews" not in sql


def test_no_hit_block_schema_fields_are_used():
    connection = RecordingConnection()

    create_no_hit_block(
        connection,
        product_variant_id="variant-1",
        review_session_item_id="item-1",
        origin_review_id="review-1",
    )

    sql, params = connection.calls[0]
    assert "origin_review_id" in sql
    assert "block_type" in sql
    assert "'no_hit'" in sql
    assert params == ("variant-1", "item-1", "review-1")


def test_block_release_preserves_row_and_stores_audit_fields():
    connection = RecordingConnection()

    release_no_hit_block(
        connection,
        review_block_id="block-1",
        released_by_user_ref="admin-1",
        release_reason="Administrative exception",
    )

    sql, params = connection.calls[0]
    assert "UPDATE review_blocks" in sql
    assert "DELETE" not in sql
    assert "released_at = now()" in sql
    assert "released_by_user_ref = %s" in sql
    assert "release_reason = %s" in sql
    assert "released_at IS NULL" in sql
    assert params == ("admin-1", "Administrative exception", "block-1")


def test_repository_does_not_mutate_other_domains():
    connection = RecordingConnection()

    create_review(
        connection,
        review_session_item_id="item-1",
        decision="later",
        decided_by_user_ref="user-1",
        reason=None,
        supersedes_review_id=None,
        correction_reason=None,
    )

    sql = " ".join(query for query, _ in connection.calls)
    assert "scout_results" not in sql
    assert "product_variants" not in sql
    assert "DELETE FROM review_session_items" not in sql
    assert "evaluator" not in sql
