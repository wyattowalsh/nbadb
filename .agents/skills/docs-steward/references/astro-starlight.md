# Astro + Starlight Reference

## 1. Version Snapshot (2026-03-05)

- `astro`: `5.18.0`
- `@astrojs/starlight`: `0.37.6`

Re-check before claiming "latest": see `version-refresh.md`.

## 2. Core Project Signals

- Canonical pair: `<site-root>/astro.config.mjs` or `<site-root>/astro.config.ts` with `<site-root>/src/content/docs`
- Starlight integration in Astro config (`@astrojs/starlight`)
- Monorepo-safe roots are valid (`.`, `docs/`, `apps/docs/`) as long as config + content paths are aligned

## 3. High-Value Sync Workflow

1. Validate content collection schemas.
2. Regenerate derived docs artifacts (for this repo, via `wagents docs generate`).
3. Build-check the site.
4. Scan for orphaned pages and sidebar drift.

## 4. Advanced Configuration Focus

- Use explicit sidebar group hierarchy.
- Ensure slug stability for long-lived links.
- Keep custom components constrained to content UX needs.
- Keep frontmatter complete (`title`, `description`, nav metadata).

## 5. Health Checks

- Broken internal links and anchor mismatches
- Missing frontmatter required by docs conventions
- Dead-end nav entries
- Unreferenced docs files
- Build warnings from MDX or content collections

## 6. Enhancement Priorities

- Improve task-first docs entry pages.
- Add cross-link blocks for related guides and API pages.
- Consolidate repetitive setup content with shared includes/components.
- Improve "quick start -> deep dive" progression.

## 7. Common Anti-Patterns

- Flat nav with too many top-level pages
- Duplicate content across guides and references
- Opaque page titles ("Overview", "Details", "Notes")
- Version claims with no registry/source evidence

## 8. Command Skeletons

```bash
# Install/update
pnpm add astro@latest @astrojs/starlight@latest

# Build checks
pnpm astro check
pnpm astro build
```

Use project-specific command wrappers when present.
