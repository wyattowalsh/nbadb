---
title: CommonPlayerInfo upstream reference
kind: raw-source
status: captured
source_url: https://nba-api-sbang.readthedocs.io/en/latest/nba_api/stats/endpoints/commonplayerinfo/
captured_on: 2026-04-14
capture_type: docs-page-summary
why_it_matters: Documents the upstream player identity and biographical fields returned by CommonPlayerInfo, which are foundational for player dimensions and metadata enrichment.
---

## Source Record

- Upstream page title: `CommonPlayerInfo`
- Wrapper path: `nba_api/stats/endpoints/commonplayerinfo.py`
- Example endpoint URL: `https://stats.nba.com/stats/commonplayerinfo?LeagueID=&PlayerID=2544`
- Page notes a validation date of `2020-08-16`

## Why It Matters

This page shows the main upstream schema for player identity, roster affiliation, draft metadata, and lightweight headline stats, making it a strong reference for player dimension sourcing and column naming.

## Key Excerpts

- Required parameter listed: `PlayerID`
- Nullable parameter listed: `LeagueID`
- Data sets listed: `AvailableSeasons`, `CommonPlayerInfo`, `PlayerHeadlineStats`
- Example identity fields: `PERSON_ID`, `FIRST_NAME`, `LAST_NAME`, `DISPLAY_FIRST_LAST`, `PLAYER_SLUG`, `BIRTHDATE`, `SCHOOL`, `COUNTRY`, `HEIGHT`, `WEIGHT`, `SEASON_EXP`, `JERSEY`, `POSITION`
- Team and draft fields include `TEAM_ID`, `TEAM_NAME`, `TEAM_ABBREVIATION`, `FROM_YEAR`, `TO_YEAR`, `DRAFT_YEAR`, `DRAFT_ROUND`, `DRAFT_NUMBER`
- Headline stats fields: `PLAYER_ID`, `PLAYER_NAME`, `TimeFrame`, `PTS`, `AST`, `REB`, `PIE`

## Capture Notes

- Page fetched successfully from Read the Docs.
- The page provides both table-form metadata and a JSON metadata block with the same schema details.
- Particularly useful when validating exact upstream casing and field coverage for player bio sources.
