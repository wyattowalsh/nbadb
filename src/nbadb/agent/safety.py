from __future__ import annotations

import re

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
    r"glob|read_csv_auto|read_ndjson|http_get)\s*\(",
    re.IGNORECASE,
)

MAX_RESULT_ROWS: int = 10_000
QUERY_TIMEOUT_SECONDS: float = 30.0


class ReadOnlyGuard:
    def validate(self, sql: str) -> str | None:
        stripped = sql.strip().rstrip(";").strip()
        if not stripped:
            return "Empty query"
        match = _WRITE_PATTERN.search(stripped)
        if match:
            return f"Write operation not allowed: {match.group(0)}"
        func_match = _DANGEROUS_FUNCTIONS.search(stripped)
        if func_match:
            return f"File access function not allowed: {func_match.group(1)}"
        if not stripped.upper().startswith(("SELECT", "WITH", "EXPLAIN", "SHOW", "DESCRIBE")):
            return f"Only SELECT queries are allowed, got: {stripped.split()[0]}"
        return None

    def wrap_with_limit(self, sql: str, max_rows: int = MAX_RESULT_ROWS) -> str:
        stripped = sql.strip().rstrip(";")
        if "LIMIT" not in stripped.upper():
            return f"{stripped}\nLIMIT {max_rows}"
        return stripped
