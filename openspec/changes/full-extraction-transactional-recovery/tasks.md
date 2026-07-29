Checked tasks are present in the current working tree. They are not a substitute
for the still-open validation, CI, smoke, extraction, and publication gates.
Tasks are ordered by dependency; tasks with the same `depends` set are safe
parallel subagent leaves unless they name the same file.

## 1. Evidence And Contract Freeze

- [x] 1.1 Record run `29568624951`, its failed checkpoint error, source SHA, duration, job counts, accepted lane counts, call counts, row counts, and missing canonical checkpoint as the incident baseline
- [x] 1.2 Freeze the 13 completed lanes' original and rescheduled indexes in a deterministic fixture (depends: 1.1)
- [x] 1.3 Freeze the incident's expected semantic coverage fingerprint and per-lane coverage hashes in that fixture (depends: 1.2)
- [x] 1.4 Document the change motivation, capability boundaries, affected surfaces, and retained fail-closed gates in `proposal.md` (depends: 1.1)
- [x] 1.5 Document architectural decisions, alternatives, risks, migration, rollback, and live open questions in `design.md` (depends: 1.4)
- [x] 1.6 Specify transactional checkpoint requirements and testable scenarios (depends: 1.5)
- [x] 1.7 Specify exact redispatch requirements and testable scenarios (depends: 1.5; parallel: 1.6, 1.8)
- [x] 1.8 Specify bounded response-contract circuit requirements and testable scenarios (depends: 1.5; parallel: 1.6, 1.7)
- [x] 1.9 Run strict OpenSpec validation after every planning-artifact edit and retain the final JSON evidence (depends: 1.6-1.8, this task file)

## 2. Stable Lane Identity

- [x] 2.1 Define stable lane coverage identity as exact `lane_id` plus lowercase SHA-256 `coverage_units_hash` (depends: 1.6)
- [x] 2.2 Canonically sort stable lane identities before computing the lane-inventory digest (depends: 2.1)
- [x] 2.3 Exclude `lane_index`, planned wave, scheduling priority, queue class, and VPN slot from durable coverage identity (depends: 2.1)
- [x] 2.4 Preserve attempt-local `lane_index` in manifests and metadata for diagnostics and dispatch (depends: 2.3)
- [x] 2.5 Validate a present attempt-local index as non-boolean, integral, and non-negative without comparing it to a rescheduled index (depends: 2.4)
- [x] 2.6 Keep lane ID, semantic axes, coverage hash, source, chain, run, state-artifact, journal, and workload-scope validation strict (depends: 2.3)
- [x] 2.7 Update checkpoint artifact acceptance to use semantic identity after rescheduling (depends: 2.5, 2.6)
- [x] 2.8 Add property tests proving input permutation and dispatch-field changes preserve durable identity (depends: 2.2, 2.7)
- [x] 2.9 Add negative tests proving lane ID or coverage-hash changes invalidate durable identity (depends: 2.2, 2.7)
- [x] 2.10 Add the run `29568624951` end-to-end regression proving original metadata indexes survive a later schedule reorder (depends: 1.2, 2.7)

## 3. Versioned Checkpoint Transaction Contract

- [x] 3.1 Add a dedicated checkpoint-contract module with a declared schema version (depends: 1.6)
- [x] 3.2 Define exact-key lane coverage, checkpoint coverage, checkpoint identity, build, artifact receipt, and transaction value objects (depends: 3.1)
- [x] 3.3 Validate exact text, positive integers, full source SHAs, raw SHA-256 values, and `sha256:` artifact digests (depends: 3.2)
- [x] 3.4 Define the `candidate`, `built`, `uploaded_verified`, and `committed` states (depends: 3.1)
- [x] 3.5 Permit only candidate-to-built, built-to-uploaded-verified, and uploaded-verified-to-committed transitions (depends: 3.4)
- [x] 3.6 Bind built transactions to checkpoint database and report SHA-256 values (depends: 3.2, 3.5)
- [x] 3.7 Bind artifact receipts to artifact ID, run ID, name, digest, size, chain, source, generation, coverage, database, and report (depends: 3.2, 3.6)
- [x] 3.8 Reject receipt verification when any built identity or content field differs (depends: 3.7)
- [x] 3.9 Serialize and deserialize each transaction state with exact-key validation (depends: 3.2-3.8)
- [x] 3.10 Add unit tests for happy-path state transitions and exact round trips (depends: 3.9)
- [x] 3.11 Add unit tests for illegal transitions, malformed fields, unknown keys, and receipt-binding mismatches (depends: 3.9; parallel: 3.10)
- [x] 3.12 Add tests proving dispatch metadata does not alter checkpoint coverage identity (depends: 2.3, 3.2; parallel: 3.10, 3.11)

