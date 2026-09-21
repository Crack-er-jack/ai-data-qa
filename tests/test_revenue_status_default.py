"""Tests for deterministic order status defaulting on revenue/sales queries.

Verifies:
1. When user asks for total revenue/sales/line_total and an order status column
   exists with 'completed', the system defaults to status = 'completed' without clarification.
2. When the user explicitly mentions another status (e.g. refunded), that status is used.
3. When the question is ambiguous or unrelated to revenue status, clarification is preserved.
"""

from __future__ import annotations

import duckdb
import pytest

from src.agent import run_analysis
from src.context.builder import resolve_revenue_status_default
from src.context.state import AnalyticalState
from src.llm.schemas import AnalysisPlan, SqlRequest
from src.profiling.schema import ColumnProfile, TableProfile


def _create_mock_profiles_with_status() -> list[TableProfile]:
    """Create mock table profiles simulating orders with a status column."""
    orders = TableProfile(
        table_name="orders",
        original_filename="orders.csv",
        row_count=438,
        column_count=4,
        columns=[
            ColumnProfile(
                name="order_id",
                original_name="order_id",
                data_type="string",
                pandas_dtype="object",
                null_percentage=0.0,
                cardinality=438,
                sample_values=["O0001", "O0002"],
            ),
            ColumnProfile(
                name="line_total",
                original_name="line_total",
                data_type="float",
                pandas_dtype="float64",
                null_percentage=0.0,
                cardinality=300,
                sample_values=["296.65", "799.00"],
            ),
            ColumnProfile(
                name="status",
                original_name="status",
                data_type="string",
                pandas_dtype="object",
                null_percentage=0.0,
                cardinality=2,
                sample_values=["completed", "refunded"],
            ),
        ],
    )
    return [orders]


class TestRevenueStatusDefault:
    """Test suite for revenue order status defaulting logic."""

    def test_resolve_revenue_status_default_triggers_on_total_revenue(self):
        """Verify resolve_revenue_status_default identifies orders.status = completed."""
        profiles = _create_mock_profiles_with_status()
        res = resolve_revenue_status_default("What is the total revenue?", profiles)
        assert res == ("orders", "status", "completed")

    def test_resolve_revenue_status_default_triggers_on_sales_and_line_total(self):
        """Verify detection works for sales and line_total queries."""
        profiles = _create_mock_profiles_with_status()
        assert resolve_revenue_status_default("Show total sales", profiles) == ("orders", "status", "completed")
        assert resolve_revenue_status_default("What is the line_total?", profiles) == ("orders", "status", "completed")

    def test_resolve_revenue_status_default_ignores_when_other_status_specified(self):
        """Verify explicit user requests for refunded or pending orders bypass defaulting."""
        profiles = _create_mock_profiles_with_status()
        assert resolve_revenue_status_default("What is the total revenue of refunded orders?", profiles) is None
        assert resolve_revenue_status_default("Total sales for cancelled items", profiles) is None

    def test_revenue_query_overrides_aggressive_clarification(self):
        """Verify that if LLM asks clarification about completed orders, it defaults and executes directly."""
        profiles = _create_mock_profiles_with_status()
        state = AnalyticalState()

        # Mock duckdb connection with orders table
        conn = duckdb.connect(":memory:")
        conn.execute(
            """
            CREATE TABLE orders (
                order_id VARCHAR,
                line_total DOUBLE,
                status VARCHAR
            );
            INSERT INTO orders VALUES
                ('O1', 100.0, 'completed'),
                ('O2', 50.0, 'refunded'),
                ('O3', 200.0, 'completed');
            """
        )

        class OverlyAggressivePlanner:
            """Simulates an LLM asking clarification on completed orders."""

            def plan(self, context: str, question: str, repair: str | None = None) -> AnalysisPlan:
                if repair and "status = 'completed'" in repair:
                    return AnalysisPlan(
                        intent="metric",
                        metric="revenue",
                        filters={"status": "completed"},
                        required_tables=["orders"],
                        sql_requests=[
                            SqlRequest(
                                sql="SELECT SUM(line_total) AS total_revenue FROM orders WHERE status = 'completed'",
                                description="Total revenue for completed orders",
                            )
                        ],
                        explanation="Total revenue from completed orders.",
                    )
                return AnalysisPlan(
                    intent="clarification",
                    clarification_needed=True,
                    clarification_question="Do you want to include only completed orders in the total revenue calculation?",
                    explanation="Clarification needed on order status.",
                )

        answer = run_analysis(
            "What is the total revenue?",
            profiles,
            [],
            state,
            conn,
            planner=OverlyAggressivePlanner(),
        )

        # Must execute directly without asking clarification
        assert answer.status == "ok"
        assert answer.clarification is None
        assert "WHERE status = 'completed'" in answer.sql_used[0]
        assert answer.filters.get("status") == "completed"

    def test_ambiguous_non_revenue_query_still_asks_clarification(self):
        """Verify clarification behavior is strictly preserved for genuinely ambiguous non-revenue queries."""
        profiles = _create_mock_profiles_with_status()
        state = AnalyticalState()
        conn = duckdb.connect(":memory:")

        class AmbiguousPlanner:
            def plan(self, context: str, question: str, repair: str | None = None) -> AnalysisPlan:
                return AnalysisPlan(
                    intent="clarification",
                    clarification_needed=True,
                    clarification_question="Which region or product category would you like to view?",
                    explanation="Question is ambiguous.",
                )

        answer = run_analysis(
            "Compare them",
            profiles,
            [],
            state,
            conn,
            planner=AmbiguousPlanner(),
        )

        assert answer.status == "clarification"
        assert answer.message == "Which region or product category would you like to view?"

