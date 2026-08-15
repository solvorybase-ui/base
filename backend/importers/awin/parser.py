"""Streaming parser for AWIN CSV product feeds.

This module is intentionally limited to parsing and structural validation.
It does not normalize values, deduplicate records, or access a database.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path
from typing import TextIO


AWIN_HEADER: tuple[str, ...] = (
    "aw_deep_link",
    "product_name",
    "aw_product_id",
    "merchant_product_id",
    "merchant_image_url",
    "description",
    "merchant_category",
    "search_price",
    "merchant_name",
    "merchant_id",
    "category_name",
    "category_id",
    "aw_image_url",
    "currency",
    "store_price",
    "delivery_cost",
    "merchant_deep_link",
    "language",
    "last_updated",
    "display_price",
    "data_feed_id",
    "brand_name",
    "brand_id",
    "colour",
    "product_short_description",
    "specifications",
    "condition",
    "product_model",
    "model_number",
    "dimensions",
    "keywords",
    "promotional_text",
    "product_type",
    "commission_group",
    "merchant_product_category_path",
    "merchant_product_second_category",
    "merchant_product_third_category",
    "rrp_price",
    "saving",
    "savings_percent",
    "base_price",
    "base_price_amount",
    "base_price_text",
    "product_price_old",
    "delivery_restrictions",
    "delivery_weight",
    "warranty",
    "terms_of_contract",
    "delivery_time",
    "in_stock",
    "stock_quantity",
    "valid_from",
    "valid_to",
    "is_for_sale",
    "web_offer",
    "pre_order",
    "stock_status",
    "size_stock_status",
    "size_stock_amount",
    "merchant_thumb_url",
    "large_image",
    "alternate_image",
    "aw_thumb_url",
    "alternate_image_two",
    "alternate_image_three",
    "alternate_image_four",
    "reviews",
    "average_rating",
    "rating",
    "number_available",
    "custom_1",
    "custom_2",
    "custom_3",
    "custom_4",
    "custom_5",
    "custom_6",
    "custom_7",
    "custom_8",
    "custom_9",
    "ean",
    "isbn",
    "upc",
    "mpn",
    "parent_product_id",
    "product_GTIN",
    "basket_link",
    "Fashion:suitable_for",
    "Fashion:category",
    "Fashion:size",
    "Fashion:material",
    "Fashion:pattern",
    "Fashion:swatch",
    "ShoppingNL:energy_label",
    "ShoppingNL:energy_label_link",
    "ShoppingNL:energy_label_logo",
    "ShoppingNL:google_taxonomy",
)


class AwinParserError(ValueError):
    """Base error for structurally invalid AWIN CSV input."""


class AwinHeaderError(AwinParserError):
    """Raised when the CSV header does not match the approved AWIN feed format."""


class AwinRowError(AwinParserError):
    """Raised when a CSV record has a different column count than the header."""


def validate_header(header: list[str] | tuple[str, ...]) -> None:
    """Validate the exact ordered AWIN header used by the approved feed."""

    actual = tuple(header)
    if actual == AWIN_HEADER:
        return

    missing = [field for field in AWIN_HEADER if field not in actual]
    unexpected = [field for field in actual if field not in AWIN_HEADER]

    details: list[str] = [
        f"expected {len(AWIN_HEADER)} columns, received {len(actual)}"
    ]
    if missing:
        details.append(f"missing: {', '.join(missing)}")
    if unexpected:
        details.append(f"unexpected: {', '.join(unexpected)}")
    if not missing and not unexpected and actual != AWIN_HEADER:
        details.append("column order differs from the approved AWIN header")

    raise AwinHeaderError("Invalid AWIN CSV header (" + "; ".join(details) + ")")


def iter_awin_stream(stream: TextIO) -> Iterator[dict[str, str]]:
    """Yield AWIN records from an already-open text stream.

    Values are returned exactly as parsed by :mod:`csv`. Empty CSV fields remain
    empty strings. No trimming, type conversion, or other normalization occurs.
    """

    reader = csv.reader(stream, delimiter=";", quotechar='"')

    try:
        header = next(reader)
    except StopIteration as exc:
        raise AwinHeaderError("AWIN CSV is empty; header row is missing") from exc

    validate_header(header)
    expected_columns = len(AWIN_HEADER)

    for line_number, row in enumerate(reader, start=2):
        if len(row) != expected_columns:
            raise AwinRowError(
                f"Invalid AWIN CSV row at line {line_number}: "
                f"expected {expected_columns} columns, received {len(row)}"
            )

        yield dict(zip(AWIN_HEADER, row, strict=True))


def iter_awin_rows(path: str | Path) -> Iterator[dict[str, str]]:
    """Stream AWIN records from a UTF-8 CSV file without loading it into memory."""

    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        yield from iter_awin_stream(stream)
