BEGIN;

-- ============================================================================
-- Solvory
-- Migration: 004_unique_shop_external_offer.sql
-- Purpose: Enforce shop-local uniqueness of external offer identifiers.
--
-- Rule:
--   For offers with an external_offer_id, the combination
--   (shop_id, external_offer_id) must be unique.
--
-- NULL external_offer_id values remain allowed and are intentionally excluded
-- from this uniqueness rule.
-- ============================================================================

CREATE UNIQUE INDEX IF NOT EXISTS uq_offers_shop_external_offer_id
    ON offers (shop_id, external_offer_id)
    WHERE external_offer_id IS NOT NULL;

COMMIT;
