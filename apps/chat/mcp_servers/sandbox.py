"""Python sandbox MCP server for executing analytics code."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
from _preamble import build_preamble  # noqa: E402

_DEFAULT_DB = Path("~/.nbadb/data/nba.duckdb").expanduser()
DB_PATH = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else _DEFAULT_DB

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills" / "nba-data-analytics" / "scripts"

mcp = FastMCP("nbadb-sandbox")

# Block dangerous patterns in user code
_BLOCKED_PATTERNS = [
    "subprocess",
    "os.system",
    "os.popen",
    "os.exec",
    "__import__('os')",
    "importlib",
    "shutil.rmtree",
    "open('/etc",
    "open('/proc",
    "open('/sys",
]


def _check_code_safety(code: str) -> str | None:
    """Check for obviously dangerous code patterns. Returns error or None."""
    for pattern in _BLOCKED_PATTERNS:
        if pattern in code:
            return f"Blocked: code contains dangerous pattern '{pattern}'"
    return None


@mcp.tool()
def run_python(code: str) -> str:
    """Execute Python code with access to the NBA database and visualization libraries.

    Pre-imported libraries: pandas (pd), numpy (np), plotly.express (px),
    plotly.graph_objects (go), matplotlib (plt), duckdb, scipy.stats (stats)

    Pre-defined helpers:
    - `conn` — read-only DuckDB connection to the NBA database
    - `query(sql)` — run SQL and return a DataFrame
    - `chart(fig)` — output a Plotly figure for display
    - `table(df)` — output a DataFrame for display
    - `show(data)` — auto-detect: Plotly figure → chart(), DataFrame → table(), else print()
    - `mc` — metric_calculator module (mc.true_shooting_pct, mc.usage_rate, etc.)
    """
    if not code or not code.strip():
        return json.dumps({"error": "No code provided"})

    safety_error = _check_code_safety(code)
    if safety_error:
        return json.dumps({"error": safety_error})

    preamble = build_preamble(
        db_path=str(DB_PATH),
        skills_dir=str(SKILLS_DIR),
    )
    full_code = preamble + "\n" + code

    # Scrub sensitive environment variables from sandbox
    clean_env = {
        k: v
        for k, v in os.environ.items()
        if not any(
            secret in k.upper()
            for secret in (
                "API_KEY",
                "SECRET",
                "TOKEN",
                "PASSWORD",
                "LANGCHAIN_API",
                "LANGFUSE",
                "COPILOT",
            )
        )
    }

    script_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(full_code)
            script_path = f.name

        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(DB_PATH.parent),
            env=clean_env,
            start_new_session=True,
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if result.returncode != 0:
            return json.dumps({"error": stderr or "Script failed", "stdout": stdout})

        # Try to detect structured output in the last line
        if stdout:
            last_line = stdout.rstrip().rsplit("\n", 1)[-1]
            try:
                parsed = json.loads(last_line)
                if isinstance(parsed, dict):
                    # Matplotlib base64 PNG
                    if "image_base64" in parsed and "format" in parsed:
                        return last_line  # Return raw for Chainlit rendering
                    # Plotly figure
                    if "data" in parsed and "layout" in parsed:
                        return last_line  # Return raw plotly JSON for Chainlit
                    # DataFrame (split orient)
                    if "columns" in parsed and "data" in parsed:
                        return json.dumps(
                            {
                                "columns": parsed["columns"],
                                "rows": parsed["data"],
                                "row_count": len(parsed["data"]),
                            }
                        )
            except (json.JSONDecodeError, KeyError):
                pass

        return json.dumps({"stdout": stdout, "stderr": stderr})

    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Script timed out after 60 seconds"})
    finally:
        if script_path:
            with contextlib.suppress(OSError):
                os.unlink(script_path)


if __name__ == "__main__":
    mcp.run(transport="stdio")
