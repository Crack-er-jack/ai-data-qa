"""Tests for dataset discoverability, dynamic suggestions, metadata questions, and session uploads."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from src.agent import run_analysis
from src.context.state import AnalyticalState
from src.ingestion.loader import parse_upload
from src.ingestion.registry import Dataset, create_connection, dataset_from_parsed
from src.matching.relationships import find_relationships
from src.profiling.schema import profile_dataset
from src.profiling.suggestions import (
    build_metadata_response,
    generate_schema_suggestions,
    is_metadata_question,
)
from src.session import SessionData, add_datasets

DEMO_DIR = Path(__file__).parent.parent / "demo_data"
TEST_DATA_DIR = Path(__file__).parent.parent / "test_data"


def _create_synthetic_dataset(
    filename: str,
    df: pd.DataFrame,
    existing: set[str] | None = None,
) -> Dataset:
    """Helper to convert a pandas DataFrame into a profiled Dataset via parse_upload."""
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    existing_tables = existing or set()
    parsed = parse_upload(filename, csv_bytes, existing_tables, size_bytes=len(csv_bytes), session_bytes=0)
    return dataset_from_parsed(parsed[0])


class TestSchemaSuggestions:
    """Tests for deterministic schema-based suggestion generation."""

    def test_suggestions_generated_from_retail_demo_data(self):
        """Verify dynamic suggestions generated from demo retail tables."""
        datasets = []
        for name in ("customers.csv", "orders.csv", "products.csv"):
            path = DEMO_DIR / name
            data = path.read_bytes()
            parsed = parse_upload(name, data, {d.meta.table_name for d in datasets}, len(data), 0)
            datasets.append(dataset_from_parsed(parsed[0]))

        profiles = [profile_dataset(d) for d in datasets]
        relationships = find_relationships(datasets, profiles)

        suggestions = generate_schema_suggestions(profiles, relationships)

        # Must generate 4 to 6 suggestions
        assert 4 <= len(suggestions) <= 6
        # Must detect metric line_total
        assert any("line_total" in s for s in suggestions)
        # Must generate total, average/grouping, and temporal suggestions
        assert any("total line_total" in s for s in suggestions)
        assert any("by " in s for s in suggestions)
        assert any("over time" in s for s in suggestions)

    def test_suggestions_generated_from_hr_test_data(self):
        """Verify dynamic suggestions generated from HR test data pack."""
        salaries_path = TEST_DATA_DIR / "hr" / "salaries.xlsx"
        sal_data = salaries_path.read_bytes()
        parsed_sal = parse_upload("salaries.xlsx", sal_data, set(), len(sal_data), 0)
        sal_dataset = dataset_from_parsed(parsed_sal[0])

        dept_path = TEST_DATA_DIR / "hr" / "departments.csv"
        dept_data = dept_path.read_bytes()
        parsed_dept = parse_upload("departments.csv", dept_data, {"salaries"}, len(dept_data), 0)
        dept_dataset = dataset_from_parsed(parsed_dept[0])

        datasets = [sal_dataset, dept_dataset]
        profiles = [profile_dataset(d) for d in datasets]
        relationships = find_relationships(datasets, profiles)

        suggestions = generate_schema_suggestions(profiles, relationships)

        assert 4 <= len(suggestions) <= 6
        # Must detect salary metric
        assert any("base_salary" in s for s in suggestions)
        assert any("over time" in s for s in suggestions)

    def test_suggestions_on_arbitrary_custom_dataset(self):
        """Verify suggestions work dynamically on an arbitrary single CSV dataset."""
        df = pd.DataFrame(
            {
                "equipment_id": ["E101", "E102", "E103", "E104"],
                "facility_location": ["Plant Alpha", "Plant Alpha", "Warehouse Beta", "Plant Alpha"],
                "runtime_hours": [1240.5, 830.0, 450.2, 1980.0],
                "maintenance_cost": [450.0, 120.0, 0.0, 890.0],
                "inspection_date": ["2026-01-10", "2026-02-15", "2026-03-01", "2026-04-12"],
            }
        )
        dataset = _create_synthetic_dataset("machinery_fleet.csv", df)
        profiles = [profile_dataset(dataset)]

        suggestions = generate_schema_suggestions(profiles)

        assert len(suggestions) >= 4
        # Suggests total runtime_hours or maintenance_cost
        assert any("total runtime_hours" in s or "total maintenance_cost" in s for s in suggestions)
        # Suggests breakdown by facility_location
        assert any("by facility_location" in s for s in suggestions)
        # Suggests trend over time
        assert any("over time" in s for s in suggestions)


class TestMetadataQuestionDetection:
    """Tests for detecting metadata/schema questions vs analytical questions."""

    @pytest.mark.parametrize(
        "query",
        [
            "What datasets are currently loaded?",
            "What datasets are loaded?",
            "what datasets do i have",
            "What datasets are available?",
            "Describe the datasets.",
            "describe datasets",
            "What columns are available?",
            "what columns do i have",
            "What data do I have?",
            "what data is available",
            "What files are uploaded?",
            "Show available tables",
            "show tables",
            "Show columns",
            "show schema",
            "Describe schema",
            "List datasets",
            "list tables",
            "what can i ask",
        ],
    )
    def test_metadata_questions_detected(self, query: str):
        """All variations of metadata questions must evaluate to True."""
        assert is_metadata_question(query) is True

    @pytest.mark.parametrize(
        "query",
        [
            "What was our total revenue last quarter?",
            "What is total revenue by product category?",
            "Which region generated the most revenue?",
            "What about South?",
            "Compare revenue across regions.",
            "Show me the monthly revenue trend.",
            "What is the average salary by department?",
            "Show total sales over time",
            "How many orders were placed yesterday?",
            "What is the highest unit price?",
        ],
    )
    def test_analytical_questions_not_flagged_as_metadata(self, query: str):
        """Analytical computational queries must evaluate to False."""
        assert is_metadata_question(query) is False


class TestMetadataResponseAndExecution:
    """Tests for build_metadata_response and run_analysis metadata routing."""

    def test_build_metadata_response_contains_all_dataset_info(self):
        """Verify formatted response includes filenames, row counts, columns, types, and suggestions."""
        df_cust = pd.DataFrame(
            {
                "customer_id": ["C1", "C2"],
                "region": ["North", "South"],
                "joined_date": ["2026-01-01", "2026-02-01"],
            }
        )
        df_ord = pd.DataFrame(
            {
                "order_id": [1, 2],
                "customer_id": ["C1", "C2"],
                "total_amount": [150.0, 300.0],
            }
        )
        ds1 = _create_synthetic_dataset("customers.csv", df_cust)
        ds2 = _create_synthetic_dataset("orders.csv", df_ord, existing={"customers"})

        datasets = [ds1, ds2]
        profiles = [profile_dataset(d) for d in datasets]
        relationships = find_relationships(datasets, profiles)

        response = build_metadata_response(profiles, relationships)

        # Datasets count and filenames
        assert "2 datasets loaded" in response
        assert "customers.csv" in response
        assert "orders.csv" in response

        # Row counts and columns
        assert "2 rows · 3 columns" in response
        assert "customer_id" in response
        assert "total_amount" in response

        # Relationships
        assert "customers.customer_id" in response
        assert "orders.customer_id" in response

        # Analytical question suggestions
        assert "You can ask analytical questions such as:" in response
        assert any(term in response for term in ("total_amount", "region"))

    def test_run_analysis_handles_metadata_question_without_llm(self):
        """run_analysis for 'What datasets are currently loaded?' returns status='ok' without calling LLM."""
        df = pd.DataFrame(
            {
                "patient_id": [101, 102, 103],
                "treatment_cost": [1200.0, 850.0, 2400.0],
                "department": ["Cardiology", "Neurology", "Cardiology"],
            }
        )
        dataset = _create_synthetic_dataset("hospital_admissions.csv", df)
        profiles = [profile_dataset(dataset)]
        con = create_connection([dataset])

        # Execute run_analysis with NO LLM planner provided (defaults to None / GroqProvider)
        # Because it is a metadata question, it must NOT fail or invoke the LLM
        ans = run_analysis(
            "What datasets are currently loaded?",
            profiles,
            relationships=[],
            state=AnalyticalState(),
            connection=con,
            planner=None,
        )

        assert ans.status == "ok"
        assert ans.sql_used == []
        assert ans.results == []
        assert "hospital_admissions.csv" in ans.message
        assert "3 rows · 3 columns" in ans.message
        assert "treatment_cost" in ans.message
        # Invariant: does not produce the failed analytical query message
        assert "I could not produce a valid analytical query" not in ans.message


class TestSessionUploadLifecycle:
    """Tests that uploading additional files updates the session state dynamically."""

    def test_upload_additional_file_updates_session_overview(self):
        """Simulate uploading file 1 and file 2, then adding file 3 later in the session."""
        session = SessionData()

        # Step 1: Initial upload: customers and orders
        ds_cust = _create_synthetic_dataset(
            "customers.csv",
            pd.DataFrame({"customer_id": ["C1"], "name": ["Alice"]}),
        )
        ds_ord = _create_synthetic_dataset(
            "orders.csv",
            pd.DataFrame({"order_id": [1], "customer_id": ["C1"], "amount": [100.0]}),
            existing={"customers"},
        )
        session = add_datasets(session, [ds_cust, ds_ord])

        assert len(session.datasets) == 2
        assert len(session.profiles) == 2
        assert {d.meta.table_name for d in session.datasets} == {"customers", "orders"}

        # Step 2: Upload another file: marketing_spend.csv
        ds_mkt = _create_synthetic_dataset(
            "marketing_spend.csv",
            pd.DataFrame({"channel": ["Search"], "spend": [500.0]}),
            existing={"customers", "orders"},
        )
        session = add_datasets(session, [ds_mkt])

        # Step 3: Verify all 3 datasets are present and profiled
        assert len(session.datasets) == 3
        assert len(session.profiles) == 3
        table_names = {d.meta.table_name for d in session.datasets}
        assert table_names == {"customers", "orders", "marketing_spend"}

        # Metadata response reflects all 3 datasets
        overview = build_metadata_response(session.profiles, session.relationships)
        assert "3 datasets loaded" in overview
        assert "customers.csv" in overview
        assert "orders.csv" in overview
        assert "marketing_spend.csv" in overview

        # Preview works on all 3 datasets (first 5 rows)
        for ds in session.datasets:
            preview_df = ds.dataframe.head(5)
            assert len(preview_df) == 1
            assert not preview_df.empty
