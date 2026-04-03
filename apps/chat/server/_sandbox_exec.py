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
        "ftplib",
        "smtplib",
        "xmlrpc",
        "telnetlib",
        "poplib",
        "imaplib",
        "asyncio",
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
        # Dynamic class creation (3-arg type() is a sandbox escape primitive)
        "type",
        # Information leaks
        "dir",
        "help",
        # Raw memory access
        "memoryview",
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
        # numpy file I/O
        "save",
        "load",
        "loadtxt",
        "genfromtxt",
        "fromfile",
        "savetxt",
        # plotly file I/O
        "write_html",
        "write_image",
        "write_json",
        # matplotlib file I/O (only dangerous when called, not accessed)
        "savefig",
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
        "__objclass__",
        "__init_subclass__",
        "__set_name__",
        "__class_getitem__",
        "__reduce__",
        "__reduce_ex__",
        # Introspection attrs that leak internals (e.g. raw DB conn via defaults)
        "__dict__",
        "__defaults__",
        "__func__",
        "__closure__",
        "__wrapped__",
        "__self__",
        # Descriptor protocol — prevents overriding attribute access
        "__getattr__",
        "__getattribute__",
        "__setattr__",
        "__delattr__",
        "__get__",
        "__set__",
        "__delete__",
    }
)


def _attribute_chain(node: ast.AST) -> str:
    """Return the dotted attribute chain for *node* as a string."""
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


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
                chain = _attribute_chain(func)
                if chain in _BLOCKED_ATTRIBUTE_CHAINS:
                    return f"Blocked DuckDB access call: {chain}()"
                if func.attr in _BLOCKED_BUILTINS:
                    return f"Blocked attribute call: .{func.attr}()"
                if func.attr in _BLOCKED_ATTRIBUTE_CALLS:
                    call_name = chain or func.attr
                    return f"Blocked file or network access call: {call_name}()"

        # Block decorators that use blocked calls (evaluated at definition time)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for decorator in node.decorator_list:
                for sub in ast.walk(decorator):
                    if isinstance(sub, ast.Call):
                        func = sub.func
                        if isinstance(func, ast.Name) and func.id in _BLOCKED_BUILTINS:
                            return f"Blocked builtin in decorator: {func.id}()"
                        if isinstance(func, ast.Attribute) and func.attr in _BLOCKED_BUILTINS:
                            return f"Blocked call in decorator: .{func.attr}()"

        # Block dunder attribute access for class hierarchy traversal
        elif isinstance(node, ast.Attribute) and node.attr in _BLOCKED_ATTRS:
            return f"Blocked attribute access: .{node.attr}"

        # Block bare __builtins__ access (enables subscript bypass like
        # __builtins__.__dict__["open"] or __builtins__["open"])
        elif isinstance(node, ast.Name) and node.id == "__builtins__":
            return "Blocked access to __builtins__"

    return None


# ---------------------------------------------------------------------------
# Environment scrubbing
# ---------------------------------------------------------------------------

_SAFE_ENV_VARS: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "TMPDIR",
        "TEMP",
        "TMP",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "PYTHONPATH",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONUNBUFFERED",
        "DISPLAY",
        "TERM",
        "COLORTERM",
    }
)


def build_clean_env() -> dict[str, str]:
    """Return a minimal environment with only known-safe variables.

    Uses an allowlist rather than a blocklist so that new sensitive
    variables (DATABASE_URL, AWS_ACCESS_KEY_ID, etc.) are excluded
    by default.
    """
    return {k: v for k, v in os.environ.items() if k in _SAFE_ENV_VARS}


# ---------------------------------------------------------------------------
# Sandboxed execution
# ---------------------------------------------------------------------------


_RESOURCE_LIMITS_CODE = """\
import contextlib as _ctx, resource as _res
with _ctx.suppress(ValueError, OSError):
    _res.setrlimit(_res.RLIMIT_AS, (536870912, 536870912))  # 512 MB
with _ctx.suppress(ValueError, OSError):
    _res.setrlimit(_res.RLIMIT_FSIZE, (10485760, 10485760))  # 10 MB
with _ctx.suppress(ValueError, OSError):
    _res.setrlimit(_res.RLIMIT_CPU, (65, 65))  # 65s (slightly above 60s timeout)
# Note: RLIMIT_AS and RLIMIT_NPROC may not be enforced on macOS
with _ctx.suppress(ValueError, OSError):
    _res.setrlimit(_res.RLIMIT_NPROC, (0, 0))  # No forking
del _ctx, _res
"""


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
            f.write(_RESOURCE_LIMITS_CODE + full_code)
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


def _classify_output(parsed: dict) -> dict | None:
    """Classify a parsed JSON dict as a known structured output type."""
    # Matplotlib base64 PNG
    if "image_base64" in parsed and "format" in parsed:
        return {"_type": "matplotlib", "_raw": json.dumps(parsed)}
    # Plotly figure
    if "data" in parsed and "layout" in parsed:
        return {"_type": "plotly", "_raw": json.dumps(parsed)}
    # DataFrame (split orient)
    if "columns" in parsed and "data" in parsed:
        columns = parsed["columns"]
        rows = parsed["data"]
        return {
            "_type": "dataframe",
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        }
    # Export / embed / spreadsheet / social / thread
    if "format" in parsed and "content" in parsed:
        return {"_type": parsed["format"], "_raw": json.dumps(parsed)}
    return None


def _parse_all_structured_outputs(stdout: str) -> tuple[list[dict], str]:
    """Scan all stdout lines for structured JSON outputs.

    Returns (results, plain_text) where results is a list of classified
    outputs and plain_text is the remaining non-structured text.
    """
    results: list[dict] = []
    plain_lines: list[str] = []
    for line in stdout.strip().splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                result = _classify_output(parsed)
                if result is not None:
                    results.append(result)
                    continue
        except json.JSONDecodeError:
            pass
        plain_lines.append(line)
    return results, "\n".join(plain_lines)


def _parse_structured_output(stdout: str, stderr: str) -> dict:
    """Detect structured output (Plotly, DataFrame, image) in *stdout*.

    Supports multiple structured outputs from a single execution.
    When multiple outputs are found, returns ``{"_multi": [...]}``
    so the rendering layer can display all of them.
    """
    if not stdout:
        return {"stdout": stdout, "stderr": stderr}

    results, plain_text = _parse_all_structured_outputs(stdout)

    if len(results) == 0:
        return {"stdout": stdout, "stderr": stderr}

    if len(results) == 1:
        # Backward-compatible: single result without _multi wrapper
        single = results[0]
        # Preserve legacy format for _raw results
        if "_raw" in single:
            return {"_raw": single["_raw"]}
        return single

    # Multiple results
    return {"_multi": results, "stdout": plain_text, "stderr": stderr}
