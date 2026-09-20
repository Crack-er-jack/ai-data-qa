"""Regression tests for AnalysisPlan validation (BUG 1) and SQL fidelity (BUG 2)."""

from pathlib import Path

import pandas as pd
import pytest

from src.agent import _compose_message, audit_sql_fidelity, run_analysis
from src.context.builder import resolve_temporal_context
from src.context.state import AnalyticalState
from src.ingestion.loader import parse_upload
from src.ingestion.registry import create_connection, dataset_from_parsed
from src.llm.schemas import AnalysisPlan, SqlRequest
from src.results import FormattedResult
from src.session import add_datasets, empty_session

DEMO_DIR = Path(__file__).resolve().parent.parent / "demo_data"


class ScriptedPlanner:
    """Mock planner returning pre-defined plans for deterministic testing."""

    def __init__(self, plans: list[AnalysisPlan]) -> None:
        self.plans = list(plans)

    def plan(self, context: str, question: str, repair: str | None = None) -> AnalysisPlan:
        if not self.plans:
            raise AssertionError("Unexpected planner call: plan list is empty.")
        return self.plans.pop(0)


def _load_demo_session():
    """Load demo CSV datasets into a populated SessionData object."""
    session = empty_session()
    existing: set[str] = set()
    added = []
    for path in sorted(DEMO_DIR.glob("*.csv")):
        data = path.read_bytes()
        parsed = parse_upload(path.name, data, existing, size_bytes=len(data))
        for table in parsed:
            added.append(dataset_from_parsed(table))
            existing.add(table.table_name)
    return add_datasets(session, added)


# =====================================================================
# BUG 1 REGRESSION TESTS: AnalysisPlan explanation=None robustness
# =====================================================================


def test_bug1_analysis_plan_from_raw_handles_none_explanation():
    """Verify AnalysisPlan.from_raw parses cleanly when explanation is null/None."""
    raw_payload = {
        "intent": "metric",
        "clarification_needed": False,
        "cannot_answer": False,
        "required_tables": ["orders"],
        "sql_requests": [{"sql": "SELECT SUM(line_total) FROM orders", "purpose": "revenue"}],
        "expected_result_shape": "scalar",
        "visualization": "kpi",
        "explanation": None,  # Simulated LLM null output
        "metric": "revenue",
        "filters": {},
        "grouping": None,
        "time_period": None,
    }

    plan = AnalysisPlan.from_raw(raw_payload)
    # Plan must not raise ValidationError and explanation should default safely
    assert plan.explanation in (None, "")
    assert len(plan.sql_requests) == 1


def test_bug1_analysis_plan_direct_instantiation_allows_none_explanation():
    """Verify AnalysisPlan accepts explanation=None directly without validation error."""
    plan = AnalysisPlan(
        intent="metric",
        sql_requests=[SqlRequest(sql="SELECT 1")],
        explanation=None,
    )
    assert plan.explanation is None

    # Downstream message composition must handle None cleanly without crashing
    dummy_result = FormattedResult(
        kind="scalar",
        title="Total",
        text="Total: 100",
        dataframe=pd.DataFrame({"total": [100]}),
        sql="SELECT 1",
        truncated=False,
        scalar_value=100,
    )
    msg = _compose_message(plan.explanation, [dummy_result], ["Total: 100"])
    assert "Total: 100" in msg


# =====================================================================
# BUG 2 REGRESSION TESTS: Analytical state / SQL fidelity
# =====================================================================


def test_bug2_temporal_context_resolution():
    """Verify temporal_context resolves accurate date bounds from actual demo data."""
    session = _load_demo_session()
    temporal = resolve_temporal_context(session.profiles)
    assert temporal is not None
    assert temporal["table"] == "orders"
    assert temporal["date_column"] == "order_date"

    periods = temporal["resolved_periods"]
    # Verify last quarter (Q2 2026), latest quarter (Q3 2026), and years are grounded
    assert "last_quarter" in periods
    assert "2026-Q2" in periods["last_quarter"]["label"]
    assert "2026-04-01" in periods["last_quarter"]["sql_predicate"]
    assert "2026-06-30" in periods["last_quarter"]["sql_predicate"]

    assert "current_year" in periods
    assert "2026" in periods["current_year"]["label"]
    assert "previous_year" in periods
    assert "2025" in periods["previous_year"]["label"]


def test_bug2_regression_last_quarter_revenue_execution():
    """Regression test 1: Question for last quarter includes explicit date bounds in SQL."""
    session = _load_demo_session()
    connection = create_connection(session.datasets)

    # Resolved last quarter for the demo dataset is Q2 2026
    sql = (
        "SELECT ROUND(SUM(line_total), 2) AS last_quarter_revenue "
        "FROM orders "
        "WHERE status = 'completed' "
        "  AND order_date >= '2026-04-01' AND order_date <= '2026-06-30'"
    )
    plan = AnalysisPlan(
        intent="metric",
        required_tables=["orders"],
        sql_requests=[SqlRequest(sql=sql, purpose="revenue for Q2 2026")],
        expected_result_shape="scalar",
        visualization="kpi",
        explanation="Revenue for last quarter (Q2 2026).",
        metric="revenue",
        time_period="last quarter",
    )

    answer = run_analysis(
        "What was our total revenue last quarter?",
        session.profiles,
        session.relationships,
        AnalyticalState(),
        connection,
        planner=ScriptedPlanner([plan]),
    )
    assert answer.status == "ok"
    # Verify DuckDB computed the exact bounded revenue
    val = float(answer.results[0].scalar_value)
    assert val > 0
    # Last quarter revenue must be strictly less than all-time revenue
    all_time_rev = session.datasets[1].dataframe.loc[
        session.datasets[1].dataframe["status"] == "completed", "line_total"
    ].sum()
    assert val < all_time_rev


