import pytest

from backend.web import security


SECRET = "a-secure-test-signing-secret-with-more-than-32-bytes"


@pytest.fixture(autouse=True)
def signing_secret(monkeypatch):
    monkeypatch.setenv(security.REVIEW_COOKIE_SIGNING_SECRET_ENV, SECRET)


def test_signed_cookie_round_trip_contains_only_record_identity():
    cookie = security.create_review_cookie_value(review_link_id="link-uuid-1")
    assert security.parse_review_cookie_value(cookie) == "link-uuid-1"
    assert "review-token" not in cookie


def test_cookie_payload_or_signature_manipulation_is_rejected():
    cookie = security.create_review_cookie_value(review_link_id="link-uuid-1")
    version, payload, signature = cookie.split(".")
    assert security.parse_review_cookie_value(
        f"{version}.{payload}x.{signature}"
    ) is None
    assert security.parse_review_cookie_value(
        f"{version}.{payload}.{signature[:-1]}x"
    ) is None


@pytest.mark.parametrize("value", [None, "", "bad", "v2.a.b", "v1.!.!"])
def test_malformed_cookie_is_rejected(value):
    assert security.parse_review_cookie_value(value) is None


def test_missing_or_weak_signing_secret_fails_closed(monkeypatch):
    monkeypatch.delenv(security.REVIEW_COOKIE_SIGNING_SECRET_ENV, raising=False)
    with pytest.raises(security.ReviewSecurityConfigurationError):
        security.create_review_cookie_value(review_link_id="link-1")

    monkeypatch.setenv(security.REVIEW_COOKIE_SIGNING_SECRET_ENV, "too-short")
    with pytest.raises(security.ReviewSecurityConfigurationError):
        security.create_review_cookie_value(review_link_id="link-1")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://Review.Example/", "https://review.example"),
        ("https://review.example:443", "https://review.example"),
        ("https://review.example:8443", "https://review.example:8443"),
        ("http://127.0.0.1:8000", "http://127.0.0.1:8000"),
        ("http://localhost:8000", "http://localhost:8000"),
    ],
)
def test_public_origin_is_normalized(value, expected):
    assert security.normalize_review_public_origin(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "http://review.example",
        "https://review.example/path",
        "https://user@review.example",
        "https://review.example?token=x",
        "https://review.example#token",
    ],
)
def test_unsafe_public_origin_is_rejected(value):
    with pytest.raises(security.ReviewSecurityConfigurationError):
        security.normalize_review_public_origin(value)


def test_exact_origin_is_required(monkeypatch):
    monkeypatch.setenv(
        security.REVIEW_PUBLIC_ORIGIN_ENV, "https://review.example"
    )
    security.require_valid_origin("https://review.example")
    with pytest.raises(PermissionError):
        security.require_valid_origin(None)
    with pytest.raises(PermissionError):
        security.require_valid_origin("https://other.example")


@pytest.mark.parametrize(
    ("origin", "expected_state", "expected_normalized"),
    [
        (None, "missing", None),
        ("null", "null", None),
        ("https://review.example", "exact", "https://review.example"),
        ("https://other.example/", "other", "https://other.example"),
    ],
)
def test_origin_diagnostic_classification(
    monkeypatch, origin, expected_state, expected_normalized
):
    monkeypatch.setenv(
        security.REVIEW_PUBLIC_ORIGIN_ENV, "https://review.example"
    )

    assert security.classify_request_origin(origin) == (
        expected_state,
        expected_normalized,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "missing"),
        ("same-origin", "same-origin"),
        ("same-site", "same-site"),
        ("cross-site", "cross-site"),
        ("none", "none"),
        ("untrusted value", "other"),
    ],
)
def test_sec_fetch_site_diagnostic_is_bounded(value, expected):
    assert security.classify_sec_fetch_site(value) == expected
