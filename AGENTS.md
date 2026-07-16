# nbadb — Agent Instructions

## Project Overview

nbadb is a comprehensive NBA database built around the current `nba_api` runtime surface
with 152 registered extractors, 416 staging entries, 254 transform outputs,
and 254 schema-backed public tables.
It follows an ELT pipeline: extract from NBA API → stage in DuckDB → transform into the
analytics/star schema → export to SQLite/DuckDB/Parquet/CSV.

## Tech Stack

- Python ≥3.12, uv (package manager), hatchling (build)
- nba_api 1.11.4 (exact runtime/docs/tools contract pin)
- Polars 1.42.1 (primary DataFrame engine)
- DuckDB 1.5.4 (staging engine, zero-copy Arrow interchange)
- Pandera[polars] 0.32.1 (3-tier schema validation: raw → staging → star)
- SQLModel 0.0.39
- ty 0.0.58 (type checker), ruff (lint/format)
- Docs: Fumadocs 16 + Next.js 16 + pnpm + Tailwind v4

## Module Map

```text
src/nbadb/
├── extract/          # 152 registered extractors wrapping nba_api endpoints
│   ├── stats/        # Statistical endpoint extractors
│   ├── static/       # Static data extractors (players, teams, arenas, awards)
│   └── live/         # Live game data extractors
├── schemas/          # Pandera schema definitions
│   ├── raw/          # Raw extraction schemas
│   ├── staging/      # Staging schemas + STAGING_MAP-backed staging keys
│   └── star/         # Output table schemas for final analytics model
├── transform/        # 254 transform outputs (246 historical + 8 live snapshot outputs)
│   ├── dimensions/   # 18 dimension builders (dim_*)
│   ├── facts/        # 197 fact_* outputs + 6 bridge_* outputs
│   ├── derived/      # 19 aggregate builders (agg_* outputs live here)
│   └── views/        # 14 analytics_* builders
├── load/             # SQLite/DuckDB/Parquet/CSV loaders
├── orchestrate/      # Pipeline orchestration + staging map
├── cli/              # Typer CLI + Textual TUI surface
├── core/             # Config, database, logging, coverage helpers
├── agent/            # Natural-language query agent
├── kaggle/           # Kaggle download/upload integration
└── docs_gen/         # Auto-generates schema/data-dictionary/ER/lineage artifacts
```

Additional repo-owned surfaces:

```text
chat/                # Canonical Chainlit app surface; `nbadb chat` uses it when launcher files are present
src/nbadb/chat/      # Shared chat launcher, notebook, runtime, tracing, SQL, catalog, and memory helpers
kb/                  # Companion Obsidian-native knowledge base for maintainers and agents
```

## Key Conventions

### Coverage Trust Floor

- Preserve and improve full historical `nba_api` coverage for every year available per endpoint.
- If an endpoint/year/season-type combination is unavailable upstream or blocked by a known contract gap, classify it explicitly in audits/support matrices instead of silently dropping it.

### Naming

- `dim_*` — Dimension tables (18)
- `fact_*` — Fact tables (197)
- `bridge_*` — Bridge tables (6)
- `agg_*` — Pre-aggregated rollups (19 current outputs; code lives under `transform/derived/`)
- `analytics_*` — Analytics convenience tables/views (14)
- `stg_*` — DuckDB staging tables generated from `STAGING_MAP`
- `raw_*` — Raw extraction data

### SqlTransformer Base Class

Most transformers (100+) extend `SqlTransformer(BaseTransformer)` — define `_SQL` as a ClassVar, no `transform()` override needed. The base class handles execution.

### Schema Validation

3-tier Pandera validation:

- **Raw**: Validates extracted DataFrames before staging
- **Staging**: Validates after DuckDB load
- **Star**: Validates final output tables
- `BaseSchema.Config.strict=False` — hard-fail on missing/type errors, soft-warn+strip extras

### Full Extraction Control Plane

