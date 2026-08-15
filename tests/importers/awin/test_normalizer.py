from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from backend.importers.awin.normalizer import (
    AwinNormalizationError,
    collect_image_urls,
    derive_availability,
    normalize_awin_record,
)
from backend.importers.awin.parser import AWIN_HEADER, iter_awin_rows


FIXTURE = Path(__file__).parents[2] / "fixtures" / "awin" / "sample.csv"


def _record(**overrides: str) -> dict[str, str]:
    record = {field: "" for field in AWIN_HEADER}
    record.update(
        {
            "merchant_product_id": " SKU-123 ",
            "aw_product_id": " 987654321 ",
            "merchant_id": " 496 ",
            "data_feed_id": " 496 ",
            "product_name": " Test Product ",
            "merchant_deep_link": " https://merchant.example/product/123 ",
            "aw_deep_link": " https://www.awin1.com/example ",
            "search_price": " 13.9500 ",
            "currency": " gbp ",
        }
    )
    record.update(overrides)
    return record


def test_normalizes_real_fixture_record() -> None:
    raw = next(iter_awin_rows(FIXTURE))

    normalized = normalize_awin_record(raw)

    assert normalized.merchant_product_id == "658207"
    assert normalized.aw_product_id == "36013645938"
    assert normalized.merchant_id == "496"
    assert normalized.data_feed_id == "496"
    assert normalized.title == "Wiha Magnetiser and Demagnetiser"
    assert normalized.brand == "Wiha"
    assert normalized.category == "Hand Tools > Inspection & Pick Up Tools > Magnets"
    assert normalized.price == Decimal("13.95")
    assert normalized.currency == "GBP"
    assert normalized.ean == "4010995025687"
    assert normalized.gtin == "4010995025687"
    assert normalized.mpn == "02568"
    assert normalized.availability == "in_stock"
    assert normalized.product_url.startswith("https://www.tooled-up.com/")
    assert normalized.aw_deep_link.startswith("https://www.awin1.com/")


def test_trims_strings_and_maps_blank_optional_values_to_none() -> None:
    normalized = normalize_awin_record(
        _record(
            product_name="  Product title  ",
            description="  Description  ",
            brand_name="   ",
            mpn="  MPN-42  ",
            product_model="  Model X  ",
        )
    )

    assert normalized.title == "Product title"
    assert normalized.description == "Description"
    assert normalized.brand is None
    assert normalized.mpn == "MPN-42"
    assert normalized.product_model == "Model X"


def test_price_is_decimal_without_float_conversion() -> None:
    normalized = normalize_awin_record(_record(search_price="0.10"))

    assert normalized.price == Decimal("0.10")
    assert isinstance(normalized.price, Decimal)


def test_blank_price_and_currency_are_allowed() -> None:
    normalized = normalize_awin_record(_record(search_price=" ", currency=""))

    assert normalized.price is None
    assert normalized.currency is None


def test_currency_is_trimmed_and_uppercased() -> None:
    normalized = normalize_awin_record(_record(currency=" eur "))

    assert normalized.currency == "EUR"


@pytest.mark.parametrize("currency", ["EU", "EURO", "€€€", "12A"])
def test_invalid_currency_is_rejected(currency: str) -> None:
    with pytest.raises(AwinNormalizationError, match="currency") as exc_info:
        normalize_awin_record(_record(currency=currency))

    assert exc_info.value.field == "currency"


def test_price_requires_currency() -> None:
    with pytest.raises(AwinNormalizationError, match="currency is required"):
        normalize_awin_record(_record(currency=""))


@pytest.mark.parametrize("price", ["abc", "12,34", "NaN", "Infinity", "-1"])
def test_invalid_price_is_rejected(price: str) -> None:
    with pytest.raises(AwinNormalizationError, match="search_price") as exc_info:
        normalize_awin_record(_record(search_price=price))

    assert exc_info.value.field == "search_price"


def test_ean_is_trimmed_and_used_as_gtin_without_losing_leading_zeroes() -> None:
    normalized = normalize_awin_record(_record(ean=" 0012345678905 ", product_GTIN="9999999999999"))

    assert normalized.ean == "0012345678905"
    assert normalized.gtin == "0012345678905"


def test_product_gtin_is_used_when_ean_is_empty() -> None:
    normalized = normalize_awin_record(_record(ean="", product_GTIN=" 4006381333931 "))

    assert normalized.ean is None
    assert normalized.gtin == "4006381333931"


def test_invalid_ean_is_rejected_instead_of_silently_corrected() -> None:
    with pytest.raises(AwinNormalizationError, match="digits only"):
        normalize_awin_record(_record(ean="4006-3813-33931"))


def test_mpn_is_only_trimmed_not_rewritten() -> None:
    normalized = normalize_awin_record(_record(mpn="  AB-12 / X  "))

    assert normalized.mpn == "AB-12 / X"


