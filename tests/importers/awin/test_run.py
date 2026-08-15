from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from backend.importers.awin import run as runtime


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakePsycopgError(Exception):
    pass


class FakeOperationalError(FakePsycopgError):
    pass


def install_fake_psycopg(monkeypatch, connect):
    fake_module = SimpleNamespace(
        connect=connect,
        Error=FakePsycopgError,
        OperationalError=FakeOperationalError,
    )
    monkeypatch.setitem(sys.modules, "psycopg", fake_module)
    return fake_module


def test_missing_feed_path_returns_usage_error(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/db")
    monkeypatch.setenv("IMPORTER_VERSION", "test")

    exit_code = runtime.main([])

    assert exit_code == 2
    assert "AWIN feed path is required" in capsys.readouterr().err


def test_nonexistent_feed_path_returns_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/db")
    monkeypatch.setenv("IMPORTER_VERSION", "test")
    missing = tmp_path / "missing.csv"

    exit_code = runtime.main([str(missing)])

    assert exit_code == 2
    assert "does not exist" in capsys.readouterr().err


def test_missing_database_url_returns_error(monkeypatch, tmp_path, capsys):
    feed = tmp_path / "feed.csv"
    feed.write_text("header\n", encoding="utf-8")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("IMPORTER_VERSION", "test")

    exit_code = runtime.main([str(feed)])

    assert exit_code == 2
    assert "DATABASE_URL environment variable is required" in capsys.readouterr().err


def test_missing_importer_version_returns_error(monkeypatch, tmp_path, capsys):
    feed = tmp_path / "feed.csv"
    feed.write_text("header\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/db")
    monkeypatch.delenv("IMPORTER_VERSION", raising=False)

    exit_code = runtime.main([str(feed)])

    assert exit_code == 2
    assert "IMPORTER_VERSION environment variable is required" in capsys.readouterr().err


def test_success_connects_and_calls_existing_orchestrator(monkeypatch, tmp_path, capsys):
    feed = tmp_path / "feed.csv"
    feed.write_text("header\n", encoding="utf-8")
    database_url = "postgresql://user:secret@example.invalid/db"
    connection = FakeConnection()
    captured = {}

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("IMPORTER_VERSION", "phase4-test")

    def fake_connect(value):
        captured["database_url"] = value
        return connection

    install_fake_psycopg(monkeypatch, fake_connect)

    def fake_run(conn, path, *, importer_version):
        captured["connection"] = conn
        captured["feed_path"] = path
        captured["importer_version"] = importer_version
        return SimpleNamespace(records_read=3, records_accepted=2, records_rejected=1)

    monkeypatch.setattr(runtime, "run_awin_import", fake_run)

    exit_code = runtime.main([str(feed)])

    assert exit_code == 0
    assert captured == {
        "database_url": database_url,
        "connection": connection,
        "feed_path": Path(feed),
        "importer_version": "phase4-test",
    }
    output = capsys.readouterr()
    assert "read=3 accepted=2 rejected=1" in output.out
    assert "secret" not in output.out
    assert "secret" not in output.err


def test_database_error_returns_generic_error_without_secret(monkeypatch, tmp_path, capsys):
    feed = tmp_path / "feed.csv"
    feed.write_text("header\n", encoding="utf-8")
    database_url = "postgresql://user:super-secret@example.invalid/db"

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("IMPORTER_VERSION", "test")

    def fake_connect(_value):
        raise FakeOperationalError("connection failed for super-secret")

    install_fake_psycopg(monkeypatch, fake_connect)

    exit_code = runtime.main([str(feed)])

    assert exit_code == 1
    output = capsys.readouterr()
    assert "could not be started or completed" in output.err
    assert "super-secret" not in output.err


def test_fatal_import_error_returns_failure_without_details(monkeypatch, tmp_path, capsys):
    feed = tmp_path / "feed.csv"
    feed.write_text("header\n", encoding="utf-8")
    connection = FakeConnection()

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@example.invalid/db")
    monkeypatch.setenv("IMPORTER_VERSION", "test")
    install_fake_psycopg(monkeypatch, lambda _value: connection)

    def fake_run(*_args, **_kwargs):
        raise runtime.AwinImportFatalError(SimpleNamespace(), "secret database detail")

    monkeypatch.setattr(runtime, "run_awin_import", fake_run)

    exit_code = runtime.main([str(feed)])

    assert exit_code == 1
    output = capsys.readouterr()
    assert "AWIN import failed" in output.err
    assert "secret database detail" not in output.err
