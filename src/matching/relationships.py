"""Deterministic join-key candidates across uploaded tables."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from src.constants import OVERLAP_SAMPLE_LIMIT, RELATIONSHIP_MIN_OVERLAP
from src.ingestion.registry import Dataset
from src.profiling.schema import TableProfile, normalize_dtype


ID_HINTS = ("id", "key", "code", "sku", "uuid")
COMPATIBLE = {
    ("integer", "integer"),
    ("integer", "float"),
    ("float", "integer"),
    ("float", "float"),
    ("numeric", "integer"),
    ("numeric", "float"),
    ("integer", "numeric"),
    ("float", "numeric"),
    ("string", "string"),
    ("boolean", "boolean"),
    ("datetime", "datetime"),
}


@dataclass
class RelationshipCandidate:
    left_table: str
    left_column: str
    right_table: str
    right_column: str
    reason: str
    confidence: float
    overlap_ratio: float | None = None


def find_relationships(
    datasets: list[Dataset],
    profiles: list[TableProfile] | None = None,
) -> list[RelationshipCandidate]:
    by_name = {dataset.meta.table_name: dataset for dataset in datasets}
    columns: list[tuple[str, str, str, pd.Series]] = []
    profile_types: dict[tuple[str, str], str] = {}
    if profiles:
        for profile in profiles:
            for column in profile.columns:
                profile_types[(profile.table_name, column.name)] = column.data_type

    for dataset in datasets:
        for column in dataset.dataframe.columns:
            series = dataset.dataframe[column]
            dtype = profile_types.get(
                (dataset.meta.table_name, column), normalize_dtype(series)
            )
            columns.append((dataset.meta.table_name, column, dtype, series))

    candidates: list[RelationshipCandidate] = []
    seen: set[tuple[str, str, str, str]] = set()
    for i, left in enumerate(columns):
        for right in columns[i + 1 :]:
            if left[0] == right[0]:
                continue
            candidate = _score_pair(left, right, by_name)
            if candidate is None:
                continue
            key = (
                candidate.left_table,
                candidate.left_column,
                candidate.right_table,
                candidate.right_column,
            )
            reverse = (
                candidate.right_table,
                candidate.right_column,
                candidate.left_table,
                candidate.left_column,
            )
            if key in seen or reverse in seen:
                continue
            seen.add(key)
            candidates.append(candidate)

    candidates.sort(key=lambda item: item.confidence, reverse=True)
    return candidates


def _score_pair(
    left: tuple[str, str, str, pd.Series],
    right: tuple[str, str, str, pd.Series],
    datasets: dict[str, Dataset],
) -> RelationshipCandidate | None:
    left_table, left_col, left_type, left_series = left
    right_table, right_col, right_type, right_series = right
    if (left_type, right_type) not in COMPATIBLE:
        return None

    name_score = _name_similarity(left_col, right_col)
    if name_score == 0 and not (_is_id_like(left_col) and _is_id_like(right_col)):
        return None

    overlap = _overlap_ratio(left_series, right_series)
    confidence = name_score
    reasons = []
    if left_col == right_col:
        reasons.append("identical column names")
        confidence = max(confidence, 0.9)
    elif name_score >= 0.7:
        reasons.append("similar column names")
    if _is_id_like(left_col) and _is_id_like(right_col):
        reasons.append("id/key naming pattern")
        confidence = max(confidence, 0.75)
    if overlap is not None:
        if overlap >= RELATIONSHIP_MIN_OVERLAP:
            reasons.append(f"value overlap {overlap:.0%}")
            confidence = min(1.0, confidence + min(overlap, 0.2))
        elif name_score < 0.85:
            return None

    if not reasons:
        return None

    left_key = (left_table, left_col)
    right_key = (right_table, right_col)
    if left_key > right_key:
        left_table, left_col, right_table, right_col = (
            right_table,
            right_col,
            left_table,
            left_col,
        )
        overlap_left = overlap
    else:
        overlap_left = overlap

    return RelationshipCandidate(
        left_table=left_table,
        left_column=left_col,
        right_table=right_table,
        right_column=right_col,
        reason="; ".join(reasons),
        confidence=round(min(confidence, 1.0), 2),
        overlap_ratio=None if overlap_left is None else round(overlap_left, 3),
    )


def _name_similarity(left: str, right: str) -> float:
    if left == right:
        return 1.0
    left_n = left.replace("_", "")
    right_n = right.replace("_", "")
    if left_n == right_n:
        return 0.95
    if left.endswith("_id") and right.endswith("_id") and left.split("_id")[0] == right.split("_id")[0]:
        return 0.9
    if left in right or right in left:
        return 0.7
    return 0.0


def _is_id_like(name: str) -> bool:
    lowered = name.lower()
    return lowered == "id" or any(hint in lowered.split("_") for hint in ID_HINTS) or lowered.endswith("_id")


def _overlap_ratio(left: pd.Series, right: pd.Series) -> float | None:
    left_vals = _sample_set(left)
    right_vals = _sample_set(right)
    if not left_vals or not right_vals:
        return None
    smaller, larger = (left_vals, right_vals) if len(left_vals) <= len(right_vals) else (right_vals, left_vals)
    overlap = len(smaller & larger)
    return overlap / max(len(smaller), 1)


def _sample_set(series: pd.Series) -> set[str]:
    values = series.dropna()
    if len(values) > OVERLAP_SAMPLE_LIMIT:
        values = values.head(OVERLAP_SAMPLE_LIMIT)
    return set(values.astype(str).tolist())


def relationships_as_dicts(candidates: list[RelationshipCandidate]) -> list[dict]:
    return [asdict(item) for item in candidates]
