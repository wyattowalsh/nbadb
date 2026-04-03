"""Shared Python sandbox preamble for MCP sandbox and Copilot backend."""

from __future__ import annotations

from pathlib import Path

_PREAMBLE_TEMPLATE = '''\
import sys
import json
import html as _html
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, __SERVER_DIR__)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Monkey-patch plt.show() to capture figures as base64 PNG
import io as _io
import base64 as _b64

def _patched_show(*args, _io_mod=_io, _b64_mod=_b64, _json=json, _plt=plt, **kwargs):
    buf = _io_mod.BytesIO()
    _plt.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                 facecolor="#141a2e", edgecolor="none")
    buf.seek(0)
    img_b64 = _b64_mod.b64encode(buf.read()).decode()
    print(_json.dumps({"image_base64": img_b64, "format": "png"}))
    _plt.close("all")

plt.show = _patched_show

import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import duckdb as _duckdb
from _safety import ReadOnlyGuard as _ReadOnlyGuard

try:
    import scipy.stats as stats
except ImportError:
    pass

# Read-only database connection
_RAW_CONN = _duckdb.connect(__DB_PATH__, read_only=True)
_RAW_CONN.execute("SET enable_external_access = false")
del _duckdb

_READ_ONLY_GUARD = _ReadOnlyGuard()
_READ_ONLY_MAX_ROWS = 1000

def _prepare_sql(sql: str) -> str:
    error = _READ_ONLY_GUARD.validate(sql)
    if error:
        raise ValueError(error)
    return _READ_ONLY_GUARD.wrap_with_limit(sql, max_rows=_READ_ONLY_MAX_ROWS)

def _safe_execute(sql: str, *args, _raw_conn=_RAW_CONN, **kwargs):
    return _raw_conn.execute(_prepare_sql(sql), *args, **kwargs)

def _safe_sql(sql: str, *args, _raw_conn=_RAW_CONN, **kwargs):
    return _raw_conn.sql(_prepare_sql(sql), *args, **kwargs)

class _SafeConn:
    def execute(self, sql: str, *args, _executor=_safe_execute, **kwargs):
        return _executor(sql, *args, **kwargs)

    def sql(self, sql: str, *args, _executor=_safe_sql, **kwargs):
        return _executor(sql, *args, **kwargs)

conn = _SafeConn()
del _RAW_CONN

# NBA metric calculator and skill scripts
sys.path.insert(0, __SKILLS_DIR__)
try:
    import metric_calculator as mc
    import team_colors
    import season_utils
    import court
    import compare
    import nba_stats
    import similarity
    import lineups
    import trends
except ImportError:
    pass

def query(sql: str) -> pd.DataFrame:
    """Shorthand to run SQL and return a DataFrame."""
    return conn.execute(sql).fetchdf()

# --- Session state (last_result persistence across tool calls) ---------------
from pathlib import Path as _SessionPath

_LAST_RESULT_PATH = _SessionPath(__SESSION_DIR__) / "last_result.parquet"
_LAST_RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)

try:
    last_result = pd.read_parquet(_LAST_RESULT_PATH)
except Exception:
    last_result = pd.DataFrame()

def _save_last_result(df, _last_result_path=_LAST_RESULT_PATH):
    """Persist DataFrame for next tool call."""
    global last_result
    last_result = df
    try:
        df.to_parquet(_last_result_path, index=False)
    except Exception:
        pass

del _SessionPath

# --- Display helpers ---------------------------------------------------------

def chart(fig):
    """Output a Plotly figure for display in the chat."""
    print(fig.to_json())

def annotated_chart(fig, df=None, metric_col=None):
    """Output a Plotly chart with automatic reference annotations."""
    if df is not None and metric_col and metric_col in df.columns:
        vals = df[metric_col].dropna()
        if len(vals) >= 3:
            avg = float(vals.mean())
            fig.add_hline(
                y=avg, line_dash="dash", line_color="#999",
                annotation_text=f"Avg: {avg:.1f}")
    chart(fig)

def table(df):
    """Output a DataFrame for display and save as last_result."""
    _save_last_result(df)
    print(df.to_json(orient="split"))

def show(data):
    """Smart output — auto-detects Plotly figures vs DataFrames."""
    if hasattr(data, "to_json") and hasattr(data, "data") and hasattr(data, "layout"):
        chart(data)
    elif isinstance(data, pd.DataFrame):
        table(data)
    else:
        print(data)

# --- Export helpers -----------------------------------------------------------

def to_csv(df, name="export", _json=json, _b64_mod=_b64):
    """Export DataFrame as CSV and output for download."""
    csv_data = df.to_csv(index=False)
    print(_json.dumps({"export_file": name + ".csv", "format": "csv",
                       "content": _b64_mod.b64encode(csv_data.encode()).decode()}))

def to_xlsx(df, name="export", _io_mod=_io, _json=json, _b64_mod=_b64):
    """Export DataFrame as XLSX and output for download."""
    buf = _io_mod.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    print(_json.dumps({"export_file": name + ".xlsx", "format": "xlsx",
                       "content": _b64_mod.b64encode(buf.getvalue()).decode()}))

def to_json(df, name="export", _json=json, _b64_mod=_b64):
    """Export DataFrame as JSON and output for download."""
    json_data = df.to_json(orient="records", indent=2)
    print(_json.dumps({"export_file": name + ".json", "format": "json",
                       "content": _b64_mod.b64encode(json_data.encode()).decode()}))

def export(df, name="export", fmt="csv"):
    """Export DataFrame in any format. fmt: csv, xlsx, json."""
    {"csv": to_csv, "xlsx": to_xlsx, "json": to_json}[fmt](df, name)

# --- Shareable output helpers ------------------------------------------------

def to_embed(fig, title="", _json=json, _b64_mod=_b64):
    """Output a self-contained HTML snippet for blog/site embedding."""
    import plotly.io as _pio
    html = _pio.to_html(fig, full_html=False, include_plotlyjs="cdn")
    if title:
        html = f"<h3>{_html.escape(title)}</h3>\\n" + html
    full = f"<div class='nbadb-embed'>\\n{html}\\n</div>"
    import re as _re_embed
    _safe_fn = _re_embed.sub(r'[^\\w\\s-]', '', title or "chart").strip()[:50] or "chart"
    del _re_embed
    print(_json.dumps({"export_file": _safe_fn + ".html",
                       "format": "embed",
                       "content": _b64_mod.b64encode(
                           full.encode()).decode()}))

def to_social(
    fig_or_df,
    headline,
    subtitle="",
    _plt=plt,
    _pd=pd,
    _io_mod=_io,
    _json=json,
    _b64_mod=_b64,
):
    """Render a 1200x630 branded PNG card for social media."""
    _fig, _ax = _plt.subplots(figsize=(12, 6.3), dpi=100)
    _fig.patch.set_facecolor("#1D428A")
    _fig.text(0.05, 0.88, headline, fontsize=28,
             fontweight="bold", color="white",
             transform=_fig.transFigure)
    if subtitle:
        _fig.text(0.05, 0.80, subtitle, fontsize=16,
                 color="#C8C8C8", transform=_fig.transFigure)
    if isinstance(fig_or_df, _pd.DataFrame):
        text = fig_or_df.head(8).to_string(index=False)
        _fig.text(0.05, 0.10, text, fontsize=11,
                 fontfamily="monospace", color="white",
                 transform=_fig.transFigure,
                 verticalalignment="bottom")
    _fig.text(0.95, 0.02, "nbadb", fontsize=10, color="#666",
             ha="right", transform=_fig.transFigure)
    _ax.axis("off")
    buf = _io_mod.BytesIO()
    _fig.savefig(buf, format="png", bbox_inches="tight",
                facecolor="#1D428A", edgecolor="none")
    _plt.close(_fig)
    buf.seek(0)
    print(_json.dumps({"export_file": "social_card.png",
                       "format": "social",
                       "content": _b64_mod.b64encode(
                           buf.read()).decode()}))

def to_thread(insights, _json=json, _b64_mod=_b64):
    """Format insights as a numbered thread for social media."""
    if isinstance(insights, str):
        insights = [l.strip() for l in insights.strip().split("\\n")
                    if l.strip()]
    thread = "\\n".join(
        f"{i}/ {s}" for i, s in enumerate(insights, 1))
    print(_json.dumps({"export_file": "thread.txt",
                       "format": "thread",
                       "content": _b64_mod.b64encode(
                           thread.encode()).decode()}))

def to_spreadsheet(df, name="data", _json=json, _b64_mod=_b64, _html_mod=_html):
    """Generate a self-contained HTML file with an editable spreadsheet.

    The HTML file embeds AG Grid (community) for in-browser editing with
    built-in sorting, filtering, and export buttons (CSV, XLSX).
    Users download the HTML file and open it in any browser to edit.
    """
    columns_json = _json.dumps([{"field": c, "editable": True, "sortable": True,
                                  "filter": True} for c in df.columns])
    rows_json = df.to_json(orient="records") or "[]"
    safe_name = _html_mod.escape(name)
    safe_rows = rows_json.replace("</", "<\\/")
    safe_cols = columns_json.replace("</", "<\\/")
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{safe_name} — NBA Data Spreadsheet</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/ag-grid-community@33.2.4/dist/ag-grid-community.min.js"
  onerror="document.getElementById('grid').textContent='AG Grid failed to load.'"></script>
<style>
  body {{ font-family: Inter, system-ui, sans-serif; margin: 0;
         padding: 16px; background: #fafafa; }}
  h1 {{ font-size: 1.25rem; color: #1D428A; margin: 0 0 12px; }}
  .toolbar {{ display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }}
  .toolbar button {{
    padding: 6px 16px; border: 1px solid #ddd; border-radius: 6px;
    background: #fff; cursor: pointer; font-size: 0.875rem;
  }}
  .toolbar button:hover, .toolbar button:focus-visible {{ background: #f0f0f0; }}
  #grid {{ height: calc(100vh - 100px); width: 100%; }}
  .ag-theme-alpine {{ --ag-font-family: Inter, system-ui, sans-serif; }}
</style>
</head>
<body>
<h1>{safe_name}</h1>
<div class="toolbar">
  <button onclick="exportCSV()">Export CSV</button>
  <button onclick="exportJSON()">Export JSON</button>
  <button onclick="resetData()">Reset</button>
  <span id="status" style="line-height:32px;color:#666;font-size:0.8rem;"></span>
</div>
<div id="grid" class="ag-theme-alpine"></div>
<script>
const originalData = {safe_rows};
const columnDefs = {safe_cols};
const gridOptions = {{
  columnDefs: columnDefs,
  rowData: JSON.parse(JSON.stringify(originalData)),
  defaultColDef: {{ resizable: true, editable: true, sortable: true, filter: true }},
  onCellValueChanged: () => document.getElementById("status").textContent = "Modified",
}};
const gridDiv = document.getElementById("grid");
const api = agGrid.createGrid(gridDiv, gridOptions);

function getRows() {{
  const rows = [];
  api.forEachNode(n => rows.push(n.data));
  return rows;
}}
function csvEscape(val) {{
  const s = String(val ?? "");
  return /[",\\n\\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}}
function exportCSV() {{
  const rows = getRows();
  const cols = columnDefs.map(c => c.field);
  const hdr = cols.map(csvEscape).join(",");
  const body = rows.map(r => cols.map(c => csvEscape(r[c])).join(","));
  const csv = [hdr, ...body].join("\\n");
  download(csv, "{safe_name}.csv", "text/csv");
}}
function exportJSON() {{
  download(JSON.stringify(getRows(), null, 2), "{safe_name}.json", "application/json");
}}
function resetData() {{
  api.setGridOption("rowData", JSON.parse(JSON.stringify(originalData)));
  document.getElementById("status").textContent = "Reset";
}}
function download(content, filename, type) {{
  const blob = new Blob([content], {{ type }});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}}
</script>
</body>
</html>"""
    print(_json.dumps({{"export_file": name + ".html", "format": "spreadsheet",
                        "content": _b64_mod.b64encode(html.encode()).decode()}}))

# Reduce the executed namespace to intended analytics helpers only.
del sys
del warnings
del _io
del _b64
del _html
del _ReadOnlyGuard
del _READ_ONLY_GUARD
del _READ_ONLY_MAX_ROWS
del _prepare_sql
del _safe_execute
del _safe_sql
del _SafeConn
del _patched_show
del _save_last_result
del _LAST_RESULT_PATH
'''


def build_preamble(db_path: str, skills_dir: str, session_dir: str) -> str:
    """Build the Python sandbox preamble with the given DB path and skills dir.

    Uses explicit string replacement instead of str.format() to avoid
    injection if db_path, skills_dir, or session_dir contain curly braces.
    """
    return (
        _PREAMBLE_TEMPLATE.replace("__DB_PATH__", repr(db_path))
        .replace("__SERVER_DIR__", repr(str(Path(__file__).resolve().parent)))
        .replace("__SKILLS_DIR__", repr(skills_dir))
        .replace("__SESSION_DIR__", repr(session_dir))
    )
