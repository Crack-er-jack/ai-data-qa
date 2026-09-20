"""Register pandas tables in DuckDB."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import duckdb
import pandas as pd

from src.ingestion.loader import ParsedTable


@dataclass
class DatasetMeta:
    original_filename: str
    table_name: str
    row_count: int
    column_count: int
    columns: list[str]
    dtypes: dict[str, str]
    null_counts: dict[str, int]
    size_bytes: int
    sheet_name: str | None = None
    original_columns: dict[str, str] = field(default_factory=dict)
    uploaded_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )


@dataclass
class Dataset:
    meta: DatasetMeta
    dataframe: pd.DataFrame


def dataset_from_parsed(parsed: ParsedTable) -> Dataset:
    frame = parsed.dataframe
    null_counts = {col: int(frame[col].isna().sum()) for col in frame.columns}
    dtypes = {col: str(frame[col].dtype) for col in frame.columns}
    meta = DatasetMeta(
        original_filename=parsed.original_filename,
        table_name=parsed.table_name,
        row_count=int(len(frame)),
        column_count=int(len(frame.columns)),
        columns=list(frame.columns),
        dtypes=dtypes,
        null_counts=null_counts,
        size_bytes=parsed.size_bytes,
        sheet_name=parsed.sheet_name,
        original_columns=parsed.original_columns,
    )
    return Dataset(meta=meta, dataframe=frame)


def create_connection(datasets: list[Dataset]) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    for dataset in datasets:
        connection.register(dataset.meta.table_name, dataset.dataframe)
    return connection
