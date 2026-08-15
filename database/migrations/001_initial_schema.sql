BEGIN;

-- ============================================================================
-- Solvory
-- Migration: 001_initial_schema.sql
-- Purpose: Initial relational schema for the Solvory MVP core pipeline.
--
-- Principles:
--   - PostgreSQL is the authoritative operational database.
--   - No workspace / tenant model exists in the MVP.
--   - No global product status exists.
--   - Domain-specific state is stored in the responsible domain tables.
--   - Historical records are preserved and protected from cascading deletion.
--   - Product Evaluator results are not persisted as an operational entity.
--   - Change Detection and Source Health are intentionally excluded.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================================
-- SHOPS
-- ============================================================================

CREATE TABLE shops (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    canonical_domain text,
    country_code varchar(2),
    description text,
    is_active boolean NOT NULL DEFAULT true,
    verification_status text NOT NULL DEFAULT 'unverified',
    last_checked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz,
    CONSTRAINT shops_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT shops_domain_not_blank CHECK (canonical_domain IS NULL OR btrim(canonical_domain) <> ''),
    CONSTRAINT shops_country_code_format CHECK (country_code IS NULL OR country_code ~ '^[A-Z]{2}$'),
    CONSTRAINT shops_verification_status_check CHECK (verification_status IN ('unverified','verified','needs_review')),
    CONSTRAINT shops_archived_not_active CHECK (archived_at IS NULL OR is_active = false)
);

CREATE UNIQUE INDEX uq_shops_canonical_domain ON shops (lower(canonical_domain)) WHERE canonical_domain IS NOT NULL;
CREATE INDEX idx_shops_active ON shops (is_active) WHERE archived_at IS NULL;
COMMENT ON TABLE shops IS 'Fachliche Verkaufsplattformen bzw. Händler. Shops sind von technischen Datenquellen getrennt.';
COMMENT ON COLUMN shops.verification_status IS 'Einfacher MVP-Prüfzustand; keine umfangreiche Shop-State-Machine.';

-- ============================================================================
-- SOURCES
-- ============================================================================

CREATE TABLE sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    shop_id uuid NOT NULL,
    name text NOT NULL,
    source_type text NOT NULL,
    source_reference text,
    description text,
    coverage_description text,
    selection_reason text,
    is_active boolean NOT NULL DEFAULT true,
    verification_status text NOT NULL DEFAULT 'unverified',
    last_checked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz,
    CONSTRAINT sources_shop_fk FOREIGN KEY (shop_id) REFERENCES shops (id) ON DELETE RESTRICT,
    CONSTRAINT sources_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT sources_type_check CHECK (source_type IN ('api','product_feed','csv','xml','sitemap','structured_web','scraping','manual')),
    CONSTRAINT sources_reference_not_blank CHECK (source_reference IS NULL OR btrim(source_reference) <> ''),
    CONSTRAINT sources_verification_status_check CHECK (verification_status IN ('unverified','verified','needs_review')),
    CONSTRAINT sources_archived_not_active CHECK (archived_at IS NULL OR is_active = false),
    CONSTRAINT uq_sources_id_shop UNIQUE (id, shop_id),
    CONSTRAINT uq_sources_shop_name UNIQUE (shop_id, name)
);

CREATE UNIQUE INDEX uq_sources_reference ON sources (shop_id, source_type, source_reference) WHERE source_reference IS NOT NULL;
CREATE INDEX idx_sources_shop ON sources (shop_id);
CREATE INDEX idx_sources_active ON sources (shop_id, is_active) WHERE archived_at IS NULL;
COMMENT ON TABLE sources IS 'Technische Datenzugänge eines Shops, z. B. API, Feed, CSV, XML, Sitemap oder Scraping. Keine Secrets speichern.';
COMMENT ON COLUMN sources.source_reference IS 'Öffentliche oder nicht geheime technische Referenz. Zugangsdaten und Tokens gehören ausdrücklich nicht hierher.';

-- ============================================================================
-- PRODUCT FAMILIES
-- ============================================================================

CREATE TABLE product_families (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    brand_name text,
    category text,
    description text,
    core_function text,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz,
    CONSTRAINT product_families_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT product_families_archived_not_active CHECK (archived_at IS NULL OR is_active = false)
);

CREATE INDEX idx_product_families_brand ON product_families (brand_name);
CREATE INDEX idx_product_families_category ON product_families (category);
CREATE INDEX idx_product_families_active ON product_families (is_active) WHERE archived_at IS NULL;
COMMENT ON TABLE product_families IS 'Fachlicher Zusammenhang verwandter Produktvarianten. Enthält keinen globalen Pipeline-Status.';

-- ============================================================================
-- PRODUCT VARIANTS
-- ============================================================================

CREATE TABLE product_variants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    product_family_id uuid NOT NULL,
    name text NOT NULL,
    model_name text,
    gtin text,
    mpn text,
    description text,
    variant_attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz,
    CONSTRAINT product_variants_family_fk FOREIGN KEY (product_family_id) REFERENCES product_families (id) ON DELETE RESTRICT,
    CONSTRAINT product_variants_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT product_variants_attributes_object CHECK (jsonb_typeof(variant_attributes) = 'object'),
    CONSTRAINT product_variants_archived_not_active CHECK (archived_at IS NULL OR is_active = false)
);

CREATE INDEX idx_product_variants_family ON product_variants (product_family_id);
CREATE INDEX idx_product_variants_gtin ON product_variants (gtin) WHERE gtin IS NOT NULL;
CREATE INDEX idx_product_variants_mpn ON product_variants (mpn) WHERE mpn IS NOT NULL;
CREATE INDEX idx_product_variants_active ON product_variants (is_active) WHERE archived_at IS NULL;
COMMENT ON TABLE product_variants IS 'Konkrete fachlich relevante Varianten einer Produktfamilie. Zentrale Einheit für Scout und Human Review.';
COMMENT ON COLUMN product_variants.variant_attributes IS 'Nur für heterogene variantenspezifische Merkmale; kein Ersatz für reguläre relationale Kernfelder.';

-- ============================================================================
-- OFFERS
-- ============================================================================

