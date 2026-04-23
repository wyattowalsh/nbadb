---
title: Sandbox Runtime Contract
tags:
  - kb
  - topics
  - chat
  - sandbox
  - runtime
  - trust-boundary
aliases:
  - Python Sandbox Contract
  - Chat Sandbox Runtime
kind: concept
status: active
updated: 2026-04-22
source_count: 9
---

# Sandbox Runtime Contract

Use this note for the narrow question: "what exactly do `run_sql` and `run_python` accept, execute, emit, and trust in the chat runtime?"

## Contract summary
The sandbox runtime is split across two execution lanes:
- `run_sql`: read-only DuckDB execution that returns structured table JSON
- `run_python`: subprocess Python execution with a prebuilt analytics preamble, structured stdout parsing, and UI-oriented payload conventions

The prompt describes the intended workflow, but the real contract lives in the shared executors, sandbox preamble, and Chainlit renderer.

## `run_sql` contract
`run_sql` is the canonical structured SQL tool exposed by both `src/nbadb/chat/mcp/sql.py` and `src/nbadb/chat/app/copilot_backend.py`.

Execution policy:
- validates SQL with `ReadOnlyGuard`
- wraps `SELECT` and `WITH` queries in a hard outer `LIMIT 1000`
- opens DuckDB with `read_only=True`
- disables DuckDB external access with `SET enable_external_access = false`
- applies a 30-second statement timeout when DuckDB supports it

Success shape:

```json
{
  "columns": ["player_name", "pts"],
  "rows": ["example row omitted"],
  "row_count": 1,
  "sql": "SELECT ..."
}
```

Failure shape:

```json
{
  "error": "Query blocked: ..."
}
```

or:

```json
{
  "error": "Query failed: CatalogException"
}
```

## `run_python` environment
`run_python` prepends a generated preamble to the user code, runs the combined script in a subprocess, then parses stdout line-by-line for known JSON payloads.

Base environment inside the sandbox:
- `pd`, `np`, `px`, `go`, `plt`
- `stats` when `scipy.stats` is importable
- matplotlib forced to `Agg`
- warnings globally suppressed

Database access surface:
- `conn.execute(sql)`
- `conn.sql(sql)`
- `query(sql)` returning a pandas DataFrame

Important constraint: those helpers route through the same read-only SQL guard logic as `run_sql`. The raw `duckdb` module is used during preamble setup, then deleted from the executed namespace.

## Preamble helpers
The preamble adds three main helper families.

### Display helpers
- `chart(fig)`: prints Plotly JSON
- `annotated_chart(fig, df, metric_col)`: adds an average reference line before printing Plotly JSON
- `table(df)`: saves `last_result` and prints DataFrame JSON with `orient="split"`
- `show(data)`: routes Plotly figures to `chart`, DataFrames to `table`, everything else to `print`
- patched `plt.show()`: emits `{"image_base64": ..., "format": "png"}`

### Export and share helpers
- `to_csv(df, name)`
- `to_xlsx(df, name)`
- `to_json(df, name)`
- `export(df, name, fmt)`
- `to_spreadsheet(df, name)`
- `to_embed(fig, title)`
- `to_social(fig_or_df, headline, subtitle)`
- `to_thread(insights)`

All of these emit JSON to stdout with at least `format`, `export_file`, and base64 `content`.

### Session and skill helpers
- `last_result`: restored from `~/.nbadb/session/<session_id>/last_result.parquet`
- `mc`: `metric_calculator`
- also pre-imports `team_colors`, `season_utils`, `court`, `compare`, `nba_stats`, `similarity`, `lineups`, and `trends`

That means `run_python` is not a blank Python shell. It is a purpose-built NBA analytics environment with session persistence and prewired helper modules.

## Rendering payload shapes
The parser in `_sandbox_exec.py` and the Chainlit renderer together define the effective output contract.
The canonical parser implementation lives in `src/nbadb/chat/sandbox/exec.py`; `chat/server/_sandbox_exec.py` is only a compatibility wrapper.

