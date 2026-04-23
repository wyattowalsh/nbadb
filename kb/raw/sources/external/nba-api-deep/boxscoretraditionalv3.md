---
title: BoxScoreTraditionalV3 upstream reference
kind: raw-source
status: captured
source_url: https://nba-api-sbang.readthedocs.io/en/latest/nba_api/stats/endpoints/boxscoretraditionalv3/
captured_on: 2026-04-14
capture_type: docs-page-summary
why_it_matters: Documents the newer v3 traditional box score schema, including camelCase output fields and team starter-bench splits that differ from older stats endpoints.
---

## Source Record

- Upstream page title: `BoxScoreTraditionalV3`
- Wrapper path: `nba_apiv3/stats/endpoints/boxscoretraditionalv3.py`
- Validation date shown on the page: `2023-09-14`
- Example `GameID` pattern: `^\d{10}$`

## Why It Matters

This page is a useful reference for the v3 box score family because it shows the fully required range parameters, the newer field naming style, and the distinct team aggregate datasets returned alongside player rows.

## Key Excerpts

- Required parameters listed: `EndPeriod`, `EndRange`, `GameID`, `RangeType`, `StartPeriod`, `StartRange`
- Output datasets listed: `PlayerStats`, `TeamStarterBenchStats`, `TeamStats`
- Player-level fields include `gameId`, `teamId`, `teamTricode`, `personId`, `firstName`, `familyName`, `playerSlug`, `position`, `jerseyNum`, `minutes`, `fieldGoalsMade`, `fieldGoalsAttempted`, `threePointersMade`, `freeThrowsMade`, `reboundsTotal`, `assists`, `steals`, `blocks`, `turnovers`, `points`, `plusMinusPoints`
- Bench split output includes `startersBench` in `TeamStarterBenchStats`
- No nullable parameters are listed on the page

## Capture Notes

- Page fetched successfully from Read the Docs.
- Compared with older stats endpoints, this page is notable for camelCase columns and the `nba_apiv3` wrapper path.
- Useful for schema confirmation when mapping v3 box score payloads into staging tables.
