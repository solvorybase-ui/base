"""Secure creation and validation of Review Link access tokens."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import secrets

from .link_repository import (
    ConnectionLike,
    create_review_link_record,
    find_active_review_link_by_hash,
    revoke_review_link_record,
)


TOKEN_BYTES = 32


@dataclass(frozen=True, slots=True)
class CreatedReviewLink:
    token_record_id: str
    token: str

    @property
    def path(self) -> str:
        return f"/r/{self.token}"


@dataclass(frozen=True, slots=True)
class ReviewLinkIdentity:
    token_record_id: str
    decided_by_user_ref: str


def hash_review_token(token: str) -> str:
    """Return the lowercase SHA-256 hash of the complete token."""
    if not token:
        raise ValueError("token must not be empty")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def derive_decided_by_user_ref(token_record_id: str) -> str:
    """Build the server-owned Human Review identity."""
    if not token_record_id:
        raise ValueError("token_record_id must not be empty")
    return f"review_link:{token_record_id}"


def create_review_link(connection: ConnectionLike) -> CreatedReviewLink:
    """Create a strong token, persist only its hash, and reveal it once."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    record = create_review_link_record(
        connection,
        token_hash=hash_review_token(token),
    )
    return CreatedReviewLink(token_record_id=record.id, token=token)


def validate_review_token(
    connection: ConnectionLike, *, token: str
) -> ReviewLinkIdentity | None:
    """Resolve an active token to its stable server-side identity."""
    if not token:
        return None
    record = find_active_review_link_by_hash(
        connection,
        token_hash=hash_review_token(token),
    )
    if record is None:
        return None
    return ReviewLinkIdentity(
        token_record_id=record.id,
        decided_by_user_ref=derive_decided_by_user_ref(record.id),
    )


def revoke_review_link(
    connection: ConnectionLike, *, token_record_id: str
) -> bool:
    """Revoke a Review Link identity by its non-secret record id."""
    return revoke_review_link_record(
        connection,
        token_record_id=token_record_id,
    )
