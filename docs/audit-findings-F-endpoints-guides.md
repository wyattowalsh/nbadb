# Audit F: Endpoints + Guides

Auditor: source-level review of all 20 MDX files, nav metadata, custom component usage, and cross-reference against actual transform/schema code.

---

## Endpoints Section

### /docs/endpoints (index)

**Task orientation:** Clear. The page states what the section covers and helps users route to the right sub-page by entry key. The "Route by the first reliable key" table is an effective decision matrix.

**Strengths:**
- Three clear "coverage lanes" (Game package, Scouting reports, League desk) with visual cards and a summary table.
- Board directory table provides endpoint counts, common keys, and route cues -- easy to scan.
- Extraction notes section briefly covers rate limiting, retry, proxy, and incremental updates.

**Defects:**
1. **D-E1: Stat pill values are vague.** "Full" and "Multi-lane" are not numbers. The other endpoint sub-pages give exact counts (10, 3, 6, 7, 6, 7, 8) totaling 47 endpoints. The index should surface the actual totals.
2. **D-E2: "Skipped endpoints" says 8 but does not list them.** The section says "Eight endpoints are deliberately excluded" but provides zero detail. Should at minimum name them and state the reason category (deprecated, redundant, auth-walled).
3. **D-E3: Curated boards count says 7 but there are only 7 sub-pages.** The number is correct but the label "Curated boards" is unclear -- are these the sub-pages themselves? Worth clarifying.

### /docs/endpoints/box-scores

**Task orientation:** Strong. Opens with "Ten endpoints make up the standard game package" and quickly routes by question type.

**Strengths:**
- Clean grouping into Core box packet / Shot mix, role, and tracking layers / Matchup-specific boards.
- Quick route table maps analytical questions to specific endpoints.
- Next steps cards are relevant and link to Play-by-Play, Other, and League Stats.

**Defects:** None found beyond the general absence of "what nbadb does with this data" (see Cross-Section Observations).

### /docs/endpoints/play-by-play

**Task orientation:** Clear. Three endpoints with well-defined lanes (V3 modern, V2 legacy, WinProbability).

**Strengths:**
- The `eventmsgtype` reference table (types 1-13) is a valuable quick reference.
- Route cues clearly differentiate when to use V3 vs V2.

**Defects:**
4. **D-E4: eventmsgtype table is missing type 11 (Ejection).** The actual transform code (`fact_play_by_play.py`) maps type 11 to `ejection`, but the docs table skips from 10 to 12.

### /docs/endpoints/other

**Task orientation:** Good. Clear split between game_id routes and season routes.

**Defects:** None significant.

### /docs/endpoints/player-stats

**Task orientation:** Good. Logical split between lookup surfaces, core dossier, and dashboards/search.

**Defects:** None significant.

### /docs/endpoints/team-stats

**Task orientation:** Good. Organized by lookup/snapshot, organization/roster, and franchise history.

**Defects:** None significant.

### /docs/endpoints/draft

**Task orientation:** Good. Clean separation of board/history lane vs combine packet.

**Defects:** None significant.

### /docs/endpoints/league-stats

**Task orientation:** Good. Eight endpoints covering dashboards, standings, combinations, and historical leaders.

**Defects:**
5. **D-E5: AllTimeLeadersGrids row is sparse.** Parameters says "none listed" and result sets says "multiple leader grids" without naming them. The actual endpoint returns 18+ result sets (one per stat category). A brief note acknowledging this would help.

---

## Guides Section

### /docs/guides (index)

**Task orientation:** Strong. The "Run one first possession" table routes by today's job. The mermaid flowchart provides a visual fallback.

**Strengths:**
- Four practice lanes (Opening drill, Skill work, Game-day operations, Film room & recovery) with scout cards.
- Guide tracks section groups all 11 guides with typical next stops.
- "How to use this section well" provides clear principles.

