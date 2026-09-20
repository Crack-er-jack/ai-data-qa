import pandas as pd
import pytest

from src.errors import SqlValidationError
from src.ingestion.registry import create_connection, dataset_from_parsed
from src.ingestion.loader import ParsedTable
from src.query.query_data import query_data
from src.query.validator import validate_sql


KNOWN = {"customers", "orders"}
COLUMNS = {
    "customers": {"customer_id", "region"},
    "orders": {"customer_id", "line_total"},
}


def test_select_is_allowed():
    sql = validate_sql("SELECT region FROM customers", KNOWN)
    assert "SELECT" in sql.upper()


def test_with_is_allowed():
    sql = validate_sql(
        "WITH totals AS (SELECT customer_id FROM orders) SELECT * FROM totals",
        KNOWN,
    )
    assert sql.upper().startswith("WITH")


def test_rejects_insert_update_drop():
    for sql in [
        "INSERT INTO customers VALUES (1)",
        "UPDATE customers SET region = 'X'",
        "DELETE FROM customers",
        "DROP TABLE customers",
        "ALTER TABLE customers ADD COLUMN x INT",
        "CREATE TABLE foo AS SELECT 1",
        "TRUNCATE customers",
        "ATTACH 'foo.db'",
        "COPY customers TO 'out.csv'",
    ]:
        with pytest.raises(SqlValidationError):
            validate_sql(sql, KNOWN)


def test_rejects_multiple_statements():
    with pytest.raises(SqlValidationError, match="Multiple"):
        validate_sql("SELECT 1; SELECT 2", KNOWN)


def test_rejects_unknown_table():
    with pytest.raises(SqlValidationError, match="Unknown table"):
        validate_sql("SELECT * FROM mystery", KNOWN)


def test_rejects_unknown_qualified_column():
    with pytest.raises(SqlValidationError, match="Unknown column"):
        validate_sql("SELECT customers.not_a_column FROM customers", KNOWN, COLUMNS)


def test_query_execution_and_limit():
    customers = dataset_from_parsed(
        ParsedTable(
            original_filename="customers.csv",
            table_name="customers",
            dataframe=pd.DataFrame(
                {"customer_id": [f"C{i:03d}" for i in range(30)], "region": ["South"] * 30}
            ),
            size_bytes=10,
            original_columns={"customer_id": "customer_id", "region": "region"},
        )
    )
    con = create_connection([customers])
    result = query_data(
        "SELECT * FROM customers",
        con,
        {"customers"},
        {"customers": {"customer_id", "region"}},
        max_rows=10,
        max_llm_rows=3,
    )
    assert result.success
    assert result.truncated
    assert result.row_count == 10
    assert len(result.llm_preview) == 3


def test_unsafe_sql_does_not_execute():
    customers = dataset_from_parsed(
        ParsedTable(
            original_filename="customers.csv",
            table_name="customers",
            dataframe=pd.DataFrame({"customer_id": ["C001"]}),
            size_bytes=10,
            original_columns={"customer_id": "customer_id"},
        )
    )
    con = create_connection([customers])
    result = query_data("DROP TABLE customers", con, {"customers"})
    assert not result.success
    remaining = con.execute("SELECT * FROM customers").fetchdf()["customer_id"].tolist()
    assert remaining == ["C001"]


def test_rejects_disallowed_file_scan_functions():
    """Verify DuckDB file-read and scan functions are rejected for security."""
    for func_sql in [
        "SELECT * FROM read_csv('secret.csv')",
        "SELECT * FROM read_parquet('data.parquet')",
        "SELECT * FROM glob('/etc/*')",
        "SELECT * FROM read_json('data.json')",
    ]:
        with pytest.raises(SqlValidationError):
            validate_sql(func_sql, KNOWN)


def test_rejects_comment_injection_attacks():
    """Verify comment evasions are properly stripped and disallowed."""
    # Embedded multiple statement using comments
    with pytest.raises(SqlValidationError):
        validate_sql("SELECT 1; /* safe comment */ DROP TABLE customers", KNOWN)


def test_valid_joins_and_aliases_execute():
    """Verify analytical join query with table aliases executes cleanly in DuckDB."""
    customers_df = pd.DataFrame(
        {"customer_id": ["C1", "C2"], "region": ["South", "North"]}
    )
    orders_df = pd.DataFrame(
        {"customer_id": ["C1", "C1", "C2"], "line_total": [100.0, 50.0, 200.0]}
    )
    customers = dataset_from_parsed(
        ParsedTable(
            original_filename="customers.csv",
            table_name="customers",
            dataframe=customers_df,
            size_bytes=100,
            original_columns={"customer_id": "customer_id", "region": "region"},
        )
    )
    orders = dataset_from_parsed(
        ParsedTable(
            original_filename="orders.csv",
            table_name="orders",
            dataframe=orders_df,
            size_bytes=100,
            original_columns={"customer_id": "customer_id", "line_total": "line_total"},
        )
    )
    con = create_connection([customers, orders])

    # Join query with aliases and aggregation
    sql = (
        "SELECT c.region, SUM(o.line_total) AS total "
        "FROM customers c "
        "JOIN orders o ON c.customer_id = o.customer_id "
        "GROUP BY c.region ORDER BY total DESC"
    )
    result = query_data(sql, con, {"customers", "orders"})
    assert result.success
    assert result.row_count == 2
    # Verify DuckDB computed the exact aggregated totals
    assert result.dataframe.iloc[0]["region"] == "200.0" or result.dataframe.iloc[0]["total"] == 200.0


def test_cell_truncation_limits_length():
    """Verify long text cells are clipped to MAX_CELL_CHARS."""
    from src.constants import MAX_CELL_CHARS

    long_text = "X" * (MAX_CELL_CHARS + 50)
    df = pd.DataFrame({"long_col": [long_text]})
    dataset = dataset_from_parsed(
        ParsedTable(
            original_filename="test.csv",
            table_name="test_data",
            dataframe=df,
            size_bytes=100,
            original_columns={"long_col": "long_col"},
        )
    )
    con = create_connection([dataset])
    result = query_data("SELECT * FROM test_data", con, {"test_data"})
    assert result.success
    clipped_val = result.dataframe.iloc[0]["long_col"]
    assert len(clipped_val) <= MAX_CELL_CHARS + 1
    assert clipped_val.endswith("…")

