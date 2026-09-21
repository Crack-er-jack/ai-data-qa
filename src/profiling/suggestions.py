"""Deterministic schema-based suggestions and metadata question handling."""

from __future__ import annotations

import re
from pathlib import Path

from src.matching.relationships import RelationshipCandidate
from src.profiling.schema import TableProfile


def is_metadata_question(question: str) -> bool:
    """Detect whether a natural language question asks for dataset metadata.

    Distinguishes informational/schema questions (e.g. 'What datasets are currently loaded?',
    'What columns are available?', 'Describe the datasets') from analytical SQL queries.

    Args:
        question: User natural language input.

    Returns:
        True if the question asks for metadata/schema, False if it is analytical.
    """
    text = (question or "").strip().lower()
    if not text:
        return False

    # Normalize whitespace and trailing punctuation
    clean = re.sub(r"\s+", " ", text.rstrip("?.! "))

    # Explicit full-phrase matches
    exact_phrases = {
        "what datasets are currently loaded",
        "what datasets are loaded",
        "what datasets do i have",
        "what datasets are available",
        "describe the datasets",
        "describe datasets",
        "describe the data",
        "describe data",
        "what columns are available",
        "what columns do i have",
        "what columns do we have",
        "what columns are there",
        "what data do i have",
        "what data is available",
        "what data is loaded",
        "what data do we have",
        "what files are uploaded",
        "what files are loaded",
        "what files do i have",
        "what tables are available",
        "what tables do i have",
        "what tables do we have",
        "what tables are loaded",
        "show available tables",
        "show available datasets",
        "show available files",
        "show available columns",
        "show datasets",
        "show tables",
        "show columns",
        "show schema",
        "describe schema",
        "what is the schema",
        "list datasets",
        "list tables",
        "list the datasets",
        "list the tables",
        "list columns",
        "list the columns",
        "what can i ask",
        "help with datasets",
    }
    if clean in exact_phrases:
        return True

    # Indicators of real computational/analytical intent
    computation_keywords = (
        "sum",
        "average",
        "avg",
        "total",
        "count",
        "trend",
        "compare",
        "revenue",
        "profit",
        "sales",
        "salary",
        "salaries",
        "spend",
        "cost",
        "price",
        "margin",
        "growth",
        "breakdown",
        "break down",
        "highest",
        "lowest",
        "top ",
        "bottom ",
        "maximum",
        "max",
        "minimum",
        "min",
        "percent",
        "percentage",
        "ratio",
        "quarter",
        "month",
        "year",
        "yesterday",
        "today",
        "filter",
        "where",
        "group by",
        "over time",
    )
    if any(kw in clean for kw in computation_keywords):
        return False

    # Regex patterns for metadata questions
    metadata_patterns = [
        r"^(what|which)\s+(datasets?|files?|tables?)\s+(are\s+)?(currently\s+)?(loaded|uploaded|available|present|in this session)$",
        r"^(describe|show|list|display)\s+(the\s+)?(available\s+)?(datasets?|files?|tables?|columns?|schema|data)$",
        r"^(what|which)\s+(columns?|fields?)\s+(are\s+)?(available|present|in (the|these) (datasets?|tables?))$",
        r"^what\s+(data|information)\s+(do\s+(i|we)\s+have|is\s+(loaded|available|here))$",
        r"^what\s+(tables?|datasets?|files?)\s+do\s+(i|we)\s+have$",
        r"^(tell\s+me\s+about|overview\s+of)\s+(the\s+)?(datasets?|files?|tables?|data)$",
        r"^what\s+can\s+(i|we)\s+ask(\s+about)?$",
    ]
    return any(bool(re.search(pattern, clean)) for pattern in metadata_patterns)


