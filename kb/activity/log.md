# Activity Log

## Operating rules
- Append-only.
- Record one entry per mutating batch.
- Name the `raw`, `wiki`, `indexes`, `schema`, and `config` surfaces touched in each batch.
- Call out `canonical material`, `provenance`, and `derived output` decisions explicitly.
- Record vault-impact details whenever frontmatter, aliases, embeds, or shared `.obsidian/` surfaces change.

## Entry template

### [YYYY-MM-DD HH:MM] [Batch label]
- Mode: [create|ingest|enrich|derive|improve|migration]
- Summary: [one sentence]
- `raw`: [files added or updated]
- `wiki`: [files added or updated]
- `indexes`: [files added or updated]
- `schema`: [files added or updated / unchanged]
- `config`: [files added or updated / unchanged]
- `canonical material`: [unchanged / annotated / approved exception]
- `provenance`: [what is now linked or what remains missing]
- `derived output`: [none / path / regeneration note]
- `vault`: [frontmatter, aliases, embeds, or shared `.obsidian/` surfaces changed / unchanged]
- `path map`: [old -> new note names or paths if migration work occurred / none]
- `link/backlink impact`: [what navigation changed and what stayed stable]
- Risks / rollback: [if relevant]
- Follow-up:
  - [ ]

## Initial entry example

### [2026-04-14 00:00] Bootstrap
- Mode: create
- Summary: Initialized the layered KB structure.
- `raw`: seeded directories only
- `wiki`: added `wiki/index.md`
- `indexes`: added `indexes/source-map.md` and `indexes/coverage.md`
- `schema`: unchanged
- `config`: added `config/obsidian-vault.md`
- `canonical material`: none yet
- `provenance`: placeholder sections only
- `derived output`: none
- `vault`: initialized `.obsidian/` shared surfaces and note metadata defaults
- `path map`: none
- `link/backlink impact`: root indexes now provide the first stable navigation surface
- Risks / rollback: remove only the new scaffold if the KB root was created in error
- Follow-up:
  - [ ] Add the first source to `raw/`

### [2026-04-14 00:01] Companion KB Seed
- Mode: create
- Summary: Replaced the bootstrap placeholders with repo-specific `wiki`, `indexes`, `schema`, `config`, and `raw` seed content for an Obsidian-first companion KB.
- `raw`: added initial internal and external extract manifests under `raw/extracts/`
- `wiki`: added route, model, operations, tooling, and source-summary notes
- `indexes`: added canonical-material, docs-surface, skill-surface, internal-source, external-source, ingest-queue, source-map, and coverage indexes
- `schema`: added initial page-type, field, and collection contracts
- `config`: refined `config/obsidian-vault.md` and added ingest/provenance contracts
- `canonical material`: unchanged; repo docs/code remain authoritative
- `provenance`: linked each maintained note back to repo paths or planned external raw captures
- `derived output`: none
- `vault`: retained shared `.obsidian/` starter templates and documented companion-KB behavior
- `path map`: none
- `link/backlink impact`: root `wiki` and `indexes` now provide stable navigation for future enrich work
- Risks / rollback: this is additive scaffold content only; rollback is limited to removing the new `kb/` tree
- Follow-up:
  - [ ] Ingest first-wave external source captures into `raw/sources/external/`
  - [ ] Add contributor and stakeholder route notes if the KB expands beyond the current maintainer focus

### [2026-04-14 00:02] External Raw Mirror Wave 1
- Mode: ingest
- Summary: Added the first broad external raw mirror across public contract, upstream NBA API, distribution, data stack, and tooling/vault collections.
- `raw`: added capture notes under `raw/sources/external/public-contract/`, `raw/sources/external/upstream-nba/`, `raw/sources/external/distribution/`, `raw/sources/external/data-stack/`, and `raw/sources/external/tooling-vault/`
- `wiki`: refreshed source-summary notes to point at the captured external collections
- `indexes`: refreshed `indexes/source-map.md`, `indexes/external-sources.md`, `indexes/ingest-queue.md`, and `raw/extracts/external/source-collections.md`
- `schema`: unchanged
- `config`: unchanged
- `canonical material`: unchanged
- `provenance`: linked external collections into the source summaries and source map
- `derived output`: none
- `vault`: unchanged
- `path map`: none
- `link/backlink impact`: external-source indexes now point at concrete captured directories instead of planned-only collections
- Risks / rollback: some public sites required failure-aware stubs instead of clean markdown captures; replace those later rather than deleting the records
- Follow-up:
  - [ ] Ingest additional published examples and docs-app stack sources
  - [ ] Replace the Obsidian Properties and PyPI stubs with fuller captures if access improves