## 4. Candidate Build And Copy-Plus-Delta

- [x] 4.1 Remove provisional next-checkpoint coverage prediction from lane control (depends: 2.7, 3.4)
- [x] 4.2 Make lane control emit a candidate manifest that retains the prior committed pointer (depends: 4.1)
- [x] 4.3 Give the candidate manifest an attempt-scoped diagnostic artifact name distinct from the committed next-manifest name (depends: 4.2)
- [x] 4.4 Pass the candidate generation and logical checkpoint artifact name explicitly into checkpoint construction (depends: 4.2)
- [x] 4.5 Require candidate generation to equal the prior committed generation plus one (depends: 4.4)
- [x] 4.6 Require the logical checkpoint artifact name to match the chain and candidate generation (depends: 4.4)
- [x] 4.7 Build actual checkpoint coverage only after current and prior artifacts pass validation (depends: 2.7, 4.4)
- [x] 4.8 Remove the predicted latest-pointer coverage comparison from checkpoint construction (depends: 4.7)
- [x] 4.9 Preserve copy-before-merge behavior and a distinct output database path (depends: 4.4)
- [x] 4.10 Preserve maximum legitimate duplicate multiplicity and current-journal precedence during delta merge (depends: 4.9)
- [x] 4.11 Create a physical copy and new report for zero-delta generations (depends: 4.9)
- [x] 4.12 Bind the completed checkpoint database and report into a built transaction before upload (depends: 3.6, 4.7)
- [x] 4.13 Add a two-generation zero-delta test proving previous and latest transactions roll forward independently (depends: 4.11, 4.12)
- [x] 4.14 Add a mutation test proving post-build report changes prevent commit (depends: 4.12)
- [x] 4.15 Add the symmetric mutation test proving post-build database changes prevent commit (depends: 4.12; parallel: 4.14)
- [x] 4.16 Add a property test that arbitrary accepted-lane ordering yields the same actual coverage and canonical inventory (depends: 4.7)

## 5. Upload Verify Commit Workflow

- [x] 5.1 Upload the lane-control output as a checkpoint candidate rather than a trusted next manifest (depends: 4.2, 4.3)
- [x] 5.2 Build and include `checkpoint-transaction.json` with the checkpoint database and report (depends: 4.12)
- [x] 5.3 Capture the upload action's positive artifact ID and digest outputs (depends: 5.2)
- [x] 5.4 Resolve the uploaded artifact through the Actions REST API and validate ID, name, digest, size, run, source SHA, and non-expired state (depends: 5.3)
- [x] 5.5 Commit the verified receipt into `latest_checkpoint_transaction` only after REST verification (depends: 3.7, 5.4)
- [x] 5.6 Move the prior committed pointer and transaction to the `previous_checkpoint_*` fields during commit (depends: 5.5)
- [x] 5.7 Preserve and deduplicate authorized artifact run IDs during manifest commit (depends: 5.5)
- [x] 5.8 Upload a separate committed next-manifest artifact after receipt commit (depends: 5.5-5.7)
- [x] 5.9 Expose checkpoint and committed-manifest artifact IDs and digests as checkpoint job outputs (depends: 5.8)
- [x] 5.10 Make downstream terminal merge download the committed manifest and checkpoint by exact artifact IDs (depends: 5.9)
- [x] 5.11 Upload attempt-scoped diagnostics when any build, upload, receipt, commit, or committed-manifest gate fails (depends: 5.1-5.10)
- [x] 5.12 Remove overwrite semantics from the canonical checkpoint artifact upload so a committed artifact ID cannot be deleted by a rerun (depends: 5.3)
- [x] 5.13 Implement bounded exact-name sibling polling after an initial no-overwrite collision (depends: 5.12)
- [x] 5.14 Validate a collision sibling's ID, digest, size, run, source, database, report, chain, generation, and coverage before reusing it (depends: 5.13)
- [x] 5.15 Fail closed on ambiguous, malformed, unstable, expired, or nonmatching sibling inventories (depends: 5.14)
- [x] 5.16 Add workflow outputs that distinguish newly uploaded from validated-existing checkpoint receipts (depends: 5.14)
- [ ] 5.17 Add tests for failures at candidate, build, upload, receipt, commit, and committed-manifest upload boundaries proving the prior pointer remains authoritative (depends: 5.11-5.16)

