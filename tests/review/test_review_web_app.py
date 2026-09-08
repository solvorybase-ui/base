import asyncio
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

import backend.web.app as web
from backend.review.continuous_service import ContinuousReviewState, StaleReviewItemError
from backend.review.link_service import ReviewLinkIdentity
from backend.review.session_read_repository import ReviewSessionProjection
from backend.web.security import REVIEW_COOKIE_NAME, create_review_cookie_value

from tests.review.test_review_session_read_service import item


SIGNING_SECRET = "test-signing-secret-that-is-at-least-32-bytes-long"
PUBLIC_ORIGIN = "https://review.test"


@pytest.fixture(autouse=True)
def review_security_environment(monkeypatch):
    monkeypatch.setenv("REVIEW_COOKIE_SIGNING_SECRET", SIGNING_SECRET)
    monkeypatch.setenv("REVIEW_PUBLIC_ORIGIN", PUBLIC_ORIGIN)


def request(
    path,
    *,
    method="GET",
    body=b"",
    origin=None,
    sec_fetch_site=None,
    cookie=None,
    content_type="application/x-www-form-urlencoded",
    accept=None,
):
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    headers = [(b"content-type", content_type.encode("ascii"))]
    if accept is not None:
        headers.append((b"accept", accept.encode("ascii")))
    if origin is not None:
        headers.append((b"origin", origin.encode("ascii")))
    if sec_fetch_site is not None:
        headers.append((b"sec-fetch-site", sec_fetch_site.encode("ascii")))
    if cookie is not None:
        headers.append(
            (b"cookie", f"{REVIEW_COOKIE_NAME}={cookie}".encode("ascii"))
        )
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "client": ("test", 123),
        "server": ("review.test", 443),
        "root_path": "",
        "path_params": {},
        "router": web.app.router,
        "app": web.app,
    }
    return Request(scope, receive)


def valid_identity():
    return ReviewLinkIdentity("link-1", "review_link:link-1")


def valid_cookie():
    return create_review_cookie_value(review_link_id="link-1")


def permit_cookie_identity(monkeypatch):
    monkeypatch.setattr(
        web,
        "validate_review_link_identity",
        lambda c, *, token_record_id: (
            valid_identity() if token_record_id == "link-1" else None
        ),
    )


def state(*, images=("https://example.test/image.jpg",), offer=True):
    current_item = item(images=images)
    if not offer:
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
    return ContinuousReviewState(session, current_item, open_count=79)


def test_bootstrap_page_contains_no_token_and_loads_local_script():
    response = web.show_access_bootstrap(request("/"))
    body = response.body.decode()
    assert response.status_code == 200
    assert "bootstrap.js" in body
    assert "window.location.hash" not in body
    assert "/r/" not in body


def test_bootstrap_script_reads_fragment_posts_body_and_removes_fragment():
    script = Path("backend/web/static/bootstrap.js").read_text(encoding="utf-8")
    assert "window.location.hash" in script
    assert 'fetch("/review/access"' in script
    assert "body: token" in script
    assert "console." not in script
    assert "replaceState" in script
    assert 'location.replace("/review")' in script


def test_access_with_valid_token_sets_secure_cookie(monkeypatch):
    monkeypatch.setattr(
        web, "validate_review_token", lambda c, *, token: valid_identity()
    )
    response = asyncio.run(
        web.establish_review_access(
            request(
                "/review/access",
                method="POST",
                body=b"plain-review-token",
                origin=PUBLIC_ORIGIN,
                content_type="text/plain;charset=UTF-8",
            ),
            connection=object(),
        )
    )
    cookie = response.headers["set-cookie"]
    assert response.status_code == 200
    assert f"{REVIEW_COOKIE_NAME}=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/" in cookie
    assert "Domain=" not in cookie
    assert "plain-review-token" not in cookie
    assert "plain-review-token" not in response.body.decode()


def test_access_invalid_or_revoked_token_denies_without_cookie_or_echo(monkeypatch):
    monkeypatch.setattr(web, "validate_review_token", lambda c, *, token: None)
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            web.establish_review_access(
                request(
                    "/review/access",
                    method="POST",
                    body=b"top-secret",
                    origin=PUBLIC_ORIGIN,
                    content_type="text/plain",
                ),
                connection=object(),
            )
        )
    assert error.value.status_code == 403
    assert "top-secret" not in str(error.value.detail)


@pytest.mark.parametrize("origin", [None, "https://other.test"])
def test_access_rejects_missing_or_wrong_origin(monkeypatch, origin):
    monkeypatch.setattr(
        web, "validate_review_token", lambda c, *, token: valid_identity()
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            web.establish_review_access(
                request(
                    "/review/access",
                    method="POST",
                    body=b"secret",
                    origin=origin,
                    content_type="text/plain",
                ),
                connection=object(),
            )
        )
    assert error.value.status_code == 403


