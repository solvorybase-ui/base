"""Minimal PostgreSQL connection dependency for the Review web app."""

from __future__ import annotations

from collections.abc import Iterator
import os


DATABASE_URL_ENV = "DATABASE_URL"


def get_database_url() -> str:
    database_url = os.environ.get(DATABASE_URL_ENV, "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required")
    return database_url


def get_database_connection() -> Iterator[object]:
    """Yield one request-scoped Psycopg 3 connection."""
    import psycopg

    with psycopg.connect(get_database_url()) as connection:
        yield connection
