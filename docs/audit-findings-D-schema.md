# Audit D: Schema + Data Dictionary

## Schema Section Findings

### /docs/schema (index)

**Rendered OK** (confirmed via fetcher). The page loads correctly and renders StatGrid, StatPill, ScoutCard, CourtDivider, InsightCard, and Mermaid diagram components.

- **Strengths**: Excellent decision-tree routing with multiple entry-point tables ("Choose the right route", "Start by the handle you already have", "Read the jersey prefix"). The Mermaid flowchart with text fallback is a solid affordance. Clear curated-vs-generated boundary explanation.
- **Repetition**: The page offers three separate "choose your starting point" sections (the route table at line 59, the card grid at line 86, and the handle table at line 120). While each has a slightly different angle, the cumulative effect is redundant -- two would be sufficient.
- **Internal linking**: Links to all 8 child pages. Does NOT link to any Data Dictionary page despite the strong conceptual overlap (field meanings vs schema contracts).

### /docs/schema/dimensions

**Rendered OK** (confirmed via fetcher).

- **Strengths**: Clean family clustering (People/identity, Teams/franchise, Game/calendar, Controlled vocabularies). The "When to reach past the default hub" escalation table is useful. SCD2 callout is prominent.
- **Count discrepancy (DEFECT)**: The page header claims "17 dimension tables" and lists 17 by name, but the generated Star Reference only contains 13 dimension schemas. Missing from star-reference: `dim_all_players`, `dim_team_extended`, `dim_defunct_team`, `dim_season_week`. These 4 dimensions lack pandera schemas in `nbadb.schemas.star`, so the generated page cannot document them.
- **No cross-link to Data Dictionary**: When the page says "Jump to the generated Star Reference after the family is chosen", it should also mention the Star Data Dictionary as an alternative lookup for field meanings.

### /docs/schema/facts

**Source reviewed** (dev server went down before live fetch).

- **Strengths**: Good grain-first routing. Clear fact family clustering with representative tables. The discriminator column callout is important and well-placed.
- **Bridge count discrepancy (DEFECT)**: The page documents only 2 bridges (`bridge_game_official`, `bridge_play_player`) but the star-reference shows 5 bridges. Missing from curated docs: `bridge_game_team`, `bridge_lineup_player`, `bridge_player_team_season`. These 3 bridges are entirely undocumented in any curated page.
- **Fact count claim**: Header says "102 fact outputs" but the star-reference contains only 62 `fact_*` entries. The discrepancy is because many fact tables lack pandera schemas (similar to the dimension gap). The curated page should either match the schema count or explain the discrepancy.
- **No cross-link to Data Dictionary**: The page routes to Star Reference for exact columns but never mentions the Data Dictionary glossary or field reference as decoding aids.

### /docs/schema/derived

**Source reviewed.**

- **Strengths**: Clear three-cluster organization (player, team/lineup, league/shot). Good "pick agg_ vs facts vs analytics views" decision table. Rolling window explanation is useful.
- **No issues found** with the 16-table claim; the star-reference has 16 `agg_*` entries matching.
- **Minor**: The table `agg_player_bio` is mentioned but could use a note explaining it overlaps with `dim_player` context.

### /docs/schema/analytics-views

**Source reviewed.**

- **Strengths**: Compact, focused page with clear view chooser and exit ramps.
- **Count discrepancy (DEFECT)**: The page documents 4 analytics views, but 12 analytics transform files exist in `src/nbadb/transform/views/analytics_*.py`. Missing from docs: `analytics_clutch_performance`, `analytics_player_matchup`, `analytics_shooting_efficiency`, `analytics_team_game_complete`, `analytics_draft_value`, `analytics_league_benchmarks`, `analytics_player_impact`, `analytics_game_summary`. At minimum the 4 from session 8 (clutch_performance, player_matchup, shooting_efficiency, team_game_complete) should be documented since they were explicitly added.
- **Zero analytics schemas in star-reference (DEFECT)**: None of the 12 analytics views have pandera schemas in `nbadb.schemas.star`, so they are completely absent from the generated reference pages. This means there is no schema-backed field inventory for any analytics view anywhere in the docs.

### /docs/schema/relationships

**Source reviewed** (earlier fetcher succeeded for initial pages).

- **Strengths**: Excellent practical SQL examples covering the 5 most common join patterns (player game, both teams, matchup, officials, shot zones). The "Common duplication traps" and "Column names to use carefully" tables address real analyst pain points.
- **Only documents 2 of 5 bridges**: SQL examples cover `bridge_game_official` and `bridge_play_player` but not the 3 newer bridges (`bridge_game_team`, `bridge_lineup_player`, `bridge_player_team_season`). No join patterns shown for these.
- **No cross-link to Data Dictionary**: Would benefit from linking to Field Reference for the "Column names to use carefully" section, since that page covers the same naming patterns in more detail.

