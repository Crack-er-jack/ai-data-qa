"""Structured analytical state for follow-up questions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AnalyticalState:
    metric: str | None = None
    filters: dict[str, str] = field(default_factory=dict)
    grouping: str | None = None
    time_period: str | None = None
    last_tables: list[str] = field(default_factory=list)
    last_sql: list[str] = field(default_factory=list)
    last_result_shape: str | None = None
    last_columns: list[str] = field(default_factory=list)
    last_row_count: int | None = None
    last_question: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AnalyticalState":
        if not data:
            return cls()
        return cls(
            metric=data.get("metric"),
            filters=dict(data.get("filters") or {}),
            grouping=data.get("grouping"),
            time_period=data.get("time_period"),
            last_tables=list(data.get("last_tables") or []),
            last_sql=list(data.get("last_sql") or []),
            last_result_shape=data.get("last_result_shape"),
            last_columns=list(data.get("last_columns") or []),
            last_row_count=data.get("last_row_count"),
            last_question=data.get("last_question"),
        )


def merge_state(
    previous: AnalyticalState,
    metric: str | None,
    filters: dict[str, str] | None,
    grouping: str | None,
    time_period: str | None,
    tables: list[str],
    sql: list[str],
    result_shape: str | None,
    columns: list[str],
    row_count: int | None,
    question: str,
) -> AnalyticalState:
    merged_filters = dict(previous.filters)
    if filters:
        merged_filters.update({k: v for k, v in filters.items() if v not in (None, "")})
    return AnalyticalState(
        metric=metric or previous.metric,
        filters=merged_filters,
        grouping=grouping if grouping is not None else previous.grouping,
        time_period=time_period if time_period is not None else previous.time_period,
        last_tables=tables or previous.last_tables,
        last_sql=sql or previous.last_sql,
        last_result_shape=result_shape or previous.last_result_shape,
        last_columns=columns or previous.last_columns,
        last_row_count=row_count if row_count is not None else previous.last_row_count,
        last_question=question,
    )


def looks_like_follow_up(question: str) -> bool:
    text = question.strip().lower()
    prefixes = (
        "what about",
        "how about",
        "and for",
        "same for",
        "now for",
        "filter to",
        "only for",
        "vs ",
        "compared to",
        "break that down",
        "by region",
        "by month",
        "by category",
        "and south",
        "and north",
        "and east",
        "and west",
    )
    if text.startswith(("what about", "how about", "and ", "also ", "same ")):
        return True
    return any(token in text for token in prefixes)
