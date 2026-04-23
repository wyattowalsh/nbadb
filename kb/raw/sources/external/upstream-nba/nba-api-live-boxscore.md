---
title: "Live BoxScore Endpoint Contract"
kind: raw-source
status: captured
source_url: "https://nba-api-sbang.readthedocs.io/en/latest/nba_api/live/endpoints/boxscore/"
captured_on: "2026-04-14"
capture_type: endpoint-doc
why_it_matters: "High-value live endpoint contract for nested game, team, player, arena, and official structures served from CDN JSON that nbadb can model independently of stats.nba.com tables."
---

## Source Record

- Source: ReadTheDocs endpoint page for live `BoxScore`
- Endpoint URL pattern: `https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json`
- Scope captured: required parameter pattern and major nested object structure for game, team, and player payloads

## Why It Matters

This page documents one of the richest live-data contracts exposed by the upstream package. It shows that live box score data comes from CDN JSON, not the stats endpoint family, and that the payload is deeply nested around `game`, `homeTeam`, `awayTeam`, `players`, `statistics`, `arena`, and `officials`.

## Key Excerpts

> Endpoint URL: `https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json`

> Required parameter: `GameID` with pattern `^\d{10}$`

> Documented top-level structures include `game`, `homeTeam`, `awayTeam`, `officials`, and `arena`.

> Player statistics include fields such as `assists`, `blocks`, `fieldGoalsAttempted`, `fieldGoalsMade`, `freeThrowsAttempted`, `minutes`, `points`, `reboundsTotal`, `steals`, `threePointersAttempted`, `turnovers`, and `twoPointersAttempted`.

## Capture Notes

- The contract page is especially useful because it flattens a deeply nested JSON payload into named dataset groups.
- The embedded example JSON shows live-style ISO timestamps, duration, attendance, team summaries, and per-player nested statistics.
- The page reports `Last validated 2020-08-16`, so field presence should still be verified against fresh live payloads when schema accuracy matters.
