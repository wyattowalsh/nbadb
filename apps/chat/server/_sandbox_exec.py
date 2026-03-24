"""Shared sandbox execution logic for MCP sandbox and Copilot backend.

Provides AST-based code safety checks, environment scrubbing, and sandboxed
subprocess execution. Both ``mcp_servers/sandbox.py`` and
``server/copilot_backend.py`` delegate to this module so that security
policy lives in a single place.
"""

from __future__ import annotations

import ast
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Code safety — AST-based (replaces naive string blocklist)
# ---------------------------------------------------------------------------

_BLOCKED_MODULES: frozenset[str] = frozenset(
    {
        "subprocess",
        "os",
        "shutil",
        "importlib",
        "ctypes",
        "socket",
        "http",
        "urllib",
        "requests",
        "builtins",
        "signal",
        "multiprocessing",
        "threading",
        "sys",
        "pathlib",
        "io",
        "duckdb",
    }
)

_BLOCKED_BUILTINS: frozenset[str] = frozenset(
    {
        "exec",
        "eval",
        "compile",
        "__import__",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
        "open",
        "breakpoint",
    }
)

_BLOCKED_ATTRIBUTE_CALLS: frozenset[str] = frozenset(
    {
        "read_csv",
        "read_table",
        "read_parquet",
        "read_json",
        "read_excel",
        "read_feather",
        "read_hdf",
        "read_html",
        "read_xml",
        "read_pickle",
        "read_fwf",
        "read_spss",
        "read_sas",
        "read_stata",
        "read_text",
        "read_bytes",
        "write_text",
        "write_bytes",
        "to_csv",
        "to_parquet",
        "to_excel",
        "to_feather",
        "to_hdf",
        "to_pickle",
        "to_sql",
        "to_xml",
        "open",
        "mkdir",
        "rmdir",
        "unlink",
        "touch",
        "glob",
        "rglob",
        "iterdir",
        "connect",
    }
)

_BLOCKED_ATTRIBUTE_CHAINS: frozenset[str] = frozenset(
    {
        "duckdb.sql",
        "duckdb.execute",
        "duckdb.query",
        "duckdb.table",
        "duckdb.from_query",
        "duckdb.read_csv",
        "duckdb.read_parquet",
        "duckdb.read_json",
        "duckdb.read_json_auto",
        "duckdb.read_text",
        "duckdb.read_blob",
        "duckdb.read_xlsx",
        "duckdb.from_csv_auto",
    }
)

_BLOCKED_ATTRS: frozenset[str] = frozenset(
    {
        "__class__",
        "__subclasses__",
        "__bases__",
        "__mro__",
        "__globals__",
        "__code__",
        "__builtins__",
        "savefig",
    }
)


def _attribute_chain(node: ast.AST) -> tuple[str, ...]:
    """Return the dotted attribute chain for *node* if possible."""
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return tuple(reversed(parts))


def check_code_safety(code: str) -> str | None:
    """Validate Python code via AST analysis.

    Returns an error string describing the violation, or ``None`` if the code
    passes all checks.
    """
    code = unicodedata.normalize("NFKC", code)

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"Syntax error: {exc}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _BLOCKED_MODULES:
                    return f"Blocked import: {alias.name}"

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                if root in _BLOCKED_MODULES:
                    return f"Blocked import: {node.module}"

        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _BLOCKED_BUILTINS:
                return f"Blocked builtin call: {func.id}()"
            if isinstance(func, ast.Attribute):
                chain = ".".join(_attribute_chain(func))
                if chain in _BLOCKED_ATTRIBUTE_CHAINS:
                    return f"Blocked DuckDB access call: {chain}()"
                if func.attr in _BLOCKED_BUILTINS:
                    return f"Blocked attribute call: .{func.attr}()"
                if func.attr in _BLOCKED_ATTRIBUTE_CALLS:
                    call_name = chain or func.attr
                    return f"Blocked file or network access call: {call_name}()"

        # Block dunder attribute access for class hierarchy traversal
        elif isinstance(node, ast.Attribute) and node.attr in _BLOCKED_ATTRS:
            return f"Blocked attribute access: .{node.attr}"

    return None


# ---------------------------------------------------------------------------
# Environment scrubbing
# ---------------------------------------------------------------------------

_SECRET_TOKENS: tuple[str, ...] = (
    "API_KEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "LANGCHAIN_API",
    "LANGFUSE",
    "COPILOT",
)


def build_clean_env() -> dict[str, str]:
    """Return a copy of ``os.environ`` with sensitive variables stripped."""
    return {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in _SECRET_TOKENS)}


# ---------------------------------------------------------------------------
# Sandboxed execution
# ---------------------------------------------------------------------------


def run_sandboxed(
    full_code: str,
    cwd: Path,
    timeout: int = 60,
) -> dict:
    """Execute *full_code* in a subprocess sandbox.

    Returns a dict suitable for JSON serialization.  The dict always has at
    least one of ``error``, ``stdout``, ``_raw``, ``columns``, or similar keys
    so callers can dispatch on structure.
    """
    script_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".py",
            mode="w",
            delete=False,
        ) as f:
            f.write(full_code)
            script_path = f.name

        # Restrict file permissions (HR-9)
        os.chmod(script_path, 0o600)

        clean_env = build_clean_env()

        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd),
            env=clean_env,
            start_new_session=True,
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if result.returncode != 0:
            return {"error": stderr or "Script failed", "stdout": stdout}

        return _parse_structured_output(stdout, stderr)

    except subprocess.TimeoutExpired:
        return {"error": f"Script timed out after {timeout} seconds"}
    finally:
        if script_path:
            with contextlib.suppress(OSError):
                os.unlink(script_path)


def _parse_structured_output(stdout: str, stderr: str) -> dict:
    """Detect structured output (Plotly, DataFrame, image) in *stdout*."""
    if stdout:
        last_line = stdout.rstrip().rsplit("\n", 1)[-1]
        try:
            parsed = json.loads(last_line)
            if isinstance(parsed, dict):
                # Matplotlib base64 PNG
                if "image_base64" in parsed and "format" in parsed:
                    return {"_raw": last_line}
                # Plotly figure
                if "data" in parsed and "layout" in parsed:
                    return {"_raw": last_line}
                # DataFrame (split orient)
                if "columns" in parsed and "data" in parsed:
                    return {
                        "columns": parsed["columns"],
                        "rows": parsed["data"],
                        "row_count": len(parsed["data"]),
                    }
        except (json.JSONDecodeError, KeyError):
            pass

    return {"stdout": stdout, "stderr": stderr}
