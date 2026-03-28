# Audit A: Home + Entry Funnel

## Screenshots Taken

Browser-based screenshots were not captured because no Chrome instance with remote debugging was available for the Playwright or Chrome DevTools MCPs to connect to. All findings below are derived from a thorough source-code audit of every file in the homepage render path, combined with HTTP status checks against the running dev server on localhost:3000.

## Defects

### D1. All docs CTA destinations return HTTP 500 (Critical)

Every link on the homepage that routes into `/docs/*` returns a 500 error at the time of this audit. Tested routes:

| Route | Status | Source |
|-------|--------|--------|
| `/` | 200 | Homepage |
| `/docs/guides/analytics-quickstart` | 200 | Hero CTA "Analyst quickstart" |
| `/docs/guides/daily-updates` | 200 | Hero CTA "Operator guide" |
| `/docs/schema` | 500 | Hero CTA "Schema map", section index card, footer |
| `/docs/playground` | 500 | Hero CTA "Browser playground", quick-start step 03 |
| `/docs/endpoints` | 500 | Section index card, footer |
| `/docs/lineage` | 500 | Section index card, footer |
| `/docs/guides` | 500 | Footer, section index card |
| `/docs` | 500 | Section index card "Core Docs" |
| `/docs/data-dictionary` | 500 | Section index card |
| `/docs/diagrams` | 500 | Section index card |

The error response body is `<p>An error occurred.</p>` with a Vike reference, which is unexpected for a Next.js app. This may be a dev-server compilation issue or a runtime error in the docs layout (`app/docs/[[...slug]]/layout.tsx` or `page.tsx`). Two routes (analytics-quickstart and daily-updates) do work, which suggests the issue is in specific layout/page components rather than a universal problem.

**Impact**: A first-time visitor who clicks "Schema map", "Browser playground", or any section index card gets a blank error page. Only the "Analyst quickstart" and "Operator guide" CTAs work.

**File**: `docs/app/docs/[[...slug]]/layout.tsx`, `docs/app/docs/[[...slug]]/page.tsx`

### D2. No `<h1>` element on the homepage (Medium)

The homepage has zero heading elements (`<h1>` through `<h6>`). The project title "nbadb" is rendered as a `<span>` with visual styling (`nba-display nba-title-gradient`). Screen readers and crawlers have no document heading to anchor to.

**File**: `docs/app/(home)/page.tsx`, line 63

### D3. All three `<Image>` instances use empty `alt=""` (Low)

- Line 56: Hero logo (decorative -- acceptable)
- Line 134: Court panel logo (inside `aria-hidden` container -- acceptable)
- Line 320: Footer logo (decorative -- acceptable)

These are actually handled correctly since the logo images are decorative and the court panel is `aria-hidden="true"`. No action needed, but noted for completeness.

### D4. No navigation header on the homepage (Medium)

The homepage renders directly inside a bare `HomeLayout` that is just a fragment pass-through (line 3, `app/(home)/layout.tsx`). There is no site navigation, search bar, theme toggle, or back-to-docs link visible to the user. Once a visitor lands on the homepage, there is no persistent navigation chrome to orient them.

**File**: `docs/app/(home)/layout.tsx`

### D5. Grid gap pattern inconsistency (Low)

The hero signals grid (line 77) uses `gap-px border border-border bg-border` which creates visible 1px divider lines between cells. The stat counters grid (line 174), section index grid (line 210), and audience lanes grid (line 262) use `gap-px border border-border` without `bg-border`. In these grids, the 1px gap has no background color, so whether dividers appear depends on the parent background. This is cosmetically inconsistent but likely not visually broken because the `bg-card` children fill the space.

**File**: `docs/app/(home)/page.tsx`, lines 77, 174, 210, 262

## Enhancement Ideas

### E1. Add an `<h1>` heading for SEO and accessibility

Wrap the "nbadb" title text in an `<h1>` element. The visual styling can remain identical. Consider also adding section headings (`<h2>`) for "Scoreboard", "Choose by question", "Choose your lane", and "Quick start" -- these are currently `<span>` elements with the `nba-kicker` class.

### E2. Add a minimal navigation bar to the homepage

Even a simple top bar with the logo, a "Docs" link, GitHub link, and a theme toggle would significantly improve wayfinding. Currently, the only way out of the homepage is through the CTA buttons and footer links.

### E3. Improve skip-navigation for keyboard users

There is no skip-to-content link. Given the number of interactive elements (4 CTAs, 6 section cards, 3 audience lanes, 3 quick-start links, 9+ footer links), a skip link would benefit keyboard-only users.

