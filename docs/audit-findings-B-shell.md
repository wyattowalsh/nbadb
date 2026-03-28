# Audit B: Docs Shell, Navigation, Search, Theme

> Audited: 2026-03-28
> Method: Code-level review of all shell, layout, nav, search, and theme files.
> Browser testing was blocked (no Chrome DevTools or dev server available at audit time).
> Files inspected: `layout.tsx`, `docs-shell.tsx`, `site-config.ts`, `global.css`, `page.tsx`, `source.config.ts`, `utils.ts`, `badge.tsx`, `button.tsx`, `mdx.tsx`, `middleware.ts`, `api/search/route.ts`, all section `meta.json` files.

---

## Screenshots Taken

None -- Chrome was not running with remote debugging, and the dev server returned HTTP 500 during the audit window. All findings below are from source code analysis and would benefit from visual confirmation once the dev server is available.

---

## Defects

### D1. Command palette trigger is not interactive (P1 -- Accessibility / UX)

**File:** `components/site/docs-shell.tsx` lines 43-47

The `nba-nav-command` element renders as a plain `<div>` containing the Search icon and `⌘K` hint. It is not focusable, not clickable, and has no `role`, `tabIndex`, or click handler. Users who see "Search ⌘K" and try to click it get no response.

**Impact:** Sighted users expect the pill to open search. Keyboard-only users cannot reach it. Screen readers do not announce it as interactive.

**Fix:** Either:
- Make it a `<button>` with `onClick` that dispatches the Fumadocs search open event, or
- Wrap it in Fumadocs' `<SearchToggle />` component so it participates in the built-in `⌘K` flow.

---

### D2. `/docs/playground` is mis-classified as "core" section (P2 -- Navigation)

**File:** `lib/site-config.ts` function `getSectionId()` (line 1499)

The `playground` slug falls through to the `default: return "core"` case. However, `/docs/playground` appears in the sidebar under "Practice Facility" alongside guides, and the guides section's `quickLinks` explicitly links to `/docs/playground`.

**Impact:** When a user is on `/docs/playground`:
- The sidebar banner shows "Core Docs" metadata instead of "Guides"
- The breadcrumb reads "Docs / Playground" instead of "Docs / Guides / Playground"
- The page hero shows Core Docs stats (4 entry pages, 7 sections) instead of Guides stats
- The context rail shows core quick links instead of guides quick links

**Fix:** Add `case "playground": return "guides";` to the switch in `getSectionId()`.

---

### D3. `toneClass` is defined but never consumed (P3 -- Dead code)

**File:** `lib/site-config.ts` (all 7 `SectionMeta` objects define `toneClass`)

Every section defines a `toneClass` string with gradient tokens (e.g., `from-primary/20 via-primary/8 to-accent/14`), but no `.tsx` component reads `section.toneClass`. The field is declared in the `SectionMeta` type but never rendered.

**Impact:** No visual differentiation between section tones. The configuration promise of per-section gradient theming is unfulfilled.

**Fix:** Either apply `toneClass` as a gradient background on `nba-page-hero` or `nba-sidebar-banner`, or remove it from the type and all section objects to reduce config noise.

---

### D4. Breadcrumb intermediate segments may produce 404 links (P2 -- Navigation)

**File:** `lib/utils.ts` function `getDocBreadcrumbs()`

The breadcrumb builder creates a link for every intermediate slug segment. For a page like `/docs/data-dictionary/star`, it produces:
- `Docs` -> `/docs` (exists)
- `Data Dictionary` -> `/docs/data-dictionary` (exists)
- `Star` -> `/docs/data-dictionary/star` (exists, current page)

But for deeper or non-standard slugs, intermediate paths are generated even if no page exists at that path. For example, if there were a `/docs/guides/kaggle-setup/advanced` page, the breadcrumb would link to `/docs/guides/kaggle-setup` which may not be an index page. This is a latent defect since the current tree is mostly 2 levels deep, but the logic has no existence check.

**Impact:** Low risk today, higher risk as content grows.

---

### D5. Sidebar `defaultOpenLevel: 1` may hide nested pages (P3 -- UX)

