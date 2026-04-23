---
title: Fumadocs Algolia Search UI
kind: raw-source
status: captured
source_url: https://fumadocs.dev/docs/search/algolia
captured_on: 2026-04-14
capture_type: webfetch-markdown-summary
why_it_matters: Captures the framework-mode Algolia integration path for wiring Fumadocs search UI to a hosted search backend with optional locale and tag filtering.
---

## Source Record

- Source URL: `https://fumadocs.dev/docs/search/algolia`
- Fetch method: `webfetch` in markdown mode
- Capture date: `2026-04-14`

## Why It Matters

This page shows the runtime seam between Fumadocs UI search components and Algolia. It matters because the docs app can swap in a custom search dialog while still using Fumadocs provider wiring, i18n locale propagation, and optional tag filtering.

## Key Excerpts

> "While generally we recommend building your own search with their client-side SDK, you can also plug the built-in dialog interface."

> "useDocsSearch({ type: 'algolia', client, indexName: 'document', locale })"

> "Replace the search dialog with yours from `<RootProvider />`."

## Capture Notes

- The integration point is `useDocsSearch()` plus a custom `SearchDialog` component passed through `RootProvider`.
- Locale-aware search is optional but first-class through `useI18n()` and the `locale` option.
- Tag filtering is handled in UI state and passed back into `useDocsSearch()` as `tag`.