## 6. Receipt-Bound Restore And Migration

- [x] 6.1 Add committed latest and previous transaction fields to chain-state serialization and normalization (depends: 3.9)
- [x] 6.2 Require any present checkpoint transaction to parse exactly and be committed (depends: 6.1)
- [x] 6.3 Cross-check transaction chain, source, generation, artifact name, and coverage against pointer fields (depends: 6.2)
- [x] 6.4 Resolve a receipt-aware previous checkpoint by its exact positive artifact ID (depends: 6.3)
- [x] 6.5 Validate the artifact REST identity against the committed receipt before download (depends: 6.4)
- [x] 6.6 Download the previous checkpoint by artifact ID with digest mismatch configured as an error (depends: 6.5)
- [x] 6.7 Revalidate downloaded database and report digests against the committed transaction before inventory use (depends: 6.6)
- [x] 6.8 Retain name/run restore only when the transaction field is entirely absent on a persisted legacy pointer (depends: 6.2)
- [x] 6.9 Ensure a present malformed transaction cannot fall back to legacy restore (depends: 6.2, 6.8)
- [x] 6.10 Ensure the first successful roll-forward from a legacy pointer emits a receipt-aware committed transaction (depends: 5.5, 6.8)
- [ ] 6.11 Add tests for expired artifact ID, REST digest mismatch, workflow-run mismatch, source-SHA mismatch, and size mismatch (depends: 6.5-6.7)
- [x] 6.12 Add tests proving transaction-absent legacy restore is accepted once and malformed transaction fallback is rejected (depends: 6.8-6.10)
- [ ] 6.13 Add a test proving a same-name newer artifact cannot replace the exact committed artifact ID (depends: 5.12-5.15, 6.4)

## 7. Exact Self-Redispatch

- [x] 7.1 Retain the exact-title history precheck for active and successful duplicate children (depends: 1.7)
- [x] 7.2 Retain source checkout, trusted-branch ancestry, publish ancestry, and workflow-blob equality gates (depends: 1.7)
- [x] 7.3 Make redispatch consume the committed next-manifest artifact name rather than the lane-control candidate (depends: 5.8)
- [x] 7.4 Build the complete child input payload with fixed chain, source, manifest, iteration, budget, network, chunk, and publication fields (depends: 7.2, 7.3)
- [x] 7.5 Post workflow dispatch with `return_run_details=true` (depends: 7.4)
- [x] 7.6 Parse and validate the positive returned run ID, API URL, and HTML URL (depends: 7.5)
- [x] 7.7 Read that exact run with bounded retries and validate title, event, head SHA, ID, and URL (depends: 7.6)
- [x] 7.8 Expose the exact acknowledged child ID and URL as outputs and summary evidence (depends: 7.7)
- [x] 7.9 Install exit and signal traps before dispatch and cancel the exact returned child when acknowledgement fails (depends: 7.5)
- [x] 7.10 Limit inventory-difference fallback to cancellation when dispatch may exist but its response was not parseable (depends: 7.9)
- [x] 7.11 Add a deterministic static test for `return_run_details`, returned-ID parsing, exact-run GET, and provenance assertions (depends: 7.5-7.8)
- [x] 7.12 Add mocked API tests for malformed response, unreadable exact child, wrong title, wrong event, wrong SHA, wrong URL, and interrupted acknowledgement (depends: 7.6-7.10)
- [x] 7.13 Add a test proving workflow-run inventory is never used to acknowledge the child (depends: 7.10)

## 8. Bounded Response-Contract Failure Circuit

