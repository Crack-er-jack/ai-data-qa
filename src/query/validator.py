"""Defense-in-depth validation for analytical, read-only SQL."""

from __future__ import annotations

import re

from src.errors import SqlValidationError

_COMMENT_LINE = re.compile(r"--.*?$", re.MULTILINE)
_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)
_STRINGS = re.compile(r"('([^'\\]|\\.)*'|\"([^\"\\]|\\.)*\")")

_UNSAFE_FUNCTIONS = re.compile(
    r"\b(read_csv|read_csv_auto|read_parquet|read_json|read_json_auto|read_ndjson|"
    r"read_blob|read_text|read_xlsx|glob|sqlite_scan|postgres_scan|delta_scan|"
    r"iceberg_scan|httpfs|query_table)\s*\(",
    re.IGNORECASE,
)

_UNSAFE_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|ATTACH|DETACH|COPY|"
    r"EXPORT|IMPORT|INSTALL|LOAD|PRAGMA|VACUUM|CHECKPOINT|GRANT|REVOKE|"
    r"MERGE|EXECUTE|PREPARE|BEGIN|COMMIT|ROLLBACK|TRANSACTION|CALL|SECRET|"
    r"REPLACE\s+INTO|PIVOT_WIDER)\b",
    re.IGNORECASE,
)

_FROM_JOIN = re.compile(
    r"\b(?:FROM|JOIN)\s+("
    r"[A-Za-z_][\w]*"
    r"|\"[^\"]+\""
    r")"
    r"(?:\s*\.\s*("
    r"[A-Za-z_][\w]*"
    r"|\"[^\"]+\""
    r"))?",
    re.IGNORECASE,
)

_WITH_CTE = re.compile(
    r"\b([A-Za-z_][\w]*|\"[^\"]+\")\s+AS\s*\(",
    re.IGNORECASE,
)

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def strip_sql_comments(sql: str) -> str:
    """Remove SQL block and line comments without modifying string literals.

    Guarantees that hyphens or slashes inside quotes (e.g. date strings
    or URLs) are never misidentified as comments.

    Args:
        sql: The raw SQL string.

    Returns:
        SQL string with comments stripped.
    """
    result: list[str] = []
    i = 0
    n = len(sql)
    in_single = False
    in_double = False

    while i < n:
        c = sql[i]
        # Track literal boundaries
        if c == "'" and not in_double:
            in_single = not in_single
            result.append(c)
            i += 1
            continue
        if c == '"' and not in_single:
            in_double = not in_double
            result.append(c)
            i += 1
            continue

        if not in_single and not in_double:
            # Check for block comment /* ... */
            if c == "/" and i + 1 < n and sql[i + 1] == "*":
                end_idx = sql.find("*/", i + 2)
                if end_idx != -1:
                    i = end_idx + 2
                    result.append(" ")
                    continue
                else:
                    break
            # Check for line comment -- ...
            if c == "-" and i + 1 < n and sql[i + 1] == "-":
                newline_idx = sql.find("\n", i + 2)
                if newline_idx != -1:
                    i = newline_idx
                    continue
                else:
                    break

        result.append(c)
        i += 1

    return "".join(result)


def mask_literals(sql: str) -> str:
    """Mask string literals for safe lexical keyword scanning."""
    return _STRINGS.sub("'x'", sql)


def split_statements(sql: str) -> list[str]:
    """Split SQL into individual statements, ignoring semicolons inside string literals.

    Args:
        sql: The raw SQL string.

    Returns:
        List of non-empty SQL statement strings.
    """
    cleaned = strip_sql_comments(sql)
    statements: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    escape = False

    for char in cleaned:
        if escape:
            current.append(char)
            escape = False
            continue

        if char == "\\":
            current.append(char)
            escape = True
            continue

        if char == "'" and not in_double:
            in_single = not in_single
            current.append(char)
            continue

        if char == '"' and not in_single:
            in_double = not in_double
            current.append(char)
            continue

        if char == ";" and not in_single and not in_double:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            continue

        current.append(char)

    trailing = "".join(current).strip()
    if trailing:
        statements.append(trailing)

    return statements


