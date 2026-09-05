"""Read-only persistence queries for Review Session UI projections."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, Sequence


ACTIVE_SESSION_STATUSES = ("prepared", "open", "in_progress")


class CursorLike(Protocol):
    def __enter__(self): ...
    def __exit__(self, exc_type, exc, tb): ...
    def execute(
        self, query: str, params: Sequence[object] | None = None
    ) -> Any: ...
    def fetchone(self) -> Sequence[object] | None: ...
    def fetchall(self) -> list[Sequence[object]]: ...


class ConnectionLike(Protocol):
    def cursor(self) -> CursorLike: ...


@dataclass(frozen=True, slots=True)
class ReviewSessionItemProjection:
    review_session_item_id: str
    position: int
    product_variant_id: str
    family_name: str
    variant_name: str
    brand_name: str | None
    category: str | None
    description: str | None
    scout_reason: str
    current_decision: str | None
    image_urls: tuple[str, ...]
    shop_name: str | None
    price: Decimal | None
    currency: str | None
    offer_name: str | None
    product_url: str | None
    availability: str | None


@dataclass(frozen=True, slots=True)
class ReviewSessionProjection:
    session_id: str
    status: str
    item_count: int
    items: tuple[ReviewSessionItemProjection, ...]


@dataclass(frozen=True, slots=True)
class LockedReviewItem:
    review_session_item_id: str
    review_session_id: str


_SESSION_ITEMS_SQL = """
    SELECT rsi.id,
           rsi.position,
           rsi.product_variant_id,
           pf.name,
           pv.name,
           pf.brand_name,
           pf.category,
           COALESCE(pv.description, pf.description),
           sr.reason,
           current_review.decision,
           COALESCE(images.urls, ARRAY[]::text[]),
           selected_offer.shop_name,
           selected_offer.current_price,
           selected_offer.currency_code,
           selected_offer.shop_title,
           selected_offer.product_url,
           selected_offer.availability_status
    FROM review_session_items rsi
    JOIN product_variants pv ON pv.id = rsi.product_variant_id
    JOIN product_families pf ON pf.id = pv.product_family_id
    JOIN scout_results sr ON sr.id = rsi.scout_result_id
    LEFT JOIN LATERAL (
        SELECT r.decision
        FROM reviews r
        WHERE r.review_session_item_id = rsi.id
          AND NOT EXISTS (
              SELECT 1
              FROM reviews correction
              WHERE correction.supersedes_review_id = r.id
          )
        ORDER BY r.decided_at DESC, r.id DESC
        LIMIT 1
    ) current_review ON true
    LEFT JOIN LATERAL (
        SELECT o.id,
               s.name AS shop_name,
               o.current_price,
               o.currency_code,
               o.shop_title,
               o.product_url,
               o.availability_status
        FROM offers o
        JOIN shops s ON s.id = o.shop_id
        WHERE o.product_variant_id = rsi.product_variant_id
          AND o.is_active = true
          AND o.archived_at IS NULL
          AND s.is_active = true
          AND s.archived_at IS NULL
        ORDER BY o.last_seen_at DESC, o.id
        LIMIT 1
    ) selected_offer ON true
    LEFT JOIN LATERAL (
        SELECT array_agg(
                   pi.external_url
                   ORDER BY pi.is_primary DESC, pi.position, pi.id
               ) AS urls
        FROM product_images pi
        WHERE pi.offer_id = selected_offer.id
          AND pi.is_active = true
          AND pi.archived_at IS NULL
          AND pi.usability_status <> 'unusable'
    ) images ON true
    WHERE rsi.review_session_id = %s
    ORDER BY rsi.position, rsi.id
