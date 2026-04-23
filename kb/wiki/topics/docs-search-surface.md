---
title: Docs Search Surface
tags:
  - kb
  - topics
  - docs
  - search
  - runtime
aliases:
  - Docs Search Runtime Surface
  - Docs Search and Discovery Surface
kind: concept
status: active
updated: 2026-04-14
source_count: 11
---

# Docs Search Surface

Use this note when the question is "how does `/docs` search actually work right now?" rather than "how do I author a page?"

## Source search
- The searchable corpus starts in `docs/source.config.ts`, which declares `content/docs` as the docs tree.
- `docs/lib/source.ts` turns that MDX tree into the canonical Fumadocs loader with `baseUrl: "/docs"`.
- `docs/app/api/search/route.ts` publishes search directly from that same `source` via `createFromSource(source, { language: "english" })`.
- `docs/lib/search-query.ts` expands a small set of stat abbreviations before the request hits Fumadocs search. Current examples include `ppg`, `rpg`, `apg`, `ts_pct`, and `bpm`.
- The practical boundary is important: docs search is source-backed inside the app, not a separate crawler or hand-maintained index in repo code.

## Nav and search triggers
| Surface | File | Behavior |
| --- | --- | --- |
| Home header search pill | `docs/app/(home)/layout.tsx` | Opens search with a seeded broad query for onboarding, schema, and playground discovery |
| Docs top-nav search button | `docs/components/site/docs-nav.tsx` | Opens the search dialog from the shared docs chrome |
| Docs sidebar footer prompt | `docs/components/site/docs-nav.tsx` | Seeds section-specific prompt text into search via `section.prompts[0]` |
| Docs context rail prompts | `docs/components/site/docs-context-rail.tsx` | Opens search with one of several discovery prompts tied to the current page context |
| Shared trigger behavior | `docs/components/site/search-trigger.tsx` | Calls `setOpenSearch(true)`, then retries until the dialog input exists and pre-fills it when `query` is provided |

- `SearchShortcutKey` renders `⌘K` on Apple platforms and `Ctrl K` elsewhere.
- Search is enabled globally in `docs/app/layout.tsx` through `RootProvider search={{ enabled: true }}`.

## How docs content becomes searchable
1. A page enters the docs graph by existing under `docs/content/docs` and being picked up by `defineDocs({ dir: "content/docs" })` in `docs/source.config.ts`.
2. `docs/lib/source.ts` exposes that graph as the canonical `source` used by both the docs routes and the search API.
3. Generated docs join the same graph because `uv run nbadb docs-autogen --docs-root docs/content/docs` writes MDX stubs into that same tree, including schema references, data-dictionary stubs, and generated ER/lineage pages.
4. Navigation grouping comes from `docs/content/docs/meta.json`, so route placement and sidebar wayfinding are configured there, but search still follows inclusion in the shared `source` graph.

## Admin health checks
- `docs/app/api/admin/health/route.ts` reports search as a first-class subsystem with detail `Fumadocs source search active`.
- `docs/app/(admin)/admin/health/page.tsx` shows the same subsystem on the human-facing admin page with detail `Docs search API is published from the generated Fumadocs source`.
- Both admin health surfaces pair that search status with content counts from `getContentPages()`, which itself reads from `source.getPages()` in `docs/lib/admin/content-audit.ts`.
- Current limitation: the health route does not execute a live search request. It reports configured/runtime status, not end-to-end query correctness.

## Operational rule of thumb
- If a page is missing from search, first verify it is in `docs/content/docs` and visible to `source.getPages()`.
- If the page is generator-owned, regenerate docs before debugging the search route.
- If the search UI opens but looks empty or unseeded, inspect `SearchTrigger` call sites before assuming the backend corpus is wrong.

## Related notes
- [[wiki/topics/docs-app-stack|Docs App Stack]]
- [[wiki/topics/docs-autogen|Docs Autogen]]
- [[wiki/topics/docs-component-registry|Docs Component Registry]]
- [[wiki/topics/docs-generator-internals|Docs Generator Internals]]
- [[wiki/topics/docs-site-source-summary|Docs Site Source Summary]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| `content/docs` is the source tree | `docs/source.config.ts` | `defineDocs({ dir: "content/docs" })` |
| canonical docs loader and `/docs` base URL | `docs/lib/source.ts` | shared source graph for routes and search |
| search API is published from the Fumadocs source | `docs/app/api/search/route.ts` | uses `createFromSource(source, { language: "english" })` |
| query alias expansion before search | `docs/lib/search-query.ts` | abbreviation widening layer |
| search enabled in global provider | `docs/app/layout.tsx` | `RootProvider search={{ enabled: true }}` |
| shared dialog-opening and query-prefill logic | `docs/components/site/search-trigger.tsx` | search dialog trigger contract |
| top-nav and sidebar search entrypoints | `docs/components/site/docs-nav.tsx` | nav button plus seeded sidebar prompt |
| post-body discovery prompts | `docs/components/site/docs-context-rail.tsx` | context-aware seeded search flows |
| home-page seeded search entrypoint | `docs/app/(home)/layout.tsx` | broad onboarding query in header |
| generated docs artifacts written into `docs/content/docs` | `src/nbadb/docs_gen/autogen.py` | explains how generated MDX becomes part of the searchable tree |
| admin health and content-audit search status model | `docs/app/api/admin/health/route.ts`; `docs/app/(admin)/admin/health/page.tsx`; `docs/lib/admin/content-audit.ts`; `docs/content/docs/meta.json` | status reporting, page counting, and nav grouping |
