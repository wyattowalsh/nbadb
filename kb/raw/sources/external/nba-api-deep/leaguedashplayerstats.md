---
title: LeagueDashPlayerStats upstream reference
kind: raw-source
status: captured
source_url: https://nba-api-sbang.readthedocs.io/en/latest/nba_api/stats/endpoints/leaguedashplayerstats/
captured_on: 2026-04-14
capture_type: docs-page-summary
why_it_matters: Captures the large filter surface and output schema for LeagueDashPlayerStats, a core leaderboard-style player stats endpoint with many slicing dimensions.
---

## Source Record

- Upstream page title: `LeagueDashPlayerStats`
- Wrapper path: `nba_api/stats/endpoints/leaguedashplayerstats.py`
- Extracted page content exposed parameter metadata and dataset schema
- Page notes a validation date of `2020-08-16`

## Why It Matters

This reference is valuable because it compresses a very wide parameter contract into one place, showing which leaderboard filters exist, which are nullable, and what the returned player stat table looks like.

## Key Excerpts

- Single output dataset listed: `LeagueDashPlayerStats`
- Example output fields include `PLAYER_ID`, `PLAYER_NAME`, `TEAM_ID`, `TEAM_ABBREVIATION`, `AGE`, `GP`, `W`, `L`, `W_PCT`, `MIN`, `FGM`, `FGA`, `FG_PCT`, `FG3M`, `FG3A`, `FTM`, `FTA`, `REB`, `AST`, `TOV`, `STL`, `BLK`, `PTS`, `PLUS_MINUS`, `NBA_FANTASY_PTS`, `DD2`, `TD3`, `CFID`, `CFPARAMS`
- Notable required filters called out on the page include `MeasureType`, `PerMode`, `Season`, `SeasonType`, `PaceAdjust`, `PlusMinus`, `Rank`, `LastNGames`, `Month`, `OpponentTeamID`, `Period`, `DateFrom`, `DateTo`, `GameScope`, and `GameSegment`
- Example regex constraints include `MeasureType` with values such as `Base`, `Advanced`, `Misc`, `Four Factors`, `Scoring`, `Opponent`, `Usage`, `Defense`
- `PerMode` supports many granularities including `Totals`, `PerGame`, `Per36`, `PerPossession`, `Per100Possessions`, and `Per100Plays`

## Capture Notes

- Page fetched successfully from Read the Docs.
- The extracted content did not clearly surface a concrete sample endpoint URL, but it did include the full parameter inventory and JSON metadata.
- Useful upstream evidence for any extractor or schema code handling leaderboard filters or interpreting `CFPARAMS`.
