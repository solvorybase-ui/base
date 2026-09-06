import hashlib
import re

import pytest

import backend.review.link_service as service
from backend.review.link_repository import (
    ReviewLinkRecord,
    create_review_link_record,
    find_active_review_link_by_id,
    find_active_review_link_by_hash,
    revoke_review_link_record,
)


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        pass

    def execute(self, query, params=None):
        sql = " ".join(query.split())
        self.connection.calls.append((sql, params))
        if sql.startswith("INSERT"):
            self.result = ("link-1", params[0])
        elif sql.startswith("SELECT"):
            self.result = self.connection.select_result
        elif sql.startswith("UPDATE"):
            self.result = ("link-1",) if self.connection.update_succeeds else None

    def fetchone(self):
        return self.result


class FakeConnection:
    def __init__(self, *, select_result=None, update_succeeds=True):
        self.calls = []
        self.select_result = select_result
        self.update_succeeds = update_succeeds

    def cursor(self):
        return FakeCursor(self)


def test_token_is_cryptographically_generated_and_long(monkeypatch):
    observed = {}

    def fake_token_urlsafe(byte_count):
        observed["bytes"] = byte_count
        return "strong-random-token"

    monkeypatch.setattr(service.secrets, "token_urlsafe", fake_token_urlsafe)
    monkeypatch.setattr(
        service,
        "create_review_link_record",
        lambda connection, *, token_hash: ReviewLinkRecord("link-1", token_hash),
    )

    created = service.create_review_link(object())

    assert observed["bytes"] >= 32
    assert created.token == "strong-random-token"
    assert created.path == "/#strong-random-token"


def test_sha256_hashes_complete_token():
    token = "complete-token-value"
    assert service.hash_review_token(token) == hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


def test_empty_token_hash_is_rejected():
    with pytest.raises(ValueError, match="must not be empty"):
        service.hash_review_token("")


def test_create_persists_hash_only(monkeypatch):
    captured = {}

    def fake_create(connection, *, token_hash):
        captured["value"] = token_hash
        return ReviewLinkRecord("link-1", token_hash)

    monkeypatch.setattr(service.secrets, "token_urlsafe", lambda size: "secret-token")
    monkeypatch.setattr(service, "create_review_link_record", fake_create)

    created = service.create_review_link(object())

    assert created.token == "secret-token"
    assert captured["value"] != created.token
    assert re.fullmatch(r"[0-9a-f]{64}", captured["value"])


def test_valid_token_resolves_server_identity(monkeypatch):
    monkeypatch.setattr(
        service,
        "find_active_review_link_by_hash",
        lambda connection, *, token_hash: ReviewLinkRecord("uuid-1", token_hash),
    )

    identity = service.validate_review_token(object(), token="valid")

    assert identity.token_record_id == "uuid-1"
    assert identity.decided_by_user_ref == "review_link:uuid-1"


def test_wrong_or_revoked_token_is_rejected(monkeypatch):
    monkeypatch.setattr(
        service,
        "find_active_review_link_by_hash",
        lambda connection, *, token_hash: None,
    )

    assert service.validate_review_token(object(), token="wrong") is None
    assert service.validate_review_token(object(), token="") is None


def test_active_record_id_resolves_server_identity(monkeypatch):
    monkeypatch.setattr(
        service,
        "find_active_review_link_by_id",
        lambda connection, *, token_record_id: ReviewLinkRecord(
            token_record_id, "a" * 64
        ),
    )

    identity = service.validate_review_link_identity(
        object(), token_record_id="uuid-1"
    )

    assert identity.token_record_id == "uuid-1"
    assert identity.decided_by_user_ref == "review_link:uuid-1"


def test_revoked_record_id_is_rejected(monkeypatch):
    monkeypatch.setattr(
        service,
        "find_active_review_link_by_id",
        lambda connection, *, token_record_id: None,
    )

    assert service.validate_review_link_identity(
        object(), token_record_id="uuid-1"
    ) is None


def test_user_reference_is_derived_only_from_record_id():
    assert service.derive_decided_by_user_ref("abc") == "review_link:abc"


def test_repository_insert_contains_no_plaintext_column():
    connection = FakeConnection()
    digest = "a" * 64

    record = create_review_link_record(connection, token_hash=digest)

    sql, params = connection.calls[0]
    assert "token_hash" in sql
    assert "token," not in sql
    assert params == (digest,)
    assert record == ReviewLinkRecord("link-1", digest)


def test_repository_validation_requires_non_revoked_record():
    connection = FakeConnection(select_result=("link-1", "b" * 64))

    result = find_active_review_link_by_hash(connection, token_hash="b" * 64)

    sql, _ = connection.calls[0]
    assert "revoked_at IS NULL" in sql
    assert result.id == "link-1"


def test_repository_cookie_validation_requires_non_revoked_record():
    connection = FakeConnection(select_result=("link-1", "b" * 64))

    result = find_active_review_link_by_id(
        connection, token_record_id="link-1"
    )

    sql, params = connection.calls[0]
    assert "id = %s" in sql
    assert "revoked_at IS NULL" in sql
    assert params == ("link-1",)
    assert result.id == "link-1"


def test_revoke_is_historical_update_not_delete():
    connection = FakeConnection()

    assert revoke_review_link_record(connection, token_record_id="link-1") is True
    sql, params = connection.calls[0]
    assert "UPDATE review_links" in sql
    assert "revoked_at = now()" in sql
    assert "DELETE" not in sql
    assert params == ("link-1",)