### [2026-04-14 00:03] External Raw Mirror Wave 2
- Mode: ingest
- Summary: Added published Kaggle example captures, docs-app stack captures, and deeper KB topic notes for project, extractor, docs generator, and chat/query surfaces.
- `raw`: added `raw/sources/external/published-examples/` and `raw/sources/external/docs-app-stack/`
- `wiki`: added `project-overview`, `docs-autogen`, `docs-app-stack`, `extractor-surface`, `query-agent`, `chat-surface`, and `published-examples-source-summary`
- `indexes`: refreshed `source-map`, `external-sources`, `ingest-queue`, and `coverage`
- `schema`: unchanged
- `config`: unchanged
- `canonical material`: unchanged
- `provenance`: linked second-wave external collections into the new topic notes
- `derived output`: none
- `vault`: unchanged
- `path map`: none
- `link/backlink impact`: the KB now has explicit notes for docs generation, chat runtime, extractor surface, and published examples
- Risks / rollback: published Kaggle notebook captures remain stub-heavy because the notebook pages were fetch-limited
- Follow-up:
  - [ ] Capture richer notebook metadata if access improves
  - [ ] Add dedicated topic notes for model-audit, docs generator internals, and query cookbook families

### [2026-04-14 00:04] KB Enrichment Wave 3
- Mode: enrich
- Summary: Added high-value internal topic notes for docs generator internals, browser playground behavior, model audit, and query-cookbook routing, plus supporting internal extract manifests.
- `raw`: added `raw/extracts/internal/chat-surface-manifest.md` and `raw/extracts/internal/docs-app-stack-inventory.md`
- `wiki`: added `docs-generator-internals`, `playground-lane`, `model-audit`, and `query-cookbook-families`
- `indexes`: refreshed `source-map`, `coverage`, and root wiki navigation
- `schema`: unchanged
- `config`: unchanged
- `canonical material`: unchanged
- `provenance`: linked new notes to internal manifests, repo code, and external docs-app stack captures
- `derived output`: none
- `vault`: unchanged
- `path map`: none
- `link/backlink impact`: topic-level navigation is now stronger for docs generation, playground behavior, and model-audit work
- Risks / rollback: additive note batch only; no existing canonical material moved or rewritten
- Follow-up:
  - [ ] Add component-level docs-app notes if the docs surface becomes an active maintenance lane
  - [ ] Add deeper query-cookbook family examples if the analytics KB grows into a cookbook reference

### [2026-04-14 00:05] KB Enrichment Wave 4
- Mode: ingest + enrich
- Summary: Added a much larger fourth wave covering deeper NBA API docs, warehouse docs, docs-framework docs, agent-runtime docs, six new topic notes, and two new internal manifests.
- `raw`: added `nba-api-deep`, `warehouse-deep`, `docs-framework-deep`, and `agent-runtime-deep` external collections plus `analytics-helper-surface-manifest` and `lineage-audit-inventory`
- `wiki`: added `metric-calculator-surface`, `season-time-semantics`, `visualization-surface`, `docs-component-registry`, `lineage-internals`, and `query-safety`
- `indexes`: refreshed `external-sources`, `ingest-queue`, `source-map`, `coverage`, and root wiki navigation
- `schema`: unchanged
- `config`: unchanged
- `canonical material`: unchanged
- `provenance`: linked the new deep collections to the new topic notes and manifests
- `derived output`: none
- `vault`: unchanged
- `path map`: none
- `link/backlink impact`: the KB now has deeper coverage for safety, lineage internals, docs components, metric helpers, and season semantics
- Risks / rollback: some deep framework and agent-runtime URLs required stub captures because the public endpoint moved or returned a 404 shell
- Follow-up:
  - [ ] Add dedicated topic notes for specific visualization helpers or cookbook families if usage becomes heavy
  - [ ] Replace stub captures with fuller extracts when access paths improve

