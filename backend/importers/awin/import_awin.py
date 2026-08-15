"""AWIN import orchestration.

This module connects the approved parser, normalizer, and repository layers.
It owns import-level transaction boundaries, batch handling, record isolation,
and import-run statistics. It contains no schema creation, enrichment, AI, or
affiliate-offer logic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Mapping, Protocol

from .normalizer import AwinNormalizationError, AwinNormalizedRecord, normalize_awin_record
from .parser import AwinParserError, iter_awin_rows
from . import repository


DEFAULT_BATCH_SIZE = 250


class TransactionContext(Protocol):
    def __enter__(self) -> object: ...
    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool | None: ...


class ConnectionLike(repository.ConnectionLike, Protocol):
    def transaction(self) -> TransactionContext: ...


@dataclass(slots=True)
class SourceImportStats:
    source_id: str
    shop_id: str
    import_run_id: str
    records_received: int = 0
    records_processed: int = 0
    records_created: int = 0
    records_updated: int = 0
    records_rejected: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ImportResult:
    records_read: int
    records_accepted: int
    records_rejected: int
    source_runs: tuple[SourceImportStats, ...]


@dataclass(frozen=True, slots=True)
class _PreparedRecord:
    normalized: AwinNormalizedRecord
    source: repository.SourceRef
    stats: SourceImportStats


class AwinImportFatalError(RuntimeError):
    """Raised after active import runs have been marked as failed."""

    def __init__(self, result: ImportResult, message: str) -> None:
        self.result = result
        super().__init__(message)


def _iter_batches(rows: Iterator[Mapping[str, str]], batch_size: int) -> Iterator[list[Mapping[str, str]]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    batch: list[Mapping[str, str]] = []
    for row in rows:
        batch.append(row)
        if len(batch) == batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def _safe_record_identity(record: Mapping[str, str]) -> tuple[str | None, str | None, str | None]:
    def clean(field: str) -> str | None:
        value = record.get(field)
        if not isinstance(value, str):
            return None
        value = value.strip()
        return value or None

    return clean("merchant_id"), clean("merchant_product_id"), clean("aw_product_id")


def _short_error(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
    if not text:
        return exc.__class__.__name__
    return text[:240]


def _fatal_error_summary(exc: BaseException) -> str:
    # Database connection exceptions may include connection details in their
    # message. Persist/log only the exception category for those failures.
    if exc.__class__.__module__.startswith("psycopg"):
        return exc.__class__.__name__
    return _short_error(exc)


def _is_fatal_database_error(exc: BaseException) -> bool:
    """Recognise Psycopg connection/interface failures without requiring Psycopg in unit tests."""

    module = exc.__class__.__module__
    name = exc.__class__.__name__
    return module.startswith("psycopg") and name in {"OperationalError", "InterfaceError"}


def _is_record_error(exc: BaseException) -> bool:
    if isinstance(
        exc,
        (
            AwinNormalizationError,
            repository.SourceNotFoundError,
            repository.SourceAmbiguityError,
            repository.VariantAmbiguityError,
            ValueError,
            RuntimeError,
        ),
    ):
        return True

    # Psycopg constraint/data errors are record-local; connection/interface
    # failures must abort the import instead.
    module = exc.__class__.__module__
    if module.startswith("psycopg"):
        return not _is_fatal_database_error(exc)

    return False


def _variant_attributes(record: AwinNormalizedRecord) -> dict[str, str | None]:
    attributes = dict(record.variant_fields)
    attributes.update(
        {
            "colour": record.colour,
            "dimensions": record.dimensions,
            "model_number": record.model_number,
        }
    )
    return attributes


def _persist_record(connection: ConnectionLike, prepared: _PreparedRecord) -> bool:
    """Persist one normalized record and return ``True`` when its offer was newly created."""

    record = prepared.normalized
    source = prepared.source

    existing_offer = repository.find_offer(
        connection,
        shop_id=source.shop_id,
        external_offer_id=record.merchant_product_id,
    )

    if existing_offer is not None:
        product_variant_id = str(existing_offer["product_variant_id"])
        offer_created = False
    else:
        variant = repository.find_product_variant(
            connection,
            gtin=record.gtin,
            brand_name=record.brand,
            mpn=record.mpn,
        )
        if variant is None:
            family_id = repository.create_product_family(
                connection,
                name=record.title,
                brand_name=record.brand,
                category=record.category,
                description=record.description,
            )
            product_variant_id = repository.create_product_variant(
                connection,
                product_family_id=family_id,
                name=record.title,
                model_name=record.product_model or record.model_number,
                gtin=record.gtin,
                mpn=record.mpn,
                description=record.description,
                variant_attributes=_variant_attributes(record),
            )
        else:
            product_variant_id = variant.id
        offer_created = True

    offer_id = repository.upsert_offer(
        connection,
        product_variant_id=product_variant_id,
        shop_id=source.shop_id,
        external_offer_id=record.merchant_product_id,
        shop_title=record.title,
        shop_description=record.description,
        product_url=record.product_url,
        current_price=record.price,
        currency_code=record.currency,
        availability_status=record.availability,
    )

    source_record_id = repository.get_or_create_offer_source_record(
        connection,
        offer_id=offer_id,
        source_id=source.id,
        shop_id=source.shop_id,
        external_record_key=record.aw_product_id,
        external_reference=record.aw_deep_link,
    )

    repository.create_offer_observation(
        connection,
        import_run_id=prepared.stats.import_run_id,
        offer_source_record_id=source_record_id,
        source_id=source.id,
        offer_id=offer_id,
        observed_shop_title=record.title,
        observed_shop_description=record.description,
        observed_product_url=record.product_url,
        observed_price=record.price,
        currency_code=record.currency,
        availability_status=record.availability,
        processing_status="created" if offer_created else "updated",
    )

    for position, image_url in enumerate(record.image_urls, start=1):
        repository.get_or_create_product_image(
            connection,
            offer_id=offer_id,
            source_id=source.id,
            shop_id=source.shop_id,
            offer_source_record_id=source_record_id,
            external_url=image_url,
            position=position,
            is_primary=position == 1,
        )

    return offer_created


def _finish_runs(
    connection: ConnectionLike,
    source_stats: dict[str, SourceImportStats],
    *,
    failed: bool,
    fatal_error: str | None = None,
) -> None:
    if not source_stats:
        return

    with connection.transaction():
        for stats in source_stats.values():
            if failed:
                status = "failed"
                error_summary = fatal_error
            elif stats.records_rejected:
                status = "partially_succeeded"
                error_summary = stats.errors[0] if stats.errors else "one or more records were rejected"
            else:
                status = "succeeded"
                error_summary = None

            repository.finish_import_run(
                connection,
                import_run_id=stats.import_run_id,
                technical_status=status,
                records_received=stats.records_received,
                records_processed=stats.records_processed,
                records_created=stats.records_created,
                records_updated=stats.records_updated,
                records_rejected=stats.records_rejected,
                error_summary=error_summary,
            )


def run_awin_import(
    connection: ConnectionLike,
    feed_path: str | Path,
    *,
    importer_version: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    logger: logging.Logger | None = None,
) -> ImportResult:
    """Run one streaming AWIN import using the approved parser/normalizer/repository pipeline."""

    if not importer_version.strip():
        raise ValueError("importer_version must not be blank")
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    log = logger or logging.getLogger(__name__)
    source_stats: dict[str, SourceImportStats] = {}
    records_read = 0
    records_accepted = 0
    records_rejected = 0

    try:
        rows = iter_awin_rows(feed_path)

        def counted_rows() -> Iterator[Mapping[str, str]]:
            nonlocal records_read
            for row in rows:
                records_read += 1
                yield row

        for raw_batch in _iter_batches(counted_rows(), batch_size):
            prepared_batch: list[_PreparedRecord] = []

            # Normalize first. Invalid records are rejected without touching the DB.
            normalized_batch: list[tuple[Mapping[str, str], AwinNormalizedRecord]] = []
            for raw_record in raw_batch:
                try:
                    normalized = normalize_awin_record(raw_record)
                except Exception as exc:
                    if not _is_record_error(exc):
                        raise
                    records_rejected += 1
                    merchant_id, merchant_product_id, aw_product_id = _safe_record_identity(raw_record)
                    log.warning(
                        "AWIN record rejected during normalization merchant_id=%r merchant_product_id=%r aw_product_id=%r error=%s",
                        merchant_id,
                        merchant_product_id,
                        aw_product_id,
                        _short_error(exc),
                    )
                    continue
                normalized_batch.append((raw_record, normalized))

            # Resolve sources and create a run once per actually used source. This
            # transaction commits before batch persistence so a later fatal batch
            # rollback cannot erase the running import history.
            if normalized_batch:
                with connection.transaction():
                    for raw_record, normalized in normalized_batch:
                        try:
                            source = repository.get_source_for_merchant(connection, normalized.merchant_id)
                        except Exception as exc:
                            if not _is_record_error(exc):
                                raise
                            records_rejected += 1
                            log.warning(
                                "AWIN record rejected during source resolution merchant_id=%r merchant_product_id=%r aw_product_id=%r error=%s",
                                normalized.merchant_id,
                                normalized.merchant_product_id,
                                normalized.aw_product_id,
                                _short_error(exc),
                            )
                            continue

                        stats = source_stats.get(source.id)
                        if stats is None:
                            import_run_id = repository.create_import_run(
                                connection,
                                source_id=source.id,
                                importer_version=importer_version,
                            )
                            stats = SourceImportStats(
                                source_id=source.id,
                                shop_id=source.shop_id,
                                import_run_id=import_run_id,
                            )
                            source_stats[source.id] = stats

                        stats.records_received += 1
                        prepared_batch.append(_PreparedRecord(normalized=normalized, source=source, stats=stats))

            if not prepared_batch:
                continue

            # One transaction per batch, one nested transaction/savepoint per row.
            committed_successes: list[tuple[SourceImportStats, bool]] = []
            batch_rejections: list[SourceImportStats] = []
            with connection.transaction():
                for prepared in prepared_batch:
                    try:
                        with connection.transaction():
                            created = _persist_record(connection, prepared)
                    except Exception as exc:
                        if not _is_record_error(exc) or _is_fatal_database_error(exc):
                            raise
                        records_rejected += 1
                        prepared.stats.errors.append(_short_error(exc))
                        batch_rejections.append(prepared.stats)
                        record = prepared.normalized
                        log.warning(
                            "AWIN record rejected source_id=%s merchant_product_id=%r aw_product_id=%r error=%s",
                            prepared.source.id,
                            record.merchant_product_id,
                            record.aw_product_id,
                            _short_error(exc),
                        )
                        continue
                    committed_successes.append((prepared.stats, created))

            # Apply success counters only after the batch transaction commits.
            for stats, created in committed_successes:
                records_accepted += 1
                stats.records_processed += 1
                if created:
                    stats.records_created += 1
                else:
                    stats.records_updated += 1
            for stats in batch_rejections:
                stats.records_rejected += 1

    except Exception as exc:
        # Anything not explicitly isolated as a record error above is fatal for
        # this run. Never log feed rows or connection details/secrets.
        fatal_summary = _fatal_error_summary(exc)
        try:
            _finish_runs(connection, source_stats, failed=True, fatal_error=fatal_summary)
        except Exception:
            log.error("AWIN import failed and active import runs could not all be finalized")
        result = ImportResult(
            records_read=records_read,
            records_accepted=records_accepted,
            records_rejected=records_rejected,
            source_runs=tuple(source_stats.values()),
        )
        raise AwinImportFatalError(result, fatal_summary) from exc

    _finish_runs(connection, source_stats, failed=False)
    return ImportResult(
        records_read=records_read,
        records_accepted=records_accepted,
        records_rejected=records_rejected,
        source_runs=tuple(source_stats.values()),
    )
