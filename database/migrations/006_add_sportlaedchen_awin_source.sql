BEGIN;

-- ============================================================================
-- Solvory
-- Migration: 006_add_sportlaedchen_awin_source.sql
-- Purpose: Add Sportlädchen DE and its AWIN product-feed source
--          reproducibly without modifying any other shop or source.
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
    'Sportlädchen DE',
    'DE',
    'Approved shop from the AWIN shop selection. Technical source: AWIN.',
    true,
    'verified',
    now()
WHERE NOT EXISTS (
    SELECT 1
    FROM shops
    WHERE lower(btrim(name)) = lower(btrim('Sportlädchen DE'))
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
    'AWIN Product Feed (58269)',
    'product_feed',
    'awin:advertiser:58269',
    'AWIN product feed for advertiser/program ID 58269.',
    'Mapped from the approved AWIN advertiser/program list.',
    true,
    'verified',
    now()
FROM shops AS s
WHERE lower(btrim(s.name)) = lower(btrim('Sportlädchen DE'))
  AND NOT EXISTS (
      SELECT 1
      FROM sources AS src
      WHERE src.shop_id = s.id
        AND src.source_type = 'product_feed'
        AND src.source_reference = 'awin:advertiser:58269'
  );

COMMIT;
