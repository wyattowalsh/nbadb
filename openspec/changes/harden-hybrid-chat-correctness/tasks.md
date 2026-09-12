All tasks are intentionally unchecked until their implementation or validation
evidence is present in the integrated working tree.

Review follow-up (2026-08-04): tasks marked incomplete below were reopened
because the integrated adversarial review contradicted their earlier completion
evidence. The snapshot at the end of this file is retained only as historical
evidence and must not be used to close the reopened work.

## 1. Contract And Fixtures

- [x] 1.1 Add immutable route-local warehouse probe metadata for every year-capable catalog route
- [x] 1.2 Add catalog construction validation for probe SQL, tables, placeholders, schema, and fixture `EXPLAIN` behavior
- [x] 1.3 Add the reviewed route-match collision corpus with expected routes and cross-route co-top diagnostics
- [x] 1.4 Run strict OpenSpec validation for this change and retain JSON evidence

## 2. Season Planning

- [x] 2.1 Separate explicit year and type extraction so relative year phrases do not inject a type before route capability resolution (depends: 1.1)
- [x] 2.2 Detect raw Unicode-decimal season candidates, accept only exact adjacent ASCII `YYYY-YY`, exclude dates/identifiers, and reject any malformed candidate before probing or SQL generation (depends: 2.1)
- [x] 2.3 Replace the global warehouse maximum and scalar cache with request-local route-and-type-specific probe execution (depends: 1.1, 2.2)
- [x] 2.4 Implement the stable calendar fallback warning for probe errors, empty results, and invalid maxima (depends: 2.3)
- [x] 2.5 Add `needs_reason` and omit SQL, hash, and season execution metadata from every `needs_params` response (depends: 2.2)
- [x] 2.6 Add route-matrix, malformed-token corpus, mixed-valid precedence, no-side-effect, differing-maxima, join-visibility, explicit-precedence, unsupported-dimension, fallback, and metadata regression tests (depends: 2.3-2.5)

## 3. Catalog And Chat Integration

- [x] 3.1 Preserve semantic specificity ordering and make the reviewed corpus a catalog validation gate (depends: 1.3)
- [x] 3.2 Reconcile missing-warehouse failure, absolute Chainlit environment paths, and canonical `chat/` launcher checks
- [x] 3.3 Reconcile CLI, Chainlit, and notebook examples with the supported route contract; document offline analytics helpers as non-Q&A and enforce exact season identifier grammar (depends: 2.6, 3.1)
- [x] 3.4 Preserve `ReadOnlyGuard`, read-only DuckDB, disabled external access, static catalog SQL, and deterministic source-presence enforcement for cache-tagged and adjacent bytecode across both canonical roots (depends: 3.2)
- [x] 3.5 Add focused catalog, runtime, Chainlit handler, CLI path, safety, source-inventory, and golden-chat tests (depends: 3.1-3.4)

## 4. Session-Owned Memory

- [x] 4.1 Normalize scoped and administrator session IDs at the preference-store mutation boundary
- [x] 4.2 Implement immediate-transaction create/update authorization, typed record validation, dual-copy aware timestamp validation/healing, and per-key monotonic UTC microseconds without changing trajectory precision (depends: 4.1)
- [x] 4.3 Implement deletion with identical transaction, validation, ownership, and fixed-error behavior (depends: 4.2)
- [x] 4.4 Preserve MCP nonempty-session, payload-bound, confirmation, and sanitized-error gates (depends: 4.2, 4.3)
- [x] 4.5 Add same-owner, foreign, null-owned, malformed, administrator, frozen/backward/mismatched/invalid timestamp, rollback, and event-ordered separate-connection update/delete concurrency tests (depends: 4.2-4.4)

## 5. Integrated Assurance

- [x] 5.1 Run Ruff format and lint for every touched Python and test path (depends: 2-4)
- [x] 5.2 Run `ty check src/` and resolve every chat-surface diagnostic (depends: 5.1)
- [x] 5.3 Run focused chat, agent, memory, Chainlit, and CLI tests with `--import-mode=importlib` and record counts (depends: 5.2)
- [x] 5.4 Run `python -m nbadb.chat.source_inventory` and the full unit and integration suites (depends: 5.3)
- [x] 5.5 Reconcile authored docs and generated chat catalog artifacts, then run docs lint, format, build, and no-drift generation (depends: 3.3, 5.4)
- [x] 5.6 Run `/docs-steward` or the available equivalent after public and file-structure changes (depends: 5.5)
- [ ] 5.7 Complete independent correctness, concurrency, safety, and docs reviews; resolve every confirmed finding (depends: 5.6)
- [ ] 5.8 Re-run strict OpenSpec validation and record final commands, counts, skips, and scoped diff evidence (depends: 5.7)