CREATE TABLE offers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    product_variant_id uuid NOT NULL,
    shop_id uuid NOT NULL,
    external_offer_id text,
    shop_title text NOT NULL,
    shop_description text,
    product_url text NOT NULL,
    current_price numeric(18,4),
    currency_code varchar(3),
    availability_status text NOT NULL DEFAULT 'unknown',
    delivery_region text,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz,
    CONSTRAINT offers_variant_fk FOREIGN KEY (product_variant_id) REFERENCES product_variants (id) ON DELETE RESTRICT,
    CONSTRAINT offers_shop_fk FOREIGN KEY (shop_id) REFERENCES shops (id) ON DELETE RESTRICT,
    CONSTRAINT offers_title_not_blank CHECK (btrim(shop_title) <> ''),
    CONSTRAINT offers_url_not_blank CHECK (btrim(product_url) <> ''),
    CONSTRAINT offers_external_id_not_blank CHECK (external_offer_id IS NULL OR btrim(external_offer_id) <> ''),
    CONSTRAINT offers_price_nonnegative CHECK (current_price IS NULL OR current_price >= 0),
    CONSTRAINT offers_price_requires_currency CHECK (current_price IS NULL OR currency_code IS NOT NULL),
    CONSTRAINT offers_currency_format CHECK (currency_code IS NULL OR currency_code ~ '^[A-Z]{3}$'),
    CONSTRAINT offers_availability_check CHECK (availability_status IN ('unknown','in_stock','out_of_stock','preorder','backorder','unavailable','discontinued')),
    CONSTRAINT offers_seen_order CHECK (last_seen_at >= first_seen_at),
    CONSTRAINT offers_archived_not_active CHECK (archived_at IS NULL OR is_active = false),
    CONSTRAINT uq_offers_id_shop UNIQUE (id, shop_id)
);

CREATE INDEX idx_offers_variant ON offers (product_variant_id);
CREATE INDEX idx_offers_shop ON offers (shop_id);
CREATE INDEX idx_offers_shop_active ON offers (shop_id, is_active) WHERE archived_at IS NULL;
CREATE INDEX idx_offers_last_seen ON offers (last_seen_at DESC);
CREATE INDEX idx_offers_external_offer_id ON offers (shop_id, external_offer_id) WHERE external_offer_id IS NOT NULL;
COMMENT ON TABLE offers IS 'Konkrete Verkaufsmöglichkeit einer Produktvariante bei genau einem Shop. Enthält den aktuellen operativen Shopzustand.';
COMMENT ON COLUMN offers.external_offer_id IS 'Optionale shopbezogene Kennung. Quellenabhängige Identitäten werden zusätzlich über offer_source_records geführt.';

-- ============================================================================
-- OFFER SOURCE RECORDS
-- ============================================================================

CREATE TABLE offer_source_records (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    offer_id uuid NOT NULL,
    source_id uuid NOT NULL,
    shop_id uuid NOT NULL,
    external_record_key text NOT NULL,
    external_reference text,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz,
    CONSTRAINT offer_source_records_offer_shop_fk FOREIGN KEY (offer_id, shop_id) REFERENCES offers (id, shop_id) ON DELETE RESTRICT,
    CONSTRAINT offer_source_records_source_shop_fk FOREIGN KEY (source_id, shop_id) REFERENCES sources (id, shop_id) ON DELETE RESTRICT,
    CONSTRAINT offer_source_records_key_not_blank CHECK (btrim(external_record_key) <> ''),
    CONSTRAINT offer_source_records_external_reference_not_blank CHECK (external_reference IS NULL OR btrim(external_reference) <> ''),
    CONSTRAINT offer_source_records_seen_order CHECK (last_seen_at >= first_seen_at),
    CONSTRAINT offer_source_records_archived_not_active CHECK (archived_at IS NULL OR is_active = false),
    CONSTRAINT uq_offer_source_record_source_key UNIQUE (source_id, external_record_key),
    CONSTRAINT uq_offer_source_record_identity UNIQUE (id, source_id, offer_id)
);

CREATE INDEX idx_offer_source_records_offer ON offer_source_records (offer_id);
CREATE INDEX idx_offer_source_records_source ON offer_source_records (source_id);
COMMENT ON TABLE offer_source_records IS 'Verknüpft eine quellspezifische externe Datensatzidentität mit einem internen Angebot. Mehrere Sources desselben Shops können dasselbe Offer beschreiben.';

-- ============================================================================
-- PROMPT VERSIONS
-- ============================================================================

CREATE TABLE prompt_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_key text NOT NULL,
    version_identifier text NOT NULL,
    repository_path text NOT NULL,
    git_commit_sha text NOT NULL,
    content_hash varchar(64) NOT NULL,
    is_active boolean NOT NULL DEFAULT false,
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz,
    CONSTRAINT prompt_versions_key_not_blank CHECK (btrim(prompt_key) <> ''),
    CONSTRAINT prompt_versions_version_not_blank CHECK (btrim(version_identifier) <> ''),
    CONSTRAINT prompt_versions_repo_path_not_blank CHECK (btrim(repository_path) <> ''),
    CONSTRAINT prompt_versions_commit_not_blank CHECK (btrim(git_commit_sha) <> ''),
    CONSTRAINT prompt_versions_hash_format CHECK (content_hash ~ '^[0-9A-Fa-f]{64}$'),
    CONSTRAINT prompt_versions_archived_not_active CHECK (archived_at IS NULL OR is_active = false),
    CONSTRAINT uq_prompt_versions_key_version UNIQUE (prompt_key, version_identifier)
);

CREATE UNIQUE INDEX uq_prompt_versions_one_active ON prompt_versions (prompt_key) WHERE is_active = true AND archived_at IS NULL;
CREATE INDEX idx_prompt_versions_commit ON prompt_versions (git_commit_sha);
COMMENT ON TABLE prompt_versions IS 'Operative Referenz auf unveränderliche, in GitHub versionierte Prompt-Stände. GitHub bleibt führende Quelle der Promptdateien.';

-- ============================================================================
-- AUTOMATION RUNS
-- ============================================================================