def test_access_accepts_null_origin_only_for_same_origin_fetch(monkeypatch):
    monkeypatch.setattr(
        web, "validate_review_token", lambda c, *, token: valid_identity()
    )

    response = asyncio.run(
        web.establish_review_access(
            request(
                "/review/access",
                method="POST",
                body=b"secret",
                origin="null",
                sec_fetch_site="same-origin",
                content_type="text/plain",
            ),
            connection=object(),
        )
    )

    assert response.status_code == 200


def test_get_valid_cookie_renders_product(monkeypatch):
    permit_cookie_identity(monkeypatch)
    monkeypatch.setattr(web, "load_continuous_review", lambda c: state())
    response = web.show_review(
        request("/review", cookie=valid_cookie()), connection=object()
    )
    body = response.body.decode()
    assert response.status_code == 200
    assert "Variant" in body
    assert "HIT" in body and "NO HIT" in body and "SPÄTER" in body
    assert 'action="/review/decision"' in body
    assert "/r/" not in body


def test_review_shows_global_open_count_not_internal_session_progress(monkeypatch):
    permit_cookie_identity(monkeypatch)
    current_state = state()
    current_state = replace(
        current_state,
        session=replace(current_state.session, item_count=20),
    )
    monkeypatch.setattr(web, "load_continuous_review", lambda c: current_state)

    response = web.show_review(
        request("/review", cookie=valid_cookie()), connection=object()
    )
    body = response.body.decode()

    assert "79 offen" in body
    assert "Produkt 1 / 20" not in body


def test_review_preloads_only_main_images_of_next_two_items(monkeypatch):
    permit_cookie_identity(monkeypatch)
    current = item(item_id="item-1", position=1)
    next_one = item(
        item_id="item-2",
        position=2,
        images=(
            "https://images.test/next-1-main.jpg",
            "https://images.test/next-1-extra.jpg",
        ),
    )
    next_two = item(
        item_id="item-3",
        position=3,
        images=("https://images.test/next-2-main.jpg",),
    )
    session = ReviewSessionProjection(
        "session-1", "prepared", 3, (current, next_one, next_two)
    )
    current_state = ContinuousReviewState(
        session,
        current,
        open_count=3,
        prefetch_items=(next_one, next_two),
    )
    monkeypatch.setattr(web, "load_continuous_review", lambda c: current_state)

    body = web.show_review(
        request("/review", cookie=valid_cookie()), connection=object()
    ).body.decode()

    assert (
        'rel="preload" as="image" '
        'href="https://images.test/next-1-main.jpg"' in body
    )
    assert (
        'rel="preload" as="image" '
        'href="https://images.test/next-2-main.jpg"' in body
    )
    assert body.count('rel="preload" as="image"') == 2
    assert "next-1-extra.jpg" in body
    assert 'data-item-id="item-2"' in body
    assert 'data-item-id="item-3"' in body
    assert "review.js" in body


def test_prefetched_product_contains_complete_read_only_ui_data(monkeypatch):
    permit_cookie_identity(monkeypatch)
    current = item(item_id="item-1", position=1)
    prefetched = replace(
        item(item_id="item-2", position=2),
        family_name="Prefetch Family",
        variant_name="Prefetch Product",
        brand_name="Prefetch Brand",
        category="Prefetch Category",
        description="Prefetch Description",
        scout_reason="Prefetch Scout Reason",
        shop_name="Prefetch Shop",
        price=Decimal("12.34"),
        currency="EUR",
        availability="available",
        product_url="https://shop.test/prefetched",
        image_urls=("https://images.test/main.jpg", "https://images.test/extra.jpg"),
    )
    session = ReviewSessionProjection(
        "session-1", "prepared", 2, (current, prefetched)
    )
    monkeypatch.setattr(
        web,
        "load_continuous_review",
        lambda c: ContinuousReviewState(
            session,
            current,
            open_count=2,
            prefetch_items=(prefetched,),
        ),
    )

    body = web.show_review(
        request("/review", cookie=valid_cookie()), connection=object()
    ).body.decode()

    for expected in (
        "Prefetch Family",
        "Prefetch Product",
        "Prefetch Brand",
        "Prefetch Category",
        "Prefetch Description",
        "Prefetch Scout Reason",
        "Prefetch Shop",
        "12,34 EUR",
        "available",
        "https://shop.test/prefetched",
        "https://images.test/main.jpg",
        "https://images.test/extra.jpg",
    ):
        assert expected in body