- Fresh runs default to the `standard` chunk profile. Within each matrix wave, the scheduler targets a `5:3:1:1` rotation across fresh, partial-progress, retry, and infrastructure lanes when every queue has work, then applies priority and a ceiling-rounded 25% endpoint-family cap when alternatives are available. When another endpoint identity is available, no six-lane scheduling window may remain endpoint-homogeneous. This is endpoint-pressure diversity across six runner slots, not evidence that the runners have unique VPN exit IPs.
- Full-extraction manifests contain only executable parameter contracts. `player_vs_player`, `team_vs_player`, canonical `team_and_players_vs`, and its extractor-only `team_and_players_vs_players` alias remain schema-backed but are explicitly `contract_not_modeled_yet` for historical fan-out because player-team affiliations cannot prove comparison pairs or opposing lineups. Do not synthesize Cartesian matchup requests; restored manifests containing excluded endpoints must fail during planning before VPN allocation.
- `league_game_log` is discovery-seed-owned and must not receive a separate extraction lane. Coverage rows that canonicalize alternate wrappers must be projected through their staging keys to every concrete runtime endpoint/pattern pair before scheduling. This preserves distinct alias staging surfaces such as `player_game_logs`/`player_game_logs_v2` and `player_game_streak_finder`/`player_streak_finder` without zero-work canonical lanes.
- Every VPN tunnel must pass route and changed-exit-IP checks, a bounded GitHub control-plane reachability probe, a strict `TeamYears` JSON probe, and installed-stack `common_all_players` plus `league_game_log` canaries. The player canary requires positive player/team membership, matching workload discovery. A server that severs GitHub reachability is disconnected and replaced before the Actions runner can be stranded behind the tunnel. NBA-rejected servers are recorded, excluded across fallback technologies, disconnected, and replaced before discovery or extraction begins. Authentication rejections are capacity/account evidence rather than server-health evidence, so they use bounded server/protocol cooldown rotation without poisoning the chain quarantine. `vpn_network_error`, `vpn_auth_failure`, and `vpn_connect_timeout` are bounded `vpn_egress` failures, never one-shot application failures. Preflight attests the credential source used by downstream jobs and fails closed on missing/unknown attestations. Serial discovery tries the preflight-proven host first. The servers proven by preflight and discovery are then passed to extract lanes as a verified pool. Logical lane `N` may use only preferred host `N`; assignment never wraps modulo, and later lanes use disjoint fresh recommendations rather than sharing a verified host. These preferences do not attest distinct exit IPs across runners. Token-derived extraction is serialized to one lane; configured-credential runs use `vpn_parallelism`. VPN/auto full-extraction workflows share one non-cancelling repository concurrency group, while direct chains remain independently scoped. Preflight server failures are added to the effective chain quarantine before matrix fan-out and persisted into child manifests.
- The centralized `discovery_seed` job derives exact current-matrix season/season-type scopes for game/date and player-team-season discovery, restores a prior canonical bundle or the latest run-scoped recovery bundle from `lane_manifest_run_id`, and publishes the cumulative discovery artifact for extract lanes. Restored legacy v1 data is promoted only for validated exact single-season player/game scopes; aggregate v1 bundles are never promoted. Active-season player, game, team, and workload evidence is refreshed while stable historical scopes remain reusable. Sparse missing player-team pairs are grouped without widening them into a Cartesian product. Typed zero-row game/workload coverage is valid; empty player-ID coverage, absent artifacts, and partial required scopes are not.
- Discovery seeding is fail-closed and bounded: every request has a hard timeout, and both transport-transient failures and response-contract/validation failures, including wrapped causes, consume the bounded retry budget. Broad homogeneous transport/response outages use a three-attempt bounded canary, a 90-minute in-process deadline checkpoints partial state, and a 95-minute process watchdog leaves upload headroom before the 120-minute job cap. Discovery and player/team workload Parquet use immutable content-addressed generations; atomic manifest pointers bind exact scope/pairs, schema, row counts, sentinel semantics, and SHA-256. Valid fixed-name workload v3 pairs are promoted explicitly; invalid/partial legacy state is rejected. The command checkpoints an atomic schema-v2 summary bound to the exact lane-manifest digest. A standalone verifier independently derives required units from that manifest and reloads every scope/generation before canonical upload and after each extract lane installs the bundle. Only a verified complete seed receives the canonical name; incomplete state uses a run/attempt-scoped recovery name and must pass the full seed plus verifier gates before later canonical publication. Failed, cancelled, or timed-out discovery cannot run `lane_control`, consume lane retry budgets, create checkpoints, or dispatch a child iteration.
- Checkpoint roll-forward is copy-plus-delta. A new generation must use a different output path, copies the prior checkpoint before merging newly completed lane databases, and leaves the prior artifact unchanged; a zero-delta generation is still a distinct physical copy. Prior/current lane artifacts and prior checkpoints are accepted only when exact chain, source, run, artifact, generation, and coverage provenance match. Reject a prior checkpoint inventory containing any lane outside the current manifest. Prior generations are also accepted only when the report's database SHA-256 and per-lane coverage hashes match. Player-team-season lanes additionally require an `included_lane_workload_contracts` entry whose generation-independent exact-scope identity matches the active cumulative workload; append-only growth outside the lane is valid, but pair/count/base-identity drift inside it fails closed. A lane state is resumable only after DuckDB `CHECKPOINT`, WAL removal, regular-file and journal validation, exact source/chain/lane/coverage/database attestation, state-attestation schema v3 binding to that exact scope when applicable, and a successful artifact upload whose positive ID and SHA-256 receipt are finalized into metadata. Canonical metadata schema v3 uploads even for unattested restore/VPN failures; only an explicit `state_artifact.attested=true`, `state_artifact.uploaded=true` pointer with valid receipt fields may survive into a retry. Active partial pointers use `extraction-lane-recovery-<chain>-<lane>-run-<run>-attempt-<attempt>` with matching positive run/attempt identities; canonical complete-lane names are not partial-resume pointers. Both the lane-state snapshot and canonical metadata uploads get one exact-name overwrite retry before diagnostics, avoiding re-extraction when either first upload attempt fails. Attested partial lanes that add calls or rows retry in place, including transport-class `needs_resume` outcomes; timeout-class lanes split only after the latest attempt adds no durable progress. Split descendants clear parent state pointers and progress baselines, manifest/checkpoint entry points reject duplicate lane IDs, and unexpected workload identities fail restore and checkpoint validation. A rejected or unuploaded new snapshot is diagnostics-only and never replaces an older canonical recovery pointer or its counters. Without prior durable state, the pointer and progress baselines remain clear; in either case, unreceipted reported counter growth increments the cumulative no-progress streak. Failed checkpoint builds may upload only attempt-scoped diagnostics; upload the canonical checkpoint artifact only after validation succeeds. Reported `contract_blocked` evidence must exactly match recomputed support rules, and its canonical rows/digest must match the independent current/previous manifest chain-state commitment. Cancellation/source resume stores newly classified rows in a digest-bound pending commitment that the next checkpoint merges and clears. It lives in a separate artifact-bound blocked-evidence inventory rather than the effective checkpoint coverage used by terminal assured identity. Staging overlap removal preserves the maximum legitimate duplicate multiplicity with `EXCEPT ALL`.
- `video_details` and `video_details_asset` classify 1946-47 through 2003-04 as `contract_blocked` and schedule all 78 context measures from 2004-05 onward. Run 29195221754 discovery artifact 8260784820 covered all 290 season/type scopes in the blocked range and found 89,722 LeagueGameLog rows representing 44,861 games with `VIDEO_AVAILABLE=0`; its first three `video_details_asset` lanes also completed 8,902 zero-row calls. Both endpoints still recursively parse every returned result set, retain endpoint/result-set/request provenance, and group at most three measures per lane. Pre-2019 PlayIn, pre-1950-51 All Star, and cancelled 1998-99 All Star remain `upstream_unavailable`. Reject non-2xx responses before JSON parsing; classify HTTP 429/5xx and equivalent JSON error envelopes as transient, and reject malformed success payloads as extraction-contract failures. `video_details_asset` also uses ten-call chunks, two-call concurrency, a 15-second request timeout, zero in-call retries, abort after a fully failed newly attempted chunk, and a 600-second no-completed-chunk watchdog. Successful empty chunks must be persisted before journal success.
- Self-chaining preserves literal `max_iterations=auto` while enforcing one fixed numeric `iteration_budget` derived from remaining matrix-wide dispatch credits, retry depth, and possible split descendants. Child runs never extend it. Cumulative zero-progress retries remain bounded even when the observed failure class alternates; class-specific streaks do not reset the global no-progress budget. VPN/auto workflow concurrency is a repository-wide FIFO queue; direct workflow concurrency is scoped by chain and iteration. The pinned source SHA must be an ancestor of its trusted branch, and publish runs additionally require default-branch ancestry. `dispatch_next` blocks active or successful exact-title children, permits recovery after failed/cancelled history, and requires the exact-title child set to remain stable at exactly one newly created `Full Extraction chain=<chain_id> iteration=<next>` run before acknowledgement.
- Terminal assurance is a read-only job. `publish=false` runs merge, transform, live snapshot, export, and then `scan --fail-on error --full-publication` with the checkpoint report, manifest, database directory, chain ID, and expected source SHA, without write permission or Kaggle secrets. Full scan mode invokes the canonical checkpoint verifier, independently recomputes checkpoint staging/journal row counts, requires the lane/run/coverage inventory to account for every manifest lane as either durably complete or canonically contract-blocked with no missing, skipped, attestation, or workload errors, requires every declared silver/gold game, roster, team, box-score, play-by-play, shot, standings, draft, aggregate, and analytics anchor to be populated, and enforces declared row-preserving silver-to-gold cardinality pairs. The assured identity is built only after that scan and uses validated effective checkpoint coverage; valid contract-blocked lanes remain in their separate artifact-bound evidence inventory. `publish=true` consumes the exact run/attempt-scoped assured artifact in a separate writer job; publisher jobs share a FIFO `queue: max` concurrency group. The publisher resolves the exact GitHub artifact ID, normalizes the action's raw digest into the canonical `sha256:<hex>` receipt, verifies the downloaded archive, and then verifies the assured data manifest before Kaggle staging. A zero-active resume replays the exact manifest/report/database trio stored in an attested terminal checkpoint, never a reconstructed manifest with a stale pointer. If cancellation occurred after complete lane uploads but before checkpoint promotion, checkpoint recovery enumerates the manifest's exact `chain_state.artifact_run_ids` plus the current run, downloads only exact lane/database and metadata names, rejects ambiguity or mismatched pairs, and rebuilds the cumulative checkpoint. Full-extraction artifacts use overwrite semantics so job reruns can replace the same logical artifact names. `targeted_smoke=true` is a one-lane VPN-only exception: it requires a manual manifest, `publish=false`, `max_iterations=1`, and `retry_pipeline_failures=false`; skips merge and redispatch; and passes only when lane control plus checkpoint attestation prove one complete terminal lane. Never present it as full-dataset assurance.