CREATE TABLE automation_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_type text NOT NULL,
    triggered_by text,
    prompt_version_id uuid,
    model_name text,
    model_version text,
    technical_status text NOT NULL DEFAULT 'planned',
    started_at timestamptz,
    finished_at timestamptz,
    error_category text,
    error_summary text,
    retry_of_run_id uuid,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT automation_runs_prompt_fk FOREIGN KEY (prompt_version_id) REFERENCES prompt_versions (id) ON DELETE RESTRICT,
    CONSTRAINT automation_runs_retry_fk FOREIGN KEY (retry_of_run_id) REFERENCES automation_runs (id) ON DELETE RESTRICT,
    CONSTRAINT automation_runs_type_check CHECK (run_type IN ('import','scout','affiliate_enrichment','content_creation','publishing','performance_import','product_evaluator','other')),
    CONSTRAINT automation_runs_status_check CHECK (technical_status IN ('planned','running','succeeded','partially_succeeded','failed','cancelled')),
    CONSTRAINT automation_runs_metadata_object CHECK (jsonb_typeof(metadata) = 'object'),
    CONSTRAINT automation_runs_retry_not_self CHECK (retry_of_run_id IS NULL OR retry_of_run_id <> id),
    CONSTRAINT automation_runs_time_order CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at),
    CONSTRAINT automation_runs_status_times CHECK (
        (technical_status = 'planned' AND started_at IS NULL AND finished_at IS NULL)
        OR (technical_status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL)
        OR (technical_status IN ('succeeded','partially_succeeded','failed','cancelled') AND started_at IS NOT NULL AND finished_at IS NOT NULL)
    )
);

CREATE INDEX idx_automation_runs_prompt ON automation_runs (prompt_version_id) WHERE prompt_version_id IS NOT NULL;
CREATE INDEX idx_automation_runs_retry ON automation_runs (retry_of_run_id) WHERE retry_of_run_id IS NOT NULL;
CREATE INDEX idx_automation_runs_type_started ON automation_runs (run_type, started_at DESC);
CREATE INDEX idx_automation_runs_status_started ON automation_runs (technical_status, started_at DESC);
COMMENT ON TABLE automation_runs IS 'Technische Ausführungshistorie. Fachliche Ergebnisse bleiben in ihren jeweiligen Domänentabellen.';
COMMENT ON COLUMN automation_runs.metadata IS 'Begrenzte variable technische Metadaten. Keine Secrets, vollständigen Dialoge oder fachlichen Kernobjekte speichern.';

-- ============================================================================
-- IMPORT RUNS
-- ============================================================================

CREATE TABLE import_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id uuid NOT NULL,
    automation_run_id uuid,
    importer_version text NOT NULL,
    technical_status text NOT NULL DEFAULT 'planned',
    started_at timestamptz,
    finished_at timestamptz,
    records_received bigint NOT NULL DEFAULT 0,
    records_processed bigint NOT NULL DEFAULT 0,
    records_created bigint NOT NULL DEFAULT 0,
    records_updated bigint NOT NULL DEFAULT 0,
    records_rejected bigint NOT NULL DEFAULT 0,
    error_summary text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT import_runs_source_fk FOREIGN KEY (source_id) REFERENCES sources (id) ON DELETE RESTRICT,
    CONSTRAINT import_runs_automation_fk FOREIGN KEY (automation_run_id) REFERENCES automation_runs (id) ON DELETE RESTRICT,
    CONSTRAINT import_runs_importer_version_not_blank CHECK (btrim(importer_version) <> ''),
    CONSTRAINT import_runs_status_check CHECK (technical_status IN ('planned','running','succeeded','partially_succeeded','failed','cancelled')),
    CONSTRAINT import_runs_counts_nonnegative CHECK (records_received >= 0 AND records_processed >= 0 AND records_created >= 0 AND records_updated >= 0 AND records_rejected >= 0),
    CONSTRAINT import_runs_time_order CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at),
    CONSTRAINT import_runs_status_times CHECK (
        (technical_status = 'planned' AND started_at IS NULL AND finished_at IS NULL)
        OR (technical_status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL)
        OR (technical_status IN ('succeeded','partially_succeeded','failed','cancelled') AND started_at IS NOT NULL AND finished_at IS NOT NULL)
    ),
    CONSTRAINT uq_import_runs_id_source UNIQUE (id, source_id)
);

CREATE INDEX idx_import_runs_source_started ON import_runs (source_id, started_at DESC);
CREATE INDEX idx_import_runs_status_started ON import_runs (technical_status, started_at DESC);
CREATE INDEX idx_import_runs_automation ON import_runs (automation_run_id) WHERE automation_run_id IS NOT NULL;
COMMENT ON TABLE import_runs IS 'Historischer technischer Importlauf aus genau einer Source. Importfehler sind keine fachlichen Produktentscheidungen.';

-- ============================================================================
-- OFFER OBSERVATIONS
-- ============================================================================

CREATE TABLE offer_observations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    import_run_id uuid NOT NULL,
    offer_source_record_id uuid NOT NULL,
    source_id uuid NOT NULL,
    offer_id uuid NOT NULL,
    observed_shop_title text,
    observed_shop_description text,
    observed_product_url text,
    observed_price numeric(18,4),
    currency_code varchar(3),
    availability_status text,
    record_hash varchar(64),
    processing_status text NOT NULL DEFAULT 'processed',
    observed_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT offer_observations_import_source_fk FOREIGN KEY (import_run_id, source_id) REFERENCES import_runs (id, source_id) ON DELETE RESTRICT,
    CONSTRAINT offer_observations_source_record_fk FOREIGN KEY (offer_source_record_id, source_id, offer_id) REFERENCES offer_source_records (id, source_id, offer_id) ON DELETE RESTRICT,
    CONSTRAINT offer_observations_price_nonnegative CHECK (observed_price IS NULL OR observed_price >= 0),
    CONSTRAINT offer_observations_price_requires_currency CHECK (observed_price IS NULL OR currency_code IS NOT NULL),
    CONSTRAINT offer_observations_currency_format CHECK (currency_code IS NULL OR currency_code ~ '^[A-Z]{3}$'),
    CONSTRAINT offer_observations_availability_check CHECK (availability_status IS NULL OR availability_status IN ('unknown','in_stock','out_of_stock','preorder','backorder','unavailable','discontinued')),
    CONSTRAINT offer_observations_hash_format CHECK (record_hash IS NULL OR record_hash ~ '^[0-9A-Fa-f]{64}$'),
    CONSTRAINT offer_observations_processing_status_check CHECK (processing_status IN ('processed','created','updated','unchanged','rejected')),
    CONSTRAINT uq_offer_observation_run_record UNIQUE (import_run_id, offer_source_record_id)
);

