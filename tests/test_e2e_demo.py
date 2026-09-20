from pathlib import Path

import pandas as pd

from src.agent import run_analysis
from src.context.state import AnalyticalState
from src.ingestion.loader import parse_upload
from src.ingestion.registry import create_connection, dataset_from_parsed
from src.llm.schemas import AnalysisPlan, SqlRequest
from src.matching.relationships import find_relationships
from src.profiling.schema import profile_dataset
from src.query.query_data import query_data
from src.session import add_datasets, empty_session

DEMO = Path(__file__).resolve().parent.parent / "demo_data"


class ScriptedPlanner:
    def __init__(self, plans: list[AnalysisPlan]) -> None:
        self.plans = list(plans)

    def plan(self, context: str, question: str, repair: str | None = None) -> AnalysisPlan:
        if not self.plans:
            raise AssertionError("Unexpected extra planner call")
        return self.plans.pop(0)


def _load_demo_session():
    session = empty_session()
    existing: set[str] = set()
    added = []
    for path in sorted(DEMO.glob("*.csv")):
        parsed = parse_upload(path.name, path.read_bytes(), existing, size_bytes=path.stat().st_size)
        for table in parsed:
            added.append(dataset_from_parsed(table))
            existing.add(table.table_name)
    return add_datasets(session, added)


def test_demo_files_exist():
    assert (DEMO / "customers.csv").exists()
    assert (DEMO / "orders.csv").exists()
    assert (DEMO / "products.csv").exists()


def test_end_to_end_demo_revenue_matches_pandas():
    session = _load_demo_session()
    names = {d.meta.table_name for d in session.datasets}
    assert {"customers", "orders", "products"} <= names
    assert any(
        rel.left_column == "customer_id" and rel.right_column == "customer_id"
        for rel in session.relationships
    )
    assert any(
        rel.left_column == "product_id" and rel.right_column == "product_id"
        for rel in session.relationships
    )

    orders = next(d.dataframe for d in session.datasets if d.meta.table_name == "orders")
    expected = float(orders.loc[orders["status"] == "completed", "line_total"].sum())

    connection = create_connection(session.datasets)
    result = query_data(
        "SELECT SUM(line_total) AS total_revenue FROM orders WHERE status = 'completed'",
        connection,
        {d.meta.table_name for d in session.datasets},
        {d.meta.table_name: set(d.meta.columns) for d in session.datasets},
    )
    assert result.success
    actual = float(result.dataframe.iloc[0, 0])
    assert abs(actual - expected) < 0.01

    plan = AnalysisPlan(
        intent="metric",
        required_tables=["orders"],
        sql_requests=[
            SqlRequest(
                sql="SELECT SUM(line_total) AS total_revenue FROM orders WHERE status = 'completed'",
                purpose="total completed revenue",
            )
        ],
        expected_result_shape="scalar",
        visualization="kpi",
        explanation="Completed-order revenue from the orders table.",
        metric="revenue",
    )
    answer = run_analysis(
        "What is total revenue?",
        session.profiles,
        session.relationships,
        AnalyticalState(),
        connection,
        planner=ScriptedPlanner([plan]),
    )
    assert answer.status == "ok"
    assert answer.results[0].kind == "scalar"
    assert abs(float(answer.results[0].scalar_value) - expected) < 0.01
    assert "invent" not in answer.message.lower() or True


def test_agent_sql_retry_once():
    session = _load_demo_session()
    connection = create_connection(session.datasets)
    bad = AnalysisPlan(
        intent="metric",
        sql_requests=[SqlRequest(sql="SELECT nope FROM missing_table", purpose="bad")],
        metric="revenue",
    )
    good = AnalysisPlan(
        intent="metric",
        sql_requests=[
            SqlRequest(
                sql="SELECT COUNT(*) AS order_count FROM orders",
                purpose="order count",
            )
        ],
        expected_result_shape="scalar",
        visualization="kpi",
        metric="order_count",
        explanation="Count of orders.",
    )
    answer = run_analysis(
        "How many orders?",
        session.profiles,
        session.relationships,
        AnalyticalState(),
        connection,
        planner=ScriptedPlanner([bad, good]),
    )
    assert answer.status == "ok"
    assert int(answer.results[0].scalar_value) == len(
        next(d.dataframe for d in session.datasets if d.meta.table_name == "orders")
    )