### Single-output shapes
| Producer | Parsed shape | Chainlit rendering |
|----------|--------------|-------------------|
| `run_sql` or `table(df)` | `{"columns": [...], "rows": [...], "row_count": n}` | inline dataframe |
| `chart(fig)` | raw JSON string with `data` and `layout` | interactive `cl.Plotly` |
| patched `plt.show()` | raw JSON string with `image_base64` and `format` | inline image |
| export/share helpers | raw JSON string with `export_file`, `format`, `content` | inline file |
| plain `print(...)` only | `{"stdout": "...", "stderr": "..."}` | fenced text |
| execution failure | `{"error": "...", "stdout": "..."}` | error block, optional prior stdout |

### Multi-output shape
If one Python run prints multiple recognized JSON payloads, `_sandbox_exec.py` returns:

```json
{
  "_multi": [
    {"_type": "dataframe", "columns": [...], "rows": [...], "row_count": 3},
    {"_type": "plotly", "_raw": "{...}"},
    {"_type": "csv", "_raw": "{...}"}
  ],
  "stdout": "plain text that was not structured JSON",
  "stderr": ""
}
```

Important rendering nuance:
- single Plotly outputs stay interactive
- Plotly inside `_multi` is converted to a PNG and rendered as `cl.Image`
- export-like `_multi` items become inline files
- plain leftover text is preserved separately as `stdout`

## Trust boundaries
### What is enforced in code
- SQL safety: `ReadOnlyGuard` plus read-only DuckDB plus external access disabled
- Python safety: AST validation blocks dangerous imports, builtins, file I/O, network access, direct DuckDB calls, and introspection escape routes
- environment scrubbing: subprocess gets an allowlisted environment only
- resource limits: 512 MB address space target, 10 MB file size, 65-second CPU cap, no forking where supported
- wall-clock timeout: sandbox subprocess is killed after 60 seconds

### What is guidance, not enforcement
- the system prompt and tool descriptions
- the intended workflow of "SQL first, Python second"
- assumptions about how model-generated code will behave before validation

### Important boundary distinctions
- `run_sql` is the cleanest structured trust boundary for data retrieval
- `run_python` is broader, but it is still not raw local Python; it is a constrained subprocess plus a curated namespace
- extra MCP servers are outside this contract; built-in sandbox rules do not automatically constrain user-configured external MCP tools

## Practical maintainer takeaways
- If a chat rendering bug appears, inspect the payload shape first, not the model trace.
- If a Python helper change prints a different JSON envelope, Chainlit may silently render it as generic JSON instead of a chart, file, or table.
- If a capability is only mentioned in a prompt or docstring, treat it as advisory until you confirm the executor or preamble enforces it.

## Related notes
- [[wiki/topics/query-safety|Query Safety]]
- [[wiki/topics/chainlit-runtime|Chainlit Runtime]]
- [[wiki/topics/visualization-surface|Visualization Surface]]
- [[wiki/topics/export-share-artifacts|Export Share Artifacts]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| MCP `run_python` tool description, preamble injection, raw return behavior | `src/nbadb/chat/mcp/sandbox.py` | canonical Python tool entry point |
| MCP `run_sql` tool shape and shared executor usage | `src/nbadb/chat/mcp/sql.py` | canonical SQL MCP surface |
| shared SQL execution rules and return envelope | `src/nbadb/chat/sql/exec.py` | read-only mode, external access off, timeout, `{columns, rows, row_count, sql}` |
| sandbox preamble imports, safe connection, helper functions, `last_result`, and namespace cleanup | `src/nbadb/chat/app/preamble.py` | canonical Python runtime environment |
| AST blocking rules, env allowlist, subprocess timeout, resource limits, and structured-output parser | `src/nbadb/chat/sandbox/exec.py`; `chat/server/_sandbox_exec.py` | canonical safety layer plus compatibility wrapper boundary |
| Chainlit rendering behavior for single and multi-output payloads | `chat/chainlit_app.py` | dataframe, Plotly, image, file, stdout, and `_multi` rendering |
| prompt-level workflow framing | `src/nbadb/chat/prompts.py` | guidance layer, not enforcement |
| repo-wide SQL trust-boundary interpretation | `kb/wiki/topics/query-safety.md` | companion note for safety framing |
| UI/runtime responsibility split and sandbox helper summary | `kb/wiki/topics/chainlit-runtime.md` | companion note for renderer and session behavior |
