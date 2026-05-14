# Coverage

| Wiki path | Page type | Backing raw or canonical material | Coverage status | Last reviewed | Notes |
|-----------|-----------|-----------------------------------|-----------------|---------------|-------|
| `wiki/index.md` | overview | `README.md`, `AGENTS.md`, `docs/AGENTS.md` | active | 2026-04-22 | Root map and companion-KB contract |
| `wiki/routes/start-here.md` | overview | `docs/content/docs/index.mdx`, `docs/content/docs/guides/role-based-onboarding-hub.mdx` | active | 2026-05-07 | Reader route hub |
| `wiki/routes/analyst-route.md` | overview | `docs/content/docs/guides/analytics-quickstart.mdx`, `chat/skills/nba-data-analytics/` | active | 2026-05-07 | Analytics-first route |
| `wiki/routes/operator-route.md` | overview | `docs/content/docs/guides/daily-updates.mdx`, `docs/content/docs/guides/troubleshooting-playbook.mdx` | active | 2026-05-07 | Operator-first route |
| `wiki/routes/contributor-route.md` | overview | `AGENTS.md`, `docs/AGENTS.md`, CLI/docs workflow sources | active | 2026-04-22 | Contributor/maintainer route |
| `wiki/routes/stakeholder-route.md` | overview | public docs, README, published examples | active | 2026-04-14 | Stakeholder/high-level route |
| `wiki/model/table-family-guide.md` | concept | `README.md`, `AGENTS.md`, schema docs | active | 2026-04-14 | Prefix and grain guide |
| `wiki/model/schema-wayfinding.md` | concept | schema docs, data dictionary docs, schema coverage artifact | active | 2026-04-14 | Routing note |
| `wiki/model/lineage-wayfinding.md` | concept | model/lineage docs, endpoint docs, `AGENTS.md` | active | 2026-04-22 | Dependency routing note |
| `wiki/model/endpoint-coverage.md` | concept | endpoint docs, endpoint coverage report, `AGENTS.md` | active | 2026-04-14 | Coverage interpretation note |
| `wiki/operations/runbooks.md` | index | operations wiki pages, guides docs, `AGENTS.md` command contract, KB config/indexes | active | 2026-05-07 | Operational runbook registry and entrypoint |
| `wiki/operations/run-modes.md` | concept | architecture, CLI reference, daily-updates guide | active | 2026-04-14 | Run-mode decision note |
| `wiki/operations/kaggle-distribution.md` | concept | Kaggle guide, CLI code, config, metadata/client implementation | active | 2026-05-07 | Distribution lane aligned to current `--data-dir data/nbadb` command contract |
| `wiki/operations/troubleshooting.md` | concept | troubleshooting guide, config, CLI docs | active | 2026-04-14 | Troubleshooting lane |
| `wiki/tooling/duckdb-polars-pandera-stack.md` | concept | `pyproject.toml`, README, repo code, external docs targets | active | 2026-04-14 | Data stack explainer |
| `wiki/tooling/sqlmodel-typer-textual-stack.md` | concept | `pyproject.toml`, CLI code, external docs targets | active | 2026-04-14 | App/control surface explainer |
| `wiki/tooling/obsidian-vault-conventions.md` | concept | repo scan, `docs/AGENTS.md`, external Obsidian targets | active | 2026-04-14 | Shared vault config companion |
| `wiki/topics/analytics-skill-guide.md` | entity | analytics skill files | active | 2026-04-14 | Chat skill note |
| `wiki/topics/query-patterns.md` | concept | query cookbook, schema guide | active | 2026-04-14 | Query pattern menu |
| `wiki/topics/project-overview.md` | concept | repo canon, docs surface, public docs captures | active | 2026-04-14 | repo-level orientation note |
| `wiki/topics/strict-source-complete-roadmap.md` | concept | support matrix command output, model audit baseline, staging map, workflow/orchestrator code, README, architecture docs | active | 2026-04-22 | comprehensive execution roadmap for strict scratch-from-zero completeness |
| `wiki/topics/docs-autogen.md` | concept | docs generator code, docs instructions, and docs-generator manifest | active | 2026-04-22 | generator ownership note |
| `wiki/topics/docs-app-stack.md` | concept | docs app code, docs package, docs-app stack captures | active | 2026-04-14 | frontend/docs runtime note |
| `wiki/topics/docs-generator-internals.md` | concept | docs generator code and internal docs app inventory | active | 2026-04-14 | generator internals note |
| `wiki/topics/playground-lane.md` | concept | docs playground page, docs DuckDB runtime, docs-app stack captures | active | 2026-04-14 | browser rehearsal note |
| `wiki/topics/docs-component-registry.md` | concept | docs component files and docs instructions | active | 2026-04-14 | MDX and chrome component note |
| `wiki/topics/extractor-surface.md` | concept | extract registry, base extractor, staging map | active | 2026-04-14 | ingestion boundary note |
| `wiki/topics/upstream-nba-api.md` | concept | extractor registry, extract base, upstream capture set, extractor/staging inventory | active | 2026-04-22 | upstream family split and dependency boundary note |
| `wiki/topics/extraction-boundary.md` | concept | extractor registry, extract base, staging map, extractor/staging inventory | active | 2026-04-22 | normalization and staging ownership note |
| `wiki/topics/model-audit.md` | concept | model audit engine, endpoint coverage artifacts, and coverage/audit manifest | active | 2026-04-22 | stricter audit note |
| `wiki/topics/query-agent.md` | concept | `src/nbadb/agent/*` | active | 2026-04-14 | local read-only ask surface |
| `wiki/topics/chat-surface.md` | concept | `src/nbadb/chat/*`, `chat/*`, chat surface manifests | active | 2026-04-22 | rich chat/runtime note with runtime-shell split |
| `wiki/topics/query-cookbook-families.md` | concept | query cookbook, analytics skill, query-pattern notes | active | 2026-04-14 | cookbook routing note |
| `wiki/topics/query-safety.md` | concept | query safety code, chat/runtime trust boundaries | active | 2026-04-14 | trust-boundary note |
| `wiki/topics/metric-calculator-surface.md` | concept | analytics helper modules, canonical chat runtime, and skill docs | active | 2026-04-22 | helper-function surface note |
| `wiki/topics/season-time-semantics.md` | concept | season helpers, season-type gotchas, repo instructions, and chat prompt/runtime surfaces | active | 2026-04-22 | time-semantics note |
| `wiki/topics/visualization-surface.md` | concept | docs and chat visualization surfaces | active | 2026-04-22 | charting/visual output note |
| `wiki/topics/court-helper-internals.md` | concept | court helper, canonical chat runtime, prompt routing, viz helper manifests | active | 2026-04-22 | court and shot-chart helper note |
| `wiki/topics/comparison-similarity-helpers.md` | concept | compare/similarity helpers, canonical chat runtime, and tests | active | 2026-04-22 | comparison/similarity helper note |
| `wiki/topics/lineup-trend-helpers.md` | concept | lineup and trends helpers, canonical chat runtime, and helper manifests | active | 2026-04-22 | lineup/trend helper note |
| `wiki/topics/lineage-internals.md` | concept | lineage generator, model/lineage docs, dependency graph, and lineage/audit inventory | active | 2026-04-22 | lineage computation note |
| `wiki/topics/docs-admin-surface.md` | concept | docs admin routes, auth, telemetry, charts | active | 2026-04-14 | docs admin/runtime note |
| `wiki/topics/kaggle-publishing-lane.md` | concept | Kaggle metadata, client integration, publish/download lane, published-example index | active | 2026-05-07 | Kaggle publishing note aligned to metadata generation and upload/download boundaries |
| `wiki/topics/docs-search-surface.md` | concept | docs search runtime and source-backed search | active | 2026-04-14 | docs search/runtime note |
| `wiki/topics/chainlit-runtime.md` | concept | Chainlit session/render/export runtime | active | 2026-04-14 | Chainlit runtime note |
| `wiki/topics/export-share-artifacts.md` | concept | export, embed, spreadsheet, social-card surfaces | active | 2026-04-14 | export/share artifact note |
| `wiki/topics/docs-chrome-surfaces.md` | concept | docs chrome components and wrap order | active | 2026-04-14 | docs chrome note |
| `wiki/topics/docs-telemetry-health.md` | concept | content audit, pipeline summary, Umami, health routes | active | 2026-04-14 | docs telemetry note |
| `wiki/topics/duckdb-wasm-runtime.md` | concept | docs DuckDB-WASM singleton and worker/runtime behavior | active | 2026-04-14 | browser runtime note |
| `wiki/topics/search-query-expansion.md` | concept | docs search aliases, seeded prompts, trigger logic | active | 2026-04-14 | search expansion note |
| `wiki/topics/artifact-store-internals.md` | concept | artifact store and export helper internals | active | 2026-04-14 | artifact internals note |
| `wiki/topics/sandbox-runtime-contract.md` | concept | `run_sql` / `run_python` runtime contract and trust boundary | active | 2026-04-22 | sandbox contract note |
| `wiki/topics/prompt-assembly-and-capabilities.md` | concept | prompt assembly, capability manifest, backend wiring | active | 2026-04-14 | prompt/capabilities note |
| `wiki/topics/profile-settings-surface.md` | concept | profiles, gear-panel settings, provider/model choices | active | 2026-04-14 | settings/profile note |
| `wiki/topics/mcp-server-surface.md` | concept | MCP server layout and runtime role split | active | 2026-04-14 | MCP surface note |
| `wiki/topics/chat-skill-surface.md` | concept | overall chat skill taxonomy including new skills | active | 2026-04-14 | chat skills note |
| `wiki/topics/semantic-catalog-service.md` | concept | catalog service/models, MCP wiring, and semantic ranking logic | active | 2026-04-22 | semantic catalog note |
| `wiki/topics/sql-validator-service.md` | concept | SQL validation, risk, explain, and repair service | active | 2026-04-22 | SQL validator note |
| `wiki/topics/memory-store-internals.md` | concept | memory models, persistence, and search/store behavior | active | 2026-04-15 | memory store note |
| `wiki/topics/copilot-backend-runtime.md` | concept | alternate Copilot runtime and tool mirror | active | 2026-04-15 | Copilot backend note |
| `wiki/topics/sandbox-backend-modes.md` | concept | local/daytona/e2b backend switching, remote sync, and wrapper-aware path rewriting | active | 2026-04-22 | sandbox backend note |
| `wiki/topics/web-context-tools.md` | concept | web search/fetch tools and SSRF/content safeguards | active | 2026-04-15 | web context note |
| `wiki/topics/chat-notebook-bootstrap.md` | concept | notebook bootstrap, clone/install, and data seeding flow | active | 2026-04-15 | notebook bootstrap note |
| `wiki/topics/chat-launcher-runtime-surface.md` | concept | launcher helpers and CLI handoff to Chainlit | active | 2026-04-15 | launcher runtime note |
| `wiki/topics/chat-tracing-surface.md` | concept | tracing provider setup and fallback behavior | active | 2026-04-15 | tracing note |
| `wiki/topics/access-mode-contract.md` | concept | provider->access mode mapping and capability implications | active | 2026-04-15 | access mode note |
| `wiki/topics/docs-admin-control-center.md` | concept | admin shell/login/nav/overview control center | active | 2026-04-15 | admin control center note |
| `wiki/topics/docs-content-audit.md` | concept | source-backed docs content audit and filtering semantics | active | 2026-04-15 | content audit note |
| `wiki/topics/docs-pipeline-dashboard.md` | concept | pipeline dashboard semantics and chart/status logic | active | 2026-04-15 | pipeline dashboard note |
| `wiki/topics/docs-profiling-surface.md` | concept | profiling JSON lookup, optional artifact contract, and layer-table rendering | active | 2026-04-22 | profiling surface note |
| `wiki/topics/full-extraction-control-plane.md` | concept | manifest-driven lane planning, workflow chaining, and resume semantics | active | 2026-04-22 | workflow/control-plane note |
| `wiki/topics/live-snapshot-contract.md` | concept | automatic vs manual live-snapshot semantics and append-only warehouse contract | active | 2026-04-22 | live snapshot semantics note |
| `wiki/topics/analytics-skill-source-summary.md` | source-summary | analytics skill files and chat/runtime manifests | active | 2026-04-22 | analytics skill evidence bridge |
| `wiki/topics/docs-site-source-summary.md` | source-summary | public docs captures and internal docs manifests | active | 2026-04-22 | docs evidence bridge |
| `wiki/topics/endpoint-coverage-source-summary.md` | source-summary | coverage/audit code, artifacts, docs route, and manifest bridge | active | 2026-04-22 | coverage evidence bridge |
| `wiki/topics/nba-api-source-summary.md` | source-summary | upstream NBA captures and extractor coverage bridge | active | 2026-04-22 | upstream API evidence bridge |
| `wiki/topics/published-examples-source-summary.md` | source-summary | README notebook list, published-example stubs, and warehouse-aligned outputs | active | 2026-04-22 | notebook/source alignment note |

## Gaps
- [ ] Replace high-value stub-backed sources from [[stub-replacement-queue|Stub Replacement Queue]] before adding broad new note clusters.
- [ ] Use [[../config/note-admission|Note Admission]] for any future growth so new notes are justified by stable seams and real navigation cost.
- [ ] Treat further topic expansion as optional; the remaining high-leverage work is mostly maintenance and stub replacement.