**Defects:**
6. **D-G1: Guide count says 11 but there are 11 authored guides.** The stat pill says "Guides: 11" but the section also references SQL Playground (which is outside the guides directory). The count is debatably 11 or 12 depending on whether Playground is included. Clarify.
7. **D-G2: Guides index references non-existent lineage sub-paths.** The "Shot Chart Analysis" scout card links to `/docs/lineage/column-lineage` and "DuckDB Query Examples" links to `/docs/lineage/table-lineage`. Both files exist, so links are valid -- no defect here.
8. **D-G3: Visual Asset Prompt Pack is categorized under "Skill work" in the sidebar meta.json** but under "Film room & recovery" in the index page prose. The sidebar has it between shot-chart-analysis and parquet-usage (Skill Work), while the index page places it under "Film room and recovery." This is a classification contradiction.

### /docs/guides/analytics-quickstart

**Task orientation:** Strong. "Get from dataset download to a real answer in a few minutes" is a clear promise. The four-possession structure (install, download, connect, query) is logical.

**Strengths:**
- Three concrete "wins" to leave with.
- Multiple entry points depending on what you already have.
- Three query options (leaderboard, shot map, standings) with clear use-case labels.

**Defects (CRITICAL -- SQL examples reference non-existent table names and columns):**

9. **D-G4: `fact_box_score_player` does not exist.** Option A references `FROM fact_box_score_player b`. The actual table is `fact_player_game_traditional`. This query will fail on a real nbadb database.

10. **D-G5: `dim_game` column name mismatches in standings query.** Option C uses:
    - `s.season_id = '2024-25'` -- actual column is `season_year` (integer, not string)
    - `s.playoff_rank` -- actual column is `conference_rank`
    - `s.current_streak` -- actual column is `streak`

11. **D-G6: `dim_game` has no `season_year` filtering issue.** The `JOIN dim_game g ON b.game_id = g.game_id` pattern is used for season filtering, which works. However, the join to `dim_game g` followed by `WHERE g.season_type = 'Regular Season'` works since `dim_game` does have `season_type`. This part is correct.

### /docs/guides/duckdb-queries

**Task orientation:** Strong. Organized by question type with a clear route table.

**Defects (CRITICAL -- same table/column issues, plus additional ones):**

12. **D-G7: All "Scoring and player load" queries use `fact_box_score_player`.** This table does not exist. Should be `fact_player_game_traditional`. Affects: Top scorers, Player career averages, Triple-doubles, Most efficient scorers.

13. **D-G8: Head-to-head matchups query references non-existent dim_game columns.** The query uses `g.home_score`, `g.away_score`, and `away_t.abbreviation` joined via `g.away_team_id`. The actual dim_game column is `visitor_team_id` (not `away_team_id`), and dim_game does not carry `home_score` or `away_score` columns. This query would need `fact_game_result` or similar for scores.

14. **D-G9: Team pace leaders query references `fact_box_score_advanced_team`.** This table does exist with the correct name, but the join `JOIN dim_game g ON a.game_id = g.game_id` assumes `fact_box_score_advanced_team` has a `game_id` column, which it likely does (from `stg_box_score_advanced_team`). This query may work but should be verified.

15. **D-G10: Win probability query references multiple non-existent columns.** The `fact_win_probability` table has `pc_time_string` (not `pctimestring`), and does not have `description`, `home_team_id`, `visitor_team_id`, or `is_score_change`. The query as written would fail.

16. **D-G11: Clutch performance query references non-existent columns.** `fact_play_by_play` uses `player1_id` (not `person_id`), and has no `shot_result`, `is_field_goal`, or `points_total` columns. The actual column for event classification is `event_type_name` (with values like `made_shot`, `missed_shot`).

### /docs/guides/player-comparison

**Task orientation:** Strong. Clear comparison structure with reusable player pool.

**Defects:**

17. **D-G12: Same `fact_box_score_player` issue.** Box score baseline, Shooting and efficiency, and Closing-time read all reference `fact_box_score_player` (non-existent) and `fact_play_by_play` columns (`person_id`, `shot_result`, `is_field_goal`) that don't exist.

### /docs/guides/shot-chart-analysis

**Task orientation:** Strong. Excellent progressive build from zone query to scatter plot to heatmap to distance analysis.

