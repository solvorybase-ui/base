"""PostgreSQL repository operations for the AWIN importer.

The repository deliberately contains no import orchestration and no transaction
ownership. Every function receives an existing Psycopg 3 connection; callers
control batch transactions, commits, rollbacks, and savepoints.

All SQL is static and feed/user values are passed as query parameters.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping, Protocol, Sequence


class CursorLike(Protocol):
    def __enter__(self) -> "CursorLike": ...
    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...
    def execute(self, query: str, params: Sequence[object] | None = None) -> Any: ...
    def fetchone(self) -> Sequence[object] | None: ...
    def fetchall(self) -> list[Sequence[object]]: ...


class ConnectionLike(Protocol):
    def cursor(self) -> CursorLike: ...


class SourceNotFoundError(LookupError):
    """Raised when no active AWIN source exists for a merchant/advertiser ID."""


class SourceAmbiguityError(LookupError):
    """Raised when more than one active AWIN source matches one advertiser ID."""


class VariantAmbiguityError(LookupError):
    """Raised when a strong variant identity matches more than one candidate."""


@dataclass(frozen=True, slots=True)
class SourceRef:
    id: str
    shop_id: str


@dataclass(frozen=True, slots=True)
class VariantMatch:
    id: str
    product_family_id: str


def _one_or_none(rows: Sequence[Sequence[object]], *, ambiguity_error: type[LookupError], message: str) -> Sequence[object] | None:
    if not rows:
        return None
    if len(rows) > 1:
        raise ambiguity_error(message)
    return rows[0]


def get_source_for_merchant(connection: ConnectionLike, merchant_id: str) -> SourceRef:
    """Resolve one active AWIN product-feed source from the approved reference format."""

    source_reference = f"awin:advertiser:{merchant_id}"
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, shop_id
            FROM sources
            WHERE source_type = 'product_feed'
              AND source_reference = %s
              AND is_active = true
              AND archived_at IS NULL
            ORDER BY id
            """,
            (source_reference,),
        )
        rows = cursor.fetchall()

    row = _one_or_none(
        rows,
        ambiguity_error=SourceAmbiguityError,
        message=f"multiple active AWIN sources found for merchant_id {merchant_id!r}",
    )
    if row is None:
        raise SourceNotFoundError(f"no active AWIN source found for merchant_id {merchant_id!r}")
    return SourceRef(id=str(row[0]), shop_id=str(row[1]))


def create_import_run(
    connection: ConnectionLike,
    *,
    source_id: str,
    importer_version: str,
    automation_run_id: str | None = None,
) -> str:
    """Create one running import_run and return its id."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO import_runs (
                source_id,
                automation_run_id,
                importer_version,
                technical_status,
                started_at
            )
            VALUES (%s, %s, %s, 'running', now())
            RETURNING id
            """,
            (source_id, automation_run_id, importer_version),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("import_run INSERT returned no id")
    return str(row[0])


def finish_import_run(
    connection: ConnectionLike,
    *,
    import_run_id: str,
    technical_status: str,
    records_received: int,
    records_processed: int,
    records_created: int,
    records_updated: int,
    records_rejected: int,
    error_summary: str | None = None,
) -> None:
    """Finish an import_run with terminal status and final counters."""

    terminal_statuses = {"succeeded", "partially_succeeded", "failed", "cancelled"}
    if technical_status not in terminal_statuses:
        raise ValueError(f"technical_status must be terminal, got {technical_status!r}")
    counts = (records_received, records_processed, records_created, records_updated, records_rejected)
    if any(value < 0 for value in counts):
        raise ValueError("import_run counters must be non-negative")

    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE import_runs
            SET technical_status = %s,
                finished_at = now(),
                records_received = %s,
                records_processed = %s,
                records_created = %s,
                records_updated = %s,
                records_rejected = %s,
                error_summary = %s,
                updated_at = now()
            WHERE id = %s
            """,
            (
                technical_status,
                records_received,
                records_processed,
                records_created,
                records_updated,
                records_rejected,
                error_summary,
                import_run_id,
            ),
        )


def find_offer(connection: ConnectionLike, *, shop_id: str, external_offer_id: str) -> Mapping[str, object] | None:
    """Find an offer by the database-enforced shop-local external identity."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, product_variant_id, shop_id, external_offer_id,
                   shop_title, shop_description, product_url,
                   current_price, currency_code, availability_status
            FROM offers
            WHERE shop_id = %s
              AND external_offer_id = %s
            """,
            (shop_id, external_offer_id),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    keys = (
        "id", "product_variant_id", "shop_id", "external_offer_id", "shop_title",
        "shop_description", "product_url", "current_price", "currency_code",
        "availability_status",
    )
    return dict(zip(keys, row, strict=True))


def create_product_family(
    connection: ConnectionLike,
    *,
    name: str,
    brand_name: str | None,
    category: str | None,
    description: str | None,
) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO product_families (name, brand_name, category, description)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (name, brand_name, category, description),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("product_family INSERT returned no id")
    return str(row[0])


def create_product_variant(
    connection: ConnectionLike,
    *,
    product_family_id: str,
    name: str,
    model_name: str | None,
    gtin: str | None,
    mpn: str | None,
    description: str | None,
    variant_attributes: Mapping[str, object] | None = None,
) -> str:
    attributes_json = json.dumps(dict(variant_attributes or {}), ensure_ascii=False, separators=(",", ":"))
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO product_variants (
                product_family_id, name, model_name, gtin, mpn, description, variant_attributes
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING id
            """,
            (product_family_id, name, model_name, gtin, mpn, description, attributes_json),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("product_variant INSERT returned no id")
    return str(row[0])


