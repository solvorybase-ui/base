"""Atomic construction of prepared Human Review Sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ContextManager, Protocol

from .candidate_repository import ReviewCandidate, load_review_candidates
from .session_repository import (
    add_review_session_item,
    create_prepared_review_session,
    mark_review_session_cancelled,
    mark_review_session_completed,
    release_active_review_session_items,
)


DEFAULT_SESSION_SIZE = 20
DEFAULT_DIVERSITY_CONTEXT = "standard_queue_builder"


class TransactionConnection(Protocol):
    def transaction(self) -> ContextManager[object]: ...


@dataclass(frozen=True, slots=True)
class ReviewSessionBuildResult:
    session_id: str
    item_count: int


@dataclass(frozen=True, slots=True)
class ReviewSessionLifecycleResult:
    session_id: str
    released_item_count: int


def _unique_candidates(
    candidates: list[ReviewCandidate],
) -> list[ReviewCandidate]:
    unique: list[ReviewCandidate] = []
    seen_variant_ids: set[str] = set()
    for candidate in candidates:
        if candidate.variant_id in seen_variant_ids:
            continue
        seen_variant_ids.add(candidate.variant_id)
        unique.append(candidate)
    return unique


def build_review_session(
    connection: TransactionConnection,
    *,
    limit: int = DEFAULT_SESSION_SIZE,
) -> ReviewSessionBuildResult | None:
    """Create one prepared session from the canonical eligible candidates."""
    if not 1 <= limit <= DEFAULT_SESSION_SIZE:
        raise ValueError(
            f"limit must be between 1 and {DEFAULT_SESSION_SIZE}"
        )

    candidates = _unique_candidates(
        load_review_candidates(connection, limit=limit)
    )
    if not candidates:
        return None

    with connection.transaction():
        session_id = create_prepared_review_session(
            connection,
            diversity_context=DEFAULT_DIVERSITY_CONTEXT,
        )
        for position, candidate in enumerate(candidates, start=1):
            add_review_session_item(
                connection,
                review_session_id=session_id,
                product_variant_id=candidate.variant_id,
                scout_result_id=candidate.scout_result_id,
                position=position,
            )

    return ReviewSessionBuildResult(
        session_id=session_id,
        item_count=len(candidates),
    )


def complete_review_session(
    connection: TransactionConnection,
    *,
    session_id: str,
) -> ReviewSessionLifecycleResult:
    """Complete a session and atomically release all of its active items."""
    with connection.transaction():
        mark_review_session_completed(
            connection,
            review_session_id=session_id,
        )
        released_item_count = release_active_review_session_items(
            connection,
            review_session_id=session_id,
        )
    return ReviewSessionLifecycleResult(session_id, released_item_count)


def cancel_review_session(
    connection: TransactionConnection,
    *,
    session_id: str,
) -> ReviewSessionLifecycleResult:
    """Cancel a session and atomically release all of its active items."""
    with connection.transaction():
        mark_review_session_cancelled(
            connection,
            review_session_id=session_id,
        )
        released_item_count = release_active_review_session_items(
            connection,
            review_session_id=session_id,
        )
    return ReviewSessionLifecycleResult(session_id, released_item_count)
