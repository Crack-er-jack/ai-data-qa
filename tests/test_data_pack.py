"""Validation tests for the synthetic test-data pack.

Verifies:
1. File existence and sizes.
2. Row counts and column schemas.
3. Foreign key referential integrity across tables.
4. Mathematical consistency of computed totals.
5. Ingestion compatibility with app's parse_upload.
6. Excel parsing of salaries.xlsx.
"""

from pathlib import Path
import pandas as pd
import openpyxl

from src.ingestion.loader import parse_upload


ROOT_DIR = Path(__file__).resolve().parent.parent
RETAIL_DIR = ROOT_DIR / "test_data" / "retail"
HR_DIR = ROOT_DIR / "test_data" / "hr"
MESSY_DIR = ROOT_DIR / "test_data" / "messy"


def test_retail_files_and_integrity():
    """Verify retail dataset files, schemas, and relational constraints."""
    cust_path = RETAIL_DIR / "customers.csv"
    orders_path = RETAIL_DIR / "orders.csv"
    prods_path = RETAIL_DIR / "products.csv"
    mkt_path = RETAIL_DIR / "marketing_spend.csv"
    gt_path = RETAIL_DIR / "GROUND_TRUTH.md"

    assert cust_path.exists()
    assert orders_path.exists()
    assert prods_path.exists()
    assert mkt_path.exists()
    assert gt_path.exists()

    cust_df = pd.read_csv(cust_path)
    orders_df = pd.read_csv(orders_path)
    prods_df = pd.read_csv(prods_path)
    mkt_df = pd.read_csv(mkt_path)

    # 1. Row counts
    assert len(cust_df) == 60
    assert len(orders_df) == 500
    assert len(prods_df) == 25
    assert len(mkt_df) == 336

    # 2. Foreign keys
    cust_ids = set(cust_df["customer_id"])
    prod_ids = set(prods_df["product_id"])

    assert set(orders_df["customer_id"]).issubset(cust_ids), "Broken customer FK in orders"
    assert set(orders_df["product_id"]).issubset(prod_ids), "Broken product FK in orders"

    # 3. Mathematical consistency
    computed_line_totals = (
        orders_df["quantity"] * orders_df["unit_price"] * (1.0 - orders_df["discount"])
    ).round(2)
    diff = (orders_df["line_total"] - computed_line_totals).abs()
    assert (diff < 0.01).all(), "line_total does not match quantity * unit_price * (1 - discount)"

    # 4. Marketing spend alignment
    assert set(mkt_df["region"]).issubset(set(cust_df["region"]))

    # 5. File size checks (all small, < 100KB)
    for p in (cust_path, orders_path, prods_path, mkt_path):
        assert p.stat().st_size < 200_000, f"File {p.name} too large"


def test_hr_files_and_integrity():
    """Verify HR dataset files, schemas, and relational constraints."""
    depts_path = HR_DIR / "departments.csv"
    emps_path = HR_DIR / "employees.csv"
    salaries_path = HR_DIR / "salaries.xlsx"
    perf_path = HR_DIR / "performance.csv"
    gt_path = HR_DIR / "GROUND_TRUTH.md"

    assert depts_path.exists()
    assert emps_path.exists()
    assert salaries_path.exists()
    assert perf_path.exists()
    assert gt_path.exists()

    depts_df = pd.read_csv(depts_path)
    emps_df = pd.read_csv(emps_path)
    salaries_df = pd.read_excel(salaries_path, engine="openpyxl")
    perf_df = pd.read_csv(perf_path)

    # 1. Row counts
    assert len(depts_df) == 7
    assert len(emps_df) == 50
    assert len(salaries_df) == 133
    assert len(perf_df) == 81

    # 2. Foreign keys
    dept_ids = set(depts_df["department_id"])
    emp_ids = set(emps_df["employee_id"])

    assert set(emps_df["department_id"]).issubset(dept_ids), "Broken department FK in employees"
    assert set(salaries_df["employee_id"]).issubset(emp_ids), "Broken employee FK in salaries"
    assert set(perf_df["employee_id"]).issubset(emp_ids), "Broken employee FK in performance"

    # 3. Deliberate omission test: No attrition reason column
    assert "attrition_reason" not in emps_df.columns
    assert "termination_reason" not in emps_df.columns

    # 4. Multi-salary records exist
    counts_per_emp = salaries_df["employee_id"].value_counts()
    assert (counts_per_emp > 1).any(), "Expected some employees to have multiple salary records"


def test_messy_data_and_notes():
    """Verify messy test dataset and documentation."""
    messy_path = MESSY_DIR / "messy_sales.csv"
    notes_path = MESSY_DIR / "MESSY_DATA_NOTES.md"

    assert messy_path.exists()
    assert notes_path.exists()

    df = pd.read_csv(messy_path)
    assert len(df) == 11
    # Check for whitespace in headers
    assert " Customer Name " in df.columns
    # Check for mixed capitalization in headers
    assert "REGION" in df.columns
    assert "Sales Amount" in df.columns
    # Check for currency formatting
    assert df["Sales Amount"].str.startswith("$").all()


def test_app_ingestion_compatibility():
    """Verify that all created files can be ingested via the application loader."""
    # Test CSV ingestion
    for csv_file in [
        RETAIL_DIR / "customers.csv",
        RETAIL_DIR / "orders.csv",
        HR_DIR / "employees.csv",
        MESSY_DIR / "messy_sales.csv",
    ]:
        content = csv_file.read_bytes()
        parsed = parse_upload(csv_file.name, content, set(), size_bytes=len(content))
        assert len(parsed) >= 1
        assert len(parsed[0].dataframe) > 0

    # Test Excel ingestion
    xlsx_file = HR_DIR / "salaries.xlsx"
    content = xlsx_file.read_bytes()
    parsed = parse_upload(xlsx_file.name, content, set(), size_bytes=len(content))
    assert len(parsed) >= 1
    assert len(parsed[0].dataframe) == 133
