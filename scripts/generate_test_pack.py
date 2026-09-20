"""Synthetic test-data generator for the AI Data Q&A application.

Produces deterministic, internally consistent relational datasets for:
1. Retail (customers.csv, orders.csv, products.csv, marketing_spend.csv)
2. HR (departments.csv, employees.csv, salaries.xlsx, performance.csv)
3. Messy (messy_sales.csv)

Also computes exact ground-truth answers using DuckDB/Pandas and compiles
GROUND_TRUTH.md and MESSY_DATA_NOTES.md.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import random
from typing import Any

import duckdb
import numpy as np
import pandas as pd


ROOT_DIR = Path(__file__).resolve().parent.parent
TEST_DATA_DIR = ROOT_DIR / "test_data"
RETAIL_DIR = TEST_DATA_DIR / "retail"
HR_DIR = TEST_DATA_DIR / "hr"
MESSY_DIR = TEST_DATA_DIR / "messy"


def generate_retail_data(seed: int = 42) -> dict[str, pd.DataFrame]:
    """Generate deterministic synthetic retail datasets."""
    rng = random.Random(seed)

    # 1. Products (25 products across 4 categories)
    categories = {
        "Hardware": [
            ("HW-01", "Enterprise Server Pro", "Servers", 1200.0, 1800.0),
            ("HW-02", "Developer Laptop 16", "Laptops", 850.0, 1400.0),
            ("HW-03", "Standard Office PC", "Desktops", 400.0, 650.0),
            ("HW-04", "Network Switch 48-Port", "Networking", 300.0, 520.0),
            ("HW-05", "Enterprise Router XR", "Networking", 450.0, 750.0),
            ("HW-06", "Storage Array 10TB", "Storage", 600.0, 990.0),
        ],
        "Software": [
            ("SW-01", "Cloud Analytics Annual License", "Analytics", 200.0, 800.0),
            ("SW-02", "Security Suite Pro License", "Security", 150.0, 500.0),
            ("SW-03", "Database Enterprise Edition", "Database", 500.0, 1500.0),
            ("SW-04", "Productivity Workspace Suite", "Productivity", 80.0, 240.0),
            ("SW-05", "Developer IDE Subscription", "DevTools", 100.0, 300.0),
            ("SW-06", "CRM Platform Seat", "CRM", 250.0, 700.0),
        ],
        "Accessories": [
            ("AC-01", "Ergonomic Mechanical Keyboard", "Peripherals", 40.0, 95.0),
            ("AC-02", "Precision Wireless Mouse", "Peripherals", 20.0, 55.0),
            ("AC-03", "4K UltraSharp 27-inch Monitor", "Displays", 180.0, 350.0),
            ("AC-04", "Dual-Display Docking Station", "Docks", 60.0, 140.0),
            ("AC-05", "Noise-Cancelling Headset", "Audio", 50.0, 120.0),
            ("AC-06", "USB-C Multi-Port Hub", "Cables & Hubs", 15.0, 45.0),
            ("AC-07", "Webcam 1080p HD", "Audio & Video", 30.0, 75.0),
        ],
        "Services": [
            ("SV-01", "24/7 Enterprise Platinum Support", "Support", 300.0, 1000.0),
            ("SV-02", "Onboarding & Implementation Consulting", "Consulting", 800.0, 2500.0),
            ("SV-03", "Cloud Architecture Migration Service", "Consulting", 1500.0, 4000.0),
            ("SV-04", "Security Audit & Pen Testing", "Security Services", 1200.0, 3500.0),
            ("SV-05", "Data Pipeline Engineering Support", "Data Services", 900.0, 2200.0),
            ("SV-06", "Custom Integrations Delivery", "Engineering", 1000.0, 2800.0),
        ],
    }

    product_rows = []
    for cat, prods in categories.items():
        for pid, name, subcat, cost, price in prods:
            product_rows.append({
                "product_id": pid,
                "product_name": name,
                "category": cat,
                "subcategory": subcat,
                "unit_cost": cost,
                "_suggested_price": price,
            })
    products_df = pd.DataFrame(product_rows)

    # 2. Customers (60 customers across 4 regions and 3 segments)
    regions = ["North", "South", "East", "West"]
    segments = ["Consumer", "Small Business", "Enterprise"]
    first_names = [
        "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael",
        "Linda", "David", "Elizabeth", "William", "Barbara", "Richard", "Susan",
        "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen", "Christopher",
        "Nancy", "Daniel", "Lisa", "Matthew", "Margaret", "Anthony", "Betty",
        "Mark", "Sandra", "Donald", "Ashley", "Steven", "Kimberly", "Paul",
        "Emily", "Andrew", "Donna", "Joshua", "Michelle", "Kenneth", "Carol",
        "Kevin", "Amanda", "Brian", "Melissa", "George", "Deborah", "Edward",
        "Stephanie", "Ronald", "Rebecca", "Timothy", "Sharon", "Jason", "Laura",
        "Jeffrey", "Cynthia", "Ryan", "Kathleen"
    ]
    last_names = [
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
        "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
        "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
        "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
        "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
        "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
        "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
        "Carter", "Roberts", "Gomez", "Phillips", "Evans", "Turner", "Diaz",
        "Parker", "Cruz", "Edwards", "Collins", "Reyes"
    ]

    customer_rows = []
    start_signup = date(2023, 1, 15)
    for i in range(60):
        cid = f"CUST-{1001 + i}"
        cname = f"{first_names[i]} {last_names[i]}"
        cseg = segments[i % len(segments)]
        creg = regions[(i // 3) % len(regions)]
        signup_dt = start_signup + timedelta(days=int(i * 12 + (i % 7)))
        customer_rows.append({
            "customer_id": cid,
            "customer_name": cname,
            "segment": cseg,
            "region": creg,
            "signup_date": signup_dt.isoformat(),
        })
    customers_df = pd.DataFrame(customer_rows)

    # 3. Orders (500 orders spanning 2025-01-01 through 2026-09-15)
    start_order_date = date(2025, 1, 3)
    end_order_date = date(2026, 9, 15)
    total_days = (end_order_date - start_order_date).days

    order_rows = []
    prod_lookup = {row["product_id"]: row for row in product_rows}

    status_pool = ["completed"] * 80 + ["cancelled"] * 12 + ["pending"] * 8

    for i in range(500):
        oid = f"ORD-{50001 + i}"
        cust = customer_rows[rng.randint(0, len(customer_rows) - 1)]
        cid = cust["customer_id"]

        prod_id = rng.choice(products_df["product_id"].tolist())
        pinfo = prod_lookup[prod_id]

        day_offset = int((i / 500.0) * total_days + rng.randint(-3, 3))
        day_offset = max(0, min(total_days, day_offset))
        odate = start_order_date + timedelta(days=day_offset)

        status = status_pool[i % len(status_pool)]

        # Enterprise buys larger quantities
        if cust["segment"] == "Enterprise":
            qty = rng.choice([2, 3, 5, 8, 10, 15])
            disc = rng.choice([0.05, 0.10, 0.15, 0.20])
        elif cust["segment"] == "Small Business":
            qty = rng.choice([1, 2, 3, 4, 5])
            disc = rng.choice([0.0, 0.05, 0.10])
        else:
            qty = rng.choice([1, 1, 2, 2, 3])
            disc = rng.choice([0.0, 0.0, 0.05])

        unit_p = pinfo["_suggested_price"]
        line_tot = round(qty * unit_p * (1.0 - disc), 2)

        order_rows.append({
            "order_id": oid,
            "customer_id": cid,
            "product_id": prod_id,
            "order_date": odate.isoformat(),
            "status": status,
            "quantity": qty,
            "unit_price": unit_p,
            "discount": disc,
            "line_total": line_tot,
        })
    orders_df = pd.DataFrame(order_rows)

    # 4. Marketing Spend (Monthly spend from 2025-01 to 2026-09 across 4 regions & 4 channels)
    channels = ["Search", "Social", "Email", "Events"]
    spend_rows = []

    cur_year, cur_month = 2025, 1
    months_list = []
    while (cur_year < 2026) or (cur_year == 2026 and cur_month <= 9):
        months_list.append(f"{cur_year}-{cur_month:02d}")
        cur_month += 1
        if cur_month > 12:
            cur_year += 1
            cur_month = 1

    channel_base = {
        "Search": 4500.0,
        "Social": 3500.0,
        "Email": 1200.0,
        "Events": 6000.0,
    }
    region_multiplier = {
        "North": 1.2,
        "South": 1.0,
        "East": 1.1,
        "West": 1.15,
    }

    m_idx = 0
    for m in months_list:
        for reg in regions:
            for ch in channels:
                base = channel_base[ch] * region_multiplier[reg]
                noise = rng.uniform(-0.15, 0.15)
                amt = round(base * (1.0 + noise), 2)
                spend_rows.append({
                    "month": m,
                    "region": reg,
                    "channel": ch,
                    "spend": amt,
                })
                m_idx += 1
    marketing_df = pd.DataFrame(spend_rows)

    # Drop internal helper price column
    clean_products_df = products_df.drop(columns=["_suggested_price"])

    return {
        "customers": customers_df,
        "orders": orders_df,
        "products": clean_products_df,
        "marketing_spend": marketing_df,
    }


def generate_hr_data(seed: int = 101) -> dict[str, pd.DataFrame]:
    """Generate deterministic synthetic HR datasets."""
    rng = random.Random(seed)

    # 1. Departments (7 departments)
    depts = [
        ("D01", "Engineering", "San Francisco, CA", "CC-100"),
        ("D02", "Sales", "New York, NY", "CC-200"),
        ("D03", "Marketing", "Chicago, IL", "CC-300"),
        ("D04", "Finance", "New York, NY", "CC-400"),
        ("D05", "Operations", "Austin, TX", "CC-500"),
        ("D06", "HR", "Chicago, IL", "CC-600"),
        ("D07", "Customer Success", "Austin, TX", "CC-700"),
    ]
    departments_df = pd.DataFrame([
        {
            "department_id": d[0],
            "department_name": d[1],
            "location": d[2],
            "cost_center": d[3],
        }
        for d in depts
    ])

    # 2. Employees (50 employees)
    job_levels = ["L1", "L2", "L3", "L4", "L5"]
    emp_names = [
        "Alice Johnson", "Bob Smith", "Charlie Davis", "Diana Evans", "Ethan Harris",
        "Fiona Clark", "George Lewis", "Hannah Walker", "Ian Robinson", "Julia Young",
        "Kevin Allen", "Laura King", "Michael Wright", "Nina Scott", "Oscar Torres",
        "Paula Nguyen", "Quinn Hill", "Rachel Flores", "Sam Green", "Tina Adams",
        "Uma Nelson", "Victor Baker", "Wendy Hall", "Xavier Rivera", "Yvonne Campbell",
        "Zachary Mitchell", "Abigail Carter", "Brian Roberts", "Chloe Gomez", "Derek Phillips",
        "Elena Evans", "Felix Turner", "Grace Diaz", "Henry Parker", "Isabel Cruz",
        "Jack Edwards", "Kendra Collins", "Liam Reyes", "Mia Stewart", "Noah Morris",
        "Olivia Morales", "Peter Murphy", "Quincy Cook", "Ruby Rogers", "Sean Morgan",
        "Tara Peterson", "Uriah Cooper", "Valerie Reed", "Will Bailey", "Xena Bell"
    ]
    locations = [
        "San Francisco, CA", "New York, NY", "Chicago, IL", "Austin, TX", "Remote"
    ]
    statuses = ["Active"] * 38 + ["Exited"] * 8 + ["On Leave"] * 4

    employee_rows = []
    hire_start = date(2021, 3, 1)
    for i, name in enumerate(emp_names):
        eid = f"EMP-{2001 + i}"
        dept_id = depts[i % len(depts)][0]
        level_draw = i % 10
        if level_draw in (0,):
            jlevel = "L1"
        elif level_draw in (1, 2, 3):
            jlevel = "L2"
        elif level_draw in (4, 5, 6):
            jlevel = "L3"
        elif level_draw in (7, 8):
            jlevel = "L4"
        else:
            jlevel = "L5"

        loc = locations[i % len(locations)]
        h_offset = int(i * 35 + (i % 5) * 3)
        hdate = hire_start + timedelta(days=h_offset)
        status = statuses[i % len(statuses)]

        employee_rows.append({
            "employee_id": eid,
            "employee_name": name,
            "department_id": dept_id,
            "job_level": jlevel,
            "location": loc,
            "hire_date": hdate.isoformat(),
            "employment_status": status,
        })
    employees_df = pd.DataFrame(employee_rows)

    # 3. Salaries (salaries.xlsx)
    base_by_level = {
        "L1": 65000.0,
        "L2": 90000.0,
        "L3": 125000.0,
        "L4": 165000.0,
        "L5": 215000.0,
    }
    band_by_level = {
        "L1": "Band-A",
        "L2": "Band-B",
        "L3": "Band-C",
        "L4": "Band-D",
        "L5": "Band-E",
    }

    salary_rows = []
    for emp in employee_rows:
        eid = emp["employee_id"]
        lvl = emp["job_level"]
        base = base_by_level[lvl]
        band = band_by_level[lvl]
        hire_dt = datetime.fromisoformat(emp["hire_date"]).date()

        # Initial salary on hire
        initial_base = round(base * rng.uniform(0.95, 1.05), -2)
        initial_bonus = round(initial_base * rng.uniform(0.08, 0.12), -2)
        salary_rows.append({
            "employee_id": eid,
            "effective_date": hire_dt.isoformat(),
            "base_salary": initial_base,
            "bonus": initial_bonus,
            "salary_band": band,
        })

        # If hired before 2025, give adjustment in 2025
        if hire_dt < date(2025, 1, 1):
            eff_2025 = date(2025, 1, 1)
            b2025 = round(initial_base * 1.06, -2)
            bonus_2025 = round(b2025 * 0.12, -2)
            salary_rows.append({
                "employee_id": eid,
                "effective_date": eff_2025.isoformat(),
                "base_salary": b2025,
                "bonus": bonus_2025,
                "salary_band": band,
            })

            # If active, adjustment in 2026
            if emp["employment_status"] != "Exited":
                eff_2026 = date(2026, 1, 1)
                b2026 = round(b2025 * 1.05, -2)
                bonus_2026 = round(b2026 * 0.14, -2)
                salary_rows.append({
                    "employee_id": eid,
                    "effective_date": eff_2026.isoformat(),
                    "base_salary": b2026,
                    "bonus": bonus_2026,
                    "salary_band": band,
                })
        elif hire_dt < date(2026, 1, 1) and emp["employment_status"] != "Exited":
            eff_2026 = date(2026, 1, 1)
            b2026 = round(initial_base * 1.05, -2)
            bonus_2026 = round(b2026 * 0.12, -2)
            salary_rows.append({
                "employee_id": eid,
                "effective_date": eff_2026.isoformat(),
                "base_salary": b2026,
                "bonus": bonus_2026,
                "salary_band": band,
            })

    salaries_df = pd.DataFrame(salary_rows)

    # 4. Performance (performance.csv)
    perf_rows = []
    for emp in employee_rows:
        eid = emp["employee_id"]
        hire_dt = datetime.fromisoformat(emp["hire_date"]).date()

        if hire_dt < date(2024, 7, 1):
            score_2024 = round(rng.uniform(2.8, 4.9), 2)
            if score_2024 >= 4.2:
                r2024 = "Exceeds Expectations"
                promo_2024 = rng.choice([True, False])
            elif score_2024 >= 3.0:
                r2024 = "Meets Expectations"
                promo_2024 = False
            else:
                r2024 = "Needs Improvement"
                promo_2024 = False

            perf_rows.append({
                "employee_id": eid,
                "review_date": "2024-12-15",
                "performance_score": score_2024,
                "rating": r2024,
                "promotion_flag": promo_2024,
            })

        if hire_dt < date(2025, 7, 1):
            score_2025 = round(rng.uniform(3.0, 5.0), 2)
            if score_2025 >= 4.3:
                r2025 = "Exceeds Expectations"
                promo_2025 = rng.choice([True, False])
            elif score_2025 >= 3.1:
                r2025 = "Meets Expectations"
                promo_2025 = False
            else:
                r2025 = "Needs Improvement"
                promo_2025 = False

            perf_rows.append({
                "employee_id": eid,
                "review_date": "2025-12-15",
                "performance_score": score_2025,
                "rating": r2025,
                "promotion_flag": promo_2025,
            })

    performance_df = pd.DataFrame(perf_rows)

    return {
        "departments": departments_df,
        "employees": employees_df,
        "salaries": salaries_df,
        "performance": performance_df,
    }


def generate_messy_data(seed: int = 777) -> pd.DataFrame:
    """Generate a realistic imperfect dataset to test ingestion robustness."""
    rows = [
        {"Order ID": "ORD-901", " Customer Name ": "Acme Corp", "REGION": "South", "Sales Amount": "$1,250.00", "Order Date": "03/15/2025", "UNITS": 5, "Delivery Note": "Fragile"},
        {"Order ID": "ORD-902", " Customer Name ": "Beta LLC", "REGION": "south", "Sales Amount": "$450.50", "Order Date": "04/02/2025", "UNITS": 2, "Delivery Note": None},
        {"Order ID": "ORD-903", " Customer Name ": "Gamma Inc", "REGION": "SOUTH", "Sales Amount": "$3,100.00", "Order Date": "05/18/2025", "UNITS": 12, "Delivery Note": "Loading dock B"},
        {"Order ID": "ORD-904", " Customer Name ": "Delta Co", "REGION": "North", "Sales Amount": "$820.75", "Order Date": "06/21/2025", "UNITS": 3, "Delivery Note": "Call on arrival"},
        {"Order ID": "ORD-905", " Customer Name ": "Epsilon Ltd", "REGION": "north", "Sales Amount": "$2,400.00", "Order Date": "07/11/2025", "UNITS": 8, "Delivery Note": None},
        {"Order ID": "ORD-906", " Customer Name ": "Zeta Partners", "REGION": "East", "Sales Amount": "$990.00", "Order Date": "08/09/2025", "UNITS": 4, "Delivery Note": "Express"},
        {"Order ID": "ORD-907", " Customer Name ": "Eta Solutions", "REGION": "EAST", "Sales Amount": "$1,750.25", "Order Date": "09/14/2025", "UNITS": 6, "Delivery Note": None},
        {"Order ID": "ORD-908", " Customer Name ": "Theta Tech", "REGION": "West", "Sales Amount": "$5,600.00", "Order Date": "10/05/2025", "UNITS": 20, "Delivery Note": "Signature required"},
        {"Order ID": "ORD-909", " Customer Name ": "Iota Systems", "REGION": "west", "Sales Amount": "$340.00", "Order Date": "11/22/2025", "UNITS": 1, "Delivery Note": None},
        {"Order ID": "ORD-910", " Customer Name ": "Kappa Global", "REGION": "South", "Sales Amount": "$2,150.00", "Order Date": "12/03/2025", "UNITS": 7, "Delivery Note": "Gate code 4490"},
        {"Order ID": "ORD-910", " Customer Name ": "Kappa Global Part 2", "REGION": "South", "Sales Amount": "$850.00", "Order Date": "12/04/2025", "UNITS": 3, "Delivery Note": "Backorder shipment"},
    ]
    return pd.DataFrame(rows)


def run_duckdb_query(con: duckdb.DuckDBPyConnection, sql: str) -> pd.DataFrame:
    """Execute SQL query against in-memory DuckDB connection."""
    return con.execute(sql).fetchdf()


def compute_retail_ground_truth(data: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Deterministically compute answers for all Retail QA questions using DuckDB."""
    con = duckdb.connect(":memory:")
    for name, df in data.items():
        con.register(name, df)

    # Q1: What is the total revenue?
    q1 = run_duckdb_query(con, "SELECT ROUND(SUM(line_total), 2) AS total_revenue FROM orders")
    total_rev = float(q1.iloc[0]["total_revenue"])

    # Q2: What is the average order value for completed orders?
    q2 = run_duckdb_query(con, "SELECT ROUND(AVG(line_total), 2) AS avg_completed_aov FROM orders WHERE status = 'completed'")
    avg_completed_aov = float(q2.iloc[0]["avg_completed_aov"])

    # Q3: What is the total revenue from the South region?
    q3 = run_duckdb_query(con, """
        SELECT ROUND(SUM(o.line_total), 2) AS south_revenue
        FROM orders o
        JOIN customers c ON o.customer_id = c.customer_id
        WHERE c.region = 'South'
    """)
    south_rev = float(q3.iloc[0]["south_revenue"])

    # Q4: Compare revenue across regions
    q4 = run_duckdb_query(con, """
        SELECT c.region, ROUND(SUM(o.line_total), 2) AS revenue
        FROM orders o
        JOIN customers c ON o.customer_id = c.customer_id
        GROUP BY c.region
        ORDER BY revenue DESC
    """)

    # Q5: Which region generated the most revenue?
    top_region = q4.iloc[0]["region"]
    top_region_rev = float(q4.iloc[0]["revenue"])

    # Q6: Show monthly revenue over time
    q6 = run_duckdb_query(con, """
        SELECT STRFTIME(CAST(order_date AS DATE), '%Y-%m') AS month, ROUND(SUM(line_total), 2) AS revenue
        FROM orders
        GROUP BY month
        ORDER BY month ASC
    """)

    # Q7: What is the total revenue by customer segment?
    q7 = run_duckdb_query(con, """
        SELECT c.segment, ROUND(SUM(o.line_total), 2) AS revenue
        FROM orders o
        JOIN customers c ON o.customer_id = c.customer_id
        GROUP BY c.segment
        ORDER BY revenue DESC
    """)

    # Q8: Which product category generated the most revenue?
    q8 = run_duckdb_query(con, """
        SELECT p.category, ROUND(SUM(o.line_total), 2) AS revenue
        FROM orders o
        JOIN products p ON o.product_id = p.product_id
        GROUP BY p.category
        ORDER BY revenue DESC
    """)
    top_cat = q8.iloc[0]["category"]
    top_cat_rev = float(q8.iloc[0]["revenue"])

    # Q9: Which customer segment generated the most revenue from Hardware products?
    q9 = run_duckdb_query(con, """
        SELECT c.segment, ROUND(SUM(o.line_total), 2) AS hardware_revenue
        FROM orders o
        JOIN customers c ON o.customer_id = c.customer_id
        JOIN products p ON o.product_id = p.product_id
        WHERE p.category = 'Hardware'
        GROUP BY c.segment
        ORDER BY hardware_revenue DESC
    """)
    top_hw_seg = q9.iloc[0]["segment"]
    top_hw_seg_rev = float(q9.iloc[0]["hardware_revenue"])

    # Q10: What is the total revenue from Hardware products in the last quarter?
    # Max date is 2026-09-15 (Q3 2026). "Last quarter" is Q2 2026 (2026-04-01 to 2026-06-30).
    q10 = run_duckdb_query(con, """
        SELECT ROUND(SUM(o.line_total), 2) AS hw_last_quarter_revenue
        FROM orders o
        JOIN products p ON o.product_id = p.product_id
        WHERE p.category = 'Hardware'
          AND o.order_date >= '2026-04-01' AND o.order_date <= '2026-06-30'
    """)
    hw_lq_rev = float(q10.iloc[0]["hw_last_quarter_revenue"])

    # Q11: Show revenue by product category for the South region
    q11 = run_duckdb_query(con, """
        SELECT p.category, ROUND(SUM(o.line_total), 2) AS south_revenue
        FROM orders o
        JOIN customers c ON o.customer_id = c.customer_id
        JOIN products p ON o.product_id = p.product_id
        WHERE c.region = 'South'
        GROUP BY p.category
        ORDER BY south_revenue DESC
    """)

    # Q12: Which customer spent the most?
    q12 = run_duckdb_query(con, """
        SELECT c.customer_name, c.customer_id, ROUND(SUM(o.line_total), 2) AS total_spend
        FROM orders o
        JOIN customers c ON o.customer_id = c.customer_id
        GROUP BY c.customer_name, c.customer_id
        ORDER BY total_spend DESC
        LIMIT 1
    """)
    top_cust_name = q12.iloc[0]["customer_name"]
    top_cust_id = q12.iloc[0]["customer_id"]
    top_cust_spend = float(q12.iloc[0]["total_spend"])

    # Q13: Show the top 10 customers by revenue
    q13 = run_duckdb_query(con, """
        SELECT c.customer_name, c.customer_id, c.segment, c.region, ROUND(SUM(o.line_total), 2) AS total_revenue
        FROM orders o
        JOIN customers c ON o.customer_id = c.customer_id
        GROUP BY c.customer_name, c.customer_id, c.segment, c.region
        ORDER BY total_revenue DESC
        LIMIT 10
    """)

    # Q14: Compare revenue with marketing spend by region
    q14 = run_duckdb_query(con, """
        WITH rev AS (
            SELECT c.region, ROUND(SUM(o.line_total), 2) AS total_revenue
            FROM orders o
            JOIN customers c ON o.customer_id = c.customer_id
            GROUP BY c.region
        ),
        mkt AS (
            SELECT region, ROUND(SUM(spend), 2) AS total_marketing_spend
            FROM marketing_spend
            GROUP BY region
        )
        SELECT rev.region, rev.total_revenue, mkt.total_marketing_spend
        FROM rev
        JOIN mkt ON rev.region = mkt.region
        ORDER BY rev.total_revenue DESC
    """)

    # Q15: Show monthly revenue and monthly marketing spend
    q15 = run_duckdb_query(con, """
        WITH rev AS (
            SELECT STRFTIME(CAST(order_date AS DATE), '%Y-%m') AS month, ROUND(SUM(line_total), 2) AS revenue
            FROM orders
            GROUP BY month
        ),
        mkt AS (
            SELECT month, ROUND(SUM(spend), 2) AS marketing_spend
            FROM marketing_spend
            GROUP BY month
        )
        SELECT rev.month, rev.revenue, mkt.marketing_spend
        FROM rev
        JOIN mkt ON rev.month = mkt.month
        ORDER BY rev.month ASC
    """)

    # Q16: What was revenue in the previous year? (2025)
    q16 = run_duckdb_query(con, """
        SELECT ROUND(SUM(line_total), 2) AS revenue_2025
        FROM orders
        WHERE order_date >= '2025-01-01' AND order_date <= '2025-12-31'
    """)
    rev_prev_year = float(q16.iloc[0]["revenue_2025"])

    # Q17: What is the average order value for completed Hardware orders in the South?
    q17 = run_duckdb_query(con, """
        SELECT ROUND(AVG(o.line_total), 2) AS aov
        FROM orders o
        JOIN customers c ON o.customer_id = c.customer_id
        JOIN products p ON o.product_id = p.product_id
        WHERE o.status = 'completed'
          AND p.category = 'Hardware'
          AND c.region = 'South'
    """)
    aov_south_hw = float(q17.iloc[0]["aov"])

    # Q18: What about North?
    q18 = run_duckdb_query(con, """
        SELECT ROUND(AVG(o.line_total), 2) AS aov
        FROM orders o
        JOIN customers c ON o.customer_id = c.customer_id
        JOIN products p ON o.product_id = p.product_id
        WHERE o.status = 'completed'
          AND p.category = 'Hardware'
          AND c.region = 'North'
    """)
    aov_north_hw = float(q18.iloc[0]["aov"])

    # Q19: Compare South and North revenue
    q19 = run_duckdb_query(con, """
        SELECT c.region, ROUND(SUM(o.line_total), 2) AS revenue
        FROM orders o
        JOIN customers c ON o.customer_id = c.customer_id
        WHERE c.region IN ('South', 'North')
        GROUP BY c.region
        ORDER BY revenue DESC
    """)

    # Q20: Show that comparison by month
    q20 = run_duckdb_query(con, """
        SELECT STRFTIME(CAST(o.order_date AS DATE), '%Y-%m') AS month, c.region, ROUND(SUM(o.line_total), 2) AS revenue
        FROM orders o
        JOIN customers c ON o.customer_id = c.customer_id
        WHERE c.region IN ('South', 'North')
        GROUP BY month, c.region
        ORDER BY month ASC, c.region ASC
    """)

    return {
        "q1": total_rev,
        "q2": avg_completed_aov,
        "q3": south_rev,
        "q4": q4,
        "q5": (top_region, top_region_rev),
        "q6": q6,
        "q7": q7,
        "q8": (top_cat, top_cat_rev),
        "q9": (top_hw_seg, top_hw_seg_rev),
        "q10": hw_lq_rev,
        "q11": q11,
        "q12": (top_cust_name, top_cust_id, top_cust_spend),
        "q13": q13,
        "q14": q14,
        "q15": q15,
        "q16": rev_prev_year,
        "q17": aov_south_hw,
        "q18": aov_north_hw,
        "q19": q19,
        "q20": q20,
    }


