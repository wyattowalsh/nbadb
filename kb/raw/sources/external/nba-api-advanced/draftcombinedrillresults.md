---
title: DraftCombineDrillResults upstream reference
kind: raw-source
status: captured
source_url: https://nba-api-sbang.readthedocs.io/en/latest/nba_api/stats/endpoints/draftcombinedrillresults/
captured_on: 2026-04-14
capture_type: docs-page-summary
why_it_matters: Captures the draft combine drill-results contract, including the season keying and the exact athletic-testing fields returned for combine participants.
---

## Source Record

- Upstream page title: `DraftCombineDrillResults`
- Wrapper path: `nba_api/stats/endpoints/draftcombinedrillresults.py`
- Endpoint URL: `https://stats.nba.com/stats/draftcombinedrillresults`
- Validation date shown on the page: `2020-08-15`
- Example valid URL: `https://stats.nba.com/stats/draftcombinedrillresults?LeagueID=00&SeasonYear=2019`

## Why It Matters

This page is the upstream contract source for combine drill testing results. It shows the narrow parameter surface and the exact columns used for verticals, agility, sprint, and bench metrics when modeling prospect athletic profiles.

## Key Excerpts

- Required parameters listed: `LeagueID`, `SeasonYear`
- No nullable parameters are listed on the page
- Single output dataset listed: `Results`
- Documented fields include `TEMP_PLAYER_ID`, `PLAYER_ID`, `FIRST_NAME`, `LAST_NAME`, `PLAYER_NAME`, `POSITION`, `STANDING_VERTICAL_LEAP`, `MAX_VERTICAL_LEAP`, `LANE_AGILITY_TIME`, `MODIFIED_LANE_AGILITY_TIME`, `THREE_QUARTER_SPRINT`, `BENCH_PRESS`

## Capture Notes

- Page fetched successfully from Read the Docs.
- The page is especially useful because it centralizes the exact combine drill column names, which are easy to misremember across draft endpoints.
- Useful upstream evidence for any draft-combine ingestion or prospect-athleticism modeling work.
