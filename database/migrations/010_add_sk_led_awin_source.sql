BEGIN;

-- ============================================================================
-- Solvory
-- Migration: 010_add_sk_led_awin_source.sql
-- Purpose: Add SK-LED and its AWIN product-feed source reproducibly without
--          modifying any other shop or source.
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
    'SK-LED',
    'DE',
    'Approved shop from the AWIN shop selection. Technical source: AWIN.',
    true,
    'verified',
    now()
WHERE NOT EXISTS (
    SELECT 1
    FROM shops
    WHERE lower(btrim(name)) = lower(btrim('SK-LED'))
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
    'AWIN Product Feed (120289)',
    'product_feed',
    'awin:advertiser:120289',
    'AWIN product feed for advertiser/program ID 120289.',
    'Mapped from the approved AWIN advertiser/program list.',
    true,
    'verified',
    now()
FROM shops AS s
WHERE lower(btrim(s.name)) = lower(btrim('SK-LED'))
  AND NOT EXISTS (
      SELECT 1
      FROM sources AS src
      WHERE src.shop_id = s.id
        AND src.source_type = 'product_feed'
        AND src.source_reference = 'awin:advertiser:120289'
  );

COMMIT;
