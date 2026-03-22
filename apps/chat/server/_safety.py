from __future__ import annotations

import re
import unicodedata

_WRITE_KEYWORDS: set[str] = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "TRUNCATE",
    "REPLACE",
    "MERGE",
    "UPSERT",
    "GRANT",
    "REVOKE",
    "ATTACH",
    "DETACH",
    "COPY",
    "EXPORT",
    "IMPORT",
    "LOAD",
    "INSTALL",
    "PRAGMA",
    "SET",
    "CALL",
    "EXECUTE",
}

_WRITE_PATTERN: re.Pattern[str] = re.compile(
    r"\b(" + "|".join(_WRITE_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

_DANGEROUS_FUNCTIONS: re.Pattern[str] = re.compile(
    r"\b(read_csv|read_parquet|read_json|read_json_auto|read_text|read_blob|"
    r"read_xlsx|glob|read_csv_auto|read_ndjson|http_get|"
    r"scan_csv|scan_csv_auto|scan_parquet|scan_json|"
    r"getenv|current_setting|query_table)\s*\(",
    re.IGNORECASE,
)

_BLOCK_COMMENT: re.Pattern[str] = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT: re.Pattern[str] = re.compile(r"--[^\n]*")

MAX_RESULT_ROWS: int = 10_000
QUERY_TIMEOUT_SECONDS: float = 30.0


def _strip_comments(sql: str) -> str:
    """Remove ``/* ... */`` block comments and ``-- ...`` line comments."""
    result = _BLOCK_COMMENT.sub(" ", sql)
    result = _LINE_COMMENT.sub(" ", result)
    return result


def _normalize_sql(sql: str) -> str:
    """Normalize SQL for safe keyword matching.

    1. Unicode NFKC normalization (collapses fullwidth chars, etc.)
    2. Strip comments
    3. Collapse whitespace
    """
    normalized = unicodedata.normalize("NFKC", sql)
    stripped = _strip_comments(normalized)
    collapsed = re.sub(r"\s+", " ", stripped).strip()
    return collapsed


def _enforce_limit(sql: str, max_rows: int) -> str:
    """Wrap *sql* in a sub-select with a hard LIMIT."""
    return f"SELECT * FROM ({sql.rstrip(';').strip()}) AS _limited LIMIT {max_rows}"


class ReadOnlyGuard:
    def validate(self, sql: str) -> str | None:
        stripped = sql.strip().rstrip(";").strip()
        if not stripped:
            return "Empty query"

        normalized = _normalize_sql(stripped)

        # Block stacked queries (embedded semicolons after comment stripping)
        if ";" in normalized:
            return "Multiple statements not allowed"

        match = _WRITE_PATTERN.search(normalized)
        if match:
            return f"Write operation not allowed: {match.group(0)}"

        func_match = _DANGEROUS_FUNCTIONS.search(normalized)
        if func_match:
            return f"File access function not allowed: {func_match.group(1)}"

        upper = normalized.upper()
        if not upper.startswith(("SELECT", "WITH", "EXPLAIN", "SHOW", "DESCRIBE")):
            return f"Only SELECT queries are allowed, got: {normalized.split()[0]}"

        return None

    def wrap_with_limit(self, sql: str, max_rows: int = MAX_RESULT_ROWS) -> str:
        stripped = sql.strip().rstrip(";")
        return _enforce_limit(stripped, max_rows)
