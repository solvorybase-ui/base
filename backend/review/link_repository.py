"""Persistence primitives for hashed, revocable Review Link identities."""

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
class ReviewLinkRecord:
    id: str
    token_hash: str


def create_review_link_record(
    connection: ConnectionLike, *, token_hash: str
) -> ReviewLinkRecord:
    """Persist only a token hash and return its stable record identity."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO review_links (token_hash)
            VALUES (%s)
            RETURNING id, token_hash
            """,
            (token_hash,),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("review link INSERT returned no id")
    return ReviewLinkRecord(id=str(row[0]), token_hash=str(row[1]))


def find_active_review_link_by_hash(
    connection: ConnectionLike, *, token_hash: str
) -> ReviewLinkRecord | None:
    """Return the matching non-revoked Review Link, if one exists."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, token_hash
            FROM review_links
            WHERE token_hash = %s
              AND revoked_at IS NULL
            """,
            (token_hash,),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return ReviewLinkRecord(id=str(row[0]), token_hash=str(row[1]))


def find_active_review_link_by_id(
    connection: ConnectionLike, *, token_record_id: str
) -> ReviewLinkRecord | None:
    """Return a non-revoked Review Link by its non-secret stable id."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, token_hash
            FROM review_links
            WHERE id = %s
              AND revoked_at IS NULL
            """,
            (token_record_id,),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return ReviewLinkRecord(id=str(row[0]), token_hash=str(row[1]))


def revoke_review_link_record(
    connection: ConnectionLike, *, token_record_id: str
) -> bool:
    """Revoke an active Review Link without deleting its identity."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE review_links
            SET revoked_at = now()
            WHERE id = %s
              AND revoked_at IS NULL
            RETURNING id
            """,
            (token_record_id,),
        )
        return cursor.fetchone() is not None
