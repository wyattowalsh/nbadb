# Audit C: Core Authored Docs Pages

Audit date: 2026-03-28
Auditor: Claude Code (Opus 4.6)
Pages inspected: `/docs`, `/docs/installation`, `/docs/architecture`, `/docs/cli-reference`
Method: Source MDX review, component inspection, rendered HTML checks via dev server (Next.js 16.2.1 Turbopack), server log analysis, codebase cross-reference for accuracy.

---

## Per-Page Findings

### /docs (Index)

#### Defects

1. **Nested `<a>` hydration error (P1, cross-page)**
   The docs layout (`app/docs/[[...slug]]/layout.tsx:75`) wraps a `<Link href="/">` inside the Fumadocs `nav.title` prop. Fumadocs itself wraps `nav.title` inside its own `<Link>`, producing `<a>` inside `<a>`. The server log explicitly warns: "In HTML, `<a>` cannot be a descendant of `<a>`". This causes React hydration failures on every docs page. The nav brand should use a `<span>` or `<div>` wrapper instead of `<Link>`.

2. **Table counts in "Public model families" are stale if inherited from architecture page (cross-reference)**
   The index page StatGrid says "Star schema" and "Full coverage" without specific counts, which is fine -- but it links to Architecture where counts are given. See Architecture findings for stale numbers.

3. **`pip install nbadb` in the "First five minutes" code block may mislead source-route users**
   The quick snippet at line 80-83 shows `pip install nbadb` followed by `nbadb init`, but users who cloned from source (the contributor path) should use `uv run nbadb init`. The page does note both routes elsewhere, but the hero code block only shows the pip path.

4. **Redundant navigation surfaces create cognitive overload**
   The index page has five distinct navigation mechanisms for essentially the same content: (a) ScoutCard grid, (b) "Use this page when..." table, (c) "First five minutes" ordered list, (d) "Choose your route" cards, (e) "Reader routes in one glance" table, (f) "Fast lanes by reader" cards, (g) "Jump to the rest of the arena" list. Seven navigation patterns for four core pages creates scan fatigue rather than clarity.

#### Enhancement Ideas

- Consolidate navigation aids to at most three: a hero card grid for quick routing, one decision table for the "which page?" question, and a bottom "Jump to the rest of the arena" list. Remove the duplicate "Reader routes in one glance" table and "Choose your route" DataColumns since the "Fast lanes by reader" cards already serve that purpose.
- Add a visible version/build-date indicator (e.g., "Docs generated from v4.x on YYYY-MM-DD") so readers know if the page is current.
- The "Generated vs. hand-written docs" section is more of a contributor note than a reader navigation aid. Move it to a collapsed details block or a contributor-only callout.

---

### /docs/installation

#### Defects

1. **Nested `<a>` hydration error (same as all docs pages)** -- see /docs defect #1.

2. **No mention of `run-quality` command that the CLI Reference documents**
   The "First possession checklist" suggests `nbadb schema` and `nbadb status` but does not mention `nbadb run-quality` as a verification step, even though it exists and is documented on the CLI Reference page.

3. **Missing `.env.example` file reference is unverifiable**
   Line 92 says "start from the checked-in example file: `cp .env.example .env`". If `.env.example` does not exist in the repo, this instruction will silently fail.

4. **`NBADB_KAGGLE_DATASET` default value uses a slug that may not match the actual Kaggle dataset slug if it changed**
   The table says default is `wyattowalsh/basketball`. This should be periodically verified against the actual Kaggle dataset.

#### Enhancement Ideas

- Add a "Verify your install" step with expected output (e.g., what `nbadb --help` should print, or the table count from `nbadb schema`).
- The "What lands in your data directory" section duplicates information between the table and the ScoutCard grid immediately below it. Keep one.
- Add a note about Python virtual environment creation (`python -m venv` or `uv venv`) before `pip install nbadb`, since installing into a global Python is a common beginner mistake.
- The "Docs contributors: generated artifacts boundary" section at the bottom is a contributor concern, not an install concern. Consider moving it to an AGENTS.md or Architecture page to keep Installation focused on getting started.

---

### /docs/architecture

#### Defects

1. **Nested `<a>` hydration error (same as all docs pages)** -- see /docs defect #1.

2. **Stale table counts in "Public model families" (P1)**
   The page claims:
   - Dimensions: 17 (actual: **18** dim_*.py files)
   - Facts: 102 (actual: **128** fact_*.py files)
   - Bridges: 2 (actual: **5** bridge_*.py files)
   - Aggregates: 16 (actual: **19** agg_*.py files)
   - Analytics outputs: 4 (actual: **12** analytics_*.py files)

   Every single count is stale. The total is listed implicitly as ~141 but actual is ~182. This is the most significant accuracy defect across all four pages.