### /docs/schema/raw-reference (generated)

**Empty page returned from fetcher** -- likely due to dev server being overwhelmed by the 1327-line MDX file. Source file structure is correct.

- **Structure**: 43 raw schemas, each with Class/Coerce/Strict metadata and a Column/Type/Nullable/Constraints/Description table.
- **Descriptions populated**: All columns have descriptions (confirmed by inspection). Source tracing available via the data dictionary counterpart.
- **No DocsGeneratedEntrySurface/ScanSurface in MDX**: These components are rendered by the page template (`page.tsx`), not embedded in the MDX. Configuration exists in `generatedPageFrames` and `generatedScanSurfaceMeta` for this page key. This is the correct architecture.
- **Dense table readability concern**: At 1327 lines with 43 contiguous schema tables, this page has no mid-page navigation aids in the MDX itself. The ScanSurface component (if rendering correctly) provides TOC clustering, which helps.

### /docs/schema/staging-reference (generated)

**Connection refused from fetcher** (dev server crashed). Source file reviewed.

- **Structure**: 43 staging schemas with same format as raw. FK annotations present (e.g., `FK->staging_team.team_id`).
- **Descriptions populated**: All columns have descriptions.
- **Same dense readability concern**: 1675 lines.

### /docs/schema/star-reference (generated)

**Empty page returned from fetcher.** Source file reviewed extensively.

- **Structure**: Claims 109 schemas but includes 13 private `__*_mixin` schemas that should be excluded.
- **DEFECT -- Private mixin schemas exposed**: 13 entries with `__` prefix (e.g., `__team_dashboard_fantasy_metrics_mixin`, `__team_dashboard_standard_ranks_mixin`) are implementation-detail mixins that leak into the public reference. The `_discover_schemas` method in `schema_docs.py` skips files starting with `_` but not classes starting with `__`.
- **DEFECT -- Empty descriptions on all star columns**: Every star-tier column has an empty Description cell. The autogen reads `metadata.get("description", "")` from pandera Field metadata, but many star schemas (especially `agg_schemas.py`) don't set `metadata={"description": "..."}` on their fields. Raw and staging schemas do have descriptions, so this is a star-specific gap. This renders 839+ empty description cells across the page.
- **DEFECT -- Zero analytics view schemas**: None of the 12 analytics views appear because they lack pandera schemas in `nbadb.schemas.star`.
- **Missing dimensions**: 4 dimensions (`dim_all_players`, `dim_team_extended`, `dim_defunct_team`, `dim_season_week`) missing for the same reason (no pandera schema in the star package).
- **Density**: At 2893 lines, this is the largest MDX file and likely causes rendering performance issues.

## Data Dictionary Findings

### /docs/data-dictionary (index)

**Rendered OK** (confirmed via fetcher).

- **Strengths**: Clean Mermaid lookup-order diagram with text fallback. Good "Fastest lookup by what you have in hand" table. Clear curated-vs-generated boundary with the DataColumns/InsightCard pair. Layer and prefix guide is a useful quick reference.
- **Cross-links to Schema and Lineage**: Present and appropriate (3 links to Schema, 1 to Lineage).
- **No issues found.**

### /docs/data-dictionary/raw (generated)

**Connection refused from fetcher.** Source file reviewed.

- **Structure**: 43 raw tables, each with Column/Type/Nullable/Description/Source table. Source column shows full provenance path (e.g., `BoxScoreAdvancedV3.PlayerStats.GAME_ID`).
- **Descriptions fully populated**: All columns have descriptions.
- **Source column populated**: Full `Endpoint.ResultSet.FIELD` provenance for all fields. This is the strongest generated page for source tracing.
- **Same density concern**: 1196 lines, no mid-page navigation in MDX (relies on ScanSurface component).

### /docs/data-dictionary/staging (generated)

**Connection refused from fetcher.** Source file reviewed.

- **Structure**: 43 staging tables with same format. FK annotations embedded in Description column text (e.g., "Team identifier (FK -> staging_team.team_id)").
- **Descriptions fully populated**: All columns have descriptions.
- **Source column populated**: Same full provenance paths.

### /docs/data-dictionary/star (generated)

**Empty page returned from fetcher.** Source file reviewed.

