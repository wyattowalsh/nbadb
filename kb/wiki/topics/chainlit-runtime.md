---
title: Chainlit Runtime
tags:
  - kb
  - topics
  - chat
  - chainlit
  - runtime
aliases:
  - Chat Chainlit Runtime
  - Chainlit App Runtime
kind: concept
status: active
updated: 2026-04-14
source_count: 9
---

# Chainlit Runtime

This note covers the `chat/chainlit_app.py` runtime surface: the Chainlit UI shell that owns session setup, settings changes, message streaming, step rendering, and export actions for the richer NBA analytics assistant.

## What the Chainlit layer is responsible for
The Chainlit app is not the agent itself.

It is the session and presentation layer that:
- defines chat profiles and starter prompts
- collects provider and model settings from the gear panel
- creates or rebuilds the assembled agent for the current session
- streams assistant text tokens into the main response message
- renders tool outputs into typed `Step` blocks with tables, charts, files, and actions
- tracks per-session code and export payloads for later download

## Lifecycle hooks
### Chat start
`@cl.on_chat_start` does the initial session boot:
1. sanitize and store the session id
2. garbage-collect old session directories once per process
3. derive initial `ChatSettings`, including profile-specific adjustments
4. initialize session state such as `agent`, `callbacks`, and `code_log`
5. render the settings panel
6. create the agent with `create_nba_agent(...)`
7. attach tracing callbacks via `setup_tracing(...)`

If the app is running in public-demo mode without a user-supplied key, the UI stops at the setup message instead of creating an agent.

### Settings update
`@cl.on_settings_update` validates the new settings, attempts a fresh agent build, and only swaps the session agent after the rebuild succeeds. If rebuild fails, the previous agent stays active.

### Chat end
`@cl.on_chat_end` calls `agent.cleanup()` if available, then removes the current persisted session state directory.

## Event flow
`@cl.on_message` is the main event loop.

Current flow:
1. fetch the current session agent and tracing callbacks
2. create an empty `cl.Message` response shell
3. call `agent.astream({"messages": [HumanMessage(...)]}, stream_mode="messages", config=...)`
4. ignore non-tuple stream events
5. stream `AIMessage` string content directly into the response token-by-token
6. open a `cl.Step(type="tool")` for each `ToolMessage`
7. copy tool input metadata into `step.input`
8. pass the tool payload to `_render_tool_result(...)`
9. finalize the response with `response.update()` even on failure

The important split is simple: assistant prose streams into the main message, while tool work is rendered as separate typed steps.

## Rendering surface
### SQL-style tabular outputs
When tool JSON contains `columns` and `rows`, the runtime renders:
- `cl.Dataframe` inline
- a textual caption with row count and echoed SQL
- lightweight numeric annotations for the first few numeric columns
- a small-sample note for tiny result sets

It also stores a capped export payload in session state under `export_{step.id}` so later button clicks do not need to rerun the query.

### Plotly and matplotlib
The renderer treats chart payloads differently based on shape:
- single Plotly payloads with `data` and `layout` become interactive `cl.Plotly`
- matplotlib payloads with `image_base64` become inline `cl.Image`
- multi-output sandbox bundles are rendered one item at a time; in that path, Plotly JSON is converted to a PNG and shown as `cl.Image`, while matplotlib also stays image-based

That means the runtime supports both rich interactive Plotly and simpler image-only chart rendering, depending on how the sandbox packaged the output.

### Files and raw output
- export payloads with `export_file` and `content` become inline `cl.File`
- stdout and stderr are rendered as fenced code blocks
- unrecognized structured payloads fall back to formatted JSON

## Artifacts and export paths
### Immediate step actions
The Chainlit runtime adds action buttons directly to rendered steps.

For SQL result steps, the common actions are:
- `Copy SQL`
- `CSV`
- `XLSX`
- `JSON`
- `Edit as Spreadsheet`
- `Refine`
- `Export Code`
- `Save Template`

For code-producing steps, `_add_code_actions(...)` adds:
- `Copy Code`
- `Export All Code`
- `Export as Notebook`

### Session-scoped reproducibility
The UI keeps a `code_log` in `cl.user_session`. That log powers:
- Python script export for the whole session
- notebook export for the whole session
- reusable template generation from the session code history

### Sandbox display and share helpers
The Python sandbox preamble shapes what Chainlit receives back from analysis code.

It provides:
- `chart(fig)` and `annotated_chart(...)` for Plotly
- `table(df)` and `show(...)` for DataFrame-aware display
- patched `plt.show()` that emits base64 PNG JSON
- `to_csv`, `to_xlsx`, `to_json`, and `to_spreadsheet` for downloadable artifacts
- `to_embed`, `to_social`, and `to_thread` for share-oriented outputs
- persisted `last_result` between tool calls inside the session directory

### Artifact store relationship
Separate from Chainlit button exports, the app also exposes an MCP artifact server for reusable templates and findings. That server uses `ArtifactStore` under `~/.nbadb/chat/artifacts`, so the agent can save and search durable artifacts even though the UI itself mostly works with inline files and session state.

## Relationship to the assembled agent
The Chainlit runtime depends on `create_nba_agent(...)` but does not define the analytical behavior by itself.

`create_nba_agent(...)` assembles the real agent in three stages:
1. build runtime context: ensure the database exists, load schema context, build the system prompt, and compute capability flags
2. select backend: Copilot runtime or deepagents runtime
3. wrap the result in `NbaAgentWrapper`, which normalizes `astream(...)` and `cleanup()`

For the deepagents path, the assembled agent includes:
- the chosen chat model
- MCP tools
- optional local `web_search` and `web_fetch`
- skills from `chat/skills`
- a `LocalShellBackend` rooted at the database directory
- the schema-injected system prompt, optionally extended by the selected Chainlit profile

This is the key boundary:
- Chainlit owns interaction, rendering, and session ergonomics
- the assembled agent owns reasoning, tool choice, SQL and Python execution, and artifact generation

## Related notes
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/query-agent|Query Agent]]
- [[wiki/topics/visualization-surface|Visualization Surface]]
- [[wiki/topics/analytics-skill-guide|Analytics Skill Guide]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| Chainlit hook set, profiles, actions, message loop, step renderer | `chat/chainlit_app.py` | canonical UI runtime surface |
| assembled agent wrapper and backend split | `chat/server/agent.py` | `NbaAgentWrapper`, `create_nba_agent`, deepagents vs Copilot |
| sandbox display and export helper contract | `chat/server/_preamble.py` | `chart`, `table`, patched `plt.show()`, export and share helpers |
| durable artifact MCP tool surface | `chat/mcp_servers/artifacts.py` | save and search findings/templates via MCP |
| runtime context assembly | `src/nbadb/chat/runtime/factory.py` | DB path, schema context, prompt, capabilities |
| system prompt and profile augmentation | `src/nbadb/chat/prompts.py` | workflow contract and profile-specific instructions |
| capability manifest shape | `src/nbadb/chat/runtime/capabilities.py` | capability flags attached to assembled agent |
| durable artifact storage location and file shape | `src/nbadb/chat/artifacts/store.py` | backing store for templates and findings |
| user-facing chat feature summary | `chat/chainlit.md` | welcome copy for exports, sharing, iteration, and profiles |
