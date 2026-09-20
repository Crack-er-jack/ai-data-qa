"""Build compact, LLM-safe schema profiles from uploaded tables."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from src.constants import SAMPLE_VALUE_COUNT
from src.ingestion.registry import Dataset


@dataclass
class ColumnProfile:
    name: str
    original_name: str
    data_type: str
    pandas_dtype: str
    null_percentage: float
    cardinality: int | None
    sample_values: list[str]


@dataclass
class TableProfile:
    table_name: str
    original_filename: str
    row_count: int
    column_count: int
    columns: list[ColumnProfile]


def profile_dataset(dataset: Dataset) -> TableProfile:
    frame = dataset.dataframe
    columns = [
        profile_column(name, frame[name], dataset.meta.original_columns.get(name, name))
        for name in frame.columns
    ]
    return TableProfile(
        table_name=dataset.meta.table_name,
        original_filename=dataset.meta.original_filename,
        row_count=dataset.meta.row_count,
        column_count=dataset.meta.column_count,
        columns=columns,
    )


def profile_column(name: str, series: pd.Series, original_name: str) -> ColumnProfile:
    non_null = series.dropna()
    total = max(len(series), 1)
    null_percentage = round(float(series.isna().mean() * 100), 2)
    cardinality = int(non_null.nunique()) if len(non_null) else 0
    samples = _sample_values(non_null)
    return ColumnProfile(
        name=name,
        original_name=original_name,
        data_type=normalize_dtype(series),
        pandas_dtype=str(series.dtype),
        null_percentage=null_percentage,
        cardinality=cardinality if cardinality <= total else total,
        sample_values=samples,
    )


def normalize_dtype(series: pd.Series) -> str:
    dtype = series.dtype
    if pd.api.types.is_bool_dtype(dtype):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "datetime"
    if pd.api.types.is_integer_dtype(dtype):
        return "integer"
    if pd.api.types.is_float_dtype(dtype):
        return "float"
    if pd.api.types.is_numeric_dtype(dtype):
        return "numeric"
    if _looks_like_datetime(series):
        return "datetime"
    return "string"


def _looks_like_datetime(series: pd.Series) -> bool:
    non_null = series.dropna()
    if non_null.empty:
        return False
    name = str(series.name or "").lower()
    if not any(token in name for token in ("date", "time", "day", "month", "year")):
        return False
    if not (non_null.dtype == object or pd.api.types.is_string_dtype(non_null.dtype)):
        return False
    sample = non_null.head(20)
    parsed = pd.to_datetime(sample, errors="coerce")
    return bool(parsed.notna().mean() >= 0.8)


def _sample_values(series: pd.Series) -> list[str]:
    if series.empty:
        return []
    unique = series.astype(str).unique().tolist()
    values = unique[:SAMPLE_VALUE_COUNT]
    return [value[:80] for value in values]


def profiles_as_dicts(profiles: list[TableProfile]) -> list[dict]:
    return [asdict(profile) for profile in profiles]