### E4. Add `id` attributes to section landmarks

The four `<section>` elements have no `id` attributes. Adding IDs like `id="hero"`, `id="sections"`, `id="lanes"`, `id="quickstart"` would enable in-page anchor links and improve screen reader navigation.

### E5. Counter `aria-live` region is empty during animation

The `Counter` component (line 101-103 of `counter.tsx`) only announces the value when `displayValue === target`. During the 600ms count-up animation, the screen reader `aria-live` region is empty string. This is intentional (avoids spamming announcements), but it means there's a brief window where the counter shows `\u00A0` (non-breaking space) visually. If the element is above the fold and the animation fires before the user scrolls, the shimmer placeholder is appropriate. However, if the observer threshold (0.3) is not met on page load, the counters could remain at 0 / shimmer state.

### E6. Consider adding `font-display: swap` safeguard

The layout loads three Google Fonts (IBM Plex Sans, Noto Sans, IBM Plex Mono) via `next/font/google`. Next.js handles `font-display: swap` by default, but the custom `--font-heading`, `--font-sans`, and `--font-mono-var` CSS variables could flash unstyled text if font loading is slow on cold visits.

### E7. Court panel illustration is hidden on mobile but takes up space

The `.nba-court-panel` becomes a single-column layout below 960px (the `nba-hero-grid` media query). On mobile, it appears below the hero text. At `min-height: 22rem` (18rem below 640px), it is a large decorative element that pushes actionable content further down the viewport. Consider hiding it entirely on small screens or reducing its height further.

### E8. Quick-start step notes are hidden on mobile

The descriptive `note` text in quick-start items has `className="hidden sm:inline"` (line 305). On mobile (< 640px), users only see the step number and label without context. Consider showing a condensed note or using a different layout.

### E9. Footer lacks a "back to top" affordance

The page can be quite long (hero + scoreboard + section index + audience lanes + quick start + footer). A back-to-top link or sticky micro-nav would help orientation on longer scroll depths.

### E10. The `style={{ fontFamily: ... }}` inline overrides are redundant

The inline `style={{ fontFamily: "var(--font-sans), system-ui, sans-serif" }}` appears on 10+ elements throughout the page (lines 71, 85, 114, 154, 167, 203, 230, 256, 279, 305, 325, 365). Since the `<body>` already sets `font-family: var(--font-sans), system-ui, sans-serif` in global CSS (line 136), these inline styles are redundant unless they are guarding against a Fumadocs or prose override. If so, a single utility class would be cleaner.

## Notes

### What works well

- **Counter component**: Well-engineered with IntersectionObserver trigger, easeOutExpo easing, proper `aria-hidden`/`aria-live` split, and `useSyncExternalStore` for reduced-motion detection. The shimmer loading state is a nice touch.

- **Reduced-motion support**: Both CSS-level (line 1171, global blanket that zeros all animation/transition durations) and JS-level (Counter checks `prefers-reduced-motion` and skips to final value immediately). This is thorough.

- **NBA design language**: The court panel illustration is built entirely with CSS (court markings, keys, arcs, center circle) -- no images or SVG required. The animated gradient border (`nba-border-shift`), court pulse animation, and hero glow create an atmospheric feel without being distracting.

- **Information architecture**: The page follows a clear funnel: hero with primary CTA, stat proof points, section index for browsing, audience-based lanes for persona routing, then quick-start for task-oriented entry. This is a well-structured landing page pattern.

- **CTA hierarchy**: "Analyst quickstart" is the sole primary button (filled). "Operator guide", "Schema map", and "Browser playground" are secondary (outline). This correctly signals the default happy path while offering alternatives.

- **Color system**: The oklch-based color palette with light/dark themes is modern and well-organized. The warm primary (hue ~45-48, an amber/orange) gives it the basketball aesthetic without NBA trademark issues.

- **Badge component**: Clean CVA implementation with 6 variants. The `primary` variant for "v4" and `default` for technology badges creates appropriate visual hierarchy.

- **Metadata**: Open Graph, Twitter cards, canonical URL, manifest, and keywords are all configured. The `metadataBase` is set to `https://nbadb.w4w.dev`.

- **Grid pattern**: The `gap-px` + `border` + `bg-card` children pattern creates clean 1px dividers between cards without extra markup. This is an elegant CSS technique.

- **Type scale**: The kicker text (0.65rem, 600 weight, 0.2em tracking, uppercase) is used consistently across all section labels, creating strong visual rhythm. The scoreboard values use mono font with tabular-nums for proper numeric alignment.
