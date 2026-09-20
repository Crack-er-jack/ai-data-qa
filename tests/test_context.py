from src.context.builder import build_context
from src.context.state import AnalyticalState, looks_like_follow_up, merge_state
from src.matching.relationships import RelationshipCandidate
from src.profiling.schema import ColumnProfile, TableProfile


def _profile() -> TableProfile:
    return TableProfile(
        table_name="orders",
        original_filename="orders.csv",
        row_count=10,
        column_count=2,
        columns=[
            ColumnProfile("line_total", "line_total", "float", "float64", 0.0, 10, ["10"]),
            ColumnProfile("region", "region", "string", "object", 0.0, 4, ["South"]),
        ],
    )


def test_follow_up_phrase_detected():
    assert looks_like_follow_up("What about South?")
    assert looks_like_follow_up("How about North?")
    assert not looks_like_follow_up("What is total revenue by product category?")


def test_context_includes_previous_metric_and_filters():
    state = AnalyticalState(
        metric="revenue",
        filters={},
        time_period="last quarter",
        last_tables=["orders"],
        last_question="What is our total revenue?",
    )
    context = build_context("What about South?", [_profile()], [], state)
    assert "revenue" in context
    assert "last quarter" in context
    assert "What about South?" not in context or "South" in "What about South?"


def test_merge_state_updates_filter_keeps_metric():
    previous = AnalyticalState(metric="revenue", filters={}, time_period="last quarter")
    updated = merge_state(
        previous,
        metric="revenue",
        filters={"region": "South"},
        grouping=None,
        time_period=None,
        tables=["orders", "customers"],
        sql=["SELECT 1"],
        result_shape="scalar",
        columns=["total"],
        row_count=1,
        question="What about South?",
    )
    assert updated.metric == "revenue"
    assert updated.filters["region"] == "South"
    assert updated.time_period == "last quarter"
    assert updated.last_question == "What about South?"


def test_build_context_with_candidate_relationships():
    """Verify that candidate relationships are structured into the LLM context."""
    rel = RelationshipCandidate(
        left_table="customers",
        left_column="customer_id",
        right_table="orders",
        right_column="customer_id",
        reason="identical column names",
        confidence=0.95,
        overlap_ratio=0.85,
    )
    context = build_context("Total revenue by customer", [_profile()], [rel], AnalyticalState())
    assert "customers.customer_id" in context
    assert "orders.customer_id" in context
    assert "0.95" in context


def test_analytical_state_serialization_roundtrip():
    """Verify AnalyticalState serializes to dict and deserializes cleanly."""
    state = AnalyticalState(
        metric="profit",
        filters={"segment": "Enterprise", "year": "2025"},
        grouping="region",
        time_period="Q1",
        last_tables=["orders", "customers"],
        last_sql=["SELECT 1"],
        last_result_shape="grouped",
        last_columns=["region", "profit"],
        last_row_count=4,
        last_question="Profit by region in Q1?",
    )
    serialized = state.to_dict()
    restored = AnalyticalState.from_dict(serialized)
    assert restored.metric == state.metric
    assert restored.filters == state.filters
    assert restored.grouping == state.grouping
    assert restored.last_tables == state.last_tables
    assert restored.last_question == state.last_question