CREATE INDEX idx_offer_observations_offer_time ON offer_observations (offer_id, observed_at DESC);
CREATE INDEX idx_offer_observations_import_run ON offer_observations (import_run_id);
CREATE INDEX idx_offer_observations_source_record ON offer_observations (offer_source_record_id);
COMMENT ON TABLE offer_observations IS 'Historische Beobachtung eines Angebots innerhalb eines Importlaufs. Bewahrt Preis-, Verfügbarkeits- und URL-Historie ohne Überschreiben.';

-- ============================================================================
-- PRODUCT IMAGES
-- ============================================================================

CREATE TABLE product_images (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    offer_id uuid NOT NULL,
    source_id uuid NOT NULL,
    shop_id uuid NOT NULL,
    offer_source_record_id uuid,
    external_url text NOT NULL,
    internal_storage_location text,
    content_hash varchar(64),
    position integer NOT NULL,
    is_primary boolean NOT NULL DEFAULT false,
    usability_status text NOT NULL DEFAULT 'unknown',
    is_active boolean NOT NULL DEFAULT true,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz,
    CONSTRAINT product_images_offer_shop_fk FOREIGN KEY (offer_id, shop_id) REFERENCES offers (id, shop_id) ON DELETE RESTRICT,
    CONSTRAINT product_images_source_shop_fk FOREIGN KEY (source_id, shop_id) REFERENCES sources (id, shop_id) ON DELETE RESTRICT,
    CONSTRAINT product_images_source_record_fk FOREIGN KEY (offer_source_record_id, source_id, offer_id) REFERENCES offer_source_records (id, source_id, offer_id) ON DELETE RESTRICT,
    CONSTRAINT product_images_url_not_blank CHECK (btrim(external_url) <> ''),
    CONSTRAINT product_images_storage_not_blank CHECK (internal_storage_location IS NULL OR btrim(internal_storage_location) <> ''),
    CONSTRAINT product_images_hash_format CHECK (content_hash IS NULL OR content_hash ~ '^[0-9A-Fa-f]{64}$'),
    CONSTRAINT product_images_position_positive CHECK (position > 0),
    CONSTRAINT product_images_usability_status_check CHECK (usability_status IN ('unknown','usable','unusable','unreachable','replaced')),
    CONSTRAINT product_images_seen_order CHECK (last_seen_at >= first_seen_at),
    CONSTRAINT product_images_primary_requires_active CHECK (is_primary = false OR (is_active = true AND archived_at IS NULL)),
    CONSTRAINT product_images_archived_not_active CHECK (archived_at IS NULL OR is_active = false)
);

CREATE UNIQUE INDEX uq_product_images_identity ON product_images (offer_id, source_id, external_url, COALESCE(content_hash, ''));
CREATE UNIQUE INDEX uq_product_images_active_position ON product_images (offer_id, position) WHERE is_active = true AND archived_at IS NULL;
CREATE UNIQUE INDEX uq_product_images_active_primary ON product_images (offer_id) WHERE is_primary = true AND is_active = true AND archived_at IS NULL;
CREATE INDEX idx_product_images_offer ON product_images (offer_id);
CREATE INDEX idx_product_images_source ON product_images (source_id);
CREATE INDEX idx_product_images_source_record ON product_images (offer_source_record_id) WHERE offer_source_record_id IS NOT NULL;
COMMENT ON TABLE product_images IS 'Alle erfassten Produktbilder mit Angebots- und Quellenherkunft. Historisch verwendete Bilder werden nicht stillschweigend ersetzt.';
COMMENT ON COLUMN product_images.internal_storage_location IS 'Optionale spätere interne Speicherreferenz; externe URLs bleiben als Herkunft erhalten.';

-- ============================================================================
-- SCOUT RESULTS
-- ============================================================================

CREATE TABLE scout_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    product_variant_id uuid NOT NULL,
    prompt_version_id uuid NOT NULL,
    automation_run_id uuid,
    model_name text NOT NULL,
    model_version text,
    technical_status text NOT NULL DEFAULT 'requested',
    decision text,
    reason text,
    started_at timestamptz,
    finished_at timestamptz,
    error_code text,
    error_summary text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT scout_results_variant_fk FOREIGN KEY (product_variant_id) REFERENCES product_variants (id) ON DELETE RESTRICT,
    CONSTRAINT scout_results_prompt_fk FOREIGN KEY (prompt_version_id) REFERENCES prompt_versions (id) ON DELETE RESTRICT,
    CONSTRAINT scout_results_automation_fk FOREIGN KEY (automation_run_id) REFERENCES automation_runs (id) ON DELETE RESTRICT,
    CONSTRAINT scout_results_model_not_blank CHECK (btrim(model_name) <> ''),
    CONSTRAINT scout_results_status_check CHECK (technical_status IN ('requested','running','succeeded','failed','invalid_output')),
    CONSTRAINT scout_results_decision_check CHECK (decision IS NULL OR decision IN ('selected','rejected')),
    CONSTRAINT scout_results_success_requires_decision CHECK (technical_status <> 'succeeded' OR (decision IS NOT NULL AND reason IS NOT NULL AND btrim(reason) <> '')),
    CONSTRAINT scout_results_failure_has_no_decision CHECK (technical_status = 'succeeded' OR decision IS NULL),
    CONSTRAINT scout_results_time_order CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at),
    CONSTRAINT scout_results_status_times CHECK (
        (technical_status = 'requested' AND started_at IS NULL AND finished_at IS NULL)
        OR (technical_status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL)
        OR (technical_status IN ('succeeded','failed','invalid_output') AND started_at IS NOT NULL AND finished_at IS NOT NULL)
    ),
    CONSTRAINT uq_scout_results_id_variant UNIQUE (id, product_variant_id)
);

CREATE UNIQUE INDEX uq_scout_results_one_success_per_variant ON scout_results (product_variant_id) WHERE technical_status = 'succeeded';
CREATE INDEX idx_scout_results_variant_created ON scout_results (product_variant_id, created_at DESC);
CREATE INDEX idx_scout_results_prompt ON scout_results (prompt_version_id);
CREATE INDEX idx_scout_results_automation ON scout_results (automation_run_id) WHERE automation_run_id IS NOT NULL;
CREATE INDEX idx_scout_results_status ON scout_results (technical_status);
COMMENT ON TABLE scout_results IS 'Historische Product-Scout-Ausführungen. Technische Fehler dürfen niemals als fachliche Ablehnung gespeichert werden.';

-- ============================================================================
-- REVIEW SESSIONS
-- ============================================================================

