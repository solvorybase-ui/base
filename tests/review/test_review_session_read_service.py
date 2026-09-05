from decimal import Decimal

import backend.review.session_read_service as service
from backend.review.session_read_repository import (
    ReviewSessionItemProjection,
    ReviewSessionProjection,
    find_active_session_with_open_items,
    find_fully_decided_active_session_ids,
    load_review_session_projection,
    lock_open_review_item,
)


def item(*, item_id="item-1", position=1, decision=None, images=("one.jpg",)):
    return ReviewSessionItemProjection(
        review_session_item_id=item_id,
        position=position,
        product_variant_id=f"variant-{position}",
        family_name="Family",
        variant_name="Variant",
        brand_name="Brand",
        category="Category",
        description="Description",
        scout_reason="Scout reason",
        current_decision=decision,
        image_urls=images,
        shop_name="Shop",
        price=Decimal("12.50"),
        currency="EUR",
        offer_name="Offer",
        product_url="https://example.test/product",
        availability="in_stock",
    )


class QueueCursor:
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
        self.result = self.connection.results.pop(0)

    def fetchone(self):
        if isinstance(self.result, list):
            return self.result[0] if self.result else None
        return self.result

    def fetchall(self):
        return self.result


class QueueConnection:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def cursor(self):
        return QueueCursor(self)


def projection_row(*, images=("primary.jpg", "second.jpg"), decision=None, offer=True):
    offer_values = (
        "Shop",
        Decimal("19.99"),
        "EUR",
        "Offer title",
        "https://example.test/product",
        "in_stock",
    ) if offer else (None, None, None, None, None, None)
    return (
        "item-1", 1, "variant-1", "Family", "Variant", "Brand",
        "Category", "Description", "Scout reason", decision, images,
        *offer_values,
    )


def test_session_and_items_are_loaded_with_all_ui_data():
    connection = QueueConnection(("session-1", "prepared"), [projection_row()])

    result = load_review_session_projection(connection, session_id="session-1")

    assert result.session_id == "session-1"
    assert result.status == "prepared"
    assert result.item_count == 1
    assert result.items[0].shop_name == "Shop"
    assert result.items[0].price == Decimal("19.99")


def test_images_keep_repository_order():
    connection = QueueConnection(
        ("session-1", "prepared"),
        [projection_row(images=("primary.jpg", "position-2.jpg"))],
    )
    result = load_review_session_projection(connection, session_id="session-1")
    assert result.items[0].image_urls == ("primary.jpg", "position-2.jpg")
    sql = connection.calls[1][0]
    assert "pi.is_primary DESC, pi.position, pi.id" in sql


def test_missing_image_is_supported():
    connection = QueueConnection(("session-1", "prepared"), [projection_row(images=())])
    result = load_review_session_projection(connection, session_id="session-1")
    assert result.items[0].image_urls == ()


def test_missing_offer_is_supported():
    connection = QueueConnection(("session-1", "prepared"), [projection_row(offer=False)])
    result = load_review_session_projection(connection, session_id="session-1")
    assert result.items[0].shop_name is None
    assert result.items[0].price is None
    assert result.items[0].product_url is None


def test_offer_selection_is_deterministic_and_active():
    connection = QueueConnection(("session-1", "prepared"), [projection_row()])
    load_review_session_projection(connection, session_id="session-1")
    sql = connection.calls[1][0]
    assert "o.is_active = true" in sql
    assert "o.archived_at IS NULL" in sql
    assert "ORDER BY o.last_seen_at DESC, o.id" in sql


def test_next_open_skips_decided_items(monkeypatch):
    session = ReviewSessionProjection(
        "session-1", "prepared", 2,
        (item(item_id="done", decision="hit"), item(item_id="open", position=2)),
    )
    monkeypatch.setattr(service, "find_active_session_with_open_items", lambda c: "session-1")
    monkeypatch.setattr(service, "load_review_session_projection", lambda c, *, session_id: session)

    result = service.load_next_open_review_item(object())
    assert result[1].review_session_item_id == "open"


def test_no_active_session_returns_no_next_item(monkeypatch):
    monkeypatch.setattr(service, "find_active_session_with_open_items", lambda c: None)
    assert service.load_next_open_review_item(object()) is None


def test_active_session_query_is_deterministic_and_only_open_items():
    connection = QueueConnection(("session-1",))
    assert find_active_session_with_open_items(connection) == "session-1"
    sql, _ = connection.calls[0]
    assert "'prepared', 'open', 'in_progress'" in sql
    assert "correction.supersedes_review_id = r.id" in sql
    assert "ORDER BY rs.created_at, rs.id" in sql


def test_fully_decided_sessions_are_deterministic():
    connection = QueueConnection([("session-1",), ("session-2",)])
    assert find_fully_decided_active_session_ids(connection) == ["session-1", "session-2"]
    sql, _ = connection.calls[0]
    assert "AND NOT EXISTS" in sql
    assert "ORDER BY rs.created_at, rs.id" in sql


def test_item_lock_uses_database_row_lock():
    connection = QueueConnection(("item-1", "session-1"))
    locked = lock_open_review_item(connection, review_session_item_id="item-1")
    sql, params = connection.calls[0]
    assert "FOR UPDATE OF rsi" in sql
    assert "rsi.released_at IS NULL" in sql
    assert locked.review_session_id == "session-1"
    assert params == ("item-1",)
