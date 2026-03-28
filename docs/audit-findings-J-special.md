# Audit J: Special Routes, Metadata, Edge States

## Sitemap

### Completeness

The sitemap at `/sitemap.xml` returns **50 entries** (1 homepage + 49 docs pages), matching the 49 MDX content files plus the root URL. All seven docs sections are represented:

| Section | Count |
|---|---|
| Homepage (root) | 1 |
| Core docs (architecture, cli-reference, installation, playground) | 5 |
| Schema | 7 (index + 6 sub-pages) |
| Data Dictionary | 6 (index + 5 sub-pages) |
| Diagrams | 5 (index + 4 sub-pages) |
| Endpoints | 8 (index + 7 sub-pages) |
| Lineage | 4 (index + 3 sub-pages) |
| Guides | 12 (index + 11 sub-pages) |
| Docs index | 1 |
| **Total** | **50** |

Admin pages are correctly **excluded** from the sitemap (0 admin URLs found).

### Priority Weights

- **1.0** -- 1 entry: homepage (`https://nbadb.w4w.dev`)
- **0.9** -- 1 entry: docs index (`/docs`)
- **0.7** -- 48 entries: all other docs pages

**Finding:** All 48 non-index docs pages share the same 0.7 priority. The sitemap source (`app/sitemap.ts` lines 8-12) only distinguishes between the docs index (`page.url === "/docs"`) and everything else. Section index pages (e.g., `/docs/schema`, `/docs/guides`) and high-traffic pages like `/docs/guides/analytics-quickstart` could benefit from differentiated priority weights.

**Finding:** All `lastModified` values are set to `new Date()` at generation time, meaning every entry shares the same timestamp. This provides no useful signal to crawlers about which pages actually changed recently. Ideally, `lastModified` would reflect the actual file modification time or git commit date.

## Robots.txt

Live response from `/robots.txt`:

```
User-Agent: *
Allow: /

Host: https://nbadb.w4w.dev
Sitemap: https://nbadb.w4w.dev/sitemap.xml
```

Source: `app/robots.ts` -- correctly references `siteOrigin` (`https://nbadb.w4w.dev`).

**Finding (D-SEO-1):** No `Disallow: /admin` rule exists in `robots.txt`. While admin pages have `<meta name="robots" content="noindex, nofollow"/>` in HTML, adding a `Disallow` in robots.txt provides defense-in-depth and prevents crawl budget waste. The `robots.ts` source only specifies `allow: "/"` with no disallow entries.

## OG Image Generation

Source: `app/docs-og/[[...slug]]/route.tsx`

- **`/docs-og/schema`** -- HTTP 200, `content-type: image/png`
- **`/docs-og/architecture`** -- HTTP 200, `content-type: image/png`
- **`/docs-og`** (docs root, no slug) -- HTTP 200

The OG image route uses `next/og` `ImageResponse` to generate 1200x630 PNG images server-side. It renders:
- Site name + section label badge
- Page title (72px bold) + description
- Footer stats from `site-metrics.generated.ts` (first 2 metrics + "DuckDB")

The route gracefully handles missing pages by falling back to section metadata via `getSectionMeta()`.

**Finding (D-OG-1):** `/docs-og/nonexistent-slug` returns HTTP 200 with a fallback image. This is acceptable behavior (no broken images in social previews for stale links), but worth noting -- it will never return a 404 for an OG image request.

## 404/Error States

| URL | HTTP Status | Behavior |
|---|---|---|
| `/docs/nonexistent-page` | **404** | Correct. Returned by `notFound()` in `page.tsx` line 50 when `source.getPage()` returns null. Page title shows "nbadb -- NBA Data Warehouse" (inherits root template). Has `<meta name="robots" content="noindex"/>`. |
| `/nonexistent` | **404** | Correct. Next.js default 404 page. Title shows "404: This page could not be found." |

**Finding (D-404-1):** No custom `not-found.tsx`, `error.tsx`, or `global-error.tsx` files exist anywhere in the app. The site relies entirely on Next.js/Fumadocs default error pages. This means:
- No branded 404 page with navigation back to docs
- No error boundary to catch and display runtime errors gracefully
- No `global-error.tsx` to handle root layout errors

The `/docs/nonexistent-page` 404 correctly includes `<meta name="robots" content="noindex"/>` (Next.js default behavior).

## Meta Tags

### Root Metadata

Source: `app/layout.tsx` lines 26-75

The root layout exports comprehensive `Metadata`:

| Tag | Value | Status |
|---|---|---|
| `metadataBase` | `https://nbadb.w4w.dev` | Correct |
| `title.template` | `%s \| nbadb` | Correct |
| `title.default` | `nbadb -- NBA Data Warehouse` | Correct |
| `description` | `Star-schema NBA data warehouse...` | Present |
| `application-name` | `nbadb` | Present |
| `keywords` | 8 keywords (NBA data, basketball analytics, DuckDB, etc.) | Present |
| `canonical` | `/` (root) | Present |
| `og:type` | `website` | Correct |
| `og:image` | `https://nbadb.w4w.dev/opengraph-image.png` | Present, verified accessible (200) |
| `og:image` dimensions | 1200x630 | Correct |
| `twitter:card` | `summary_large_image` | Correct |
| `manifest` | `/site.webmanifest` | Present, verified accessible (200) |
| `favicon.ico` | Present | Verified accessible (200) |
| `apple-icon.png` | Present | Verified accessible (200) |

