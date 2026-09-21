"""Regression tests for analytical context resolution and SQL query bounding.

Validates:
1. Context resolution: distinguishes standalone questions (clearing stale filters/dates)
   from genuine follow-ups (inheriting and merging context).
2. UI / SQL fidelity invariant: active filters and time periods shown in the UI
   must always be represented in the executed SQL.
3. SQL result bounding: wraps queries in safe subquery envelope preserving exact
   string literals, date literals, identifiers, CTEs, and ORDER BY clauses.
4. End-to-end multi-turn sequences on synthetic retail data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pytest

from src.agent import AgentAnswer, run_analysis
from src.context.state import AnalyticalState, looks_like_follow_up, merge_state, reconcile_filters_with_sql
from src.ingestion.loader import parse_upload
from src.ingestion.registry import create_connection, dataset_from_parsed
from src.llm.schemas import AnalysisPlan, SqlRequest
from src.profiling.schema import profile_dataset
from src.query.query_data import _apply_limit, query_data, strip_trailing_semicolon
from src.query.validator import split_statements, strip_sql_comments, validate_sql
from src.session import add_datasets, empty_session


DATA_DIR = Path(__file__).resolve().parent.parent / "test_data" / "retail"


class ScriptedPlanner:
    """Mock planner that yields pre-configured AnalysisPlan instances."""

    def __init__(self, plans: list[AnalysisPlan]) -> None:
        self.plans = list(plans)

    def plan(self, context: str, question: str, repair: str | None = None) -> AnalysisPlan:
        if not self.plans:
            raise AssertionError(f"Unexpected extra planner call for: '{question}'")
        return self.plans.pop(0)


def _load_retail_session():
    """Load the synthetic retail dataset into an in-memory session."""
    session = empty_session()
    existing: set[str] = set()
    added = []
    for path in sorted(DATA_DIR.glob("*.csv")):
        parsed = parse_upload(path.name, path.read_bytes(), existing, size_bytes=path.stat().st_size)
        for table in parsed:
            added.append(dataset_from_parsed(table))
            existing.add(table.table_name)
    return add_datasets(session, added)


# =========================================================================
# 1. SQL Result Bounding & Literal Preservation Tests
# =========================================================================

@pytest.fixture
def sample_connection() -> duckdb.DuckDBPyConnection:
    """Create in-memory DuckDB connection populated with test orders."""
    con = duckdb.connect(":memory:")
    con.execute("""
        CREATE TABLE orders (
            order_id VARCHAR PRIMARY KEY,
            region VARCHAR,
            category VARCHAR,
            order_date DATE,
            line_total DOUBLE
        );
        INSERT INTO orders VALUES
        ('ORD-1', 'North', 'Hardware', '2026-04-10', 1200.0),
        ('ORD-2', 'South', 'Hardware', '2026-05-15', 2400.0),
        ('ORD-3', 'South', 'Software', '2026-05-20', 800.0),
        ('ORD-4', 'North', 'Accessories', '2026-06-01', 150.0),
        ('ORD-5', 'West', 'Services', '2026-07-04', 3000.0);
    """)
    return con


def test_bounding_1_simple_select(sample_connection):
    """Test result bounding on a simple SELECT query."""
    sql = "SELECT * FROM orders"
    bounded = _apply_limit(sql, 201)
    df = sample_connection.execute(bounded).fetchdf()
    assert len(df) == 5
    assert "AS bounded_query" in bounded


def test_bounding_2_where_string_filter(sample_connection):
    """Test result bounding preserving single-quoted string literal."""
    sql = "SELECT * FROM orders WHERE region = 'North'"
    bounded = _apply_limit(sql, 201)
    assert "'North'" in bounded
    df = sample_connection.execute(bounded).fetchdf()
    assert len(df) == 2
    assert (df["region"] == "North").all()


def test_bounding_3_multiple_string_filters(sample_connection):
    """Test result bounding preserving multiple string filter literals."""
    sql = "SELECT * FROM orders WHERE region = 'South' AND category = 'Hardware'"
    bounded = _apply_limit(sql, 201)
    assert "'South'" in bounded
    assert "'Hardware'" in bounded
    df = sample_connection.execute(bounded).fetchdf()
    assert len(df) == 1
    assert df.iloc[0]["order_id"] == "ORD-2"


def test_bounding_4_date_filters_intact(sample_connection):
    """Verify exact date string literals '2026-04-01' and '2026-06-30' remain intact."""
    sql = (
        "SELECT * FROM orders "
        "WHERE order_date >= '2026-04-01' AND order_date <= '2026-06-30'"
    )
    bounded = _apply_limit(sql, 201)
    # Both date string literals must remain completely intact without missing quotes
    assert "'2026-04-01'" in bounded
    assert "'2026-06-30'" in bounded
    assert "'2026-06-30) AS bounded_query" not in bounded  # Regression check for unclosed quote
    df = sample_connection.execute(bounded).fetchdf()
    assert len(df) == 4


def test_bounding_5_combined_date_and_categorical(sample_connection):
    """Verify combined date and categorical filters in bounded envelope."""
    sql = (
        "SELECT * FROM orders "
        "WHERE category = 'Hardware' "
        "  AND order_date >= '2026-04-01' AND order_date <= '2026-06-30'"
    )
    bounded = _apply_limit(sql, 201)
    assert "'Hardware'" in bounded
    assert "'2026-04-01'" in bounded
    assert "'2026-06-30'" in bounded
    df = sample_connection.execute(bounded).fetchdf()
    assert len(df) == 2


def test_bounding_6_cte_query(sample_connection):
    """Verify Common Table Expressions (WITH clause) inside bounding wrapper."""
    sql = """
    WITH q2_orders AS (
        SELECT * FROM orders
        WHERE order_date >= '2026-04-01' AND order_date <= '2026-06-30'
    )
    SELECT region, SUM(line_total) AS total
    FROM q2_orders
    GROUP BY region
    """
    bounded = _apply_limit(sql, 201)
    df = sample_connection.execute(bounded).fetchdf()
    assert len(df) == 2
    assert set(df["region"]) == {"North", "South"}


def test_bounding_7_order_by_query(sample_connection):
    """Verify queries with ORDER BY clauses retain ordering inside bounded wrapper."""
    sql = "SELECT order_id, line_total FROM orders ORDER BY line_total DESC"
    bounded = _apply_limit(sql, 201)
    df = sample_connection.execute(bounded).fetchdf()
    assert len(df) == 5
    assert df.iloc[0]["order_id"] == "ORD-5"
    assert df.iloc[-1]["order_id"] == "ORD-4"


def test_bounding_8_existing_limit_preserved(sample_connection):
    """Verify existing smaller LIMIT clause is preserved without unnecessary wrapper."""
    sql = "SELECT * FROM orders LIMIT 2;"
    bounded = _apply_limit(sql, 201)
    # Trailing semicolon stripped, existing limit 2 preserved
    assert bounded.strip().endswith("LIMIT 2")
    df = sample_connection.execute(bounded).fetchdf()
    assert len(df) == 2


def test_strip_trailing_semicolon_preserves_literals():
    """Verify strip_trailing_semicolon does not alter internal semicolons inside quotes."""
    sql = "SELECT * FROM notes WHERE text = 'hello;world';;;  "
    clean = strip_trailing_semicolon(sql)
    assert clean == "SELECT * FROM notes WHERE text = 'hello;world'"


def test_quote_aware_split_statements():
    """Verify split_statements ignores semicolons inside single/double quotes."""
    sql = "SELECT 'item 1; item 2' AS items; SELECT 2"
    stmts = split_statements(sql)
    assert len(stmts) == 2
    assert stmts[0] == "SELECT 'item 1; item 2' AS items"
    assert stmts[1] == "SELECT 2"


# =========================================================================
# 2. Context Resolution & Follow-Up Distinction Tests
# =========================================================================

def test_context_resolution_test1_standalone_clears_stale_context():
    """TEST 1:
    Previous: 'Revenue from Hardware in last quarter' (category=Hardware, date=2026-04-01..2026-06-30)
    Current: 'Total revenue from South'
    Expected:
      region = South
      category = absent
      date filter = absent
    """
    prev_state = AnalyticalState(
        metric="revenue",
        filters={"category": "Hardware"},
        time_period="2026-04-01 to 2026-06-30",
        last_question="What was revenue from Hardware in last quarter?",
        last_sql=["SELECT SUM(line_total) FROM orders WHERE category = 'Hardware'"],
    )

    q2 = "Total revenue from South"
    assert not looks_like_follow_up(q2)

    # State update for standalone query with South filter
    new_state = merge_state(
        previous=prev_state,
        metric="revenue",
        filters={"region": "South"},
        grouping=None,
        time_period=None,
        tables=["orders", "customers"],
        sql=["SELECT SUM(o.line_total) AS revenue FROM orders o JOIN customers c ON o.customer_id = c.customer_id WHERE c.region = 'South'"],
        result_shape="scalar",
        columns=["revenue"],
        row_count=1,
        question=q2,
        is_follow_up=False,
    )

    assert new_state.filters == {"region": "South"}
    assert "category" not in new_state.filters
    assert new_state.time_period is None


def test_context_resolution_test2_follow_up_inherits_metric_and_adds_filter():
    """TEST 2:
    Previous: 'Total revenue'
    Current: 'What about South?'
    Expected:
      metric = revenue
      region = South
    """
    prev_state = AnalyticalState(
        metric="revenue",
        filters={},
        time_period=None,
        last_question="What is the total revenue?",
        last_sql=["SELECT SUM(line_total) FROM orders"],
    )

    q2 = "What about South?"
    assert looks_like_follow_up(q2)

    new_state = merge_state(
        previous=prev_state,
        metric=None,  # Not restated, inherited
        filters={"region": "South"},
        grouping=None,
        time_period=None,
        tables=["orders", "customers"],
        sql=["SELECT SUM(o.line_total) FROM orders o JOIN customers c ON o.customer_id = c.customer_id WHERE c.region = 'South'"],
        result_shape="scalar",
        columns=["revenue"],
        row_count=1,
        question=q2,
        is_follow_up=True,
    )

    assert new_state.metric == "revenue"
    assert new_state.filters == {"region": "South"}


def test_context_resolution_test3_follow_up_inherits_category_and_adds_region():
    """TEST 3:
    Previous: 'Revenue from Hardware'
    Current: 'What about South?'
    Expected:
      if interpreted as a follow-up:
      Hardware + South
    """
    prev_state = AnalyticalState(
        metric="revenue",
        filters={"category": "Hardware"},
        time_period=None,
        last_question="What is revenue from Hardware?",
        last_sql=["SELECT SUM(o.line_total) FROM orders o JOIN products p ON o.product_id = p.product_id WHERE p.category = 'Hardware'"],
    )

    q2 = "What about South?"
    assert looks_like_follow_up(q2)

    sql_with_both = (
        "SELECT SUM(o.line_total) FROM orders o "
        "JOIN customers c ON o.customer_id = c.customer_id "
        "JOIN products p ON o.product_id = p.product_id "
        "WHERE p.category = 'Hardware' AND c.region = 'South'"
    )

    new_state = merge_state(
        previous=prev_state,
        metric="revenue",
        filters={"region": "South"},
        grouping=None,
        time_period=None,
        tables=["orders", "customers", "products"],
        sql=[sql_with_both],
        result_shape="scalar",
        columns=["revenue"],
        row_count=1,
        question=q2,
        is_follow_up=True,
    )

    assert new_state.filters == {"category": "Hardware", "region": "South"}


def test_context_resolution_test4_standalone_trend_clears_stale_filters():
    """TEST 4:
    Previous: 'Revenue from Hardware in the last quarter'
    Current: 'Show monthly revenue'
    Expected:
      The system determines this is a new standalone trend request.
      It must not silently display filters that are not represented in SQL.
    """
    prev_state = AnalyticalState(
        metric="revenue",
        filters={"category": "Hardware"},
        time_period="2026-04-01 to 2026-06-30",
        last_question="Revenue from Hardware in the last quarter",
        last_sql=["SELECT SUM(line_total) FROM orders WHERE category = 'Hardware' AND order_date >= '2026-04-01'"],
    )

    q2 = "Show monthly revenue"
    assert not looks_like_follow_up(q2)

    sql_monthly = (
        "SELECT STRFTIME(CAST(order_date AS DATE), '%Y-%m') AS month, "
        "ROUND(SUM(line_total), 2) AS revenue "
        "FROM orders GROUP BY month ORDER BY month ASC"
    )

    new_state = merge_state(
        previous=prev_state,
        metric="revenue",
        filters={},
        grouping="month",
        time_period=None,
        tables=["orders"],
        sql=[sql_monthly],
        result_shape="time_series",
        columns=["month", "revenue"],
        row_count=21,
        question=q2,
        is_follow_up=False,
    )

    # Invariant: Hardware and last quarter are not in SQL, so they MUST NOT appear in filters
    assert new_state.filters == {}
    assert new_state.time_period is None
    assert new_state.grouping == "month"


def test_fidelity_invariant_test5_active_date_filter_must_appear_in_sql():
    """TEST 5: Any active date filter shown in the UI must appear in the executed SQL."""
    # SQL without date filter
    sql_no_date = "SELECT SUM(line_total) FROM orders WHERE region = 'South'"
    verified_filters, verified_time = reconcile_filters_with_sql(
        filters={"region": "South"},
        time_period="last quarter",
        sql=sql_no_date,
    )
    # Because SQL has no date predicate, time_period must be stripped
    assert verified_time is None
    assert verified_filters == {"region": "South"}

    # SQL with date filter
    sql_with_date = (
        "SELECT SUM(line_total) FROM orders "
        "WHERE region = 'South' AND order_date >= '2026-04-01' AND order_date <= '2026-06-30'"
    )
    verified_filters_2, verified_time_2 = reconcile_filters_with_sql(
        filters={"region": "South"},
        time_period="last quarter",
        sql=sql_with_date,
    )
    assert verified_time_2 == "last quarter"
    assert verified_filters_2 == {"region": "South"}


def test_fidelity_invariant_test6_active_category_filter_must_appear_in_sql():
    """TEST 6: Any active categorical filter shown in the UI must appear in the executed SQL."""
    # SQL only filters by region, NOT category
    sql_only_south = "SELECT SUM(o.line_total) FROM orders o JOIN customers c ON o.customer_id = c.customer_id WHERE c.region = 'South'"
    candidate_filters = {"category": "Hardware", "region": "South"}

    verified_filters, _ = reconcile_filters_with_sql(
        filters=candidate_filters,
        time_period=None,
        sql=sql_only_south,
    )
    # Hardware is not in SQL, so it MUST NOT be returned as an active filter
    assert "Hardware" not in verified_filters.values()
    assert "category" not in verified_filters
    assert verified_filters == {"region": "South"}


# =========================================================================
# 3. End-to-End Multi-Turn QA Integration Tests on Retail Data
# =========================================================================

def test_e2e_q1_hardware_last_quarter_then_q2_what_about_north():
    """End-to-end follow-up test:
    Q1: 'What is the total revenue from Hardware products in the last quarter?'
    Q2: 'What about North?'
    Verifies that Q2 retains Hardware and date bounds, executes valid bounded SQL,
    and returns deterministic DuckDB computed answer.
    """
    session = _load_retail_session()
    con = create_connection(session.datasets)

    # Q1 Plan
    plan_q1 = AnalysisPlan(
        intent="metric",
        required_tables=["orders", "products"],
        sql_requests=[
            SqlRequest(
                sql=(
                    "SELECT ROUND(SUM(o.line_total), 2) AS hardware_q2_revenue "
                    "FROM orders o JOIN products p ON o.product_id = p.product_id "
                    "WHERE p.category = 'Hardware' "
                    "  AND o.order_date >= '2026-04-01' AND o.order_date <= '2026-06-30'"
                ),
                purpose="Hardware revenue in Q2 2026",
            )
        ],
        expected_result_shape="scalar",
        visualization="none",
        explanation="Hardware revenue in Q2 2026.",
        metric="hardware_q2_revenue",
        filters={"category": "Hardware"},
        time_period="2026-04-01 to 2026-06-30",
    )

    planner_q1 = ScriptedPlanner([plan_q1])
    ans1 = run_analysis(
        "What is the total revenue from Hardware products in the last quarter?",
        session.profiles,
        session.relationships,
        session.state,
        con,
        planner=planner_q1,
    )

    assert ans1.status == "ok"
    assert ans1.filters == {"category": "Hardware"}
    assert ans1.time_period == "2026-04-01 to 2026-06-30"
    assert ans1.results[0].scalar_value == 68574.0

    # Q2: 'What about North?' (Follow-up)
    plan_q2 = AnalysisPlan(
        intent="follow_up",
        required_tables=["orders", "products", "customers"],
        sql_requests=[
            SqlRequest(
                sql=(
                    "SELECT ROUND(SUM(o.line_total), 2) AS north_hardware_revenue "
                    "FROM orders o "
                    "JOIN customers c ON o.customer_id = c.customer_id "
                    "JOIN products p ON o.product_id = p.product_id "
                    "WHERE c.region = 'North' "
                    "  AND p.category = 'Hardware' "
                    "  AND o.order_date >= '2026-04-01' AND o.order_date <= '2026-06-30'"
                ),
                purpose="North region Hardware revenue in Q2 2026",
            )
        ],
        expected_result_shape="scalar",
        visualization="none",
        explanation="North region Hardware revenue in Q2 2026.",
        metric="north_hardware_revenue",
        filters={"region": "North", "category": "Hardware"},
        time_period="2026-04-01 to 2026-06-30",
    )

    planner_q2 = ScriptedPlanner([plan_q2])
    ans2 = run_analysis(
        "What about North?",
        session.profiles,
        session.relationships,
        ans1.state,
        con,
        planner=planner_q2,
    )

    assert ans2.status == "ok"
    assert ans2.filters == {"region": "North", "category": "Hardware"}
    assert ans2.time_period == "2026-04-01 to 2026-06-30"
    # Final SQL executed must be bounded and preserved
    assert len(ans2.sql_used) == 1
    assert "North" in ans2.sql_used[0]
    assert "Hardware" in ans2.sql_used[0]
    assert ans2.results[0].scalar_value is not None


def test_e2e_q1_hardware_last_quarter_then_q2_total_revenue_from_south_clears_stale_filters():
    """End-to-end test of the exact user bug report:
    User asks Q1: 'What is the total revenue from Hardware products in the last quarter?'
    Then asks Q2: 'What is the total revenue from South?'
    Verifies that Q2:
      - Does NOT inherit Hardware or last-quarter filters
      - Displays ONLY region = South
      - Executed SQL has only South constraint
      - DuckDB computes full South revenue ($740,684.00)
    """
    session = _load_retail_session()
    con = create_connection(session.datasets)

    # Q1: Hardware in Q2 2026
    plan_q1 = AnalysisPlan(
        intent="metric",
        required_tables=["orders", "products"],
        sql_requests=[
            SqlRequest(
                sql=(
                    "SELECT ROUND(SUM(o.line_total), 2) AS hardware_q2_revenue "
                    "FROM orders o JOIN products p ON o.product_id = p.product_id "
                    "WHERE p.category = 'Hardware' "
                    "  AND o.order_date >= '2026-04-01' AND o.order_date <= '2026-06-30'"
                ),
                purpose="Hardware Q2 revenue",
            )
        ],
        expected_result_shape="scalar",
        visualization="none",
        explanation="Hardware revenue in Q2.",
        metric="hardware_q2_revenue",
        filters={"category": "Hardware"},
        time_period="2026-04-01 to 2026-06-30",
    )

    planner_q1 = ScriptedPlanner([plan_q1])
    ans1 = run_analysis(
        "What is the total revenue from Hardware products in the last quarter?",
        session.profiles,
        session.relationships,
        session.state,
        con,
        planner=planner_q1,
    )
    assert ans1.status == "ok"

    # Q2: Standalone question for South total revenue
    plan_q2 = AnalysisPlan(
        intent="metric",
        required_tables=["orders", "customers"],
        sql_requests=[
            SqlRequest(
                sql=(
                    "SELECT ROUND(SUM(o.line_total), 2) AS revenue "
                    "FROM orders o "
                    "JOIN customers c ON o.customer_id = c.customer_id "
                    "WHERE c.region = 'South'"
                ),
                purpose="Total revenue from South region",
            )
        ],
        expected_result_shape="scalar",
        visualization="none",
        explanation="Total revenue from the South region.",
        metric="revenue",
        filters={"region": "South"},
        time_period=None,
    )

    planner_q2 = ScriptedPlanner([plan_q2])
    ans2 = run_analysis(
        "What is the total revenue from South?",
        session.profiles,
        session.relationships,
        ans1.state,
        con,
        planner=planner_q2,
    )

    assert ans2.status == "ok"
    # CRITICAL CHECK: Stale category and date filters are ABSENT
    assert "category" not in ans2.filters
    assert ans2.time_period is None
    assert ans2.filters == {"region": "South"}

    # SQL check
    assert len(ans2.sql_used) == 1
    assert "Hardware" not in ans2.sql_used[0]
    assert "2026-04-01" not in ans2.sql_used[0]

    # DuckDB computation check: South total revenue matches Ground Truth ($740,684.00)
    assert ans2.results[0].scalar_value == 740684.0
