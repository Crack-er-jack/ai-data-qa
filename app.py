"""Streamlit UI for AI Data Q&A."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.agent import run_analysis
from src.constants import MAX_FILE_SIZE_MB, MAX_SESSION_SIZE_MB, SUPPORTED_EXTENSIONS
from src.errors import AppError
from src.ingestion.loader import parse_upload
from src.ingestion.registry import create_connection, dataset_from_parsed
from src.session import add_datasets, empty_session, load_from_streamlit, persist_to_streamlit
from src.settings import get_settings

DEMO_DIR = Path(__file__).parent / "demo_data"
ROOT = Path(__file__).parent


def main() -> None:
    st.set_page_config(page_title="AI Data Q&A", page_icon="📊", layout="wide")
    _inject_styles()
    session = load_from_streamlit(st.session_state)

    st.title("AI Data Q&A")
    st.caption("Ask questions across your CSV and Excel data.")

    with st.sidebar:
        session = _render_sidebar(session)

    persist_to_streamlit(st.session_state, session)

    if not session.datasets:
        _empty_state()
        return

    _dataset_summary(session)
    _question_area(session)


def _render_sidebar(session):
    st.header("Data")
    st.write(
        f"Per-file limit: **{MAX_FILE_SIZE_MB} MB**  \n"
        f"Session limit: **{MAX_SESSION_SIZE_MB} MB**  \n"
        f"Used this session: **{session.session_bytes / (1024 * 1024):.2f} MB**"
    )
    uploads = st.file_uploader(
        "Upload CSV or Excel files",
        type=[ext.lstrip(".") for ext in sorted(SUPPORTED_EXTENSIONS)],
        accept_multiple_files=True,
        help="You can add more files later in this same session.",
    )
    if uploads:
        if st.button("Add to session", type="primary", use_container_width=True):
            session = _ingest_uploads(session, uploads)

    if DEMO_DIR.exists():
        if st.button("Load demo datasets", use_container_width=True):
            session = _load_demo(session)

    st.subheader("Current datasets")
    if session.datasets:
        for dataset in session.datasets:
            st.markdown(
                f"- `{dataset.meta.table_name}`  \n"
                f"  {dataset.meta.original_filename} · "
                f"{dataset.meta.row_count:,} rows · {dataset.meta.column_count} columns"
            )
    else:
        st.caption("No datasets uploaded yet.")

    if session.relationships:
        with st.expander("Candidate relationships"):
            for rel in session.relationships:
                st.caption(
                    f"{rel.left_table}.{rel.left_column} ↔ "
                    f"{rel.right_table}.{rel.right_column} ({rel.reason})"
                )

    st.divider()
    if st.button("Reset session", use_container_width=True):
        session = empty_session()
        persist_to_streamlit(st.session_state, session)
        st.rerun()
    return session


def _ingest_uploads(session, uploads):
    existing = {dataset.meta.table_name for dataset in session.datasets}
    added = []
    session_bytes = session.session_bytes
    for upload in uploads:
        try:
            parsed = parse_upload(
                upload.name,
                upload.getvalue(),
                existing,
                size_bytes=int(getattr(upload, "size", 0) or len(upload.getvalue())),
                session_bytes=session_bytes,
            )
        except AppError as exc:
            st.error(str(exc))
            continue
        for table in parsed:
            dataset = dataset_from_parsed(table)
            added.append(dataset)
            existing.add(dataset.meta.table_name)
            session_bytes += dataset.meta.size_bytes
            st.success(f"Added `{dataset.meta.table_name}` from {dataset.meta.original_filename}")
    if added:
        session = add_datasets(session, added)
    return session


def _load_demo(session):
    existing = {dataset.meta.table_name for dataset in session.datasets}
    added = []
    session_bytes = session.session_bytes
    for path in sorted(DEMO_DIR.glob("*.csv")):
        if path.stem in existing:
            st.info(f"`{path.stem}` is already in this session.")
            continue
        data = path.read_bytes()
        try:
            parsed = parse_upload(path.name, data, existing, size_bytes=len(data), session_bytes=session_bytes)
        except AppError as exc:
            st.error(str(exc))
            continue
        for table in parsed:
            dataset = dataset_from_parsed(table)
            added.append(dataset)
            existing.add(dataset.meta.table_name)
            session_bytes += dataset.meta.size_bytes
    if added:
        session = add_datasets(session, added)
        st.success("Demo customers, orders, and products are ready.")
    return session


def _empty_state() -> None:
    st.info(
        "Upload one or more CSV/Excel files, or load the demo datasets from the sidebar, "
        "then ask a question in natural language."
    )
    st.markdown(
        """