**File:** `app/docs/[[...slug]]/layout.tsx` line 100

With `defaultOpenLevel: 1`, only the first level of the sidebar tree is expanded by default. Sections like `schema/` have 8 child pages -- users must click to expand, which adds friction when arriving from a direct link to a nested page. Fumadocs does auto-expand the active path, but on first load of the section hub the tree is collapsed.

**Impact:** Minor friction. Users landing on `/docs/schema` see a collapsed sidebar and may not realize there are 8 subpages.

---

### D6. External shields in sidebar footer load lazily with no fallback height (P3 -- Layout shift)

**File:** `components/site/docs-shell.tsx` lines 134-138

The GitHub stars and PyPI version badges are loaded as external `<img>` elements from `img.shields.io` with `loading="lazy"` but no explicit `width`/`height` attributes. When they load, they cause a layout shift in the sidebar footer.

**Impact:** Minor CLS in sidebar. Badges are below the fold so the user impact is small, but it violates CLS best practices.

**Fix:** Add `width` and `height` attributes matching the shields.io badge dimensions (typically ~80x20).

---

### D7. `nba-nav-command` is hidden on mobile (P2 -- Mobile UX)

**File:** `components/site/docs-shell.tsx` line 35

The entire `DocsNavBadge` component (including the search hint) is wrapped in `className="hidden items-center gap-2 md:flex"`. On viewports below `md` (768px), the search hint and section badge disappear entirely.

**Impact:** Mobile users have no visible hint that `⌘K` search exists. They must rely on discovering Fumadocs' built-in search icon or knowing the keyboard shortcut. Combined with D1 (non-interactive trigger), search discoverability on mobile is poor.

**Fix:** Show a minimal search trigger on mobile, even if the full section badge is hidden.

---

## Enhancement Ideas

### E1. Make search prompts clickable in sidebar footer and context rail

The sidebar footer (line 140-147) and context rail (lines 866-886) show curated search prompts like `"fact_player_game"` with labels like "Try in search". These are purely text -- clicking them does nothing. They should programmatically open the search dialog with the suggested query pre-filled.

---

### E2. Add visual section indicators to sidebar tree

The sidebar tree uses Fumadocs' default tree rendering. With 7 sections and many pages, there is no visual grouping beyond the `meta.json` separator labels. Consider adding subtle background tints or left-border accents per section using the already-defined `toneClass` values.

---

### E3. Add skip-to-content link

No skip navigation link exists. The docs layout has a complex header (brand, nav links, section badge, search trigger) and sidebar. Keyboard users must tab through all of these to reach the main content.

**Fix:** Add `<a href="#content" class="sr-only focus:not-sr-only ...">Skip to content</a>` as the first child of `<body>`, and add `id="content"` to the main content area.

---

### E4. Consolidate focus-visible styles

The global `focus-visible` style (global.css line 177-180) uses `outline: 2px solid var(--primary)` with a box-shadow ring. But the button component (button.tsx line 7) uses Tailwind's `focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-offset-2`. These two systems create inconsistent focus indicators depending on whether the element is a custom component or a native element styled with CSS.

**Fix:** Standardize on one approach -- either the CSS custom property ring or Tailwind's ring utilities.

---

### E5. Add keyboard shortcut hints for theme switching

The theme switcher is configured via `themeSwitch={{ mode: "light-dark-system" }}` in the layout, which renders Fumadocs' built-in theme toggle. There is no keyboard shortcut hint or tooltip visible to the user.

---

### E6. Consider `scroll-margin-top` for all anchor targets

Heading elements get `scroll-margin-top: 6rem` (global.css line 891), which accounts for the sticky header. However, the TOC anchor links for generated scan surfaces (e.g., `#table-level-lineage`) point to `<section>` or `<div>` elements that may not have this scroll margin, causing the header to overlap the target on navigation.

---

### E7. Search API is default Fumadocs -- no custom weighting

**File:** `app/api/search/route.ts`