### Kaggle Publication Verification

- `nbadb upload --verify-remote` requires an exact positive dataset version returned by the publication-marker resolver; cache directory names are not version evidence. It paginates the exact version's complete API file inventory and streams every listed resource through SHA-256 readback one file at a time. `nbadb upload --full-publication` implies that exact readback and additionally requires a valid `assured-artifact-manifest.json` plus a declared, schema-valid `terminal-assurance-report.json` with matching chain, source, complete lane/run/coverage inventory, checkpoint identity, and blocked-evidence digest. Its 1,344-resource contract fixes each path as a file or partition directory and requires table inventory, ordered schema, and row-count parity across DuckDB, SQLite, CSV, and Parquet. Upload without remote verification is reported as submitted/unverified rather than complete.
- Only a marker-specific Kaggle HTTP 404 enters bootstrap handling. Every downloaded marker and persisted publication record is validated before a decision. For every marker-present baseline, the client requires its exact version to equal the current dataset metadata version and rechecks both marker and version immediately before upload. The marker-missing bootstrap path receives the same just-in-time stabilization. The client permits at most one unresolved upload for the dataset.
- Baseline timeouts, authentication failures, non-404 HTTP errors, invalid versions, and unreadable reconciliation evidence fail closed before upload and are recorded as `baseline_reconciliation_failed`.
- If any upload remains unresolved, a later run blocks every new bundle until exact marker evidence resolves the prior publication. A matching prior marker is reconciled first; a missing or nonmatching marker fails closed. Inspect `logs/kaggle/kaggle-upload-manifest.json` before retrying.
- The client serializes same-process uploads and uses `fcntl` or `msvcrt` for same-host advisory locking; cross-host safety comes from exact marker/version reconciliation. Full, daily, and monthly publishing workflows are default-branch-only, FIFO-serialized, restore and save `logs/kaggle/kaggle-publication-state.json` through the same dataset-wide Actions cache, and include it in publication artifacts, so ambiguous upload evidence survives ephemeral runners, different extraction chains, and failed-job reruns.
- A terminal full extraction writes `assured-artifact-manifest.json` after export and full-publication scan. Its sorted SHA-256 inventory binds the exact data files to the source commit, chain ID, and validated effective checkpoint coverage; blocked-lane evidence remains separately artifact-bound. The publisher must recompute the assured identity after downloading the exact artifact ID and verifying the archive SHA-256. Kaggle metadata includes this manifest as a resource, is generated from all 254 runtime transform outputs, and publication marker schema v2 repeats its provenance. Publication uses hardlinks when safe, enforces disk/headroom and a hard remote deadline, and never retries local permanent errors such as `ENOSPC`. Immediately before upload, require the default branch to equal the pinned source; a failed-job rerun may also accept its single exact, byte-identical metadata-only publication child. Refresh and push checked-in metadata as the final idempotent step only after exact remote inventory/digest verification and receipt artifacts succeed.