def find_product_variant(
    connection: ConnectionLike,
    *,
    gtin: str | None,
    brand_name: str | None,
    mpn: str | None,
) -> VariantMatch | None:
    """Find a variant only through approved strong identities.

    GTIN is attempted first. If absent, Brand + MPN is attempted. Multiple
    candidates are always reported as ambiguity and are never merged.
    """

    if gtin is not None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, product_family_id
                FROM product_variants
                WHERE gtin = %s
                  AND is_active = true
                  AND archived_at IS NULL
                ORDER BY id
                """,
                (gtin,),
            )
            rows = cursor.fetchall()
        row = _one_or_none(
            rows,
            ambiguity_error=VariantAmbiguityError,
            message=f"multiple active product_variants found for gtin {gtin!r}",
        )
        if row is None:
            return None
        return VariantMatch(id=str(row[0]), product_family_id=str(row[1]))

    if brand_name is not None and mpn is not None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT pv.id, pv.product_family_id
                FROM product_variants AS pv
                JOIN product_families AS pf ON pf.id = pv.product_family_id
                WHERE pf.brand_name = %s
                  AND pv.mpn = %s
                  AND pv.is_active = true
                  AND pv.archived_at IS NULL
                  AND pf.is_active = true
                  AND pf.archived_at IS NULL
                ORDER BY pv.id
                """,
                (brand_name, mpn),
            )
            rows = cursor.fetchall()
        row = _one_or_none(
            rows,
            ambiguity_error=VariantAmbiguityError,
            message=f"multiple active product_variants found for brand {brand_name!r} and mpn {mpn!r}",
        )
        if row is None:
            return None
        return VariantMatch(id=str(row[0]), product_family_id=str(row[1]))

    return None


def upsert_offer(
    connection: ConnectionLike,
    *,
    product_variant_id: str,
    shop_id: str,
    external_offer_id: str,
    shop_title: str,
    shop_description: str | None,
    product_url: str,
    current_price: Decimal | None,
    currency_code: str | None,
    availability_status: str,
) -> str:
    """Create/update current offer state while preserving its existing variant identity."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO offers (
                product_variant_id, shop_id, external_offer_id, shop_title,
                shop_description, product_url, current_price, currency_code,
                availability_status, last_seen_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (shop_id, external_offer_id)
                WHERE external_offer_id IS NOT NULL
            DO UPDATE SET
                shop_title = EXCLUDED.shop_title,
                shop_description = EXCLUDED.shop_description,
                product_url = EXCLUDED.product_url,
                current_price = EXCLUDED.current_price,
                currency_code = EXCLUDED.currency_code,
                availability_status = EXCLUDED.availability_status,
                last_seen_at = now(),
                updated_at = now()
            RETURNING id
            """,
            (
                product_variant_id,
                shop_id,
                external_offer_id,
                shop_title,
                shop_description,
                product_url,
                current_price,
                currency_code,
                availability_status,
            ),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("offer upsert returned no id")
    return str(row[0])


def get_or_create_offer_source_record(
    connection: ConnectionLike,
    *,
    offer_id: str,
    source_id: str,
    shop_id: str,
    external_record_key: str,
    external_reference: str | None,
) -> str:
    """Create/reuse one source record by (source_id, external_record_key)."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO offer_source_records (
                offer_id, source_id, shop_id, external_record_key,
                external_reference, last_seen_at
            )
            VALUES (%s, %s, %s, %s, %s, now())
            ON CONFLICT (source_id, external_record_key)
            DO UPDATE SET
                last_seen_at = now(),
                updated_at = now()
            WHERE offer_source_records.offer_id = EXCLUDED.offer_id
              AND offer_source_records.shop_id = EXCLUDED.shop_id
            RETURNING id
            """,
            (offer_id, source_id, shop_id, external_record_key, external_reference),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("offer_source_record identity conflicts with a different offer or shop")
    return str(row[0])


def create_offer_observation(
    connection: ConnectionLike,
    *,
    import_run_id: str,
    offer_source_record_id: str,
    source_id: str,
    offer_id: str,
    observed_shop_title: str | None,
    observed_shop_description: str | None,
    observed_product_url: str | None,
    observed_price: Decimal | None,
    currency_code: str | None,
    availability_status: str | None,
    record_hash: str | None = None,
    processing_status: str = "processed",
    observed_at: datetime | None = None,
) -> str:
    """Append one historical observation. Existing observations are never updated."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO offer_observations (
                import_run_id, offer_source_record_id, source_id, offer_id,
                observed_shop_title, observed_shop_description,
                observed_product_url, observed_price, currency_code,
                availability_status, record_hash, processing_status, observed_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, now()))
            RETURNING id
            """,
            (
                import_run_id,
                offer_source_record_id,
                source_id,
                offer_id,
                observed_shop_title,
                observed_shop_description,
                observed_product_url,
                observed_price,
                currency_code,
                availability_status,
                record_hash,
                processing_status,
                observed_at,
            ),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("offer_observation INSERT returned no id")
    return str(row[0])


def get_or_create_product_image(
    connection: ConnectionLike,
    *,
    offer_id: str,
    source_id: str,
    shop_id: str,
    offer_source_record_id: str | None,
    external_url: str,
    position: int,
    is_primary: bool,
) -> str:
    """Create/reuse the exact externally observed image URL for an offer/source."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO product_images (
                offer_id, source_id, shop_id, offer_source_record_id,
                external_url, position, is_primary, last_seen_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (offer_id, source_id, external_url, COALESCE(content_hash, ''))
            DO UPDATE SET
                last_seen_at = now(),
                updated_at = now()
            RETURNING id
            """,
            (offer_id, source_id, shop_id, offer_source_record_id, external_url, position, is_primary),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("product_image upsert returned no id")
    return str(row[0])
