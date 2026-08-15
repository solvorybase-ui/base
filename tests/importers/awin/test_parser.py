from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path

import pytest

from backend.importers.awin.parser import (
    AWIN_HEADER,
    AWIN_OPTIONAL_FIELDS,
    AWIN_REQUIRED_FIELDS,
    AwinHeaderError,
    AwinRowError,
    iter_awin_rows,
    iter_awin_stream,
    validate_header,
)


FIXTURE = Path(__file__).parents[2] / "fixtures" / "awin" / "sample.csv"


def _csv_text(header: tuple[str, ...], rows: list[list[str]] | None = None) -> str:
    output = StringIO(newline="")
    writer = csv.writer(output, delimiter=";", lineterminator="\n")
    writer.writerow(header)
    for row in rows or []:
        writer.writerow(row)
    return output.getvalue()


def test_existing_96_column_feed_header_is_accepted() -> None:
    with FIXTURE.open("r", encoding="utf-8", newline="") as stream:
        header = next(csv.reader(stream, delimiter=";"))

    assert len(header) == 96
    assert tuple(header) == AWIN_HEADER
    validate_header(header)


def test_streams_real_fixture_records_as_strings() -> None:
    records = iter_awin_rows(FIXTURE)

    first = next(records)

    assert first["aw_product_id"] == "36013645938"
    assert first["merchant_product_id"] == "658207"
    assert first["merchant_id"] == "496"
    assert first["search_price"] == "13.95"
    assert isinstance(first["search_price"], str)


def test_empty_values_remain_empty_strings() -> None:
    records = list(iter_awin_rows(FIXTURE))

    assert any(record["store_price"] == "" for record in records)
    assert any(record["isbn"] == "" for record in records)
    assert all(value is not None for record in records for value in record.values())


def test_semicolon_inside_quoted_long_description_is_preserved() -> None:
    records = list(iter_awin_rows(FIXTURE))
    record = next(item for item in records if item["aw_product_id"] == "36013645938")

    assert ";" in record["description"]
    assert "&bull;" in record["description"]
    assert len(record["description"]) > 1_000


def test_quotes_inside_real_feed_text_are_preserved() -> None:
    records = list(iter_awin_rows(FIXTURE))
    record = next(item for item in records if item["aw_product_id"] == "44021382747")

    assert '5" mini long nose pliers' in record["description"]
    assert '4.5" mini side cutters' in record["description"]


def test_unicode_and_special_characters_are_preserved() -> None:
    records = list(iter_awin_rows(FIXTURE))
    record = next(item for item in records if item["aw_product_id"] == "43439485474")

    assert "•" in record["description"]
    assert "\xa0" in record["description"]


def test_long_real_feed_text_is_not_truncated() -> None:
    records = list(iter_awin_rows(FIXTURE))
    longest = max(records, key=lambda item: len(item["description"]))

    assert longest["aw_product_id"] == "39632417048"
    assert len(longest["description"]) == 3783


def test_bellerei_86_column_header_is_accepted() -> None:
    bellerei_header = tuple(field for field in AWIN_HEADER if field not in AWIN_OPTIONAL_FIELDS)

    assert len(bellerei_header) == 86
    validate_header(bellerei_header)


def test_all_declared_optional_fields_may_be_missing() -> None:
    header = tuple(field for field in AWIN_HEADER if field not in AWIN_OPTIONAL_FIELDS)

    assert set(header) == set(AWIN_REQUIRED_FIELDS)
    validate_header(header)


def test_additional_unknown_columns_are_tolerated_and_mapped() -> None:
    header = (*AWIN_HEADER, "Advertiser:future_field")
    row = [""] * len(header)
    row[-1] = "future value"

    records = list(iter_awin_stream(StringIO(_csv_text(header, [row]))))

    assert records[0]["Advertiser:future_field"] == "future value"


def test_rejects_missing_required_header_field() -> None:
    invalid_header = tuple(field for field in AWIN_HEADER if field != "merchant_product_id")

    with pytest.raises(AwinHeaderError, match=r"missing required field\(s\): merchant_product_id"):
        validate_header(invalid_header)


def test_reordered_required_header_is_accepted_and_values_follow_actual_header() -> None:
    header = list(AWIN_HEADER)
    header[0], header[1] = header[1], header[0]
    row = [""] * len(header)
    row[0] = "Reordered product"
    row[1] = "https://example.test/awin"

    records = list(iter_awin_stream(StringIO(_csv_text(tuple(header), [row]))))

    assert records[0]["product_name"] == "Reordered product"
    assert records[0]["aw_deep_link"] == "https://example.test/awin"


def test_rejects_empty_file() -> None:
    with pytest.raises(AwinHeaderError, match="header row is missing"):
        list(iter_awin_stream(StringIO("")))


def test_rejects_row_with_wrong_column_count() -> None:
    short_row = [""] * (len(AWIN_HEADER) - 1)
    stream = StringIO(_csv_text(AWIN_HEADER, [short_row]))

    with pytest.raises(AwinRowError, match="line 2"):
        list(iter_awin_stream(stream))
