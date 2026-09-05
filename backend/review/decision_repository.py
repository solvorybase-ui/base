"""Persistence primitives for append-only Human Review decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence


class CursorLike(Protocol):
    def __enter__(self): ...
    def __exit__(self, exc_type, exc, tb): ...
    def execute(
        self, query: str, params: Sequence[object] | None = None
    ) -> Any: ...
    def fetchone(self) -> Sequence[object] | None: ...


class ConnectionLike(Protocol):
    def cursor(self) -> CursorLike: ...


@dataclass(frozen=True, slots=True)
class ReviewSessionItemRef:
    id: str
    product_variant_id: str


@dataclass(frozen=True, slots=True)
class CurrentReviewRef:
    id: str
    decision: str


@dataclass(frozen=True, slots=True)
class ActiveReviewBlockRef:
    id: str
    origin_review_id: str


def get_review_session_item(
    connection: ConnectionLike, *, review_session_item_id: str
) -> ReviewSessionItemRef:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, product_variant_id
            FROM review_session_items
            WHERE id = %s
            """,
            (review_session_item_id,),
        )
        row = cursor.fetchone()
    if row is None:
        raise LookupError("review session item does not exist")
    return ReviewSessionItemRef(str(row[0]), str(row[1]))


def get_current_review(
    connection: ConnectionLike, *, review_session_item_id: str
) -> CurrentReviewRef | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT r.id, r.decision
            FROM reviews r
            WHERE r.review_session_item_id = %s
              AND NOT EXISTS (
                  SELECT 1
                  FROM reviews correction
                  WHERE correction.supersedes_review_id = r.id
              )
            ORDER BY r.decided_at DESC, r.id DESC
            LIMIT 1
            """,
            (review_session_item_id,),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return CurrentReviewRef(str(row[0]), str(row[1]))


def create_review(
    connection: ConnectionLike,
    *,
    review_session_item_id: str,
    decision: str,
    decided_by_user_ref: str,
    reason: str | None,
    supersedes_review_id: str | None,
    correction_reason: str | None,
) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO reviews (
                review_session_item_id,
                decision,
                reason,
                decided_by_user_ref,
                supersedes_review_id,
                correction_reason
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                review_session_item_id,
                decision,
                reason,
                decided_by_user_ref,
                supersedes_review_id,
                correction_reason,
            ),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("review INSERT returned no id")
    return str(row[0])


def get_active_no_hit_block(
    connection: ConnectionLike, *, product_variant_id: str
) -> ActiveReviewBlockRef | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, origin_review_id
            FROM review_blocks
            WHERE product_variant_id = %s
              AND block_type = 'no_hit'
              AND released_at IS NULL
            """,
            (product_variant_id,),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return ActiveReviewBlockRef(str(row[0]), str(row[1]))


def create_no_hit_block(
    connection: ConnectionLike,
    *,
    product_variant_id: str,
    review_session_item_id: str,
    origin_review_id: str,
) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO review_blocks (
                product_variant_id,
                review_session_item_id,
                origin_review_id,
                block_type
            )
            VALUES (%s, %s, %s, 'no_hit')
            RETURNING id
            """,
            (
                product_variant_id,
                review_session_item_id,
                origin_review_id,
            ),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("review block INSERT returned no id")
    return str(row[0])


def release_no_hit_block(
    connection: ConnectionLike,
    *,
    review_block_id: str,
    released_by_user_ref: str,
    release_reason: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE review_blocks
            SET released_at = now(),
                released_by_user_ref = %s,
                release_reason = %s,
                updated_at = now()
            WHERE id = %s
              AND block_type = 'no_hit'
              AND released_at IS NULL
            RETURNING id
            """,
            (
                released_by_user_ref,
                release_reason,
                review_block_id,
            ),
        )
        row = cursor.fetchone()
    if row is None:
        raise LookupError("active no-hit block does not exist")
