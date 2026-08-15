from __future__ import annotations

from decimal import Decimal

import pytest

from backend.importers.awin.repository import (
    SourceAmbiguityError,
    SourceNotFoundError,
    VariantAmbiguityError,
    create_import_run,
    create_offer_observation,
    create_product_family,
    create_product_variant,
    find_offer,
    find_product_variant,
    finish_import_run,
    get_or_create_offer_source_record,
    get_or_create_product_image,
    get_source_for_merchant,
    upsert_offer,
)


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection
        self.response = None

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, query: str, params=None) -> None:
        normalized_sql = " ".join(query.split())
        self.connection.calls.append((normalized_sql, params))
        if not self.connection.responses:
            raise AssertionError(f"unexpected SQL execution: {normalized_sql}")
        self.response = self.connection.responses.pop(0)

    def fetchone(self):
        if self.response is None:
            return None
        if isinstance(self.response, list):
            return self.response[0] if self.response else None
        return self.response

    def fetchall(self):
        if self.response is None:
            return []
        if isinstance(self.response, list):
            return self.response
        return [self.response]


class FakeConnection:
    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, object]] = []
        self.commit_called = False
        self.rollback_called = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commit_called = True

    def rollback(self) -> None:
        self.rollback_called = True


def _assert_transaction_untouched(connection: FakeConnection) -> None:
    assert connection.commit_called is False
    assert connection.rollback_called is False


def test_source_lookup_uses_approved_awin_reference_format() -> None:
    connection = FakeConnection([("source-1", "shop-1")])

    source = get_source_for_merchant(connection, "37938")

    assert source.id == "source-1"
    assert source.shop_id == "shop-1"
    sql, params = connection.calls[0]
    assert "FROM sources" in sql
    assert "source_reference = %s" in sql
    assert params == ("awin:advertiser:37938",)
    _assert_transaction_untouched(connection)


def test_source_lookup_rejects_missing_mapping() -> None:
    with pytest.raises(SourceNotFoundError):
        get_source_for_merchant(FakeConnection([]), "999")


def test_source_lookup_rejects_ambiguous_mapping() -> None:
    connection = FakeConnection([("s1", "shop"), ("s2", "shop")])
    with pytest.raises(SourceAmbiguityError):
        get_source_for_merchant(connection, "37938")


def test_create_import_run_uses_running_status_and_returns_id() -> None:
    connection = FakeConnection(("run-1",))
    result = create_import_run(connection, source_id="source-1", importer_version="1.0.0")
    assert result == "run-1"
    sql, params = connection.calls[0]
    assert "INSERT INTO import_runs" in sql
    assert "'running'" in sql
    assert params == ("source-1", None, "1.0.0")
    _assert_transaction_untouched(connection)


def test_finish_import_run_updates_only_run_row_and_counters() -> None:
    connection = FakeConnection(None)
    finish_import_run(
        connection,
        import_run_id="run-1",
        technical_status="partially_succeeded",
        records_received=10,
        records_processed=9,
        records_created=3,
        records_updated=5,
        records_rejected=1,
        error_summary="one rejected record",
    )
    sql, params = connection.calls[0]
    assert "UPDATE import_runs" in sql
    assert "finished_at = now()" in sql
    assert params[-1] == "run-1"
    _assert_transaction_untouched(connection)


@pytest.mark.parametrize("status", ["planned", "running", "invalid"])
def test_finish_import_run_rejects_non_terminal_status(status: str) -> None:
    with pytest.raises(ValueError):
        finish_import_run(
            FakeConnection(), import_run_id="r", technical_status=status,
            records_received=0, records_processed=0, records_created=0,
            records_updated=0, records_rejected=0,
        )


def test_finish_import_run_rejects_negative_counters() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        finish_import_run(
            FakeConnection(), import_run_id="r", technical_status="failed",
            records_received=-1, records_processed=0, records_created=0,
            records_updated=0, records_rejected=0,
        )