- [x] 8.1 Add explicit per-endpoint positive response-contract circuit thresholds to settings (depends: 1.8)
- [x] 8.2 Configure `win_probability` with a threshold of three based on the repeated malformed-response incident (depends: 8.1)
- [x] 8.3 Implement pattern-execution-scoped consecutive signature state (depends: 8.1)
- [x] 8.4 Reset endpoint state after a contract-valid response (depends: 8.3)
- [x] 8.5 Restart the count when the normalized permanent failure signature changes (depends: 8.3)
- [x] 8.6 Exclude transport and all other non-response-contract failure classes from the circuit (depends: 8.3)
- [x] 8.7 Check the circuit before entering the endpoint rate limiter and upstream call (depends: 8.3)
- [x] 8.8 Record every suppressed call as a response-contract failure with a distinct circuit-open signature (depends: 8.7)
- [x] 8.9 Increment failed-call accounting and preserve the eligible-call denominator for suppressed calls (depends: 8.8)
- [x] 8.10 Prohibit success journal records, rows, and completed coverage for suppressed calls (depends: 8.8)
- [x] 8.11 Pass the circuit through initial chunk tasks and late-recovery replay paths (depends: 8.3-8.10)
- [x] 8.12 Preserve zero-progress chunk abort behavior after a circuit opens (depends: 8.9-8.11)
- [x] 8.13 Add a 1,241-call malformed `win_probability` test proving only three upstream calls and ten current-chunk failures (depends: 8.2-8.12)
- [x] 8.14 Assert circuit-suppressed calls produce failure journal entries and no success entries (depends: 8.13)
- [x] 8.15 Add a transport-failure test proving the response-contract circuit stays closed (depends: 8.6)
- [x] 8.16 Add a mixed-signature test proving the threshold is consecutive per signature (depends: 8.5)
- [x] 8.17 Add a valid-response reset test across queued calls (depends: 8.4)
- [ ] 8.18 Add a resume test proving suppressed params remain absent from completed journal coverage (depends: 8.8-8.12)
- [x] 8.19 Add metrics or structured summary counts for upstream attempts, circuit suppressions, signature, and preserved outstanding calls (depends: 8.8)

## 9. Focused Deterministic Assurance

- [ ] 9.1 Run Ruff formatting checks on every touched Python and test path (depends: 2-8)
- [ ] 9.2 Run Ruff lint on every touched Python and test path and resolve all findings (depends: 9.1)
- [ ] 9.3 Run `ty` on the checkpoint contract, control plane, runner, resilience, and configuration modules (depends: 9.2)
- [ ] 9.4 Run the checkpoint-contract unit test file in isolation (depends: 3.10-3.12)
- [ ] 9.5 Run the checkpoint-manifest transaction unit test file in isolation (depends: 4.13-4.16, 5.17, 6.11-6.13)
- [ ] 9.6 Run the lane-identity incident regression and Hypothesis properties in isolation (depends: 2.8-2.10)
- [ ] 9.7 Run the extractor-runner response-contract circuit tests in isolation (depends: 8.13-8.18)
- [ ] 9.8 Run all full-extraction control tests with `--import-mode=importlib` (depends: 9.4-9.7)
- [ ] 9.9 Run the maximum-width 256-lane checkpoint integration test (depends: 9.8)
- [ ] 9.10 Run the no-network terminal handoff and redispatch control-plane integration tests (depends: 9.8)
- [ ] 9.11 Record exact test counts, duration, and any expected skips for focused assurance (depends: 9.4-9.10)

## 10. Workflow Static And Fault Assurance

