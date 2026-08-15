from __future__ import annotations

import csv
from contextlib import AbstractContextManager
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from backend.importers.awin import import_awin
from backend.importers.awin.parser import AWIN_HEADER
from backend.importers.awin.repository import SourceRef, VariantAmbiguityError, VariantMatch


class FakeTransaction(AbstractContextManager[object]):
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection
        self.entered_depth = 0

    def __enter__(self) -> object:
        self.entered_depth = self.connection.depth
        self.connection.transaction_entries.append(self.entered_depth)
        self.connection.depth += 1
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.connection.depth -= 1
        if exc_type is None:
            self.connection.transaction_commits.append(self.entered_depth)
        else:
            self.connection.transaction_rollbacks.append(self.entered_depth)
        return False


class FakeConnection:
    def __init__(self) -> None:
        self.depth = 0
        self.transaction_entries: list[int] = []
        self.transaction_commits: list[int] = []
        self.transaction_rollbacks: list[int] = []

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)

    def cursor(self):  # pragma: no cover - repository functions are replaced in these tests
        raise AssertionError("orchestrator tests must not execute SQL")


class FakeRepository:
    def __init__(self) -> None:
        self.sources = {
            "100": SourceRef(id="source-100", shop_id="shop-100"),
            "200": SourceRef(id="source-200", shop_id="shop-200"),
        }
        self.run_counter = 0
        self.family_counter = 0
        self.variant_counter = 0
        self.offer_counter = 0
        self.source_record_counter = 0
        self.observation_counter = 0
        self.image_counter = 0
        self.runs: dict[str, dict[str, object]] = {}
        self.variants: dict[tuple[str, str], VariantMatch] = {}
        self.offers: dict[tuple[str, str], dict[str, object]] = {}
        self.source_records: dict[tuple[str, str], str] = {}
        self.observations: list[dict[str, object]] = []
        self.images: dict[tuple[str, str, str], str] = {}
        self.external_references: list[str | None] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        names = (
            "get_source_for_merchant",
            "create_import_run",
            "finish_import_run",
            "find_offer",
            "find_product_variant",
            "create_product_family",
            "create_product_variant",
            "upsert_offer",
            "get_or_create_offer_source_record",
            "create_offer_observation",
            "get_or_create_product_image",
        )
        for name in names:
            monkeypatch.setattr(import_awin.repository, name, getattr(self, name))

    def get_source_for_merchant(self, connection, merchant_id: str) -> SourceRef:
        try:
            return self.sources[merchant_id]
        except KeyError as exc:
            raise import_awin.repository.SourceNotFoundError(merchant_id) from exc

    def create_import_run(self, connection, *, source_id: str, importer_version: str, automation_run_id=None) -> str:
        self.run_counter += 1
        run_id = f"run-{self.run_counter}"
        self.runs[run_id] = {
            "source_id": source_id,
            "importer_version": importer_version,
            "technical_status": "running",
        }
        return run_id

    def finish_import_run(self, connection, *, import_run_id: str, **values) -> None:
        self.runs[import_run_id].update(values)

    def find_offer(self, connection, *, shop_id: str, external_offer_id: str):
        return self.offers.get((shop_id, external_offer_id))

    def find_product_variant(self, connection, *, gtin: str | None, brand_name: str | None, mpn: str | None):
        if mpn == "AMBIGUOUS":
            raise VariantAmbiguityError("multiple candidates")
        if gtin is not None:
            return self.variants.get(("gtin", gtin))
        if brand_name is not None and mpn is not None:
            return self.variants.get(("brand_mpn", f"{brand_name}\0{mpn}"))
        return None

    def create_product_family(self, connection, **kwargs) -> str:
        self.family_counter += 1
        return f"family-{self.family_counter}"

    def create_product_variant(
        self,
        connection,
        *,
        product_family_id: str,
        gtin: str | None,
        mpn: str | None,
        **kwargs,
    ) -> str:
        self.variant_counter += 1
        variant_id = f"variant-{self.variant_counter}"
        match = VariantMatch(id=variant_id, product_family_id=product_family_id)
        brand = kwargs.get("variant_attributes", {}).get("__brand_for_test")
        if gtin is not None:
            self.variants[("gtin", gtin)] = match
        # Brand+MPN indexing is added by upsert_offer test helper below only when needed.
        if brand is not None and mpn is not None:
            self.variants[("brand_mpn", f"{brand}\0{mpn}")] = match
        return variant_id

    def upsert_offer(
        self,
        connection,
        *,
        product_variant_id: str,
        shop_id: str,
        external_offer_id: str,
        **kwargs,
    ) -> str:
        key = (shop_id, external_offer_id)
        existing = self.offers.get(key)
        if existing is not None:
            existing.update(kwargs)
            return str(existing["id"])
        self.offer_counter += 1
        offer_id = f"offer-{self.offer_counter}"
        self.offers[key] = {
            "id": offer_id,
            "product_variant_id": product_variant_id,
            "shop_id": shop_id,
            "external_offer_id": external_offer_id,
            **kwargs,
        }
        return offer_id

    def get_or_create_offer_source_record(
        self,
        connection,
        *,
        offer_id: str,
        source_id: str,
        external_record_key: str,
        external_reference: str | None,
        **kwargs,
    ) -> str:
        self.external_references.append(external_reference)
        key = (source_id, external_record_key)
        if key not in self.source_records:
            self.source_record_counter += 1
            self.source_records[key] = f"source-record-{self.source_record_counter}"
        return self.source_records[key]

    def create_offer_observation(self, connection, **kwargs) -> str:
        self.observation_counter += 1
        self.observations.append(dict(kwargs))
        return f"observation-{self.observation_counter}"

    def get_or_create_product_image(self, connection, *, offer_id: str, source_id: str, external_url: str, **kwargs) -> str:
        key = (offer_id, source_id, external_url)
        if key not in self.images:
            self.image_counter += 1
            self.images[key] = f"image-{self.image_counter}"
        return self.images[key]


