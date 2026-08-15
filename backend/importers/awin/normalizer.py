"""Deterministic normalization for parsed AWIN product-feed records.

This module accepts one raw record produced by :mod:`backend.importers.awin.parser`
and converts it into a typed, repository-ready value object. It deliberately
contains no database access, deduplication, orchestration, or inferred product
matching.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Mapping


class AwinNormalizationError(ValueError):
    """Raised when a raw AWIN record cannot be normalized safely."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(f"{field}: {message}")


@dataclass(frozen=True, slots=True)
class AwinNormalizedRecord:
    """Normalized representation of one AWIN feed row.

    Source values remain traceable: no product identity matching or database
    identifiers are introduced here.
    """

    merchant_product_id: str
    aw_product_id: str
    merchant_id: str
    data_feed_id: str

    title: str
    description: str | None
    short_description: str | None
    brand: str | None
    category: str | None
    merchant_category: str | None
    awin_category_name: str | None
    awin_category_id: str | None

    price: Decimal | None
    currency: str | None
    availability: str

    product_url: str
    aw_deep_link: str | None

    ean: str | None
    gtin: str | None
    mpn: str | None

    product_model: str | None
    model_number: str | None
    parent_product_id: str | None
    product_type: str | None
    colour: str | None
    dimensions: str | None
    specifications: str | None
    variant_fields: Mapping[str, str | None]

    image_urls: tuple[str, ...]


IMAGE_FIELDS: tuple[str, ...] = (
    "merchant_image_url",
    "aw_image_url",
    "merchant_thumb_url",
    "large_image",
    "alternate_image",
    "aw_thumb_url",
    "alternate_image_two",
    "alternate_image_three",
    "alternate_image_four",
)

VARIANT_FIELDS: tuple[str, ...] = (
    "Fashion:suitable_for",
    "Fashion:category",
    "Fashion:size",
    "Fashion:material",
    "Fashion:pattern",
    "Fashion:swatch",
)

_TRUE_VALUES = frozenset({"1", "true", "yes", "y"})
_FALSE_VALUES = frozenset({"0", "false", "no", "n"})

_STOCK_STATUS_MAP: dict[str, str] = {
    "in stock": "in_stock",
    "out of stock": "out_of_stock",
    "pre order": "preorder",
    "pre-order": "preorder",
    "preorder": "preorder",
    "back order": "backorder",
    "back-order": "backorder",
    "backorder": "backorder",
    "unavailable": "unavailable",
    "discontinued": "discontinued",
}


