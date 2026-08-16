from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from backend.scout import run as runtime


class FakePsycopgError(Exception):
    pass


class FakeConnection:
    def __init__(self):
        self.commit_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self):
        self.commit_calls += 1


def install_fake_psycopg(monkeypatch, connect):
    module = SimpleNamespace(connect=connect, Error=FakePsycopgError)
    monkeypatch.setitem(sys.modules, "psycopg", module)
    return module


class FakeClient:
    pass


def configure_runtime(monkeypatch, tmp_path, *, repository_path="prompts/product_scout_v1.md"):
    connection = FakeConnection()
    captured = {}
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@example.invalid/db")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    install_fake_psycopg(monkeypatch, lambda value: captured.setdefault("database_url", value) or connection)
    # The lambda above returns the URL because setdefault returns its value; replace
    # it with a normal function so the fake connection is returned.
    def fake_connect(value):
        captured["database_url"] = value
        return connection
    install_fake_psycopg(monkeypatch, fake_connect)

    client = FakeClient()
    monkeypatch.setattr(runtime, "OpenAIResponsesScoutClient", lambda: client)
    prompt_ref = SimpleNamespace(id="prompt-version-id", version_identifier="v1", repository_path=repository_path)
    monkeypatch.setattr(runtime, "get_active_prompt_version", lambda conn, prompt_key: prompt_ref)
    def fake_load_prompt(path):
        captured["prompt_path"] = path
        return "PROMPT"
    monkeypatch.setattr(runtime, "load_prompt_template", fake_load_prompt)
    return connection, client, captured


def stats(*, candidates=1, selected=0, rejected=0, failed=0, invalid_output=0):
    return SimpleNamespace(
        candidates=candidates,
        selected=selected,
        rejected=rejected,
        failed=failed,
        invalid_output=invalid_output,
    )


def test_limit_is_explicit_and_required(capsys):
    assert runtime.main([]) == 2
    assert "--limit" in capsys.readouterr().err


def test_limit_must_be_between_one_and_ten(capsys):
    assert runtime.main(["--limit", "0"]) == 2
    assert "between 1 and 10" in capsys.readouterr().err
    assert runtime.main(["--limit", "11"]) == 2


def test_missing_database_url_is_clear_and_does_not_log_secret(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    assert runtime.main(["--limit", "1"]) == 2
    output = capsys.readouterr()
    assert "DATABASE_URL environment variable is required" in output.err
    assert "openai-secret" not in output.err


def test_missing_openai_key_is_clear(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:db-secret@example.invalid/db")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    def missing_key_client():
        raise runtime.MissingOpenAIAPIKeyError("OPENAI_API_KEY environment variable is required")
    monkeypatch.setattr(runtime, "OpenAIResponsesScoutClient", missing_key_client)
    assert runtime.main(["--limit", "1"]) == 2
    output = capsys.readouterr()
    assert "OPENAI_API_KEY environment variable is required" in output.err
    assert "db-secret" not in output.err


def test_uses_active_prompt_repository_path_model_and_requested_limit(monkeypatch, tmp_path, capsys):
    connection, client, captured = configure_runtime(monkeypatch, tmp_path)
    calls = []

    def fake_run(conn, **kwargs):
        calls.append((conn, kwargs))
        return stats(candidates=1, selected=1) if len(calls) == 1 else stats(candidates=0)

    monkeypatch.setattr(runtime, "run_product_scout", fake_run)

    assert runtime.main(["--limit", "3"]) == 0
    assert len(calls) == 2
    assert calls[0][0] is connection
    assert calls[0][1]["client"] is client
    assert calls[0][1]["prompt_version_id"] == "prompt-version-id"
    assert calls[0][1]["model_name"] == "gpt-5.6-luna"
    assert calls[0][1]["limit"] == 1
    assert captured["prompt_path"] == Path(runtime.__file__).resolve().parents[2] / "prompts/product_scout_v1.md"
    assert connection.commit_calls == 1
    assert "candidates=1 selected=1 rejected=0" in capsys.readouterr().out


def test_processes_at_most_requested_limit(monkeypatch, tmp_path):
    connection, _client, _captured = configure_runtime(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(
        runtime,
        "run_product_scout",
        lambda conn, **kwargs: calls.append(kwargs) or stats(candidates=1, selected=1),
    )

    assert runtime.main(["--limit", "3"]) == 0
    assert len(calls) == 3
    assert connection.commit_calls == 3


def test_stops_immediately_on_first_failed_result_and_keeps_prior_success(monkeypatch, tmp_path, capsys):
    connection, _client, _captured = configure_runtime(monkeypatch, tmp_path)
    results = iter([stats(candidates=1, selected=1), stats(candidates=1, failed=1), stats(candidates=1, selected=1)])
    calls = []

    def fake_run(conn, **kwargs):
        calls.append(kwargs)
        return next(results)

    monkeypatch.setattr(runtime, "run_product_scout", fake_run)

    assert runtime.main(["--limit", "10"]) == 1
    assert len(calls) == 2
    assert connection.commit_calls == 2
    assert "technical provider failure" in capsys.readouterr().err


def test_stops_immediately_on_first_invalid_output(monkeypatch, tmp_path, capsys):
    connection, _client, _captured = configure_runtime(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(
        runtime,
        "run_product_scout",
        lambda conn, **kwargs: calls.append(kwargs) or stats(candidates=1, invalid_output=1),
    )

    assert runtime.main(["--limit", "10"]) == 1
    assert len(calls) == 1
    assert connection.commit_calls == 1
    assert "invalid structured output" in capsys.readouterr().err


def test_database_error_is_generic_and_does_not_log_secret(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:db-secret@example.invalid/db")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setattr(runtime, "OpenAIResponsesScoutClient", lambda: FakeClient())

    def connect(_value):
        raise FakePsycopgError("db-secret openai-secret")

    install_fake_psycopg(monkeypatch, connect)

    assert runtime.main(["--limit", "1"]) == 1
    output = capsys.readouterr()
    assert "database operation failed" in output.err
    assert "db-secret" not in output.err
    assert "openai-secret" not in output.err
