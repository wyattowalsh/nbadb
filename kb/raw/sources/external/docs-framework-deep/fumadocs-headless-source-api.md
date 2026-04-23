---
title: Fumadocs Loader API
kind: raw-source
status: captured
source_url: https://fumadocs.dev/docs/headless/source-api
captured_on: 2026-04-14
capture_type: webfetch-markdown-summary
why_it_matters: Captures the server-side source loader contract that turns content collections into page trees, page lookups, and static params for Fumadocs-based docs apps.
---

## Source Record

- Source URL: `https://fumadocs.dev/docs/headless/source-api`
- Fetch method: `webfetch` in markdown mode
- Capture date: `2026-04-14`

## Why It Matters

This is the most relevant deeper Fumadocs headless page for understanding how content sources are normalized into routing and navigation structures. It explains the `loader()` contract that bridges source data into slugs, URLs, page trees, i18n variants, and Next.js static params.

## Key Excerpts

> "`loader()` provides an interface for Fumadocs to integrate with different content sources."

> "`loader()` is a server-side API, not a build-time magic or browser compatible API."

> "With i18n enabled, loader will generate a page tree for every locale."

> "The generated parameter names will be `slug: string[]` and `lang: string` (i18n only)."

## Capture Notes

- The page centers on one abstraction: `loader()` converts content files into a unified source object for lookup, tree generation, and routing.
- The main outputs are `getPage`, `getPages`, `getPageTree`, `generateParams`, and helpers for recovering source files from tree nodes.
- Client-side usage is secondary; the page emphasizes RSC-first server usage with optional serialization for non-RSC environments.
