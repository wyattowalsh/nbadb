---
title: "LeagueGameFinder Endpoint Contract"
kind: raw-source
status: captured
source_url: "https://nba-api-sbang.readthedocs.io/en/latest/nba_api/stats/endpoints/leaguegamefinder/"
captured_on: "2026-04-14"
capture_type: endpoint-doc
why_it_matters: "High-value stats endpoint contract for broad historical game retrieval, including its required parameter, nullable filter surface, and documented result columns used by downstream game-level modeling."
---

## Source Record

- Source: ReadTheDocs endpoint page for `LeagueGameFinder`
- Endpoint URL: `https://stats.nba.com/stats/leaguegamefinder`
- Scope captured: endpoint URL, required and nullable parameters, and documented result dataset columns

## Why It Matters

`LeagueGameFinder` is one of the most useful broad-retrieval stats endpoints because it can return team or player game logs across many filter combinations. For nbadb, it is a contract source for understanding the upstream query surface and the stable game-level columns expected from this endpoint.

## Key Excerpts

> Endpoint URL: `https://stats.nba.com/stats/leaguegamefinder`

> Required parameter: `PlayerOrTeam` with pattern `^(P)|(T)$`

> Documented dataset: `LeagueGameFinderResults`

> Documented columns: `SEASON_ID`, `TEAM_ID`, `TEAM_ABBREVIATION`, `TEAM_NAME`, `GAME_ID`, `GAME_DATE`, `MATCHUP`, `WL`, `MIN`, `PTS`, `FGM`, `FGA`, `FG_PCT`, `FG3M`, `FG3A`, `FG3_PCT`, `FTM`, `FTA`, `FT_PCT`, `OREB`, `DREB`, `REB`, `AST`, `STL`, `BLK`, `TOV`, `PF`, `PLUS_MINUS`

## Capture Notes

- The docs page exposes a very large nullable filter surface, including date, season, opponent, outcome, and stat threshold parameters.
- The page reports `last_validated_date` in the embedded JSON as `2020-08-15`, so the contract is useful but should not be treated as a fresh validation signal by itself.
- This is a generated contract page, which makes it especially useful for extractor and schema comparison work.
