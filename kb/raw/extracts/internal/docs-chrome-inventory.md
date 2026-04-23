# Docs Chrome Inventory

## Purpose
- Grouped internal extract manifest for the docs chrome surface: shared docs-shell exports, route-aware navigation and hero components, generated-page helper surfaces, and the App Router assembly files that compose them into the docs experience.

## High-value paths

### Chrome barrel and section navigation
| Path | Inventory role |
| --- | --- |
| `docs/components/site/docs-shell.tsx` | Barrel export for the docs chrome surface; re-exports nav, hero, generated helpers, and context rail so layout/page assembly imports stay centralized. |
| `docs/components/site/docs-nav.tsx` | Houses `DocsNavBadge`, `DocsSidebarBanner`, and `DocsSidebarFooter`; turns section metadata into top-nav route pills, sidebar stats, quick links, and seeded search prompts. |
| `docs/lib/site-config.ts` | Barrel export for split site-config modules consumed by nearly every chrome component. |
| `docs/lib/site-config/sections.ts` | Canonical section-level copy, stats, quick links, hub routes, and seeded search prompts used by nav, hero, and context rail surfaces. |

### Hero and context rail surfaces
| Path | Inventory role |
| --- | --- |
| `docs/components/site/docs-page-hero.tsx` | Page hero renderer with breadcrumbs, section badges, TOC count, ownership badges, last-updated label, lead CTA, related links, and section stats. |
| `docs/components/site/docs-context-rail.tsx` | Related-links rail plus search/discovery panel; supports `priority` mode for generated pages and derives cross-section badges from hrefs. |

### Generated-page helper surfaces
| Path | Inventory role |
| --- | --- |
| `docs/components/site/docs-generated.tsx` | Small barrel that re-exports the generated entry, coverage, scan, and modules surfaces as one import lane. |
| `docs/components/site/docs-generated-entry.tsx` | Generated-page introduction block: ownership boundary, generator label, workflow steps, stats, and regenerate command. |
| `docs/components/site/docs-generated-coverage.tsx` | Coverage-boundary explainer for schema-backed reference pages and lineage; reads exact counts from generated coverage JSON. |
| `docs/components/site/docs-generated-scan.tsx` | TOC-driven scan clustering surface; groups dense generated pages by source family or public table family and includes manual clusters for ER and lineage pages. |
| `docs/components/site/docs-generated-modules.tsx` | Companion-route cards for generated pages; renders the curated next-step module grid from generated page frame metadata. |
| `docs/lib/site-config/generated-pages.ts` | Canonical generated-page frame and context-rail metadata; defines ownership copy, steps, module cards, and generated-page rail overrides. |
| `docs/lib/generated/schema-coverage.json` | Data source for schema-reference coverage counts and uncovered output examples shown by `DocsSchemaCoverageSurface`. |

### Layout and page assembly
| Path | Inventory role |
| --- | --- |
| `docs/app/docs/{catch-all}/layout.tsx` | Fumadocs `DocsLayout` assembly point; mounts brand title, nav badge, sidebar banner/footer, docs nav links, and footer around the docs route tree. |
| `docs/app/docs/{catch-all}/page.tsx` | Main docs page renderer; computes TOC and ownership state, injects JSON-LD, mounts hero and generated helper surfaces, and switches `DocsContextRail` placement based on whether the page is generated. |

## Notes
- The docs chrome is intentionally split into focused components, but the public import surface is `docs-shell.tsx`; that barrel is the fastest entry point when tracing page composition.
- `docs-nav.tsx`, `docs-page-hero.tsx`, and `docs-context-rail.tsx` all depend on section metadata from `getSectionMeta(...)`; generated-page helpers additionally depend on `getGeneratedPageFrame(...)` and generated-page rail overrides.
- Generated pages receive a different reading order than hand-authored pages in `docs/app/docs/{catch-all}/page.tsx`: entry surface, coverage surface, scan surface, then a priority context rail before the MDX body.
- Hand-authored pages skip the generated helper stack and instead render the standard context rail after the main body.
- `docs-generated-scan.tsx` is the densest helper surface in this inventory: it mixes static copy maps, TOC normalization, family grouping helpers, and manual route clusters for exhaustive ER and lineage artifacts.
- `docs-generated-coverage.tsx` is the explicit ownership-boundary explainer for schema reference coverage. The surface is only as current as `docs/lib/generated/schema-coverage.json`.

## Planned wiki coverage
- `wiki/topics/docs-chrome-assembly.md`
- `wiki/topics/generated-docs-reading-order.md`
- `wiki/topics/docs-site-config-surfaces.md`

## Provenance
- `docs/AGENTS.md`
- `docs/components/site/docs-shell.tsx`
- `docs/components/site/docs-nav.tsx`
- `docs/components/site/docs-page-hero.tsx`
- `docs/components/site/docs-context-rail.tsx`
- `docs/components/site/docs-generated.tsx`
- `docs/components/site/docs-generated-entry.tsx`
- `docs/components/site/docs-generated-coverage.tsx`
- `docs/components/site/docs-generated-scan.tsx`
- `docs/components/site/docs-generated-modules.tsx`
- `docs/app/docs/{catch-all}/layout.tsx`
- `docs/app/docs/{catch-all}/page.tsx`
- `docs/lib/site-config.ts`
- `docs/lib/site-config/sections.ts`
- `docs/lib/site-config/generated-pages.ts`
- `docs/lib/generated/schema-coverage.json`
