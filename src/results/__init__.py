"""Deterministic result classification and formatting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

import pandas as pd

from src.query.query_data import QueryResult

ResultKind = Literal["scalar", "grouped", "time_series", "tabular", "empty"]


@dataclass
class FormattedResult:
    kind: ResultKind
    title: str
    text: str
    dataframe: pd.DataFrame
    sql: str
    truncated: bool
    scalar_value: Any | None = None
    scalar_label: str | None = None


def classify_result(frame: pd.DataFrame) -> ResultKind:
    if frame is None or frame.empty:
        return "empty"
    numeric_cols = [c for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])]
    time_cols = [c for c in frame.columns if _is_time_like(frame[c])]
    category_cols = [
        c
        for c in frame.columns
        if c not in numeric_cols and c not in time_cols
    ]
    if len(frame) == 1 and len(numeric_cols) == 1 and len(frame.columns) <= 2:
        return "scalar"
    if time_cols and numeric_cols:
        return "time_series"
    if category_cols and numeric_cols and len(frame) <= 50:
        return "grouped"
    return "tabular"


def format_query_result(result: QueryResult, purpose: str = "Result") -> FormattedResult:
    frame = result.dataframe if result.dataframe is not None else pd.DataFrame()
    kind = classify_result(frame)
    if kind == "empty":
        return FormattedResult(
            kind="empty",
            title=purpose,
            text="The query returned no rows for the uploaded data.",
            dataframe=frame,
            sql=result.sql,
            truncated=result.truncated,
        )
    if kind == "scalar":
        numeric_cols = [c for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])]
        label = numeric_cols[0] if numeric_cols else frame.columns[0]
        value = frame.iloc[0][label]
        pretty = _pretty_label(label)
        return FormattedResult(
            kind="scalar",
            title=purpose,
            text=f"{pretty}: {_format_number(value)}",
            dataframe=frame,
            sql=result.sql,
            truncated=result.truncated,
            scalar_value=value,
            scalar_label=pretty,
        )
    return FormattedResult(
        kind=kind,
        title=purpose,
        text=_table_preview(frame),
        dataframe=frame,
        sql=result.sql,
        truncated=result.truncated,
    )


def _pretty_label(name: str) -> str:
    return name.replace("_", " ").strip().title()


def _format_number(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "n/a"
    if isinstance(value, (int,)) or (isinstance(value, float) and float(value).is_integer()):
        return f"{int(value):,}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def _table_preview(frame: pd.DataFrame, rows: int = 8) -> str:
    preview = frame.head(rows).copy()
    for column in preview.columns:
        if pd.api.types.is_numeric_dtype(preview[column]):
            preview[column] = preview[column].map(_format_number)
    return preview.to_string(index=False)


def _is_time_like(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if series.empty:
        return False
    name = str(series.name).lower()
    if any(token in name for token in ("date", "month", "year", "week", "time")):
        sample = series.dropna().astype(str).head(10)
        parsed = pd.to_datetime(sample, errors="coerce")
        return bool(parsed.notna().mean() >= 0.7)
    if series.dtype == object or pd.api.types.is_string_dtype(series):
        sample = series.dropna().head(8)
        if sample.empty:
            return False
        if all(isinstance(v, (datetime, date)) for v in sample):
            return True
    return False
