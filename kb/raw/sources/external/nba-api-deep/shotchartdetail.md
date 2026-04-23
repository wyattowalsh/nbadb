---
title: ShotChartDetail upstream reference
kind: raw-source
status: captured
source_url: https://nba-api-sbang.readthedocs.io/en/latest/nba_api/stats/endpoints/shotchartdetail/
captured_on: 2026-04-14
capture_type: docs-page-summary
why_it_matters: Records the upstream contract for shot-level event output and league-average shot zones, which is central to any spatial shooting analysis pipeline.
---

## Source Record

- Upstream page title: `ShotChartDetail`
- Wrapper path: `nba_api/stats/endpoints/shotchartdetail.py`
- Extracted page content exposed parameter metadata and dataset schema
- Page notes a validation date of `2020-08-16`

## Why It Matters

This endpoint mixes rich filtering with shot-level coordinates and contextual fields, so the page is a useful upstream reference for understanding both the event grain and the zone-based comparison dataset.

## Key Excerpts

- Output datasets listed: `Shot_Chart_Detail` and `LeagueAverages`
- Shot-level fields include `GAME_ID`, `GAME_EVENT_ID`, `PLAYER_ID`, `PLAYER_NAME`, `TEAM_ID`, `PERIOD`, `MINUTES_REMAINING`, `SECONDS_REMAINING`, `EVENT_TYPE`, `ACTION_TYPE`, `SHOT_TYPE`, `SHOT_ZONE_BASIC`, `SHOT_ZONE_AREA`, `SHOT_ZONE_RANGE`, `SHOT_DISTANCE`, `LOC_X`, `LOC_Y`, `SHOT_ATTEMPTED_FLAG`, `SHOT_MADE_FLAG`, `GAME_DATE`, `HTM`, `VTM`
- League-average zone fields: `GRID_TYPE`, `SHOT_ZONE_BASIC`, `SHOT_ZONE_AREA`, `SHOT_ZONE_RANGE`, `FGA`, `FGM`, `FG_PCT`
- Required filters called out on the page include `ContextMeasure`, `DateFrom`, `DateTo`, `GameID`, `GameSegment`, `LastNGames`, `LeagueID`, `Location`, `Month`, `OpponentTeamID`, `Outcome`, `Period`, `PlayerID`, `PlayerPosition`, `SeasonSegment`, `SeasonType`, `TeamID`, `VsConference`, and `VsDivision`
- `GameID` regex shown: `^(\d{10})?$`

## Capture Notes

- Page fetched successfully from Read the Docs.
- The source page includes a JSON block mirroring the dataset and parameter metadata.
- This is a strong raw-source reference for reconciling shot chart schemas, especially coordinate fields and zone labels.
