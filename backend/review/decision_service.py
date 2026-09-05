"""Atomic Human Review decision and administrative override services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ContextManager, Protocol

from .decision_repository import (
    create_no_hit_block,
    create_review,
    get_active_no_hit_block,
    get_current_review,
    get_review_session_item,
    release_no_hit_block,
)


VALID_DECISIONS = frozenset({"hit", "no_hit", "later"})
VALID_NO_HIT_OVERRIDE_DECISIONS = frozenset({"hit", "later"})


class TransactionConnection(Protocol):
    def transaction(self) -> ContextManager[object]: ...


@dataclass(frozen=True, slots=True)
class ReviewDecisionResult:
    review_id: str
    product_variant_id: str
    decision: str
    supersedes_review_id: str | None


def _required_text(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def record_review_decision(
    connection: TransactionConnection,
    *,
    review_session_item_id: str,
    decision: str,
    decided_by_user_ref: str,
    reason: str | None = None,
) -> ReviewDecisionResult:
    """Append a normal human decision and create a NO-HIT block if needed."""
    if decision not in VALID_DECISIONS:
        raise ValueError("decision must be hit, no_hit, or later")
    user_ref = _required_text(
        decided_by_user_ref, field_name="decided_by_user_ref"
    )
    normalized_reason = _optional_text(reason)

    with connection.transaction():
        item = get_review_session_item(
            connection,
            review_session_item_id=review_session_item_id,
        )
        current = get_current_review(
            connection,
            review_session_item_id=review_session_item_id,
        )

        if current is not None and current.decision == "no_hit":
            raise ValueError(
                "a current no_hit decision requires administrative override"
            )
        if current is not None and normalized_reason is None:
            raise ValueError("reason is required when correcting a decision")

        if decision == "no_hit":
            active_block = get_active_no_hit_block(
                connection,
                product_variant_id=item.product_variant_id,
            )
            if active_block is not None:
                raise ValueError("an active no-hit block already exists")

        supersedes_review_id = None if current is None else current.id
        review_id = create_review(
            connection,
            review_session_item_id=item.id,
            decision=decision,
            decided_by_user_ref=user_ref,
            reason=normalized_reason,
            supersedes_review_id=supersedes_review_id,
            correction_reason=(
                normalized_reason if supersedes_review_id is not None else None
            ),
        )

        if decision == "no_hit":
            create_no_hit_block(
                connection,
                product_variant_id=item.product_variant_id,
                review_session_item_id=item.id,
                origin_review_id=review_id,
            )

    return ReviewDecisionResult(
        review_id=review_id,
        product_variant_id=item.product_variant_id,
        decision=decision,
        supersedes_review_id=supersedes_review_id,
    )


def override_no_hit_decision(
    connection: TransactionConnection,
    *,
    review_session_item_id: str,
    new_decision: str,
    decided_by_user_ref: str,
    reason: str,
) -> ReviewDecisionResult:
    """Administratively replace a current NO HIT and release its block."""
    if new_decision not in VALID_NO_HIT_OVERRIDE_DECISIONS:
        raise ValueError("new_decision must be hit or later")
    user_ref = _required_text(
        decided_by_user_ref, field_name="decided_by_user_ref"
    )
    normalized_reason = _required_text(reason, field_name="reason")

    with connection.transaction():
        item = get_review_session_item(
            connection,
            review_session_item_id=review_session_item_id,
        )
        current = get_current_review(
            connection,
            review_session_item_id=review_session_item_id,
        )
        if current is None or current.decision != "no_hit":
            raise ValueError("current decision must be no_hit")

        active_block = get_active_no_hit_block(
            connection,
            product_variant_id=item.product_variant_id,
        )
        if active_block is None:
            raise ValueError("an active no-hit block is required")

        review_id = create_review(
            connection,
            review_session_item_id=item.id,
            decision=new_decision,
            decided_by_user_ref=user_ref,
            reason=normalized_reason,
            supersedes_review_id=current.id,
            correction_reason=normalized_reason,
        )
        release_no_hit_block(
            connection,
            review_block_id=active_block.id,
            released_by_user_ref=user_ref,
            release_reason=normalized_reason,
        )

    return ReviewDecisionResult(
        review_id=review_id,
        product_variant_id=item.product_variant_id,
        decision=new_decision,
        supersedes_review_id=current.id,
    )
