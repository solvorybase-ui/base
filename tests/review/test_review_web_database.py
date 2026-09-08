import sys
from types import SimpleNamespace

import pytest

from backend.web import database


class FakeConnectionContext:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, tb):
        return False


def test_web_connection_uses_autocommit_for_reads_and_explicit_service_writes(
    monkeypatch,
):
    observed = {}
    connection = object()

    def connect(database_url, **kwargs):
        observed["database_url"] = database_url
        observed.update(kwargs)
        return FakeConnectionContext(connection)

    monkeypatch.setenv(database.DATABASE_URL_ENV, "postgresql://configured")
    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=connect))

    dependency = database.get_database_connection()
    assert next(dependency) is connection
    with pytest.raises(StopIteration):
        next(dependency)

    assert observed == {
        "database_url": "postgresql://configured",
        "autocommit": True,
    }
