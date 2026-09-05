BEGIN;

-- ============================================================================
-- Solvory
-- Migration: 007_add_modellbau_universe_awin_source.sql
-- Purpose: Add Modellbau-Universe – die Adresse für Modellbau and its AWIN
--          product-feed source reproducibly without modifying any other shop
--          or source.
-- ============================================================================

INSERT INTO shops (
    name,
    country_code,
    description,
    is_active,
    verification_status,
    last_checked_at
)
SELECT
    'Modellbau-Universe – die Adresse für Modellbau',
    'DE',
    'Approved shop from the AWIN shop selection. Technical source: AWIN.',
    true,
    'verified',
    now()
WHERE NOT EXISTS (
    SELECT 1
    FROM shops
    WHERE lower(btrim(name)) = lower(btrim('Modellbau-Universe – die Adresse für Modellbau'))
);

INSERT INTO sources (
    shop_id,
    name,
    source_type,
    source_reference,
    description,
    selection_reason,
    is_active,
    verification_status,
    last_checked_at
)
SELECT
    s.id,
    'AWIN Product Feed (17471)',
    'product_feed',
    'awin:advertiser:17471',
    'AWIN product feed for advertiser/program ID 17471.',
    'Mapped from the approved AWIN advertiser/program list.',
    true,
    'verified',
    now()
FROM shops AS s
WHERE lower(btrim(s.name)) = lower(btrim('Modellbau-Universe – die Adresse für Modellbau'))
  AND NOT EXISTS (
      SELECT 1
      FROM sources AS src
      WHERE src.shop_id = s.id
        AND src.source_type = 'product_feed'
        AND src.source_reference = 'awin:advertiser:17471'
  );

COMMIT;
