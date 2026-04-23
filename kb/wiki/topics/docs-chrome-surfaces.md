---
title: Docs Chrome Surfaces
tags:
  - kb
  - topics
  - docs
  - frontend
  - chrome
aliases:
  - Docs Page Chrome
  - Docs Route Chrome Surfaces
kind: concept
status: active
updated: 2026-04-15
source_count: 13
---

# Docs Chrome Surfaces

Use this note when the question is "what wraps a `/docs/...` page, in what order, and which surfaces only appear on generated routes?"

## Route boundary
- `docs/app/docs/{catch-all}/layout.tsx` is the always-on outer shell for every docs route.
- `docs/app/docs/{catch-all}/page.tsx` is the inner assembly layer for one resolved docs page.
- `docs/components/site/docs-shell.tsx` is the public barrel for docs chrome.
- `docs/components/site/docs-generated.tsx` is the generated-page sub-barrel.

## Always-on layout chrome
| Surface | File | Where it wraps | Applies to |
| --- | --- | --- | --- |
| Top nav badge/search trigger | `docs/components/site/docs-nav.tsx` -> `DocsNavBadge` | passed as `nav.children` into `DocsLayout` | every `/docs/**` route |
| Sidebar banner | `docs/components/site/docs-nav.tsx` -> `DocsSidebarBanner` | passed as `sidebar.banner` into `DocsLayout` | every `/docs/**` route |
| Sidebar footer | `docs/components/site/docs-nav.tsx` -> `DocsSidebarFooter` | passed as `sidebar.footer` into `DocsLayout` | every `/docs/**` route |
| Docs footer | `docs/components/site/footer.tsx` | rendered after page children inside the layout main column | every `/docs/**` route |

- The top nav, sidebar banner, and sidebar footer all derive section-aware content from `getSectionMeta(slug)`.
- The sidebar footer also seeds search through `section.prompts[0]`, so it is both chrome and a discovery entrypoint.

## Per-page chrome
| Surface | File | Position inside `page.tsx` | Applies to |
| --- | --- | --- | --- |
| Hero | `docs/components/site/docs-page-hero.tsx` -> `DocsPageHero` | first visible surface inside `nba-docs-page`, before any generated surfaces or MDX body | every docs content page |
| Context rail | `docs/components/site/docs-context-rail.tsx` -> `DocsContextRail` | before body for generated pages, after body for hand-authored pages | all docs pages, but in different positions |

- `DocsPageHero` owns breadcrumbs, section badges, stats, title, description, ownership badges, updated date, and lead links.
- `DocsContextRail` is the related/discovery surface driven by `getDocsContextRail(slug)`.
- On generated pages the context rail is rendered with `priority`, which changes both placement and layout emphasis.

## Generated-entry surfaces
The generated-page family is not one component. It is a stack of route-level surfaces exported through `docs/components/site/docs-generated.tsx`.

| Surface | File | Position relative to body | When it renders |
| --- | --- | --- | --- |
| Entry surface | `docs/components/site/docs-generated-entry.tsx` -> `DocsGeneratedEntrySurface` | immediately after hero, before body | when `getGeneratedPageFrame(slug)` returns a frame |
| Coverage surface | `docs/components/site/docs-generated-coverage.tsx` -> `DocsSchemaCoverageSurface` | after entry, before scan/body | only for configured schema and lineage page keys |
| Quick-scan surface | `docs/components/site/docs-generated-scan.tsx` -> `DocsGeneratedScanSurface` | after coverage, before body | only for configured generated page keys with enough TOC/manual clusters |
| Modules surface | `docs/components/site/docs-generated-modules.tsx` -> `DocsGeneratedModules` | after body | when `getGeneratedPageFrame(slug)` returns a frame |

- `DocsGeneratedEntrySurface` is the ownership and "how to use this page" frame.
- `DocsSchemaCoverageSurface` explains where schema-backed reference coverage is narrower than broader lineage/output coverage.
- `DocsGeneratedScanSurface` turns long generated pages into clustered jump lanes.
- `DocsGeneratedModules` is the post-body companion-route grid.

## Wrap order by page type

### Hand-authored docs page
1. `DocsLayout`
2. `DocsNavBadge` + `DocsSidebarBanner` + `DocsSidebarFooter`
3. `DocsPage`
4. `DocsPageHero`
5. MDX body inside `DocsBody` -> `nba-mdx-body`
6. trailing `DocsContextRail`
7. `DocsFooter`

### Generated docs page
1. `DocsLayout`
2. `DocsNavBadge` + `DocsSidebarBanner` + `DocsSidebarFooter`
3. `DocsPage`
4. `DocsPageHero`
5. `DocsGeneratedEntrySurface`
6. optional `DocsSchemaCoverageSurface`
7. optional `DocsGeneratedScanSurface`
8. priority `DocsContextRail`
9. MDX body inside `DocsBody` -> `nba-mdx-body`
10. `DocsGeneratedModules`
11. `DocsFooter`

## Maintainer cues
- Change outer docs chrome in `docs/app/docs/{catch-all}/layout.tsx` or the `docs/components/site/docs-nav.tsx` family, not in MDX.
- Change page assembly order in `docs/app/docs/{catch-all}/page.tsx`.
- Change hero, context-rail, or generated-page messaging in the matching `docs/components/site/docs-*.tsx` file.
- Treat `docs/lib/site-config/sections.ts` and `docs/lib/site-config/generated-pages.ts` as the content model for most chrome text, links, stats, and prompts.

## Related notes
- [[wiki/topics/docs-component-registry|Docs Component Registry]]
- [[wiki/topics/docs-app-stack|Docs App Stack]]
- [[wiki/topics/docs-search-surface|Docs Search Surface]]
- [[wiki/topics/docs-autogen|Docs Autogen]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| docs route-group structure and chrome inventory | `docs/AGENTS.md` | canonical docs-site contract |
| always-on outer shell for docs routes | `docs/app/docs/{catch-all}/layout.tsx` | `DocsLayout`, nav, sidebar, theme switch, footer wrap |
| inner page assembly order | `docs/app/docs/{catch-all}/page.tsx` | hero, generated surfaces, body, and context-rail placement |
| docs chrome barrel export | `docs/components/site/docs-shell.tsx` | public import surface for route files |
| generated-page barrel export | `docs/components/site/docs-generated.tsx` | groups generated entry, coverage, scan, and modules surfaces |
| nav badge and sidebar banner/footer behavior | `docs/components/site/docs-nav.tsx` | section-aware nav/search and sidebar chrome |
| hero contract | `docs/components/site/docs-page-hero.tsx` | breadcrumbs, badges, stats, metadata, and actions |
| context rail contract | `docs/components/site/docs-context-rail.tsx` | related links, search prompts, and `priority` variant |
| generated entry surface | `docs/components/site/docs-generated-entry.tsx` | generator boundary, stats, and usage steps |
| schema coverage surface | `docs/components/site/docs-generated-coverage.tsx` | coverage-specific surface for selected page keys |
| generated scan surface | `docs/components/site/docs-generated-scan.tsx` | TOC/manual cluster jump surface for generated pages |
| generated modules surface | `docs/components/site/docs-generated-modules.tsx` | post-body companion route grid |
| section and generated-page content model | `docs/lib/site-config.ts`; `docs/lib/site-config/sections.ts`; `docs/lib/site-config/generated-pages.ts` | source for labels, prompts, stats, links, and generated-page frames |
