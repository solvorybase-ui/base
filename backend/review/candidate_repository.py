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


def load_review_candidates(
    connection: ConnectionLike, *, limit: int = 30
) -> list[ReviewCandidate]:
    """Return deterministically ordered Product Variants eligible for review."""
    if limit <= 0:
        raise ValueError("limit must be greater than zero")

    with connection.cursor() as cursor:
        cursor.execute(
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
                   sr.finished_at
            FROM product_variants pv
            JOIN product_families pf
              ON pf.id = pv.product_family_id
            JOIN scout_results sr
              ON sr.product_variant_id = pv.id
             AND sr.technical_status = 'succeeded'
             AND sr.decision = 'selected'
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
            ORDER BY sr.finished_at, pv.id, sr.id
            LIMIT %s
            """,
            (limit,),
        )
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
        )
        for row in rows
    ]