CREATE TABLE review_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    status text NOT NULL DEFAULT 'prepared',
    diversity_context text,
    started_at timestamptz,
    completed_at timestamptz,
    cancelled_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz,
    CONSTRAINT review_sessions_status_check CHECK (status IN ('prepared','open','in_progress','completed','cancelled')),
    CONSTRAINT review_sessions_completed_timestamp CHECK (status <> 'completed' OR completed_at IS NOT NULL),
    CONSTRAINT review_sessions_cancelled_timestamp CHECK (status <> 'cancelled' OR cancelled_at IS NOT NULL)
);

CREATE INDEX idx_review_sessions_status ON review_sessions (status, created_at DESC);
COMMENT ON TABLE review_sessions IS 'Menschliche Review-Runden. Produktzuordnungen werden separat in review_session_items gespeichert.';

-- ============================================================================
-- REVIEW SESSION ITEMS
-- ============================================================================

CREATE TABLE review_session_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    review_session_id uuid NOT NULL,
    product_variant_id uuid NOT NULL,
    scout_result_id uuid NOT NULL,
    position integer NOT NULL,
    assigned_at timestamptz NOT NULL DEFAULT now(),
    released_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT review_session_items_session_fk FOREIGN KEY (review_session_id) REFERENCES review_sessions (id) ON DELETE RESTRICT,
    CONSTRAINT review_session_items_variant_fk FOREIGN KEY (product_variant_id) REFERENCES product_variants (id) ON DELETE RESTRICT,
    CONSTRAINT review_session_items_scout_variant_fk FOREIGN KEY (scout_result_id, product_variant_id) REFERENCES scout_results (id, product_variant_id) ON DELETE RESTRICT,
    CONSTRAINT review_session_items_position_positive CHECK (position > 0),
    CONSTRAINT review_session_items_release_order CHECK (released_at IS NULL OR released_at >= assigned_at),
    CONSTRAINT uq_review_session_variant UNIQUE (review_session_id, product_variant_id),
    CONSTRAINT uq_review_session_position UNIQUE (review_session_id, position),
    CONSTRAINT uq_review_session_item_id_variant UNIQUE (id, product_variant_id)
);

CREATE UNIQUE INDEX uq_review_session_items_one_active_session ON review_session_items (product_variant_id) WHERE released_at IS NULL;
CREATE INDEX idx_review_session_items_session_position ON review_session_items (review_session_id, position);
CREATE INDEX idx_review_session_items_scout ON review_session_items (scout_result_id);
COMMENT ON TABLE review_session_items IS 'Explizite Session-Zuordnung einer Produktvariante. Existiert bereits vor einer menschlichen Entscheidung.';

-- ============================================================================
-- REVIEWS
-- ============================================================================