- [ ] 10.1 Parse `.github/workflows/full-extraction.yml` with a YAML 1.2-compatible parser (depends: 5, 7)
- [ ] 10.2 Run `actionlint` and resolve every workflow diagnostic (depends: 10.1)
- [ ] 10.3 Assert every third-party action remains pinned to a full commit SHA (depends: 10.1; parallel: 10.2)
- [ ] 10.4 Assert candidate upload precedes checkpoint build and no candidate updates the latest pointer (depends: 5.1)
- [ ] 10.5 Assert checkpoint upload precedes receipt verification, manifest commit, and committed-manifest upload (depends: 5.2-5.8)
- [ ] 10.6 Assert redispatch and terminal merge depend on checkpoint success and consume committed artifact outputs (depends: 5.9-5.10, 7.3)
- [ ] 10.7 Assert exact artifact-ID downloads use digest mismatch errors (depends: 5.10, 6.6)
- [ ] 10.8 Assert canonical checkpoint upload is non-overwriting and collision recovery is fail-closed (depends: 5.12-5.15)
- [ ] 10.9 Assert dispatch requests and validates exact returned run details (depends: 7.5-7.8)
- [ ] 10.10 Simulate failure immediately before checkpoint upload and prove no next pointer or child appears (depends: 5.11, 5.17)
- [ ] 10.11 Simulate failure immediately after artifact upload and before receipt commit and prove no child appears (depends: 5.17)
- [ ] 10.12 Simulate failure after manifest commit but before child acknowledgement and prove the committed state is reusable (depends: 5.17, 7.9)
- [ ] 10.13 Simulate a same-name artifact collision and prove exact receipt reuse or fail-closed behavior (depends: 5.13-5.17)
- [ ] 10.14 Simulate parent signal interruption and prove bounded exact-child cancellation (depends: 7.9-7.12)

## 11. Documentation Stewardship

- [x] 11.1 Update `README.md` full-extraction control-plane prose to distinguish semantic lane identity from attempt-local indexes (depends: 2.7)
- [x] 11.2 Document candidate, built, uploaded/verified, and committed checkpoint states in `README.md` (depends: 5.8)
- [x] 11.3 Document exact artifact-ID restore, immutable collision handling, and bounded legacy migration in `README.md` (depends: 5.12-5.15, 6.8-6.10)
- [x] 11.4 Document exact returned-run redispatch and cleanup semantics in `README.md` (depends: 7.10)
- [x] 11.5 Document response-contract circuit accounting and its non-effect on required coverage in `README.md` (depends: 8.8-8.12, 8.19)
- [x] 11.6 Reconcile the root `AGENTS.md` full-extraction contract with the implemented transaction and dispatch behavior (depends: 11.1-11.5)
- [x] 11.7 Search for nested `AGENTS.md` files governing workflow, orchestration, tests, and docs and update only those whose contract changed (depends: 11.6)
- [x] 11.8 Update authored operator docs for recovery, smoke, full extraction, terminal assurance, and Kaggle handoff (depends: 11.2-11.5)
- [x] 11.9 Regenerate only repository-declared generated docs affected by public CLI or schema changes, if any (depends: 11.8)
- [ ] 11.10 Run docs formatting and lint checks and verify generated-doc drift is intentional (depends: 11.8-11.9)
- [ ] 11.11 Run `/docs-steward` or the available equivalent review over README, AGENTS, authored docs, and generated surfaces (depends: 11.1-11.10)

## 12. Repository-Wide Assurance

- [ ] 12.1 Recheck branch, HEAD, origin, and dirty paths and separate this change from unrelated user work (depends: 9-11)
- [ ] 12.2 Run full Ruff check over `src/` and `tests/` (depends: 9.2)
- [ ] 12.3 Run full `ty check src/` (depends: 9.3)
- [ ] 12.4 Run all unit tests with `--import-mode=importlib` and record exact count and duration (depends: 9.8)
- [ ] 12.5 Run all integration tests with `--import-mode=importlib` and record exact count and duration (depends: 9.9-9.10)
- [ ] 12.6 Run the complete test suite with `--import-mode=importlib` when unit and integration subsets are green (depends: 12.4, 12.5)
- [ ] 12.7 Run extraction-completeness with the exact pinned `nba_api` runtime contract (depends: 12.2-12.6)
- [ ] 12.8 Run full upstream docs/tools contract analysis against `nba_api 1.11.4` when the source checkout is available (depends: 12.7)
- [ ] 12.9 Run model audit, SQL lint, and any repository CI-equivalent quality gates affected by extraction output (depends: 12.6)
- [ ] 12.10 Run strict OpenSpec validation again after implementation and docs settle (depends: 11, 12.1-12.9)
- [ ] 12.11 Review the final scoped diff for secrets, unpinned actions, compatibility paths, generated churn, and unrelated changes (depends: 12.10)
- [ ] 12.12 Run a parallel subagent review of checkpoint correctness, workflow security, failure accounting, test gaps, and docs consistency (depends: 12.11)
- [ ] 12.13 Resolve every confirmed review finding and repeat its narrowest failing gate (depends: 12.12)