def test_find_offer_uses_shop_and_external_offer_identity() -> None:
    connection = FakeConnection(("offer-1", "variant-1", "shop-1", "mp-1", "Title", None, "https://p", Decimal("10.00"), "EUR", "in_stock"))
    offer = find_offer(connection, shop_id="shop-1", external_offer_id="mp-1")
    assert offer is not None
    assert offer["id"] == "offer-1"
    assert offer["product_variant_id"] == "variant-1"
    sql, params = connection.calls[0]
    assert "shop_id = %s" in sql and "external_offer_id = %s" in sql
    assert params == ("shop-1", "mp-1")


def test_find_offer_returns_none_when_absent() -> None:
    assert find_offer(FakeConnection(None), shop_id="shop", external_offer_id="x") is None


def test_create_product_family_uses_only_schema_columns() -> None:
    connection = FakeConnection(("family-1",))
    result = create_product_family(connection, name="Widget", brand_name="Brand", category="Tools", description="Desc")
    assert result == "family-1"
    sql, params = connection.calls[0]
    assert "INSERT INTO product_families (name, brand_name, category, description)" in sql
    assert params == ("Widget", "Brand", "Tools", "Desc")


def test_create_product_variant_serializes_attributes_as_json_parameter() -> None:
    connection = FakeConnection(("variant-1",))
    result = create_product_variant(
        connection,
        product_family_id="family-1",
        name="Widget Blue",
        model_name="M1",
        gtin="4006381333931",
        mpn="ABC-1",
        description=None,
        variant_attributes={"colour": "Blau", "size": None},
    )
    assert result == "variant-1"
    sql, params = connection.calls[0]
    assert "%s::jsonb" in sql
    assert params[-1] == '{"colour":"Blau","size":null}'


def test_variant_lookup_prefers_gtin_and_does_not_query_brand_mpn() -> None:
    connection = FakeConnection([("variant-1", "family-1")])
    result = find_product_variant(connection, gtin="4006381333931", brand_name="Brand", mpn="MPN")
    assert result is not None and result.id == "variant-1"
    assert len(connection.calls) == 1
    sql, params = connection.calls[0]
    assert "WHERE gtin = %s" in sql
    assert params == ("4006381333931",)


def test_variant_lookup_reports_multiple_gtin_candidates_as_ambiguity() -> None:
    connection = FakeConnection([("v1", "f1"), ("v2", "f2")])
    with pytest.raises(VariantAmbiguityError, match="gtin"):
        find_product_variant(connection, gtin="4006381333931", brand_name=None, mpn=None)


def test_variant_lookup_uses_brand_and_mpn_only_when_gtin_missing() -> None:
    connection = FakeConnection([("variant-2", "family-2")])
    result = find_product_variant(connection, gtin=None, brand_name="Brand", mpn="MPN-1")
    assert result is not None and result.product_family_id == "family-2"
    sql, params = connection.calls[0]
    assert "JOIN product_families" in sql
    assert "pf.brand_name = %s" in sql and "pv.mpn = %s" in sql
    assert params == ("Brand", "MPN-1")


def test_variant_lookup_reports_multiple_brand_mpn_candidates_as_ambiguity() -> None:
    connection = FakeConnection([("v1", "f1"), ("v2", "f2")])
    with pytest.raises(VariantAmbiguityError, match="brand"):
        find_product_variant(connection, gtin=None, brand_name="Brand", mpn="MPN")


@pytest.mark.parametrize(
    ("gtin", "brand", "mpn"),
    [(None, None, None), (None, "Brand", None), (None, None, "MPN")],
)
def test_variant_lookup_returns_none_without_complete_strong_identity(gtin, brand, mpn) -> None:
    connection = FakeConnection()
    assert find_product_variant(connection, gtin=gtin, brand_name=brand, mpn=mpn) is None
    assert connection.calls == []


def test_upsert_offer_uses_partial_unique_identity_and_does_not_update_variant() -> None:
    connection = FakeConnection(("offer-1",))
    result = upsert_offer(
        connection,
        product_variant_id="variant-new",
        shop_id="shop-1",
        external_offer_id="merchant-product-1",
        shop_title="Title",
        shop_description="Desc",
        product_url="https://merchant.example/p",
        current_price=Decimal("9.99"),
        currency_code="EUR",
        availability_status="in_stock",
    )
    assert result == "offer-1"
    sql, params = connection.calls[0]
    assert "ON CONFLICT (shop_id, external_offer_id)" in sql
    assert "WHERE external_offer_id IS NOT NULL" in sql
    update_clause = sql.split("DO UPDATE SET", 1)[1]
    assert "product_variant_id" not in update_clause
    assert params[0] == "variant-new"
    _assert_transaction_untouched(connection)


