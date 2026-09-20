import pandas as pd

from src.results import classify_result
from src.visualization import choose_visualization


def test_scalar_uses_kpi():
    frame = pd.DataFrame({"total_revenue": [1234.5]})
    assert classify_result(frame) == "scalar"
    assert choose_visualization(frame, suggestion="bar") == "kpi"


def test_category_comparison_uses_bar():
    frame = pd.DataFrame({"region": ["South", "North"], "revenue": [10, 20]})
    assert classify_result(frame) == "grouped"
    assert choose_visualization(frame, suggestion="bar") == "bar"
    assert choose_visualization(frame, suggestion="histogram") == "bar"


def test_time_series_uses_line():
    frame = pd.DataFrame(
        {"month": pd.to_datetime(["2026-01-01", "2026-02-01"]), "revenue": [10, 12]}
    )
    assert classify_result(frame) == "time_series"
    assert choose_visualization(frame, suggestion="line") == "line"


def test_single_numeric_column_histogram():
    frame = pd.DataFrame({"amount": [1, 2, 3, 4, 5, 6]})
    assert choose_visualization(frame) in {"histogram", "table"}


def test_wide_table_stays_table():
    frame = pd.DataFrame(
        {
            "order_id": ["O1", "O2"],
            "customer_id": ["C1", "C2"],
            "product_id": ["P1", "P2"],
            "notes": ["a", "b"],
        }
    )
    assert choose_visualization(frame, suggestion="bar") == "table"


def test_build_figure_creates_valid_plotly_figures():
    """Verify build_figure creates valid Plotly figures for bar, line, and histogram."""
    import plotly.graph_objects as go
    from src.visualization import build_figure

    # Bar chart
    bar_df = pd.DataFrame({"region": ["South", "North"], "revenue": [100.0, 200.0]})
    fig_bar = build_figure(bar_df, "bar", title="Revenue by Region")
    assert isinstance(fig_bar, go.Figure)
    assert fig_bar.layout.title.text == "Revenue by Region"

    # Line chart
    line_df = pd.DataFrame(
        {"date": pd.to_datetime(["2025-01-01", "2025-02-01"]), "revenue": [50.0, 80.0]}
    )
    fig_line = build_figure(line_df, "line", title="Revenue Trend")
    assert isinstance(fig_line, go.Figure)

    # Histogram
    hist_df = pd.DataFrame({"order_value": [10.0, 20.0, 25.0, 30.0, 50.0]})
    fig_hist = build_figure(hist_df, "histogram", title="Order Value Distribution")
    assert isinstance(fig_hist, go.Figure)


def test_build_figure_returns_none_for_kpi_table_empty():
    """Verify build_figure returns None for formats rendered by Streamlit widgets."""
    from src.visualization import build_figure

    df = pd.DataFrame({"metric": [42]})
    # KPI and table visualizations do not use Plotly graphs
    assert build_figure(df, "kpi") is None
    assert build_figure(df, "table") is None
    assert build_figure(df, "none") is None
    assert build_figure(pd.DataFrame(), "bar") is None

