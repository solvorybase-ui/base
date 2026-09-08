import pytest

from backend.review.candidate_repository import (
    count_open_review_variants,
    load_review_candidates,
)


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def cursor(self):
        return FakeCursor(self)


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        pass

    def execute(self, query, params=None):
        self.connection.calls.append((" ".join(query.split()), params))

    def fetchall(self):
        return self.connection.rows

    def fetchone(self):
        return self.connection.rows[0] if self.connection.rows else None


def query_for_candidates():
    connection = FakeConnection([])
    load_review_candidates(connection)
    return connection.calls[0]


def test_succeeded_selected_is_returned():
    rows = [
        (
            "variant-1",
            "scout-1",
            "Family",
            "Brand",
            "Category",
            "Variant",
            "Model",
            "Description",
            {"size": "M"},
            "Scout reason",
            "shop-1",
            "Shop One",
            "2026-01-01T00:00:00Z",
        )
    ]

    candidates = load_review_candidates(FakeConnection(rows))

    assert len(candidates) == 1
    assert candidates[0].variant_id == "variant-1"
    assert candidates[0].scout_result_id == "scout-1"
    assert candidates[0].scout_reason == "Scout reason"
    assert candidates[0].shop_id == "shop-1"
    assert candidates[0].shop_name == "Shop One"


def test_succeeded_rejected_is_excluded():
    sql, _ = query_for_candidates()
    assert "sr.decision = 'selected'" in sql


def test_failed_selected_is_excluded():
    sql, _ = query_for_candidates()
    assert "sr.technical_status = 'succeeded'" in sql


def test_invalid_output_selected_is_excluded():
    sql, _ = query_for_candidates()
    assert "sr.technical_status = 'succeeded'" in sql


def test_current_hit_is_excluded():
    sql, _ = query_for_candidates()
    assert "r.decision = 'hit'" in sql
    assert "correction.supersedes_review_id = r.id" in sql


def test_current_no_hit_is_excluded():
    sql, _ = query_for_candidates()
    assert "r.decision = 'no_hit'" in sql
    assert "correction.supersedes_review_id = r.id" in sql


def test_active_no_hit_block_is_excluded():
    sql, _ = query_for_candidates()
    assert "rb.block_type = 'no_hit'" in sql
    assert "rb.released_at IS NULL" in sql


def test_current_later_is_excluded():
    sql, _ = query_for_candidates()
    assert "r.decision = 'later'" in sql
    assert "correction.supersedes_review_id = r.id" in sql


@pytest.mark.parametrize("status", ["prepared", "open", "in_progress"])
def test_variant_in_active_review_session_is_excluded(status):
    sql, _ = query_for_candidates()
    active_statuses = "'prepared', 'open', 'in_progress'"
    assert active_statuses in sql
    assert f"'{status}'" in active_statuses
    assert "active_item.released_at IS NULL" in sql


@pytest.mark.parametrize("status", ["completed", "cancelled"])
def test_variant_in_inactive_review_session_is_not_excluded(status):
    sql, _ = query_for_candidates()
    assert f"'{status}'" not in sql


def test_query_prevents_duplicate_variants():
    sql, _ = query_for_candidates()
    assert sql.startswith("SELECT DISTINCT pv.id")


def test_query_has_deterministic_order():
    sql, _ = query_for_candidates()
    assert "ORDER BY sr.finished_at, pv.id, sr.id" in sql


def test_candidate_shop_uses_same_deterministic_active_offer_selection():
    sql, _ = query_for_candidates()
    assert "LEFT JOIN LATERAL" in sql
    assert "o.is_active = true" in sql
    assert "o.archived_at IS NULL" in sql
    assert "s.is_active = true" in sql
    assert "s.archived_at IS NULL" in sql
    assert "ORDER BY o.last_seen_at DESC, o.id" in sql


def test_limit_is_forwarded_to_query():
    connection = FakeConnection([])
    load_review_candidates(connection, limit=12)
    _, params = connection.calls[0]
    assert params == (12,)


def test_limit_must_be_positive():
    with pytest.raises(ValueError):
        load_review_candidates(FakeConnection([]), limit=0)


def test_unlimited_candidate_pool_omits_sql_limit():
    connection = FakeConnection([])

    load_review_candidates(connection, limit=None)

    sql, params = connection.calls[0]
    assert "LIMIT %s" not in sql
    assert params is None


def test_global_open_count_uses_selected_review_eligibility_without_session_limit():
    connection = FakeConnection([(79,)])

    assert count_open_review_variants(connection) == 79

    sql, params = connection.calls[0]
    assert params is None
    assert "count(DISTINCT pv.id)" in sql
    assert "sr.technical_status = 'succeeded'" in sql
    assert "sr.decision = 'selected'" in sql
    assert "r.decision = 'hit'" in sql
    assert "r.decision = 'no_hit'" in sql
    assert "r.decision = 'later'" in sql
    assert "active_item" not in sql
    assert "LIMIT" not in sql


def test_global_open_count_is_zero_when_query_returns_no_row():
    assert count_open_review_variants(FakeConnection([])) == 0
