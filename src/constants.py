"""Configurable product limits. Environment variables may override these."""

import os


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


MAX_FILE_SIZE_MB = _int_env("MAX_FILE_SIZE_MB", 10)
MAX_SESSION_SIZE_MB = _int_env("MAX_SESSION_SIZE_MB", 50)
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_SESSION_SIZE_BYTES = MAX_SESSION_SIZE_MB * 1024 * 1024

MAX_RESULT_ROWS = _int_env("MAX_RESULT_ROWS", 200)
MAX_LLM_RESULT_ROWS = _int_env("MAX_LLM_RESULT_ROWS", 50)
MAX_CELL_CHARS = 200

MAX_SQL_CORRECTION_RETRIES = _int_env("MAX_SQL_CORRECTION_RETRIES", 1)
MAX_ANALYTICAL_QUERIES = _int_env("MAX_ANALYTICAL_QUERIES", 3)

SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls"}
SAMPLE_VALUE_COUNT = 5
OVERLAP_SAMPLE_LIMIT = 2000
RELATIONSHIP_MIN_OVERLAP = 0.15
