"""Compact context for each LLM planning call."""

from __future__ import annotations

import json
from typing import Any

from src.context.state import AnalyticalState, looks_like_follow_up
from src.matching.relationships import RelationshipCandidate
from src.profiling.schema import TableProfile


def build_context(
    question: str,
    profiles: list[TableProfile],
    relationships: list[RelationshipCandidate],
    state: AnalyticalState,
) -> str:
    """Build a compact, high-signal context packet for LLM planning.

    Includes datasets metadata, candidate relationships, structured previous
    state, and ground-truth temporal periods derived from dataset dates.

    Args:
        question: The user's natural language question.
        profiles: Schema and column profiles for all active tables.
        relationships: Inferred cross-table join candidate pairs.
        state: Structured analytical context from previous turns.

    Returns:
        JSON string containing the contextual planning packet.
    """
    temporal = resolve_temporal_context(profiles)
    payload: dict[str, Any] = {
        "datasets": [_compact_profile(profile) for profile in profiles],
        "candidate_relationships": [
            {
                "left": f"{item.left_table}.{item.left_column}",
                "right": f"{item.right_table}.{item.right_column}",
                "reason": item.reason,
                "confidence": item.confidence,
            }
            for item in relationships[:12]
        ],
        "analytical_state": _relevant_state(question, state),
        "notes": [
            "Use only these tables and columns.",
            "Join using candidate relationships when needed.",
            "If a follow-up changes one filter, keep the previous metric and other filters.",
            "Do not request raw datasets.",
            "SQL FIDELITY: When the question refers to a time period (e.g. 'last quarter', 'this year', '2025') or category, you MUST include the exact WHERE filter in the SQL.",
        ],
    }
    if temporal:
        payload["temporal_context"] = temporal

    return json.dumps(payload, default=str)


def resolve_temporal_context(profiles: list[TableProfile]) -> dict[str, Any] | None:
    """Resolve ground-truth date ranges and relative period bounds from data.

    Calculates deterministic start and end dates for 'last quarter', 'latest quarter',
    'current year', and 'previous year' based on the dataset's actual date values
    rather than fabricating dates.

    Args:
        profiles: List of table profiles.

    Returns:
        Dictionary of temporal period definitions with SQL predicates, or None.
    """
    import pandas as pd

    best_date_col: str | None = None
    table_name: str | None = None
    min_date_val: pd.Timestamp | None = None
    max_date_val: pd.Timestamp | None = None

    # Inspect all profiles for datetime columns with min/max bounds
    for profile in profiles:
        for col in profile.columns:
            if col.data_type == "datetime" or "date" in col.name.lower():
                if col.min_value and col.max_value:
                    try:
                        cur_min = pd.to_datetime(col.min_value)
                        cur_max = pd.to_datetime(col.max_value)
                        if max_date_val is None or cur_max > max_date_val:
                            max_date_val = cur_max
                            min_date_val = cur_min
                            best_date_col = col.name
                            table_name = profile.table_name
                    except Exception:
                        continue

    if best_date_col is None or max_date_val is None or min_date_val is None:
        return None

    cur_year = max_date_val.year
    prev_year = cur_year - 1

    # Determine quarter relative to dataset max date
    cur_quarter = (max_date_val.month - 1) // 3 + 1
    if cur_quarter > 1:
        prev_quarter = cur_quarter - 1
        prev_quarter_year = cur_year
    else:
        prev_quarter = 4
        prev_quarter_year = cur_year - 1

    def _quarter_bounds(year: int, q: int) -> tuple[str, str]:
        starts = {1: "01-01", 2: "04-01", 3: "07-01", 4: "10-01"}
        ends = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
        return f"{year}-{starts[q]}", f"{year}-{ends[q]}"

    last_q_start, last_q_end = _quarter_bounds(prev_quarter_year, prev_quarter)
    lat_q_start, lat_q_end = _quarter_bounds(cur_year, cur_quarter)
    return {
        "table": table_name,
        "date_column": best_date_col,
        "dataset_min_date": min_date_val.strftime("%Y-%m-%d"),
        "dataset_max_date": max_date_val.strftime("%Y-%m-%d"),
        "resolved_periods": {
            "last_quarter": {
                "label": f"{prev_quarter_year}-Q{prev_quarter} ({last_q_start} to {last_q_end})",
                "sql_predicate": f"{best_date_col} >= '{last_q_start}' AND {best_date_col} <= '{last_q_end}'",
            },
            "latest_quarter": {
                "label": f"{cur_year}-Q{cur_quarter} ({lat_q_start} to {lat_q_end})",
                "sql_predicate": f"{best_date_col} >= '{lat_q_start}' AND {best_date_col} <= '{lat_q_end}'",
            },
            "current_year": {
                "label": str(cur_year),
                "sql_predicate": f"{best_date_col} >= '{cur_year}-01-01' AND {best_date_col} <= '{cur_year}-12-31'",
            },
            "previous_year": {
                "label": str(prev_year),
                "sql_predicate": f"{best_date_col} >= '{prev_year}-01-01' AND {best_date_col} <= '{prev_year}-12-31'",
            },
        },
    }


def _compact_profile(profile: TableProfile) -> dict[str, Any]:
    columns_data = []
    for column in profile.columns:
        col_dict = {
            "name": column.name,
            "type": column.data_type,
            "null_pct": column.null_percentage,
            "cardinality": column.cardinality,
            "samples": column.sample_values,
        }
        if column.min_value is not None and column.max_value is not None:
            col_dict["min_val"] = column.min_value
            col_dict["max_val"] = column.max_value
        columns_data.append(col_dict)

    return {
        "table": profile.table_name,
        "source_file": profile.original_filename,
        "row_count": profile.row_count,
        "columns": columns_data,
    }


def _relevant_state(question: str, state: AnalyticalState) -> dict[str, Any]:
    if not state.last_question and not state.metric and not state.filters:
        return {"available": False}
    is_follow_up = looks_like_follow_up(question)
    if not is_follow_up:
        return {
            "available": True,
            "is_follow_up": False,
            "previous_question": state.last_question,
            "note": "This is a new standalone question. Do not inherit previous filters or time periods unless explicitly asked.",
        }
    data: dict[str, Any] = {
        "available": True,
        "is_follow_up": True,
        "metric": state.metric,
        "filters": state.filters,
        "grouping": state.grouping,
        "time_period": state.time_period,
        "relevant_tables": state.last_tables,
        "last_result_shape": state.last_result_shape,
        "last_result_columns": state.last_columns,
        "last_result_row_count": state.last_row_count,
        "last_question": state.last_question,
    }
    if state.last_sql:
        data["previous_sql"] = state.last_sql[:2]
    return data