- **DEFECT -- All descriptions empty**: Every column in every star table has an empty Description cell. This is the same root cause as the star-reference: star pandera schemas generally lack `metadata={"description": "..."}`.
- **DEFECT -- All Source columns empty**: Every Source cell shows `` `` (empty backtick pair). The `DataDictionaryGenerator._extract_fields` reads `metadata.get("source", "")`, but star schemas don't populate this field. This makes the star data dictionary nearly useless -- it's just a column/type/nullable listing with no descriptions or provenance.
- **Same mixin leak**: The 13 `__*_mixin` private schemas also appear here.
- **Same analytics gap**: No analytics views in this generated page.
- **Density**: 2564 lines.

### /docs/data-dictionary/glossary

**Source reviewed.**

- **Strengths**: Comprehensive coverage of shooting efficiency, impact metrics, rebounding, pace/ratings, Four Factors, Synergy, box score basics, hustle, tracking, and win probability. Formulas are provided where meaningful. Column name cross-references to specific fact tables are helpful.
- **Well-structured**: Organized by stat family with clear "Read this family first" openers. ScoutCard grid at top provides good quick routing.
- **No issues found.** This is one of the strongest pages in both sections.

### /docs/data-dictionary/field-reference

**Source reviewed.**

- **Strengths**: Practical reading-order guidance ("grain first, then discriminator, then role/context, then measures"). The discriminator column section is particularly valuable for preventing misreads on dashboard-style surfaces. ScoutCard "Common misread traps" section is excellent.
- **Good cross-links**: Links to generated raw/staging/star pages and to schema family pages.
- **No issues found.** Another strong curated page.

## Cross-Section Observations

### 1. Asymmetric cross-linking (moderate)
- Schema section has **zero** links to Data Dictionary pages across all 9 pages.
- Data Dictionary links to Schema in 4 places (index and field-reference only).
- The glossary and field-reference are directly relevant when users are reading generated schema references, but no links guide them there.

### 2. Curated vs generated quality gap (critical)
- Raw and staging tiers have fully populated descriptions and source columns in both schema-reference and data-dictionary pages.
- Star tier has empty descriptions and empty sources in both generated page families. This is the most important tier for analysts and it has the weakest generated documentation.

### 3. Generated page rendering concern
- All 3 star-tier pages (star-reference, data-dictionary/star, and star) returned empty or connection-refused from the fetcher. This may indicate rendering performance issues with very large MDX files (2500-2900 lines). The raw and staging pages (1200-1700 lines) also had issues but the initial pages loaded fine.
- The DocsGeneratedEntrySurface and DocsGeneratedScanSurface components are correctly configured for all 6 generated pages and are rendered by the page template. They don't need to be embedded in the MDX.

### 4. Table count claims vs reality
Multiple curated pages claim table counts that exceed what the generated references can verify:

| Claim | Curated page | Generated star-reference count | Gap |
|-------|-------------|-------------------------------|-----|
| 17 dimensions | Dimensions page | 13 dim_* schemas | 4 missing schemas |
| 102 fact outputs | Facts page | 62 fact_* schemas | ~40 missing schemas |
| 2 bridges | Facts page | 5 bridge_* schemas | 3 undocumented bridges |
| 4 analytics views | Analytics Views page | 0 analytics_* schemas | 4 (really 12) missing |
| 16 agg tables | Derived page | 16 agg_* schemas | Matches |

### 5. Hierarchy clarity
The section organization is logical and well-conceived:
- Schema section: index -> curated guides (dims/facts/derived/analytics/relationships) -> generated references (raw/staging/star). The curated-then-generated flow works.
- Data Dictionary section: index -> curated decoders (glossary/field-reference) -> generated inventories (raw/staging/star). Same pattern, equally clear.
- The separator (`---`) in meta.json correctly groups curated from generated pages in the sidebar.

## Defects

### D-01: Star tier descriptions empty across both generated families [Critical]
**Affected pages**: `/docs/schema/star-reference`, `/docs/data-dictionary/star`
**Root cause**: Star pandera schemas in `nbadb.schemas.star` generally do not set `metadata={"description": "...", "source": "..."}` on their `pa.Field()` calls. The autogen reads these fields and emits empty cells.
**Impact**: 839+ empty description cells in star-reference, 890+ in data-dictionary/star. The most analyst-facing tier has the least useful generated documentation.
**Fix**: Add metadata to star schema fields, or have the autogen fall back to inferring descriptions from field names and types.

