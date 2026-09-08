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

    # Read checks run in autocommit mode; domain services open explicit atomic
    # transactions for writes. This avoids turning their transaction blocks
    # into nested savepoints after an earlier request-level read.
    with psycopg.connect(get_database_url(), autocommit=True) as connection:
        yield connection