**Strengths:**
- The "fact_shot_chart gives you" table is a useful column reference.
- Court coordinates refresher explains the coordinate frame.
- Sanity checks section is practical and well-targeted.

**Defects:**

18. **D-G13: `shot_type` column in zone efficiency query.** The query groups by `sc.shot_type` but the `fact_shot_chart` SELECT in the transform does not explicitly list `shot_type`. Need to verify if `shot_type` passes through from `stg_shot_chart_detail`.

19. **D-G14: Minor -- DuckDB connection path inconsistency.** This page uses `conn = duckdb.connect("nbadb/nba.duckdb")` while analytics-quickstart uses `conn = duckdb.connect(f"{path}/nba.duckdb")` with the kagglehub path. Not wrong per se, but the varying connection patterns could confuse new users.

### /docs/guides/parquet-usage

**Task orientation:** Strong. Clean structure covering Polars, DuckDB, Pandas, and PyArrow with progressive examples.

**Strengths:**
- "Habits that pay off" table is practical advice.
- Good coverage of both single-file and partitioned table patterns.

**Defects:**
20. **D-G15: Minor path inconsistency.** Uses `nbadb/parquet/` paths while other guides use different base paths. This is documented behavior, but a note saying "adjust the base path to match your data directory" would help.

### /docs/guides/kaggle-setup

**Task orientation:** Strong. Three clear routes (CLI download, kagglehub download, upload).

**Strengths:**
- "What lands on disk" section with directory layout is very helpful.
- Preflight checklist for upload is practical.
- Multiple format loading examples (SQLite, DuckDB, Parquet with Polars/Pandas).

**Defects:**
21. **D-G16: `nba.sqlite` prominence may be misleading.** The page leads with SQLite as the first delivery format, but the rest of the docs site overwhelmingly uses DuckDB. The table and examples should lead with DuckDB as the primary format.

### /docs/guides/daily-updates

**Task orientation:** Strong. Clear three-command decision (daily/monthly/full) with escalation logic.

**Strengths:**
- "What nbadb daily actually does" section is excellent -- 6-step breakdown.
- Operator cues table (TUI signals, Ctrl+C behavior) is practical.
- Scheduling example with cron is useful.

**Defects:** None significant.

### /docs/guides/role-based-onboarding-hub

**Task orientation:** Strong. Four clear personas (Contributor, Analyst, Operator, Stakeholder) with tabs.

**Strengths:**
- Each tab follows Run first / Open next / Watch for structure -- consistent and scannable.
- The "Browser warm-up" scout card adds a fifth, friction-minimizing route.

**Defects:**
22. **D-G17: "Analyst without local setup" row references SQL Playground, but the tab structure does not separate browser-analyst from local-analyst.** The route board at the top has two analyst rows (with/without local setup), but the tabs only have one "Analyst" tab that blends both paths. The tab could be split or the in-tab instructions could more clearly delineate the two sub-routes.

23. **D-G18: `nbadb download` command in Analyst tab may not exist.** The Analyst tab says "Run first: `nbadb download`" but the Kaggle Setup guide says the command is `nbadb download`. Need to verify this command exists in the CLI.

### /docs/guides/troubleshooting-playbook

**Task orientation:** Strong. Five clear failure categories with generate/diagnose/remediate structure.

**Strengths:**
- The narrowest-recovery-loop principle is excellent operational advice.
- Each artifact section follows the same 3-step pattern (generate, diagnose, remediate).
- Known issue callout for `run-quality` is a good transparency practice.

**Defects:**
24. **D-G19: Extract completeness command may not exist.** The guide references `nbadb extract-completeness` and `--require-full` / `--require-model-contract` flags. Should verify these exist in the CLI.

### /docs/guides/strategic-shift-rollout

**Task orientation:** Clear but niche. This is a future-looking planning document, not a hands-on guide.

**Defects:**
25. **D-G20: This page is not a guide in the traditional sense.** It is a phased migration roadmap with placeholder feature flags. It sits in the "Film Room & Recovery" lane but contains no actionable recovery steps. It could be better placed under Architecture or as a standalone planning document.

### /docs/guides/visual-asset-prompt-pack

