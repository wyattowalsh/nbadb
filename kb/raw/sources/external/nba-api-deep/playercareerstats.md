---
title: PlayerCareerStats upstream reference
kind: raw-source
status: captured
source_url: https://nba-api-sbang.readthedocs.io/en/latest/nba_api/stats/endpoints/playercareerstats/
captured_on: 2026-04-14
capture_type: docs-page-summary
why_it_matters: Documents the parameter contract and dataset layout for career and season-level player totals exposed by the upstream nba_api stats endpoint.
---

## Source Record

- Upstream page title: `PlayerCareerStats`
- Wrapper path: `nba_api/stats/endpoints/playercareerstats.py`
- Example endpoint URL: `https://stats.nba.com/stats/playercareerstats?LeagueID=&PerMode=Totals&PlayerID=2544`
- Page notes a validation date of `2020-08-16`

## Why It Matters

This reference is the clearest compact source for how `PlayerCareerStats` splits player output into career totals, season totals, and season rankings across regular season, postseason, All-Star, and college contexts.

## Key Excerpts

- Required parameters listed: `PerMode`, `PlayerID`
- Nullable parameter listed: `LeagueID`
- `PerMode` pattern: `^(Totals)|(PerGame)|(Per36)$`
- Data sets listed include `CareerTotalsRegularSeason`, `CareerTotalsPostSeason`, `SeasonTotalsRegularSeason`, `SeasonTotalsPostSeason`, `SeasonRankingsRegularSeason`, and `SeasonRankingsPostSeason`
- Example season-total columns: `PLAYER_ID`, `SEASON_ID`, `TEAM_ID`, `TEAM_ABBREVIATION`, `PLAYER_AGE`, `GP`, `GS`, `MIN`, `FGM`, `FGA`, `FG_PCT`, `FG3M`, `FG3A`, `FG3_PCT`, `FTM`, `FTA`, `FT_PCT`, `OREB`, `DREB`, `REB`, `AST`, `STL`, `BLK`, `TOV`, `PF`, `PTS`

## Capture Notes

- Page fetched successfully from Read the Docs.
- Capture is concise by design; the source page also includes a JSON block repeating the parameter and dataset metadata.
- Useful as an upstream contract check for staging and star outputs that depend on player career rollups.
