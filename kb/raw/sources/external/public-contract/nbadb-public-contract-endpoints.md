---
title: nbadb Docs Endpoints
kind: raw-source
status: captured
source_url: https://nbadb.w4w.dev/docs/endpoints
captured_on: 2026-04-14
capture_type: web-fetch-markdown
why_it_matters: Public endpoint coverage contract that explains which nba_api families are covered, how readers should route by key or use case, and which upstream endpoints are intentionally excluded.
---

# Source Record
- Page title: `Endpoints | nbadb`
- Page role: public endpoint coverage overview.
- Declares full runtime inventory across stats, static, and live feeds, with `7` curated landing pages for major endpoint families.
- Publicly lists `13` skipped endpoints and explains why they are excluded.

# Why It Matters
This is the strongest public source page for upstream coverage boundaries. It explains how nbadb maps the `nba_api` runtime surface into extractor families, how users should route by `game_id`, `player_id`, `team_id`, `season`, or draft context, and which endpoints are deliberately not part of the analytical model because of V3 supersession, video-only scope, redundancy, or auth walls. That makes it a direct external contract page, not just a convenience index.

# Key Excerpts
> "nbadb extracts data from the nba_api endpoint surface, covering every major statistical category in the NBA."

> "nbadb now inventories the full nba_api runtime surface across stats, static, and live feeds."

> "Some classes still split into multiple extractor paths or result-set lanes."

> "Thirteen endpoints are deliberately excluded from the analytical model."

> "All endpoint coverage flows through nba_api, with a few operational patterns that matter when you move from docs to extraction code: rate limiting, retry logic, proxy rotation, and incremental updates."

# Capture Notes
- Captured from the rendered markdown page and normalized to the coverage and exclusion statements.
- Most contract-relevant material is the explicit skipped-endpoint list and the family-level routing guidance.
- The page is also a useful operational contract because it names extraction behaviors that affect coverage realism: retry/backoff, semaphores, proxies, and watermark-based refresh.