### [2026-04-14 00:06] KB Enrichment Wave 5
- Mode: ingest + enrich
- Summary: Added another extra-large wave with deep Kaggle, docs-runtime, visualization, and LangGraph captures plus eight new topic notes and two new internal manifests.
- `raw`: added `kaggle-deep`, `docs-runtime-deep`, `viz-deep`, and `langgraph-deep` external collections plus `helper-module-breakdown` and `docs-admin-search-inventory`
- `wiki`: added `court-helper-internals`, `comparison-similarity-helpers`, `lineup-trend-helpers`, `docs-admin-surface`, `kaggle-publishing-lane`, `docs-search-surface`, `chainlit-runtime`, and `export-share-artifacts`
- `indexes`: refreshed `external-sources`, `ingest-queue`, `source-map`, `coverage`, and root wiki navigation
- `schema`: unchanged
- `config`: unchanged
- `canonical material`: unchanged
- `provenance`: linked the new deep collections to runtime, admin, export, helper, and publishing notes
- `derived output`: none
- `vault`: unchanged
- `path map`: none
- `link/backlink impact`: helper and runtime topics now have stronger raw-source coverage and discoverability
- Risks / rollback: a handful of deep pages still required stub captures because the upstream route moved or was unavailable
- Follow-up:
  - [ ] Add topic notes for admin telemetry internals or notebook publishing internals if the KB keeps expanding
  - [ ] Replace remaining stubs with fuller captures when source accessibility improves

### [2026-04-14 00:07] KB Enrichment Wave 6
- Mode: ingest + enrich
- Summary: Resumed the interrupted doubled wave and added deeper Chainlit, Copilot, docs-admin, DuckDB-WASM, advanced NBA API, and notebook-metadata captures plus route, topic, and manifest coverage for chrome, telemetry, prompts, MCP, sandbox, and skills.
- `raw`: added `chainlit-deep`, `copilot-deep`, `docs-admin-deep`, `duckdb-wasm-deep`, `nba-api-advanced`, and `kaggle-notebook-metadata` external collections plus six new internal manifests
- `wiki`: added contributor/stakeholder routes, topic family and stub-replacement indexes, and topic notes for docs chrome, telemetry, DuckDB-WASM runtime, search query expansion, artifact store, sandbox contract, prompt assembly, profile/settings, MCP surface, and chat skills
- `indexes`: refreshed `external-sources`, `ingest-queue`, `source-map`, and root wiki navigation
- `schema`: unchanged
- `config`: unchanged
- `canonical material`: unchanged
- `provenance`: linked new raw collections and internal manifests into runtime, route, admin, and export topics
- `derived output`: none
- `vault`: unchanged
- `path map`: none
- `link/backlink impact`: the KB now has stronger route coverage, admin/docs runtime coverage, and deeper chat/runtime surface mapping
- Risks / rollback: several new deep captures are stub-heavy because upstream docs moved or were unavailable
- Follow-up:
  - [ ] Add dedicated notes for notebook publishing internals and admin telemetry internals if the KB continues expanding
  - [ ] Replace new stub captures as upstream access paths stabilize

### [2026-04-15 00:09] KB Enrichment Wave 7
- Mode: enrich
- Summary: Added the remaining high-value service-layer, notebook/bootstrap, tracing, catalog, memory, and finer-grained docs-admin notes, plus supporting service/admin inventories.
- `raw`: added `chat-service-layer-inventory` and `docs-admin-page-inventory`
- `wiki`: added service/runtime notes for semantic catalog, SQL validator, memory store, Copilot backend, web context tools, notebook/bootstrap, launcher, tracing, access mode, and finer-grained docs-admin pages
- `indexes`: refreshed `wiki/index.md`, `coverage`, `topic-family-map`, `source-map`, and `activity/log.md`
- `schema`: unchanged
- `config`: unchanged
- `canonical material`: unchanged
- `provenance`: linked the new service-layer and admin-page inventories into the new note cluster
- `derived output`: none
- `vault`: unchanged
- `path map`: none
- `link/backlink impact`: the KB now has dedicated notes for the main remaining chat service and docs-admin page surfaces rather than only broad umbrella notes
- Risks / rollback: additive note batch only; structural work is effectively complete and remaining work is mostly stub replacement or optional deepening
- Follow-up:
  - [ ] Replace stub-heavy external captures when upstream docs stabilize
  - [ ] Add only optional deeper notes if a specific maintenance lane starts seeing repeated use

