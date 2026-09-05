"""Continuous Human Review flow across internal Review Sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ContextManager, Protocol

from psycopg.errors import UniqueViolation

from .decision_repository import get_current_review
from .decision_service import ReviewDecisionResult, record_review_decision
from .session_read_repository import (
    ReviewSessionItemProjection,
    ReviewSessionProjection,
    find_fully_decided_active_session_ids,
    lock_open_review_item,
)
from .session_read_service import load_next_open_review_item
from .session_service import build_review_session, complete_review_session


class TransactionConnection(Protocol):
    def transaction(self) -> ContextManager[object]: ...


class StaleReviewItemError(ValueError):
    """Raised when a displayed item is no longer open for a new decision."""


@dataclass(frozen=True, slots=True)
class ContinuousReviewState:
    session: ReviewSessionProjection | None
    item: ReviewSessionItemProjection | None

    @property
    def is_empty(self) -> bool:
        return self.item is None


def _complete_finished_sessions(connection: TransactionConnection) -> None:
    for session_id in find_fully_decided_active_session_ids(connection):
        complete_review_session(connection, session_id=session_id)


def load_continuous_review(
    connection: TransactionConnection,
) -> ContinuousReviewState:
    """Continue an active queue, build the next one, or return empty state."""
    _complete_finished_sessions(connection)
    current = load_next_open_review_item(connection)
    if current is not None:
        return ContinuousReviewState(session=current[0], item=current[1])

    try:
        created = build_review_session(connection)
    except UniqueViolation:
        # A concurrent request may have won the active-item unique constraint.
        # Only absorb the failure if that request left a usable queue behind.
        current = load_next_open_review_item(connection)
        if current is None:
            raise
        return ContinuousReviewState(session=current[0], item=current[1])

    if created is None:
        return ContinuousReviewState(session=None, item=None)

    current = load_next_open_review_item(connection)
    if current is None:
        raise RuntimeError("new review session contains no open item")
    return ContinuousReviewState(session=current[0], item=current[1])


def record_continuous_review_decision(
    connection: TransactionConnection,
    *,
    review_session_item_id: str,
    decision: str,
    decided_by_user_ref: str,
) -> ReviewDecisionResult:
    """Atomically reject stale state and delegate the human decision write."""
    with connection.transaction():
        locked_item = lock_open_review_item(
            connection,
            review_session_item_id=review_session_item_id,
        )
        if locked_item is None:
            raise StaleReviewItemError("review item is no longer open")

        current = get_current_review(
            connection,
            review_session_item_id=review_session_item_id,
        )
        if current is not None:
            raise StaleReviewItemError("review item was already decided")

        result = record_review_decision(
            connection,
            review_session_item_id=review_session_item_id,
            decision=decision,
            decided_by_user_ref=decided_by_user_ref,
        )

    _complete_finished_sessions(connection)
    return result
