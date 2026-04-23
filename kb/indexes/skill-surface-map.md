---
title: Skill Surface Map
tags:
  - kb
  - index
  - skills
aliases:
  - nbadb Skill Surface Map
kind: index
status: active
updated: 2026-04-22
source_count: 6
---

# Skill Surface Map

Related: [[canonical-material]] · [[docs-surface-map]] · [[../wiki/index|KB Home]]

This index covers repo-local `skill` surfaces and adjacent instruction surfaces that already live inside the repository.

## Repo-local skill surfaces
| Skill surface | Paths | Intended use |
|---------------|-------|--------------|
| `nba-data-analytics` | `chat/skills/nba-data-analytics/SKILL.md`, `chat/skills/nba-data-analytics/references/` | NBA analytics queries requiring multi-table star schema joins, advanced metric formulas, and chart generation |
| Specialist chat skills | `chat/skills/*/SKILL.md` excluding `nba-data-analytics` | Planner, SQL drafting, debugging, visualization, artifact, refinement, connector, and web-context specialization layered into the current chat runtime |
| `docs-steward` project-local install | `.agents/skills/docs-steward/SKILL.md`, `.agents/skills/docs-steward/references/` | Docs maintenance and framework sync inside the repo |
| `docs-steward` compatibility mirror | `.claude/skills/docs-steward/SKILL.md`, `.claude/skills/docs-steward/references/` | Same docs-maintenance role for Claude-compatible tooling |

## Skill integration points
| Skill surface | Connected repo code/docs | Why it matters |
|---------------|--------------------------|----------------|
| `nba-data-analytics` | `chat/chainlit.md`, `src/nbadb/chat/app/agent.py`, `src/nbadb/chat/app/preamble.py`, `src/nbadb/chat/prompts.py`, `src/nbadb/transform/views/`, `src/nbadb/transform/derived/` | The chat runtime depends on analytics tables, helper scripts, and prompt rules from the main repo |
| Specialist chat skills | `src/nbadb/chat/app/agent.py`, `chat/skills/`, `src/nbadb/chat/runtime/capabilities.py` | The current runtime assembles multiple specialist skills instead of one monolithic surface |
| `docs-steward` | `docs/AGENTS.md`, `docs/content/docs/`, `docs/lib/generated/`, `src/nbadb/docs_gen/` | The skill maps directly onto the docs app and docs generator ownership boundaries |

## Adjacent instruction surfaces
| Surface | Paths | Role |
|---------|-------|------|
| Project instructions | `AGENTS.md` | Root operating instructions for work in this repo |
| Docs instructions | `docs/AGENTS.md` | Docs-only operating instructions and generated-doc ownership rules |
| Chat UX prompt surface | `chat/chainlit.md` | User-facing welcome and capability framing for the chat app |

## Provenance
- `chat/skills/nba-data-analytics/SKILL.md`
- `chat/skills/*/SKILL.md`
- `src/nbadb/chat/app/agent.py`
- `src/nbadb/chat/runtime/capabilities.py`
- `.agents/skills/docs-steward/SKILL.md`
- `docs/AGENTS.md`