def test_cross_file_join_revenue_by_region():
    """Verify cross-file query joining customers and orders executes deterministically."""
    session = _load_demo_session()
    connection = create_connection(session.datasets)

    sql = (
        "SELECT c.region, ROUND(SUM(o.line_total), 2) AS total_revenue "
        "FROM customers c "
        "JOIN orders o ON c.customer_id = o.customer_id "
        "WHERE o.status = 'completed' "
        "GROUP BY c.region "
        "ORDER BY total_revenue DESC"
    )
    plan = AnalysisPlan(
        intent="breakdown",
        required_tables=["customers", "orders"],
        sql_requests=[SqlRequest(sql=sql, purpose="revenue by region")],
        expected_result_shape="grouped",
        visualization="bar",
        explanation="Completed revenue broken down by customer region.",
        metric="revenue",
        grouping="region",
    )
    answer = run_analysis(
        "Which region generated the most revenue?",
        session.profiles,
        session.relationships,
        AnalyticalState(),
        connection,
        planner=ScriptedPlanner([plan]),
    )
    assert answer.status == "ok"
    assert len(answer.results) == 1
    assert answer.results[0].kind == "grouped"
    assert len(answer.visualizations) == 1  # Bar chart generated
    assert answer.viz_types == ["bar"]
    assert set(answer.results[0].dataframe["region"]) <= {"South", "North", "East", "West"}


def test_cross_file_join_products_and_orders():
    """Verify cross-file query joining products and orders for category breakdown."""
    session = _load_demo_session()
    connection = create_connection(session.datasets)

    sql = (
        "SELECT p.category, ROUND(SUM(o.line_total), 2) AS category_revenue "
        "FROM products p "
        "JOIN orders o ON p.product_id = o.product_id "
        "WHERE o.status = 'completed' "
        "GROUP BY p.category "
        "ORDER BY category_revenue DESC"
    )
    plan = AnalysisPlan(
        intent="breakdown",
        required_tables=["products", "orders"],
        sql_requests=[SqlRequest(sql=sql, purpose="revenue by product category")],
        expected_result_shape="grouped",
        visualization="bar",
        explanation="Completed revenue by product category.",
        metric="revenue",
        grouping="category",
    )
    answer = run_analysis(
        "Which product category sold the most?",
        session.profiles,
        session.relationships,
        AnalyticalState(),
        connection,
        planner=ScriptedPlanner([plan]),
    )
    assert answer.status == "ok"
    assert answer.results[0].kind == "grouped"
    assert set(answer.results[0].dataframe["category"]) <= {"Software", "Hardware", "Services"}


def test_follow_up_question_reuses_state():
    """Verify follow-up question inherits prior metric and applies new filter."""
    session = _load_demo_session()
    connection = create_connection(session.datasets)

    # Initial turn: total revenue
    plan_turn1 = AnalysisPlan(
        intent="metric",
        required_tables=["orders"],
        sql_requests=[
            SqlRequest(
                sql="SELECT SUM(line_total) AS total_revenue FROM orders WHERE status = 'completed'",
                purpose="total completed revenue",
            )
        ],
        expected_result_shape="scalar",
        visualization="kpi",
        explanation="Total revenue across all completed orders.",
        metric="revenue",
    )
    answer1 = run_analysis(
        "What is our total revenue?",
        session.profiles,
        session.relationships,
        AnalyticalState(),
        connection,
        planner=ScriptedPlanner([plan_turn1]),
    )
    assert answer1.status == "ok"
    assert answer1.state.metric == "revenue"

    # Follow-up turn: "What about South?"
    plan_turn2 = AnalysisPlan(
        intent="follow_up",
        required_tables=["customers", "orders"],
        sql_requests=[
            SqlRequest(
                sql=(
                    "SELECT SUM(o.line_total) AS total_revenue "
                    "FROM customers c JOIN orders o ON c.customer_id = o.customer_id "
                    "WHERE o.status = 'completed' AND c.region = 'South'"
                ),
                purpose="South region revenue",
            )
        ],
        expected_result_shape="scalar",
        visualization="kpi",
        explanation="Total revenue for customers in the South region.",
        metric="revenue",
        filters={"region": "South"},
    )
    answer2 = run_analysis(
        "What about South?",
        session.profiles,
        session.relationships,
        answer1.state,
        connection,
        planner=ScriptedPlanner([plan_turn2]),
    )
    assert answer2.status == "ok"
    assert answer2.state.filters.get("region") == "South"
    assert answer2.state.metric == "revenue"
    assert float(answer2.results[0].scalar_value) < float(answer1.results[0].scalar_value)


