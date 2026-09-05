"""Persistence primitives for Review Sessions and their items."""

from __future__ import annotations

from typing import Any, Protocol, Sequence


class CursorLike(Protocol):
    rowcount: int

    def __enter__(self): ...
    def __exit__(self, exc_type, exc, tb): ...
    def execute(
        self, query: str, params: Sequence[object] | None = None
    ) -> Any: ...
    def fetchone(self) -> Sequence[object] | None: ...


class ConnectionLike(Protocol):
    def cursor(self) -> CursorLike: ...


def create_prepared_review_session(
    connection: ConnectionLike,
    *,
    diversity_context: str,
) -> str:
    """Create a prepared Review Session and return its identifier."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO review_sessions (status, diversity_context)
            VALUES ('prepared', %s)
            RETURNING id
            """,
            (diversity_context,),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("review session INSERT returned no id")
    return str(row[0])


def add_review_session_item(
    connection: ConnectionLike,
    *,
    review_session_id: str,
    product_variant_id: str,
    scout_result_id: str,
    position: int,
) -> None:
    """Add one eligible candidate at its stable position in a session."""
    if position <= 0:
        raise ValueError("position must be greater than zero")
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO review_session_items (
                review_session_id,
                product_variant_id,
                scout_result_id,
                position
            )
            VALUES (%s, %s, %s, %s)
            """,
            (
                review_session_id,
                product_variant_id,
                scout_result_id,
                position,
            ),
        )


def mark_review_session_completed(
    connection: ConnectionLike,
    *,
    review_session_id: str,
) -> None:
    """Mark one existing Review Session as completed."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE review_sessions
            SET status = 'completed',
                completed_at = now(),
                cancelled_at = NULL,
                updated_at = now()
            WHERE id = %s
            RETURNING id
            """,
            (review_session_id,),
        )
        row = cursor.fetchone()
    if row is None:
        raise LookupError("review session does not exist")


def mark_review_session_cancelled(
    connection: ConnectionLike,
    *,
    review_session_id: str,
) -> None:
    """Mark one existing Review Session as cancelled."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE review_sessions
            SET status = 'cancelled',
                cancelled_at = now(),
                completed_at = NULL,
                updated_at = now()
            WHERE id = %s
            RETURNING id
            """,
            (review_session_id,),
        )
        row = cursor.fetchone()
    if row is None:
        raise LookupError("review session does not exist")


def release_active_review_session_items(
    connection: ConnectionLike,
    *,
    review_session_id: str,
) -> int:
    """Release only currently active items belonging to one Review Session."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE review_session_items
            SET released_at = now()
            WHERE review_session_id = %s
              AND released_at IS NULL
            """,
            (review_session_id,),
        )
        return cursor.rowcount