def validate_sql(sql: str, known_tables: set[str], known_columns: dict[str, set[str]] | None = None) -> str:
    if not sql or not sql.strip():
        raise SqlValidationError("SQL is empty.")

    statements = split_statements(sql)
    if len(statements) == 0:
        raise SqlValidationError("SQL is empty.")
    if len(statements) > 1:
        raise SqlValidationError("Multiple SQL statements are not allowed.")

    statement = statements[0]
    masked = mask_literals(statement)
    leading = masked.lstrip().split(None, 1)
    if not leading:
        raise SqlValidationError("SQL is empty.")
    start = leading[0].upper()
    if start not in {"SELECT", "WITH"}:
        raise SqlValidationError("Only SELECT / WITH analytical queries are allowed.")

    if _UNSAFE_KEYWORDS.search(masked):
        raise SqlValidationError("SQL contains a disallowed statement or command.")
    if _UNSAFE_FUNCTIONS.search(masked):
        raise SqlValidationError("SQL contains a disallowed file or scan function.")

    referenced = extract_table_names(statement)
    cte_names = extract_cte_names(statement)
    allowed = {name.lower() for name in known_tables} | cte_names
    unknown = [name for name in referenced if name not in allowed]
    if unknown:
        raise SqlValidationError(
            "Unknown table(s): "
            + ", ".join(sorted(unknown))
            + ". Known tables: "
            + ", ".join(sorted(known_tables))
        )

    if known_columns:
        _validate_qualified_columns(statement, known_columns, cte_names)

    return statement


def extract_cte_names(sql: str) -> set[str]:
    masked = mask_literals(strip_sql_comments(sql))
    if not re.match(r"^\s*WITH\b", masked, re.IGNORECASE):
        return set()
    names = set()
    for match in _WITH_CTE.finditer(masked):
        names.add(_unquote(match.group(1)).lower())
    return names


def extract_table_names(sql: str) -> list[str]:
    """Extract table identifiers referenced in FROM and JOIN clauses.

    Handles explicit JOIN syntax and comma-separated FROM syntax while
    excluding Common Table Expressions (CTEs) and subquery keywords.

    Args:
        sql: The raw or cleaned SQL query string.

    Returns:
        List of lowercased referenced table names.
    """
    masked = mask_literals(strip_sql_comments(sql))
    cte_names = extract_cte_names(masked)
    tables: list[str] = []

    for match in _FROM_JOIN.finditer(masked):
        first = _unquote(match.group(1))
        second = _unquote(match.group(2)) if match.group(2) else None
        # Skip subquery starts that slipped through (shouldn't with this regex).
        # Skip subquery starts that slipped through
        if first.upper() in {"SELECT", "VALUES"}:
            continue
        name = (second or first).lower()
        if name in cte_names:
            continue
        tables.append(name)
        if name not in tables:
            tables.append(name)

    # Also handle comma-separated table lists in FROM clauses (e.g. FROM a, b)
    from_list_pattern = re.compile(
        r"\bFROM\s+([A-Za-z_][\w]*(?:\s*,\s*[A-Za-z_][\w]*)+)",
        re.IGNORECASE,
    )
    for from_match in from_list_pattern.finditer(masked):
        for raw_item in from_match.group(1).split(","):
            candidate = _unquote(raw_item.strip()).lower()
            if candidate and candidate not in cte_names and candidate not in tables:
                tables.append(candidate)

    return tables


def _validate_qualified_columns(
    sql: str,
    known_columns: dict[str, set[str]],
    cte_names: set[str],
) -> None:
    masked = mask_literals(strip_sql_comments(sql))
    pattern = re.compile(r"\b([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\b")
    unknown: list[str] = []
    for table, column in pattern.findall(masked):
        table_l = table.lower()
        column_l = column.lower()
        if table_l in cte_names:
            continue
        if table_l not in known_columns:
            continue
        if column_l not in {c.lower() for c in known_columns[table_l]}:
            unknown.append(f"{table}.{column}")
    if unknown:
        raise SqlValidationError("Unknown column(s): " + ", ".join(sorted(set(unknown))))


def _unquote(value: str) -> str:
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


def quote_ident(name: str) -> str:
    if _IDENT.match(name):
        return name
    return '"' + name.replace('"', '""') + '"'
