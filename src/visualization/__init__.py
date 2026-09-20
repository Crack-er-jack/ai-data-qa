"""Plotly visualization selection with backend compatibility checks."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from src.results import ResultKind, classify_result

ALLOWED = {"kpi", "bar", "line", "histogram", "table", "none"}


def choose_visualization(
    frame: pd.DataFrame,
    suggestion: str | None = None,
    result_kind: ResultKind | None = None,
) -> str:
    kind = result_kind or classify_result(frame)
    compatible = _compatible_for(frame, kind)
    suggested = (suggestion or "").lower()
    if suggested not in {"", "none"} and suggested in compatible:
        return suggested
    if kind == "scalar":
        return "kpi"
    if kind == "time_series":
        return "line"
    if kind == "grouped":
        return "bar"
    if kind == "empty":
        return "none"
    numeric_cols = [c for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])]
    if len(frame.columns) == 1 and numeric_cols:
        return "histogram"
    return "table"


def build_figure(frame: pd.DataFrame, viz: str, title: str | None = None) -> Any | None:
    if frame is None or frame.empty or viz in {"none", "table", "kpi"}:
        return None
    try:
        if viz == "bar":
            return _bar(frame, title)
        if viz == "line":
            return _line(frame, title)
        if viz == "histogram":
            numeric = [c for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])]
            if not numeric:
                return None
            return px.histogram(frame, x=numeric[0], title=title)
    except Exception:
        return None
    return None


def _compatible_for(frame: pd.DataFrame, kind: ResultKind) -> set[str]:
    if kind == "empty":
        return {"none"}
    if kind == "scalar":
        return {"kpi", "table", "none"}
    if kind == "time_series":
        return {"line", "bar", "table", "none"}
    if kind == "grouped":
        return {"bar", "table", "none"}
    numeric = [c for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])]
    allowed = {"table", "none"}
    if len(numeric) == 1 and len(frame.columns) == 1:
        allowed.add("histogram")
    if len(numeric) >= 1 and len(frame.columns) >= 2:
        allowed.update({"bar", "line"})
    return allowed


def _bar(frame: pd.DataFrame, title: str | None) -> go.Figure:
    numeric = [c for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])]
    category = [c for c in frame.columns if c not in numeric]
    x = category[0] if category else frame.columns[0]
    y = numeric[0] if numeric else frame.columns[-1]
    return px.bar(frame, x=x, y=y, title=title)


def _line(frame: pd.DataFrame, title: str | None) -> go.Figure:
    numeric = [c for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])]
    time_cols = [c for c in frame.columns if c not in numeric]
    x = time_cols[0] if time_cols else frame.columns[0]
    y = numeric[0] if numeric else frame.columns[-1]
    ordered = frame.sort_values(by=x)
    return px.line(ordered, x=x, y=y, title=title, markers=True)
