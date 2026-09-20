import pandas as pd

from src.ingestion.registry import Dataset, DatasetMeta, dataset_from_parsed
from src.ingestion.loader import ParsedTable
from src.matching.relationships import find_relationships
from src.profiling.schema import profile_dataset


def _dataset(name: str, frame: pd.DataFrame) -> Dataset:
    parsed = ParsedTable(
        original_filename=f"{name}.csv",
        table_name=name,
        dataframe=frame,
        size_bytes=100,
        original_columns={c: c for c in frame.columns},
    )
    return dataset_from_parsed(parsed)


def test_schema_profile_contains_nulls_and_samples():
    frame = pd.DataFrame(
        {
            "customer_id": ["C001", "C002", "C003"],
            "region": ["South", "North", None],
            "score": [1, 2, 3],
        }
    )
    profile = profile_dataset(_dataset("customers", frame))
    assert profile.table_name == "customers"
    region = next(col for col in profile.columns if col.name == "region")
    assert region.null_percentage > 0
    assert region.sample_values
    score = next(col for col in profile.columns if col.name == "score")
    assert score.data_type in {"integer", "numeric"}


def test_relationship_detection_on_shared_ids():
    customers = _dataset(
        "customers",
        pd.DataFrame({"customer_id": ["C001", "C002"], "region": ["South", "North"]}),
    )
    orders = _dataset(
        "orders",
        pd.DataFrame({"order_id": ["O1", "O2"], "customer_id": ["C001", "C002"], "amount": [10, 20]}),
    )
    products = _dataset(
        "products",
        pd.DataFrame({"product_id": ["P1"], "product_name": ["Widget"]}),
    )
    orders2 = _dataset(
        "orders",
        pd.DataFrame(
            {
                "order_id": ["O1", "O2"],
                "customer_id": ["C001", "C002"],
                "product_id": ["P1", "P1"],
                "amount": [10, 20],
            }
        ),
    )
    rels = find_relationships([customers, orders2, products])
    pairs = {(r.left_column, r.right_column) for r in rels}
    assert ("customer_id", "customer_id") in pairs or any(
        r.left_column == "customer_id" and r.right_column == "customer_id" for r in rels
    )
    assert any(r.left_column == "product_id" and r.right_column == "product_id" for r in rels)


def test_datetime_detection_in_profiler():
    """Verify that date-formatted string columns are profiled as datetime."""
    frame = pd.DataFrame(
        {
            "order_date": ["2025-01-01", "2025-01-02", "2025-01-03"],
            "event_time": ["2025-01-01 10:00:00", "2025-01-02 11:00:00", "2025-01-03 12:00:00"],
            "plain_text": ["apple", "banana", "cherry"],
        }
    )
    profile = profile_dataset(_dataset("orders", frame))
    col_map = {col.name: col for col in profile.columns}

    # order_date and event_time should normalize to datetime
    assert col_map["order_date"].data_type == "datetime"
    assert col_map["event_time"].data_type == "datetime"
    # plain_text should remain string
    assert col_map["plain_text"].data_type == "string"


def test_no_false_positive_relationships():
    """Ensure disparate columns without name or type match are not linked."""
    table_a = _dataset(
        "table_a",
        pd.DataFrame({"metric_val": [10.5, 20.2], "category_name": ["A", "B"]}),
    )
    table_b = _dataset(
        "table_b",
        pd.DataFrame({"user_comment": ["great", "bad"], "status_flag": [True, False]}),
    )
    rels = find_relationships([table_a, table_b])
    # No relationships should be inferred between arbitrary metric/comment columns
    assert len(rels) == 0

