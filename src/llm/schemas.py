"""Structured analytical plan returned by the LLM."""

from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, Field, field_validator

ResultShape = Literal["scalar", "grouped", "time_series", "tabular", "unknown"]
VisualizationKind = Literal["kpi", "bar", "line", "histogram", "table", "none"]
Intent = Literal[
    "metric",
    "comparison",
    "trend",
    "breakdown",
    "lookup",
    "follow_up",
    "multi_question",
    "clarification",
    "unsupported",
]


class SqlRequest(BaseModel):
    sql: str = Field(..., min_length=1)
    purpose: str = Field(default="answer the user question")


class AnalysisPlan(BaseModel):
    intent: Intent = "metric"
    clarification_needed: bool = False
    clarification_question: str | None = None
    cannot_answer: bool = False
    cannot_answer_reason: str | None = None
    required_tables: list[str] = Field(default_factory=list)
    sql_requests: list[SqlRequest] = Field(default_factory=list)
    expected_result_shape: ResultShape = "unknown"
    visualization: VisualizationKind = "none"
    explanation: str = ""
    metric: str | None = None
    filters: dict[str, str] = Field(default_factory=dict)
    grouping: str | None = None
    time_period: str | None = None

    @field_validator("sql_requests")
    @classmethod
    def cap_sql_requests(cls, value: list[SqlRequest]) -> list[SqlRequest]:
        return value[:5]

    @classmethod
    def from_raw(cls, data: dict[str, Any]) -> "AnalysisPlan":
        """Parse raw dictionary output from LLM, ensuring safe defaults and types.

        Args:
            data: Dictionary response from the LLM JSON completion.

        Returns:
            Validated AnalysisPlan instance.
        """
        payload = dict(data)

        # Handle filters if returned as a list of key-value pairs
        if "filters" in payload and isinstance(payload["filters"], list):
            flattened: dict[str, str] = {}
            for item in payload["filters"]:
                if isinstance(item, dict) and "column" in item and "value" in item:
                    flattened[str(item["column"])] = str(item["value"])
            payload["filters"] = flattened
        # Handle filters if returned as dictionary with non-string/null values
        elif "filters" in payload and isinstance(payload["filters"], dict):
            payload["filters"] = {
                str(k): str(v)
                for k, v in payload["filters"].items()
                if v not in (None, "")
            }

        # Fallback to defaults if values are outside supported literals
        if payload.get("intent") not in get_args(Intent):
            payload["intent"] = "metric"
        if payload.get("visualization") not in get_args(VisualizationKind):
            payload["visualization"] = "none"
        if payload.get("expected_result_shape") not in get_args(ResultShape):
            payload["expected_result_shape"] = "unknown"

        return cls.model_validate(payload)

