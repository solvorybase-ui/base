"""Read-only eligibility query for Human Review candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence


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
class ReviewCandidate:
    variant_id: str
    scout_result_id: str
    family_name: str
    brand_name: str | None
    category: str | None
    variant_name: str
    model_name: str | None
    description: str | None
    variant_attributes: dict[str, object] = field(default_factory=dict)
    scout_reason: str = ""
    shop_id: str | None = None
    shop_name: str | None = None


_ELIGIBLE_SCOUT_JOIN_SQL = """
            FROM product_variants pv
            JOIN product_families pf
              ON pf.id = pv.product_family_id
            JOIN scout_results sr
             ON sr.product_variant_id = pv.id
             AND sr.technical_status = 'succeeded'
             AND sr.decision = 'selected'
"""


_SELECTED_OFFER_SHOP_JOIN_SQL = """
            LEFT JOIN LATERAL (
                SELECT s.id AS shop_id,
                       s.name AS shop_name
                FROM offers o
                JOIN shops s ON s.id = o.shop_id
                WHERE o.product_variant_id = pv.id
                  AND o.is_active = true
                  AND o.archived_at IS NULL
                  AND s.is_active = true
                  AND s.archived_at IS NULL
                ORDER BY o.last_seen_at DESC, o.id
                LIMIT 1
            ) selected_offer ON true
"""


_OPEN_REVIEW_WHERE_SQL = """
            WHERE pv.is_active = true
              AND pv.archived_at IS NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM reviews r
                  JOIN review_session_items decided_item
                    ON decided_item.id = r.review_session_item_id
                  WHERE decided_item.product_variant_id = pv.id
                    AND r.decision = 'hit'
                    AND NOT EXISTS (
                        SELECT 1
                        FROM reviews correction
                        WHERE correction.supersedes_review_id = r.id
                    )
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM reviews r
                  JOIN review_session_items decided_item
                    ON decided_item.id = r.review_session_item_id
                  WHERE decided_item.product_variant_id = pv.id
                    AND r.decision = 'no_hit'
                    AND NOT EXISTS (
                        SELECT 1
                        FROM reviews correction
                        WHERE correction.supersedes_review_id = r.id
                    )
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM review_blocks rb
                  WHERE rb.product_variant_id = pv.id
                    AND rb.block_type = 'no_hit'
                    AND rb.released_at IS NULL
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM reviews r
                  JOIN review_session_items decided_item
                    ON decided_item.id = r.review_session_item_id
                  WHERE decided_item.product_variant_id = pv.id
                    AND r.decision = 'later'
                    AND NOT EXISTS (
                        SELECT 1
                        FROM reviews correction
                        WHERE correction.supersedes_review_id = r.id
                    )
              )
"""


_ACTIVE_SESSION_EXCLUSION_SQL = """
              AND NOT EXISTS (
                  SELECT 1
                  FROM review_session_items active_item
                  JOIN review_sessions active_session
                    ON active_session.id = active_item.review_session_id
                  WHERE active_item.product_variant_id = pv.id
                    AND active_item.released_at IS NULL
                    AND active_session.archived_at IS NULL
                    AND active_session.status IN (
                        'prepared', 'open', 'in_progress'
                    )
              )
"""


def count_open_review_variants(connection: ConnectionLike) -> int:
    """Count all unresolved succeeded/selected variants across sessions."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(DISTINCT pv.id)"
            + _ELIGIBLE_SCOUT_JOIN_SQL
            + _OPEN_REVIEW_WHERE_SQL
        )
        row = cursor.fetchone()
    return 0 if row is None else int(row[0])


def load_review_candidates(
    connection: ConnectionLike, *, limit: int | None = 30
) -> list[ReviewCandidate]:
    """Return deterministically ordered Product Variants eligible for review."""
    if limit is not None and limit <= 0:
        raise ValueError("limit must be greater than zero")

    query = (
        """
            SELECT DISTINCT
                   pv.id,
                   sr.id,
                   pf.name,
                   pf.brand_name,
                   pf.category,
                   pv.name,
                   pv.model_name,
                   pv.description,
                   pv.variant_attributes,
                   sr.reason,
                   selected_offer.shop_id,
                   selected_offer.shop_name,
                   sr.finished_at
        """
        + _ELIGIBLE_SCOUT_JOIN_SQL
        + _SELECTED_OFFER_SHOP_JOIN_SQL
        + _OPEN_REVIEW_WHERE_SQL
        + _ACTIVE_SESSION_EXCLUSION_SQL
        + (
            """
            ORDER BY sr.finished_at, pv.id, sr.id
            LIMIT %s
            """
            if limit is not None
            else """
            ORDER BY sr.finished_at, pv.id, sr.id
            """
        )
    )

    with connection.cursor() as cursor:
        cursor.execute(query, None if limit is None else (limit,))
        rows = cursor.fetchall()

    return [
        ReviewCandidate(
            variant_id=str(row[0]),
            scout_result_id=str(row[1]),
            family_name=str(row[2]),
            brand_name=None if row[3] is None else str(row[3]),
            category=None if row[4] is None else str(row[4]),
            variant_name=str(row[5]),
            model_name=None if row[6] is None else str(row[6]),
            description=None if row[7] is None else str(row[7]),
            variant_attributes=dict(row[8] or {}),
            scout_reason=str(row[9]),
            shop_id=None if row[10] is None else str(row[10]),
            shop_name=None if row[11] is None else str(row[11]),
        )
        for row in rows
    ]