@pytest.mark.parametrize("cookie", [None, "invalid.cookie.value"])
def test_get_missing_or_invalid_cookie_denies(monkeypatch, cookie):
    permit_cookie_identity(monkeypatch)
    with pytest.raises(HTTPException) as error:
        web.show_review(request("/review", cookie=cookie), connection=object())
    assert error.value.status_code == 403


def test_revoked_link_makes_existing_cookie_invalid(monkeypatch):
    monkeypatch.setattr(
        web,
        "validate_review_link_identity",
        lambda c, *, token_record_id: None,
    )
    with pytest.raises(HTTPException) as error:
        web.show_review(
            request("/review", cookie=valid_cookie()), connection=object()
        )
    assert error.value.status_code == 403


def test_empty_flow_renders_completion(monkeypatch):
    permit_cookie_identity(monkeypatch)
    monkeypatch.setattr(
        web,
        "load_continuous_review",
        lambda c: ContinuousReviewState(None, None),
    )
    response = web.show_review(
        request("/review", cookie=valid_cookie()), connection=object()
    )
    assert "Alles geprüft" in response.body.decode()


def test_product_without_image_or_offer_is_renderable(monkeypatch):
    permit_cookie_identity(monkeypatch)
    monkeypatch.setattr(
        web, "load_continuous_review", lambda c: state(images=(), offer=False)
    )
    response = web.show_review(
        request("/review", cookie=valid_cookie()), connection=object()
    )
    body = response.body.decode()
    assert "Kein Produktbild verfügbar" in body
    assert "Keine Angebotsinformationen verfügbar" in body


@pytest.mark.parametrize(
    ("stored_price", "display_price"),
    [
        (Decimal("228.0000"), "228,00 €"),
        (Decimal("228.5"), "228,50 €"),
        (Decimal("19.99"), "19,99 €"),
    ],
)
def test_price_is_formatted_for_display_without_mutating_decimal(
    monkeypatch, stored_price, display_price
):
    permit_cookie_identity(monkeypatch)
    current_state = state()
    current_item = replace(
        current_state.item,
        price=stored_price,
        currency="€",
    )
    current_state = ContinuousReviewState(
        replace(current_state.session, items=(current_item,)),
        current_item,
    )
    monkeypatch.setattr(
        web, "load_continuous_review", lambda c: current_state
    )

    response = web.show_review(
        request("/review", cookie=valid_cookie()), connection=object()
    )

    assert display_price in response.body.decode()
    assert current_item.price is stored_price


@pytest.mark.parametrize("decision", ["hit", "no_hit", "later"])
def test_post_delegates_human_decision_and_redirects(monkeypatch, decision):
    captured = {}
    permit_cookie_identity(monkeypatch)
    monkeypatch.setattr(
        web,
        "record_continuous_review_decision",
        lambda c, **kwargs: captured.update(kwargs),
    )
    body = f"review_session_item_id=item-1&decision={decision}".encode()
    response = asyncio.run(
        web.submit_decision(
            request(
                "/review/decision",
                method="POST",
                body=body,
                origin=PUBLIC_ORIGIN,
                cookie=valid_cookie(),
            ),
            connection=object(),
        )
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/review"
    assert captured == {
        "review_session_item_id": "item-1",
        "decision": decision,
        "decided_by_user_ref": "review_link:link-1",
    }


@pytest.mark.parametrize("decision", ["hit", "no_hit", "later"])
def test_fetch_decision_returns_json_success(monkeypatch, decision):
    captured = {}
    permit_cookie_identity(monkeypatch)
    monkeypatch.setattr(
        web,
        "record_continuous_review_decision",
        lambda c, **kwargs: captured.update(kwargs),
    )

    response = asyncio.run(
        web.submit_decision(
            request(
                "/review/decision",
                method="POST",
                body=(
                    f"review_session_item_id=item-1&decision={decision}"
                ).encode(),
                origin=PUBLIC_ORIGIN,
                cookie=valid_cookie(),
                accept="application/json",
            ),
            connection=object(),
        )
    )

    assert response.status_code == 200
    assert response.body == b'{"ok":true}'
    assert captured["decision"] == decision


def test_client_identity_fields_are_rejected(monkeypatch):
    permit_cookie_identity(monkeypatch)
    body = (
        b"review_session_item_id=item-1&decision=hit&"
        b"decided_by_user_ref=attacker&review_link_id=other&token=secret"
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            web.submit_decision(
                request(
                    "/review/decision",
                    method="POST",
                    body=body,
                    origin=PUBLIC_ORIGIN,
                    cookie=valid_cookie(),
                ),
                connection=object(),
            )
        )
    assert error.value.status_code == 400


@pytest.mark.parametrize("origin", [None, "https://other.test"])
def test_decision_rejects_missing_or_wrong_origin(monkeypatch, origin):
    permit_cookie_identity(monkeypatch)
    body = b"review_session_item_id=item-1&decision=hit"
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            web.submit_decision(
                request(
                    "/review/decision",
                    method="POST",
                    body=body,
                    origin=origin,
                    cookie=valid_cookie(),
                ),
                connection=object(),
            )
        )
    assert error.value.status_code == 403