**Task orientation:** Clear for its purpose (generating on-brand visual assets).

**Strengths:**
- Thorough brand pillars and universal constraints.
- Section-specific prompt variants are well-differentiated.
- Review checklist is practical.

**Defects:**
26. **D-G21: Also not a traditional guide.** This is an art-direction reference, not a data workflow. Its placement under "Skill Work" in the sidebar and "Film room & recovery" in the index prose (see D-G3) suggests uncertainty about where it belongs. It is useful content but feels out of place among analytical guides.

---

## Cross-Section Observations

### 1. Critical: SQL examples use non-existent table names and columns

This is the single most important finding. At least 6 guides contain SQL code that will fail when run against an actual nbadb DuckDB database:

| Phantom table/column | Actual name | Affected guides |
| -------------------- | ----------- | --------------- |
| `fact_box_score_player` | `fact_player_game_traditional` | analytics-quickstart, duckdb-queries, player-comparison |
| `dim_game.away_team_id` | `dim_game.visitor_team_id` | duckdb-queries |
| `dim_game.home_score` / `away_score` | (not in dim_game) | duckdb-queries |
| `fact_standings.season_id` | `fact_standings.season_year` | analytics-quickstart, duckdb-queries |
| `fact_standings.playoff_rank` | `fact_standings.conference_rank` | analytics-quickstart, duckdb-queries |
| `fact_standings.current_streak` | `fact_standings.streak` | analytics-quickstart, duckdb-queries |
| `fact_win_probability.pctimestring` | `fact_win_probability.pc_time_string` | duckdb-queries |
| `fact_win_probability.description` | (does not exist) | duckdb-queries |
| `fact_win_probability.home_team_id` | (does not exist) | duckdb-queries |
| `fact_win_probability.is_score_change` | (does not exist) | duckdb-queries |
| `fact_play_by_play.person_id` | `fact_play_by_play.player1_id` | duckdb-queries, player-comparison |
| `fact_play_by_play.shot_result` | (does not exist; use `event_type_name`) | duckdb-queries, player-comparison |
| `fact_play_by_play.is_field_goal` | (does not exist) | duckdb-queries, player-comparison |
| `fact_play_by_play.points_total` | (does not exist) | duckdb-queries |

**Impact:** A new user following the analytics quickstart will hit errors on their first query attempt. This directly undermines the "first answer in minutes" promise.

### 2. Basketball metaphor is consistent but occasionally heavy

The basketball metaphor (possessions, drills, film room, practice facility, scouting reports) is well-executed and gives the docs a distinctive voice. However, in a few places the metaphor replaces specificity:
- "Opening possession" / "first possession" / "pick a lane" appear so frequently that navigational meaning blurs.
- The stat pills on index pages sometimes sacrifice precision for metaphor (e.g., "Full" and "Multi-lane" instead of numbers).

### 3. Internal cross-linking is strong

Almost every page ends with a "Related routes" or "Next steps" section. The guides reference each other, the endpoints, and the schema/lineage layers consistently. No broken internal links were found among the audited pages.

### 4. Endpoints section is reference-only -- no "what nbadb does with it"

The endpoint pages list the nba_api surface (parameters, result sets, key columns) but never explain what nbadb transforms do with the data. A one-line note per endpoint like "Lands in: `fact_player_game_traditional`" or "Transforms into: `dim_player`, `fact_player_available_seasons`" would connect the extraction layer to the schema layer that users actually query.

### 5. Onboarding flow is well-sequenced

The guides genuinely build on each other:
- Role-Based Onboarding Hub routes to the right starting guide
- Analytics Quickstart provides the first working query
- DuckDB Queries and Player Comparison extend with more patterns
- Shot Chart Analysis deepens into visualization
- Daily Updates and Troubleshooting handle operations

The one gap is that there is no guide bridging from "I ran my first query" to "I want to understand the schema." The guides link to Schema Reference but do not walk through how to read it.

### 6. Repetition between analytics-quickstart and duckdb-queries

The standings query in analytics-quickstart (Option C) is nearly identical to the "Team records and standings" query in duckdb-queries. The shot chart query (Option B) covers similar ground to the shot-chart-analysis Pass 1. This is mild and arguably intentional (quickstart as a sampler), but worth noting.

