---
title: LeagueDashPtDefend upstream reference
kind: raw-source
status: captured
source_url: https://nba-api-sbang.readthedocs.io/en/latest/nba_api/stats/endpoints/leaguedashptdefend/
captured_on: 2026-04-14
capture_type: docs-page-summary
why_it_matters: Documents the player-tracking defense leaderboard contract, including its required defense filters, broad nullable slice surface, and compact defend-against shooting output schema.
---

## Source Record

- Upstream page title: `LeagueDashPtDefend`
- Wrapper path: `nba_api/stats/endpoints/leaguedashptdefend.py`
- Endpoint URL: `https://stats.nba.com/stats/leaguedashptdefend`
- Validation date shown on the page: `2020-08-15`
- Example valid URL uses `DefenseCategory=Overall`, `PerMode=Totals`, `LeagueID=00`, `Season=2019-20`, `SeasonType=Regular Season`

## Why It Matters

This page is the upstream contract reference for defend-against tracking splits by nearest defender. It shows the small required core, the large optional filter surface, and the exact leaderboard columns needed to interpret defended shot volume and efficiency.

## Key Excerpts

- Required parameters listed: `DefenseCategory`, `LeagueID`, `PerMode`, `Season`, `SeasonType`
- `DefenseCategory` supports distance buckets such as `Overall`, `3 Pointers`, `2 Pointers`, `Less Than 6Ft`, `Less Than 10Ft`, `Greater Than 15Ft`
- Nullable filters include roster and split dimensions such as `College`, `Conference`, `Country`, `DraftPick`, `DraftYear`, `GameSegment`, `Location`, `Outcome`, `PlayerID`, `PlayerPosition`, `StarterBench`, `TeamID`, `VsConference`, `VsDivision`, `Weight`
- Single output dataset listed: `LeagueDashPTDefend`
- Documented fields include `CLOSE_DEF_PERSON_ID`, `PLAYER_NAME`, `PLAYER_LAST_TEAM_ID`, `PLAYER_LAST_TEAM_ABBREVIATION`, `PLAYER_POSITION`, `AGE`, `GP`, `G`, `FREQ`, `D_FGM`, `D_FGA`, `D_FG_PCT`, `NORMAL_FG_PCT`, `PCT_PLUSMINUS`

## Capture Notes

- Page fetched successfully from Read the Docs.
- The page exposes both the human-readable parameter table and embedded JSON metadata, which agree on the single dataset name and required filter set.
- Useful for validating any extractor or schema work around defender shot-contest tracking.
