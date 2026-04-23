# Chat Surface Manifest

## Purpose
- Inventory the current `chat` runtime surface: agent assembly, prompt contract, analytics skill package, and bundled helper/reference assets.

## High-value paths

### Runtime assembly
| Path | Inventory role |
| --- | --- |
| `chat/server/agent.py` | Builds the chat agent, injects schema-aware prompt/context, selects `copilot` vs `deepagents`, wires MCP tools plus local web tools, and points skills loading at `chat/skills/`. |
| `chat/server/prompts.py` | Defines the canonical system prompt: workflow, tool usage rules, chart/export helpers, session state, profile overlays, and style/error-recovery guidance. |

### Analytics skill package
| Path | Inventory role |
| --- | --- |
| `chat/skills/nba-data-analytics/SKILL.md` | Declares the NBA analytics skill, allowed tools, preferred table-selection patterns, SCD2 guidance, and helper APIs exposed inside `run_python`. |
| `chat/skills/nba-data-analytics/scripts/` | Metric, court, compare, stats, similarity, lineup, trend, team-color, and season helper modules. |
| `chat/skills/nba-data-analytics/references/query-cookbook.md` | Reusable SQL patterns for common NBA analytics questions. |
| `chat/skills/nba-data-analytics/references/schema-guide.md` | Lightweight table family map and common join patterns. |

## Notes
- `create_nba_agent()` always builds `schema_context`, then renders a profile-aware system prompt, then constructs a capability manifest before runtime selection.
- Provider split is explicit: `copilot` delegates to `create_copilot_agent()`, while `deepagents` uses `create_chat_model()`, MCP tools, `web_search`, `web_fetch`, and `LocalShellBackend(root_dir=db_path.parent)`.
- The prompt contract is broader than the skill frontmatter.

## Planned wiki coverage
- `wiki/topics/chat-surface.md`
- `wiki/topics/query-agent.md`
- `wiki/topics/query-cookbook-families.md`
- `wiki/topics/analytics-skill-guide.md`

## Provenance
- `chat/server/agent.py`
- `chat/server/prompts.py`
- `chat/skills/nba-data-analytics/SKILL.md`
- `chat/skills/nba-data-analytics/references/query-cookbook.md`
- `chat/skills/nba-data-analytics/references/schema-guide.md`
