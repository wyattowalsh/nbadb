---
title: Fumadocs Content Collections Integration
kind: raw-source
status: captured
source_url: https://fumadocs.dev/docs/headless/content-collections
captured_on: 2026-04-14
capture_type: webfetch-markdown-summary
why_it_matters: Captures the typed content-source path for feeding MDX docs and meta records into Fumadocs loader-based routing, trees, and page lookups.
---

## Source Record

- Source URL: `https://fumadocs.dev/docs/headless/content-collections`
- Fetch method: `webfetch` in markdown mode
- Capture date: `2026-04-14`

## Why It Matters

This is the clearest deeper reference for how Fumadocs can sit on top of Content Collections instead of a bespoke source layer. It documents the typed handoff from MDX and `meta.json` collections into `loader()`, which is the core runtime bridge for page resolution and tree generation.

## Key Excerpts

> "Content Collections is a library that transforms your content into type-safe data collections."

> "To integrate with Fumadocs, add the following to your `content-collections.ts`."

> "Done! You can access the pages and generated page tree from Source API."

## Capture Notes

- The recommended setup uses `frontmatterSchema`, `metaSchema`, and `transformMDX` from `@fumadocs/content-collections/configuration`.
- Runtime hookup happens in `loader({ baseUrl, source: createMDXSource(allDocs, allMetas) })`.
- The page also explains why importing components directly inside MDX is possible but discouraged.