def test_bug2_regression_previous_year_revenue():
    """Regression test 2: Annual question filters strictly by year."""
    session = _load_demo_session()
    connection = create_connection(session.datasets)

    sql = (
        "SELECT ROUND(SUM(line_total), 2) AS revenue_2025 "
        "FROM orders "
        "WHERE status = 'completed' "
        "  AND order_date >= '2025-01-01' AND order_date <= '2025-12-31'"
    )
    plan = AnalysisPlan(
        intent="metric",
        required_tables=["orders"],
        sql_requests=[SqlRequest(sql=sql, purpose="2025 revenue")],
        expected_result_shape="scalar",
        visualization="kpi",
        explanation="Total revenue for 2025.",
        metric="revenue",
        time_period="2025",
    )

    answer = run_analysis(
        "What was our total revenue in 2025?",
        session.profiles,
        session.relationships,
        AnalyticalState(),
        connection,
        planner=ScriptedPlanner([plan]),
    )
    assert answer.status == "ok"
    assert float(answer.results[0].scalar_value) > 0


def test_bug2_regression_categorical_filter():
    """Regression test 3: Category question includes explicit category filter in SQL."""
    session = _load_demo_session()
    connection = create_connection(session.datasets)

    sql = (
        "SELECT ROUND(SUM(o.line_total), 2) AS hardware_revenue "
        "FROM orders o "
        "JOIN products p ON o.product_id = p.product_id "
        "WHERE o.status = 'completed' AND p.category = 'Hardware'"
    )
    plan = AnalysisPlan(
        intent="metric",
        required_tables=["orders", "products"],
        sql_requests=[SqlRequest(sql=sql, purpose="hardware revenue")],
        expected_result_shape="scalar",
        visualization="kpi",
        explanation="Revenue from Hardware category.",
        metric="revenue",
        filters={"category": "Hardware"},
    )

    answer = run_analysis(
        "What is the revenue from hardware products?",
        session.profiles,
        session.relationships,
        AnalyticalState(),
        connection,
        planner=ScriptedPlanner([plan]),
    )
    assert answer.status == "ok"
    # All-time hardware revenue in demo data is 108,590.35
    assert abs(float(answer.results[0].scalar_value) - 108590.35) < 1.0


def test_bug2_regression_combined_categorical_and_date_filter():
    """Regression test 4: Combined categorical + date filter executes with full fidelity."""
    session = _load_demo_session()
    connection = create_connection(session.datasets)

    # Hardware revenue in last quarter (Q2 2026)
    sql = (
        "SELECT ROUND(SUM(o.line_total), 2) AS q2_hardware_revenue "
        "FROM orders o "
        "JOIN products p ON o.product_id = p.product_id "
        "WHERE p.category = 'Hardware' "
        "  AND o.status = 'completed' "
        "  AND o.order_date >= '2026-04-01' AND o.order_date <= '2026-06-30'"
    )
    plan = AnalysisPlan(
        intent="metric",
        required_tables=["orders", "products"],
        sql_requests=[SqlRequest(sql=sql, purpose="Hardware revenue in Q2 2026")],
        expected_result_shape="scalar",
        visualization="kpi",
        explanation="Hardware revenue for last quarter (Q2 2026).",
        metric="revenue",
        filters={"category": "Hardware"},
        time_period="last quarter",
    )

    answer = run_analysis(
        "What is the revenue from hardware products in the last quarter?",
        session.profiles,
        session.relationships,
        AnalyticalState(),
        connection,
        planner=ScriptedPlanner([plan]),
    )
    assert answer.status == "ok"
    val = float(answer.results[0].scalar_value)
    # Exact DuckDB computed value for hardware in Q2 2026 is 8,550.85
    assert abs(val - 8550.85) < 0.1
    # Must be dramatically smaller than all-time hardware revenue (108,590.35)
    assert val < 50000.0


def test_bug2_fidelity_enforcement_rejects_missing_date_predicate():
    """Verify audit_sql_fidelity rejects plan specifying time_period when SQL omits date filter."""
    session = _load_demo_session()

    # Plan says 'last quarter', but SQL has NO date predicate
    bad_plan = AnalysisPlan(
        intent="metric",
        required_tables=["orders"],
        sql_requests=[
            SqlRequest(
                sql="SELECT SUM(line_total) FROM orders WHERE status = 'completed'",
                purpose="revenue",
            )
        ],
        metric="revenue",
        time_period="last quarter",
    )

    errors = audit_sql_fidelity(
        bad_plan,
        bad_plan.sql_requests[0].sql,
        "What was our revenue last quarter?",
        session.profiles,
    )
    # Auditor must flag that the date filter is missing from SQL
    assert len(errors) > 0
    assert "date predicate" in errors[0] or "time period" in errors[0]


def test_bug2_fidelity_enforcement_rejects_missing_category_filter():
    """Verify audit_sql_fidelity rejects plan specifying category filter when SQL omits it."""
    session = _load_demo_session()

    # Plan says category='Hardware', but SQL omitted it
    bad_plan = AnalysisPlan(
        intent="metric",
        required_tables=["orders"],
        sql_requests=[
            SqlRequest(
                sql="SELECT SUM(line_total) FROM orders WHERE status = 'completed'",
                purpose="revenue",
            )
        ],
        metric="revenue",
        filters={"category": "Hardware"},
    )

    errors = audit_sql_fidelity(
        bad_plan,
        bad_plan.sql_requests[0].sql,
        "What is revenue from hardware products?",
        session.profiles,
    )
    # Auditor must flag that the category filter is missing from SQL
    assert len(errors) > 0
    assert "category" in errors[0] or "Hardware" in errors[0]
