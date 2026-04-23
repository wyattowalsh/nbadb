# Chat Surface Manifest

## Purpose
- Inventory the current v1 chat surface across the shared `src/nbadb/chat/*` runtime, the app-local `chat/` shell, the app-local MCP entrypoints, and the current skill family.

## High-value paths

### Shared runtime assembly
| Path | Inventory role |
| --- | --- |
| `src/nbadb/chat/runtime/factory.py` | Builds the shared runtime context: DuckDB path, schema context, system prompt, and capability manifest. |
| `src/nbadb/chat/app/agent.py` | Canonical agent assembly: manager prompt, subagent split, deepagents-vs-Copilot branch, and skill-directory wiring. |
| `src/nbadb/chat/prompts.py` | Canonical prompt contract for workflow, tool families, profile overlays, and answer style. |
| `src/nbadb/chat/providers/factory.py` | Canonical non-Copilot model factory for provider-backed sessions. |
| `src/nbadb/chat/web/search.py` | Canonical local web-search tool implementation. |
| `src/nbadb/chat/web/fetch.py` | Canonical guarded web-fetch implementation. |

### App shell and local entrypoints
| Path | Inventory role |
| --- | --- |
| `chat/chainlit_app.py` | Canonical Chainlit UI shell, settings/profile surface, step rendering, and export actions. |
| `chat/chainlit.md` | User-facing app framing for profiles, providers, exports, and workflow. |
| `chat/pyproject.toml` | App dependency and launch surface for the Chainlit package. |
| `chat/server/agent.py` | Compatibility wrapper over the shared app agent assembly in `src/nbadb/chat/app/agent.py`. |
| `chat/server/prompts.py` | Compatibility wrapper over `src/nbadb/chat/prompts.py`. |
| `chat/server/tools/` | Compatibility wrappers over `src/nbadb/chat/web/*`. |

### Skill family and helper assets
| Path | Inventory role |
| --- | --- |
| `chat/skills/nba-data-analytics/SKILL.md` | Declares the NBA analytics skill, allowed tools, preferred table-selection patterns, SCD2 guidance, and helper APIs exposed inside `run_python`. |
| `chat/skills/nba-data-analytics/scripts/` | Metric, court, compare, stats, similarity, lineup, trend, team-color, and season helper modules. |
| `chat/skills/nba-data-analytics/references/query-cookbook.md` | Reusable SQL patterns for common NBA analytics questions. |
| `chat/skills/nba-data-analytics/references/schema-guide.md` | Lightweight table family map and common join patterns. |
| `chat/skills/nbadb-semantic-catalog/SKILL.md` | Semantic-first surface selection skill for grain and table-family routing. |
| `chat/skills/warehouse-query-writing/SKILL.md` | SQL drafting skill for warehouse-native query construction. |
| `chat/skills/data-quality-debugging/SKILL.md` | Result-debugging skill for empty, duplicated, or semantically suspicious outputs. |
| `chat/skills/analysis-and-visualization/SKILL.md` | Post-query analysis and visualization skill. |
| `chat/skills/artifact-creation/SKILL.md` | Artifact persistence and replay packaging skill. |
| `chat/skills/follow-up-refinement/SKILL.md` | Minimal-delta refinement skill for later turns. |
| `chat/skills/connector-usage/SKILL.md` | Runtime-capability adaptation skill for provider and sandbox differences. |
| `chat/skills/web-context-for-nba/SKILL.md` | Live-context augmentation skill for warehouse-external NBA facts. |

## Notes
- The current v1 split is deliberate:
  shared runtime logic lives in `src/nbadb/chat/*`,
  the Chainlit shell and stdio-facing entrypoints live in `chat/`,
  and domain workflow is expressed through the current `chat/skills/*` family.
- `chat/server/*` should be read as wrapper or shim surface unless the note is explicitly about app-local compatibility imports.
- The broad `nba-data-analytics` skill still carries the helper-script surface, but the current worktree also has narrower specialist skills for semantic planning, SQL drafting, debugging, visualization, artifact creation, refinement, connector differences, and live web context.

## Planned wiki coverage
- `wiki/topics/chat-surface.md`
- `wiki/topics/chainlit-runtime.md`
- `wiki/topics/prompt-assembly-and-capabilities.md`
- `wiki/topics/mcp-server-surface.md`
- `wiki/topics/chat-skill-surface.md`
- `wiki/topics/query-agent.md`
- `wiki/topics/analytics-skill-guide.md`
- `wiki/topics/query-cookbook-families.md`

## Provenance
- `src/nbadb/chat/runtime/factory.py`
- `src/nbadb/chat/app/agent.py`
- `src/nbadb/chat/prompts.py`
- `src/nbadb/chat/providers/factory.py`
- `src/nbadb/chat/web/search.py`
- `src/nbadb/chat/web/fetch.py`
- `chat/chainlit_app.py`
- `chat/chainlit.md`
- `chat/pyproject.toml`
- `chat/server/agent.py`
- `chat/server/prompts.py`
- `chat/skills/nba-data-analytics/SKILL.md`
- `chat/skills/nba-data-analytics/references/query-cookbook.md`
- `chat/skills/nba-data-analytics/references/schema-guide.md`
- `chat/skills/nbadb-semantic-catalog/SKILL.md`
- `chat/skills/warehouse-query-writing/SKILL.md`
- `chat/skills/data-quality-debugging/SKILL.md`
- `chat/skills/analysis-and-visualization/SKILL.md`
- `chat/skills/artifact-creation/SKILL.md`
- `chat/skills/follow-up-refinement/SKILL.md`
- `chat/skills/connector-usage/SKILL.md`
- `chat/skills/web-context-for-nba/SKILL.md`
