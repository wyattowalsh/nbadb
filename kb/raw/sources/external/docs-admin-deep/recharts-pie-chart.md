---
title: Recharts PieChart API URL Stub
kind: raw-source
status: stub
source_url: https://recharts.org/en-US/api/PieChart
captured_on: 2026-04-15
capture_type: direct-fetch-failed-stub
why_it_matters: Tracks the intended Recharts PieChart API reference URL for future docs-admin composition and share-of-total views even though the current route was not fetchable.
---

## Source Record

- Source URL: `https://recharts.org/en-US/api/PieChart`
- Fetch method: `webfetch` in markdown mode, then `trafilatura`, then direct `curl` header and canonical-path checks
- Capture date: `2026-04-15`

## Why It Matters

Pie and donut-style views are occasionally useful for share-of-total summaries in admin dashboards. This stub preserves the exact upstream URL that was requested so a later pass can retry against any updated Recharts docs structure.

## Key Excerpts

> Stub only. No reliable page body was retrievable from this URL during capture.

> Direct requests to both the requested URL and the trailing-slash variant returned `404`.

## Capture Notes

- `webfetch` returned `404` for the requested URL.
- `trafilatura` failed to download the page body.
- Direct `curl -L -I` checks confirmed `404` for both `/api/PieChart` and `/api/PieChart/`.