### D-02: 13 private mixin schemas leak into generated references [High]
**Affected pages**: `/docs/schema/star-reference`, `/docs/data-dictionary/star`
**Root cause**: `SchemaDocsGenerator._discover_schemas` skips files starting with `_` but does not skip classes whose resolved table name starts with `__`. The `_table_name_from_class` method converts `__TeamDashboardFantasyMetricsMixin` to `__team_dashboard_fantasy_metrics_mixin`.
**Impact**: 13 internal mixins pollute the public reference, inflating the "109 schemas" count and confusing users.
**Fix**: Filter out schemas whose class name starts with `__` or `_` in `_discover_schemas`, or filter table names starting with `__` in the MDX generation loop.

### D-03: Zero analytics views in any generated reference [High]
**Affected pages**: `/docs/schema/star-reference`, `/docs/data-dictionary/star`
**Root cause**: Analytics views are defined as SQL transforms in `nbadb.transform.views/` but have no pandera schema classes in `nbadb.schemas.star/`. The autogen only discovers schemas from that package.
**Impact**: 12 analytics views (including 4 from session 8 and 8 newer ones) have no schema-backed field inventory anywhere.
**Fix**: Either create pandera schemas for analytics views, or extend the autogen to derive schema from transform SQL or DuckDB introspection.

### D-04: 3 bridge tables undocumented in curated pages [Medium]
**Affected pages**: `/docs/schema/facts`, `/docs/schema/relationships`
**Tables**: `bridge_game_team`, `bridge_lineup_player`, `bridge_player_team_season`
**Impact**: Users see these bridges in the generated reference but have no curated guidance on when or how to use them.
**Fix**: Add these to the "Current bridge tables" section in facts.mdx and add join examples in relationships.mdx.

### D-05: 4 dimensions missing from generated star reference [Medium]
**Affected**: `dim_all_players`, `dim_team_extended`, `dim_defunct_team`, `dim_season_week`
**Root cause**: No pandera schemas in `nbadb.schemas.star` for these.
**Impact**: The curated dimensions page documents them, but the generated reference cannot verify their contracts.
**Fix**: Add star-tier pandera schemas for these 4 dimensions.

### D-06: Analytics views page documents only 4 of 12 [Medium]
**Affected page**: `/docs/schema/analytics-views`
**Impact**: 8 analytics views (draft_value, league_benchmarks, player_impact, game_summary, clutch_performance, player_matchup, shooting_efficiency, team_game_complete) exist as transforms but are not documented in any curated or generated page.
**Fix**: Update the analytics-views page to document all 12 (or at least the 8 from sessions 7-8 that were explicitly added).

### D-07: Fact count claim does not match generated reference [Low]
**Affected page**: `/docs/schema/facts`
**Detail**: Claims "102 fact outputs" but star-reference shows 62 `fact_*` schemas. The discrepancy is because many transforms create output tables without corresponding pandera schemas.
**Fix**: Either align the claim with what the generated reference can verify, or add a note explaining the gap.

## Enhancement Ideas

### E-01: Add cross-links from Schema pages to Data Dictionary
Every curated schema page that says "jump to Star Reference for exact columns" should also suggest the Glossary for metric meanings and Field Reference for naming patterns. This is a 5-minute edit per page.

### E-02: Add "auto-generated" banner to generated MDX content
The DocsGeneratedEntrySurface component renders a "Generated page" badge, but the MDX content itself has no indicator. If the component fails to render, or if users read the source, there's no in-content signal. Consider adding a brief auto-generated note at the top of each generated MDX file.

### E-03: Split star-reference into multiple files
At 2893 lines and 109 (really 96) schema blocks, the star-reference may benefit from splitting into sub-pages by family (dims, facts, bridges, aggs). This would improve rendering performance and scanability.

### E-04: Add search/filter capability to generated pages
Dense reference tables with 40+ schema blocks are hard to scan even with TOC clustering. A client-side filter or Ctrl+F-friendly heading structure would help.

### E-05: Show table relationships in generated reference
The generated schema blocks show columns and constraints but not which other tables they relate to. Adding a "Joins to:" line under each schema block would bridge the gap between the reference and relationships pages.

## Notes

- The curated pages (dimensions, facts, derived, analytics-views, relationships, glossary, field-reference) are uniformly high quality. The basketball metaphor is consistent and aids navigation. The decision tables and escalation guidance are genuinely useful.
- The generated pages have a strong architectural foundation (DocsGeneratedEntrySurface, DocsGeneratedScanSurface, companion modules) but the star tier's empty descriptions severely undermine the most important generated pages.
- The dev server appeared to struggle with the largest generated pages during this audit. The star-reference (2893 lines) and data-dictionary/star (2564 lines) consistently returned empty content from the fetcher, while smaller pages rendered correctly. This warrants investigation of rendering performance for very large MDX files.
- The meta.json sidebar organization uses `---` separators to visually group curated from generated pages, which is a good practice.
