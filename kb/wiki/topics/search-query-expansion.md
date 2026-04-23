---
title: Search Query Expansion
tags:
  - kb
  - topics
  - docs
  - search
  - frontend
aliases:
  - Docs Search Query Expansion
  - Docs Search Trigger Behavior
kind: concept
status: active
updated: 2026-04-14
source_count: 8
---

# Search Query Expansion

Use this note when the question is "why did docs search return these results?" or "which UI actions open search versus seed it with a prompt?"

## Core rule
- Docs search is source-backed, not crawler-backed.
- `docs/app/api/search/route.ts` expands the incoming `query` first, then delegates to Fumadocs `createFromSource(source, { language: "english" })`.
- The searchable corpus comes from the same docs `source` graph used to render `/docs`, so search coverage follows what is present in `content/docs` and loaded through `docs/lib/source.ts`.

## Abbreviation expansion
- `docs/lib/search-query.ts` only expands token-level aliases that match the hard-coded shorthand map.
- Current shorthand coverage is: `ppg`, `rpg`, `apg`, `spg`, `bpg`, `fg_pct`, `ts_pct`, and `bpm`.
- Expansion is case-insensitive because the function lowercases tokens before lookup.
- Expansion is additive, not substitutive: the original query stays in place and the expanded phrases are appended.
- Expansion phrases are deduplicated through a `Set`, so repeated shorthand does not repeat the same long-form phrase.
- Unmatched queries pass through unchanged.

## Trigger behavior
- `SearchTrigger` is the shared thin client wrapper for docs search UI actions.
- Every trigger opens the dialog by calling `setOpenSearch(true)` from the Fumadocs search context.
- If no `query` prop is passed, the trigger only opens the search UI.
- If a `query` prop is passed, the trigger retries until the live dialog input exists, then writes the query into the input, dispatches `input` and `change`, focuses the field, and moves the caret to the end.
- The retry path uses staged delays (`0`, `80`, `180` ms) because the dialog input may not exist on the first frame.

## Seeded prompts and entry points
| Surface | File | Behavior |
| --- | --- | --- |
| Docs top-nav button | `docs/components/site/docs-nav.tsx` | Opens search only; no seeded query |
| Docs sidebar footer | `docs/components/site/docs-nav.tsx` | Seeds `section.prompts[0].query` into search |
| Docs context rail prompts | `docs/components/site/docs-context-rail.tsx` | Seeds the selected contextual discovery prompt |
| Home header search button | `docs/app/(home)/layout.tsx` | Seeds a broad onboarding query for docs, schema, and playground discovery |

## Practical boundary
- Search behavior has two separate layers: query shaping in `expandSearchQuery()` and UI seeding/opening in `SearchTrigger`.
- Seeded prompts do not change the alias map; they only prefill the dialog with a starting query.
- Adding a docs page to the searchable surface is a content/source problem.
- Making shorthand or discovery prompts behave differently is a search-query or trigger-entry-point problem.

## Related notes
- [[wiki/topics/docs-search-surface|Docs Search Surface]]
- [[wiki/topics/docs-component-registry|Docs Component Registry]]
- [[wiki/topics/docs-app-stack|Docs App Stack]]
- [[wiki/topics/docs-site-source-summary|Docs Site Source Summary]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| search API expands query then delegates to source-backed Fumadocs search | `docs/app/api/search/route.ts` | `expandSearchQuery(query)` runs before `createFromSource(source, { language: "english" })` |
| searchable corpus comes from the shared docs source graph | `docs/lib/source.ts`; `docs/source.config.ts` | search follows the same `content/docs` graph used by routes |
| alias map contents and additive expansion behavior | `docs/lib/search-query.ts` | shorthand tokens append long-form phrases |
| case-insensitive and deduplicated expansion semantics | `docs/lib/search-query.test.ts` | verifies uppercase input and duplicate suppression |
| shared dialog-opening and prefill retry behavior | `docs/components/site/search-trigger.tsx` | `setOpenSearch(true)` plus staged input lookup and synthetic events |
| unseeded docs-nav search button and seeded sidebar prompt | `docs/components/site/docs-nav.tsx` | nav button opens search; sidebar footer seeds `section.prompts[0]` |
| contextual seeded prompts below docs pages | `docs/components/site/docs-context-rail.tsx` | prompt cards pass `prompt.query` into `SearchTrigger` |
| broad seeded home-entry query | `docs/app/(home)/layout.tsx` | onboarding-style search starter for first-time navigation |
