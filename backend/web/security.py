"""Security primitives for the token-free Review web access context."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from urllib.parse import urlsplit


REVIEW_COOKIE_NAME = "solvory_review"
REVIEW_COOKIE_SIGNING_SECRET_ENV = "REVIEW_COOKIE_SIGNING_SECRET"
REVIEW_PUBLIC_ORIGIN_ENV = "REVIEW_PUBLIC_ORIGIN"
MIN_SIGNING_SECRET_BYTES = 32


class ReviewSecurityConfigurationError(RuntimeError):
    """Raised when required Review security configuration is unsafe."""


def _urlsafe_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _urlsafe_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(
        value + padding,
        altchars=b"-_",
        validate=True,
    )


def get_review_cookie_signing_secret() -> bytes:
    value = os.environ.get(REVIEW_COOKIE_SIGNING_SECRET_ENV, "")
    secret = value.encode("utf-8")
    if len(secret) < MIN_SIGNING_SECRET_BYTES:
        raise ReviewSecurityConfigurationError(
            f"{REVIEW_COOKIE_SIGNING_SECRET_ENV} must contain at least "
            f"{MIN_SIGNING_SECRET_BYTES} bytes"
        )
    return secret


def create_review_cookie_value(*, review_link_id: str) -> str:
    """Create a tamper-evident cookie containing no plaintext Review token."""
    if not review_link_id:
        raise ValueError("review_link_id must not be empty")
    payload = _urlsafe_encode(review_link_id.encode("utf-8"))
    signed = f"v1.{payload}"
    signature = hmac.new(
        get_review_cookie_signing_secret(),
        signed.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signed}.{_urlsafe_encode(signature)}"


def parse_review_cookie_value(cookie_value: str | None) -> str | None:
    """Verify a Review cookie and return its non-secret link id."""
    if not cookie_value or len(cookie_value) > 1024:
        return None
    try:
        version, payload, supplied_signature = cookie_value.split(".", 2)
        if version != "v1" or not payload or not supplied_signature:
            return None
        signed = f"{version}.{payload}"
        expected_signature = hmac.new(
            get_review_cookie_signing_secret(),
            signed.encode("ascii"),
            hashlib.sha256,
        ).digest()
        decoded_signature = _urlsafe_decode(supplied_signature)
        if not hmac.compare_digest(decoded_signature, expected_signature):
            return None
        review_link_id = _urlsafe_decode(payload).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    return review_link_id or None


def normalize_review_public_origin(value: str) -> str:
    """Return a canonical HTTPS origin, allowing HTTP only on loopback."""
    raw = value.strip()
    if not raw:
        raise ReviewSecurityConfigurationError(
            f"{REVIEW_PUBLIC_ORIGIN_ENV} environment variable is required"
        )
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ReviewSecurityConfigurationError("invalid Review public origin") from exc

    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ReviewSecurityConfigurationError("invalid Review public origin")

    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower()
    is_loopback = hostname in {"localhost", "127.0.0.1", "::1"}
    if scheme != "https" and not (scheme == "http" and is_loopback):
        raise ReviewSecurityConfigurationError(
            "Review public origin must use HTTPS except on loopback"
        )

    display_host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 443 if scheme == "https" else 80
    port_suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{scheme}://{display_host}{port_suffix}"


def get_review_public_origin() -> str:
    return normalize_review_public_origin(
        os.environ.get(REVIEW_PUBLIC_ORIGIN_ENV, "")
    )


def require_valid_origin(origin_header: str | None) -> None:
    """Reject missing, malformed, or non-canonical browser origins."""
    if not origin_header:
        raise PermissionError("request origin denied")
    try:
        supplied_origin = normalize_review_public_origin(origin_header)
    except ReviewSecurityConfigurationError as exc:
        raise PermissionError("request origin denied") from exc
    if not hmac.compare_digest(supplied_origin, get_review_public_origin()):
        raise PermissionError("request origin denied")