## 13. Atomic Integration And Exact-SHA CI

- [ ] 13.1 Partition only change-owned files from unrelated dirty-tree work (depends: 12.13)
- [ ] 13.2 Create an atomic conventional commit for stable identity and checkpoint transaction code and tests (depends: 13.1)
- [ ] 13.3 Create an atomic conventional commit for workflow transaction and exact redispatch changes and tests (depends: 13.1; after: 13.2)
- [ ] 13.4 Create an atomic conventional commit for response-contract circuit code and tests (depends: 13.1; after: 13.3)
- [ ] 13.5 Create an atomic conventional docs/OpenSpec commit (depends: 11, 12.10, 13.1; after: 13.4)
- [ ] 13.6 Re-run the repository pre-push gate on the exact commit stack (depends: 13.2-13.5)
- [ ] 13.7 Push the commits to the existing `main` branch without rewriting history (depends: 13.6)
- [ ] 13.8 Verify remote `main` equals the intended local HEAD (depends: 13.7)
- [ ] 13.9 Monitor every required GitHub Actions workflow for the exact pushed SHA (depends: 13.8)
- [ ] 13.10 Download and diagnose any failing exact-SHA job before starting network extraction (depends: 13.9)
- [ ] 13.11 Fix confirmed CI defects in new atomic commits and repeat local and exact-SHA gates (depends: 13.10)
- [ ] 13.12 Require all mandatory exact-SHA checks green with no queued or in-progress ambiguity (depends: 13.9-13.11)

## 14. Targeted VPN Transaction Smoke

- [ ] 14.1 Confirm no stale full-extraction chain can launch competing VPN or publisher jobs (depends: 13.12)
- [ ] 14.2 Confirm VPN credential source and configured tunnel capacity without exposing secrets (depends: 14.1)
- [ ] 14.3 Select one small representative manual lane with nonzero expected coverage and no known contract block (depends: 14.2)
- [ ] 14.4 Dispatch `targeted_smoke=true`, `publish=false`, `max_iterations=1`, and pipeline-failure retries disabled on the exact green SHA (depends: 14.3)
- [ ] 14.5 Monitor preflight, discovery, capacity, lane extraction, lane control, checkpoint build, receipt verification, and committed-manifest upload (depends: 14.4)
- [ ] 14.6 Verify the smoke lane's complete metadata, state receipt, DuckDB checkpoint, WAL removal, and exact coverage hash (depends: 14.5)
- [ ] 14.7 Verify the checkpoint transaction is committed and both artifact IDs and digests resolve to the exact source SHA (depends: 14.6)
- [ ] 14.8 Verify targeted smoke does not merge, redispatch, publish, or claim full-dataset assurance (depends: 14.7)
- [ ] 14.9 Diagnose and fix any smoke failure locally and through exact-SHA CI before one bounded retry (depends: 14.5-14.8)

## 15. Full Initial Extraction

- [ ] 15.1 Confirm the prior failed chain's reusable artifacts, expiration windows, and committed checkpoint status before choosing resume versus fresh start (depends: 14.7)
- [ ] 15.2 Confirm no unresolved Kaggle upload state or publisher lock can conflict with the eventual publish wave (depends: 15.1)
- [ ] 15.3 Dispatch the full initial extraction from the exact smoke-proven SHA with `publish=false` (depends: 14.7-14.9, 15.2)
- [ ] 15.4 Record chain ID, root run ID, source SHA, manifest artifact identity, network mode, capacity, and iteration budget (depends: 15.3)
- [ ] 15.5 Monitor each discovery seed for complete required scopes and immutable generation receipts (depends: 15.4)
- [ ] 15.6 Monitor each configured VPN admission gate and exact capacity marker set (depends: 15.4; parallel: 15.5)
- [ ] 15.7 Monitor matrix workload cardinality, endpoint families, calls, rows, failure classes, durable progress, and recovery pointers (depends: 15.5, 15.6)
- [ ] 15.8 Monitor response-contract circuit suppressions separately from upstream calls and confirm they remain failed outstanding coverage (depends: 15.7)
- [ ] 15.9 Verify each iteration's candidate retains the previous committed checkpoint pointer (depends: 15.7)
- [ ] 15.10 Verify each checkpoint report's actual lane inventory, coverage fingerprint, database digest, and report digest (depends: 15.9)
- [ ] 15.11 Verify each checkpoint artifact's exact ID, archive digest, size, run, source, and immutable collision outcome (depends: 15.10)
- [ ] 15.12 Verify each committed next manifest advances one generation and shifts the prior transaction intact (depends: 15.11)
- [ ] 15.13 Verify each child ID is the exact dispatch return and matches title, event, source SHA, URL, and committed manifest input (depends: 15.12)
- [ ] 15.14 Stop and diagnose on any missing artifact, predicted pointer, overwrite, digest mismatch, non-monotonic generation, ambiguous child, or coverage regression (depends: 15.9-15.13)
- [ ] 15.15 Apply only evidence-backed fixes, repeat local and exact-SHA CI gates, and resume from the latest committed receipt (depends: 15.14)
- [ ] 15.16 Continue bounded iterations until every manifest lane is durably complete or canonically contract-blocked with no missing or skipped coverage (depends: 15.5-15.15)
- [ ] 15.17 Record terminal chain, run, generation, checkpoint artifact ID/digest, complete lane inventory, calls, rows, and blocked-evidence digest (depends: 15.16)

