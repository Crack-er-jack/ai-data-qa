# Messy Data Test Case — Specification & Ingestion Notes

## Purpose
`messy_sales.csv` tests the resilience and cleaning capabilities of the ingestion and schema profiling layer when dealing with realistic, imperfect business spreadsheets.

## File Summary
- **File**: `test_data/messy/messy_sales.csv`
- **Rows**: 11
- **Columns**: 7

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
| Order ID |  Customer Name  | REGION | Sales Amount | Order Date | UNITS | Delivery Note |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| ORD-901 | Acme Corp | South | $1,250.00 | 03/15/2025 | 5 | Fragile |
| ORD-902 | Beta LLC | south | $450.50 | 04/02/2025 | 2 |  |
| ORD-903 | Gamma Inc | SOUTH | $3,100.00 | 05/18/2025 | 12 | Loading dock B |
| ORD-904 | Delta Co | North | $820.75 | 06/21/2025 | 3 | Call on arrival |
| ORD-905 | Epsilon Ltd | north | $2,400.00 | 07/11/2025 | 8 |  |
| ORD-906 | Zeta Partners | East | $990.00 | 08/09/2025 | 4 | Express |
| ORD-907 | Eta Solutions | EAST | $1,750.25 | 09/14/2025 | 6 |  |
| ORD-908 | Theta Tech | West | $5,600.00 | 10/05/2025 | 20 | Signature required |
| ORD-909 | Iota Systems | west | $340.00 | 11/22/2025 | 1 |  |
| ORD-910 | Kappa Global | South | $2,150.00 | 12/03/2025 | 7 | Gate code 4490 |
| ORD-910 | Kappa Global Part 2 | South | $850.00 | 12/04/2025 | 3 | Backorder shipment |