CREATE TABLE reviews (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    review_session_item_id uuid NOT NULL,
    decision text NOT NULL,
    reason text,
    decided_by_user_ref text NOT NULL,
    decided_at timestamptz NOT NULL DEFAULT now(),
    supersedes_review_id uuid,
    correction_reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT reviews_session_item_fk FOREIGN KEY (review_session_item_id) REFERENCES review_session_items (id) ON DELETE RESTRICT,
    CONSTRAINT reviews_decision_check CHECK (decision IN ('hit','no_hit','later')),
    CONSTRAINT reviews_user_ref_not_blank CHECK (btrim(decided_by_user_ref) <> ''),
    CONSTRAINT reviews_supersedes_not_self CHECK (supersedes_review_id IS NULL OR supersedes_review_id <> id),
    CONSTRAINT reviews_correction_requires_reason CHECK (supersedes_review_id IS NULL OR (correction_reason IS NOT NULL AND btrim(correction_reason) <> '')),
    CONSTRAINT uq_reviews_id_session_item UNIQUE (id, review_session_item_id),
    CONSTRAINT uq_reviews_superseded_once UNIQUE (supersedes_review_id),
    CONSTRAINT reviews_supersedes_same_item_fk FOREIGN KEY (supersedes_review_id, review_session_item_id) REFERENCES reviews (id, review_session_item_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX uq_reviews_one_root_per_session_item ON reviews (review_session_item_id) WHERE supersedes_review_id IS NULL;
CREATE INDEX idx_reviews_session_item_decided ON reviews (review_session_item_id, decided_at DESC);
CREATE INDEX idx_reviews_supersedes ON reviews (supersedes_review_id) WHERE supersedes_review_id IS NOT NULL;
CREATE INDEX idx_reviews_decision ON reviews (decision, decided_at DESC);
COMMENT ON TABLE reviews IS 'Historische menschliche Entscheidungen HIT, NO HIT oder SPÄTER. Alte Entscheidungen werden bei Korrekturen nicht überschrieben.';
COMMENT ON COLUMN reviews.decided_by_user_ref IS 'Stabile externe Benutzerreferenz. Das vollständige Authentifizierungs- und Rollenmodell ist nicht Bestandteil von Migration 001.';

-- ============================================================================
-- REVIEW BLOCKS
-- ============================================================================

CREATE TABLE review_blocks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    product_variant_id uuid NOT NULL,
    review_session_item_id uuid NOT NULL,
    origin_review_id uuid NOT NULL,
    block_type text NOT NULL DEFAULT 'no_hit',
    blocked_at timestamptz NOT NULL DEFAULT now(),
    released_at timestamptz,
    released_by_user_ref text,
    release_reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT review_blocks_item_variant_fk FOREIGN KEY (review_session_item_id, product_variant_id) REFERENCES review_session_items (id, product_variant_id) ON DELETE RESTRICT,
    CONSTRAINT review_blocks_origin_review_fk FOREIGN KEY (origin_review_id, review_session_item_id) REFERENCES reviews (id, review_session_item_id) ON DELETE RESTRICT,
    CONSTRAINT review_blocks_type_check CHECK (block_type = 'no_hit'),
    CONSTRAINT review_blocks_release_order CHECK (released_at IS NULL OR released_at >= blocked_at),
    CONSTRAINT review_blocks_release_metadata CHECK (
        (released_at IS NULL AND released_by_user_ref IS NULL AND release_reason IS NULL)
        OR (released_at IS NOT NULL AND released_by_user_ref IS NOT NULL AND btrim(released_by_user_ref) <> '' AND release_reason IS NOT NULL AND btrim(release_reason) <> '')
    )
);

CREATE UNIQUE INDEX uq_review_blocks_active_no_hit ON review_blocks (product_variant_id) WHERE released_at IS NULL;
CREATE INDEX idx_review_blocks_variant ON review_blocks (product_variant_id);
CREATE INDEX idx_review_blocks_origin_review ON review_blocks (origin_review_id);
COMMENT ON TABLE review_blocks IS 'Explizite Human-Review-Sperren. NO HIT blockiert eine Produktvariante dauerhaft im regulären Auswahlprozess.';
COMMENT ON COLUMN review_blocks.released_at IS 'Nur für ausdrückliche administrative Ausnahmefälle vorgesehen; keine automatische NO-HIT-Wiederaufnahme.';

-- ============================================================================
-- AFFILIATE OFFERS
-- ============================================================================

CREATE TABLE affiliate_offers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    offer_id uuid NOT NULL,
    automation_run_id uuid,
    affiliate_network text NOT NULL,
    affiliate_program text NOT NULL,
    external_program_id text,
    target_url text NOT NULL,
    tracking_url text NOT NULL,
    commission_type text NOT NULL DEFAULT 'unknown',
    commission_value numeric(18,6),
    commission_currency_code varchar(3),
    cookie_duration_days integer,
    region_codes text[] NOT NULL DEFAULT ARRAY[]::text[],
    verification_status text NOT NULL DEFAULT 'unverified',
    tracking_status text NOT NULL DEFAULT 'unknown',
    checked_at timestamptz,
    valid_from timestamptz,
    valid_until timestamptz,
    is_active boolean NOT NULL DEFAULT true,
    is_preferred boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz,
    CONSTRAINT affiliate_offers_offer_fk FOREIGN KEY (offer_id) REFERENCES offers (id) ON DELETE RESTRICT,
    CONSTRAINT affiliate_offers_automation_fk FOREIGN KEY (automation_run_id) REFERENCES automation_runs (id) ON DELETE RESTRICT,
    CONSTRAINT affiliate_offers_network_not_blank CHECK (btrim(affiliate_network) <> ''),
    CONSTRAINT affiliate_offers_program_not_blank CHECK (btrim(affiliate_program) <> ''),
    CONSTRAINT affiliate_offers_target_url_not_blank CHECK (btrim(target_url) <> ''),
    CONSTRAINT affiliate_offers_tracking_url_not_blank CHECK (btrim(tracking_url) <> ''),
    CONSTRAINT affiliate_offers_external_program_not_blank CHECK (external_program_id IS NULL OR btrim(external_program_id) <> ''),
    CONSTRAINT affiliate_offers_commission_type_check CHECK (commission_type IN ('percentage','fixed','variable','unknown')),
    CONSTRAINT affiliate_offers_commission_nonnegative CHECK (commission_value IS NULL OR commission_value >= 0),
    CONSTRAINT affiliate_offers_percentage_range CHECK (commission_type <> 'percentage' OR commission_value IS NULL OR commission_value <= 100),
    CONSTRAINT affiliate_offers_fixed_requires_currency CHECK (commission_type <> 'fixed' OR commission_value IS NULL OR commission_currency_code IS NOT NULL),
    CONSTRAINT affiliate_offers_currency_format CHECK (commission_currency_code IS NULL OR commission_currency_code ~ '^[A-Z]{3}$'),
    CONSTRAINT affiliate_offers_cookie_nonnegative CHECK (cookie_duration_days IS NULL OR cookie_duration_days >= 0),
    CONSTRAINT affiliate_offers_verification_status_check CHECK (verification_status IN ('unverified','verified','needs_review','invalid')),
    CONSTRAINT affiliate_offers_tracking_status_check CHECK (tracking_status IN ('unknown','unverified','verified','problematic')),
    CONSTRAINT affiliate_offers_validity_order CHECK (valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from),
    CONSTRAINT affiliate_offers_preferred_requires_valid_state CHECK (is_preferred = false OR (is_active = true AND verification_status = 'verified' AND archived_at IS NULL)),
    CONSTRAINT affiliate_offers_archived_not_active CHECK (archived_at IS NULL OR is_active = false),
    CONSTRAINT uq_affiliate_offers_id_offer UNIQUE (id, offer_id)
);

CREATE UNIQUE INDEX uq_affiliate_offers_one_preferred_per_offer ON affiliate_offers (offer_id) WHERE is_preferred = true;
CREATE INDEX idx_affiliate_offers_offer ON affiliate_offers (offer_id);
CREATE INDEX idx_affiliate_offers_offer_active ON affiliate_offers (offer_id, is_active) WHERE archived_at IS NULL;
CREATE INDEX idx_affiliate_offers_valid_until ON affiliate_offers (valid_until) WHERE valid_until IS NOT NULL;
CREATE INDEX idx_affiliate_offers_automation ON affiliate_offers (automation_run_id) WHERE automation_run_id IS NOT NULL;
COMMENT ON TABLE affiliate_offers IS 'Affiliate-spezifische Monetarisierung eines konkreten normalen Angebots. Ein Offer kann mehrere Affiliate Offers besitzen.';
COMMENT ON COLUMN affiliate_offers.region_codes IS 'ISO-3166-1-Alpha-2-Ländercodes. Leeres Array bedeutet, dass im MVP keine explizite regionale Einschränkung gespeichert ist.';

-- ============================================================================
-- CONTENT PACKAGES
-- ============================================================================

CREATE TABLE content_packages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    product_variant_id uuid NOT NULL,
    platform text NOT NULL DEFAULT 'pinterest',
    content_type text NOT NULL DEFAULT 'pin',
    created_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz,
    CONSTRAINT content_packages_variant_fk FOREIGN KEY (product_variant_id) REFERENCES product_variants (id) ON DELETE RESTRICT,
    CONSTRAINT content_packages_platform_check CHECK (platform = 'pinterest'),
    CONSTRAINT content_packages_type_check CHECK (content_type = 'pin')
);

CREATE INDEX idx_content_packages_variant ON content_packages (product_variant_id);
COMMENT ON TABLE content_packages IS 'Logisches produktbezogenes Content-Paket. Affiliate Enrichment ist keine Voraussetzung für die Content-Erstellung.';

-- ============================================================================
-- CONTENT VERSIONS
-- ============================================================================

