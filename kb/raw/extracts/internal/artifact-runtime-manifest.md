# Artifact Runtime Manifest

## Purpose
- Grouped internal extract for the chat/runtime artifact lane: durable artifact storage, transient export helpers, session code and notebook export, spreadsheet packaging, share outputs, and the file-delivery path back into Chainlit.

## High-value paths

### Durable artifact store
| Path | Inventory role |
| --- | --- |
| `src/nbadb/chat/artifacts/store.py` | Canonical `ArtifactStore`: roots at `~/.nbadb/chat/artifacts`, writes JSON bucket files, and mirrors templates/findings into `artifacts.sqlite3` plus FTS tables for lookup. |
| `src/nbadb/chat/artifacts/models.py` | Broader artifact vocabulary: `ArtifactKind`, `ArtifactPointer`, and `ResultEnvelope` distinguish export, notebook, script, template, and finding concepts even though the store persists only a subset. |
| `src/nbadb/chat/artifacts/__init__.py` | Public import surface for the artifact package. |
| `chat/mcp_servers/artifacts.py` | FastMCP wrapper around `ArtifactStore` for `save_template`, `load_template`, `list_templates`, `save_finding`, and `search_findings`. |
| `src/nbadb/chat/mcp/artifacts.py` | Canonical artifact MCP implementation used by the app-local stdio entrypoint. |
| `src/nbadb/chat/app/copilot_backend.py` | Backend-local mirror of template and finding persistence tools; shares the same storage contract without going through the MCP server. |

### Export and share helpers
| Path | Inventory role |
| --- | --- |
| `src/nbadb/chat/app/preamble.py` | Canonical sandbox helper surface for `to_csv`, `to_xlsx`, `to_json`, `export`, `to_embed`, `to_social`, and `to_thread`; emits base64 file payloads on stdout. |
| `src/nbadb/chat/sandbox/exec.py` | Detects structured sandbox stdout and classifies exports by `format` + `content` so the renderer can treat files differently from tables and charts. |
| `chat/mcp_servers/sandbox.py` | App-local stdio entrypoint that advertises the export/share helper inventory to `run_python` callers. |
| `src/nbadb/chat/mcp/sandbox.py` | Canonical sandbox MCP implementation and helper description surface. |

### Session script and notebook export
| Path | Inventory role |
| --- | --- |
| `chat/chainlit_app.py` | Owns no-code export callbacks for `session_code.py` and `session_analysis.ipynb`, tracks executed code in `code_log`, and writes reusable `.py` templates under `~/.nbadb/templates`. |
| `src/nbadb/chat/notebook.py` | Adjacent notebook utility layer for checked-out chat app discovery, pinned repo clone, and local DuckDB bootstrapping in notebook environments. |

### Spreadsheet template and delivery wiring
| Path | Inventory role |
| --- | --- |
| `src/nbadb/chat/app/spreadsheet_template.py` | Shared AG Grid HTML template used by the Chainlit spreadsheet action callback; current toolbar supports CSV export, JSON export, and reset. |
| `chat/chainlit_app.py` | SQL-result action lane: stores capped export payloads in session state, rebuilds DataFrames for CSV/XLSX/JSON delivery, and generates spreadsheet HTML files from query results. |

### File delivery flow
| Path | Inventory role |
| --- | --- |
| `chat/chainlit_app.py` | Final renderer: attaches `cl.File`, `cl.Image`, `cl.Plotly`, or `cl.Dataframe` elements, adds export actions, and handles expired session payloads. |
| `tests/unit/chat/test_chainlit_rendering.py` | Source-level guardrails for export-file detection, action presence, and payload capping in the rendering layer. |
| `tests/unit/chat/test_action_helpers.py` | Source-level checks for template-name sanitization, spreadsheet-template usage, and notebook export wiring. |
| `tests/unit/chat/test_preamble_helpers.py` | Coverage of helper presence and export/share function inventory in the sandbox preamble. |
| `tests/unit/chat/test_catalog_and_memory_services.py` | Runtime round-trip coverage for `ArtifactStore` templates and findings. |

## Notes
- The repo has two adjacent artifact lanes.
- Durable lane: `ArtifactStore` persists templates and findings under `~/.nbadb/chat/artifacts`, with both JSON files and an `artifacts.sqlite3` index backing template listing and finding search.
- Transient lane: sandbox export helpers print JSON payloads that contain `export_file`, `format`, and base64 `content`; Chainlit decodes those payloads into inline files for the current interaction.
- Template handling is split across two runtimes.
- Persistent analysis templates go through `ArtifactStore` as JSON envelopes.
- Session-code templates in `chainlit_app.py` are exported or saved as `.py` files under `~/.nbadb/templates` after `Path(...).stem` plus regex sanitization.
- Session export is driven by `code_log` in Chainlit session state.
- SQL steps append `run_sql` entries; non-SQL sandbox/chart/file steps append via `_add_code_actions()` and `_track_code()`.
- Script export writes a runnable Python file with imports, a DuckDB connection stub, and replayed steps.
- Notebook export writes an `.ipynb` with setup cells plus one markdown/code pair per tracked step.
- Spreadsheet flow is intentionally HTML-first.
- The SQL-result action callback delegates to `chat/server/_spreadsheet_template.py`.
- The sandbox helper surface and spreadsheet template now belong to the shared `src/nbadb/chat/app/*` layer. The `chat/server/*` mirrors should be treated as app-local compatibility shims only where they remain.
- Share helpers are file-oriented, not store-oriented.
- `to_embed()` emits a self-contained HTML snippet in an `nbadb-embed` wrapper.
- `to_social()` emits `social_card.png` as a branded 1200x630 PNG.
- `to_thread()` emits `thread.txt` with numbered lines.
- Delivery flow differs by source.
- SQL table exports use `cl.user_session["export_<step.id>"]` payloads capped at 100 rows, then rebuild the DataFrame inside `download_csv`, `download_xlsx`, `download_json`, and `edit_spreadsheet`.
- Sandbox exports bypass that session cache: `_sandbox_exec.py` classifies `format` + `content`, then `_render_tool_result()` or `_render_single_output()` base64-decodes the payload and attaches a `cl.File` immediately.
- Expired SQL export payloads fail soft with `Export data expired. Please re-run the query.` rather than trying to recover from disk.

## Planned wiki coverage
- `wiki/topics/artifact-runtime.md`
- `wiki/topics/file-delivery-flow.md`
- `wiki/topics/session-code-export.md`
- `wiki/topics/spreadsheet-export-surface.md`
- `wiki/topics/share-helper-surface.md`

## Provenance
- `src/nbadb/chat/artifacts/store.py`
- `src/nbadb/chat/artifacts/models.py`
- `src/nbadb/chat/artifacts/__init__.py`
- `src/nbadb/chat/mcp/artifacts.py`
- `chat/mcp_servers/artifacts.py`
- `src/nbadb/chat/app/copilot_backend.py`
- `src/nbadb/chat/app/preamble.py`
- `src/nbadb/chat/sandbox/exec.py`
- `src/nbadb/chat/app/spreadsheet_template.py`
- `src/nbadb/chat/mcp/sandbox.py`
- `chat/mcp_servers/sandbox.py`
- `chat/chainlit_app.py`
- `src/nbadb/chat/notebook.py`
- `tests/unit/chat/test_preamble_helpers.py`
- `tests/unit/chat/test_action_helpers.py`
- `tests/unit/chat/test_chainlit_rendering.py`
- `tests/unit/chat/test_catalog_and_memory_services.py`
