"""Minimal command-line runtime entry point for the AWIN importer."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Sequence

from .import_awin import AwinImportFatalError, run_awin_import


DATABASE_URL_ENV = "DATABASE_URL"
IMPORTER_VERSION_ENV = "IMPORTER_VERSION"


def _print_error(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the AWIN importer from the command line and return a process exit code."""

    args = list(sys.argv[1:] if argv is None else argv)

    if len(args) != 1 or not args[0].strip():
        _print_error("AWIN feed path is required. Usage: python -m backend.importers.awin.run <feed-path>")
        return 2

    feed_path = Path(args[0]).expanduser()
    if not feed_path.is_file():
        _print_error(f"AWIN feed file does not exist: {feed_path}")
        return 2

    database_url = os.environ.get(DATABASE_URL_ENV, "").strip()
    if not database_url:
        _print_error("DATABASE_URL environment variable is required.")
        return 2

    importer_version = os.environ.get(IMPORTER_VERSION_ENV, "").strip()
    if not importer_version:
        _print_error("IMPORTER_VERSION environment variable is required.")
        return 2

    try:
        import psycopg
    except ImportError:
        _print_error("Psycopg 3 is not installed. Install the dependencies from requirements.txt.")
        return 1

    try:
        with psycopg.connect(database_url) as connection:
            result = run_awin_import(
                connection,
                feed_path,
                importer_version=importer_version,
            )
    except AwinImportFatalError:
        _print_error("AWIN import failed. Check the importer logs for non-sensitive error details.")
        return 1
    except (psycopg.Error, OSError):
        # Database and local I/O error messages may expose connection or local
        # environment details. Keep CLI output deliberately generic.
        _print_error("AWIN import could not be started or completed.")
        return 1

    print(
        "AWIN import completed successfully: "
        f"read={result.records_read} accepted={result.records_accepted} rejected={result.records_rejected}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
