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
        ],
    }
    return json.dumps(payload, default=str)


def _compact_profile(profile: TableProfile) -> dict[str, Any]:
    return {
        "table": profile.table_name,
        "source_file": profile.original_filename,
        "row_count": profile.row_count,
        "columns": [
            {
                "name": column.name,
                "type": column.data_type,
                "null_pct": column.null_percentage,
                "cardinality": column.cardinality,
                "samples": column.sample_values,
            }
            for column in profile.columns
        ],
    }


def _relevant_state(question: str, state: AnalyticalState) -> dict[str, Any]:
    if not state.last_question and not state.metric and not state.filters:
        return {"available": False}
    include_preview = looks_like_follow_up(question) or bool(state.metric or state.filters)
    data: dict[str, Any] = {
        "available": True,
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
    if include_preview and state.last_sql:
        data["previous_sql"] = state.last_sql[:2]
    return data
