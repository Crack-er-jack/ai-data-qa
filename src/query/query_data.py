"""Controlled query_data tool: validate, execute, bound results."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import duckdb
import pandas as pd

from src.constants import MAX_CELL_CHARS, MAX_LLM_RESULT_ROWS, MAX_RESULT_ROWS
from src.errors import QueryExecutionError, SqlValidationError
from src.query.validator import validate_sql


@dataclass
class QueryResult:
    success: bool
    sql: str
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    error: str | None = None
    dtypes: dict[str, str] = field(default_factory=dict)
    llm_preview: list[list[Any]] = field(default_factory=list)
    dataframe: pd.DataFrame | None = None

    def to_llm_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "success": self.success,
            "columns": self.columns,
            "row_count": self.row_count,
            "truncated": self.truncated,
            "preview_rows": self.llm_preview,
        }
        if self.error:
            payload["error"] = self.error
        return payload


def query_data(
    sql: str,
    connection: duckdb.DuckDBPyConnection,
    known_tables: set[str],
    known_columns: dict[str, set[str]] | None = None,
    max_rows: int = MAX_RESULT_ROWS,
    max_llm_rows: int = MAX_LLM_RESULT_ROWS,
) -> QueryResult:
    try:
        clean_sql = validate_sql(sql, known_tables, known_columns)
    except SqlValidationError as exc:
        return QueryResult(success=False, sql=sql, error=str(exc))

    bounded_sql = _apply_limit(clean_sql, max_rows + 1)
    try:
        frame = connection.execute(bounded_sql).fetchdf()
    except Exception as exc:
        return QueryResult(
            success=False,
            sql=clean_sql,
            error=f"DuckDB execution failed: {exc}",
        )

    truncated = len(frame) > max_rows
    if truncated:
        frame = frame.head(max_rows)

    display_frame = _clip_cells(frame)
    rows = display_frame.values.tolist()
    llm_preview = display_frame.head(max_llm_rows).values.tolist()
    dtypes = {col: str(display_frame[col].dtype) for col in display_frame.columns}
    return QueryResult(
        success=True,
        sql=clean_sql,
        columns=list(display_frame.columns),
        rows=rows,
        row_count=len(display_frame),
        truncated=truncated,
        dtypes=dtypes,
        llm_preview=llm_preview,
        dataframe=display_frame,
    )


def query_data_or_raise(
    sql: str,
    connection: duckdb.DuckDBPyConnection,
    known_tables: set[str],
    known_columns: dict[str, set[str]] | None = None,
) -> QueryResult:
    result = query_data(sql, connection, known_tables, known_columns)
    if not result.success:
        raise QueryExecutionError(result.error or "Query failed.")
    return result


def strip_trailing_semicolon(sql: str) -> str:
    """Safely strip trailing semicolons and whitespace without modifying literals."""
    s = sql.strip()
    while s.endswith(";"):
        s = s[:-1].strip()
    return s


def _apply_limit(sql: str, max_rows: int) -> str:
    """Ensure that the query execution is strictly bounded by max_rows.

    Preserves exact string literals, date literals, identifiers, CTEs, and ORDER BY clauses.
    If an existing trailing LIMIT is smaller than max_rows, it is preserved.
    Otherwise, wraps the query in a safe subquery envelope with LIMIT max_rows.

    Args:
        sql: The validated read-only SQL query string.
        max_rows: The maximum allowed number of rows to retrieve.

    Returns:
        SQL string guaranteed to have a bounded limit.
    """
    clean = strip_trailing_semicolon(sql)
    existing_limit = _extract_trailing_limit(clean)
    if existing_limit is not None and existing_limit <= max_rows:
        return clean
    return f"SELECT *\nFROM (\n{clean}\n) AS bounded_query\nLIMIT {max_rows}"


def _extract_trailing_limit(sql: str) -> int | None:
    """Extract integer value from trailing LIMIT clause if present."""
    match = re.search(r"\bLIMIT\s+(\d+)\s*$", sql, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def re_has_limit(sql: str) -> bool:
    """Check if query has a trailing limit."""
    return _extract_trailing_limit(sql) is not None


def _clip_cells(frame: pd.DataFrame) -> pd.DataFrame:
    """Clip oversized text values across string/object columns.

    Args:
        frame: Pandas DataFrame to clip.

    Returns:
        DataFrame with text cells capped at MAX_CELL_CHARS.
    """
    clipped = frame.copy()
    for column in clipped.columns:
        if (
            pd.api.types.is_string_dtype(clipped[column])
            or clipped[column].dtype == object
            or "string" in str(clipped[column].dtype).lower()
            or str(clipped[column].dtype) == "str"
        ):
            clipped[column] = clipped[column].map(_clip_value)
    return clipped


def _clip_value(value: Any) -> Any:
    """Cap string length to MAX_CELL_CHARS with an ellipsis."""
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        return value[:MAX_CELL_CHARS] + "…"
    return value
