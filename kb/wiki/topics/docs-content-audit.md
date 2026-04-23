---
title: Docs Content Audit Surface
tags:
  - kb
  - topics
  - docs
  - admin
  - content
  - qa
aliases:
  - Content Audit Surface
  - Docs Content Analytics
kind: concept
status: active
updated: 2026-04-15
source_count: 8
---

# Docs Content Audit Surface

Use this note when you need the exact contract behind the docs admin content audit: where the page inventory comes from, how sections are derived, what counts as shallow TOC coverage, how freshness swatches are bucketed, and what the content table does client-side.

## Surface summary
| Surface | Canonical source | Main behavior |
| --- | --- | --- |
| source graph | `docs/lib/source.ts` -> `source.getPages()` | reads the live Fumadocs page graph under `/docs` |
| page normalization | `docs/lib/admin/content-audit.ts` | emits `ContentPageMeta` rows with title, slug, url, section, description, TOC depth, and mtime |
| section slicing | `docs/lib/admin/content-audit.ts` | first slug segment becomes `section`; empty slug becomes `root` |
| TOC-depth QA | `docs/lib/admin/content-audit.ts` | pages with `tocDepth < 3` are flagged as shallow |
| freshness bands | `docs/app/(admin)/admin/content/page.tsx`; `docs/components/admin/content-freshness.tsx` | converts `lastModified` to days old and bins into five color bands |
| filter behavior | `docs/app/(admin)/admin/content/filterable-content-table.tsx` | client-side title/slug substring filter plus section dropdown |
| table presentation | `docs/app/(admin)/admin/content/content-table.tsx`; `docs/components/admin/data-table.tsx` | sortable TanStack table with pagination, badges, truncation, and empty-state row |

## Source graph
- The audit does not read a generated JSON snapshot.
- `docs/lib/source.ts` builds the canonical docs loader with `loader({ baseUrl: "/docs", source: toFumadocsSource(docs, meta) })`.
- `getContentPages()` calls `source.getPages()` directly, so the audit follows the same runtime page graph used by the docs site.
- Each returned page is normalized into `ContentPageMeta`, the shared row shape consumed by the admin content page and content table.

## Section slicing
- `slugParts = page.slugs` is the only section input.
- `section = slugParts[0] ?? "root"`.
- `slug` is serialized as `slugParts.join("/")`.
- `url` is taken from `page.url`, so page routing stays aligned with Fumadocs resolution rather than a hand-built pathname.
- The resulting section counts are a simple frequency map over the normalized rows.

## TOC-depth QA
- `tocDepth` is currently defined as `page.data.toc?.length ?? 0`.
- The audit's shallow-TOC rule is strict and global: any page with fewer than 3 TOC entries is included in `shallowToc`.
- The admin content page exposes that rule in the KPI label as `Shallow TOC (<3)`.
- This is a depth-by-count heuristic, not a semantic heading-quality review. A page can pass with 3 entries even if the outline is uneven.

## Freshness bands
- `lastModified` is resolved from the content tree by probing:
  1. `content/docs/<slug>/index.mdx`
  2. `content/docs/<slug>.mdx`
- The docs landing page uses `content/docs/index.mdx` because it has an empty slug array.
- `daysOldFromIso()` converts ISO mtimes to whole-day ages.
- Missing mtimes are treated as `999` days old, which pushes them into the stalest band.

| Band | Rule | Visual token |
| --- | --- | --- |
| newest | `<14d` | `bg-primary/70` |
| recent | `14-30d` | `bg-primary/40` |
| aging | `30-60d` | `bg-accent/50` |
| stale | `60-90d` | `bg-muted-foreground/30` |
| oldest | `>90d` | `bg-destructive/50` |

- The freshness widget renders one square per page and uses the tooltip format ``${title} (${section}) — ${daysOld}d old``.

## Filter behavior
- Filtering is entirely client-side.
- The text box lowercases and trims the query, then matches it against:
  - `page.slug.toLowerCase()`
  - `page.title.toLowerCase()`
- There is no description search, fuzzy search, regex, or server round-trip.
- The section dropdown is built from the current page set as `["all", ...new Set(pages.map((page) => page.section))]`.
- A row survives only when both conditions pass:
  - section matches the selected section or the selector is `all`
  - title or slug contains the normalized query, or the query is empty

## Table presentation
- `ContentTable` defines four columns only: `Title`, `Section`, `Description`, `TOC depth`.
- Title cells render as direct links to the docs page URL.
- Section cells render as outline badges.
- Description cells truncate long values and show `Missing` in destructive styling when absent.
- TOC depth renders in monospace tabular numerals.
- `DataTable` adds the shared table shell:
  - sortable headers with `aria-sort`
  - client-side sorting
  - page size of 20 rows
  - Prev/Next pagination when more than one page exists
  - empty-state row: `No rows are available for this view yet.`

## Page composition cues
- `/admin/content` is more than the table. It also shows:
  - KPI cards for total pages, missing descriptions, shallow TOC rows, and section count
  - a bar list of pages by section
  - the freshness swatch grid
  - a separate `Missing Descriptions` findings list when any rows lack descriptions
- That means the audit surface has two operator modes:
  - tabular inventory for broad scanning
  - explicit findings for the highest-signal content gaps

## Related notes
- [[wiki/topics/docs-admin-surface|Docs Admin Surface]]
- [[wiki/topics/docs-telemetry-health|Docs Telemetry and Health]]
- [[wiki/topics/docs-site-source-summary|Docs Site Source Summary]]
- [[wiki/topics/docs-search-surface|Docs Search Surface]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| shared docs source graph and `/docs` base URL | `docs/lib/source.ts` | canonical runtime loader for docs pages |
| page inventory, section derivation, slug serialization, TOC count, mtime lookup, audit outputs | `docs/lib/admin/content-audit.ts` | canonical content-audit loader |
| row type for normalized page metadata | `docs/lib/admin/types.ts` | defines `ContentPageMeta` contract |
| content page KPI labels, freshness data derivation, missing-description findings list | `docs/app/(admin)/admin/content/page.tsx` | admin page composition |
| client-side search and section filter behavior | `docs/app/(admin)/admin/content/filterable-content-table.tsx` | filter state and matching rules |
| content-table column set and cell rendering | `docs/app/(admin)/admin/content/content-table.tsx` | title link, badge, truncation, TOC depth presentation |
| shared data-table sorting, pagination, empty state, and `aria-sort` behavior | `docs/components/admin/data-table.tsx` | TanStack wrapper used by content table |
| freshness color bands and tooltip format | `docs/components/admin/content-freshness.tsx` | operator-facing freshness legend and swatch rendering |
