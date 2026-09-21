# AI Data Q&A

A Streamlit web application for business users to upload arbitrary CSV/Excel datasets and ask analytical questions in natural language.

> **Core Architectural Principle:**  
> *"The LLM interprets and plans; DuckDB is the sole source of truth for numerical computation."*  
> Numbers, rankings, and totals are never fabricated by the model. GPT-OSS 20B (via Groq) interprets user intent and generates DuckDB-compatible SQL. DuckDB computes the numbers directly against the uploaded tables. The application validates SQL safety, bounds output sizes, and renders answers, KPI metric cards, data tables, and Plotly visualizations.

---

## Tech Stack

| Layer | Technology | Version | Purpose & Rationale |
| :--- | :--- | :--- | :--- |
| **Frontend / UI** | [Streamlit](https://streamlit.io/) | `>=1.32.0` | Rapid, interactive web interface with sidebar dataset preview, responsive metric cards, expandable SQL audit transparency, and dark/light mode compatibility. |
| **Analytical Engine** | [DuckDB](https://duckdb.org/) | `>=1.1.0` | In-process columnar analytical database. Zero-latency SQL execution directly on Pandas DataFrames without external database infrastructure. |
| **Data Ingestion** | [Pandas](https://pandas.pydata.org/) | `>=2.1.0` | Robust tabular parsing, schema inspection, cell sanitization, and data normalization for CSV and Excel files. |
| **Excel Support** | [openpyxl](https://openpyxl.readthedocs.io/), [xlrd](https://xlrd.readthedocs.io/) | `>=3.1.0`, `>=2.0.1` | Support for `.xlsx` and legacy `.xls` workbooks with multi-sheet detection. |
| **LLM Inference** | [Groq Python SDK](https://github.com/groq/groq-python) | `>=0.9.0` | Ultra-fast JSON planning using `openai/gpt-oss-20b` (or configurable alternatives) with strictly enforced JSON schemas. |
| **Visualizations** | [Plotly](https://plotly.com/python/) | `>=5.18.0` | Interactive charts (bar charts, time-series lines, distributions) selected deterministically based on result shapes. |
| **Configuration** | [pydantic-settings](https://docs.pydantic.dev/), [python-dotenv](https://github.com/theskumar/python-dotenv) | `>=2.6.0`, `>=1.0.0` | Type-safe environment variable parsing with validation and `.env` fallback. |
| **Testing** | [pytest](https://pytest.org/) | `>=8.0.0` | Comprehensive regression test suite covering ingestion, SQL safety, context retention, DuckDB execution, and fidelity. |

> **What We Explicitly Avoid:** No LangChain, no heavy agent frameworks, no vector databases, no arbitrary Python `eval`/`exec`, and no external database servers.

---

## System Architecture

```
User Question (Natural Language)
  │
  ├── 1. Discoverability & Metadata Check
  │      └── Directly answers "What tables are loaded?", "Describe schema", etc. without LLM SQL
  │
  ├── 2. Context Builder
  │      ├── Compact Dataset Profiles (column names, types, value samples, min/max dates)
  │      ├── Inferred Join Candidates (cross-table key matching)
  │      ├── Analytical State (previous filters, metrics, time periods, clarifications)
  │      └── Ground-Truth Temporal Context (exact date bounds derived from dataset)
  │
  ├── 3. LLM Planning (Groq)
  │      └── Structured JSON: Intent, SQL query, explanation, expected shape, viz hint
  │
  ├── 4. SQL Normalization & Safety Audit
  │      ├── AST validation (read-only SELECT/WITH statements, no DDL/DML or file scans)
  │      ├── Date function normalization (automatic TRY_CAST on string dates for DuckDB)
  │      ├── Fidelity audit (verifies filters, categories, and date constraints match plan)
  │      └── Auto-correction retry loop if syntax or fidelity validation fails
  │
  ├── 5. Deterministic DuckDB Execution
  │      └── Bounded execution (enforces MAX_RESULT_ROWS and cell truncation)
  │
  └── 6. Result Layer & UI Presentation
         ├── Metric Cards & Entity Labels (e.g. Segment: Consumer, Revenue: $37,218.25)
         ├── Plotly Chart (if time-series or multi-category comparison)
         ├── Interactive Data Table Preview
         └── "How was this calculated?" Expander (tables used, active filters, exact SQL)
```

---

## Prerequisites

- **Python 3.10 to 3.12** installed on your system.
- A free **[Groq API Key](https://console.groq.com/)** to enable natural language planning.

---

## Local Setup

### 1. Clone or Open the Repository

```bash
git clone https://github.com/your-org/Darwinbox_FDE.git
cd Darwinbox_FDE
```

### 2. Create and Activate a Virtual Environment

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Copy the template file to `.env`:

**Windows:**
```powershell
copy .env.example .env
```

**macOS / Linux:**
```bash
cp .env.example .env
```

Open `.env` in any text editor and provide your Groq API key:
```ini
GROQ_API_KEY=gsk_your_actual_groq_api_key_here
```

---

## Environment Variables & Configuration

All execution bounds and model settings have safe defaults built-in. You only need to set `GROQ_API_KEY` unless you wish to customize runtime behavior:

| Variable | Required | Default | Description |
| :--- | :---: | :---: | :--- |
| `GROQ_API_KEY` | **Yes** | — | Groq Cloud API key for natural language planning. |
| `LLM_PROVIDER` | No | `groq` | LLM backend provider id (`groq`). |
| `LLM_MODEL` | No | `openai/gpt-oss-20b` | Model identifier on Groq (fast, high-fidelity planning). |
| `LLM_TEMPERATURE` | No | `0.0` | Sampling temperature (`0.0` ensures deterministic SQL plans). |
| `MAX_FILE_SIZE_MB` | No | `10` | Maximum allowed size per uploaded file in megabytes. |
| `MAX_SESSION_SIZE_MB`| No | `50` | Maximum cumulative upload size per browser session in megabytes. |
| `MAX_RESULT_ROWS` | No | `200` | Maximum rows fetched from DuckDB and displayed in the UI. |
| `MAX_LLM_RESULT_ROWS` | No | `50` | Maximum sample rows passed back to the LLM during repair loops. |
| `MAX_SQL_CORRECTION_RETRIES` | No | `1` | Number of automatic repair attempts if DuckDB execution errors. |
| `MAX_ANALYTICAL_QUERIES` | No | `3` | Maximum SQL statements allowed per user turn. |

---

## Running the Application

Launch the Streamlit app:

```bash
streamlit run app.py
```

Streamlit will print the local server URL (typically `http://localhost:8501`). Open it in your web browser.

---

## How to Use the App

1. **Load Data**:
   - In the sidebar, click **"Upload CSV or Excel files"** to load your own datasets, **OR**
   - Click **"Load demo datasets"** to immediately load sample retail data (`customers.csv`, `orders.csv`, `products.csv`).
2. **Inspect Session Datasets**:
   - Expand the dataset previews in the sidebar to review column names, inferred data types, and first 5 rows.
   - Review detected candidate cross-table relationships (e.g. `orders.customer_id` → `customers.customer_id`).
3. **Ask Questions**:
   - Type a question into the prompt input or click one of the suggested query cards under **"💡 Try asking"**.
4. **Follow-Up Questions**:
   - Ask elliptical follow-ups like *"What about South?"*, *"And in 2026?"*, or *"Break that down by month"*. The agent preserves prior metrics, filters, and tables without needing full conversation transcripts.
5. **Inspect Execution Details**:
   - Open **"How was this calculated?"** beneath any answer to inspect the exact tables used, active WHERE constraints, and executed SQL query.
6. **Reset Session**:
   - Click **"Reset session"** in the sidebar at any time to clear loaded files and analysis history.

---

## Example Questions (Demo Data)

- **Total Metrics**: *"What is the total revenue?"* *(automatically filters `status = 'completed'`)*
- **Entity Ranking**: *"Which customer segment generated the most revenue from Hardware products?"*
- **Cross-Table Joins**: *"Which region generated the most revenue?"*
- **Elliptical Follow-ups**: *"What about South?"* followed by *"And for Hardware?"*
- **Time-Series Trends**: *"Show me monthly revenue over time."*
- **Multi-Category Comparison**: *"Compare revenue across regions."*
- **Dataset Discovery**: *"What datasets are loaded?"* or *"What columns are available?"*

---

## Running Tests

Run the full automated test suite using `pytest`:

```bash
pytest
```

To run tests with detailed output:
```bash
pytest -v
```

The test suite covers:
- Ingestion pipelines, upload sanitization, and size caps.
- Profiling engines, datetime detection, and join candidate heuristics.
- Context building and temporal bounds resolution.
- SQL security validation (rejecting DDL, DML, file scans, multiple statements).
- DuckDB date casting (`strftime`, `TRY_CAST`) and bounded execution.
- Context retention across follow-ups and clarification flows.
- Result classification, entity/scalar preservation, and visualization builders.

---

## Deployment (Streamlit Community Cloud)

1. Push your repository to GitHub.
2. Visit [share.streamlit.io](https://share.streamlit.io) and select your repository.
3. Set the **Main file path** to `app.py`.
4. In **Advanced Settings → Secrets**, provide your API key:
   ```toml
   GROQ_API_KEY = "gsk_your_groq_api_key"
   ```
5. Click **Deploy**. Streamlit Cloud will automatically install dependencies from `requirements.txt`.
