"""Minimal productive CLI/runtime entry point for Product Scout V1."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence

from .openai_client import MODEL_NAME, MissingOpenAIAPIKeyError, OpenAIResponsesScoutClient
from .prompt_builder import load_prompt_template
from .result_repository import get_active_prompt_version
from .scout_service import run_product_scout

DATABASE_URL_ENV = "DATABASE_URL"
PROMPT_KEY = "product_scout"
MAX_LIMIT = 10

EXIT_OK = 0
EXIT_RUNTIME_ERROR = 1
EXIT_USAGE_ERROR = 2


class LimitArgumentError(ValueError):
    """Raised when --limit is outside the approved Product Scout V1 range."""


def _limit_value(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--limit must be an integer from 1 to 10") from exc
    if not 1 <= value <= MAX_LIMIT:
        raise argparse.ArgumentTypeError("--limit must be between 1 and 10")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Product Scout V1.")
    parser.add_argument(
        "--limit",
        required=True,
        type=_limit_value,
        help="maximum number of product variants to scout (1-10)",
    )
    return parser


def _print_error(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_prompt_path(repository_path: str) -> Path:
    path = Path(repository_path)
    if path.is_absolute():
        return path
    return _repository_root() / path


def main(argv: Sequence[str] | None = None) -> int:
    """Run Product Scout V1 and return a process exit code."""

    parser = _build_parser()
    try:
        args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as exc:
        # Keep argparse's standard help/error output while making main() testable.
        return int(exc.code)

    database_url = os.environ.get(DATABASE_URL_ENV, "").strip()
    if not database_url:
        _print_error("DATABASE_URL environment variable is required.")
        return EXIT_USAGE_ERROR

    try:
        client = OpenAIResponsesScoutClient()
    except MissingOpenAIAPIKeyError:
        _print_error("OPENAI_API_KEY environment variable is required.")
        return EXIT_USAGE_ERROR
    except ImportError:
        _print_error("OpenAI Python SDK is not installed. Install requirements.txt.")
        return EXIT_RUNTIME_ERROR

    try:
        import psycopg
    except ImportError:
        _print_error("Psycopg 3 is not installed. Install requirements.txt.")
        return EXIT_RUNTIME_ERROR

    try:
        with psycopg.connect(database_url) as connection:
            prompt_version = get_active_prompt_version(
                connection, prompt_key=PROMPT_KEY
            )
            prompt_path = _resolve_prompt_path(prompt_version.repository_path)
            prompt_template = load_prompt_template(prompt_path)

            total_candidates = 0
            total_selected = 0
            total_rejected = 0

            # Process one candidate at a time. Successful Scout results are excluded
            # by the repository query on the next iteration. This also lets the CLI
            # stop immediately on the first failed/invalid_output result.
            for _ in range(args.limit):
                stats = run_product_scout(
                    connection,
                    client=client,
                    prompt_template=prompt_template,
                    prompt_version_id=prompt_version.id,
                    model_name=MODEL_NAME,
                    limit=1,
                )

                if stats.candidates == 0:
                    break

                total_candidates += stats.candidates
                total_selected += stats.selected
                total_rejected += stats.rejected

                # Persist each completed variant independently so earlier successful
                # results remain durable if a later variant fails.
                connection.commit()

                if stats.failed:
                    _print_error(
                        "Product Scout stopped after a technical provider failure."
                    )
                    return EXIT_RUNTIME_ERROR
                if stats.invalid_output:
                    _print_error(
                        "Product Scout stopped after invalid structured output."
                    )
                    return EXIT_RUNTIME_ERROR

    except FileNotFoundError:
        _print_error("The active Product Scout prompt file does not exist.")
        return EXIT_RUNTIME_ERROR
    except (LookupError, OSError):
        _print_error("Product Scout runtime configuration could not be loaded.")
        return EXIT_RUNTIME_ERROR
    except psycopg.Error:
        _print_error("Product Scout database operation failed.")
        return EXIT_RUNTIME_ERROR
    except Exception:
        # Do not expose provider, database, prompt, or secret-bearing exception text.
        _print_error("Product Scout failed unexpectedly.")
        return EXIT_RUNTIME_ERROR

    print(
        "Product Scout completed successfully: "
        f"candidates={total_candidates} selected={total_selected} rejected={total_rejected}"
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