---

## Defects

### Critical (will cause user-facing failures)

| ID | Location | Description |
| -- | -------- | ----------- |
| D-G4 | analytics-quickstart Option A | `fact_box_score_player` does not exist; should be `fact_player_game_traditional` |
| D-G5 | analytics-quickstart Option C | `season_id`, `playoff_rank`, `current_streak` are wrong column names for `fact_standings` |
| D-G7 | duckdb-queries (4 queries) | All scoring/player-load queries use non-existent `fact_box_score_player` |
| D-G8 | duckdb-queries head-to-head | `dim_game` has no `home_score`/`away_score`/`away_team_id` |
| D-G10 | duckdb-queries win probability | 5 non-existent columns in `fact_win_probability` query |
| D-G11 | duckdb-queries clutch perf | 4 non-existent columns in `fact_play_by_play` query |
| D-G12 | player-comparison (3 queries) | Same `fact_box_score_player` and `fact_play_by_play` column issues |

### Moderate

| ID | Location | Description |
| -- | -------- | ----------- |
| D-E2 | endpoints index | "8 skipped endpoints" claimed but none listed |
| D-E4 | play-by-play | eventmsgtype table missing type 11 (Ejection) |
| D-G3 | guides index vs meta.json | Visual Asset Prompt Pack classified differently in sidebar vs prose |
| D-G13 | shot-chart-analysis | `shot_type` column usage needs verification against actual table |

### Minor

| ID | Location | Description |
| -- | -------- | ----------- |
| D-E1 | endpoints index | Stat pill values "Full" and "Multi-lane" are not specific |
| D-E5 | league-stats | AllTimeLeadersGrids row is underspecified |
| D-G1 | guides index | Guide count ambiguity (11 vs 12 including Playground) |
| D-G14 | shot-chart-analysis | DuckDB connection path varies across guides |
| D-G15 | parquet-usage | Base path varies without guidance note |
| D-G16 | kaggle-setup | SQLite prominence over DuckDB as lead format |
| D-G17 | role-based-onboarding-hub | Analyst tab does not split browser-only vs local sub-routes |
| D-G20 | strategic-shift-rollout | Not a guide -- better placed under Architecture |
| D-G21 | visual-asset-prompt-pack | Not a data workflow guide -- placement uncertain |

---

## Enhancement Ideas

1. **Fix all SQL examples against actual schema.** This is the highest-priority fix. Every query in analytics-quickstart, duckdb-queries, player-comparison, and shot-chart-analysis should be tested against a real nbadb DuckDB file. Replace phantom table/column names with actual ones.

2. **Add "Lands in" annotations to endpoint pages.** Each endpoint row could include a brief note: "Transforms into: `fact_player_game_traditional`" connecting extraction docs to the queryable tables.

3. **List the 8 skipped endpoints.** Even a compact table (endpoint name, reason for exclusion) would close the gap.

4. **Add a "Reading the Schema" bridge guide.** Between the first-query guides and the reference pages, a short guide showing how to navigate dim/fact/analytics layers would help.

5. **Standardize DuckDB connection patterns.** Pick one canonical pattern (e.g., `conn = duckdb.connect("path/to/nba.duckdb")`) and use it consistently, with a note about adjusting the path.

6. **Move strategic-shift-rollout and visual-asset-prompt-pack** to more appropriate locations (Architecture and a top-level creative/brand section respectively), or at minimum reconcile their classification between meta.json and the guides index.

7. **Add type 11 (Ejection) to the play-by-play eventmsgtype table.**

---

## Notes

- Chrome was not running during this audit, so all findings are source-level. Rendered page appearance, component rendering, and interactive behavior were not verified.
- The basketball metaphor is a distinctive strength of these docs. The voice is consistent and the routing logic is genuinely helpful. The critical defects are all in SQL accuracy, not in information architecture.
- The endpoint pages are well-structured as reference material. The guides are well-sequenced as a learning path. The connection between the two sections (endpoints describe sources, guides use the outputs) could be made more explicit.
