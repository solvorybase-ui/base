"""Create one Review Link and reveal its plaintext path exactly once."""

from __future__ import annotations

import os
import sys

from backend.review.link_service import create_review_link

from .database import DATABASE_URL_ENV
from .security import REVIEW_PUBLIC_ORIGIN_ENV, normalize_review_public_origin


def _print_error(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)


def main() -> int:
    database_url = os.environ.get(DATABASE_URL_ENV, "").strip()
    if not database_url:
        _print_error("DATABASE_URL environment variable is required.")
        return 2

    configured_origin = os.environ.get(REVIEW_PUBLIC_ORIGIN_ENV, "").strip()
    try:
        public_origin = (
            normalize_review_public_origin(configured_origin)
            if configured_origin
            else ""
        )
    except RuntimeError:
        _print_error("REVIEW_PUBLIC_ORIGIN environment variable is invalid.")
        return 2

    try:
        import psycopg

        with psycopg.connect(database_url) as connection:
            created = create_review_link(connection)
    except Exception:
        _print_error("Review Link could not be created.")
        return 1

    print(f"{public_origin}{created.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
