---
title: "Today's Scoreboard CDN JSON Snapshot"
kind: raw-source
status: captured
source_url: "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
captured_on: "2026-04-14"
capture_type: live-json-snapshot
why_it_matters: "Direct live CDN payload snapshot showing the minimal real-time scoreboard contract nbadb can poll without going through the package wrapper or stats.nba.com."
---

## Source Record

- Source: direct CDN JSON payload for today's NBA scoreboard
- Request captured successfully with HTTP code `200`
- Capture date: `2026-04-14`

## Why It Matters

This is the direct upstream live JSON contract behind the package's scoreboard access pattern. It is valuable because it shows the actual payload shape and current runtime behavior without relying on generated documentation or wrapper code.

## Key Excerpts

> `"request": "https://nba-prod-us-east-1-mediaops-stats.s3.amazonaws.com/NBA/liveData/scoreboard/todaysScoreboard_00.json"`

> `"gameDate": "2026-04-13"`

> `"leagueId": "00"`

> `"games": []`

## Capture Notes

- At capture time the payload contained an empty `games` array, so this note captures the transport contract rather than a populated game example.
- The `meta.request` value points to the current backing S3-hosted mediaops URL, which is useful when tracing CDN behavior.
- This source complements the docs pages by showing a real live response from the NBA CDN on the capture date.
