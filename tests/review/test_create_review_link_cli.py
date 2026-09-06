from contextlib import nullcontext
import sys
from types import SimpleNamespace

import backend.web.create_review_link as cli
from backend.review.link_service import CreatedReviewLink


def configure_cli(monkeypatch, *, public_origin=None):
    monkeypatch.setenv("DATABASE_URL", "postgresql://not-used")
    if public_origin is None:
        monkeypatch.delenv("REVIEW_PUBLIC_ORIGIN", raising=False)
    else:
        monkeypatch.setenv("REVIEW_PUBLIC_ORIGIN", public_origin)
    monkeypatch.setitem(
        sys.modules,
        "psycopg",
        SimpleNamespace(connect=lambda database_url: nullcontext(object())),
    )
    monkeypatch.setattr(
        cli,
        "create_review_link",
        lambda connection: CreatedReviewLink("link-1", "one-time-token"),
    )


def test_cli_prints_fragment_path_without_configured_origin(monkeypatch, capsys):
    configure_cli(monkeypatch)

    assert cli.main() == 0

    captured = capsys.readouterr()
    assert captured.out.strip() == "/#one-time-token"
    assert captured.err == ""


def test_cli_prints_fragment_url_with_normalized_origin(monkeypatch, capsys):
    configure_cli(monkeypatch, public_origin="https://Review.Example/")

    assert cli.main() == 0

    captured = capsys.readouterr()
    assert captured.out.strip() == "https://review.example/#one-time-token"


def test_cli_rejects_unsafe_origin_before_creating_link(monkeypatch, capsys):
    configure_cli(monkeypatch, public_origin="http://review.example")
    called = False

    def must_not_create(connection):
        nonlocal called
        called = True

    monkeypatch.setattr(cli, "create_review_link", must_not_create)

    assert cli.main() == 2
    assert called is False
    assert "invalid" in capsys.readouterr().err
