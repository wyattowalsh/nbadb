"""Shared Python sandbox preamble for MCP sandbox and Copilot backend."""

from __future__ import annotations

_PREAMBLE_TEMPLATE = '''\
import sys
import json
import warnings
warnings.filterwarnings("ignore")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Monkey-patch plt.show() to capture figures as base64 PNG
import io as _io
import base64 as _b64

def _patched_show(*args, **kwargs):
    buf = _io.BytesIO()
    plt.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                facecolor="#141a2e", edgecolor="none")
    buf.seek(0)
    img_b64 = _b64.b64encode(buf.read()).decode()
    print(json.dumps({"image_base64": img_b64, "format": "png"}))
    plt.close("all")

plt.show = _patched_show

import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import duckdb

try:
    import scipy.stats as stats
except ImportError:
    pass

# Read-only database connection
conn = duckdb.connect(__DB_PATH__, read_only=True)

# NBA metric calculator and skill scripts
sys.path.insert(0, __SKILLS_DIR__)
try:
    import metric_calculator as mc
    import team_colors
    import season_utils
except ImportError:
    pass

def query(sql: str) -> pd.DataFrame:
    """Shorthand to run SQL and return a DataFrame."""
    return conn.execute(sql).fetchdf()

# --- Session state (last_result persistence across tool calls) ---------------
import pathlib as _pathlib

_SESSION_DIR = _pathlib.Path.home() / ".nbadb" / "session"
_SESSION_DIR.mkdir(parents=True, exist_ok=True)
_LAST_RESULT_PATH = _SESSION_DIR / "last_result.parquet"

try:
    last_result = pd.read_parquet(_LAST_RESULT_PATH)
except Exception:
    last_result = pd.DataFrame()

def _save_last_result(df):
    """Persist DataFrame for next tool call."""
    global last_result
    last_result = df
    try:
        df.to_parquet(_LAST_RESULT_PATH, index=False)
    except Exception:
        pass

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

def to_csv(df, name="export"):
    """Export DataFrame as CSV and output for download."""
    csv_data = df.to_csv(index=False)
    print(json.dumps({"export_file": name + ".csv", "format": "csv",
                       "content": _b64.b64encode(csv_data.encode()).decode()}))

def to_xlsx(df, name="export"):
    """Export DataFrame as XLSX and output for download."""
    buf = _io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    print(json.dumps({"export_file": name + ".xlsx", "format": "xlsx",
                       "content": _b64.b64encode(buf.getvalue()).decode()}))

def to_json(df, name="export"):
    """Export DataFrame as JSON and output for download."""
    json_data = df.to_json(orient="records", indent=2)
    print(json.dumps({"export_file": name + ".json", "format": "json",
                       "content": _b64.b64encode(json_data.encode()).decode()}))

def export(df, name="export", fmt="csv"):
    """Export DataFrame in any format. fmt: csv, xlsx, json."""
    {"csv": to_csv, "xlsx": to_xlsx, "json": to_json}[fmt](df, name)

# --- Shareable output helpers ------------------------------------------------

def to_embed(fig, title=""):
    """Output a self-contained HTML snippet for blog/site embedding."""
    import plotly.io as _pio
    html = _pio.to_html(fig, full_html=False, include_plotlyjs="cdn")
    if title:
        html = f"<h3>{title}</h3>\\n" + html
    full = f"<div class='nbadb-embed'>\\n{html}\\n</div>"
    print(json.dumps({"export_file": (title or "chart") + ".html",
                       "format": "embed",
                       "content": _b64.b64encode(
                           full.encode()).decode()}))

def to_social(fig_or_df, headline, subtitle=""):
    """Render a 1200x630 branded PNG card for social media."""
    _fig, _ax = plt.subplots(figsize=(12, 6.3), dpi=100)
    _fig.patch.set_facecolor("#1D428A")
    _fig.text(0.05, 0.88, headline, fontsize=28,
             fontweight="bold", color="white",
             transform=_fig.transFigure)
    if subtitle:
        _fig.text(0.05, 0.80, subtitle, fontsize=16,
                 color="#C8C8C8", transform=_fig.transFigure)
    if isinstance(fig_or_df, pd.DataFrame):
        text = fig_or_df.head(8).to_string(index=False)
        _fig.text(0.05, 0.10, text, fontsize=11,
                 fontfamily="monospace", color="white",
                 transform=_fig.transFigure,
                 verticalalignment="bottom")
    _fig.text(0.95, 0.02, "nbadb", fontsize=10, color="#666",
             ha="right", transform=_fig.transFigure)
    _ax.axis("off")
    buf = _io.BytesIO()
    _fig.savefig(buf, format="png", bbox_inches="tight",
                facecolor="#1D428A", edgecolor="none")
    plt.close(_fig)
    buf.seek(0)
    print(json.dumps({"export_file": "social_card.png",
                       "format": "social",
                       "content": _b64.b64encode(
                           buf.read()).decode()}))

def to_thread(insights):
    """Format insights as a numbered thread for social media."""
    if isinstance(insights, str):
        insights = [l.strip() for l in insights.strip().split("\\n")
                    if l.strip()]
    thread = "\\n".join(
        f"{i}/ {s}" for i, s in enumerate(insights, 1))
    print(json.dumps({"export_file": "thread.txt",
                       "format": "thread",
                       "content": _b64.b64encode(
                           thread.encode()).decode()}))

def to_spreadsheet(df, name="data"):
    """Generate a self-contained HTML file with an editable spreadsheet.

    The HTML file embeds AG Grid (community) for in-browser editing with
    built-in sorting, filtering, and export buttons (CSV, XLSX).
    Users download the HTML file and open it in any browser to edit.
    """
    columns_json = json.dumps([{"field": c, "editable": True, "sortable": True,
                                 "filter": True} for c in df.columns])
    rows_json = df.to_json(orient="records")
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{name} — NBA Data Spreadsheet</title>
<script src="https://cdn.jsdelivr.net/npm/ag-grid-community@33/dist/ag-grid-community.min.js"></script>
<style>
  body {{ font-family: Inter, system-ui, sans-serif; margin: 0;
         padding: 16px; background: #fafafa; }}
  h1 {{ font-size: 1.25rem; color: #1D428A; margin: 0 0 12px; }}
  .toolbar {{ display: flex; gap: 8px; margin-bottom: 12px; }}
  .toolbar button {{
    padding: 6px 16px; border: 1px solid #ddd; border-radius: 6px;
    background: #fff; cursor: pointer; font-size: 0.875rem;
  }}
  .toolbar button:hover {{ background: #f0f0f0; }}
  #grid {{ height: calc(100vh - 100px); width: 100%; }}
  .ag-theme-alpine {{ --ag-font-family: Inter, system-ui, sans-serif; }}
</style>
</head>
<body>
<h1>{name}</h1>
<div class="toolbar">
  <button onclick="exportCSV()">Export CSV</button>
  <button onclick="exportJSON()">Export JSON</button>
  <button onclick="resetData()">Reset</button>
  <span id="status" style="line-height:32px;color:#666;font-size:0.8rem;"></span>
</div>
<div id="grid" class="ag-theme-alpine"></div>
<script>
const originalData = {rows_json};
const columnDefs = {columns_json};
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
function exportCSV() {{
  const rows = getRows();
  const cols = columnDefs.map(c => c.field);
  const hdr = cols.join(",");
  const body = rows.map(r => cols.map(c =>
    JSON.stringify(r[c] ?? "")).join(","));
  const csv = [hdr, ...body].join("\\n");
  download(csv, "{name}.csv", "text/csv");
}}
function exportJSON() {{
  download(JSON.stringify(getRows(), null, 2), "{name}.json", "application/json");
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
}}
</script>
</body>
</html>"""
    print(json.dumps({{"export_file": name + ".html", "format": "spreadsheet",
                       "content": _b64.b64encode(html.encode()).decode()}}))
'''


def build_preamble(db_path: str, skills_dir: str) -> str:
    """Build the Python sandbox preamble with the given DB path and skills dir.

    Uses explicit string replacement instead of str.format() to avoid
    injection if db_path or skills_dir contain curly braces.
    """
    return _PREAMBLE_TEMPLATE.replace("__DB_PATH__", repr(db_path)).replace(
        "__SKILLS_DIR__", repr(skills_dir)
    )
