"""Shared AG Grid spreadsheet HTML template.

Both ``chainlit_app.py`` (action callback) and ``_preamble.py`` (sandbox helper)
delegate to this module so the template is maintained in one place.
"""

from __future__ import annotations

import html
import json


def build_spreadsheet_html(name: str, columns_json: str, rows_json: str) -> str:
    """Generate a self-contained HTML file with an AG Grid editable spreadsheet."""
    safe_name = json.dumps(name)[1:-1]  # JSON-encode, strip quotes -- safe for JS string literal
    html_safe_name = html.escape(safe_name)  # Safe for HTML contexts
    safe_rows = rows_json.replace("</", "<\\/")
    safe_cols = columns_json.replace("</", "<\\/")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html_safe_name} — NBA Data Spreadsheet</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/ag-grid-community@33.2.4/dist/ag-grid-community.min.js"
  onerror="document.getElementById('grid').textContent='AG Grid failed to load.'"></script>
<style>
  body {{ font-family: Inter, system-ui, sans-serif; margin: 0;
         padding: 16px; background: #fafafa;
         display:flex;flex-direction:column;height:100vh; }}
  h1 {{ font-size: 1.25rem; color: #1D428A; margin: 0 0 12px; }}
  .toolbar {{ display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }}
  .toolbar button {{
    padding: 6px 16px; border: 1px solid #ddd; border-radius: 6px;
    background: #fff; cursor: pointer; font-size: 0.875rem;
  }}
  .toolbar button:hover, .toolbar button:focus-visible {{ background: #f0f0f0; }}
  #grid {{ flex:1;min-height:0;width:100%; }}
  .ag-theme-alpine {{ --ag-font-family: Inter, system-ui, sans-serif; }}
</style>
</head>
<body>
<h1>{html_safe_name}</h1>
<div class="toolbar">
  <button type="button" onclick="exportCSV()">Export CSV</button>
  <button type="button" onclick="exportJSON()">Export JSON</button>
  <button type="button" onclick="resetData()">Reset</button>
  <span id="status" role="status" style="line-height:32px;color:#666;font-size:0.8rem;"></span>
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