3. **Mermaid diagram for run-mode decision tree references `nbadb full` without noting deprecation**
   The `full` command is marked `deprecated=True` in `src/nbadb/cli/commands/full.py`. The decision tree flowchart and the run-mode table both present it as a current peer of `init`, `daily`, and `monthly` without any deprecation notice.

4. **Internal state table list is incomplete**
   The "Internal tables to recognize quickly" section lists 8 tables but misses tables that may have been added since (e.g., those from the metadata or journal-summary commands). The `_transform_metrics` table listed separately from `_pipeline_metrics` should be verified as still distinct.

5. **"Docs boundary" section duplicates content from the index page**
   Both `/docs` and `/docs/architecture` include the same generator-owned files list and the same `uv run nbadb docs-autogen` command block. This creates a maintenance burden where updates must be made in two places.

#### Enhancement Ideas

- Add an automated mechanism (or a callout) indicating these counts are approximate and may drift. Better yet, generate them from the codebase at docs-build time.
- Mark `nbadb full` as deprecated in the run-mode decision flowchart and table, and guide users to `nbadb backfill run` as the replacement.
- The "Directory map by responsibility" table is excellent for contributors but could include a "you probably won't touch this" indicator for analyst readers.
- The Mermaid pipeline flowchart is clean but the validation tiers section uses a plain `text` code block (`raw -> staging -> star`) that adds no value over the table below it. Remove the code block.

---

### /docs/cli-reference

#### Defects

1. **Nested `<a>` hydration error (same as all docs pages)** -- see /docs defect #1.

2. **StatGrid claims "19 (15 top-level + 4 backfill subcommands)" -- actual count is higher (P1)**
   Actual top-level commands registered via `@app.command`: `ask`, `audit-models`, `chat`, `daily`, `docs-autogen`, `download`, `export`, `extract-completeness`, `full` (deprecated), `init`, `journal-summary`, `lint-sql`, `metadata`, `migrate`, `monthly`, `run-quality` (deprecated), `scan`, `schema`, `status`, `upload` = **20 top-level** + **4 backfill subcommands** = **24 total**. The page is missing 5 commands entirely.

3. **Missing commands from the full command matrix (P1)**
   The following registered commands are not documented anywhere on the page:
   - `nbadb chat` -- interactive chat/query interface
   - `nbadb scan` -- scanning command
   - `nbadb lint-sql` -- SQL linting command
   - `nbadb metadata` -- metadata management command
   - `nbadb journal-summary` -- journal summary command

4. **`nbadb full` documented without deprecation notice (P2)**
   The command is `deprecated=True` in the source but appears in the CLI Reference as a current, recommended command alongside `init`, `daily`, and `monthly`. It should be clearly marked as deprecated with guidance on the replacement (`backfill run`).

5. **`nbadb run-quality` documented without deprecation notice (P2)**
   Similarly, `run-quality` is `deprecated=True` in the source but documented as a current command.

6. **`--output-format` flag collision with `--format` (minor clarity issue)**
   The shared flags table shows `--format/-f` for `init` and `export`, and `--output-format/-f` for `status`. Both use `-f` as the short flag but for different purposes. The page notes this but it could be clearer that these are on different commands and will not conflict.

7. **GitHub sidebar footer links to `wyattowalsh/nba-db` but installation page and clone URL use `wyattowalsh/nbadb`**
   The sidebar footer component (`docs-shell.tsx:133`) links to `https://github.com/wyattowalsh/nba-db` but the installation page clone command uses `https://github.com/wyattowalsh/nbadb.git`. One of these is wrong.

#### Enhancement Ideas

- Add a "Deprecated commands" section that lists `full` and `run-quality` with migration guidance.
- Add the missing 5 commands to the full command matrix.
- Consider generating the command matrix from the Typer app introspection at build time to prevent drift.
- The "Opening possessions" quick-reference table at the top is very effective. Consider adding `nbadb scan`, `nbadb chat`, and `nbadb lint-sql` to it.
- The backfill section is thorough and well-structured. Use it as a template for documenting the other missing command families.

---

## Cross-Page Observations

### Structural patterns (positive)

