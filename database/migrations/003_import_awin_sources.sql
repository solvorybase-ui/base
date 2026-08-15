-- ============================================================================
-- Solvory
-- Migration: 003_import_awin_sources.sql
-- Purpose: Create one technical AWIN product-feed source for each uniquely
--          mappable AWIN shop imported by migration 002.
--
-- Notes:
--   - Uses only tables and columns defined by 001_initial_schema.sql.
--   - No feed URLs are invented.
--   - source_reference stores a stable, non-secret AWIN advertiser reference.
--   - Idempotent: existing matching sources are not duplicated.
--   - No products, offers or affiliate offers are created.
-- ============================================================================

-- Not imported because migration 002 combines or abbreviates multiple AWIN
-- programmes and therefore no single programme ID can be assigned safely:
--
-- 3DMakerpro:
--   AWIN 48247 = 3DMakerpro (Global)
--   AWIN 70050 = 3DMakerpro (EU)
--
-- VBS-Hobby NL/AT:
--   AWIN 20570 = VBS-Hobby NL
--   AWIN 16477 = vbs-hobby AT
--
-- Acer CH/ES/FR:
--   Multiple country-specific Acer AWIN programmes exist.
--   Migration 002 stores them as one combined shop, so no single advertiser ID
--   is assigned here.

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
    'AWIN Product Feed (' || m.awin_program_id || ')',
    'product_feed',
    'awin:advertiser:' || m.awin_program_id,
    'AWIN product feed for advertiser/program ID ' || m.awin_program_id || '.',
    'Mapped from the approved AWIN advertiser/program list.',
    true,
    'verified',
    now()
FROM (
    VALUES
        ('Laifen Inc.',         '37938'),
        ('Leifheit DE',         '19753'),
        ('3pagen DE',           '14305'),
        ('Aosom ES',            '17092'),
        ('MiniFinder SE',       '26197'),
        ('Olight DE',           '19759'),
        ('Globus Baumarkt DE',  '11830'),
        ('Toolbrothers DE',     '102589'),
        ('Happy Lamps DE',      '29733'),

        ('Trocafy BR',          '51277'),
        ('Dalfilo CH',          '84521'),
        ('JAPANNEXT FR',        '83047'),
        ('Vertbaudet AT',       '118293'),
        ('cambuy DE',           '13433'),
        ('ab-in-die-BOX DE',    '105797'),
        ('alternate FR',        '11424'),
        ('watt24 DE',           '16905'),
        ('Lefton Home',         '97661'),
        ('Floordirekt DE',      '73387'),
        ('Masterchef (US)',     '83593'),
        ('Marigold Living',     '54601'),
        ('Panasonic BR',        '78382'),
        ('Gigantec BR',         '115463'),
        ('HABA USA',            '70014'),
        ('Wedgwood (US)',       '58345'),

        ('Eminent Luggage',     '26821'),
        ('INWARIA DE',          '20674'),
        ('Clove Technology',    '20676'),
        ('myphotobook FR',      '22757'),
        ('Poltronesofà at SCS', '3682')
) AS m(shop_name, awin_program_id)
JOIN shops AS s
    ON lower(btrim(s.name)) = lower(btrim(m.shop_name))
WHERE NOT EXISTS (
    SELECT 1
    FROM sources AS existing_source
    WHERE existing_source.shop_id = s.id
      AND existing_source.source_type = 'product_feed'
      AND existing_source.source_reference =
          'awin:advertiser:' || m.awin_program_id
);