def test_decision_accepts_null_origin_for_same_origin_fetch(monkeypatch):
    captured = {}
    permit_cookie_identity(monkeypatch)
    monkeypatch.setattr(
        web,
        "record_continuous_review_decision",
        lambda c, **kwargs: captured.update(kwargs),
    )

    response = asyncio.run(
        web.submit_decision(
            request(
                "/review/decision",
                method="POST",
                body=b"review_session_item_id=item-1&decision=later",
                origin="null",
                sec_fetch_site="same-origin",
                cookie=valid_cookie(),
            ),
            connection=object(),
        )
    )

    assert response.status_code == 303
    assert captured["decision"] == "later"


def test_stale_multi_device_post_redirects_without_second_write(monkeypatch):
    calls = []
    permit_cookie_identity(monkeypatch)

    def stale(connection, **kwargs):
        calls.append(kwargs)
        raise StaleReviewItemError("already decided")

    monkeypatch.setattr(web, "record_continuous_review_decision", stale)
    body = b"review_session_item_id=item-1&decision=later"
    response = asyncio.run(
        web.submit_decision(
            request(
                "/review/decision",
                method="POST",
                body=body,
                origin=PUBLIC_ORIGIN,
                cookie=valid_cookie(),
            ),
            connection=object(),
        )
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/review"
    assert len(calls) == 1


def test_stale_fetch_returns_conflict_without_success(monkeypatch):
    permit_cookie_identity(monkeypatch)
    monkeypatch.setattr(
        web,
        "record_continuous_review_decision",
        lambda c, **kwargs: (_ for _ in ()).throw(
            StaleReviewItemError("already decided")
        ),
    )

    response = asyncio.run(
        web.submit_decision(
            request(
                "/review/decision",
                method="POST",
                body=b"review_session_item_id=item-1&decision=hit",
                origin=PUBLIC_ORIGIN,
                cookie=valid_cookie(),
                accept="application/json",
            ),
            connection=object(),
        )
    )

    assert response.status_code == 409
    assert response.body == b'{"ok":false,"stale":true}'


def test_fast_next_script_waits_for_ack_updates_count_and_has_safe_fallbacks():
    script = Path("backend/web/static/review.js").read_text(encoding="utf-8")

    assert 'fetch(form.action' in script
    assert script.index("await fetch(form.action") < script.index(
        "if (!showPrefetchedProduct())"
    )
    assert "response.status === 409" in script
    assert "window.location.reload()" in script
    assert 'window.location.assign("/review")' in script
    assert "Math.max(0, openCount - 1)" in script
    assert 'fetch("/review"' in script
    assert "prefetched.shift()" in script
    assert "token" not in script.lower()


def test_csp_allows_local_review_script_without_inline_script():
    async def call_next(_request):
        return Response("ok")

    response = asyncio.run(web.review_security_headers(request("/review"), call_next))
    csp = response.headers["Content-Security-Policy"]

    assert "script-src 'self'" in csp
    assert "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp


def test_get_never_invokes_decision_write(monkeypatch):
    permit_cookie_identity(monkeypatch)
    monkeypatch.setattr(web, "load_continuous_review", lambda c: state())
    monkeypatch.setattr(
        web,
        "record_continuous_review_decision",
        lambda *a, **k: pytest.fail("GET wrote decision"),
    )
    web.show_review(request("/review", cookie=valid_cookie()), connection=object())


def test_legacy_token_routes_are_removed():
    route_paths = {getattr(route, "path", None) for route in web.app.routes}
    assert "/r/{token}" not in route_paths
    assert "/r/{token}/decision" not in route_paths


def test_security_headers_are_consistent():
    async def call_next(_request):
        return Response("ok")

    response = asyncio.run(
        web.review_security_headers(request("/"), call_next)
    )
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    csp = response.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp
    assert "unsafe-eval" not in csp
    assert "unsafe-inline" not in csp


def test_missing_form_fields_return_generic_error(monkeypatch):
    permit_cookie_identity(monkeypatch)
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            web.submit_decision(
                request(
                    "/review/decision",
                    method="POST",
                    body=b"decision=hit",
                    origin=PUBLIC_ORIGIN,
                    cookie=valid_cookie(),
                ),
                connection=object(),
            )
        )
    assert error.value.status_code == 400