def compute_hr_ground_truth(data: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Deterministically compute answers for all HR QA questions using DuckDB."""
    con = duckdb.connect(":memory:")
    for name, df in data.items():
        con.register(name, df)

    # Q1: How many active employees do we have?
    q1 = run_duckdb_query(con, "SELECT COUNT(*) AS active_count FROM employees WHERE employment_status = 'Active'")
    active_count = int(q1.iloc[0]["active_count"])

    # Q2: What is the average salary by department? (latest effective salary per employee)
    q2 = run_duckdb_query(con, """
        WITH latest_salary AS (
            SELECT employee_id, base_salary,
                   ROW_NUMBER() OVER (PARTITION BY employee_id ORDER BY effective_date DESC) as rn
            FROM salaries
        )
        SELECT d.department_name, ROUND(AVG(ls.base_salary), 2) AS avg_salary
        FROM employees e
        JOIN departments d ON e.department_id = d.department_id
        JOIN latest_salary ls ON e.employee_id = ls.employee_id AND ls.rn = 1
        GROUP BY d.department_name
        ORDER BY avg_salary DESC
    """)

    # Q3: Which department has the highest average salary?
    top_dept = q2.iloc[0]["department_name"]
    top_dept_salary = float(q2.iloc[0]["avg_salary"])

    # Q4: What is the total salary expense by department? (latest effective salary per employee)
    q4 = run_duckdb_query(con, """
        WITH latest_salary AS (
            SELECT employee_id, base_salary,
                   ROW_NUMBER() OVER (PARTITION BY employee_id ORDER BY effective_date DESC) as rn
            FROM salaries
        )
        SELECT d.department_name, ROUND(SUM(ls.base_salary), 2) AS total_salary_expense
        FROM employees e
        JOIN departments d ON e.department_id = d.department_id
        JOIN latest_salary ls ON e.employee_id = ls.employee_id AND ls.rn = 1
        GROUP BY d.department_name
        ORDER BY total_salary_expense DESC
    """)

    # Q5: Show employee count by location
    q5 = run_duckdb_query(con, """
        SELECT location, COUNT(*) AS employee_count
        FROM employees
        GROUP BY location
        ORDER BY employee_count DESC
    """)

    # Q6: Show monthly salary expense over time
    q6 = run_duckdb_query(con, """
        SELECT STRFTIME(CAST(effective_date AS DATE), '%Y-%m') AS month,
               ROUND(SUM(base_salary), 2) AS total_base_salary
        FROM salaries
        GROUP BY month
        ORDER BY month ASC
    """)

    # Q7: What is the average salary for Engineering?
    q7 = run_duckdb_query(con, """
        WITH latest_salary AS (
            SELECT employee_id, base_salary,
                   ROW_NUMBER() OVER (PARTITION BY employee_id ORDER BY effective_date DESC) as rn
            FROM salaries
        )
        SELECT ROUND(AVG(ls.base_salary), 2) AS eng_avg_salary
        FROM employees e
        JOIN departments d ON e.department_id = d.department_id
        JOIN latest_salary ls ON e.employee_id = ls.employee_id AND ls.rn = 1
        WHERE d.department_name = 'Engineering'
    """)
    eng_avg_salary = float(q7.iloc[0]["eng_avg_salary"])

    # Q8: How many L3 employees are there?
    q8 = run_duckdb_query(con, "SELECT COUNT(*) AS l3_count FROM employees WHERE job_level = 'L3'")
    l3_count = int(q8.iloc[0]["l3_count"])

    # Q9: What is the average performance score by department?
    q9 = run_duckdb_query(con, """
        SELECT d.department_name, ROUND(AVG(p.performance_score), 2) AS avg_perf_score
        FROM employees e
        JOIN departments d ON e.department_id = d.department_id
        JOIN performance p ON e.employee_id = p.employee_id
        GROUP BY d.department_name
        ORDER BY avg_perf_score DESC
    """)

    # Q10: Which department has the highest average performance score?
    top_perf_dept = q9.iloc[0]["department_name"]
    top_perf_score = float(q9.iloc[0]["avg_perf_score"])

    # Q11: Show the relationship between job level and average salary
    q11 = run_duckdb_query(con, """
        WITH latest_salary AS (
            SELECT employee_id, base_salary,
                   ROW_NUMBER() OVER (PARTITION BY employee_id ORDER BY effective_date DESC) as rn
            FROM salaries
        )
        SELECT e.job_level, ROUND(AVG(ls.base_salary), 2) AS avg_salary
        FROM employees e
        JOIN latest_salary ls ON e.employee_id = ls.employee_id AND ls.rn = 1
        GROUP BY e.job_level
        ORDER BY e.job_level ASC
    """)

    # Q12: What was the average salary in 2025? (salaries effective in 2025)
    q12 = run_duckdb_query(con, """
        SELECT ROUND(AVG(base_salary), 2) AS avg_sal_2025
        FROM salaries
        WHERE effective_date >= '2025-01-01' AND effective_date <= '2025-12-31'
    """)
    avg_sal_2025 = float(q12.iloc[0]["avg_sal_2025"])

    # Q13: What about 2026? (salaries effective in 2026)
    q13 = run_duckdb_query(con, """
        SELECT ROUND(AVG(base_salary), 2) AS avg_sal_2026
        FROM salaries
        WHERE effective_date >= '2026-01-01' AND effective_date <= '2026-12-31'
    """)
    avg_sal_2026 = float(q13.iloc[0]["avg_sal_2026"])

    # Q14: What is the average salary of active Engineering employees?
    q14 = run_duckdb_query(con, """
        WITH latest_salary AS (
            SELECT employee_id, base_salary,
                   ROW_NUMBER() OVER (PARTITION BY employee_id ORDER BY effective_date DESC) as rn
            FROM salaries
        )
        SELECT ROUND(AVG(ls.base_salary), 2) AS active_eng_avg
        FROM employees e
        JOIN departments d ON e.department_id = d.department_id
        JOIN latest_salary ls ON e.employee_id = ls.employee_id AND ls.rn = 1
        WHERE d.department_name = 'Engineering' AND e.employment_status = 'Active'
    """)
    active_eng_avg = float(q14.iloc[0]["active_eng_avg"])

    # Q15: What about L3 Engineering employees?
    q15 = run_duckdb_query(con, """
        WITH latest_salary AS (
            SELECT employee_id, base_salary,
                   ROW_NUMBER() OVER (PARTITION BY employee_id ORDER BY effective_date DESC) as rn
            FROM salaries
        )
        SELECT ROUND(AVG(ls.base_salary), 2) AS l3_eng_avg
        FROM employees e
        JOIN departments d ON e.department_id = d.department_id
        JOIN latest_salary ls ON e.employee_id = ls.employee_id AND ls.rn = 1
        WHERE d.department_name = 'Engineering' AND e.job_level = 'L3'
    """)
    l3_eng_avg = float(q15.iloc[0]["l3_eng_avg"])

    # Q16: Show salary trends for Engineering
    q16 = run_duckdb_query(con, """
        SELECT s.effective_date, ROUND(AVG(s.base_salary), 2) AS avg_base_salary
        FROM employees e
        JOIN departments d ON e.department_id = d.department_id
        JOIN salaries s ON e.employee_id = s.employee_id
        WHERE d.department_name = 'Engineering'
        GROUP BY s.effective_date
        ORDER BY s.effective_date ASC
    """)

    # Q17: Which department has the largest number of exited employees?
    q17 = run_duckdb_query(con, """
        SELECT d.department_name, COUNT(*) AS exited_count
        FROM employees e
        JOIN departments d ON e.department_id = d.department_id
        WHERE e.employment_status = 'Exited'
        GROUP BY d.department_name
        ORDER BY exited_count DESC
    """)
    top_exited_dept = q17.iloc[0]["department_name"]
    top_exited_count = int(q17.iloc[0]["exited_count"])

    # Q18: What was the average salary before the most recent salary change?
    q18 = run_duckdb_query(con, """
        WITH ranked_salaries AS (
            SELECT employee_id, base_salary,
                   ROW_NUMBER() OVER (PARTITION BY employee_id ORDER BY effective_date DESC) as rn
            FROM salaries
        )
        SELECT ROUND(AVG(base_salary), 2) AS prev_avg_salary
        FROM ranked_salaries
        WHERE rn = 2
    """)
    prev_avg_salary = float(q18.iloc[0]["prev_avg_salary"])

    # Follow-up test 4: L3 Engineering salaries over effective dates
    fu4 = run_duckdb_query(con, """
        SELECT s.effective_date, ROUND(AVG(s.base_salary), 2) AS avg_salary
        FROM employees e
        JOIN departments d ON e.department_id = d.department_id
        JOIN salaries s ON e.employee_id = s.employee_id
        WHERE d.department_name = 'Engineering' AND e.job_level = 'L3'
        GROUP BY s.effective_date
        ORDER BY s.effective_date ASC
    """)

    return {
        "q1": active_count,
        "q2": q2,
        "q3": (top_dept, top_dept_salary),
        "q4": q4,
        "q5": q5,
        "q6": q6,
        "q7": eng_avg_salary,
        "q8": l3_count,
        "q9": q9,
        "q10": (top_perf_dept, top_perf_score),
        "q11": q11,
        "q12": avg_sal_2025,
        "q13": avg_sal_2026,
        "q14": active_eng_avg,
        "q15": l3_eng_avg,
        "q16": q16,
        "q17": (top_exited_dept, top_exited_count),
        "q18": prev_avg_salary,
        "fu4": fu4,
    }


def df_to_markdown(df: pd.DataFrame) -> str:
    """Render DataFrame as a GitHub-flavored markdown table without external dependencies."""
    headers = [str(col) for col in df.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join([":---"] * len(headers)) + " |",
    ]
    for _, row in df.iterrows():
        cells = [str(val) if pd.notna(val) else "" for val in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def build_retail_ground_truth_md(data: dict[str, pd.DataFrame], gt: dict[str, Any]) -> str:
    """Construct markdown content for retail/GROUND_TRUTH.md."""
    customers = data["customers"]
    orders = data["orders"]
    products = data["products"]
    marketing = data["marketing_spend"]

    # Pre-render markdown tables
    q4_table = df_to_markdown(gt["q4"])
    q6_table = df_to_markdown(gt["q6"])
    q7_table = df_to_markdown(gt["q7"])
    q8_df = orders.merge(products, on="product_id").groupby("category")["line_total"].sum().round(2).reset_index().sort_values("line_total", ascending=False)
    q8_table = df_to_markdown(q8_df)
    q9_df = orders.merge(products, on="product_id").merge(customers, on="customer_id").query("category == 'Hardware'").groupby("segment")["line_total"].sum().round(2).reset_index().sort_values("line_total", ascending=False)
    q9_table = df_to_markdown(q9_df)
    q11_table = df_to_markdown(gt["q11"])
    q13_table = df_to_markdown(gt["q13"])
    q14_table = df_to_markdown(gt["q14"])
    q15_table = df_to_markdown(gt["q15"])
    q19_table = df_to_markdown(gt["q19"])
    q20_table = df_to_markdown(gt["q20"])

    mermaid_block = "```mermaid\nflowchart TD\n    CUSTOMERS[\"customers\"] -->|customer_id| ORDERS[\"orders\"]\n    PRODUCTS[\"products\"] -->|product_id| ORDERS[\"orders\"]\n    CUSTOMERS[\"customers\"] -.->|region| MARKETING_SPEND[\"marketing_spend\"]\n```"

    md = f"""# Retail Test Pack — Ground Truth & Specification

## 1. Overview & Seed Details
- **Random Seed**: Deterministic seed `42`
- **Time Span**: Orders from `2025-01-03` to `2026-09-15` (covering 21 months, 7 quarters across 2025 and 2026).
- **Temporal Anchors**:
  - `current year`: 2026 (`2026-01-01` to `2026-09-15`)
  - `previous year`: 2025 (`2025-01-01` to `2025-12-31`)
  - `last quarter`: Q2 2026 (`2026-04-01` to `2026-06-30`, given max date in Q3 2026)

## 2. Table Profiles & Row Counts

| Table Name | File Format | Row Count | Column Count | Primary Key | Foreign Keys |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `customers` | CSV | {len(customers)} | {len(customers.columns)} | `customer_id` | None |
| `orders` | CSV | {len(orders)} | {len(orders.columns)} | `order_id` | `customer_id` -> `customers.customer_id`<br>`product_id` -> `products.product_id` |
| `products` | CSV | {len(products)} | {len(products.columns)} | `product_id` | None |
| `marketing_spend` | CSV | {len(marketing)} | {len(marketing.columns)} | Composite (`month`, `region`, `channel`) | `region` matches `customers.region`<br>`month` matches `orders.order_date` (`YYYY-MM`) |

### Key Columns
- **customers**: `customer_id`, `customer_name`, `segment` (Consumer, Small Business, Enterprise), `region` (North, South, East, West), `signup_date`.
- **orders**: `order_id`, `customer_id`, `product_id`, `order_date`, `status` (completed [400], cancelled [60], pending [40]), `quantity`, `unit_price`, `discount`, `line_total`.
  - Mathematical integrity: `line_total = round(quantity * unit_price * (1 - discount), 2)`
- **products**: `product_id`, `product_name`, `category` (Hardware, Software, Accessories, Services), `subcategory`, `unit_cost`.
- **marketing_spend**: `month` (YYYY-MM), `region`, `channel` (Search, Social, Email, Events), `spend`.

## 3. Relational Architecture
{mermaid_block}

## 4. Calculated Ground Truth for Retail QA Questions

### Question 1: What is the total revenue?
- **Expected Answer**: **${gt['q1']:,.2f}**
- **Relevant Tables**: `orders`
- **Expected Visualization Type**: `none` (or `kpi` / `scalar`)
- **Query Verification**: `SELECT ROUND(SUM(line_total), 2) FROM orders`

### Question 2: What is the average order value for completed orders?
- **Expected Answer**: **${gt['q2']:,.2f}**
- **Relevant Tables**: `orders`
- **Expected Visualization Type**: `none` (or `kpi` / `scalar`)
- **Query Verification**: `SELECT ROUND(AVG(line_total), 2) FROM orders WHERE status = 'completed'`

### Question 3: What is the total revenue from the South region?
- **Expected Answer**: **${gt['q3']:,.2f}**
- **Relevant Tables**: `orders`, `customers`
- **Expected Visualization Type**: `none` (or `kpi` / `scalar`)
- **Query Verification**: `SELECT ROUND(SUM(o.line_total), 2) FROM orders o JOIN customers c ON o.customer_id = c.customer_id WHERE c.region = 'South'`

### Question 4: Compare revenue across regions.
- **Expected Answer**:
{q4_table}
- **Relevant Tables**: `orders`, `customers`
- **Expected Visualization Type**: `bar`

### Question 5: Which region generated the most revenue?
- **Expected Answer**: **{gt['q5'][0]}** with **${gt['q5'][1]:,.2f}**
- **Relevant Tables**: `orders`, `customers`
- **Expected Visualization Type**: `none` (or `kpi` / `bar`)

### Question 6: Show monthly revenue over time.
- **Expected Answer**:
{q6_table}
- **Relevant Tables**: `orders`
- **Expected Visualization Type**: `line`

### Question 7: What is the total revenue by customer segment?
- **Expected Answer**:
{q7_table}
- **Relevant Tables**: `orders`, `customers`
- **Expected Visualization Type**: `bar`

### Question 8: Which product category generated the most revenue?
- **Expected Answer**: **{gt['q8'][0]}** with **${gt['q8'][1]:,.2f}**
- **Breakdown**:
{q8_table}
- **Relevant Tables**: `orders`, `products`
- **Expected Visualization Type**: `bar`

### Question 9: Which customer segment generated the most revenue from Hardware products?
- **Expected Answer**: **{gt['q9'][0]}** with **${gt['q9'][1]:,.2f}**
- **Breakdown**:
{q9_table}
- **Relevant Tables**: `orders`, `customers`, `products`
- **Expected Visualization Type**: `bar`

### Question 10: What is the total revenue from Hardware products in the last quarter?
- **Expected Answer**: **${gt['q10']:,.2f}** (Q2 2026: 2026-04-01 to 2026-06-30)
- **Relevant Tables**: `orders`, `products`
- **Expected Visualization Type**: `none` (or `kpi` / `scalar`)

### Question 11: Show revenue by product category for the South region.
- **Expected Answer**:
{q11_table}
- **Relevant Tables**: `orders`, `customers`, `products`
- **Expected Visualization Type**: `bar`

### Question 12: Which customer spent the most?
- **Expected Answer**: **{gt['q12'][0]}** ({gt['q12'][1]}) with total spend of **${gt['q12'][2]:,.2f}**
- **Relevant Tables**: `orders`, `customers`
- **Expected Visualization Type**: `none` (or `kpi` / `scalar`)

### Question 13: Show the top 10 customers by revenue.
- **Expected Answer**:
{q13_table}
- **Relevant Tables**: `orders`, `customers`
- **Expected Visualization Type**: `bar` (or `table`)

### Question 14: Compare revenue with marketing spend by region.
- **Expected Answer**:
{q14_table}
- **Relevant Tables**: `orders`, `customers`, `marketing_spend`
- **Expected Visualization Type**: `bar` (grouped or table)

### Question 15: Show monthly revenue and monthly marketing spend.
- **Expected Answer**:
{q15_table}
- **Relevant Tables**: `orders`, `marketing_spend`
- **Expected Visualization Type**: `line` (or `bar` / `table`)

### Question 16: What was revenue in the previous year?
- **Expected Answer**: **${gt['q16']:,.2f}** (Year 2025: 2025-01-01 to 2025-12-31)
- **Relevant Tables**: `orders`
- **Expected Visualization Type**: `none` (or `kpi` / `scalar`)

### Question 17: What is the average order value for completed Hardware orders in the South?
- **Expected Answer**: **${gt['q17']:,.2f}**
- **Relevant Tables**: `orders`, `customers`, `products`
- **Expected Visualization Type**: `none` (or `kpi` / `scalar`)

### Question 18: What about North?
- **Expected Answer**: **${gt['q18']:,.2f}**
- **Relevant Tables**: `orders`, `customers`, `products`
- **Expected Visualization Type**: `none` (or `kpi` / `scalar`)

### Question 19: Compare South and North revenue.
- **Expected Answer**:
{q19_table}
- **Relevant Tables**: `orders`, `customers`
- **Expected Visualization Type**: `bar`

### Question 20: Show that comparison by month.
- **Expected Answer**:
{q20_table}
- **Relevant Tables**: `orders`, `customers`
- **Expected Visualization Type**: `line` (or `bar`)

---

## 5. Expected Behavior for Negative / Missing-Data Questions

The following questions MUST NOT be answered with fabricated data. The model must return `status="cannot_answer"` with a clear explanation of missing columns/data:

| Question Number | Question Text | Missing Information | Expected System Behavior |
| :--- | :--- | :--- | :--- |
| **Q21** | *What is our employee attrition rate?* | No employee or HR tables present in the retail dataset. | Decline and inform user that employee data is not present in the uploaded tables. |
| **Q22** | *What was our profit margin?* | Profit margin requires total cost of goods sold or operating expenses subtracted from net revenue; while `products.unit_cost` exists, operating overhead expenses are absent. | Clarify or decline if interpreted as corporate profit margin, or explicitly state assumptions. |
| **Q23** | *How many employees resigned?* | No employee or HR tables present. | Decline with clear notice of missing data. |
| **Q24** | *What was the customer satisfaction score?* | No CSAT, NPS, survey, or feedback ratings exist in `customers` or `orders`. | Decline and state that customer satisfaction scores are not tracked in the dataset. |
"""
    return md


def build_hr_ground_truth_md(data: dict[str, pd.DataFrame], gt: dict[str, Any]) -> str:
    """Construct markdown content for hr/GROUND_TRUTH.md."""
    depts = data["departments"]
    emps = data["employees"]
    salaries = data["salaries"]
    perf = data["performance"]

    # Pre-render tables
    q2_table = df_to_markdown(gt["q2"])
    q4_table = df_to_markdown(gt["q4"])
    q5_table = df_to_markdown(gt["q5"])
    q6_table = df_to_markdown(gt["q6"])
    q9_table = df_to_markdown(gt["q9"])
    q11_table = df_to_markdown(gt["q11"])
    q16_table = df_to_markdown(gt["q16"])
    q17_df = emps.merge(depts, on="department_id").query("employment_status == 'Exited'").groupby("department_name").size().reset_index(name="exited_count").sort_values("exited_count", ascending=False)
    q17_table = df_to_markdown(q17_df)
    fu4_table = df_to_markdown(gt["fu4"])

    mermaid_block = "```mermaid\nflowchart TD\n    DEPARTMENTS[\"departments\"] -->|department_id| EMPLOYEES[\"employees\"]\n    EMPLOYEES[\"employees\"] -->|employee_id| SALARIES[\"salaries\"]\n    EMPLOYEES[\"employees\"] -->|employee_id| PERFORMANCE[\"performance\"]\n```"

    md = f"""# HR Test Pack — Ground Truth & Specification

## 1. Overview & Seed Details
- **Random Seed**: Deterministic seed `101`
- **Time Span**: Hires from `2021-03-01` through `2026-03-15`. Salary effective dates from `2021-03-01` through `2026-01-01`. Performance reviews in `2024-12-15` and `2025-12-15`.
- **Deliberate Omission**: No `attrition_reason` or `termination_reason` column exists. The system must not invent reasons for departure.

## 2. Table Profiles & Row Counts

| Table Name | File Format | Row Count | Column Count | Primary Key | Foreign Keys |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `departments` | CSV | {len(depts)} | {len(depts.columns)} | `department_id` | None |
| `employees` | CSV | {len(emps)} | {len(emps.columns)} | `employee_id` | `department_id` -> `departments.department_id` |
| `salaries` | Excel (`.xlsx`) | {len(salaries)} | {len(salaries.columns)} | Composite (`employee_id`, `effective_date`) | `employee_id` -> `employees.employee_id` |
| `performance` | CSV | {len(perf)} | {len(perf.columns)} | Composite (`employee_id`, `review_date`) | `employee_id` -> `employees.employee_id` |

### Key Columns
- **departments**: `department_id`, `department_name` (Engineering, Sales, Marketing, Finance, Operations, HR, Customer Success), `location`, `cost_center`.
- **employees**: `employee_id`, `employee_name`, `department_id`, `job_level` (L1, L2, L3, L4, L5), `location`, `hire_date`, `employment_status` (Active [38], Exited [8], On Leave [4]).
- **salaries**: `employee_id`, `effective_date`, `base_salary`, `bonus`, `salary_band` (Band-A to Band-E). Multiple historical records per employee.
- **performance**: `employee_id`, `review_date`, `performance_score` (float 2.80 to 5.00), `rating` (Exceeds Expectations, Meets Expectations, Needs Improvement), `promotion_flag` (boolean).

## 3. Relational Architecture
{mermaid_block}

## 4. Calculated Ground Truth for HR QA Questions

### Question 1: How many active employees do we have?
- **Expected Answer**: **{gt['q1']}** active employees
- **Relevant Tables**: `employees`
- **Expected Visualization Type**: `none` (or `kpi` / `scalar`)
- **Query Verification**: `SELECT COUNT(*) FROM employees WHERE employment_status = 'Active'`

### Question 2: What is the average salary by department?
*(Using latest effective salary per employee)*
- **Expected Answer**:
{q2_table}
- **Relevant Tables**: `employees`, `departments`, `salaries`
- **Expected Visualization Type**: `bar`

### Question 3: Which department has the highest average salary?
- **Expected Answer**: **{gt['q3'][0]}** with an average salary of **${gt['q3'][1]:,.2f}**
- **Relevant Tables**: `employees`, `departments`, `salaries`
- **Expected Visualization Type**: `none` (or `kpi` / `bar`)

### Question 4: What is the total salary expense by department?
- **Expected Answer**:
{q4_table}
- **Relevant Tables**: `employees`, `departments`, `salaries`
- **Expected Visualization Type**: `bar`

### Question 5: Show employee count by location.
- **Expected Answer**:
{q5_table}
- **Relevant Tables**: `employees`
- **Expected Visualization Type**: `bar`

### Question 6: Show monthly salary expense over time.
*(Aggregated total base salary effective in each recorded month)*
- **Expected Answer**:
{q6_table}
- **Relevant Tables**: `salaries`
- **Expected Visualization Type**: `line` (or `bar`)

### Question 7: What is the average salary for Engineering?
- **Expected Answer**: **${gt['q7']:,.2f}**
- **Relevant Tables**: `employees`, `departments`, `salaries`
- **Expected Visualization Type**: `none` (or `kpi` / `scalar`)

### Question 8: How many L3 employees are there?
- **Expected Answer**: **{gt['q8']}** employees
- **Relevant Tables**: `employees`
- **Expected Visualization Type**: `none` (or `kpi` / `scalar`)

### Question 9: What is the average performance score by department?
- **Expected Answer**:
{q9_table}
- **Relevant Tables**: `employees`, `departments`, `performance`
- **Expected Visualization Type**: `bar`

### Question 10: Which department has the highest average performance score?
- **Expected Answer**: **{gt['q10'][0]}** with an average score of **{gt['q10'][1]:.2f}**
- **Relevant Tables**: `employees`, `departments`, `performance`
- **Expected Visualization Type**: `none` (or `kpi` / `bar`)

### Question 11: Show the relationship between job level and average salary.
- **Expected Answer**:
{q11_table}
- **Relevant Tables**: `employees`, `salaries`
- **Expected Visualization Type**: `bar` (or `scatter`)

### Question 12: What was the average salary in 2025?
- **Expected Answer**: **${gt['q12']:,.2f}** (salaries effective in calendar year 2025)
- **Relevant Tables**: `salaries`
- **Expected Visualization Type**: `none` (or `kpi` / `scalar`)

### Question 13: What about 2026?
- **Expected Answer**: **${gt['q13']:,.2f}** (salaries effective in calendar year 2026)
- **Relevant Tables**: `salaries`
- **Expected Visualization Type**: `none` (or `kpi` / `scalar`)

### Question 14: What is the average salary of active Engineering employees?
- **Expected Answer**: **${gt['q14']:,.2f}**
- **Relevant Tables**: `employees`, `departments`, `salaries`
- **Expected Visualization Type**: `none` (or `kpi` / `scalar`)

### Question 15: What about L3 Engineering employees?
- **Expected Answer**: **${gt['q15']:,.2f}**
- **Relevant Tables**: `employees`, `departments`, `salaries`
- **Expected Visualization Type**: `none` (or `kpi` / `scalar`)

### Question 16: Show salary trends for Engineering.
- **Expected Answer**:
{q16_table}
- **Relevant Tables**: `employees`, `departments`, `salaries`
- **Expected Visualization Type**: `line`

### Question 17: Which department has the largest number of exited employees?
- **Expected Answer**: **{gt['q17'][0]}** ({gt['q17'][1]} exited employees)
- **Breakdown**:
{q17_table}
- **Relevant Tables**: `employees`, `departments`
- **Expected Visualization Type**: `bar` (or `scalar`)

### Question 18: What was the average salary before the most recent salary change?
- **Expected Answer**: **${gt['q18']:,.2f}** (computed from the 2nd most recent salary record per employee)
- **Relevant Tables**: `salaries`
- **Expected Visualization Type**: `none` (or `kpi` / `scalar`)

---

## 5. Conversational Follow-Up Sequence Test

The system must support the following consecutive multi-turn dialogue with state preservation:

1. **User**: *"What is the average salary by department?"*
   - **State Updated**: `metric="salary"`, `grouping="department"`.
   - **Result**: Department breakdown table / bar chart (Q2).
2. **User**: *"What about Engineering?"*
   - **State Updated**: Preserves metric `salary`, adds filter `department="Engineering"`.
   - **Result**: Scalar value **${gt['q7']:,.2f}** (Q7).
3. **User**: *"What about L3?"*
   - **State Updated**: Preserves `salary`, `department="Engineering"`, adds filter `job_level="L3"`.
   - **Result**: Scalar value **${gt['q15']:,.2f}** (Q15).
4. **User**: *"Show that over time."*
   - **State Updated**: Preserves `salary`, `department="Engineering"`, `job_level="L3"`, changes grouping to `effective_date` / time.
   - **Result**: Time series line chart:
{fu4_table}

---

## 6. Expected Behavior for Negative / Missing-Data Questions

The datasets intentionally do NOT contain attrition reasons, employee satisfaction surveys, or attendance / leave records. The application MUST return `cannot_answer` without hallucinating:

| Question Number | Question Text | Missing Information | Expected System Behavior |
| :--- | :--- | :--- | :--- |
| **Q19** | *Why did employees leave?* | No `attrition_reason` or exit survey column exists in `employees` or `departments`. | Inform user that reason for departure is not tracked in the dataset. |
| **Q20** | *What are the most common resignation reasons?* | No resignation categories or exit feedback columns exist. | Decline with message stating resignation reasons are not present. |
| **Q21** | *What is employee satisfaction?* | No pulse survey, eNPS, or satisfaction score fields exist. | Decline with notice that satisfaction scores are not available. |
| **Q22** | *What is the average number of sick days?* | No time-off, PTO, or sick leave records exist. | Decline with notice that sick days and leave metrics are not recorded. |
"""
    return md


def build_messy_notes_md(df: pd.DataFrame) -> str:
    """Construct markdown documentation for messy/MESSY_DATA_NOTES.md."""
    table_preview = df_to_markdown(df)
    return f"""# Messy Data Test Case — Specification & Ingestion Notes

## Purpose
`messy_sales.csv` tests the resilience and cleaning capabilities of the ingestion and schema profiling layer when dealing with realistic, imperfect business spreadsheets.

## File Summary
- **File**: `test_data/messy/messy_sales.csv`
- **Rows**: {len(df)}
- **Columns**: {len(df.columns)}

## Intentional Imperfections & Validation Criteria

| Imperfection Category | Specific Manifestation in Dataset | Expected App Handling |
| :--- | :--- | :--- |
| **1. Column Names with Whitespace** | `' Customer Name '` has leading and trailing spaces | Normalizer should strip leading/trailing whitespace into `'Customer Name'` or sanitized identifier `'customer_name'`. |
| **2. Mixed Capitalization in Column Headers** | `'Order ID'`, `'REGION'`, `'Sales Amount'`, `'UNITS'` | Schema profiler should normalize headers deterministically to lowercase snake_case (e.g. `order_id`, `region`, `sales_amount`, `units`). |
| **3. Currency-Formatted Numeric Column** | `'Sales Amount'` contains values formatted as `"$1,250.00"`, `"$450.50"` with dollar signs and commas | Should either ingest as string and allow DuckDB string casting (e.g. `CAST(REPLACE(REPLACE(sales_amount, '$', ''), ',', '') AS DOUBLE)`), or automatically coerce cleaned numeric data. |
| **4. Non-ISO Date Formats** | `'Order Date'` contains dates in `MM/DD/YYYY` format (`"03/15/2025"`, `"11/22/2025"`) | Parser and DuckDB should parse via `STRPTIME("Order Date", '%m/%d/%Y')` or `TRY_CAST`. |
| **5. Missing / Null Values** | `'Delivery Note'` contains several explicit empty/null values (`None`) | Column profiler accurately calculates `null_percentage` without throwing exceptions or corrupting row counts. |
| **6. Inconsistent Categorical Capitalization** | `'REGION'` contains `'South'`, `'south'`, and `'SOUTH'` across different rows | When grouping or filtering by region, queries should handle case insensitivity via `LOWER(region) = 'south'` or ILIKE. |
| **7. Duplicate-Looking Identifier** | `'ORD-910'` appears twice (for `"Kappa Global"` and `"Kappa Global Part 2"`) | Profiler detects non-unique cardinality for `order_id` (cardinality 10 out of 11 rows). Does not crash primary key assumptions. |

## Dataset Preview
{table_preview}
"""


def write_all_files():
    """Generate all files, calculate ground truths, and compile documentation."""
    RETAIL_DIR.mkdir(parents=True, exist_ok=True)
    HR_DIR.mkdir(parents=True, exist_ok=True)
    MESSY_DIR.mkdir(parents=True, exist_ok=True)

    print("Generating Retail data...")
    retail_data = generate_retail_data(seed=42)
    for name, df in retail_data.items():
        csv_path = RETAIL_DIR / f"{name}.csv"
        df.to_csv(csv_path, index=False)
        print(f"  Wrote {csv_path.name}: {len(df)} rows, {len(df.columns)} cols")

    print("Computing Retail ground truth...")
    retail_gt = compute_retail_ground_truth(retail_data)

    print("Generating HR data...")
    hr_data = generate_hr_data(seed=101)
    hr_data["departments"].to_csv(HR_DIR / "departments.csv", index=False)
    hr_data["employees"].to_csv(HR_DIR / "employees.csv", index=False)
    hr_data["performance"].to_csv(HR_DIR / "performance.csv", index=False)
    xlsx_path = HR_DIR / "salaries.xlsx"
    hr_data["salaries"].to_excel(xlsx_path, index=False, engine="openpyxl")
    print(f"  Wrote departments.csv: {len(hr_data['departments'])} rows")
    print(f"  Wrote employees.csv: {len(hr_data['employees'])} rows")
    print(f"  Wrote salaries.xlsx: {len(hr_data['salaries'])} rows")
    print(f"  Wrote performance.csv: {len(hr_data['performance'])} rows")

    print("Computing HR ground truth...")
    hr_gt = compute_hr_ground_truth(hr_data)

    print("Generating Messy data...")
    messy_df = generate_messy_data(seed=777)
    messy_path = MESSY_DIR / "messy_sales.csv"
    messy_df.to_csv(messy_path, index=False)
    print(f"  Wrote messy_sales.csv: {len(messy_df)} rows")

    # Build Retail GROUND_TRUTH.md
    print("Writing Retail GROUND_TRUTH.md...")
    retail_md = build_retail_ground_truth_md(retail_data, retail_gt)
    (RETAIL_DIR / "GROUND_TRUTH.md").write_text(retail_md, encoding="utf-8")

    # Build HR GROUND_TRUTH.md
    print("Writing HR GROUND_TRUTH.md...")
    hr_md = build_hr_ground_truth_md(hr_data, hr_gt)
    (HR_DIR / "GROUND_TRUTH.md").write_text(hr_md, encoding="utf-8")

    # Build MESSY_DATA_NOTES.md
    print("Writing MESSY_DATA_NOTES.md...")
    messy_md = build_messy_notes_md(messy_df)
    (MESSY_DIR / "MESSY_DATA_NOTES.md").write_text(messy_md, encoding="utf-8")

    print("All test data generation complete.")


if __name__ == "__main__":
    write_all_files()
