from pathlib import Path

import pandas as pd
import pytest

from src.ingestion.loader import parse_upload, validate_file
from src.ingestion.names import normalize_identifier, table_name_from_filename
from src.errors import FileValidationError
from src.constants import MAX_FILE_SIZE_BYTES, MAX_SESSION_SIZE_BYTES


def test_normalize_identifier_strips_and_lowers():
    assert normalize_identifier("Customer ID") == "customer_id"
    assert normalize_identifier("  Revenue ($) ") == "revenue"
    assert normalize_identifier("123abc") == "col_123abc"
    assert normalize_identifier("") == "col"


def test_duplicate_table_names_get_suffix():
    existing = {"customers"}
    assert table_name_from_filename("customers.csv", existing) == "customers_2"


def test_reject_unsupported_extension():
    with pytest.raises(FileValidationError, match="Unsupported"):
        validate_file("notes.txt", 100)


def test_reject_oversize_file():
    with pytest.raises(FileValidationError, match="per-file limit"):
        validate_file("big.csv", MAX_FILE_SIZE_BYTES + 1)


def test_reject_session_over_capacity():
    with pytest.raises(FileValidationError, match="session limit"):
        validate_file("more.csv", 10, session_bytes=MAX_SESSION_SIZE_BYTES)


def test_parse_csv_roundtrip(tmp_path: Path):
    csv = "region,revenue\nSouth,10\nNorth,20\n"
    tables = parse_upload("sales.csv", csv.encode(), existing_tables=set())
    assert len(tables) == 1
    table = tables[0]
    assert table.table_name == "sales"
    assert list(table.dataframe.columns) == ["region", "revenue"]
    assert len(table.dataframe) == 2


def test_empty_csv_rejected():
    with pytest.raises(FileValidationError):
        parse_upload("empty.csv", b"", existing_tables=set())


def test_header_only_csv_rejected():
    with pytest.raises(FileValidationError, match="no rows"):
        parse_upload("headers.csv", b"a,b\n", existing_tables=set())


def test_parse_excel_xlsx_multiple_sheets():
    """Verify that Excel .xlsx files with multiple sheets are parsed correctly."""
    import io
    import openpyxl

    # Create an in-memory workbook with two sheets
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Customers"
    ws1.append(["Customer ID", "Customer Name"])
    ws1.append(["C001", "Acme Corp"])

    ws2 = wb.create_sheet(title="Orders")
    ws2.append(["Order ID", "Amount ($)"])
    ws2.append(["O001", 125.50])

    buf = io.BytesIO()
    wb.save(buf)
    excel_bytes = buf.getvalue()

    tables = parse_upload("data_export.xlsx", excel_bytes, existing_tables=set())
    assert len(tables) == 2

    # Check table names and column sanitization
    table_names = {t.table_name for t in tables}
    assert any("customers" in name for name in table_names)
    assert any("orders" in name for name in table_names)

    # Check that data was loaded correctly into dataframes
    for t in tables:
        assert not t.dataframe.empty
        assert t.size_bytes == len(excel_bytes)


def test_sanitize_columns_handles_symbols_and_duplicates():
    """Ensure sanitize_columns removes symbols, trims whitespace, and deduplicates."""
    from src.ingestion.names import sanitize_columns

    raw_cols = ["  Customer ID  ", "Revenue ($)", "123_Growth_%", "Customer ID"]
    safe, mapping = sanitize_columns(raw_cols)

    # All column names should be valid lowercased identifiers
    assert safe[0] == "customer_id"
    assert safe[1] == "revenue"
    assert safe[2].startswith("col_") and "123_growth" in safe[2]
    # Duplicate 'Customer ID' must be disambiguated
    assert safe[3] == "customer_id_2"
    assert len(safe) == len(set(safe))
    assert mapping[safe[0]] == "  Customer ID  "


def test_table_name_normalization_with_special_characters():
    """Ensure table_name_from_filename produces clean DuckDB-safe table names."""
    existing = {"sales_data"}
    # Leading numbers, spaces, and punctuation
    name = table_name_from_filename("2024 Q1 - Sales Report!.csv", existing)
    assert name.startswith("table_2024_q1_sales_report")
    assert not any(char in name for char in " -!")