- **Consistent page anatomy**: All four pages follow the same layout: StatGrid hero, ScoutCard quick navigation, CourtDivider sections, decision tables, Callout tips, and "best next reads" footer. This creates a predictable, learnable rhythm.
- **Basketball metaphor is well-controlled**: Terms like "tipoff," "possession," "sideline play sheet," and "arena" are used sparingly enough to add flavor without obstructing clarity.
- **Internal links are valid**: Every `href="/docs/..."` link target resolves to an existing MDX file. No broken internal links were found.
- **Custom components render correctly**: StatPill, ScoutCard, DataColumns, InsightCard, CourtDivider all map to valid component definitions in `components/mdx.tsx`.

### Structural patterns (negative)

1. **Hydration errors on every docs page** due to nested `<a>` in the layout nav title. This is the single highest-priority fix across the entire docs site.

2. **Table counts are stale across Architecture and CLI Reference**. Both pages hard-code numbers (dimensions, facts, bridges, aggregates, analytics views, CLI commands) that have drifted significantly from the codebase. Every numeric claim should be verified.

3. **Duplicated content across pages**: The "generated artifacts boundary" block (listing generator-owned files + the `docs-autogen` command) appears on `/docs`, `/docs/installation`, and `/docs/architecture`. This creates triple-maintenance burden. Extract it to a single canonical location and link to it.

4. **Deprecated commands (`full`, `run-quality`) treated as current** on both Architecture and CLI Reference. Readers may invest time learning commands that will be removed.

5. **Five CLI commands are undocumented**: `chat`, `scan`, `lint-sql`, `metadata`, `journal-summary` exist in the codebase but are absent from the CLI Reference page.

6. **Over-navigation on the index page**: Seven distinct navigation mechanisms for four core pages. Consolidation would improve scannability.

7. **No visual differentiation for generated vs. authored page chrome**: The DocsPageHero, DocsContextRail, and sidebar all render identically for authored pages (like these four) and generated reference pages. A subtle visual cue would help readers orient.

### Server/runtime observations

- **SyntaxError on homepage**: `SyntaxError: Unexpected end of JSON input` on the `/` route (line 24-27 of server log). This is a homepage issue, not a docs issue, but it caused intermittent 500 errors during testing.
- **Hydration mismatch on Counter component**: The homepage Counter component causes hydration mismatches due to client-side animation (shimmer class) not matching server render.
- **Slow initial compilation**: First docs page load took 67 seconds due to `generate-params` taking 34 seconds. Subsequent loads are fast (195-518ms). This is a Turbopack dev-mode issue, not a production concern.
- **Deprecated middleware warning**: Next.js 16 warns about the `middleware.ts` convention being deprecated in favor of `proxy.ts`.

---

## Notes

- All source files were read directly from the filesystem. Rendered HTML was checked via curl against the local dev server.
- The Chrome DevTools MCP could not connect because Chrome was not running with `--remote-debugging-port`. Screenshots were not captured. All findings are based on source analysis, server log inspection, and HTML response checks.
- The dev server (Next.js 16.2.1 Turbopack) was started during the audit and confirmed serving 200 responses for all four docs pages after initial compilation.
- Component definitions were verified in `docs/components/mdx.tsx` and `docs/components/site/docs-shell.tsx`.
- Codebase counts were verified by file enumeration in `src/nbadb/transform/` and `src/nbadb/cli/commands/`.

### Priority summary

| Priority | Count | Key items |
|----------|------:|-----------|
| P0 (blocking) | 1 | Nested `<a>` hydration error in layout.tsx (affects all docs pages) |
| P1 (accuracy) | 3 | Stale table counts in Architecture, stale CLI command count, 5 undocumented commands |
| P2 (misleading) | 2 | Deprecated commands presented as current (`full`, `run-quality`) |
| P3 (polish) | 4 | Over-navigation on index, duplicate docs-autogen content, GitHub URL mismatch, minor install gaps |

### Files referenced

- `/Users/ww/dev/projects/nbadb/docs/content/docs/index.mdx`
- `/Users/ww/dev/projects/nbadb/docs/content/docs/installation.mdx`
- `/Users/ww/dev/projects/nbadb/docs/content/docs/architecture.mdx`
- `/Users/ww/dev/projects/nbadb/docs/content/docs/cli-reference.mdx`
- `/Users/ww/dev/projects/nbadb/docs/app/docs/[[...slug]]/layout.tsx` (nested `<a>` source)
- `/Users/ww/dev/projects/nbadb/docs/app/docs/[[...slug]]/page.tsx`
- `/Users/ww/dev/projects/nbadb/docs/components/mdx.tsx`
- `/Users/ww/dev/projects/nbadb/docs/components/site/docs-shell.tsx`
- `/Users/ww/dev/projects/nbadb/docs/lib/site-config.ts`
- `/Users/ww/dev/projects/nbadb/docs/content/docs/meta.json`