CREATE TABLE content_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    content_package_id uuid NOT NULL,
    version_number integer NOT NULL,
    pin_title text,
    description text,
    hook text,
    overlay_text text,
    call_to_action text,
    hashtags text[] NOT NULL DEFAULT ARRAY[]::text[],
    image_concept text,
    product_image_id uuid,
    prompt_version_id uuid NOT NULL,
    automation_run_id uuid,
    model_name text NOT NULL,
    model_version text,
    technical_status text NOT NULL DEFAULT 'requested',
    approval_status text NOT NULL DEFAULT 'draft',
    generated_at timestamptz,
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT content_versions_package_fk FOREIGN KEY (content_package_id) REFERENCES content_packages (id) ON DELETE RESTRICT,
    CONSTRAINT content_versions_image_fk FOREIGN KEY (product_image_id) REFERENCES product_images (id) ON DELETE RESTRICT,
    CONSTRAINT content_versions_prompt_fk FOREIGN KEY (prompt_version_id) REFERENCES prompt_versions (id) ON DELETE RESTRICT,
    CONSTRAINT content_versions_automation_fk FOREIGN KEY (automation_run_id) REFERENCES automation_runs (id) ON DELETE RESTRICT,
    CONSTRAINT content_versions_version_positive CHECK (version_number > 0),
    CONSTRAINT content_versions_model_not_blank CHECK (btrim(model_name) <> ''),
    CONSTRAINT content_versions_technical_status_check CHECK (technical_status IN ('requested','running','succeeded','failed','invalid_output')),
    CONSTRAINT content_versions_approval_status_check CHECK (approval_status IN ('draft','pending_review','approved','rejected','archived')),
    CONSTRAINT content_versions_success_requires_content CHECK (
        technical_status <> 'succeeded'
        OR (
            pin_title IS NOT NULL AND btrim(pin_title) <> ''
            AND description IS NOT NULL AND btrim(description) <> ''
            AND hook IS NOT NULL AND btrim(hook) <> ''
            AND overlay_text IS NOT NULL AND btrim(overlay_text) <> ''
            AND call_to_action IS NOT NULL AND btrim(call_to_action) <> ''
            AND cardinality(hashtags) > 0
            AND (product_image_id IS NOT NULL OR (image_concept IS NOT NULL AND btrim(image_concept) <> ''))
        )
    ),
    CONSTRAINT content_versions_approved_requires_success CHECK (approval_status <> 'approved' OR (technical_status = 'succeeded' AND approved_at IS NOT NULL)),
    CONSTRAINT uq_content_versions_package_version UNIQUE (content_package_id, version_number)
);

CREATE INDEX idx_content_versions_package_version ON content_versions (content_package_id, version_number DESC);
CREATE INDEX idx_content_versions_image ON content_versions (product_image_id) WHERE product_image_id IS NOT NULL;
CREATE INDEX idx_content_versions_prompt ON content_versions (prompt_version_id);
CREATE INDEX idx_content_versions_automation ON content_versions (automation_run_id) WHERE automation_run_id IS NOT NULL;
CREATE INDEX idx_content_versions_approval ON content_versions (approval_status);
COMMENT ON TABLE content_versions IS 'Versionierte Pinterest-Content-Fassungen mit getrenntem technischem Erstellungsstatus und fachlichem Freigabestatus.';

-- ============================================================================
-- PUBLICATIONS
-- ============================================================================

CREATE TABLE publications (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    content_version_id uuid NOT NULL,
    offer_id uuid NOT NULL,
    affiliate_offer_id uuid,
    platform text NOT NULL DEFAULT 'pinterest',
    publication_mode text NOT NULL,
    status text NOT NULL DEFAULT 'draft',
    target_url_snapshot text NOT NULL,
    idempotency_key text NOT NULL,
    scheduled_at timestamptz,
    published_at timestamptz,
    external_pinterest_id text,
    published_url text,
    removed_at timestamptz,
    archived_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT publications_content_version_fk FOREIGN KEY (content_version_id) REFERENCES content_versions (id) ON DELETE RESTRICT,
    CONSTRAINT publications_offer_fk FOREIGN KEY (offer_id) REFERENCES offers (id) ON DELETE RESTRICT,
    CONSTRAINT publications_affiliate_offer_fk FOREIGN KEY (affiliate_offer_id, offer_id) REFERENCES affiliate_offers (id, offer_id) ON DELETE RESTRICT,
    CONSTRAINT publications_platform_check CHECK (platform = 'pinterest'),
    CONSTRAINT publications_mode_check CHECK (publication_mode IN ('immediate','scheduled')),
    CONSTRAINT publications_status_check CHECK (status IN ('draft','queued','scheduled','publishing','published','failed','unknown_external_state','removed','archived')),
    CONSTRAINT publications_target_url_not_blank CHECK (btrim(target_url_snapshot) <> ''),
    CONSTRAINT publications_idempotency_key_not_blank CHECK (btrim(idempotency_key) <> ''),
    CONSTRAINT publications_scheduled_requires_time CHECK (publication_mode <> 'scheduled' OR scheduled_at IS NOT NULL),
    CONSTRAINT publications_scheduled_status_requires_time CHECK (status <> 'scheduled' OR scheduled_at IS NOT NULL),
    CONSTRAINT publications_published_requires_external_data CHECK (
        status <> 'published'
        OR (
            published_at IS NOT NULL
            AND external_pinterest_id IS NOT NULL AND btrim(external_pinterest_id) <> ''
            AND published_url IS NOT NULL AND btrim(published_url) <> ''
        )
    ),
    CONSTRAINT publications_removed_requires_timestamp CHECK (status <> 'removed' OR removed_at IS NOT NULL),
    CONSTRAINT publications_archived_requires_timestamp CHECK (status <> 'archived' OR archived_at IS NOT NULL),
    CONSTRAINT uq_publications_idempotency_key UNIQUE (idempotency_key)
);

CREATE UNIQUE INDEX uq_publications_external_pinterest_id ON publications (external_pinterest_id) WHERE external_pinterest_id IS NOT NULL;
CREATE INDEX idx_publications_content_version ON publications (content_version_id);
CREATE INDEX idx_publications_offer ON publications (offer_id);
CREATE INDEX idx_publications_affiliate_offer ON publications (affiliate_offer_id) WHERE affiliate_offer_id IS NOT NULL;
CREATE INDEX idx_publications_status_schedule ON publications (status, scheduled_at);
CREATE INDEX idx_publications_published_at ON publications (published_at DESC) WHERE published_at IS NOT NULL;
COMMENT ON TABLE publications IS 'Logischer Pinterest-Veröffentlichungsauftrag. Der tatsächlich verwendete Ziel-Link wird als unveränderliche historische Momentaufnahme gespeichert.';
COMMENT ON COLUMN publications.target_url_snapshot IS 'Konkreter beim Publishing verwendeter Ziel-Link. Publishing ohne nichtleeren Ziel-Link ist nicht möglich.';
COMMENT ON COLUMN publications.idempotency_key IS 'Stabiler anwendungsseitiger Schlüssel zum Schutz vor unbeabsichtigt doppelten logischen Publishing-Aufträgen.';