### Test Patterns

- 4406 tests collected across 205 test files
- `conftest.py` autouse fixture calls `get_settings.cache_clear()` (settings use `@lru_cache`)
- Use `--import-mode=importlib` — the `nbadb/` root dir shadows `src/nbadb/`

## Commands

```bash
# Setup
uv sync                          # Install dependencies
uv sync --extra dev              # Install with dev extras

# Quality
uv run ruff check src/ tests/    # Lint
uv run ruff format src/ tests/   # Format
uv run ty check src/             # Type check
uv run pytest --import-mode=importlib tests/unit  # Unit tests
uv run pytest --import-mode=importlib tests/      # All tests

# Pipeline
uv run nbadb init --season-start 1946             # Full rebuild (resume-safe)
uv run nbadb daily                                # Incremental update
uv run nbadb monthly                              # Recent-season refresh
uv run nbadb backfill run                          # Targeted gap backfill
uv run nbadb full                                 # Fill gaps (deprecated — use backfill)
uv run nbadb status --output-format json          # Machine-readable pipeline status
uv run nbadb scan --fail-on error --report-path artifacts/health/local/scan-report.json  # Hard assurance gate
uv run nbadb export --data-dir data/nbadb       # Export sqlite/duckdb/csv/parquet by default
uv run nbadb extract-completeness --require-full  # CI coverage gate
uv run nbadb extract-completeness --require-full --endpoint-analysis-docs-root /path/to/nba_api  # Full upstream docs/tools + runtime live contract gate
uv run nbadb migrate                              # Create/migrate pipeline tables
uv run nbadb schema                               # Star schema info + lineage
uv run nbadb ask "Who scored the most in 1996?"   # Natural-language query
uv run nbadb chat                                 # AI chat UI when chat/chainlit_app.py and chat/pyproject.toml are present
uv run nbadb audit-models                          # nba_api endpoint coverage audit
uv run nbadb lint-sql                              # SQLFluff lint on transformer SQL
uv run nbadb metadata --data-dir data/nbadb --output dataset-metadata.json  # Generate Kaggle metadata JSON
uv run nbadb journal-summary                       # Pipeline telemetry for docs admin
uv run nbadb download                             # Pull latest Kaggle dataset
uv run nbadb upload --data-dir data/nbadb -m "Automated update" --verify-remote  # Validate, push, and read back any Kaggle update
uv run nbadb upload --data-dir data/nbadb -m "Full extraction" --full-publication  # Require terminal extraction provenance and exact readback

# Docs
uv run nbadb docs-autogen --docs-root docs/content/docs   # Regenerate docs artifacts
uv run python -m nbadb.docs_gen --docs-root docs/content/docs
cd docs && pnpm dev              # Dev server
cd docs && pnpm lint             # Docs lint
cd docs && pnpm format:check     # Docs formatting check
```

