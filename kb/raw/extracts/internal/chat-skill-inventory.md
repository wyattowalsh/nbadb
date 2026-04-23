# Chat Skill Inventory

## Purpose
- Grouped internal extract for the current `chat/skills/*` surface.
- Capture skill-role boundaries so chat routing can separate warehouse planning, SQL execution, post-query analysis, session refinement, artifact persistence, runtime adaptation, and web-context augmentation.

## High-value paths

### End-to-end analytics package
| Path | Boundary | Surface status |
| --- | --- | --- |
| `chat/skills/nba-data-analytics/` | Legacy bundled analytics skill: broad end-to-end contract spanning SQL table selection, SCD2 handling, `run_python` helpers, visualization, export, and iterative `last_result` work. | Existing tracked skill; wider than the newer single-purpose skills. |

### Warehouse routing and query correctness
| Path | Boundary | Surface status |
| --- | --- | --- |
| `chat/skills/nbadb-semantic-catalog/` | Semantic-first routing layer for choosing entity, grain, and table family before SQL exists. | New untracked skill. |
| `chat/skills/warehouse-query-writing/` | SQL-authoring layer for turning the chosen warehouse surface into validated query logic. | New untracked skill. |
| `chat/skills/data-quality-debugging/` | Post-validation debugging layer for wrong, empty, duplicated, or semantically suspicious results. | New untracked skill. |

### Post-query analysis and persistence
| Path | Boundary | Surface status |
| --- | --- | --- |
| `chat/skills/analysis-and-visualization/` | Python-side interpretation layer once the right rows already exist: chart choice, derived metrics, tests, and explanation. | New untracked skill. |
| `chat/skills/artifact-creation/` | Persistence layer for saving findings, templates, repro scripts, exports, and replayable bundles. | New untracked skill. |

### Session and runtime control
| Path | Boundary | Surface status |
| --- | --- | --- |
| `chat/skills/follow-up-refinement/` | Multi-turn refinement layer for modifying the prior result or artifact without silently changing grain or provenance. | New untracked skill. |
| `chat/skills/connector-usage/` | Runtime-capability layer for adapting behavior to local, BYOK, Copilot, OpenAI-login, or sandbox differences. | New untracked skill. |

### External context augmentation
| Path | Boundary | Surface status |
| --- | --- | --- |
| `chat/skills/web-context-for-nba/` | Current-events augmentation layer for injuries, trades, and live NBA context that the warehouse cannot yet answer. | New untracked skill. |

## Notes
- Current skill roots under `chat/skills/`: 9.
- Boundary split is deliberate: `nbadb-semantic-catalog` chooses surfaces, `warehouse-query-writing` writes SQL, and `data-quality-debugging` explains why a runnable query is still untrustworthy.
- `analysis-and-visualization` starts after SQL correctness; it should not absorb warehouse retrieval work that belongs in `warehouse-query-writing`.
- `artifact-creation` is persistence-oriented, not analytical; it packages outputs that should survive the current chat turn.
- `follow-up-refinement` is session-scoped; it refines an existing result or saved SQL instead of re-planning from scratch.
- `connector-usage` is infrastructure-aware routing logic, not domain analytics; it guards workflow differences across connector and sandbox modes.
- `web-context-for-nba` supplements warehouse truth but does not replace it.
- `nba-data-analytics` overlaps several of the narrower roles above; it remains the broad packaged skill while the eight newer skills carve the workflow into explicit responsibilities.
- `git status --short -- chat/skills kb/raw/extracts/internal` showed eight untracked skill directories plus the untracked target extract directory; `nba-data-analytics` was not listed, consistent with it already being tracked.

## Planned wiki coverage
- `kb/wiki/topics/chat-skill-surface.md`
- `kb/wiki/topics/analytics-skill-guide.md`
- `kb/wiki/topics/query-cookbook-families.md`

## Provenance
- `chat/skills/nba-data-analytics/SKILL.md`
- `chat/skills/nbadb-semantic-catalog/SKILL.md`
- `chat/skills/warehouse-query-writing/SKILL.md`
- `chat/skills/data-quality-debugging/SKILL.md`
- `chat/skills/analysis-and-visualization/SKILL.md`
- `chat/skills/artifact-creation/SKILL.md`
- `chat/skills/follow-up-refinement/SKILL.md`
- `chat/skills/connector-usage/SKILL.md`
- `chat/skills/web-context-for-nba/SKILL.md`
- `git status --short -- chat/skills kb/raw/extracts/internal`