"""


def _item_from_row(row: Sequence[object]) -> ReviewSessionItemProjection:
    raw_images = row[10] or ()
    return ReviewSessionItemProjection(
        review_session_item_id=str(row[0]),
        position=int(row[1]),
        product_variant_id=str(row[2]),
        family_name=str(row[3]),
        variant_name=str(row[4]),
        brand_name=None if row[5] is None else str(row[5]),
        category=None if row[6] is None else str(row[6]),
        description=None if row[7] is None else str(row[7]),
        scout_reason=str(row[8]),
        current_decision=None if row[9] is None else str(row[9]),
        image_urls=tuple(str(url) for url in raw_images),
        shop_name=None if row[11] is None else str(row[11]),
        price=None if row[12] is None else Decimal(row[12]),
        currency=None if row[13] is None else str(row[13]),
        offer_name=None if row[14] is None else str(row[14]),
        product_url=None if row[15] is None else str(row[15]),
        availability=None if row[16] is None else str(row[16]),
    )


def find_active_session_with_open_items(
    connection: ConnectionLike,
) -> str | None:
    """Find the oldest active session that still contains an open item."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT rs.id
            FROM review_sessions rs
            WHERE rs.status IN ('prepared', 'open', 'in_progress')
              AND rs.archived_at IS NULL
              AND EXISTS (
                  SELECT 1
                  FROM review_session_items rsi
                  WHERE rsi.review_session_id = rs.id
                    AND rsi.released_at IS NULL
                    AND NOT EXISTS (
                        SELECT 1
                        FROM reviews r
                        WHERE r.review_session_item_id = rsi.id
                          AND NOT EXISTS (
                              SELECT 1
                              FROM reviews correction
                              WHERE correction.supersedes_review_id = r.id
                          )
                    )
              )
            ORDER BY rs.created_at, rs.id
            LIMIT 1
            """
        )
        row = cursor.fetchone()
    return None if row is None else str(row[0])


def load_review_session_projection(
    connection: ConnectionLike, *, session_id: str
) -> ReviewSessionProjection:
    """Load one Review Session and all ordered UI item data."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, status
            FROM review_sessions
            WHERE id = %s
              AND archived_at IS NULL
            """,
            (session_id,),
        )
        session_row = cursor.fetchone()
        if session_row is None:
            raise LookupError("review session does not exist")
        cursor.execute(_SESSION_ITEMS_SQL, (session_id,))
        rows = cursor.fetchall()

    items = tuple(_item_from_row(row) for row in rows)
    return ReviewSessionProjection(
        session_id=str(session_row[0]),
        status=str(session_row[1]),
        item_count=len(items),
        items=items,
    )


def find_fully_decided_active_session_ids(
    connection: ConnectionLike,
) -> list[str]:
    """Return active non-empty sessions with no remaining undecided items."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT rs.id
            FROM review_sessions rs
            WHERE rs.status IN ('prepared', 'open', 'in_progress')
              AND rs.archived_at IS NULL
              AND EXISTS (
                  SELECT 1
                  FROM review_session_items any_item
                  WHERE any_item.review_session_id = rs.id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM review_session_items rsi
                  WHERE rsi.review_session_id = rs.id
                    AND rsi.released_at IS NULL
                    AND NOT EXISTS (
                        SELECT 1
                        FROM reviews r
                        WHERE r.review_session_item_id = rsi.id
                          AND NOT EXISTS (
                              SELECT 1
                              FROM reviews correction
                              WHERE correction.supersedes_review_id = r.id
                          )
                    )
              )
            ORDER BY rs.created_at, rs.id
            """
        )
        rows = cursor.fetchall()
    return [str(row[0]) for row in rows]


def lock_open_review_item(
    connection: ConnectionLike, *, review_session_item_id: str
) -> LockedReviewItem | None:
    """Lock an active item so stale checks and decision writes serialize."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT rsi.id, rsi.review_session_id
            FROM review_session_items rsi
            JOIN review_sessions rs ON rs.id = rsi.review_session_id
            WHERE rsi.id = %s
              AND rsi.released_at IS NULL
              AND rs.archived_at IS NULL
              AND rs.status IN ('prepared', 'open', 'in_progress')
            FOR UPDATE OF rsi
            """,
            (review_session_item_id,),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return LockedReviewItem(
        review_session_item_id=str(row[0]),
        review_session_id=str(row[1]),
    )
