"""Deterministic table/column name sanitization."""

from __future__ import annotations

import re
from pathlib import Path

_INVALID = re.compile(r"[^a-z0-9_]+")


def normalize_identifier(raw: str, fallback: str = "col") -> str:
    name = (raw or "").strip().lower().replace(" ", "_")
    name = _INVALID.sub("_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if not name:
        name = fallback
    if not name[0].isalpha() and name[0] != "_":
        name = f"{fallback}_{name}"
    return name


def table_name_from_filename(filename: str, existing: set[str]) -> str:
    stem = Path(filename).stem
    base = normalize_identifier(stem, fallback="table")
    return uniquify(base, existing)


def uniquify(base: str, existing: set[str]) -> str:
    candidate = base
    index = 2
    while candidate in existing:
        candidate = f"{base}_{index}"
        index += 1
    return candidate


def sanitize_columns(columns: list[str]) -> tuple[list[str], dict[str, str]]:
    used: set[str] = set()
    safe: list[str] = []
    mapping: dict[str, str] = {}
    for i, original in enumerate(columns):
        normalized = normalize_identifier(str(original), fallback=f"col_{i + 1}")
        unique = uniquify(normalized, used)
        used.add(unique)
        safe.append(unique)
        mapping[unique] = str(original)
    return safe, mapping