@pytest.mark.parametrize(
    ("stock_fields", "expected"),
    [
        ({"pre_order": "1", "in_stock": "1"}, "preorder"),
        ({"stock_status": "In Stock"}, "in_stock"),
        ({"stock_status": "Out of Stock"}, "out_of_stock"),
        ({"stock_status": "Back Order"}, "backorder"),
        ({"stock_status": "Discontinued"}, "discontinued"),
        ({"size_stock_status": "In Stock"}, "in_stock"),
        ({"in_stock": "1"}, "in_stock"),
        ({"in_stock": "0"}, "out_of_stock"),
        ({"is_for_sale": "0"}, "unavailable"),
        ({}, "unknown"),
        ({"stock_status": "Available to Order"}, "unknown"),
        ({"in_stock": "maybe", "is_for_sale": "perhaps"}, "unknown"),
    ],
)
def test_availability_is_derived_only_from_explicit_known_stock_signals(
    stock_fields: dict[str, str], expected: str
) -> None:
    assert derive_availability(stock_fields) == expected


def test_collects_existing_image_fields_in_order_and_removes_exact_duplicates() -> None:
    record = _record(
        merchant_image_url=" https://img.example/original.jpg ",
        aw_image_url="https://img.example/awin.jpg",
        merchant_thumb_url="https://img.example/original.jpg",
        large_image="https://img.example/large.jpg",
        alternate_image="https://img.example/alt.jpg",
        aw_thumb_url="https://img.example/awin-thumb.jpg",
    )

    assert collect_image_urls(record) == (
        "https://img.example/original.jpg",
        "https://img.example/awin.jpg",
        "https://img.example/large.jpg",
        "https://img.example/alt.jpg",
        "https://img.example/awin-thumb.jpg",
    )


def test_image_urls_are_not_transformed_or_canonicalised() -> None:
    transformed_feed_url = (
        "https://images2.productserve.com/?w=70&h=70&url=ssl%3Aexample.com%2Fimage.jpg"
    )
    normalized = normalize_awin_record(_record(aw_thumb_url=transformed_feed_url))

    assert normalized.image_urls == (transformed_feed_url,)


def test_product_url_and_aw_deep_link_remain_separate() -> None:
    normalized = normalize_awin_record(
        _record(
            merchant_deep_link=" https://merchant.example/item ",
            aw_deep_link=" https://awin.example/tracking ",
        )
    )

    assert normalized.product_url == "https://merchant.example/item"
    assert normalized.aw_deep_link == "https://awin.example/tracking"


def test_category_prefers_merchant_category_and_keeps_awin_category_separately() -> None:
    normalized = normalize_awin_record(
        _record(
            merchant_category=" Tools > Pliers ",
            category_name=" Hand Tools ",
            category_id=" 474 ",
        )
    )

    assert normalized.category == "Tools > Pliers"
    assert normalized.merchant_category == "Tools > Pliers"
    assert normalized.awin_category_name == "Hand Tools"
    assert normalized.awin_category_id == "474"


def test_category_falls_back_to_awin_category_when_merchant_category_is_blank() -> None:
    normalized = normalize_awin_record(_record(merchant_category="", category_name=" Hand Tools "))

    assert normalized.category == "Hand Tools"


def test_model_and_variant_fields_are_exposed_without_inference() -> None:
    normalized = normalize_awin_record(
        _record(
            product_model=" Model Alpha ",
            model_number=" A-100 ",
            parent_product_id=" Parent-1 ",
            product_type=" Drill ",
            colour=" Blue ",
            dimensions=" 10 x 20 cm ",
            specifications=" 500 W ",
            **{
                "Fashion:size": " M ",
                "Fashion:material": " Cotton ",
                "Fashion:pattern": " Plain ",
            },
        )
    )

    assert normalized.product_model == "Model Alpha"
    assert normalized.model_number == "A-100"
    assert normalized.parent_product_id == "Parent-1"
    assert normalized.product_type == "Drill"
    assert normalized.colour == "Blue"
    assert normalized.dimensions == "10 x 20 cm"
    assert normalized.specifications == "500 W"
    assert normalized.variant_fields["Fashion:size"] == "M"
    assert normalized.variant_fields["Fashion:material"] == "Cotton"
    assert normalized.variant_fields["Fashion:pattern"] == "Plain"
    assert normalized.variant_fields["Fashion:swatch"] is None


@pytest.mark.parametrize(
    "field",
    [
        "merchant_product_id",
        "aw_product_id",
        "merchant_id",
        "data_feed_id",
        "product_name",
        "merchant_deep_link",
    ],
)
def test_missing_required_fields_are_rejected_with_field_name(field: str) -> None:
    with pytest.raises(AwinNormalizationError) as exc_info:
        normalize_awin_record(_record(**{field: "   "}))

    assert exc_info.value.field == field
    assert field in str(exc_info.value)


def test_html_unicode_quotes_semicolons_and_long_text_are_preserved_except_outer_whitespace() -> None:
    text = '  <p>Größe: 10×20&nbsp;cm; "Pro" • robust</p>' + (" x" * 2_000) + "  "

    normalized = normalize_awin_record(_record(description=text))

    assert normalized.description is not None
    assert normalized.description.startswith('<p>Größe: 10×20&nbsp;cm; "Pro" • robust</p>')
    assert len(normalized.description) > 4_000
    assert not normalized.description.startswith(" ")
    assert not normalized.description.endswith(" ")