-- ============================================================================
-- PUBLICATION ATTEMPTS
-- ============================================================================

CREATE TABLE publication_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    publication_id uuid NOT NULL,
    automation_run_id uuid,
    attempt_number integer NOT NULL,
    technical_status text NOT NULL DEFAULT 'started',
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    error_code text,
    error_summary text,
    external_reference text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT publication_attempts_publication_fk FOREIGN KEY (publication_id) REFERENCES publications (id) ON DELETE RESTRICT,
    CONSTRAINT publication_attempts_automation_fk FOREIGN KEY (automation_run_id) REFERENCES automation_runs (id) ON DELETE RESTRICT,
    CONSTRAINT publication_attempts_number_positive CHECK (attempt_number > 0),
    CONSTRAINT publication_attempts_status_check CHECK (technical_status IN ('started','succeeded','failed','unknown_external_state')),
    CONSTRAINT publication_attempts_time_order CHECK (finished_at IS NULL OR finished_at >= started_at),
    CONSTRAINT publication_attempts_terminal_finished CHECK (technical_status = 'started' OR finished_at IS NOT NULL),
    CONSTRAINT uq_publication_attempt_number UNIQUE (publication_id, attempt_number)
);

CREATE INDEX idx_publication_attempts_publication ON publication_attempts (publication_id, attempt_number);
CREATE INDEX idx_publication_attempts_status ON publication_attempts (technical_status);
CREATE INDEX idx_publication_attempts_automation ON publication_attempts (automation_run_id) WHERE automation_run_id IS NOT NULL;
COMMENT ON TABLE publication_attempts IS 'Technische Pinterest-Publishing-Versuche einschließlich Retries. Mehrere technische Versuche gehören zu derselben logischen Publication.';

-- ============================================================================
-- PERFORMANCE DAILY
-- ============================================================================

CREATE TABLE performance_daily (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    publication_id uuid NOT NULL,
    automation_run_id uuid,
    metric_date date NOT NULL,
    impressions bigint NOT NULL DEFAULT 0,
    saves bigint NOT NULL DEFAULT 0,
    outbound_clicks bigint NOT NULL DEFAULT 0,
    affiliate_clicks bigint NOT NULL DEFAULT 0,
    sales bigint NOT NULL DEFAULT 0,
    revenue numeric(18,4) NOT NULL DEFAULT 0,
    commission numeric(18,4) NOT NULL DEFAULT 0,
    currency_code varchar(3),
    data_source text NOT NULL,
    source_updated_at timestamptz,
    imported_at timestamptz NOT NULL DEFAULT now(),
    quality_status text NOT NULL DEFAULT 'unknown',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT performance_daily_publication_fk FOREIGN KEY (publication_id) REFERENCES publications (id) ON DELETE RESTRICT,
    CONSTRAINT performance_daily_automation_fk FOREIGN KEY (automation_run_id) REFERENCES automation_runs (id) ON DELETE RESTRICT,
    CONSTRAINT performance_daily_counts_nonnegative CHECK (impressions >= 0 AND saves >= 0 AND outbound_clicks >= 0 AND affiliate_clicks >= 0 AND sales >= 0),
    CONSTRAINT performance_daily_money_nonnegative CHECK (revenue >= 0 AND commission >= 0),
    CONSTRAINT performance_daily_currency_format CHECK (currency_code IS NULL OR currency_code ~ '^[A-Z]{3}$'),
    CONSTRAINT performance_daily_money_requires_currency CHECK ((revenue = 0 AND commission = 0) OR currency_code IS NOT NULL),
    CONSTRAINT performance_daily_source_not_blank CHECK (btrim(data_source) <> ''),
    CONSTRAINT performance_daily_quality_status_check CHECK (quality_status IN ('unknown','complete','incomplete','corrected')),
    CONSTRAINT uq_performance_daily_publication_date UNIQUE (publication_id, metric_date)
);

CREATE INDEX idx_performance_daily_metric_date ON performance_daily (metric_date);
CREATE INDEX idx_performance_daily_publication_date ON performance_daily (publication_id, metric_date DESC);
CREATE INDEX idx_performance_daily_automation ON performance_daily (automation_run_id) WHERE automation_run_id IS NOT NULL;
COMMENT ON TABLE performance_daily IS 'Tägliche Performance je Veröffentlichung. metric_date übernimmt im MVP den Berichtstag des jeweiligen Ursprungssystems.';
COMMENT ON COLUMN performance_daily.data_source IS 'Nachvollziehbare Herkunft der Tageswerte. Eine spätere Trennung von Pinterest- und Affiliate-Messdomänen bleibt möglich.';

-- ============================================================================
-- APP SETTINGS
-- ============================================================================

CREATE TABLE app_settings (
    setting_key text PRIMARY KEY,
    setting_value jsonb NOT NULL,
    description text,
    is_active boolean NOT NULL DEFAULT true,
    updated_by_user_ref text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT app_settings_key_not_blank CHECK (btrim(setting_key) <> ''),
    CONSTRAINT app_settings_updated_by_not_blank CHECK (updated_by_user_ref IS NULL OR btrim(updated_by_user_ref) <> '')
);

CREATE INDEX idx_app_settings_active ON app_settings (is_active);
COMMENT ON TABLE app_settings IS 'Einfache nicht geheime globale Anwendungseinstellungen des einzigen MVP-Datenkontexts.';
COMMENT ON COLUMN app_settings.setting_value IS 'Darf keine Passwörter, API-Schlüssel, Tokens oder sonstige Secrets enthalten.';

-- ============================================================================
-- FINAL SCHEMA NOTES
-- ============================================================================

COMMENT ON DATABASE CURRENT_DATABASE() IS
    'Solvory operational PostgreSQL database. Domain states are intentionally distributed across import, scout, review, affiliate, content, publishing and automation domains; there is no global product status.';

COMMIT;