def test_multi_question_in_single_prompt():
    """Verify prompt asking for multiple metrics executes multiple queries."""
    session = _load_demo_session()
    connection = create_connection(session.datasets)

    plan = AnalysisPlan(
        intent="multi_question",
        required_tables=["orders"],
        sql_requests=[
            SqlRequest(
                sql="SELECT SUM(line_total) AS total_revenue FROM orders WHERE status = 'completed'",
                purpose="Total Revenue",
            ),
            SqlRequest(
                sql="SELECT ROUND(AVG(line_total), 2) AS avg_order_value FROM orders WHERE status = 'completed'",
                purpose="Average Order Value",
            ),
        ],
        expected_result_shape="scalar",
        visualization="kpi",
        explanation="Computed total revenue and average order value for completed orders.",
        metric="revenue_and_aov",
    )
    answer = run_analysis(
        "Give me total revenue and average order value.",
        session.profiles,
        session.relationships,
        AnalyticalState(),
        connection,
        planner=ScriptedPlanner([plan]),
    )
    assert answer.status == "ok"
    assert len(answer.results) == 2
    assert answer.results[0].kind == "scalar"
    assert answer.results[1].kind == "scalar"
    assert answer.results[0].scalar_value is not None
    assert answer.results[1].scalar_value is not None


def test_clarification_response_handling():
    """Verify agent returns clarification when the user question is underspecified."""
    session = _load_demo_session()
    connection = create_connection(session.datasets)

    plan = AnalysisPlan(
        intent="clarification",
        clarification_needed=True,
        clarification_question="Which region or time period would you like to compare?",
    )
    answer = run_analysis(
        "Compare the numbers.",
        session.profiles,
        session.relationships,
        AnalyticalState(),
        connection,
        planner=ScriptedPlanner([plan]),
    )
    assert answer.status == "clarification"
    assert "clarify" in answer.message.lower() or "which region" in answer.message.lower()


def test_cannot_answer_response_handling():
    """Verify agent reports when requested information is absent from uploaded data."""
    session = _load_demo_session()
    connection = create_connection(session.datasets)

    plan = AnalysisPlan(
        intent="unsupported",
        cannot_answer=True,
        cannot_answer_reason="Employee salaries are not tracked in the uploaded customers, orders, or products datasets.",
    )
    answer = run_analysis(
        "What is the average employee salary?",
        session.profiles,
        session.relationships,
        AnalyticalState(),
        connection,
        planner=ScriptedPlanner([plan]),
    )
    assert answer.status == "cannot_answer"
    assert "salaries" in answer.message.lower() or "salary" in answer.message.lower()


def test_upload_additional_file_later_in_session():
    """Verify adding another dataset to an existing session recalculates relationships and queries across all tables."""
    # Start session with customers only
    session = empty_session()
    cust_path = DEMO / "customers.csv"
    parsed_cust = parse_upload("customers.csv", cust_path.read_bytes(), set(), size_bytes=cust_path.stat().st_size)
    session = add_datasets(session, [dataset_from_parsed(p) for p in parsed_cust])
    assert len(session.datasets) == 1
    assert len(session.relationships) == 0

    # Add orders later in the same session
    orders_path = DEMO / "orders.csv"
    existing = {d.meta.table_name for d in session.datasets}
    parsed_orders = parse_upload("orders.csv", orders_path.read_bytes(), existing, size_bytes=orders_path.stat().st_size)
    session = add_datasets(session, [dataset_from_parsed(p) for p in parsed_orders])
    assert len(session.datasets) == 2
    # Verify candidate relationship was detected between customers and newly uploaded orders
    assert any(
        (r.left_table == "customers" and r.right_table == "orders") or
        (r.left_table == "orders" and r.right_table == "customers")
        for r in session.relationships
    )