def _clean_text(value: object) -> str | None:
    """Trim a string-like feed value and map blank strings to ``None``."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"AWIN feed values must be strings or None, got {type(value).__name__}")
    cleaned = value.strip()
    return cleaned or None


def _required_text(record: Mapping[str, str], field: str) -> str:
    value = _clean_text(record.get(field))
    if value is None:
        raise AwinNormalizationError(field, "required value is missing or blank")
    return value


def _parse_decimal(record: Mapping[str, str], field: str) -> Decimal | None:
    raw = _clean_text(record.get(field))
    if raw is None:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise AwinNormalizationError(field, f"invalid decimal value {raw!r}") from exc
    if not value.is_finite():
        raise AwinNormalizationError(field, f"non-finite decimal value {raw!r}")
    if value < 0:
        raise AwinNormalizationError(field, "price must not be negative")
    return value


def _normalize_currency(value: object) -> str | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    currency = cleaned.upper()
    if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
        raise AwinNormalizationError("currency", f"invalid ISO-style currency code {cleaned!r}")
    return currency


def _clean_gtin(value: object, field: str) -> str | None:
    """Trim GTIN/EAN values without guessing or rewriting their contents."""

    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    if not cleaned.isascii() or not cleaned.isdigit():
        raise AwinNormalizationError(field, f"GTIN/EAN must contain digits only, got {cleaned!r}")
    return cleaned


def _parse_boolean(value: object) -> bool | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    lowered = cleaned.casefold()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    return None


def derive_availability(record: Mapping[str, str]) -> str:
    """Derive the approved availability vocabulary from AWIN stock fields.

    Only explicit stock signals are used. Unknown or contradictory/unrecognised
    values fall back to ``unknown`` instead of being guessed.
    """

    pre_order = _parse_boolean(record.get("pre_order"))
    if pre_order is True:
        return "preorder"

    stock_status = _clean_text(record.get("stock_status"))
    if stock_status is not None:
        mapped = _STOCK_STATUS_MAP.get(stock_status.casefold())
        if mapped is not None:
            return mapped

    size_stock_status = _clean_text(record.get("size_stock_status"))
    if size_stock_status is not None:
        mapped = _STOCK_STATUS_MAP.get(size_stock_status.casefold())
        if mapped is not None:
            return mapped

    in_stock = _parse_boolean(record.get("in_stock"))
    if in_stock is True:
        return "in_stock"
    if in_stock is False:
        return "out_of_stock"

    is_for_sale = _parse_boolean(record.get("is_for_sale"))
    if is_for_sale is False:
        return "unavailable"

    return "unknown"


def collect_image_urls(record: Mapping[str, str]) -> tuple[str, ...]:
    """Collect existing AWIN image fields in feed order, removing exact duplicates.

    URLs are not resized, rewritten, decoded, canonicalised, or otherwise
    transformed. This prevents the normalizer from creating thumbnail variants.
    """

    urls: list[str] = []
    seen: set[str] = set()
    for field in IMAGE_FIELDS:
        url = _clean_text(record.get(field))
        if url is not None and url not in seen:
            seen.add(url)
            urls.append(url)
    return tuple(urls)


def normalize_awin_record(record: Mapping[str, str]) -> AwinNormalizedRecord:
    """Normalize one parsed AWIN record into a typed value object."""

    merchant_product_id = _required_text(record, "merchant_product_id")
    aw_product_id = _required_text(record, "aw_product_id")
    merchant_id = _required_text(record, "merchant_id")
    data_feed_id = _required_text(record, "data_feed_id")
    title = _required_text(record, "product_name")
    product_url = _required_text(record, "merchant_deep_link")

    price = _parse_decimal(record, "search_price")
    currency = _normalize_currency(record.get("currency"))
    if price is not None and currency is None:
        raise AwinNormalizationError("currency", "currency is required when search_price is present")

    ean = _clean_gtin(record.get("ean"), "ean")
    product_gtin = _clean_gtin(record.get("product_GTIN"), "product_GTIN")
    gtin = ean if ean is not None else product_gtin

    merchant_category = _clean_text(record.get("merchant_category"))
    awin_category_name = _clean_text(record.get("category_name"))
    category = merchant_category if merchant_category is not None else awin_category_name

    variant_values = {
        field: _clean_text(record.get(field))
        for field in VARIANT_FIELDS
    }

    return AwinNormalizedRecord(
        merchant_product_id=merchant_product_id,
        aw_product_id=aw_product_id,
        merchant_id=merchant_id,
        data_feed_id=data_feed_id,
        title=title,
        description=_clean_text(record.get("description")),
        short_description=_clean_text(record.get("product_short_description")),
        brand=_clean_text(record.get("brand_name")),
        category=category,
        merchant_category=merchant_category,
        awin_category_name=awin_category_name,
        awin_category_id=_clean_text(record.get("category_id")),
        price=price,
        currency=currency,
        availability=derive_availability(record),
        product_url=product_url,
        aw_deep_link=_clean_text(record.get("aw_deep_link")),
        ean=ean,
        gtin=gtin,
        mpn=_clean_text(record.get("mpn")),
        product_model=_clean_text(record.get("product_model")),
        model_number=_clean_text(record.get("model_number")),
        parent_product_id=_clean_text(record.get("parent_product_id")),
        product_type=_clean_text(record.get("product_type")),
        colour=_clean_text(record.get("colour")),
        dimensions=_clean_text(record.get("dimensions")),
        specifications=_clean_text(record.get("specifications")),
        variant_fields=MappingProxyType(variant_values),
        image_urls=collect_image_urls(record),
    )
