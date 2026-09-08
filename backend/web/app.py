"""FastAPI entry point for the mobile-first Human Review application."""

from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from backend.review.continuous_service import (
    StaleReviewItemError,
    load_continuous_review,
    record_continuous_review_decision,
)
from backend.review.link_service import (
    validate_review_link_identity,
    validate_review_token,
)

from .database import get_database_connection
from .security import (
    REVIEW_COOKIE_NAME,
    classify_request_origin,
    classify_sec_fetch_site,
    create_review_cookie_value,
    parse_review_cookie_value,
    require_valid_origin,
)


BASE_DIR = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def format_price(value: Decimal) -> str:
    """Format a stored Decimal price for German-language presentation."""
    return format(value, ".2f").replace(".", ",")


templates.env.filters["price"] = format_price

app = FastAPI(title="Solvory Review", docs_url=None, redoc_url=None)
app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static",
)


@app.middleware("http")
async def review_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'none'; object-src 'none'; "
        "frame-ancestors 'none'; form-action 'self'; script-src 'self'; "
        "style-src 'self'; img-src 'self' https: data:; connect-src 'self'"
    )
    return response


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


def _enforce_origin(request: Request) -> None:
    origin_header = request.headers.get("origin")
    sec_fetch_site_header = request.headers.get("sec-fetch-site")
    try:
        require_valid_origin(origin_header, sec_fetch_site_header)
    except PermissionError as exc:
        origin_state, normalized_origin = classify_request_origin(origin_header)
        sec_fetch_site = classify_sec_fetch_site(sec_fetch_site_header)
        if origin_state == "other" and normalized_origin is not None:
            logger.warning(
                "review_origin_denied origin_state=%s normalized_origin=%s "
                "sec_fetch_site=%s",
                origin_state,
                normalized_origin,
                sec_fetch_site,
            )
        else:
            logger.warning(
                "review_origin_denied origin_state=%s sec_fetch_site=%s",
                origin_state,
                sec_fetch_site,
            )
        raise HTTPException(status_code=403, detail="Request origin denied") from exc


def _require_cookie_identity(request: Request, connection):
    review_link_id = parse_review_cookie_value(
        request.cookies.get(REVIEW_COOKIE_NAME)
    )
    if review_link_id is None:
        raise HTTPException(status_code=403, detail="Review access denied")
    identity = validate_review_link_identity(
        connection,
        token_record_id=review_link_id,
    )
    if identity is None:
        raise HTTPException(status_code=403, detail="Review access denied")
    return identity


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "").lower()


@app.get("/", response_class=HTMLResponse)
def show_access_bootstrap(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="access.html",
        context={},
    )


async def _read_access_token(request: Request) -> str:
    body = await request.body()
    if not body or len(body) > 1024:
        raise HTTPException(status_code=400, detail="Invalid access data")
    try:
        token = body.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid access data") from exc
    if not token:
        raise HTTPException(status_code=400, detail="Invalid access data")
    return token


@app.post("/review/access")
async def establish_review_access(
    request: Request,
    connection=Depends(get_database_connection),
):
    # Origin checking also prevents login-CSRF that would silently replace a
    # device's Review identity with an attacker's valid Review Link.
    _enforce_origin(request)
    token = await _read_access_token(request)
    identity = validate_review_token(connection, token=token)
    if identity is None:
        raise HTTPException(status_code=403, detail="Review access denied")

    response = JSONResponse({"ok": True})
    response.set_cookie(
        key=REVIEW_COOKIE_NAME,
        value=create_review_cookie_value(
            review_link_id=identity.token_record_id,
        ),
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return response


@app.get("/review", response_class=HTMLResponse)
def show_review(
    request: Request,
    connection=Depends(get_database_connection),
):
    _require_cookie_identity(request, connection)
    state = load_continuous_review(connection)
    if state.is_empty:
        return templates.TemplateResponse(
            request=request,
            name="complete.html",
            context={},
        )
    return templates.TemplateResponse(
        request=request,
        name="review.html",
        context={
            "session": state.session,
            "item": state.item,
            "open_count": state.open_count,
            "prefetch_items": state.prefetch_items,
        },
    )


async def _read_decision_form(request: Request) -> tuple[str, str]:
    try:
        values = parse_qs(
            (await request.body()).decode("utf-8"),
            keep_blank_values=True,
        )
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid form data") from exc
    if set(values) != {"review_session_item_id", "decision"}:
        raise HTTPException(status_code=400, detail="Invalid decision data")
    item_values = values["review_session_item_id"]
    decision_values = values["decision"]
    if len(item_values) != 1 or len(decision_values) != 1:
        raise HTTPException(status_code=400, detail="Invalid decision data")
    item_id = item_values[0].strip()
    decision = decision_values[0].strip()
    if not item_id or not decision:
        raise HTTPException(status_code=400, detail="Missing decision data")
    return item_id, decision


@app.post("/review/decision")
async def submit_decision(
    request: Request,
    connection=Depends(get_database_connection),
):
    _enforce_origin(request)
    identity = _require_cookie_identity(request, connection)
    item_id, decision = await _read_decision_form(request)
    try:
        record_continuous_review_decision(
            connection,
            review_session_item_id=item_id,
            decision=decision,
            decided_by_user_ref=identity.decided_by_user_ref,
        )
    except StaleReviewItemError:
        if _wants_json(request):
            return JSONResponse(
                {"ok": False, "stale": True},
                status_code=409,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid decision") from exc
    if _wants_json(request):
        return JSONResponse({"ok": True})
    return RedirectResponse(url="/review", status_code=303)