def make_row(
    *,
    merchant_id: str = "100",
    merchant_product_id: str = "merchant-product-1",
    aw_product_id: str = "aw-product-1",
    gtin: str = "4006381333931",
    mpn: str = "MPN-1",
    price: str = "12.34",
    aw_deep_link: str = "https://awin.example/raw-link",
) -> dict[str, str]:
    row = {column: "" for column in AWIN_HEADER}
    row.update(
        {
            "aw_deep_link": aw_deep_link,
            "product_name": f"Product {merchant_product_id}",
            "aw_product_id": aw_product_id,
            "merchant_product_id": merchant_product_id,
            "merchant_image_url": f"https://img.example/{merchant_product_id}.jpg",
            "description": "Description",
            "merchant_category": "Category",
            "search_price": price,
            "merchant_id": merchant_id,
            "currency": "EUR",
            "merchant_deep_link": f"https://merchant.example/{merchant_product_id}",
            "data_feed_id": "feed-1",
            "brand_name": "Brand",
            "in_stock": "1",
            "ean": gtin,
            "mpn": mpn,
        }
    )
    return row


def write_feed(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=AWIN_HEADER, delimiter=";", quotechar='"', lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_successful_mini_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    repo.install(monkeypatch)
    feed = tmp_path / "feed.csv"
    write_feed(feed, [make_row(), make_row(merchant_product_id="merchant-product-2", aw_product_id="aw-product-2", gtin="4006381333948")])

    result = import_awin.run_awin_import(FakeConnection(), feed, importer_version="phase4")

    assert (result.records_read, result.records_accepted, result.records_rejected) == (2, 2, 0)
    assert len(repo.offers) == 2
    assert len(repo.observations) == 2
    run = next(iter(repo.runs.values()))
    assert run["technical_status"] == "succeeded"
    assert run["records_received"] == 2
    assert run["records_processed"] == 2
    assert run["records_created"] == 2
    assert run["records_updated"] == 0
    assert run["records_rejected"] == 0
    assert repo.external_references == ["https://awin.example/raw-link", "https://awin.example/raw-link"]


def test_multiple_merchants_create_one_run_per_used_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    repo.install(monkeypatch)
    feed = tmp_path / "feed.csv"
    write_feed(
        feed,
        [
            make_row(merchant_id="100", merchant_product_id="a", aw_product_id="aw-a", gtin="1000000000001"),
            make_row(merchant_id="200", merchant_product_id="b", aw_product_id="aw-b", gtin="2000000000002"),
            make_row(merchant_id="100", merchant_product_id="c", aw_product_id="aw-c", gtin="3000000000003"),
        ],
    )

    result = import_awin.run_awin_import(FakeConnection(), feed, importer_version="phase4")

    assert result.records_accepted == 3
    assert len(repo.runs) == 2
    by_source = {run["source_id"]: run for run in repo.runs.values()}
    assert by_source["source-100"]["records_received"] == 2
    assert by_source["source-200"]["records_received"] == 1


def test_single_record_error_isolated_and_import_continues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    repo.install(monkeypatch)
    feed = tmp_path / "feed.csv"
    write_feed(
        feed,
        [
            make_row(merchant_product_id="ok-1", aw_product_id="aw-1", gtin="1000000000001"),
            make_row(merchant_product_id="bad", aw_product_id="aw-2", gtin="", mpn="AMBIGUOUS"),
            make_row(merchant_product_id="ok-2", aw_product_id="aw-3", gtin="3000000000003"),
        ],
    )

    result = import_awin.run_awin_import(FakeConnection(), feed, importer_version="phase4")

    assert (result.records_read, result.records_accepted, result.records_rejected) == (3, 2, 1)
    run = next(iter(repo.runs.values()))
    assert run["technical_status"] == "partially_succeeded"
    assert run["records_received"] == 3
    assert run["records_processed"] == 2
    assert run["records_rejected"] == 1
    assert len(repo.offers) == 2


def test_invalid_normalized_record_does_not_stop_following_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    repo.install(monkeypatch)
    feed = tmp_path / "feed.csv"
    write_feed(
        feed,
        [
            make_row(merchant_product_id="bad-price", aw_product_id="aw-bad", price="not-a-price"),
            make_row(merchant_product_id="ok", aw_product_id="aw-ok", gtin="9000000000009"),
        ],
    )

    result = import_awin.run_awin_import(FakeConnection(), feed, importer_version="phase4")

    assert (result.records_read, result.records_accepted, result.records_rejected) == (2, 1, 1)
    assert len(repo.offers) == 1


def test_fatal_error_marks_active_run_failed_and_rolls_back_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    repo.install(monkeypatch)
    feed = tmp_path / "feed.csv"
    write_feed(feed, [make_row()])
    connection = FakeConnection()

    class FatalBoom(Exception):
        pass

    def fail_persist(connection, prepared):
        raise FatalBoom("database transport unavailable")

    monkeypatch.setattr(import_awin, "_persist_record", fail_persist)

    with pytest.raises(import_awin.AwinImportFatalError) as caught:
        import_awin.run_awin_import(connection, feed, importer_version="phase4")

    assert caught.value.result.records_read == 1
    assert caught.value.result.records_accepted == 0
    run = next(iter(repo.runs.values()))
    assert run["technical_status"] == "failed"
    assert run["records_received"] == 1
    assert run["records_processed"] == 0
    assert 0 in connection.transaction_rollbacks


def test_default_batch_boundary_is_250_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    repo.install(monkeypatch)
    feed = tmp_path / "feed.csv"
    rows = [
        make_row(
            merchant_product_id=f"p-{index}",
            aw_product_id=f"aw-{index}",
            gtin=str(1000000000000 + index),
        )
        for index in range(251)
    ]
    write_feed(feed, rows)
    connection = FakeConnection()

    result = import_awin.run_awin_import(connection, feed, importer_version="phase4")

    assert result.records_accepted == 251
    # Two batches: each has one source-resolution transaction and one batch
    # transaction, followed by one finalization transaction.
    assert connection.transaction_entries.count(0) == 5
    # One nested transaction/savepoint for every persisted record.
    assert connection.transaction_entries.count(1) == 251


def test_second_identical_import_does_not_create_additional_offers_or_variants(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    repo.install(monkeypatch)
    feed = tmp_path / "feed.csv"
    write_feed(
        feed,
        [
            make_row(merchant_product_id="p1", aw_product_id="aw1", gtin="1000000000001"),
            make_row(merchant_product_id="p2", aw_product_id="aw2", gtin="2000000000002"),
        ],
    )

    first = import_awin.run_awin_import(FakeConnection(), feed, importer_version="phase4")
    variants_after_first = repo.variant_counter
    offers_after_first = repo.offer_counter
    second = import_awin.run_awin_import(FakeConnection(), feed, importer_version="phase4")

    assert first.records_accepted == second.records_accepted == 2
    assert repo.variant_counter == variants_after_first
    assert repo.offer_counter == offers_after_first
    assert len(repo.runs) == 2
    assert len(repo.observations) == 4
    second_run = repo.runs["run-2"]
    assert second_run["records_created"] == 0
    assert second_run["records_updated"] == 2


def test_unknown_merchant_is_rejected_without_creating_source_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepository()
    repo.install(monkeypatch)
    feed = tmp_path / "feed.csv"
    write_feed(feed, [make_row(merchant_id="999")])

    result = import_awin.run_awin_import(FakeConnection(), feed, importer_version="phase4")

    assert (result.records_read, result.records_accepted, result.records_rejected) == (1, 0, 1)
    assert repo.runs == {}


def test_blank_importer_version_and_invalid_batch_size_rejected_before_import(tmp_path: Path) -> None:
    feed = tmp_path / "feed.csv"
    write_feed(feed, [make_row()])
    connection = FakeConnection()

    with pytest.raises(ValueError, match="importer_version"):
        import_awin.run_awin_import(connection, feed, importer_version="   ")
    with pytest.raises(ValueError, match="batch_size"):
        import_awin.run_awin_import(connection, feed, importer_version="phase4", batch_size=0)


def test_fatal_streaming_parser_error_marks_existing_run_failed_and_keeps_read_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepository()
    repo.install(monkeypatch)
    feed = tmp_path / "broken.csv"
    valid = make_row()
    with feed.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=AWIN_HEADER, delimiter=";", quotechar='"', lineterminator="\n")
        writer.writeheader()
        writer.writerow(valid)
        stream.write("too;few;columns\n")

    with pytest.raises(import_awin.AwinImportFatalError) as caught:
        import_awin.run_awin_import(FakeConnection(), feed, importer_version="phase4", batch_size=1)

    assert caught.value.result.records_read == 1
    assert caught.value.result.records_accepted == 1
    run = next(iter(repo.runs.values()))
    assert run["technical_status"] == "failed"
    assert run["records_processed"] == 1