**Example questions**
- What was our total revenue last quarter?
- Which region generated the most revenue?
- What about South?
- Compare revenue across regions.
- Show me the monthly revenue trend.
"""
    )


def _dataset_summary(session) -> None:
    st.subheader("Datasets in this session")
    cols = st.columns(min(3, len(session.datasets)))
    for i, dataset in enumerate(session.datasets):
        with cols[i % len(cols)]:
            st.metric(dataset.meta.table_name, f"{dataset.meta.row_count:,} rows")
            st.caption(", ".join(dataset.meta.columns[:8]) + ("…" if len(dataset.meta.columns) > 8 else ""))


def _question_area(session) -> None:
    st.subheader("Ask a question")
    settings = get_settings()
    if not settings.llm_configured:
        st.warning(
            "Configure `GROQ_API_KEY` in `.env` or Streamlit secrets before asking questions. "
            "File upload, profiling, and DuckDB queries still work."
        )

    question = st.text_area(
        "Question",
        placeholder="What was our total revenue last quarter?",
        label_visibility="collapsed",
        height=90,
    )
    asked = st.button("Ask", type="primary")

    if asked:
        session = load_from_streamlit(st.session_state)
        connection = create_connection(session.datasets)
        with st.spinner("Planning with the LLM, then computing in DuckDB…"):
            answer = run_analysis(
                question,
                session.profiles,
                session.relationships,
                session.state,
                connection,
            )
        if answer.state is not None:
            session.state = answer.state
        session.history.append(
            {
                "question": question,
                "status": answer.status,
                "message": answer.message,
                "sql": answer.sql_used,
                "tables": answer.tables_used,
                "filters": answer.filters,
                "viz_types": answer.viz_types,
            }
        )
        persist_to_streamlit(st.session_state, session)
        st.session_state["_latest_answer"] = answer
        st.rerun()

    answer = st.session_state.get("_latest_answer")
    if answer:
        _render_answer(answer)

    if session.history:
        with st.expander("Recent questions"):
            for item in reversed(session.history[-8:]):
                st.markdown(f"**{item['question']}**")
                st.caption(item["message"][:400])


def _render_answer(answer) -> None:
    """Render the analytical answer, figures, and computation transparency.

    Args:
        answer: AgentAnswer object containing query results, plans, and metrics.
    """
    if answer.status == "clarification":
        st.warning(answer.message)
        st.warning(f"Clarification needed: {answer.message}")
        return
    if answer.status in {"error", "cannot_answer"}:

    if answer.status == "cannot_answer":
        st.info(f"Notice: {answer.message}")
        return

    if answer.status == "error":
        st.error(answer.message)
        if answer.errors:
            with st.expander("Details"):
            with st.expander("Error details"):
                for err in answer.errors:
                    st.code(err)
        return

    st.success("Computed from your uploaded data with DuckDB.")
    st.write(answer.message)

    for i, result in enumerate(answer.results):
        if result.kind == "scalar":
            st.metric(result.scalar_label or result.title, result.text.split(": ", 1)[-1])
        elif answer.viz_types[i : i + 1] == ["table"] or result.kind in {"tabular", "empty"}:
            st.dataframe(result.dataframe, use_container_width=True, hide_index=True)
        else:
            st.dataframe(result.dataframe, use_container_width=True, hide_index=True)
    # Separate scalar KPI results from tabular/grouped results
    scalars = [res for res in answer.results if res.kind == "scalar"]
    non_scalars = [res for res in answer.results if res.kind != "scalar"]

    # Display KPI metrics side-by-side if multiple
    if scalars:
        cols = st.columns(min(len(scalars), 4))
        for idx, scalar_res in enumerate(scalars):
            with cols[idx % len(cols)]:
                label = scalar_res.scalar_label or scalar_res.title
                if ": " in scalar_res.text:
                    display_val = scalar_res.text.split(": ", 1)[-1]
                else:
                    display_val = str(scalar_res.scalar_value)
                st.metric(label=label, value=display_val)

    # Render Plotly visualizations
    for figure in answer.visualizations:
        st.plotly_chart(figure, use_container_width=True)

    # Render data tables for non-scalar results
    for res in non_scalars:
        if not res.dataframe.empty:
            st.dataframe(res.dataframe, use_container_width=True, hide_index=True)

    # Calculation transparency expander
    with st.expander("How was this calculated?"):
        if answer.tables_used:
            st.markdown("**Tables used:** " + ", ".join(f"`{name}`" for name in answer.tables_used))
        if answer.filters:
            st.markdown("**Filters:** " + ", ".join(f"`{k}` = {v}" for k, v in answer.filters.items()))
        if answer.plan and answer.plan.metric:
            st.markdown(f"**Metric:** `{answer.plan.metric}`")
        if answer.plan and answer.plan.time_period:
            st.markdown(f"**Time period:** {answer.plan.time_period}")
        for sql in answer.sql_used:
            st.code(sql, language="sql")
        st.caption("Numbers come from DuckDB. The model only planned the query and wrote the explanation.")


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp { background: #f7f5f1; }
        h1 { letter-spacing: -0.03em; }
        [data-testid="stSidebar"] { background: #efeae2; }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