The search endpoint is a vanilla `createFromSource(source)` with no custom configuration. All pages are indexed equally. Given the project's structure, consider:
- Boosting star-schema tables (`dim_*`, `fact_*`) in results
- Adding custom search tags per section
- Weighting guides and quickstart pages higher for common queries

---

### E8. Sidebar banner stat pills are capped at 2

**File:** `components/site/docs-shell.tsx` line 80

The sidebar banner renders `section.stats.slice(0, 2)` -- only 2 of the 3 configured stats per section are shown. The page hero shows all 3. This is likely intentional for sidebar space, but the third stat (often the most useful, e.g., "Best For: Table selection") is always hidden in the sidebar.

---

### E9. Nav links lack visual active state differentiation

**File:** `app/docs/[[...slug]]/layout.tsx` lines 13-57

The `links` array uses `active: "nested-url"` for all nav items, which is the correct Fumadocs pattern. However, the visual differentiation between active and inactive nav links relies entirely on Fumadocs' default styling. Consider adding a bottom border accent or bolder weight to the currently active section tab for stronger wayfinding.

---

## Notes

### Architecture summary

The docs shell is well-structured with clear separation of concerns:

1. **Layout** (`app/docs/[[...slug]]/layout.tsx`): Configures Fumadocs `DocsLayout` with nav links, sidebar banner/footer, brand mark, and theme switcher.
2. **Shell components** (`components/site/docs-shell.tsx`): 8 exported components for nav badge, sidebar banner/footer, page hero, generated entry/scan surfaces, generated modules, and context rail.
3. **Config** (`lib/site-config.ts`): 1546 lines of section metadata, context rails, generated page frames, and helper functions. Section routing is slug-prefix-based.
4. **Styling** (`app/global.css`): ~1300 lines of custom CSS layered on top of Fumadocs + Tailwind + shadcn. Uses oklch color space throughout with `color-mix()` for transparency.

### Section routing

The `getSectionId()` switch correctly routes 6 sections by their top-level slug: `schema`, `data-dictionary`, `diagrams`, `endpoints`, `lineage`, `guides`. Everything else (including `installation`, `architecture`, `cli-reference`, `playground`) falls to `core`.

### Search architecture

Search uses Fumadocs 16's built-in Orama-based search:
- Server-side index built by `createFromSource(source)` at `/api/search`
- Client-side search dialog triggered by `⌘K` (handled by Fumadocs' `RootProvider` with `search={{ enabled: true }}`)
- No custom index configuration, boosting, or faceting

### Theme architecture

- Three-mode switcher: light, dark, system (`themeSwitch={{ mode: "light-dark-system" }}`)
- Default theme is `dark` (configured in `RootProvider`)
- Light and dark palettes defined in CSS custom properties using oklch color space
- Theme attribute is `class` on `<html>` element
- `prefers-reduced-motion` is respected (global.css line 1171-1179)
- `color-scheme: light/dark` is set on `<html>` element

### Breadcrumb accuracy

Breadcrumbs are built from slug segments using `humanizeSlug()` which handles common acronyms (API, CLI, ER, MDX, NBA, PBP, SQL). The function correctly capitalizes each segment and handles hyphenated slugs. Breadcrumbs include proper `aria-label="Breadcrumb"`, `aria-current="page"` on the terminal crumb, and `aria-hidden` on separator characters.

### Responsive behavior

- Nav badge (section indicator + search hint): hidden below `md` (768px)
- Page hero mark (logo): hidden below 960px
- Page hero stat grid: single column below 640px, 3-col above
- Sidebar: Fumadocs handles the mobile drawer/hamburger natively
- Court panel (homepage): reduced min-height and element sizes below 640px

### Cross-section navigation

When navigating between sections (e.g., `/docs/schema` to `/docs/guides`):
- Fumadocs re-renders the sidebar tree for the new page
- The sidebar banner, footer, nav badge, page hero, and context rail all re-derive their section metadata from `getSectionMeta(slug)`, which reads the new slug's top-level segment
- Active states in the sidebar tree update via Fumadocs' built-in `source.pageTree` matching
- The page entry animation (`nba-page-in`) fires on each route change
