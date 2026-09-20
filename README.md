# AI Data Q&A

A Streamlit app for non-technical users to upload CSV/Excel files and ask analytical questions in natural language.
A Streamlit web application for non-technical business users to upload CSV/Excel files and ask analytical questions in natural language.

Numbers are never invented by the model. GPT-OSS 20B via Groq interprets the question and proposes SQL. DuckDB executes read-only SQL against the uploaded tables. The application validates SQL, bounds results, and renders answers/charts.
> **Core Architectural Principle:**  
> *"LLM interprets and plans; DuckDB is the source of truth for computation."*  
> Numbers are never invented by the model. GPT-OSS 20B via Groq interprets user intent and generates read-only SQL. DuckDB executes the queries deterministically against uploaded datasets. The application validates SQL safety, bounds output sizes, and renders answers and Plotly charts.

## Problem

Business users can describe the question they care about, but they should not have to write joins, remember column names, or trust a chatbot that guesses totals. Spreadsheet tools also break down once analysis spans several files.

## Solution

1. User uploads one or more CSV/Excel files in a session (more files can be added later without restarting).
2. Files are ingested with Pandas, given safe table names, profiled, and registered in DuckDB.
3. Lightweight heuristics propose join candidates (`customer_id`, `product_id`, overlap, types).
4. For each question, a compact context packet (schema, relationships, structured follow-up state) is sent to the LLM — not the raw data.
5. The LLM returns a structured plan with SQL. The app validates it, runs it in DuckDB (one correction retry), and formats DuckDB results for the UI.

## Architecture

```
User question
  → Context builder (schema + candidates + analytical state)
  → LLM plan (SQL + visualization hint + explanation)
  → query_data(sql)  [validate → DuckDB → bounded rows]
  → Result layer + Plotly (compatibility-checked)
  → Answer + optional “How was this calculated?”
```

The Phase 2 diagram lives in `docs/architecture.md`.

## Stack

| Layer | Choice |
| --- | --- |
| UI | Streamlit |
| Ingestion | Pandas |
| Analytics | DuckDB |
| LLM | Groq `openai/gpt-oss-20b` |
| Charts | Plotly |
| Session | `st.session_state` |
| Config | `.env` / Streamlit secrets |

Not used: LangChain, agents frameworks, vector DBs, RAG, arbitrary Python execution.

## Local setup

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env   # or: cp .env.example .env
```

Put a Groq API key in `.env`. Demo CSVs are already under `demo_data/`. To regenerate them:

```bash
python -m src.demo.generate_demo
```

## Environment variables / secrets

| Name | Required | Default | Purpose |
| --- | --- | --- | --- |
| `GROQ_API_KEY` | Yes, to ask questions | — | Groq API key |
| `LLM_PROVIDER` | No | `groq` | Provider id |
| `LLM_MODEL` | No | `openai/gpt-oss-20b` | Groq model |
| `LLM_TEMPERATURE` | No | `0` | Planning temperature |
| `MAX_FILE_SIZE_MB` | No | `10` | Per-file upload cap |
| `MAX_SESSION_SIZE_MB` | No | `50` | Total upload cap per session |
| `MAX_RESULT_ROWS` | No | `200` | UI result cap |
| `MAX_LLM_RESULT_ROWS` | No | `50` | Preview rows if a repair call needs them |
| `MAX_SQL_CORRECTION_RETRIES` | No | `1` | Failed SQL repair attempts |
| `MAX_ANALYTICAL_QUERIES` | No | `3` | SQL statements per user question |

On Streamlit Community Cloud, set the same keys in **App settings → Secrets**.

## How to run

```bash
streamlit run app.py
```

Open the local URL Streamlit prints (usually `http://localhost:8501`).

## How to use

1. In the sidebar, upload CSV/XLSX files **or** click **Load demo datasets**.
2. Confirm tables, row counts, and any candidate relationships.
3. Ask a question. Follow-ups reuse structured state (metric, filters, period), not the full chat transcript.
4. Add another file in the same session and keep asking.
5. Open **How was this calculated?** to inspect tables, filters, and SQL.
6. **Reset session** clears uploads and analysis state.

Limits are shown in the sidebar: 10 MB per file, 50 MB per session (configurable).

## Example questions (demo data)

The demo is a small commerce model: `customers` ↔ `orders` ↔ `products`, with `line_total` on each order line.

- What was our total revenue last quarter?
- Which region generated the most revenue?
- What about South?
- Compare revenue across regions.
- Show me the monthly revenue trend.
- Give me total revenue, average order value, and revenue by region.
- Which product category sold the most?

Completed orders contribute `line_total`; refunded rows are zeroed so filters on `status` matter.

## Testing

```bash
pytest
```

Coverage is focused on: file validation, table names, profiling, relationship heuristics, SQL safety, DuckDB execution, result limits, visualization choice, follow-up state, and one end-to-end path over the demo CSVs (scripted planner, so tests do not call Groq).

## Deployment notes (Streamlit Community Cloud)

1. Push this repo to GitHub (include `app.py` and `requirements.txt` at the repo root).
2. At [share.streamlit.io](https://share.streamlit.io), create an app from the repo, main file `app.py`.
3. Add secrets:

```toml
GROQ_API_KEY = "..."
LLM_PROVIDER = "groq"
LLM_MODEL = "openai/gpt-oss-20b"
```

4. Deploy. Community Cloud will `pip install -r requirements.txt`.
5. Upload size is still enforced in-app; Streamlit Cloud also has its own request limits.

Do not commit `.env` or `.streamlit/secrets.toml`.

## Design decisions

- **SQL is the tool, not a custom DSL.** The only analytical interface is `query_data(sql)`.
- **Structured state instead of full transcripts.** Follow-ups like “What about South?” update filters while keeping the previous metric.
- **Bounded loop.** At most three SQL executions per question and one repair attempt. No autonomous tool-calling agent.
- **Hybrid answers.** DuckDB supplies values; the LLM may add a short explanation from the same planning call. No extra rewrite call.
- **Visualization is checked in the backend.** A suggested bar chart on a single KPI is replaced with a KPI/metric display.

## Known limitations

- Column validation is practical, not a full SQL parser. DuckDB still rejects unknown objects at execution time.
- Join discovery is heuristic. Unusual keys may need a clearer question.
- Excel workbooks with many sheets become multiple tables; very messy headers may need cleaning before upload.
- “Last quarter” depends on the LLM’s date interpretation plus the dates present in the file.
- Large text cells are clipped; result sets are truncated.
- The Groq model can still propose incorrect SQL; the retry budget is one attempt, then the UI explains the failure.

## Future improvements

- Persist sessions beyond a browser tab.
- Stronger date-period helpers (explicit fiscal calendars).
- Optional saved questions / exported SQL.
- Richer semantic types (currency, geo) in the profiler.
- User-confirmed joins when heuristics are weak.
