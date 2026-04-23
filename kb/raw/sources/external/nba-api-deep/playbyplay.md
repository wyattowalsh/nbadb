---
title: PlayByPlay live upstream reference
kind: raw-source
status: captured
source_url: https://nba-api-sbang.readthedocs.io/en/latest/nba_api/live/endpoints/playbyplay/
captured_on: 2026-04-14
capture_type: docs-page-summary
why_it_matters: Captures the live play-by-play JSON shape, including action-level keys, coordinate fields, and notes about key presence variability by action type.
---

## Source Record

- Upstream page title: `PlayByPlay`
- Wrapper path: `nba_api/live/nba/endpoints/playbyplay.py`
- Live endpoint template: `https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{game_id}.json`
- Example valid URL: `https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_0022000180.json`
- Page notes a validation date of `2020-08-16`

## Why It Matters

This page goes beyond a simple field list and explains the live `actions` payload in detail, which makes it especially useful for modeling event-level play-by-play data and understanding which fields are conditional on `actionType`.

## Key Excerpts

- Required parameter listed: `GameID`
- `GameID` pattern shown: `^\d{10}$`
- Main dataset listed: `Actions`
- Action fields include `actionNumber`, `actionType`, `clock`, `description`, `descriptor`, `period`, `periodType`, `personId`, `personIdsFilter`, `pointsTotal`, `possession`, `qualifiers`, `scoreAway`, `scoreHome`, `shotActionNumber`, `shotDistance`, `shotResult`, `side`, `teamId`, `teamTricode`, `timeActual`, `x`, `xLegacy`, `y`, `yLegacy`
- Source note: not all keys appear on every action because presence depends on `actionType`
- Source note: `actionNumber` is sequential but not necessarily consecutive

## Capture Notes

- Page fetched successfully from Read the Docs.
- The upstream page includes a long per-key reference table and a sample JSON payload under `game.actions`.
- Useful as a raw-source contract for live ingest, especially around optional keys and coordinate fields.