## Docs Workflow

- Hand-edit authored docs pages such as `cli-reference.mdx`, guides, and architecture pages.
- Do **not** hand-edit generated docs artifacts; regenerate them instead:
  - `docs/content/docs/schema/{raw,staging,star}-reference.mdx`
  - `docs/content/docs/data-dictionary/{raw,staging,star}.mdx`
  - `docs/content/docs/diagrams/er-auto.mdx`
  - `docs/content/docs/lineage/lineage-auto.mdx`
  - `docs/lib/generated/{raw,staging,star}-reference.json`
  - `docs/lib/generated/{raw,staging,star}-dictionary.json`
  - `docs/lib/generated/{schema,lineage,schema-coverage,agent-catalog}.json`
  - `docs/lib/site-metrics.generated.ts`
  - `docs/table-profile.generated.json` when `data/nba.duckdb` exists
- `nbadb docs-autogen` prints `updated:` / `unchanged:` lines for each generated artifact.
- The docs site lives in `docs/` and uses Fumadocs 16 + Next.js 16 via pnpm.

## Chat + KB Workflow

- Treat `chat/` as the canonical app surface; `apps/chat/` is retired and should not be reintroduced. The CLI and notebook launchers should fail closed if `chat/chainlit_app.py` or `chat/pyproject.toml` are absent.
- Keep reusable chat logic in `src/nbadb/chat/`; path-based launchers, notebooks, and workflows should resolve through `chat/` plus these shared helpers.
- Treat `kb/` as intentional repo content, not scratch output.
- The KB is companion material: additive-first, Obsidian-native, and subordinate to repo canon such as `README.md`, `AGENTS.md`, `docs/`, and `src/nbadb/`.
- Keep project-safe shared vault surfaces tracked under `kb/.obsidian/templates/` and `kb/.obsidian/snippets/`, but do not commit volatile editor-local workspace state if it appears later.

