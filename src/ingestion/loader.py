"""Validate and parse uploaded CSV / Excel files."""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

import pandas as pd

from src.constants import (
    MAX_FILE_SIZE_BYTES,
    MAX_SESSION_SIZE_BYTES,
    SUPPORTED_EXTENSIONS,
)
from src.errors import FileValidationError, IngestionError
from src.ingestion.names import sanitize_columns, table_name_from_filename


@dataclass
class ParsedTable:
    original_filename: str
    table_name: str
    dataframe: pd.DataFrame
    size_bytes: int
    sheet_name: str | None = None
    original_columns: dict[str, str] = field(default_factory=dict)


def validate_file(filename: str, size_bytes: int, session_bytes: int = 0) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise FileValidationError(
            f"Unsupported file type '{suffix or filename}'. Upload CSV or Excel (.csv, .xlsx, .xls)."
        )
    if size_bytes <= 0:
        raise FileValidationError(f"'{filename}' is empty.")
    if size_bytes > MAX_FILE_SIZE_BYTES:
        limit_mb = MAX_FILE_SIZE_BYTES // (1024 * 1024)
        raise FileValidationError(
            f"'{filename}' exceeds the {limit_mb} MB per-file limit."
        )
    if session_bytes + size_bytes > MAX_SESSION_SIZE_BYTES:
        limit_mb = MAX_SESSION_SIZE_BYTES // (1024 * 1024)
        raise FileValidationError(
            f"Uploading '{filename}' would exceed the {limit_mb} MB session limit."
        )


def parse_upload(
    filename: str,
    data: bytes,
    existing_tables: set[str],
    size_bytes: int | None = None,
    session_bytes: int = 0,
) -> list[ParsedTable]:
    size = size_bytes if size_bytes is not None else len(data)
    validate_file(filename, size, session_bytes)
    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".csv":
            frames = _read_csv(data)
        else:
            frames = _read_excel(data, suffix)
    except FileValidationError:
        raise
    except Exception as exc:
        raise IngestionError(f"Could not read '{filename}': {exc}") from exc

    parsed: list[ParsedTable] = []
    used = set(existing_tables)
    for sheet_name, frame in frames:
        table = _normalize_frame(filename, frame, used, size, sheet_name)
        used.add(table.table_name)
        parsed.append(table)
    return parsed


def _read_csv(data: bytes) -> list[tuple[str | None, pd.DataFrame]]:
    try:
        frame = pd.read_csv(BytesIO(data))
    except Exception:
        frame = pd.read_csv(BytesIO(data), encoding="latin-1")
    return [(None, frame)]


def _read_excel(data: bytes, suffix: str) -> list[tuple[str | None, pd.DataFrame]]:
    engine = "openpyxl" if suffix == ".xlsx" else "xlrd"
    book = pd.read_excel(BytesIO(data), sheet_name=None, engine=engine)
    frames: list[tuple[str | None, pd.DataFrame]] = []
    for sheet_name, frame in book.items():
        frames.append((str(sheet_name), frame))
    if not frames:
        raise FileValidationError("The Excel workbook has no readable sheets.")
    return frames


def _normalize_frame(
    filename: str,
    frame: pd.DataFrame,
    existing_tables: set[str],
    size_bytes: int,
    sheet_name: str | None,
) -> ParsedTable:
    if frame.empty and len(frame.columns) == 0:
        raise FileValidationError(f"'{filename}' has no columns or rows.")
    if len(frame.columns) == 0:
        raise FileValidationError(f"'{filename}' has no columns.")

    safe_columns, original_columns = sanitize_columns([str(c) for c in frame.columns])
    frame = frame.copy()
    frame.columns = safe_columns
    for column in frame.columns:
        if frame[column].dtype == "object":
            frame[column] = frame[column].convert_dtypes()

    base_name = table_name_from_filename(filename, existing_tables)
    if sheet_name and len(existing_tables | {base_name}) and sheet_name.lower() not in {
        "sheet1",
        "sheet",
        "data",
    }:
        from src.ingestion.names import normalize_identifier, uniquify

        sheet_id = normalize_identifier(sheet_name, fallback="sheet")
        if sheet_id and sheet_id not in {"sheet1", "sheet"}:
            candidate = f"{base_name}_{sheet_id}"
            base_name = uniquify(candidate, existing_tables)

    if frame.empty:
        raise FileValidationError(
            f"'{filename}' was read but contains no rows. Upload a non-empty dataset."
        )

    return ParsedTable(
        original_filename=filename,
        table_name=base_name,
        dataframe=frame,
        size_bytes=size_bytes,
        sheet_name=sheet_name,
        original_columns=original_columns,
    )
