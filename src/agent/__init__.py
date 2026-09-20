"""Controlled analytical agent: LLM plans, DuckDB computes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import duckdb

from src.constants import MAX_ANALYTICAL_QUERIES, MAX_SQL_CORRECTION_RETRIES
from src.context.builder import build_context
from src.context.state import AnalyticalState, merge_state
from src.errors import LlmError
from src.llm.provider import GroqProvider
from src.llm.schemas import AnalysisPlan
from src.matching.relationships import RelationshipCandidate
from src.profiling.schema import TableProfile
from src.query.query_data import QueryResult, query_data
from src.results import FormattedResult, format_query_result
from src.visualization import build_figure, choose_visualization


class Planner(Protocol):
    def plan(self, context: str, question: str, repair: str | None = None) -> AnalysisPlan:
        ...


@dataclass
class AgentAnswer:
    question: str
    status: str
    message: str
    clarification: str | None = None
    results: list[FormattedResult] = field(default_factory=list)
    visualizations: list[Any] = field(default_factory=list)
    viz_types: list[str] = field(default_factory=list)
    sql_used: list[str] = field(default_factory=list)
    tables_used: list[str] = field(default_factory=list)
    filters: dict[str, str] = field(default_factory=dict)
    plan: AnalysisPlan | None = None
    errors: list[str] = field(default_factory=list)
    state: AnalyticalState | None = None


def run_analysis(
    question: str,
    profiles: list[TableProfile],
    relationships: list[RelationshipCandidate],
    state: AnalyticalState,
    connection: duckdb.DuckDBPyConnection,
    planner: Planner | None = None,
) -> AgentAnswer:
    question = (question or "").strip()
    if not question:
        return AgentAnswer(
            question=question,
            status="error",
            message="Enter a question about the uploaded data.",
            state=state,
        )
    if not profiles:
        return AgentAnswer(
            question=question,
            status="error",
            message="Upload at least one CSV or Excel file before asking a question.",
            state=state,
        )

    known_tables = {profile.table_name for profile in profiles}
    known_columns = {
        profile.table_name.lower(): {column.name for column in profile.columns}
        for profile in profiles
    }
    context = build_context(question, profiles, relationships, state)
    planner = planner or GroqProvider()

    try:
        plan = planner.plan(context, question)
    except LlmError as exc:
        return AgentAnswer(
            question=question,
            status="error",
            message=str(exc),
            errors=[str(exc)],
            state=state,
        )

    if plan.clarification_needed:
        return AgentAnswer(
            question=question,
            status="clarification",
            message=plan.clarification_question
            or "Could you clarify what you want to measure and which filters to apply?",
            clarification=plan.clarification_question,
            plan=plan,
            state=state,
        )
    if plan.cannot_answer:
        return AgentAnswer(
            question=question,
            status="cannot_answer",
            message=plan.cannot_answer_reason
            or "The uploaded data does not contain enough information to answer that question.",
            plan=plan,
            state=state,
        )

    sql_requests = [item for item in plan.sql_requests if item.sql.strip()][:MAX_ANALYTICAL_QUERIES]
    if not sql_requests:
        return AgentAnswer(
            question=question,
            status="cannot_answer",
            message="I could not produce a valid analytical query for that question. Try rephrasing it.",
            plan=plan,
            state=state,
        )

    executed: list[QueryResult] = []
    errors: list[str] = []
    remaining_retries = MAX_SQL_CORRECTION_RETRIES
    index = 0
    while index < len(sql_requests):
        request = sql_requests[index]
        result = query_data(
            request.sql,
            connection,
            known_tables,
            known_columns,
        )
        if result.success:
            executed.append(result)
            index += 1
            continue
        errors.append(result.error or "Query failed.")
        if remaining_retries <= 0:
            break
        remaining_retries -= 1
        try:
            repaired = planner.plan(
                context,
                question,
                repair=_repair_message(sql_requests, errors, result),
            )
        except LlmError as exc:
            errors.append(str(exc))
            break
        plan = repaired
        sql_requests = [item for item in repaired.sql_requests if item.sql.strip()][
            :MAX_ANALYTICAL_QUERIES
        ]
        executed = []
        index = 0

    if not executed:
        return AgentAnswer(
            question=question,
            status="error",
            message="The generated SQL could not be executed safely. "
            + (errors[-1] if errors else "Please rephrase the question."),
            errors=errors,
            plan=plan,
            sql_used=[item.sql for item in sql_requests],
            tables_used=plan.required_tables,
            state=state,
        )

    formatted = [
        format_query_result(item, purpose=sql_requests[i].purpose if i < len(sql_requests) else "Result")
        for i, item in enumerate(executed)
    ]
    viz_types: list[str] = []
    figures: list[Any] = []
    for item in formatted:
        viz = choose_visualization(
            item.dataframe,
            suggestion=plan.visualization,
            result_kind=item.kind,
        )
        viz_types.append(viz)
        figure = build_figure(item.dataframe, viz, title=item.title)
        if figure is not None:
            figures.append(figure)

    numbers = _collect_numbers(formatted)
    message = _compose_message(plan.explanation, formatted, numbers)
    tables_used = _tables_from_plan(plan, executed, known_tables)
    new_state = merge_state(
        previous=state,
        metric=plan.metric,
        filters=plan.filters,
        grouping=plan.grouping,
        time_period=plan.time_period,
        tables=tables_used,
        sql=[item.sql for item in executed],
        result_shape=formatted[0].kind if formatted else plan.expected_result_shape,
        columns=formatted[0].dataframe.columns.tolist() if formatted else [],
        row_count=sum(item.dataframe.shape[0] for item in formatted),
        question=question,
    )
    return AgentAnswer(
        question=question,
        status="ok",
        message=message,
        results=formatted,
        visualizations=figures,
        viz_types=viz_types,
        sql_used=[item.sql for item in executed],
        tables_used=tables_used,
        filters=new_state.filters,
        plan=plan,
        errors=errors,
        state=new_state,
    )


def _repair_message(requests, errors: list[str], last: QueryResult) -> str:
    return (
        f"Failed SQL:\n{last.sql}\n\n"
        f"Error: {last.error}\n"
        f"Earlier errors: {errors}\n"
        "Return a full corrected JSON plan. Keep the same analytical intent."
    )


def _collect_numbers(results: list[FormattedResult]) -> list[str]:
    values = []
    for item in results:
        if item.kind == "scalar" and item.scalar_value is not None:
            values.append(item.text)
    return values


def _compose_message(
    explanation: str,
    results: list[FormattedResult],
    numbers: list[str],
) -> str:
    parts = []
    if explanation:
        parts.append(explanation.strip())
    if len(results) == 1 and results[0].kind == "scalar":
        parts.append(results[0].text)
    elif numbers:
        parts.append("Computed values: " + "; ".join(numbers))
    if any(item.truncated for item in results):
        parts.append("The displayed result set is truncated for size.")
    if not parts:
        return "Here is the result computed from your uploaded data."
    return "\n\n".join(parts)


def _tables_from_plan(
    plan: AnalysisPlan,
    executed: list[QueryResult],
    known_tables: set[str],
) -> list[str]:
    from src.query.validator import extract_table_names

    found: list[str] = []
    for result in executed:
        for name in extract_table_names(result.sql):
            if name in {t.lower() for t in known_tables} and name not in found:
                found.append(name)
    if plan.required_tables:
        for name in plan.required_tables:
            if name in known_tables and name not in found:
                found.append(name)
    return found or list(known_tables)