## 6. Route-Local Entity Binding

- [x] 6.1 Declare player/team/seasonless entity capability for every routed catalog entry, including symmetric two-entity routes and route-specific required cues
- [x] 6.2 Resolve entity aliases from fixed read-only `dim_player` / `dim_team` lookups, reject missing/ambiguous required entities, and expose stable `needs_reason` guidance before probing or SQL generation (depends: 6.1)
- [x] 6.3 Bind only validated positive numeric entity IDs as positional parameters in executable SQL and route-local probes (depends: 6.2)
- [x] 6.4 Add distinct player/team plan and result tests, ambiguity/unresolved/no-side-effect tests, entity-scoped season-probe tests, and league-wide non-overscoping tests (depends: 6.3)

## 7. Session Reads, Findings, And Presentation

- [x] 7.1 Require exact normalized session ownership for preference and trajectory reads; keep any administrator-wide store inspection explicitly separate and off the MCP surface
- [x] 7.2 Make saved findings session-scoped and collision-safe with bounded slug/digest identities, preserved metadata, and bounded filesystem errors
- [x] 7.3 Render the Chainlit main answer non-verbosely, retain warnings, and attach SQL only once as a side element
- [x] 7.4 Add foreign/null/malformed read tests, same-title cross-session/concurrent finding tests, bounds/error tests, and Chainlit single-SQL tests (depends: 7.1-7.3)

## 8. Wave 2B Assurance

- [x] 8.1 Run focused agent/chat tests with `--import-mode=importlib` and record exact counts
- [x] 8.2 Run scoped Ruff lint/format, `ty`, source inventory, notebook-independent route `EXPLAIN`, and strict OpenSpec validation
- [x] 8.3 Re-run independent scoped review and reconcile task truth (depends: 8.1, 8.2)

Wave 2B evidence snapshot (2026-08-12):

- Final focused agent/chat/launcher/MCP/notebook slice: `307 passed in 31.00s`; new entity, scoped-read, contention, artifact, and handler slice: `69 passed in 133.92s`.
- Final post-review route/entity metadata and result regression: `20 passed in 7.36s`; post-integration MCP entrypoint regression: `6 passed in 26.45s`.
- Scoped Ruff lint and format check passed (`59 files already formatted`); scoped `ty` passed; source inventory reported no orphan bytecode or retired app; route and probe `EXPLAIN` covered every entity-capable route.
- Direct strict OpenSpec validation passed `1/1` with zero issues; scoped `git diff --check` passed.

Final local evidence snapshot (2026-08-05):

- Repository assurance passed: unit `5158 passed, 16 skipped`; integration `142 passed`; complete suite `5300 passed, 16 skipped`; full Ruff lint and format check; `ty check src/`; source-inventory validation; notebook JSON validation; and `git diff --check`.
- Docs assurance passed Prettier, ESLint, TypeScript checking, `28` docs tests, a `67`-route production build, and two docs-autogen runs with no generated diff.
- Strict OpenSpec validation passed for this change and `full-extraction-transactional-recovery` after final task-ledger and documentation reconciliation.
- Independent correctness, concurrency, safety, provenance, and documentation reviews found no surviving actionable issue. The complete suite and final reviews supersede the older partition counts below.

Superseded evidence snapshot (2026-08-04):

- `/docs-steward` was unavailable because `uv run wagents skills search docs-steward` failed with `Failed to spawn: wagents`; the available-equivalent review covered README, AGENTS, authored docs, Chainlit copy, generated surfaces, and final independent correctness/concurrency/safety/docs audits.
- Complete unit partitions passed: agent/chat/cli/core/docs-gen/notebooks `1069 passed, 14 skipped in 85.58s`; extract/schemas/transform/load/Kaggle `2264 passed, 2 skipped in 78.94s`; orchestration `1639 passed in 176.98s` (total `4972 passed, 16 skipped`).
- Integration passed: `142 passed in 35.51s` with `--import-mode=importlib`.
- Repository Ruff lint and format check, `ty check src/`, source inventory, notebook JSON validation, `actionlint`, `git diff --check`, docs lint/format/build (67 static pages), and docs-autogen no-drift checks passed.
- Strict non-interactive OpenSpec validation passed for both `harden-hybrid-chat-correctness` and `full-extraction-transactional-recovery` with zero issues.
- The final scoped and adversarial diff reviews reported no surviving actionable finding; `tmp.md` remained unrelated, untracked, and byte-identical.
