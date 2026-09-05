from pathlib import Path


MIGRATION = Path("database/migrations/008_add_review_links.sql")


def migration_sql():
    return " ".join(MIGRATION.read_text(encoding="utf-8").split())


def test_review_link_migration_is_idempotent_by_definition():
    assert "CREATE TABLE IF NOT EXISTS review_links" in migration_sql()


def test_review_link_migration_has_minimal_columns():
    sql = migration_sql()
    assert "id uuid PRIMARY KEY DEFAULT gen_random_uuid()" in sql
    assert "token_hash text NOT NULL UNIQUE" in sql
    assert "created_at timestamptz NOT NULL DEFAULT now()" in sql
    assert "revoked_at timestamptz" in sql


def test_review_link_migration_enforces_sha256_format():
    sql = migration_sql()
    assert "token_hash ~ '^[0-9a-f]{64}$'" in sql


def test_review_link_migration_does_not_change_other_tables():
    sql = migration_sql()
    assert "ALTER TABLE" not in sql
    assert "CREATE TABLE IF NOT EXISTS review_links" in sql
    assert "CREATE TABLE IF NOT EXISTS users" not in sql