## Internal Pipeline Tables (10)

These DuckDB tables track pipeline state — do not modify directly:

- `_pipeline_watermarks` — Load high-water marks (`last_load` on output tables after transform+load)
- `_extraction_journal` — Extraction run history
- `_pipeline_metadata` — Per-table row counts, schema hashes, and last-updated timestamps
- `_pipeline_metrics` — Per-extraction-endpoint timing and row counts
- `_transform_checkpoints` — Resume support for interrupted transforms
- `_transform_metrics` — Transform execution metrics
- `_schema_versions` — Column hash snapshots for drift detection
- `_schema_version_history` — Schema change history
- `_lane_metrics` — Full-extraction lane timing and success/failure totals
- `_staging_chunk_journal` — Durable staging-batch chunk hashes for resume-safe extraction persistence

## Gotchas

- **Import shadowing**: `nbadb/` directory at repo root shadows `src/nbadb/` — always use `--import-mode=importlib` for pytest
- **Settings caching**: `get_settings()` uses `@lru_cache` — tests must call `cache_clear()` via autouse fixture
- **Chat surface split**: `chat/` holds the app package and assets, while `src/nbadb/chat/` holds shared runtime helpers used by the CLI, notebooks, and focused validation jobs
- **Pipeline UI**: `init`, `daily`, `monthly`, and `full` use the Textual TUI when stdout is a TTY and `--verbose` is not set; CI/non-interactive runs get plain output
- **Graceful stop**: first `Ctrl+C` during pipeline commands cancels cleanly and preserves journal/checkpoint state; second `Ctrl+C` forces exit
- **ReadOnlyGuard**: Strips SQL comments, normalizes Unicode (NFKC), always wraps queries in LIMIT, uses word-boundary keyword matching
- **Season params**: `season_type` param format varies by endpoint; `DraftBoard` uses `season_year` (int), `PlayoffPicture` uses `season_id` (str "2YYYY")
- **Coverage messaging**: public trust-floor language should promise full-history preservation only where `nba_api` exposes it, and should require explicit classification of upstream-unavailable or contract-blocked combinations
- **SCD2 dimensions**: `dim_player` and `dim_team_history` use SCD Type 2 (surrogate keys, valid_from/valid_to/is_current); all other dimensions use Type 1
- **Transform naming**: `fact_box_score_*` is team-level, `fact_player_game_*` is player-level — intentional
- **fact_rotation**: Depends on `[stg_rotation_away, stg_rotation_home]` (UNION of both)
- **Quality checks**: `--quality-check` on pipeline commands is informational; empty-table warnings do not fail the command
- **scan assurance gate**: use `nbadb scan --fail-on error` for hard assurance; `run-quality` is deprecated and no longer the gate
- **`full` deprecated**: use `backfill` for targeted gap-filling instead
- **CI**: All GitHub Actions are SHA-pinned, all workflows have permissions blocks, timeout-minutes, and concurrency groups
