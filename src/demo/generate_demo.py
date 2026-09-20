"""Generate coherent demo CSVs for the AI Data Q&A app."""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "demo_data"


CUSTOMERS = [
    ("C001", "Apex Retail", "South", "Enterprise", "Austin", "2023-11-02"),
    ("C002", "Northwind Markets", "North", "Enterprise", "Chicago", "2024-01-18"),
    ("C003", "Harbor Boutique", "East", "SMB", "Boston", "2024-02-09"),
    ("C004", "Cascade Goods", "West", "SMB", "Seattle", "2024-03-14"),
    ("C005", "Sunbelt Supply", "South", "SMB", "Atlanta", "2024-04-01"),
    ("C006", "Lakeside Consumer", "North", "Consumer", "Minneapolis", "2024-04-22"),
    ("C007", "Metro Home", "East", "Consumer", "New York", "2024-05-11"),
    ("C008", "Pacific Outfitters", "West", "Enterprise", "San Francisco", "2024-06-03"),
    ("C009", "Gulf Coast Traders", "South", "Enterprise", "Houston", "2024-06-28"),
    ("C010", "Prairie Wholesale", "North", "SMB", "Omaha", "2024-07-19"),
    ("C011", "Capitol Office", "East", "Enterprise", "Washington", "2024-08-08"),
    ("C012", "Desert Direct", "West", "Consumer", "Phoenix", "2024-09-02"),
    ("C013", "Bayou Basics", "South", "Consumer", "New Orleans", "2024-09-25"),
    ("C014", "Great Lakes Co", "North", "Enterprise", "Detroit", "2024-10-16"),
    ("C015", "Atlantic Clinic", "East", "SMB", "Philadelphia", "2024-11-05"),
    ("C016", "Sierra Partners", "West", "SMB", "Denver", "2024-11-27"),
    ("C017", "Peachtree Stores", "South", "SMB", "Nashville", "2025-01-09"),
    ("C018", "Frontier Mart", "North", "Consumer", "Fargo", "2025-02-01"),
    ("C019", "Liberty Gadgets", "East", "Consumer", "Newark", "2025-02-20"),
    ("C020", "Redwood Labs", "West", "Enterprise", "Portland", "2025-03-12"),
    ("C021", "Coastal Kitchen", "South", "Consumer", "Tampa", "2025-04-04"),
    ("C022", "Iron Range Supply", "North", "SMB", "Milwaukee", "2025-05-15"),
    ("C023", "Hudson Digital", "East", "Enterprise", "Brooklyn", "2025-06-07"),
    ("C024", "Olympia Health", "West", "Enterprise", "Los Angeles", "2025-07-21"),
]

PRODUCTS = [
    ("P001", "Analytics Pro", "Software", 1299.00),
    ("P002", "Analytics Starter", "Software", 349.00),
    ("P003", "Warehouse Scanner", "Hardware", 499.00),
    ("P004", "POS Terminal", "Hardware", 899.00),
    ("P005", "Support Plus", "Services", 199.00),
    ("P006", "Implementation Pack", "Services", 2499.00),
    ("P007", "Training Day", "Services", 799.00),
    ("P008", "Mobile Add-on", "Software", 149.00),
    ("P009", "Label Printer", "Hardware", 229.00),
    ("P010", "Premium Warranty", "Services", 129.00),
    ("P011", "Dashboard Suite", "Software", 649.00),
    ("P012", "Inventory Sensor", "Hardware", 179.00),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    _write_csv(
        OUT / "customers.csv",
        ["customer_id", "customer_name", "region", "segment", "city", "signup_date"],
        CUSTOMERS,
    )
    _write_csv(
        OUT / "products.csv",
        ["product_id", "product_name", "category", "unit_price"],
        PRODUCTS,
    )
    orders = _build_orders()
    _write_csv(
        OUT / "orders.csv",
        [
            "order_id",
            "customer_id",
            "product_id",
            "order_date",
            "quantity",
            "unit_price",
            "discount",
            "line_total",
            "status",
        ],
        orders,
    )
    print(f"Wrote {len(CUSTOMERS)} customers, {len(PRODUCTS)} products, {len(orders)} orders to {OUT}")


def _build_orders() -> list[tuple]:
    rng = random.Random(42)
    start = date(2025, 1, 6)
    end = date(2026, 9, 18)
    product_map = {row[0]: row for row in PRODUCTS}
    rows = []
    current = start
    order_n = 1
    while current <= end:
        # More volume mid-week and in later months.
        daily = 1 + int(current.month in {3, 6, 9, 11})
        if current.weekday() >= 5:
            daily = max(1, daily - 1)
        for _ in range(daily):
            customer = rng.choice(CUSTOMERS)
            product = rng.choice(PRODUCTS)
            quantity = rng.choice([1, 1, 1, 2, 2, 3, 4, 5])
            discount = rng.choice([0.0, 0.0, 0.0, 0.05, 0.10, 0.15])
            unit_price = float(product[3])
            line_total = round(quantity * unit_price * (1 - discount), 2)
            status = rng.choice(["completed", "completed", "completed", "completed", "refunded"])
            if status == "refunded":
                line_total = 0.0
            rows.append(
                (
                    f"O{order_n:04d}",
                    customer[0],
                    product[0],
                    current.isoformat(),
                    quantity,
                    unit_price,
                    discount,
                    line_total,
                    status,
                )
            )
            order_n += 1
        current += timedelta(days=rng.choice([1, 1, 2, 3]))
        _ = product_map
    return rows


def _write_csv(path: Path, headers: list[str], rows: list[tuple]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


if __name__ == "__main__":
    main()
