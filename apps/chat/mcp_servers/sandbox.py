"""Python sandbox MCP server for executing analytics code."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from _preamble import build_preamble  # noqa: E402
from _sandbox_exec import check_code_safety, run_sandboxed  # noqa: E402
from _session import sanitize_session_id  # noqa: E402

_DEFAULT_DB = Path("~/.nbadb/data/nba.duckdb").expanduser()
DB_PATH = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else _DEFAULT_DB
_raw_session_id = sys.argv[2] if len(sys.argv) > 2 else "default"
SESSION_ID = sanitize_session_id(_raw_session_id)

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills" / "nba-data-analytics" / "scripts"
SESSION_DIR = Path("~/.nbadb/session").expanduser() / SESSION_ID

mcp = FastMCP("nbadb-sandbox")

# Cache preamble at module level — DB_PATH and SKILLS_DIR are process-lifetime constants
_PREAMBLE = build_preamble(
    db_path=str(DB_PATH),
    skills_dir=str(SKILLS_DIR),
    session_dir=str(SESSION_DIR),
)


@mcp.tool()
def run_python(code: str) -> str:
    """Execute Python code with access to the NBA database and visualization libraries.

    Pre-imported libraries: pandas (pd), numpy (np), plotly.express (px),
    plotly.graph_objects (go), matplotlib (plt), scipy.stats (stats)

    Pre-defined helpers:
    - `conn` — read-only DuckDB helper with safe `execute(sql)` / `sql(sql)` methods
    - `query(sql)` — run SQL and return a DataFrame
    - `chart(fig)` — output a Plotly figure for display
    - `table(df)` — output a DataFrame for display
    - `show(data)` — auto-detect: Plotly figure → chart(), DataFrame → table(), else print()
    - `to_csv(df, name)` — export DataFrame as downloadable CSV file
    - `to_xlsx(df, name)` — export DataFrame as downloadable XLSX file
    - `to_json(df, name)` — export DataFrame as downloadable JSON file
    - `export(df, name, fmt)` — export in any format ("csv", "xlsx", "json")
    - `to_spreadsheet(df, name)` — generate editable HTML spreadsheet (AG Grid)
    - `annotated_chart(fig, df, metric_col)` — Plotly chart with avg reference line
    - `to_embed(fig, title)` — HTML snippet for embedding in blogs/sites
    - `to_social(df_or_fig, headline, subtitle)` — 1200x630 branded PNG card
    - `to_thread(insights_list)` — numbered thread for social media
    - `last_result` — DataFrame from previous call (auto-persisted)
    - `mc` — metric_calculator module (mc.true_shooting_pct, mc.usage_rate, etc.)
    """
    if not code or not code.strip():
        return json.dumps({"error": "No code provided"})

    safety_error = check_code_safety(code)
    if safety_error:
        return json.dumps({"error": safety_error})

    full_code = _PREAMBLE + "\n" + code

    result = run_sandboxed(full_code, cwd=DB_PATH.parent)

    # If _raw key is present, return the raw string directly (Plotly/image JSON)
    if "_raw" in result:
        return result["_raw"]

    return json.dumps(result)


if __name__ == "__main__":
    mcp.run(transport="stdio")
