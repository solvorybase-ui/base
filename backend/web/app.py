"""FastAPI entry point for the mobile-first Human Review application."""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from backend.review.continuous_service import (
    StaleReviewItemError,
    load_continuous_review,
    record_continuous_review_decision,
)
from backend.review.link_service import validate_review_token

from .database import get_database_connection


class _RedactReviewTokenFilter(logging.Filter):
    """Prevent Uvicorn access records from containing Review Link tokens."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "uvicorn.access" or not isinstance(record.args, tuple):
            return True
        args = list(record.args)
        if len(args) >= 3 and isinstance(args[2], str):
            path = args[2]
            if path.startswith("/r/"):
                suffix = "/decision" if path.endswith("/decision") else ""
                args[2] = f"/r/[REDACTED]{suffix}"
                record.args = tuple(args)
        return True


logging.getLogger("uvicorn.access").addFilter(_RedactReviewTokenFilter())

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

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
    return response


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


def _validate_identity(connection, token: str):
    identity = validate_review_token(connection, token=token)
    if identity is None:
        raise HTTPException(status_code=403, detail="Review access denied")
    return identity


@app.get("/r/{token}", response_class=HTMLResponse)
def show_review(
    request: Request,
    token: str,
    connection=Depends(get_database_connection),
):
    _validate_identity(connection, token)
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
        context={"session": state.session, "item": state.item},
    )


async def _read_decision_form(request: Request) -> tuple[str, str]:
    try:
        values = parse_qs((await request.body()).decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid form data") from exc
    item_id = values.get("review_session_item_id", [""])[0].strip()
    decision = values.get("decision", [""])[0].strip()
    if not item_id or not decision:
        raise HTTPException(status_code=400, detail="Missing decision data")
    return item_id, decision


@app.post("/r/{token}/decision")
async def submit_decision(
    request: Request,
    token: str,
    connection=Depends(get_database_connection),
):
    identity = _validate_identity(connection, token)
    item_id, decision = await _read_decision_form(request)
    try:
        record_continuous_review_decision(
            connection,
            review_session_item_id=item_id,
            decision=decision,
            decided_by_user_ref=identity.decided_by_user_ref,
        )
    except StaleReviewItemError:
        pass
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid decision") from exc
    return RedirectResponse(url=f"/r/{token}", status_code=303)