## 16. Terminal Assurance And Kaggle Publication

- [ ] 16.1 Download the exact terminal committed manifest and checkpoint by their receipt-bound artifact IDs (depends: 15.17)
- [ ] 16.2 Run merge, transform, live snapshot, and all configured export formats without publication credentials (depends: 16.1)
- [ ] 16.3 Run `scan --fail-on error --full-publication` against the exact checkpoint report, manifest, chain, databases, and source SHA (depends: 16.2)
- [ ] 16.4 Require complete lane and blocked-evidence accounting with no missing, skipped, attestation, workload, schema, row-count, or anchor errors (depends: 16.3)
- [ ] 16.5 Verify all declared silver and gold anchors and row-preserving cardinality pairs (depends: 16.3; parallel: 16.4)
- [ ] 16.6 Build and verify the assured artifact manifest and sorted data-file SHA-256 inventory (depends: 16.4, 16.5)
- [ ] 16.7 Resolve any persisted unresolved Kaggle publication marker before authorizing a new upload (depends: 15.2, 16.6)
- [ ] 16.8 Reconfirm remote default branch equals the pinned extraction source immediately before publication (depends: 16.7)
- [ ] 16.9 Dispatch the serialized publisher with the exact assured artifact ID, archive digest, terminal report, and committed checkpoint identity (depends: 16.8)
- [ ] 16.10 Require a positive exact Kaggle dataset version and valid publication marker (depends: 16.9)
- [ ] 16.11 Page the complete exact-version resource inventory and stream SHA-256 readback for every listed resource (depends: 16.10)
- [ ] 16.12 Require the full 1,344-resource path, table, ordered-schema, row-count, and digest contract across DuckDB, SQLite, CSV, and Parquet (depends: 16.11)
- [ ] 16.13 Verify remote marker, exact version, assured manifest, terminal report, chain, source, checkpoint, coverage, and blocked-evidence parity (depends: 16.11, 16.12)
- [ ] 16.14 Persist and upload the publication receipt and reconciliation state only after exact readback succeeds (depends: 16.13)
- [ ] 16.15 Refresh checked-in metadata only as the final idempotent post-readback step and repeat exact-SHA CI if it changes (depends: 16.14)

## 17. Closeout

- [ ] 17.1 Recheck local branch, dirty tree, remote HEAD, exact-SHA CI, extraction chain, terminal assurance, and Kaggle version from live state (depends: 16.15)
- [ ] 17.2 Confirm no required jobs remain queued or in progress and no stale chain or publisher can launch later (depends: 17.1)
- [ ] 17.3 Confirm diagnostics, candidate artifacts, committed receipts, and publication records have appropriate retention and contain no secrets (depends: 17.2)
- [ ] 17.4 Record exact validation commands, test counts, commits, run IDs, job IDs, artifact IDs/digests, chain generation, Kaggle version, and resource count (depends: 17.1-17.3)
- [ ] 17.5 Archive or close the OpenSpec change only after every normative capability and live gate is evidenced (depends: 17.4)
