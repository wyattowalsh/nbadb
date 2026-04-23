---
title: Recharts AreaChart API URL Stub
kind: raw-source
status: stub
source_url: https://recharts.org/en-US/api/AreaChart
captured_on: 2026-04-15
capture_type: direct-fetch-failed-stub
why_it_matters: Tracks the intended Recharts AreaChart API reference URL for future docs-admin charting work even though the current route was not fetchable.
---

## Source Record

- Source URL: `https://recharts.org/en-US/api/AreaChart`
- Fetch method: `webfetch` in markdown mode, then `trafilatura`, then direct `curl` header and canonical-path checks
- Capture date: `2026-04-15`

## Why It Matters

Area charts are a likely fit for trend and time-series views in docs-admin surfaces. Keeping the intended Recharts API URL in the raw-source layer makes it obvious that the dependency is relevant even though the current docs route is unavailable.

## Key Excerpts

> Stub only. No reliable page body was retrievable from this URL during capture.

> Direct requests to both the requested URL and the trailing-slash variant returned `404`.

## Capture Notes

- `webfetch` returned `404` for the requested URL.
- `trafilatura` failed to download the page body.
- Direct `curl -L -I` checks confirmed `404` for both `/api/AreaChart` and `/api/AreaChart/`.
