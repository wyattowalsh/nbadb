---
title: GameRotation upstream reference
kind: raw-source
status: captured
source_url: https://nba-api-sbang.readthedocs.io/en/latest/nba_api/stats/endpoints/gamerotation/
captured_on: 2026-04-14
capture_type: docs-page-summary
why_it_matters: Documents the game rotation contract for home and away stint tables, including the in-out timing fields and player on-court point differential columns.
---

## Source Record

- Upstream page title: `GameRotation`
- Wrapper path: `nba_api/stats/endpoints/gamerotation.py`
- Endpoint URL: `https://stats.nba.com/stats/gamerotation`
- Validation date shown on the page: `2020-08-15`
- Example valid URL: `https://stats.nba.com/stats/gamerotation?GameID=0021700807&LeagueID=00`

## Why It Matters

This page is the upstream contract reference for lineup stint timing by game. It shows the small required key surface and the exact home-away rotation columns needed to reconstruct substitution windows and player-level on-court usage snapshots.

## Key Excerpts

- Required parameters listed: `GameID`, `LeagueID`
- No nullable parameters are listed on the page
- Output datasets listed: `AwayTeam`, `HomeTeam`
- Both datasets expose `GAME_ID`, `TEAM_ID`, `TEAM_CITY`, `TEAM_NAME`, `PERSON_ID`, `PLAYER_FIRST`, `PLAYER_LAST`, `IN_TIME_REAL`, `OUT_TIME_REAL`, `PLAYER_PTS`, `PT_DIFF`, `USG_PCT`

## Capture Notes

- Page fetched successfully from Read the Docs.
- The contract splits output by home and away instead of returning one unified rotation table, which is important for extractor normalization.
- Useful for validating substitution-timeline staging logic or any derived rotation analysis outputs.
