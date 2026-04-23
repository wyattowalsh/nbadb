---
title: BoxScorePlayerTrackV3 upstream reference
kind: raw-source
status: captured
source_url: https://nba-api-sbang.readthedocs.io/en/latest/nba_api/stats/endpoints/boxscoreplayertrackv3/
captured_on: 2026-04-14
capture_type: docs-page-summary
why_it_matters: Captures the v3 player-tracking box score contract, including its single-game key and the player and team tracking metrics returned in camelCase form.
---

## Source Record

- Upstream page title: `BoxScorePlayerTrackV3`
- Wrapper path: `nba_apiv3/stats/endpoints/boxscoreplayertrackv3.py`
- Endpoint URL: `https://stats.nba.com/stats/boxscoreplayertrackv3`
- Validation date shown on the page: `2023-09-14`
- Example valid URL: `https://stats.nba.com/stats/boxscoreplayertrackv3?GameID=0021700807`

## Why It Matters

This page is a compact contract reference for the v3 tracking box score family. It shows the minimal required input and the exact player-level and team-level motion, touch, rebounding-chance, and contest metrics returned for one game.

## Key Excerpts

- Required parameter listed: `GameID`
- No nullable parameters are listed on the page
- Output datasets listed: `PlayerStats`, `TeamStats`
- Player-level fields include `gameId`, `teamId`, `teamTricode`, `personId`, `firstName`, `familyName`, `playerSlug`, `position`, `minutes`, `speed`, `distance`, `reboundChancesOffensive`, `reboundChancesDefensive`, `touches`, `passes`, `assists`, `contestedFieldGoalsMade`, `uncontestedFieldGoalsMade`, `defendedAtRimFieldGoalsMade`, `defendedAtRimFieldGoalsAttempted`
- Team-level fields mirror the tracking totals without player identity columns

## Capture Notes

- Page fetched successfully from Read the Docs.
- This contract is notable for the `nba_apiv3` wrapper path and camelCase output schema, matching the newer v3 box score style.
- Useful upstream evidence for staging or star-schema work that maps player-tracking box score metrics.
