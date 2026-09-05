BEGIN;

-- ============================================================================
-- Solvory
-- Migration: 008_add_review_links.sql
-- Purpose: Persist revocable Review Link identities without storing plaintext
--          access tokens.
-- ============================================================================

CREATE TABLE IF NOT EXISTS review_links (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz,
    CONSTRAINT review_links_token_hash_format CHECK (
        token_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT review_links_revoke_order CHECK (
        revoked_at IS NULL OR revoked_at >= created_at
    )
);

COMMENT ON TABLE review_links IS
    'Revocable access identities for Human Review. Plaintext tokens are never persisted.';
COMMENT ON COLUMN review_links.token_hash IS
    'Lowercase SHA-256 hash of the complete cryptographically random Review Link token.';

COMMIT;