**Verified in live HTML:** All root meta tags render correctly on the homepage.

### Per-Page Metadata

Source: `app/docs/[[...slug]]/page.tsx` lines 88-129

Each docs page generates:
- `title` -- from frontmatter `page.data.title`
- `description` -- from frontmatter `page.data.description`
- `canonical` -- set to `page.url` (e.g., `/docs/architecture`)
- `og:type` -- `article` (overrides root `website`)
- `og:image` -- per-page dynamic OG: `https://nbadb.w4w.dev/docs-og/{slug}`
- `og:site_name` -- `nbadb`
- `twitter:card` -- `summary_large_image`

**Verified in live HTML for `/docs/architecture`:**
- `og:title` = "Architecture"
- `og:description` = "Control-tower view of the nbadb pipeline..."
- `og:url` = `https://nbadb.w4w.dev/docs/architecture`
- `og:image` = `https://nbadb.w4w.dev/docs-og/architecture`
- `canonical` = `https://nbadb.w4w.dev/docs/architecture`

**Verified in live HTML for `/docs/schema`:**
- `og:title` = "Schema Reference"
- `og:url` = `https://nbadb.w4w.dev/docs/schema`
- `og:image` = `https://nbadb.w4w.dev/docs-og/schema`

All per-page metadata is correctly generated. The `alternates.canonical` on per-page metadata correctly uses relative paths, which Next.js resolves against `metadataBase`.

## Admin SEO (noindex/nofollow)

Source: `app/(admin)/admin/layout.tsx` lines 5-11

```typescript
export const metadata: Metadata = {
  title: {
    template: "%s | Control Center",
    default: "Control Center",
  },
  robots: { index: false, follow: false },
};
```

**Verified in live HTML for `/admin`:**
```html
<meta name="robots" content="noindex, nofollow"/>
```

The admin layout correctly sets `noindex, nofollow` via Next.js Metadata API. This applies to all admin routes nested under `(admin)/admin/`.

Additional protection: The middleware (`middleware.ts`) guards `/admin/:path*` and `/api/admin/:path*` behind HMAC-signed session cookies when `ADMIN_PASSWORD` is set, so admin pages are also access-controlled.

## Defects

| ID | Severity | Description |
|---|---|---|
| D-SEO-1 | Low | `robots.txt` has no `Disallow: /admin` rule. While admin pages have `noindex,nofollow` meta tags, adding a robots.txt disallow provides defense-in-depth and prevents crawl budget waste on protected pages. |
| D-404-1 | Medium | No custom `not-found.tsx`, `error.tsx`, or `global-error.tsx` exist. Users hitting invalid URLs see a generic, unbranded error page with no navigation to recover. |
| D-SITEMAP-1 | Low | All `lastModified` timestamps are identical (`new Date()` at generation time). Crawlers receive no useful freshness signal. |
| D-SITEMAP-2 | Low | Only two priority tiers (1.0 for homepage, 0.9 for `/docs`, 0.7 for everything else). Section index pages and high-value guide pages could benefit from 0.8 priority. |
| D-OG-1 | Info | OG image route returns 200 for nonexistent slugs (falls back to section metadata). Not strictly a defect, but worth documenting. |

## Enhancement Ideas

1. **Add `Disallow: /admin` to `robots.ts`** -- Add a disallow rule for `/admin` paths in the robots configuration to complement the meta tag approach.

2. **Create a branded `not-found.tsx`** -- Add a custom 404 page at `app/not-found.tsx` and/or `app/docs/[[...slug]]/not-found.tsx` with site navigation, search, and links to popular pages.

3. **Create `error.tsx` and `global-error.tsx`** -- Add error boundaries to gracefully handle runtime errors with a branded experience rather than raw Next.js error output.

4. **Use file-based `lastModified` in sitemap** -- Derive `lastModified` from MDX file modification time or git history instead of runtime `new Date()`. Fumadocs may expose file metadata for this.

5. **Differentiate sitemap priorities** -- Give section index pages (`/docs/schema`, `/docs/guides`, etc.) a 0.8 priority to signal their importance as navigation hubs.

6. **Add `Disallow: /api/` to robots.txt** -- API routes should not be crawled. Currently nothing prevents crawlers from hitting `/api/admin/*` endpoints.

7. **Consider `X-Robots-Tag` header for admin API routes** -- The middleware could add `X-Robots-Tag: noindex` headers on admin API responses for belt-and-suspenders SEO protection.

## Notes

- The docs site runs Next.js 16.2.1 with Turbopack and Fumadocs 16.
- `siteOrigin` is `https://nbadb.w4w.dev` (defined in `lib/site-config.ts` line 99).
- The `generateStaticParams()` export in `page.tsx` enables static generation for all docs pages.
- The OG image generation uses `site-metrics.generated.ts` which is auto-generated by `uv run nbadb docs-autogen` and should not be hand-edited.
- The middleware is noted as deprecated by Next.js 16 (console warning: "The 'middleware' file convention is deprecated. Please use 'proxy' instead."). This does not affect functionality today but should be addressed in a future migration.
- Static assets (favicon, apple-icon, opengraph-image, manifest) are all accessible and return HTTP 200.
- The `middleware.ts` matcher is scoped to `/admin/:path*` and `/api/admin/:path*` only -- it does not interfere with docs routes, sitemap, or robots.txt generation.
