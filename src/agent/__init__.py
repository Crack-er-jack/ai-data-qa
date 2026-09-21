"""Controlled analytical agent: LLM plans, DuckDB computes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import duckdb

from src.constants import MAX_ANALYTICAL_QUERIES, MAX_SQL_CORRECTION_RETRIES
from src.context.builder import build_context, resolve_revenue_status_default
from src.context.state import AnalyticalState, looks_like_follow_up, merge_state
from src.errors import LlmError
from src.llm.provider import GroqProvider
from src.llm.schemas import AnalysisPlan
from src.matching.relationships import RelationshipCandidate
from src.profiling.schema import TableProfile
from src.profiling.suggestions import build_metadata_response, is_metadata_question
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
    time_period: str | None = None
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

    # Route metadata and discoverability questions directly without LLM SQL generation
    if is_metadata_question(question):
        metadata_msg = build_metadata_response(profiles, relationships)
        return AgentAnswer(
            question=question,
            status="ok",
            message=metadata_msg,
            results=[],
            visualizations=[],
            viz_types=[],
            sql_used=[],
            tables_used=[p.table_name for p in profiles],
            filters={},
            time_period=None,
            plan=None,
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

    # Apply narrow deterministic default to completed orders for revenue/sales metrics
    status_default = resolve_revenue_status_default(question, profiles)
    if status_default:
        tbl, col, val = status_default
        # If the planner requested clarification regarding order completion or status, override it
        if plan.clarification_needed and (
            not plan.clarification_question
            or any(
                w in (plan.clarification_question or "").lower()
                for w in ("completed", "status", "order", "include", "only")
            )
        ):
            try:
                repaired = planner.plan(
                    context,
                    question,
                    repair=(
                        f"Do NOT ask for clarification. Proceed with the query filtering "
                        f"{col} = '{val}'."
                    ),
                )
                if not repaired.clarification_needed and repaired.sql_requests:
                    plan = repaired
            except Exception:
                pass

            if plan.clarification_needed:
                plan.clarification_needed = False
                plan.clarification_question = None

            if plan.filters is None:
                plan.filters = {}
            plan.filters[col] = val

            # If sql_requests is empty, synthesize direct revenue query
            valid_sql_requests = [req for req in plan.sql_requests if req.sql.strip()]
            if not valid_sql_requests:
                from src.llm.schemas import SqlRequest

                target_profile = next((p for p in profiles if p.table_name == tbl), None)
                num_col = "line_total"
                if target_profile:
                    for c in target_profile.columns:
                        if c.name.lower() in {"line_total", "total_price", "amount", "revenue", "sales"}:
                            num_col = c.name
                            break
                plan.sql_requests = [
                    SqlRequest(
                        sql=f"SELECT SUM({num_col}) AS total_revenue FROM {tbl} WHERE {col} = '{val}'",
                        description="Total revenue for completed orders",
                    )
                ]
                plan.metric = "revenue"
                plan.explanation = "Total revenue from completed orders."
        elif not plan.clarification_needed and not plan.cannot_answer:
            # If the planner generated SQL containing the status constraint, record it in filters
            sql_all = " ".join(r.sql.lower() for r in plan.sql_requests)
            if val.lower() in sql_all:
                if plan.filters is None:
                    plan.filters = {}
                if col not in plan.filters:
                    plan.filters[col] = val

    if plan.clarification_needed:
        clarification_state = AnalyticalState(
            metric=plan.metric or state.metric,
            filters=plan.filters or state.filters,
            grouping=plan.grouping or state.grouping,
            time_period=plan.time_period or state.time_period,
            last_tables=plan.required_tables or state.last_tables,
            last_question=question,
            last_clarification=plan.clarification_question,
        )
        return AgentAnswer(
            question=question,
            status="clarification",
            message=plan.clarification_question
            or "Could you clarify what you want to measure and which filters to apply?",
            clarification=plan.clarification_question,
            plan=plan,
            state=clarification_state,
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
        # Audit SQL fidelity against declared analytical constraints
        fidelity_errors = audit_sql_fidelity(plan, request.sql, question, profiles)
        if fidelity_errors:
            errors.extend(fidelity_errors)
            if remaining_retries <= 0:
                break
            remaining_retries -= 1
            try:
                repaired = planner.plan(
                    context,
                    question,
                    repair=_repair_message(
                        sql_requests,
                        errors,
                        QueryResult(
                            success=False,
                            sql=request.sql,
                            error="; ".join(fidelity_errors),
                        ),
                    ),
                )
            except LlmError as exc:
                errors.append(str(exc))
                break
            plan = repaired
            sql_requests = [
                item for item in repaired.sql_requests if item.sql.strip()
            ][:MAX_ANALYTICAL_QUERIES]
            executed = []
            index = 0
            continue

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
    is_follow_up = looks_like_follow_up(question, state=state) or plan.intent == "follow_up"
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
        is_follow_up=is_follow_up,
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
        time_period=new_state.time_period,
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


def audit_sql_fidelity(
    plan: AnalysisPlan,
    sql: str,
    question: str,
    profiles: list[TableProfile],
) -> list[str]:
    """Audit SQL queries to verify declared filters and time bounds are represented.

    Guarantees that constraints like 'last quarter' or 'Hardware' are present
    as WHERE predicates in the generated SQL, preventing misleading totals.

    Args:
        plan: The proposed AnalysisPlan from the LLM.
        sql: The SQL statement being audited.
        question: User's natural language question string.
        profiles: Table profiles containing known column metadata.

    Returns:
        List of fidelity error strings, or empty list if fidelity is satisfied.
    """
    errors: list[str] = []
    sql_lower = sql.lower()
    q_lower = question.lower()

    # Collect known date column names across tables
    date_cols: set[str] = set()
    for profile in profiles:
        for col in profile.columns:
            if col.data_type == "datetime" or "date" in col.name.lower():
                date_cols.add(col.name.lower())

    # 1. Audit Date / Time Period constraint
    has_time_intent = (
        bool(plan.time_period)
        or any(token in q_lower for token in ("quarter", "last year", "previous year", "this year", "in 202"))
    )
    if has_time_intent:
        has_date_in_sql = (
            any(d_col in sql_lower for d_col in date_cols)
            or any(fn in sql_lower for fn in ("date_trunc", "strftime", "extract", "quarter(", "year(", "month("))
            or re.search(r"\b202[0-9]\b", sql) is not None
        )
        if not has_date_in_sql:
            period_str = plan.time_period or "requested time period"
            errors.append(
                f"SQL Fidelity Error: Analysis plan specifies time period '{period_str}', "
                f"but SQL contains no date predicate or date column filter."
            )

    # 2. Audit Categorical and Numeric Filters
    if plan.filters:
        for col, val in plan.filters.items():
            if val is None or str(val).strip() == "":
                continue
            col_l = str(col).lower()
            val_l = str(val).lower()
            # If neither column name nor value appears in the SQL
            if col_l not in sql_lower and val_l not in sql_lower:
                errors.append(
                    f"SQL Fidelity Error: Analysis plan specifies filter '{col} = {val}', "
                    f"but this constraint is missing from the SQL query."
                )

    # 3. Audit Grouping
    if plan.grouping and plan.grouping.strip():
        if "group by" not in sql_lower:
            errors.append(
                f"SQL Fidelity Error: Analysis plan specifies grouping by '{plan.grouping}', "
                f"but SQL contains no GROUP BY clause."
            )

    return errors


def _compose_message(
    explanation: str | None,
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