### [2026-04-17 00:38] Strict Source-Complete Roadmap
- Mode: derive
- Summary: Added a maintained roadmap note that consolidates the remaining strict scratch-from-zero execution plan into slices, waves, and subagent workstreams.
- `raw`: unchanged
- `wiki`: added `wiki/topics/strict-source-complete-roadmap.md`; updated `wiki/index.md`
- `indexes`: updated `indexes/coverage.md`
- `schema`: unchanged
- `config`: unchanged
- `canonical material`: unchanged; roadmap note points back to support-matrix, audit, workflow, orchestrator, and docs surfaces as authorities
- `provenance`: linked the roadmap to canonical code, generated contract surfaces, and current local support-matrix output
- `derived output`: none
- `vault`: frontmatter added for one new maintained topic note; no shared `.obsidian/` surfaces changed
- `path map`: none
- `link/backlink impact`: wiki home and coverage index now expose a canonical route for strict-completeness execution planning
- Risks / rollback: additive KB note only; rollback is limited to removing the note and index/log references
- Follow-up:
  - [ ] Start Wave A from the roadmap: season-type contract, registry/artifact truth cleanup, and live snapshot contract design

### [2026-04-22 13:45] KB Repair and Control-Plane Extension
- Mode: improve
- Summary: Repaired the KB trust layer, refreshed repo-path references to the current docs tree, added control-plane/live-snapshot coverage, and tightened the tracked vault surface with a KB-local ignore file.
- `raw`: added `endpoint-coverage-and-audit-manifest`, `docs-generator-manifest`, and `full-extraction-control-manifest`; refreshed existing internal manifests to current docs/chat note targets
- `wiki`: added `wiki/topics/full-extraction-control-plane.md` and `wiki/topics/live-snapshot-contract.md`; refreshed `docs-autogen`, `docs-profiling-surface`, `model-audit`, `endpoint-coverage-source-summary`, `lineage-internals`, and route/model/ops docs-path references
- `indexes`: refreshed `canonical-material`, `docs-surface-map`, `ingest-queue`, `source-map`, `coverage`, `topic-family-map`, `internal-source-catalog`, and `wiki/index.md`
- `schema`: unchanged
- `config`: unchanged; `obsidian-vault-conventions` now records the same-batch maintenance rule for `coverage`, `source-map`, `source_count`, and `activity/log.md`
- `canonical material`: removed dead `CLAUDE.md` references and aligned public-docs paths to the current `start/`, `ops/`, `model/`, and `sources/` layout
- `provenance`: linked the new control-plane and docs-generator bridges into maintained topic notes and removed dead local-path refs except the intentionally optional `docs/table-profile.generated.json`
- `derived output`: none
- `vault`: added `kb/.gitignore` plus tracked `.obsidian/snippets/.gitkeep`; local validators now only warn about the still-present volatile `.obsidian/{app,graph,workspace}.json` files if they remain in the working tree
- `path map`: docs-path refresh from legacy `guides/` / `schema/` / `lineage/` note references to current `start/` / `ops/` / `model/` / `sources/` surfaces
- `link/backlink impact`: `coverage` now has one concrete row per maintained wiki page, `source-map` source IDs are unique, and the KB has first-class routes for full-extraction control flow and live-snapshot semantics
- Risks / rollback: broad KB-only edit batch; rollback can be done by removing the new manifests/notes and restoring the refreshed indexes and path refs
- Follow-up:
  - [ ] Replace or delete the untracked local `.obsidian/app.json`, `.obsidian/graph.json`, and `.obsidian/workspace.json` files if the repo should never carry them in the working tree
  - [ ] Keep future KB growth narrow and admit it only with same-batch index/log maintenance
