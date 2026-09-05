import asyncio
import logging

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import backend.web.app as web
from backend.review.continuous_service import ContinuousReviewState, StaleReviewItemError
from backend.review.link_service import ReviewLinkIdentity
from backend.review.session_read_repository import ReviewSessionProjection

from tests.review.test_review_session_read_service import item


def request(path, *, method="GET", body=b""):
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    token = path.split("/")[2] if path.startswith("/r/") else ""
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
        "client": ("test", 123),
        "server": ("testserver", 80),
        "root_path": "",
        "path_params": {"token": token},
        "router": web.app.router,
        "app": web.app,
    }
    return Request(scope, receive)


def valid_identity():
    return ReviewLinkIdentity("link-1", "review_link:link-1")


def state(*, images=("https://example.test/image.jpg",), offer=True):
    current_item = item(images=images)
    if not offer:
        from dataclasses import replace
        current_item = replace(
            current_item,
            shop_name=None,
            price=None,
            currency=None,
            offer_name=None,
            product_url=None,
            availability=None,
        )
    session = ReviewSessionProjection("session-1", "prepared", 1, (current_item,))
    return ContinuousReviewState(session, current_item)


def test_get_valid_token_renders_product(monkeypatch):
    monkeypatch.setattr(web, "validate_review_token", lambda c, *, token: valid_identity())
    monkeypatch.setattr(web, "load_continuous_review", lambda c: state())
    response = web.show_review(request("/r/secret"), "secret", connection=object())
    body = response.body.decode()
    assert response.status_code == 200
    assert "Variant" in body
    assert "HIT" in body and "NO HIT" in body and "SPÄTER" in body


def test_get_invalid_or_revoked_token_denies_without_echo(monkeypatch):
    monkeypatch.setattr(web, "validate_review_token", lambda c, *, token: None)
    with pytest.raises(HTTPException) as error:
        web.show_review(request("/r/top-secret"), "top-secret", connection=object())
    assert error.value.status_code == 403
    assert "top-secret" not in str(error.value.detail)


def test_empty_flow_renders_completion(monkeypatch):
    monkeypatch.setattr(web, "validate_review_token", lambda c, *, token: valid_identity())
    monkeypatch.setattr(web, "load_continuous_review", lambda c: ContinuousReviewState(None, None))
    response = web.show_review(request("/r/secret"), "secret", connection=object())
    assert "Alles geprüft" in response.body.decode()


def test_product_without_image_or_offer_is_renderable(monkeypatch):
    monkeypatch.setattr(web, "validate_review_token", lambda c, *, token: valid_identity())
    monkeypatch.setattr(web, "load_continuous_review", lambda c: state(images=(), offer=False))
    response = web.show_review(request("/r/secret"), "secret", connection=object())
    body = response.body.decode()
    assert "Kein Produktbild verfügbar" in body
    assert "Keine Angebotsinformationen verfügbar" in body


@pytest.mark.parametrize("decision", ["hit", "no_hit", "later"])
def test_post_delegates_human_decision_and_redirects(monkeypatch, decision):
    captured = {}
    monkeypatch.setattr(web, "validate_review_token", lambda c, *, token: valid_identity())
    monkeypatch.setattr(web, "record_continuous_review_decision", lambda c, **kwargs: captured.update(kwargs))
    body = f"review_session_item_id=item-1&decision={decision}".encode()
    response = asyncio.run(
        web.submit_decision(request("/r/secret/decision", method="POST", body=body), "secret", connection=object())
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/r/secret"
    assert captured == {
        "review_session_item_id": "item-1",
        "decision": decision,
        "decided_by_user_ref": "review_link:link-1",
    }


def test_client_cannot_override_user_reference(monkeypatch):
    captured = {}
    monkeypatch.setattr(web, "validate_review_token", lambda c, *, token: valid_identity())
    monkeypatch.setattr(web, "record_continuous_review_decision", lambda c, **kwargs: captured.update(kwargs))
    body = b"review_session_item_id=item-1&decision=hit&decided_by_user_ref=attacker"
    asyncio.run(web.submit_decision(request("/r/secret/decision", method="POST", body=body), "secret", connection=object()))
    assert captured["decided_by_user_ref"] == "review_link:link-1"


def test_stale_multi_device_post_redirects_without_second_write(monkeypatch):
    calls = []
    monkeypatch.setattr(web, "validate_review_token", lambda c, *, token: valid_identity())

    def stale(connection, **kwargs):
        calls.append(kwargs)
        raise StaleReviewItemError("already decided")

    monkeypatch.setattr(web, "record_continuous_review_decision", stale)
    body = b"review_session_item_id=item-1&decision=later"
    response = asyncio.run(web.submit_decision(request("/r/secret/decision", method="POST", body=body), "secret", connection=object()))
    assert response.status_code == 303
    assert len(calls) == 1


def test_get_never_invokes_decision_write(monkeypatch):
    monkeypatch.setattr(web, "validate_review_token", lambda c, *, token: valid_identity())
    monkeypatch.setattr(web, "load_continuous_review", lambda c: state())
    monkeypatch.setattr(web, "record_continuous_review_decision", lambda *a, **k: pytest.fail("GET wrote decision"))
    web.show_review(request("/r/secret"), "secret", connection=object())


def test_access_log_filter_redacts_token():
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, "%s %s %s %s %s",
        (("127.0.0.1", 1), "GET", "/r/secret-token", "1.1", 200), None,
    )
    web._RedactReviewTokenFilter().filter(record)
    assert "secret-token" not in str(record.args)
    assert "/r/[REDACTED]" in str(record.args)


def test_missing_form_fields_return_generic_error(monkeypatch):
    monkeypatch.setattr(web, "validate_review_token", lambda c, *, token: valid_identity())
    with pytest.raises(HTTPException) as error:
        asyncio.run(web.submit_decision(request("/r/secret/decision", method="POST", body=b"decision=hit"), "secret", connection=object()))
    assert error.value.status_code == 400
    assert "secret" not in str(error.value.detail)
