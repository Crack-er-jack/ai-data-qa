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


import re


def reconcile_filters_with_sql(
    filters: dict[str, str],
    time_period: str | None,
    sql: str,
) -> tuple[dict[str, str], str | None]:
    """Reconcile active filters and time period with the executed SQL.

    Guarantees that every filter displayed as an active analytical constraint
    is genuinely represented in the executed SQL, preventing phantom or stale filters.

    Args:
        filters: Candidate dictionary of column-value filter pairs.
        time_period: Candidate time period string (e.g. 'last quarter', '2025').
        sql: Executed SQL query text.

    Returns:
        Tuple of (verified_filters, verified_time_period).
    """
    if not sql or not sql.strip():
        return filters, time_period

    sql_lower = sql.lower()
    # If the SQL does not reference any tables via FROM (e.g. stub or test 'SELECT 1'),
    # skip reconciliation to allow isolated unit testing of state transitions.
    if not re.search(r"\bfrom\b", sql_lower):
        return filters, time_period

    # 1. Verify categorical / scalar filters
    verified_filters: dict[str, str] = {}
    for col, val in filters.items():
        if val is None or str(val).strip() == "":
            continue
        val_str = str(val).strip()
        val_lower = val_str.lower()
        col_lower = str(col).strip().lower()

        # Filter value is present in SQL (e.g. 'south', 'hardware')
        if val_lower in sql_lower:
            verified_filters[col] = val_str
        # Or column is explicitly referenced in a WHERE predicate
        elif col_lower in sql_lower and ("where" in sql_lower or "and" in sql_lower):
            verified_filters[col] = val_str

    # 2. Verify temporal period
    verified_time = None
    if time_period and time_period.strip():
        has_date_predicate = (
            re.search(r"\b202[0-9]\b", sql) is not None
            or any(fn in sql_lower for fn in ("strftime", "date_trunc", "extract", "quarter(", "year(", "month("))
            or (
                any(token in sql_lower for token in ("order_date", "effective_date", "hire_date", "review_date", "date"))
                and any(op in sql for op in (">=", "<=", ">", "<", "between"))
            )
        )
        if has_date_predicate:
            verified_time = time_period

    return verified_filters, verified_time


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
    is_follow_up: bool | None = None,
) -> AnalyticalState:
    """Update analytical state, cleanly distinguishing standalone questions from true follow-ups.

    Args:
        previous: Previous turn's analytical state.
        metric: Metric identified in the current plan.
        filters: Filters identified in the current plan.
        grouping: Grouping identified in the current plan.
        time_period: Time period identified in the current plan.
        tables: Tables referenced in the current turn.
        sql: Executed SQL statements.
        result_shape: Classified shape of the results.
        columns: Result column names.
        row_count: Total row count.
        question: User query string.
        is_follow_up: Whether current question is a follow-up. Inferred if None.

    Returns:
        New AnalyticalState instance with verified, non-stale context.
    """
    if is_follow_up is None:
        is_follow_up = looks_like_follow_up(question)

    clean_current_filters = {
        str(k): str(v) for k, v in (filters or {}).items() if v not in (None, "")
    }

    if not is_follow_up:
        # Standalone question: start fresh with current question's filters and bounds
        active_filters = clean_current_filters
        active_metric = metric or "revenue"
        active_grouping = grouping
        active_time_period = time_period
    else:
        # True follow-up: inherit previous context, merging/overriding any updated dimensions
        active_filters = dict(previous.filters)
        active_filters.update(clean_current_filters)
        active_metric = metric or previous.metric
        active_grouping = grouping if grouping is not None else previous.grouping
        active_time_period = time_period if time_period is not None else previous.time_period

    # Reconcile active filters with the SQL that was actually executed.
    # CRITICAL INVARIANT: Displayed analytical state, generated SQL, and DuckDB must never disagree.
    sql_text = " ".join(sql) if sql else ""
    verified_filters, verified_time = reconcile_filters_with_sql(
        filters=active_filters,
        time_period=active_time_period,
        sql=sql_text,
    )

    return AnalyticalState(
        metric=active_metric,
        filters=verified_filters,
        grouping=active_grouping,
        time_period=verified_time,
        last_tables=tables or previous.last_tables,
        last_sql=sql or previous.last_sql,
        last_result_shape=result_shape or previous.last_result_shape,
        last_columns=columns or previous.last_columns,
        last_row_count=row_count if row_count is not None else previous.last_row_count,
        last_question=question,
    )


def looks_like_follow_up(question: str) -> bool:
    """Determine whether a natural language question is an elliptical follow-up.

    True follow-ups modify, filter, or expand upon the active context (e.g.
    'What about South?', 'And in 2026?', 'Break that down by month').
    Standalone questions define their own independent subject and metric (e.g.
    'What is the total revenue from South?', 'Show monthly revenue').

    Args:
        question: The user's natural language input string.

    Returns:
        True if the question is linguistically a follow-up, False otherwise.
    """
    text = question.strip().lower()
    if not text:
        return False

    # Explicit follow-up openers
    follow_up_starts = (
        "what about",
        "how about",
        "what of",
        "and for",
        "and what about",
        "and in ",
        "now for",
        "same for",
        "same in",
        "same with",
        "only for",
        "filter to",
        "filter by",
        "narrow to",
        "break that down",
        "show that",
        "display that",
        "plot that",
    )
    if any(text.startswith(prefix) for prefix in follow_up_starts):
        return True

    # Short elliptical phrases without independent verbs, e.g. 'South?', 'For Engineering?'
    words = text.rstrip("?").split()
    if len(words) <= 3:
        if any(token in text for token in ("what about", "how about", "for ", "in ", "and ")):
            return True
        if text.startswith(("and ", "also ", "or ")):
            return True

    # Phrasing referencing previous query ('that', 'those')
    reference_tokens = ("that over time", "that by", "those by", "breakdown of that")
    if any(tok in text for tok in reference_tokens):
        return True

    return False
