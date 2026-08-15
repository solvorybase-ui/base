INSERT INTO shops (
    name,
    country_code,
    description,
    is_active,
    verification_status,
    last_checked_at
)
SELECT
    awin_shop.name,
    awin_shop.country_code,
    'Approved shop from the AWIN shop selection. Technical AWIN source records are intentionally created in a later migration.',
    true,
    'verified',
    now()
FROM (
    VALUES
        ('Laifen Inc.', NULL),
        ('Leifheit DE', 'DE'),
        ('3DMakerpro', NULL),
        ('3pagen DE', 'DE'),
        ('Aosom ES', 'ES'),
        ('MiniFinder SE', 'SE'),
        ('Olight DE', 'DE'),
        ('Globus Baumarkt DE', 'DE'),
        ('Toolbrothers DE', 'DE'),
        ('Happy Lamps DE', 'DE'),

        ('Trocafy BR', 'BR'),
        ('Dalfilo CH', 'CH'),
        ('JAPANNEXT FR', 'FR'),
        ('Vertbaudet AT', 'AT'),
        ('cambuy DE', 'DE'),
        ('ab-in-die-BOX DE', 'DE'),
        ('alternate FR', 'FR'),
        ('VBS-Hobby NL/AT', NULL),
        ('watt24 DE', 'DE'),
        ('Lefton Home', NULL),
        ('Acer CH/ES/FR', NULL),
        ('Floordirekt DE', 'DE'),
        ('Masterchef (US)', 'US'),
        ('Marigold Living', NULL),
        ('Panasonic BR', 'BR'),
        ('Gigantec BR', 'BR'),
        ('HABA USA', 'US'),
        ('Wedgwood (US)', 'US'),

        ('Eminent Luggage', NULL),
        ('INWARIA DE', 'DE'),
        ('Clove Technology', NULL),
        ('myphotobook FR', 'FR'),
        ('Poltronesofà at SCS', NULL)
) AS awin_shop(name, country_code)
WHERE NOT EXISTS (
    SELECT 1
    FROM shops existing_shop
    WHERE lower(btrim(existing_shop.name)) = lower(btrim(awin_shop.name))
);