def test_offer_source_record_reuses_source_and_aw_product_key_without_overwriting_reference() -> None:
    connection = FakeConnection(("record-1",))
    result = get_or_create_offer_source_record(
        connection,
        offer_id="offer-1",
        source_id="source-1",
        shop_id="shop-1",
        external_record_key="aw-product-1",
        external_reference="https://awin.example/raw",
    )
    assert result == "record-1"
    sql, params = connection.calls[0]
    assert "ON CONFLICT (source_id, external_record_key)" in sql
    update_clause = sql.split("DO UPDATE SET", 1)[1]
    set_clause = update_clause.split("WHERE", 1)[0]
    assert "external_reference" not in set_clause
    assert "offer_id" not in set_clause
    assert "offer_source_records.offer_id = EXCLUDED.offer_id" in sql
    assert "offer_source_records.shop_id = EXCLUDED.shop_id" in sql
    assert params[3] == "aw-product-1"



def test_offer_source_record_identity_mismatch_is_not_silently_reassigned() -> None:
    connection = FakeConnection(None)
    with pytest.raises(RuntimeError, match="different offer or shop"):
        get_or_create_offer_source_record(
            connection,
            offer_id="offer-new",
            source_id="source-1",
            shop_id="shop-1",
            external_record_key="aw-product-existing",
            external_reference=None,
        )
    sql, _ = connection.calls[0]
    assert "WHERE offer_source_records.offer_id = EXCLUDED.offer_id" in sql


def test_offer_observation_is_insert_only_history() -> None:
    connection = FakeConnection(("observation-1",))
    result = create_offer_observation(
        connection,
        import_run_id="run-1",
        offer_source_record_id="record-1",
        source_id="source-1",
        offer_id="offer-1",
        observed_shop_title="Title",
        observed_shop_description="Desc",
        observed_product_url="https://merchant.example/p",
        observed_price=Decimal("11.25"),
        currency_code="EUR",
        availability_status="in_stock",
        record_hash="a" * 64,
        processing_status="updated",
    )
    assert result == "observation-1"
    sql, params = connection.calls[0]
    assert "INSERT INTO offer_observations" in sql
    assert "ON CONFLICT" not in sql
    assert "UPDATE offer_observations" not in sql
    assert params[0:4] == ("run-1", "record-1", "source-1", "offer-1")


def test_product_image_reuses_exact_feed_url_without_transforming_it() -> None:
    connection = FakeConnection(("image-1",))
    url = "https://images.example/p.jpg?w=70&h=70"
    result = get_or_create_product_image(
        connection,
        offer_id="offer-1",
        source_id="source-1",
        shop_id="shop-1",
        offer_source_record_id="record-1",
        external_url=url,
        position=1,
        is_primary=True,
    )
    assert result == "image-1"
    sql, params = connection.calls[0]
    assert "INSERT INTO product_images" in sql
    assert "ON CONFLICT (offer_id, source_id, external_url, COALESCE(content_hash, ''))" in sql
    assert params[4] == url
    update_clause = sql.split("DO UPDATE SET", 1)[1]
    assert "external_url" not in update_clause
    assert "position" not in update_clause
    assert "is_primary" not in update_clause


def test_all_repository_queries_use_placeholders_for_feed_values() -> None:
    marker = "x'; DROP TABLE offers; --"
    connection = FakeConnection([("source", "shop")])
    get_source_for_merchant(connection, marker)
    sql, params = connection.calls[0]
    assert marker not in sql
    assert params == (f"awin:advertiser:{marker}",)


def test_repository_never_commits_or_rolls_back_for_mutations() -> None:
    connection = FakeConnection(("family-1",))
    create_product_family(connection, name="X", brand_name=None, category=None, description=None)
    _assert_transaction_untouched(connection)
