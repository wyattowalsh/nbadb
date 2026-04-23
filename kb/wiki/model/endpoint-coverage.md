---
title: Endpoint Coverage
tags:
  - kb
  - model
  - endpoints
aliases:
  - Endpoint Coverage Notes
kind: concept
status: active
updated: 2026-04-14
source_count: 5
---

# Endpoint Coverage

nbadb does not model the NBA API as a thin mirror. It inventories the current runtime surface, wraps it with registered extractors, and promotes the useful result sets into a public analytical model.

## What coverage means here
- The upstream `nba_api` runtime surface is inventoried.
- Extractors may split a single endpoint into multiple result-set or operational lanes.
- Downstream modeling is selective: not every endpoint becomes a public table.
- The public model is shaped around dimensions, facts, bridges, aggregates, and analytics views rather than one-table-per-endpoint mirroring.

## Start by first reliable key
| Starting handle | Best first docs stop |
| --- | --- |
| `game_id` | Box scores, then play-by-play, then other game-adjacent feeds |
| `player_id` or player profile question | Player stats |
| `team_id` or franchise context | Team stats |
| `season` or league-wide question | League stats |
| Draft class or combine question | Draft |

## Intentional exclusions
The current endpoint docs group the intentionally skipped endpoints into three buckets:
- superseded V2 endpoints
- video-only endpoints
- duplicate or redundant paths

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| runtime-surface framing | `AGENTS.md` | repo-wide counts and vocabulary |
| endpoint family routing | `docs/content/docs/sources/index.mdx` | current docs summary |
| endpoint family map | `docs/content/docs/model/diagrams/endpoint-map.mdx` | secondary mapping reference |
| coverage and exclusions | `artifacts/endpoint-coverage/endpoint-coverage-report.md` | generated audit artifact |
| internal source summary | `wiki/topics/endpoint-coverage-source-summary.md` | companion evidence note |