def generate_schema_suggestions(
    profiles: list[TableProfile],
    relationships: list[RelationshipCandidate] | None = None,
) -> list[str]:
    """Generate deterministic, schema-based suggestions for queries from uploaded datasets.

    Derives suggestions dynamically using detected column types (numeric, categorical,
    temporal) and relationships without invoking any external LLM calls.

    Args:
        profiles: Schema profiles of all active tables.
        relationships: Inferred cross-table join candidate pairs.

    Returns:
        List of 4 to 6 natural language query suggestions.
    """
    if not profiles:
        return []

    suggestions: list[str] = []

    # Identify candidate columns across all tables
    numeric_cols: list[tuple[str, str]] = []  # (table_name, col_name)
    category_cols: list[tuple[str, str]] = []  # (table_name, col_name)
    date_cols: list[tuple[str, str]] = []  # (table_name, col_name)

    id_suffixes = ("_id", "id", "_code", "_zip", "_key", "year", "quarter", "month", "day")
    non_cat_suffixes = ("_id", "id", "_email", "_url", "_hash", "_key", "description", "notes", "comment")

    for profile in profiles:
        for col in profile.columns:
            name_lower = col.name.lower()

            # Date columns
            if col.data_type == "datetime" or "date" in name_lower or "time" in name_lower:
                date_cols.append((profile.table_name, col.name))
                continue

            # Numeric metric columns
            if col.data_type in {"integer", "float", "numeric"}:
                if not any(name_lower.endswith(suf) for suf in id_suffixes):
                    numeric_cols.append((profile.table_name, col.name))
                continue

            # Categorical dimension columns
            if col.data_type == "string":
                if not any(name_lower.endswith(suf) for suf in non_cat_suffixes):
                    card = col.cardinality if col.cardinality is not None else 0
                    if 1 < card <= 100 or card == 0:
                        category_cols.append((profile.table_name, col.name))

    # Prioritize primary business metrics (revenue, total, sales, salary, spend)
    def _metric_priority(item: tuple[str, str]) -> int:
        n = item[1].lower()
        if any(k in n for k in ("total", "revenue", "sales", "amount", "salary", "spend", "cost", "value")):
            return 0
        if any(k in n for k in ("price", "profit", "rate", "score")):
            return 1
        if any(k in n for k in ("quantity", "qty", "count", "hours")):
            return 2
        return 3

    # Prioritize primary analytical dimensions (region, category, department, segment)
    def _category_priority(item: tuple[str, str]) -> int:
        n = item[1].lower()
        if any(k in n for k in ("region", "segment", "category", "dept", "department", "channel", "type", "status")):
            return 0
        if any(k in n for k in ("tier", "gender", "level", "role", "title", "location", "rating")):
            return 1
        return 2

    numeric_cols.sort(key=_metric_priority)
    category_cols.sort(key=_category_priority)

    # Deterministic generation using available slots
    if numeric_cols:
        t_num, c_num = numeric_cols[0]
        suggestions.append(f"What is the total {c_num}?")

        # Numeric + Categorical
        if category_cols:
            t_cat, c_cat = category_cols[0]
            suggestions.append(f"What is the total {c_num} by {c_cat}?")
            suggestions.append(f"What is the average {c_num} by {c_cat}?")

        # Date + Numeric
        if date_cols:
            suggestions.append(f"Show {c_num} over time.")

        # Cross-file or second category comparison
        if len(category_cols) > 1:
            t_cat2, c_cat2 = category_cols[1]
            suggestions.append(f"Compare {c_num} across {c_cat2}.")
        elif relationships and category_cols:
            t_cat, c_cat = category_cols[0]
            suggestions.append(f"Compare {c_num} across {c_cat}.")

        # Second numeric metric if space permits
        if len(numeric_cols) > 1 and len(suggestions) < 6:
            _, c_num2 = numeric_cols[1]
            suggestions.append(f"What is the average {c_num2}?")

    # Fallback if no numeric columns found
    if not suggestions:
        for profile in profiles:
            suggestions.append(f"How many records are in {profile.table_name}?")
            if category_cols:
                _, c_cat = category_cols[0]
                suggestions.append(f"Show record count by {c_cat}.")
                break

    # Deduplicate while preserving order, cap at 6
    seen = set()
    result: list[str] = []
    for s in suggestions:
        if s not in seen:
            seen.add(s)
            result.append(s)
        if len(result) >= 6:
            break

    return result


def build_metadata_response(
    profiles: list[TableProfile],
    relationships: list[RelationshipCandidate] | None = None,
) -> str:
    """Build a natural language overview of loaded datasets, columns, and sample queries.

    Args:
        profiles: Schema profiles of all active tables.
        relationships: Inferred cross-table join candidate pairs.

    Returns:
        Formatted string describing the datasets and schema metadata.
    """
    if not profiles:
        return "No datasets are currently loaded. Upload a CSV or Excel file to get started."

    count = len(profiles)
    dataset_word = "dataset" if count == 1 else "datasets"
    lines = [f"You currently have {count} {dataset_word} loaded:\n"]

    for profile in profiles:
        filename = profile.original_filename or f"{profile.table_name}.csv"
        lines.append(f"**{filename}**")
        lines.append(f"{profile.row_count:,} rows · {profile.column_count} columns")
        col_summary = ", ".join(f"{col.name} ({col.data_type})" for col in profile.columns)
        lines.append(f"Columns: {col_summary}\n")

    if relationships:
        lines.append("**Detected relationships:**")
        for rel in relationships:
            lines.append(f"- `{rel.left_table}.{rel.left_column}` → `{rel.right_table}.{rel.right_column}`")
        lines.append("")

    suggestions = generate_schema_suggestions(profiles, relationships)
    if suggestions:
        lines.append("You can ask analytical questions such as:")
        for sugg in suggestions[:4]:
            lines.append(f"- {sugg}")

    return "\n".join(lines)
