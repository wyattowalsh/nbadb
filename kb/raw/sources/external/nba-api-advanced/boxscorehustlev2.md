---
title: BoxScoreHustleV2 upstream reference
kind: raw-source
status: captured
source_url: https://nba-api-sbang.readthedocs.io/en/latest/nba_api/stats/endpoints/boxscorehustlev2/
captured_on: 2026-04-14
capture_type: docs-page-summary
why_it_matters: Documents the v2 hustle box score contract for single-game player and team hustle metrics such as deflections, screen assists, loose balls, and box outs.
---

## Source Record

- Upstream page title: `BoxScoreHustleV2`
- Wrapper path: `nba_apiv3/stats/endpoints/boxscorehustlev2.py`
- Endpoint URL: `https://stats.nba.com/stats/boxscorehustlev2`
- Validation date shown on the page: `2023-09-14`
- Example valid URL: `https://stats.nba.com/stats/boxscorehustlev2?GameID=0021700807`

## Why It Matters

This reference compresses the hustle box score payload into one place. It is useful for confirming the exact single-game hustle metrics available for both players and teams, especially where these fields differ from traditional box score outputs.

## Key Excerpts

- Required parameter listed: `GameID`
- No nullable parameters are listed on the page
- Output datasets listed: `PlayerStats`, `TeamStats`
- Player-level fields include `gameId`, `teamId`, `teamTricode`, `personId`, `minutes`, `points`, `contestedShots`, `contestedShots2pt`, `contestedShots3pt`, `deflections`, `chargesDrawn`, `screenAssists`, `screenAssistPoints`, `looseBallsRecoveredOffensive`, `looseBallsRecoveredDefensive`, `looseBallsRecoveredTotal`, `offensiveBoxOuts`, `defensiveBoxOuts`, `boxOutPlayerTeamRebounds`, `boxOutPlayerRebounds`, `boxOuts`
- Team-level fields retain the same hustle measures without player identity columns

## Capture Notes

- Page fetched successfully from Read the Docs.
- Although named `V2`, the page points to an `nba_apiv3` wrapper path, so the wrapper generation lineage is worth noting when comparing endpoint families.
- Useful for validating extractor output and schema coverage for single-game hustle metrics.
