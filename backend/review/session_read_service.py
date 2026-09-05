"""Read-only Review Session projection services."""

from __future__ import annotations

from .session_read_repository import (
    ConnectionLike,
    ReviewSessionItemProjection,
    ReviewSessionProjection,
    find_active_session_with_open_items,
    load_review_session_projection,
)


def load_review_session(
    connection: ConnectionLike, *, session_id: str
) -> ReviewSessionProjection:
    """Return one ordered Review Session projection for the UI."""
    return load_review_session_projection(connection, session_id=session_id)


def load_next_open_review_item(
    connection: ConnectionLike,
) -> tuple[ReviewSessionProjection, ReviewSessionItemProjection] | None:
    """Return the deterministic next undecided item in the oldest session."""
    session_id = find_active_session_with_open_items(connection)
    if session_id is None:
        return None
    session = load_review_session_projection(connection, session_id=session_id)
    item = next(
        (item for item in session.items if item.current_decision is None),
        None,
    )
    if item is None:
        return None
    return session, item
