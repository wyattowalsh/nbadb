Checked tasks are present in the current working tree. They are not a substitute
for the still-open validation, CI, smoke, extraction, and publication gates.
Tasks are ordered by dependency; tasks with the same `depends` set are safe
parallel subagent leaves unless they name the same file.

Review follow-up (2026-08-04): tasks marked incomplete below were reopened
because the integrated adversarial review found contradictions in workflow
source provenance, publication resolution ownership, or their prior assurance
evidence. Previously recorded passing counts remain historical only.

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
- [x] 1.10 Reconcile user choice B and accepted facts 03-08/12-20 into proposal, design, tasks, and capability specs; run current strict validation without claiming implementation or live proof (depends: 1.9)

## 2. Stable Lane Identity

- [x] 2.1 Define stable lane coverage identity as exact `lane_id` plus lowercase SHA-256 `coverage_units_hash` (depends: 1.6)
- [x] 2.2 Canonically sort stable lane identities before computing the lane-inventory digest (depends: 2.1)
- [x] 2.3 Exclude `lane_index`, planned wave, scheduling priority, queue class, and execution slot from durable coverage identity (depends: 2.1)
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
- [x] 5.17 Add tests for failures at candidate, build, upload, receipt, commit, and committed-manifest upload boundaries proving the prior pointer remains authoritative (depends: 5.11-5.16)

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
- [x] 6.11 Add tests for expired artifact ID, REST digest mismatch, workflow-run mismatch, source-SHA mismatch, and size mismatch (depends: 6.5-6.7)
- [x] 6.12 Add tests proving transaction-absent legacy restore is accepted once and malformed transaction fallback is rejected (depends: 6.8-6.10)
- [x] 6.13 Add a test proving a same-name newer artifact cannot replace the exact committed artifact ID (depends: 5.12-5.15, 6.4)

## 7. Exact Self-Redispatch

- [x] 7.1 Align the exact-title child precheck with the explicit replaceable allowlist of completed `failure`, `cancelled`, `timed_out`, or `action_required` runs (depends: 1.7)
- [x] 7.2 Retain source checkout, trusted-branch ancestry, publish ancestry, and workflow-blob equality gates (depends: 1.7)
- [x] 7.3 Make redispatch consume the committed next-manifest artifact name rather than the lane-control candidate (depends: 5.8)
- [x] 7.4 Build the complete child input payload with fixed chain, source, manifest, iteration, budget, network, chunk, and publication fields (depends: 7.2, 7.3)
- [x] 7.5 Post workflow dispatch with a body containing exactly `{ref, inputs}` and no removed `return_run_details` field (depends: 7.4)
- [x] 7.6 Parse and validate the positive returned run ID, API URL, and HTML URL (depends: 7.5)
- [x] 7.7 Read that exact run with bounded retries and validate title, event, head SHA, ID, and URL (depends: 7.6)
- [x] 7.8 Expose the exact acknowledged child ID and URL as outputs and summary evidence (depends: 7.7)
- [x] 7.9 Install exit and signal traps before dispatch and cancel the exact returned child when acknowledgement fails (depends: 7.5)
- [x] 7.10 Limit inventory-difference fallback to cancellation when dispatch may exist but its response was not parseable (depends: 7.9)
- [x] 7.11 Replace the stale dispatch static test with exact `{ref, inputs}` body, returned-ID parsing, exact-run GET, and provenance assertions (depends: 7.5-7.8)
- [x] 7.12 Add mocked API tests for the exact child-history allowlist, malformed response, unreadable exact child, wrong title, wrong event, wrong SHA, wrong URL, and interrupted acknowledgement (depends: 7.6-7.10)
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
- [x] 8.18 Add a resume test proving suppressed params remain absent from completed journal coverage (depends: 8.8-8.12)
- [x] 8.19 Add metrics or structured summary counts for upstream attempts, circuit suppressions, signature, and preserved outstanding calls (depends: 8.8)

## 8A. NBA Stats Probe Header Contract

- [x] 8A.1 Reproduce the targeted-smoke TeamYears timeout with the connector's reduced header set
- [x] 8A.2 Prove the same endpoint and host return a valid TeamYears response with pinned `nba_api 1.11.4` `STATS_HEADERS` (depends: 8A.1)
- [x] 8A.3 Replace the connector subset with the exact pinned runtime header contract (depends: 8A.2)
- [x] 8A.4 Add a unit test that imports `STATS_HEADERS` and requires exact connector parity (depends: 8A.3)
- [x] 8A.5 Assert the generated curl command sends every contract header in canonical order (depends: 8A.3)
- [x] 8A.6 Derive the public `NBA_HEADERS` copy from the pinned runtime and test export parity (depends: 8A.3)
- [x] 8A.7 Run focused connector/core tests, Ruff, `ty`, and the direct live canary comparison (depends: 8A.4-8A.6)
- [x] 8A.8 Update `README.md`, root `AGENTS.md`, and the troubleshooting playbook with the atomic header-parity invariant (depends: 8A.6)
- [x] 8A.9 Run strict OpenSpec validation and scoped docs formatting/lint after the documentation settles (depends: 8A.7-8A.8)
- [ ] 8A.10 Run exact-SHA CI on the atomic header-contract commit (depends: 8A.9)
- [ ] 8A.11 Run a fresh one-lane strictly-free direct smoke on that exact green SHA with runner-local TeamYears and installed-stack canaries (depends: 8A.10, 8E.7)
- [x] 8A.12 Add a secret-safe root exception type to installed-stack failure attestations and connector diagnostics with root-first transport/contract classification and outer fallback
- [x] 8A.13 Give installed-stack endpoint requests bounded timeouts and a bounded child budget while retaining the attempt, connector, and finalization caps (depends: 8A.12)
- [x] 8A.14 Add wrapped-timeout, wrapped-contract, surfaced-root, malformed-root fallback, message-exclusion, sequential-budget, and constrained-budget regression coverage (depends: 8A.12-8A.13)
- [x] 8A.15 Run focused Ruff, format, type, pytest, action metadata, and strict OpenSpec validation (depends: 8A.14)
- [x] 8A.16 Update root agent policy and the operator troubleshooting playbook, then run scoped docs formatting and lint (depends: 8A.15)
- [ ] 8A.17 Run exact-SHA CI for the installed-stack probe refinement (depends: 8A.16)
- [ ] 8A.18 Run a bounded strictly-free direct smoke with expiring runner-local canary receipts on the refined exact-green SHA before launching a new full-model chain (depends: 8A.17, 8E.7)

## 8B. Receipt-Bound Discovery Recovery

- [x] 8B.1 Record same-run artifact replacement as a distinct recovery-boundary defect
- [x] 8B.2 Specify all-job attempt validation, cross-run recovery, exact receipt selection, stable duplicate admission, and fail-closed restored-layout scenarios (depends: 8B.1)
- [x] 8B.3 Add one stdlib-only repository validator shared by every full-extraction job (depends: 8B.2)
- [x] 8B.4 Validate current run ID and run attempt as positive non-boolean integers (depends: 8B.3)
- [x] 8B.5 Export only inline-manifest presence to the shared environment instead of the raw manifest JSON (depends: 8B.3)
- [x] 8B.6 Accept exactly one first-attempt mode: fresh, inline, lane source, or resume source (depends: 8B.4, 8B.5)
- [x] 8B.7 Reject mixed modes, orphan artifact metadata, asymmetric ID/digest receipts, and malformed digests (depends: 8B.6)
- [x] 8B.8 Require source IDs to be positive, distinct from the current run, and bound to an explicit chain identity (depends: 8B.6)
- [x] 8B.9 Define primary, generic partial, publication-reconcile, and dispatch-reconcile roles (depends: 8B.3)
- [x] 8B.10 Reject primary and generic partial attempts above one before querying duplicate history (depends: 8B.9)
- [x] 8B.11 Permit only the publish job to use publication reconciliation on a later attempt (depends: 8B.9, 8B.10)
- [x] 8B.12 Permit only the dispatch job to use dispatch reconciliation on a later attempt (depends: 8B.9, 8B.10)
- [x] 8B.13 Install exact source, expected title, source receipt, and inline-presence environment fields at workflow scope (depends: 8B.5-8B.8)
- [x] 8B.14 Give all 15 jobs read access to Actions metadata (depends: 8B.3)
- [x] 8B.15 Check out the exact pinned SHA and run the shared validator before side effects in all 15 jobs (depends: 8B.13, 8B.14)
- [x] 8B.16 Add checkout and shared validation to targeted-smoke assurance (depends: 8B.15)
- [x] 8B.17 Preserve only the extract job's mandatory deadline initialization before checkout (depends: 8B.15)
- [x] 8B.18 Serialize primary admission with a chain-and-iteration job concurrency key using `queue: max` and `cancel-in-progress: false` (depends: 8B.9)
- [x] 8B.19 Observe exact-workflow history three times through complete unfiltered pagination without a result-capping search parameter (depends: 8B.3, 8B.18)
- [x] 8B.20 Require stable page totals, exact row counts, unique positive run IDs, and valid local event fields per history observation (depends: 8B.19)
- [x] 8B.21 Require the final two normalized unfiltered history observations to match exactly and filter dispatch events only afterward (depends: 8B.20)
- [x] 8B.22 Permit only completed `failure`, `cancelled`, `timed_out`, or `action_required` exact-title dispatch predecessors (depends: 8B.21)
- [x] 8B.23 Validate the discovery source run's completion, executed-conclusion allowlist, repository, dispatch event, trusted branch, exact workflow path/ID, run ID, attempt, producing head `H`, and semantic `S == H` or `S`-ancestor-`H` plus identical workflow bytes (depends: 8B.8)
- [x] 8B.24 Observe the source run's complete artifact inventory three times and require the final two normalized snapshots to match (depends: 8B.23)
- [x] 8B.25 Prefer one unexpired canonical discovery artifact or accept one unique exact source-attempt-one recovery artifact (depends: 8B.24)
- [x] 8B.26 Directly re-read the selected artifact ID and require exact normalized receipt equality (depends: 8B.25)
- [x] 8B.27 Download the selected artifact by exact ID and source run with archive digest mismatch configured as an error (depends: 8B.26)
- [x] 8B.28 Reject symlinks, duplicate managed members, duplicate relevant basenames, and ambiguous discovery layouts before copying (depends: 8B.27)
- [x] 8B.29 Require canonical restore to contain exactly one discovery directory, summary, workload pointer, and workload generation (depends: 8B.28)
- [x] 8B.30 Verify canonical workload integrity and permit only provenance-valid recovery bundles to discard and reseed incomplete workload state (depends: 8B.29)
- [x] 8B.31 Parse dispatch reconciliation's exact committed-manifest name and accept only current-run, exact-next-iteration artifacts produced by attempt one (depends: 8B.12)
- [x] 8B.32 Require an attempt-one committed-manifest receipt and producing head, allow a later current run attempt only through the dedicated non-mutating dispatch-reconciliation role, retain the pinned semantic source separately, and directly verify artifact REST identity without synthesizing another artifact name (depends: 8B.31)
- [x] 8B.33 Add structural tests for all-job permissions, exact checkout, validator ordering, roles, and non-replacing guard concurrency (depends: 8B.14-8B.18)
- [x] 8B.34 Add validator tests for every valid first-attempt mode and invalid mixed, orphan, malformed, self-source, and later-attempt mode (depends: 8B.4-8B.12)
- [x] 8B.35 Add duplicate-admission tests for unfiltered pagination beyond 1,000 rows, local event selection, stability, malformed inventories, and every replaceable or blocking status/conclusion (depends: 8B.19-8B.22)
- [x] 8B.36 Add discovery-receipt tests for `S=H`, safe descendant `H`, unrelated history, workflow-byte drift, owner-field mutations, executed and non-executed conclusions, stable snapshots, exact selection, direct recheck, and pinned REST headers (depends: 8B.23-8B.27)
- [x] 8B.37 Add restore tests for exact layout, canonical/recovery completeness, real workload integrity, symlinks, and duplicate candidates (depends: 8B.28-8B.30)
- [x] 8B.38 Add dispatch tests for exact child-history allowlisting, attempt-one receipt reuse from a dedicated later reconciliation attempt, semantic/producing identity separation, and later-produced artifact, wrong-run, wrong-iteration, source, owner, role, or REST mismatch rejection (depends: 8B.31, 8B.32)
- [x] 8B.39 Run the focused receipt-recovery workflow tests and record exact passing counts (depends: 8B.33-8B.38)
- [x] 8B.40 Run the complete full-extraction workflow contract test file and record exact passing counts (depends: 8B.39)
- [x] 8B.41 Run Ruff format/lint, YAML parsing, `actionlint`, latest GitHub REST version assertions, strict OpenSpec validation, and scoped diff checks (depends: 8B.40)
- [ ] 8B.42 Prove cross-run canonical and recovery restores in exact-SHA CI before another network extraction (depends: 8B.41)
- [ ] 8B.43 Prove publication-only and dispatch-only reconciliation against immutable receipts in exact-SHA CI (depends: 8B.42)
- [ ] 8B.44 Add an automatic replacement-run dispatcher only through a separate reviewed transaction design; the current change intentionally fails closed (depends: 8B.42)
- [x] 8B.45 Bind exact lane-manifest and resume-source artifacts to owner run/head `H`, preserve semantic source `S`, and require repository/event/branch/workflow/run/attempt/state plus ancestry and workflow-byte attestation before artifact use (depends: 8B.23)
- [x] 8B.46 Resolve resume manifests from a stable complete inventory, require one unique exact-attempt-one committed receipt, bind canonical fallback to exact ID, and eliminate name-only resume download (depends: 8B.45)
- [x] 8B.47 Upgrade the bounded legacy lane handoff through semantic-source/producing-owner attestation, exact-name stable inventory, and direct selected-ID recheck (depends: 8B.45)
- [x] 8B.48 Download the upgraded legacy artifact by exact ID and enforce optional REST digest, safe ZIP layout, expected member name, and exactly one regular manifest (depends: 8B.47)
- [x] 8B.49 Prove every non-guard workflow job contains `workflow_guard` in its transitive dependency closure (depends: 8B.15)
- [x] 8B.50 Add focused negative tests for unrelated owners, workflow-byte drift, every owner-field mutation, malformed or numeric expiry, inventory ambiguity, direct-ID drift, digest mismatch, symlinks, special paths, and multiple or wrong manifest members (depends: 8B.45-8B.49)
- [x] 8B.51 Rerun the complete workflow contract, Ruff, YAML, `actionlint`, `ty`, and strict OpenSpec gates after legacy and resume hardening (depends: 8B.50)
- [x] 8B.52 Complete an initial independent adversarial review of every recovery and handoff path and record every actionable finding for the follow-up wave (after: initial 8B.41 assurance; opens: 8B.53-8B.60)
- [x] 8B.53 Consume every cross-run source attestation as a strict schema-versioned snapshot, require exact repository/workflow/event/branch/run/attempt-one/state/semantic-source/producing-head equality, and repeat that complete owner read after inventory/direct-ID selection immediately before artifact use (depends: 8B.52)
- [x] 8B.54 Replace resume lane-metadata, durable lane-state, checkpoint lane/database, checkpoint lane-metadata, checkpoint discovery, and transaction-absent legacy checkpoint run/name restores with stable complete inventory selection, direct positive-ID rechecks, and digest-bound exact-ID downloads (depends: 8B.53)
- [x] 8B.55 Carry each lane state's GitHub artifact ID and archive digest independently from its DuckDB database SHA-256 through the durable lane model, manifests, matrix contract, restore validation, and checkpoint merge (depends: 8B.54)
- [x] 8B.56 Require every historical artifact consumer to use the shared attestation and normalized receipt helpers, perform final owner validation before artifact access, reject all residual run/name download authority, and preserve exact semantic-source versus producing-head commitments through checkpoint merge (depends: 8B.53-8B.55)
- [x] 8B.57 Add sequenced mutation tests for discarded-attestation/rerun races before and after inventory/direct-ID reads, downstream attempt two, missing or mismatched `H`, malformed or unstable receipts, duplicate IDs/names, direct-ID drift, archive-versus-database digest confusion, and zero artifact calls after owner drift (depends: 8B.54-8B.56)
- [x] 8B.58 Run helper, control-plane, workflow-contract, YAML, `actionlint`, Ruff, `ty`, strict OpenSpec, and scoped diff gates for the adversarial provenance follow-up and record exact results (depends: 8B.57)
- [x] 8B.59 Reconcile README, root AGENTS, troubleshooting, pipeline-flow, Kaggle setup, and CLI reference with the consumed-attestation, historical-lane-receipt, current-terminal-authority, safe-archive, and verify-before-download contracts (depends: 8B.54-8B.58, 8C.35-8C.38, 8D.8-8D.9)
- [x] 8B.60 Complete an independent read-only re-review of every original provenance finding and resolve all surviving actionable findings (depends: 8B.58, 8B.59, 8C.36-8C.38, 8D.9)

## 8C. Durable Kaggle Publication Intent

- [x] 8C.1 Research the current GitHub Deployment/status API, retention behavior, and bounded-inventory constraints from official sources
- [x] 8C.2 Specify mandatory durable intent, fixed-cost inventory, timestamp chronology, executor admission, claim, retention, remote evidence, and frozen-source scenarios (depends: 8C.1)
- [x] 8C.3 Define one canonical source-and-bundle identity shared by the CLI, client, ledger, workflow, and terminal receipt (depends: 8C.2)
- [x] 8C.4 Validate required GitHub Actions repository, workflow, run, attempt, job, actor, source, and token environment, then fully paginate and directly verify the unique job receipt before a ledger write (depends: 8C.3)
- [x] 8C.5 Verify the exact workflow definition bytes and the repository-owned `queue: max` non-cancelling publisher mutex (depends: 8C.4)
- [x] 8C.6 Select the two newest matching deployments through GraphQL `CREATED_AT DESC`, directly revalidate both REST IDs, and bound status reads and stability to three observations (depends: 8C.2)
- [x] 8C.7 Order publication intent and status chronology by parsed `created_at` rather than numeric IDs or undocumented REST status order (depends: 8C.6)
- [x] 8C.8 Create one immutable pending intent and directly re-read its exact deployment ID (depends: 8C.3-8C.7)
- [x] 8C.9 Recover an ambiguous deployment creation only through exact bounded inventory evidence and prohibit a blind second POST (depends: 8C.8)
- [x] 8C.10 Claim only the exact pending intent with a unique nonce, current executor identity, and `in_progress` status (depends: 8C.4, 8C.8)
- [x] 8C.11 Recover an ambiguous claim-status write through exact status evidence and prohibit a blind second POST (depends: 8C.10)
- [x] 8C.12 Keep claim validation textually and behaviorally adjacent to the single Kaggle upload call (depends: 8C.10, 8C.11)
- [x] 8C.13 Revalidate the frozen bundle identity immediately before preparing the upload (depends: 8C.3)
- [x] 8C.14 Require the approved default-branch head before intent creation and immediately before and after claim admission (depends: 8C.4, 8C.12)
- [x] 8C.15 Write a terminal success status only for the fresh exact current executor after exact remote verification, deployment-origin/claim/nonce revalidation, and an immediate pre-POST executor recheck (depends: 8C.12)
- [x] 8C.16 Validate a retained terminal success when GitHub has deleted its preceding claim status (depends: 8C.15)
- [x] 8C.17 Require the exact Kaggle marker, positive version, complete inventory, and streamed digest readback before ledger success (depends: 8C.15)
- [x] 8C.18 Persist local publication state only as a secondary diagnostic and fail closed on unresolved durable or remote evidence (depends: 8C.16, 8C.17)
- [x] 8C.19 Add CLI switches for the GitHub Deployment ledger and mandatory durable-intent enforcement (depends: 8C.18)
- [x] 8C.20 Wire daily publication to the durable ledger, exact frozen-source head, and shared publisher mutex (depends: 8C.19)
- [x] 8C.21 Wire monthly publication to the durable ledger, exact frozen-source head, and shared publisher mutex (depends: 8C.19)
- [x] 8C.22 Wire full-extraction publication to the durable ledger and the approved pinned-source or exact metadata-child head (depends: 8C.19)
- [x] 8C.23 Prove a 103-publication history uses exactly 32 GitHub API requests and never scans beyond the bounded head (depends: 8C.6)
- [x] 8C.24 Prove retained terminal success validates after prior statuses are deleted (depends: 8C.16)
- [x] 8C.25 Test GraphQL head ordering, locally sorted status receipts, timestamp chronology, dynamic run names, cross-workflow history, paginated direct-job admission, pending parent runs, canonical Git-ref URLs, workflow-byte drift, mutex drift, every execution-owner field, deployment-origin drift, overlapping claims, final pre-POST executor drift, and default-head time-of-check/time-of-use failures (depends: 8C.4-8C.15)
- [x] 8C.26 Test ambiguous deployment and status writes, exact read recovery, client integration, and unresolved-intent blocking (depends: 8C.8-8C.18)
- [x] 8C.27 Run Ruff, `ty`, focused pytest, workflow YAML parsing, `actionlint`, strict OpenSpec, and scoped diff checks (depends: 8C.19-8C.26)
- [x] 8C.28 Complete an independent adversarial review and resolve every actionable finding (depends: 8C.27)
- [ ] 8C.29 Prove all three production publisher paths in exact-SHA CI (depends: 8C.28)
- [ ] 8C.30 Publish or reconcile one exact assured full bundle and retain the durable terminal receipt (depends: 8C.29)
- [x] 8C.31 Restrict publication-state cache restoration to `nbadb-kaggle-publication-state-${run_id}-` (depends: 8C.18)
- [ ] 8C.32 Admit a new zero-active publication replay only before durable intent and require exact same-run publisher-job reconciliation after pending or in-progress intent (depends: 8C.10-8C.18, 8C.31)
- [ ] 8C.33 Prove same-run reconciliation skips Kaggle after exact remote and ledger success but resumes failed metadata follow-up (depends: 8C.32)
- [ ] 8C.34 Resolve metadata head `M`, explicitly dispatch CI for a distinct direct metadata-only child, directly verify `head_sha=M`, and require all six named jobs (depends: 8C.30, 8C.33)
- [x] 8C.35 Directly verify the assured-data artifact's exact current-run ID/name/archive digest/size/unexpired/archive URL/producing-attempt-one/`GITHUB_SHA` receipt, allow a later current owner attempt only in the dedicated same-run publication-reconciliation role, and repeat the complete owner read before requesting archive bytes (depends: 8C.22)
- [x] 8C.36 Add call-order and mutation tests proving no assured archive request occurs before receipt and final owner verification, a dedicated later publication-reconciliation attempt can reuse only the attempt-one artifact, and no mismatched current head, producing attempt, role, URL, digest, size, or direct-ID receipt reaches extraction (depends: 8C.35)
- [x] 8C.37 Validate the complete assured ZIP layout before extraction and reject empty archives, duplicate normalized members, absolute or traversing paths, symlinks, special files, and destination collisions while retaining streamed size/digest verification (depends: 8C.35)
- [x] 8C.38 Add adversarial assured-archive fixtures for every unsafe member class and prove no archive member is consumed until the complete layout passes (depends: 8C.37)

## 8D. Receipt-Bound Terminal Replay

- [x] 8D.1 Make the plan job select one exact source manifest receipt from stable complete inventory and directly verify ID/name/digest/size/expiry, owner run/head `H`, workflow, semantic source `S`, ancestry/workflow-byte attestation, and chain
- [x] 8D.2 Bundle `resume-source-input-manifest.json` and schema-v1 `resume-source-selection.json` with exact member and source receipts (depends: 8D.1)
- [x] 8D.3 Upload and directly verify the current plan artifact against its exact attempt-one owner run and `GITHUB_SHA`, perform a final owner re-read after the artifact receipt, retain semantic selected-source fields separately, and expose the exact receipt as job outputs (depends: 8D.2)
- [x] 8D.4 Make terminal replay download only that plan artifact ID, validate the selection receipt, and consume the bundled manifest bytes (depends: 8D.3)
- [x] 8D.5 Remove terminal replay's duplicate artifact inventory selector and every name- or attempt-ranked source fallback (depends: 8D.4)
- [x] 8D.6 Resolve a committed checkpoint only by its exact transaction receipt and permit transaction-absent replay only through the existing exact-run-ID attested rebuild (depends: 8D.4)
- [x] 8D.7 Add positive and negative tests for plan/source identity, member hash and layout, expiry, same-name drift, malformed transactions, candidates, and exact rebuild inventory (depends: 8D.5, 8D.6)
- [x] 8D.8 Directly verify committed-next-manifest and terminal-replay-output uploads against exact current-run ID/name/archive digest/size/unexpired/archive URL/attempt-one/`GITHUB_SHA` receipts, repeat the complete owner read after artifact verification, pass those receipts to terminal merge, and download only their exact IDs (depends: 8D.3-8D.6)
- [x] 8D.9 Add omitted-receipt, current-head, later-attempt, post-receipt owner-drift, same-name-substitution, direct-ID-drift, archive-digest, zero-artifact-after-owner-drift, and verifier-before-download tests for both merge authorities (depends: 8D.8)

## 8E. Strictly-Free Execution Admission

- [x] 8E.1 Add a backend-neutral pre-publication validator for lane count, configured slot count, unique lane IDs, complete rows, and integer assignments
- [x] 8E.2 Enforce contiguous used slots, `ceil(N/S)` capacity, and maximum used-slot count difference of one (depends: 8E.1)
- [x] 8E.3 Preserve deterministic round-robin assignment and per-slot `queue: max` without treating a slot as network or free-capacity authority (depends: 8E.2)
- [x] 8E.4 Exhaustively test `N=0..256` and `S=1..64`, including `64/6 = 11,11,11,11,10,10` and seeded invalid assignments (depends: 8E.1-8E.3)
- [ ] 8E.5 Define exact-key `FreeExecutionAdmissionV1` and post-run usage receipts binding authenticated platform execution context, direct job/run receipts, source/workflow SHA, standard runner class, recursive resource plan, artifact/cache/storage allowance and liability, observation/expiry, exact capacity, and zero cost at point of use; reject free-form pricing and self-resealed/caller-projected authority (depends: 8E.1-8E.4)
- [ ] 8E.5a Define an authenticated job-to-artifact authority and receipt-bound ledger restore root; artifact run ownership or caller-authored checkpoint state alone must never create positive admission (depends: 8E.5)
- [ ] 8E.5b Define single-use per-operation authorization bound to exact context, slot, lane, endpoint, canonical URL/path, parameter/body identity, ordinal, and issued nonce, with replay/reseal/widening regressions (depends: 8E.5-8E.5a)
- [ ] 8E.6 Remove Nord, paid VPN/proxy/token credentials, actions, defaults, and fallback reachability from every production initial/catch-up/daily/monthly/opportunistic path while retaining only explicitly non-production diagnostic history (depends: 8E.5)
- [ ] 8E.7 Run GitHub, strict TeamYears, installed `common_all_players`, and installed `league_game_log` canaries on every actual runner, bind expiring receipts, and recheck immediately before its first provider call (depends: 8A.12-8A.16, 8E.5-8E.6)
- [ ] 8E.8 Emit `capacity_blocked` before provider work for missing/stale/ambiguous/nonzero eligibility, canary drift, or insufficient exact capacity; never shrink or rebase the request universe (depends: 8E.5-8E.7)
- [ ] 8E.9 Require causally ordered exact post-run zero-cost usage readback for compute plus artifact/cache/package/custom-image storage and retention before assurance or publication; add missing, predecessor-reversal, billing-owner, cross-period, drifted, allowance-overrun, and nonzero tests (depends: 8E.5b, 8E.8)
- [ ] 8E.10 Coalesce daily and opportunistic demand under one non-cancelling generation, advance desired cutoff monotonically, and emit durable `fresh`, `not_fresh`, or `capacity_blocked` receipts (depends: 8E.5-8E.9)
- [ ] 8E.11 Add workflow-static and behavioral tests proving no production Nord/paid path, no runner-label or free-text cost inference, authenticated job/artifact identity, recursive resource closure, exact single-use operation authority, runner-local canaries, exact capacity, storage-liability coverage, mid-run expiry handling, unchanged coverage, causal post-run readback, and trigger coalescing (depends: 8E.5-8E.10)

## 8F. Box-Score-Hustle Incident Gate

- [ ] 8F.1 Freeze run `30511585896`, target `0024800300`, control games, unchanged progress counts/fingerprint, exception classes, and exact artifact receipts as diagnostic-only evidence
- [ ] 8F.2 With separate explicit authority and a valid strictly-free admission, run target plus both controls through independently admitted direct runner observations with zero in-call retries and a bounded total call count; remain blocked if qualifying free capacity is unproven (depends: 8F.1, 8E.7)
- [ ] 8F.3 Record only allowlisted failure metadata and no unrestricted failure bodies, parameters, messages, or credentials; any successful body-bearing control/target observation must use the mandatory public parser-input body authority (depends: 8F.2)
- [ ] 8F.4 Route valid JSON to a narrow parser fixture/fix, transient evidence to transport classification or bounded retry, valid empty to zero-row success, and repeatable target-only unsupported evidence to a parameter-scoped support rule (depends: 8F.3)
- [ ] 8F.5 Stop on ambiguous evidence; never reset the safety cap, fabricate success, or exclude the full lane, season range, or unrelated games (depends: 8F.3)
- [ ] 8F.6 Add regression tests for the selected non-ambiguous evidence branch and repeat focused extraction assurance before source freeze (depends: 8F.4; blocked by: 8F.5)

## 8G. Exact Provider-Owned Request Universe

- [ ] 8G.1 Resolve the latest authoritative `nba_api` release/source before source freeze; atomically update the exact pin plus runtime/docs/tools, headers, endpoint/schema/route/model contracts when newer, then freeze those inputs and the source SHA for RequestUniverse generation
- [ ] 8G.2 Define exact-key RequestUniverse generation, request identity, dependency edge, closure round, shard, terminal disposition, and independent-verifier receipts (depends: 8G.1)
- [ ] 8G.3 Generate seed requests from exact bounded provider/repository contracts and reject default-inferred or guessed parameter values (depends: 8G.2)
- [ ] 8G.4 Feed typed provider-owned game/player/team/season and sparse dependent identities into closure rounds until one complete round adds none (depends: 8G.3)
- [ ] 8G.5 Keep unsupported comparison endpoints explicit as `contract_not_modeled_yet`; prohibit every Cartesian player/team/opponent/lineup fan-out (depends: 8G.3-8G.4)
- [ ] 8G.6 Independently recompute the least fixed point and reject missing, extra, duplicate, overlapping, guessed, or dependency-orphan requests (depends: 8G.4-8G.5)
- [ ] 8G.7 Partition the immutable universe into bounded disjoint exhaustive physical shards whose scheduling/index/slot changes cannot alter logical identity (depends: 8G.6)
- [ ] 8G.8 Require each invocation to end only nonempty, evidence-backed present-empty, or narrowly evidenced unavailable/blocked; keep skipped/unattempted/suppressed/unknown/failed work unresolved (depends: 8G.6)
- [ ] 8G.9 Wire full extraction planning, discovery, dependent workload generation, lane manifests, and runner dispatch to the independently verified universe rather than the ordinary plan-derived synthetic closure (depends: 8G.6-8G.8)
- [ ] 8G.10 Add property/fault/workflow tests for multi-round closure, sparse dependencies, no Cartesian fan-out, all-period coverage, shard permutation/balance, exact terminal states, and plan-versus-universe mismatch (depends: 8G.2-8G.9)

## 8H. Public Observation, Field Fate, And Temporal Authority

- [ ] 8H.1 Define public-safe content-addressed parser-input objects, logical occurrence receipts, and explicit typed bodyless dispositions with secret-safety classifications (depends: 8G.2)
- [ ] 8H.1a Freeze `PublicValueAuthorityV1` as a separate version/digest domain layered on exact-four Raw Authority V2; define strict mandatory base schemas named `raw_nba_api_result_cell`, `raw_nba_api_stats_lossless_record`, `raw_nba_api_live_lossless_node`, `raw_nba_api_value_representation`, `raw_nba_api_route_field_landing`, and `raw_nba_api_w2_operation` without compatibility projections (depends: 8H.1)
- [ ] 8H.1b Persist/read back exact `DeclaredBodylessPacketV1` bytes and `DeclaredBodylessPacketReadbackReceiptV1` outside exact-four Raw Authority V2; reject digest-only evidence, private-cache substitution, corruption, and foreign observation binding (depends: 8H.1a)
- [ ] 8H.1c Emit mandatory stats-lossless and live-lossless public authorities, including live-node rows for selected live observations with no conditional drift route (depends: 8H.1a)
- [ ] 8H.1d Emit one exhaustive `LosslessOwnershipReceiptV1` per selected stats/live observation with exact decoded-record ownership, zero-record occurrence partitions, and explicit zero-residual proof (depends: 8H.1c)
- [ ] 8H.1e Independently derive every selected result-occurrence unit plus at most one residual/fixed-zero response unit and require exactly one canonical `ValueRepresentationAssignmentV1` with no missing, extra, duplicate, reordered, dual, or cross-observation unit (depends: 8H.1b-8H.1d)
- [ ] 8H.1f Freeze the closed `rectangular_result_cells_v1|stats_lossless_records_v1|live_lossless_nodes_v1|response_lossless_records_v1|response_fixed_zero_v1` representation domain and orthogonal `parser_input_body|declared_bodyless_packet` source-input domain (depends: 8H.1a)
- [ ] 8H.2 Persist/read back exact successful parser-input bytes or bodyless packet authority before parser-derived staging becomes accepted; commit staging only as a recoverable candidate until exact W2 closure and never publish unrestricted failure bodies (depends: 8H.1-8H.1f)
- [ ] 8H.3 Carry request/result-set/field/ordinal/type/body/observation and exact representation provenance losslessly through raw capture, staging candidates, journals, lane state, restore, and copy-plus-delta merge (depends: 8H.2)
- [ ] 8H.3a Independently emit `BodyValueProjectionReceiptV1` and strict `PublicTableValueProjectionReceiptV1`, then seal `ValueProjectionEqualityReceiptV1` over exact built-in-type/cardinality/order/path/ordinal/value/presence equality; forbid production parser/staging imports and receipt-embedded source values in the table verifier (depends: 8H.1e-8H.3)
- [ ] 8H.3b Build one idempotent `W2OperationReceiptV1` per finalized logical bundle over raw/body/ownership/representation/pre-operation-table/staging-readback/field-fate/conditional/live-plan/route-field/verifier/resource roots, bind all six schemas but exclude its own W2 row/table root, then persist/read back `W2OperationPersistenceReceiptV1` before request closure or journal success (depends: 8H.3a)
- [ ] 8H.4 Define per-field parameter-period and event-time applicability, earliest/latest evidence, internal gaps, observation window, evidence class, and revalidation policy without fallback guesses (depends: 8G.1)
- [ ] 8H.5 Evaluate every supported period independently for each field and distinguish not-applicable, observed-present, evidence-backed present-empty, evidenced unavailable, and unresolved gap states (depends: 8H.4)
- [ ] 8H.6 Land every additive/unknown result set and field in exact public value authority and typed lossless staging; permit journal success only after W2 conservation while atomically blocking MODEL-GREEN and full publication on unclassified fate/type/key/lineage/temporal evidence (depends: 8H.3b-8H.5)
- [ ] 8H.7 Complete field-fate and stable-model review for every observed field, including explicit curated inclusion/exclusion and metric/experiment disposition (depends: 8H.6)
- [ ] 8H.8 Add deterministic secret, exact-byte/digest/ordinal, bodyless, failure-body, field-gap, and additive-drift tests plus hostile rectangular-looking fallback, ragged/non-sequence/missing result, duplicate name/header, hybrid response residual, fixed-zero, no-drift live-node, omitted/dual/reordered/foreign assignment, table-verifier body access, receipt-value self-attestation, hostile equality/bool-int, resource preflight, partial commit, collision, and MODEL-GREEN false-green cases (depends: 8H.1-8H.7)

## 8I. Authority-Bound Checkpoints And Fresh Cutover

- [ ] 8I.1 Define a canonical semantic diff over provider/runtime, endpoint/result-set, parameters, dependencies, requests, ordered fields, types, keys/meaning, routes, public value representation/schema/denominator/reconstruction rules, model lineage, and field-temporal authority (depends: 8G.6, 8H.7)
- [ ] 8I.2 Require fresh full for the initial W2 cutover and every identity/removal/reinterpretation/new model/representation kind/expected-unit/exactly-one/schema/reconstruction change with no compatibility projection; permit bounded delta only for a fully identified meaning-preserving additive change under unchanged W2 authority (depends: 8I.1)
- [ ] 8I.3 Extend checkpoint build and receipt schemas to bind RequestUniverse, invocation, body/bodyless, representation assignments, body/table/equality verifiers, W2 operations, result/field, field-fate, temporal, staging/journal, model, semantic-diff, and blocked-evidence digests (depends: 3, 8G.6, 8H.7)
- [ ] 8I.4 Verify associated authority receipts during lane acceptance, copy-plus-delta, upload, restore, terminal replay, and scan without weakening candidate/built/uploaded-verified/committed transitions (depends: 8I.3)
- [ ] 8I.5 Make current Kaggle data and every pre-contract checkpoint diagnostic-only for choice B; prohibit their bytes, lanes, body inventories, or pointers from satisfying new baseline coverage (depends: 8I.2-8I.4)
- [ ] 8I.6 Admit the new baseline only as fresh exact-SHA attempt one with no inline/lane/resume/checkpoint/recovery authority and permit later resume only for identical same-chain committed authority digests (depends: 8I.5)
- [ ] 8I.7 Add mutation and recovery tests for every associated digest, old-Kaggle/checkpoint and compatibility-projection rejection, exact same-chain W2 replay/resume, representation/schema/denominator drift, zero-delta conservation, and fresh-attempt-one admission (depends: 8I.3-8I.6)

## 8J. Transactional Terminal Catch-Up And Tail

- [ ] 8J.1 Define exact-key TerminalCatchup generation/component/observation-window/seal/receipt schemas and candidate/built/uploaded-verified/committed transitions (depends: 8I.3)
- [ ] 8J.2 Freeze one event-time cutoff and derive exact baseline-to-cutoff requests from the committed historical authority (depends: 8G.6, 8J.1)
- [ ] 8J.3 Execute a declared recent overlap refresh with provenance-preserving multiplicity and replacement semantics (depends: 8J.2)
- [ ] 8J.4 Independently derive and repair whole-history invocation/body/result/field/temporal holes without widening request scope (depends: 8G.6, 8H.7, 8J.2)
- [ ] 8J.5 Capture one frozen public-authority live snapshot bound to the same cutoff and generation (depends: 8H.3, 8J.2)
- [ ] 8J.6 Record per-call observation start/end, commit a final seal, reject post-seal observations, and bind all four components plus authority/database/report/artifact digests (depends: 8J.2-8J.5)
- [ ] 8J.7 Make failure at any transaction boundary resume only from the last committed exact receipt; prohibit unreceipted merge/live reuse (depends: 8J.6)
- [ ] 8J.8 Define immutable parent-bound TailGeneration transactions for post-seal data, exact overlap, semantic diff, observation window, and desired cutoff (depends: 8I.2, 8J.6)
- [ ] 8J.9 Make daily target next-day availability and emit durable `fresh`/`not_fresh`/`capacity_blocked`; coalesce opportunistic triggers through one active tail (depends: 8E.10, 8J.8)
- [ ] 8J.10 Add cutoff-boundary, overlap, whole-history hole, live-freeze, post-seal exclusion, crash/retry, parent immutability, authority-drift, daily-no-data, capacity-blocked, and coalescing tests (depends: 8J.1-8J.9)

## 8K. Workflow Full-Model Scan Authority

- [ ] 8K.1 Make full extraction produce and exact-receipt-bind `request-closure-observation-inventory.json` from committed request/body/field/checkpoint authority (depends: 8I.4)
- [ ] 8K.2 Pass the exact workflow artifact ID/digest to terminal merge and `scan --fail-on error --full-publication`; prohibit checkout-local or same-name substitution (depends: 8K.1)
- [ ] 8K.3 Independently reconcile every request terminal disposition, body/bodyless object, result/field, field-temporal authority, checkpoint, catch-up seal, optional tail, staging journal, stable model/schema/lineage, cardinality anchor, export, and assured-file digest (depends: 8H.7, 8I.4, 8J.7-8J.8)
- [ ] 8K.4 Fail MODEL-GREEN on additive unclassified drift and DATA-GREEN on missing/unresolved/unknown/failed authority even when curated tables are populated (depends: 8K.3)
- [ ] 8K.5 Create the assured artifact only after zero scan errors and bind its sorted file inventory to every associated authority receipt (depends: 8K.3-8K.4)
- [ ] 8K.6 Add workflow/static/integration fixtures for missing inventory production, same-name substitution, plan-derived false closure, body/field/catch-up/tail tamper, post-seal calls, model drift, and exact assured success (depends: 8K.1-8K.5)

Sections 9 through 12 record assurance for the already-implemented transactional
recovery foundation. They do not validate the still-open full-model authority,
strictly-free execution, catch-up, tail, scan, or publication tasks in 8E-8K.

## 9. Transactional Foundation Focused Assurance

- [x] 9.1 Run Ruff formatting checks on every touched Python and test path (depends: 2-8)
- [x] 9.2 Run Ruff lint on every touched Python and test path and resolve all findings (depends: 9.1)
- [x] 9.3 Run `ty` on the checkpoint contract, control plane, runner, resilience, and configuration modules (depends: 9.2)
- [x] 9.4 Run the checkpoint-contract unit test file in isolation (depends: 3.10-3.12)
- [x] 9.5 Run the checkpoint-manifest transaction unit test file in isolation (depends: 4.13-4.16, 5.17, 6.11-6.13)
- [x] 9.6 Run the lane-identity incident regression and Hypothesis properties in isolation (depends: 2.8-2.10)
- [x] 9.7 Run the extractor-runner response-contract circuit tests in isolation (depends: 8.13-8.18)
- [x] 9.8 Run all full-extraction control tests with `--import-mode=importlib` (depends: 9.4-9.7)
- [x] 9.9 Run the maximum-width 256-lane checkpoint integration test (depends: 9.8)
- [x] 9.10 Run the no-network terminal handoff and redispatch control-plane integration tests (depends: 9.8)
- [x] 9.11 Record exact test counts, duration, and any expected skips for focused assurance (depends: 9.4-9.10)

## 10. Transactional Foundation Workflow Assurance

- [x] 10.1 Parse `.github/workflows/full-extraction.yml` with a YAML 1.2-compatible parser (depends: 5, 7)
- [x] 10.2 Run `actionlint` and resolve every workflow diagnostic (depends: 10.1)
- [x] 10.3 Assert every third-party action remains pinned to a full commit SHA (depends: 10.1; parallel: 10.2)
- [x] 10.4 Assert candidate upload precedes checkpoint build and no candidate updates the latest pointer (depends: 5.1)
- [x] 10.5 Assert checkpoint upload precedes receipt verification, manifest commit, and committed-manifest upload (depends: 5.2-5.8)
- [x] 10.6 Assert redispatch and terminal merge depend on checkpoint success and consume committed artifact outputs (depends: 5.9-5.10, 7.3)
- [x] 10.7 Assert exact artifact-ID downloads use digest mismatch errors (depends: 5.10, 6.6)
- [x] 10.8 Assert canonical checkpoint upload is non-overwriting and collision recovery is fail-closed (depends: 5.12-5.15)
- [x] 10.9 Assert dispatch sends exactly `{ref, inputs}`, omits `return_run_details`, parses the returned identity, and validates the exact run (depends: 7.5-7.8)
- [x] 10.10 Simulate failure immediately before checkpoint upload and prove no next pointer or child appears (depends: 5.11, 5.17)
- [x] 10.11 Simulate failure immediately after artifact upload and before receipt commit and prove no child appears (depends: 5.17)
- [x] 10.12 Simulate failure after manifest commit but before child acknowledgement and prove the committed state is reusable (depends: 5.17, 7.9)
- [x] 10.13 Simulate a same-name artifact collision and prove exact receipt reuse or fail-closed behavior (depends: 5.13-5.17)
- [x] 10.14 Simulate parent signal interruption and prove bounded exact-child cancellation (depends: 7.9-7.12)

## 11. Documentation Stewardship

- [x] 11.1 Update `README.md` full-extraction control-plane prose to distinguish semantic lane identity from attempt-local indexes (depends: 2.7)
- [x] 11.2 Document candidate, built, uploaded/verified, and committed checkpoint states in `README.md` (depends: 5.8)
- [x] 11.3 Document exact artifact-ID restore, immutable collision handling, and bounded legacy migration in `README.md` (depends: 5.12-5.15, 6.8-6.10)
- [x] 11.4 Document exact returned-run redispatch, semantic-source/producing-head provenance, and cleanup semantics in `README.md` (depends: 7.10, 8B.45)
- [x] 11.5 Document response-contract circuit accounting and its non-effect on required coverage in `README.md` (depends: 8.8-8.12, 8.19)
- [x] 11.6 Reconcile the root `AGENTS.md` full-extraction contract with the implemented transaction and dispatch behavior (depends: 11.1-11.5)
- [x] 11.7 Search for nested `AGENTS.md` files governing workflow, orchestration, tests, and docs and update only those whose contract changed (depends: 11.6)
- [x] 11.8 Update authored operator docs for recovery, smoke, full extraction, terminal assurance, and Kaggle handoff (depends: 11.2-11.5)
- [x] 11.9 Regenerate only repository-declared generated docs affected by public CLI or schema changes, if any (depends: 11.8)
- [ ] 11.9a Prove one public repository, one existing Kaggle dataset, and GitHub Actions-only production control; remove stale notebook cron/private-state/alternate-publisher authority before live admission (depends: 11.8-11.9)
- [x] 11.10 Run docs formatting and lint checks and verify generated-doc drift is intentional (depends: 11.8-11.9)
- [x] 11.11 Run `/docs-steward` or the available equivalent review over README, AGENTS, authored docs, and generated surfaces (depends: 11.1-11.10,11.9a)

## 12. Historical Repository-Wide Assurance

- [x] 12.1 Recheck branch, HEAD, origin, and dirty paths and separate this change from unrelated user work (depends: 9-11)
- [x] 12.2 Run full Ruff check over `src/` and `tests/` (depends: 9.2)
- [x] 12.3 Run full `ty check src/` (depends: 9.3)
- [x] 12.4 Run all unit tests with `--import-mode=importlib` and record exact count and duration (depends: 9.8)
- [x] 12.5 Run all integration tests with `--import-mode=importlib` and record exact count and duration (depends: 9.9-9.10)
- [x] 12.6 Run the complete test suite with `--import-mode=importlib` when unit and integration subsets are green (depends: 12.4, 12.5)
- [x] 12.7 Run extraction-completeness with the exact pinned `nba_api` runtime contract (depends: 12.2-12.6)
- [ ] 12.8 Run full upstream docs/tools contract analysis against `nba_api 1.11.4` when the source checkout is available (depends: 12.7)
- [ ] 12.9 Run model audit, SQL lint, and any repository CI-equivalent quality gates affected by extraction output (depends: 12.6)
- [ ] 12.10 Run strict OpenSpec validation again after implementation and docs settle (depends: 11, 12.1-12.9)
- [ ] 12.11 Review the final scoped diff for secrets, unpinned actions, compatibility paths, generated churn, and unrelated changes (depends: 12.10)
- [ ] 12.12 Run a parallel subagent review of checkpoint correctness, workflow security, failure accounting, test gaps, and docs consistency (depends: 12.11)
- [ ] 12.13 Resolve every confirmed review finding and repeat its narrowest failing gate (depends: 12.12)

Local implementation evidence snapshot (2026-08-05):

- Focused assurance passed: provenance helper `76 passed`, complete workflow contract `237 passed`, full-extraction control `375 passed`, checkpoint contract `40 passed`, lane-identity/Hypothesis `13 passed`, and no-network workflow smoke `2 passed`.
- Independent adversarial re-review passed `20` publication/receipt tests, `313` helper/workflow tests, and `407` control/write-metadata tests with no surviving actionable finding.
- Repository assurance passed: unit `5158 passed, 16 skipped`; integration `142 passed`; complete suite `5300 passed, 16 skipped`; full Ruff lint and format check; `ty check src/`; workflow-script type checking; Python compilation; YAML parsing; `actionlint`; and `git diff --check`.
- Docs assurance passed Prettier, ESLint, TypeScript checking, `28` docs tests, a `67`-route production build, and two docs-autogen runs with no generated diff. Strict OpenSpec validation passed for this change and `harden-hybrid-chat-correctness` after the implementation and docs settled.
- Coverage assurance reported `129/129` in-scope extractors, `416` staging entries, and `254/254` transform/schema outputs with no blocking gaps. `audit-models` reported `problem_count=0`.
- The full upstream docs/tools analysis in 12.8 remains open because no `nba_api 1.11.4` source/docs checkout is present. SQL lint in 12.9 remains open because it reports the existing baseline of `752` violations across `235` untouched transformer files; this change modifies no transform or transform-test path. Tasks 12.10-12.13 were executed as extra assurance but remain unchecked because their declared dependency chain includes 12.8 and 12.9.
- Frozen provenance surfaces: `full-extraction.yml` `215d7f120a539117f073c37cc11da04feb6b765639dfdcf4af19b676312b270e`; `workflow_source_provenance.py` `740ddfbf359f5c8e1538a64ccbe1dc4ef4af5d310ffa6ad791942bf84c907581`; `resolve_legacy_manifest_handoff.py` `f33f83d9ee16102992dec1788eff33a67f95fb7c318526272b82af7ec315155b`; `validate_full_extraction_attempt.py` `069cdc73ba62fe8101d0523506e884604bab836eebb5edbaeebf354ae7a84059`; helper tests `a5da0855722d54c320b224c4a41a7c9f6694d28b6ad0abfd6b549b44955f7735`; workflow tests `4d0572ab485398cdd050e31acc9fbbc49020002250c0b3740ff41bb0c6c92759`.
- Live/remote proof, commits, push, exact-SHA CI, strictly-free cost evidence, direct smoke, full extraction, and Kaggle publication remain outside this historical local evidence snapshot and stay unchecked. Historical VPN diagnostics are not accepted production proof. The unrelated untracked `tmp.md` remained byte-identical at SHA-256 `1b519a0fa90a93ac9d252cd5a3c217d9fb7dd48ba167b4f69887ad8238e78704`.

## 12A. Full-Model Contract And Local Assurance

- [ ] 12A.1 Run strict OpenSpec validation after the reconciled planning artifacts settle and retain the exact command/result (depends: 8E-8K)
- [ ] 12A.2 Run Ruff format/check and `ty` over every new request/public-authority/checkpoint/free/catch-up/tail/scan module and test (depends: 8E-8K)
- [ ] 12A.3 Run focused no-network tests for RequestUniverse closure/shards, public body/bodyless, field fate/temporal evidence, semantic diff, associated checkpoint receipts, free admission/canaries, catch-up/seal/tail, and scanner handoff (depends: 8G.10, 8H.8, 8I.7, 8E.11, 8J.10, 8K.6)
- [ ] 12A.4 Parse every changed workflow/action with YAML 1.2, run `actionlint`, assert full SHA pins, and prove production contains no Nord/paid dependency or name-only authority (depends: 8E.11, 8K.6)
- [ ] 12A.5 Run upstream docs/tools plus runtime contract assurance at the exact pin and require every supported endpoint/result/parameter/period/field route to reconcile (depends: 8G.10, 8H.8)
- [ ] 12A.6 Run extraction completeness, strict model/schema annotation/fate audits, SQL lint, full scan fixtures, docs generation, and generated-drift checks (depends: 8H.7, 8K.6)
- [ ] 12A.7 Run the complete unit/integration suite with `--import-mode=importlib`, record exact counts/duration/skips, and do not reuse historical counts as current proof (depends: 12A.2-12A.6)
- [ ] 12A.8 Run independent adversarial reviews of fixed-point completeness, public authority/secrets, checkpoint recovery, free-cost evidence, workflow security, catch-up/seal/tail, scan, and publication recovery (depends: 12A.7)
- [ ] 12A.9 Resolve every confirmed finding and rerun the narrowest failing gate plus all affected aggregate gates (depends: 12A.8)
- [ ] 12A.10 Review the final scoped diff for unrelated work, stale VPN requirements, unchecked compatibility authority, secrets, generated churn, and false-green wording (depends: 12A.9)

## 13. Atomic Integration And Exact-SHA CI

- [ ] 13.1 Partition only change-owned files from unrelated dirty-tree work (depends: 12A.10)
- [ ] 13.2 Create atomic conventional commits for provider RequestUniverse, public body/field/temporal authority, and their tests (depends: 13.1)
- [ ] 13.3 Create atomic conventional commits for associated checkpoint receipts, semantic diff, fresh cutover, and exact recovery tests (depends: 13.1; after: 13.2)
- [ ] 13.4 Create atomic conventional commits for strictly-free direct workflows, canaries, terminal catch-up/tail, scan handoff, and tests (depends: 13.1; after: 13.3)
- [ ] 13.5 Create an atomic conventional docs/OpenSpec commit (depends: 11, 12A.10, 13.1; after: 13.4)
- [ ] 13.6 Re-run the repository pre-push gate on the exact commit stack (depends: 13.2-13.5)
- [ ] 13.7 Push the commits to the existing `main` branch without rewriting history (depends: 13.6)
- [ ] 13.8 Verify remote `main` equals the intended local HEAD (depends: 13.7)
- [ ] 13.9 Monitor every required GitHub Actions workflow for the exact pushed SHA (depends: 13.8)
- [ ] 13.10 Download and diagnose any failing exact-SHA job before starting network extraction (depends: 13.9)
- [ ] 13.11 Fix confirmed CI defects in new atomic commits and repeat local and exact-SHA gates (depends: 13.10)
- [ ] 13.12 Require all mandatory exact-SHA checks green with no queued or in-progress ambiguity (depends: 13.9-13.11)

## 14. Strictly-Free Direct Transaction Smoke

- [ ] 14.1 Confirm no stale full-extraction, tail, or publisher authority can launch competing provider or Kaggle work (depends: 13.12)
- [ ] 14.2 Obtain a trusted unexpired `FreeExecutionAdmissionV1` for the exact smoke job and prove the matching post-run usage evidence surface is available; stop `capacity_blocked` if either cannot be proven (depends: 8E.11, 14.1)
- [ ] 14.3 Select one bounded manual lane from the exact verified RequestUniverse that includes the incident target/controls only after their non-ambiguous diagnostic branch is fixed and tested (depends: 8F.6, 8G.10, 14.2)
- [ ] 14.4 Dispatch exact-SHA attempt one with direct mode, one admitted execution slot, `targeted_smoke=true`, `publish=false`, `max_iterations=1`, and pipeline-failure retries disabled (depends: 14.3)
- [ ] 14.5 Verify the actual runner's GitHub, TeamYears, `common_all_players`, and `league_game_log` canary receipt immediately before its first provider call (depends: 14.4)
- [ ] 14.6 Monitor request/body/bodyless/result/field journals, lane state, DuckDB checkpoint/WAL finalization, associated authority digests, artifact upload/receipt, and committed manifest (depends: 14.5)
- [ ] 14.7 Require the exact post-run zero-cost usage receipt and committed checkpoint/artifact identities at the exact source SHA (depends: 14.6)
- [ ] 14.8 Verify targeted smoke does not merge, catch up, redispatch, publish, or claim full-model/dataset assurance (depends: 14.7)
- [ ] 14.9 Diagnose and fix any smoke failure locally and through exact-SHA CI before at most one separately admitted bounded retry (depends: 14.5-14.8)

## 15. Full Initial Extraction

- [ ] 15.1 Prove current Kaggle bytes, every old checkpoint/recovery/body inventory, and every artifact from failed run `30511585896` are diagnostic-only; the new chain starts with no lane-manifest, resume-source, checkpoint, or recovery input (depends: 8I.7, 14.7)
- [ ] 15.2 Confirm no unresolved Kaggle upload state or publisher lock can conflict with the eventual publish wave (depends: 15.1)
- [ ] 15.3 Freeze the exact source SHA and independently verified least-fixed-point RequestUniverse/field-temporal/model generations; require semantic diff to select a fresh full baseline (depends: 8G.10, 8H.8, 8I.7, 15.2)
- [ ] 15.4 Obtain trusted strictly-free capacity and runner-local direct canary receipts for the requested initial wave; emit `capacity_blocked` and do not launch if exact eligibility is absent or insufficient (depends: 8E.11, 14.7-14.9, 15.3)
- [ ] 15.5 Dispatch direct-mode exact-SHA attempt one with `chunk_profile=standard`, `max_iterations=auto`, `publish=false`, and no old-source inputs (depends: 15.4)
- [ ] 15.6 Record chain/root run/source, RequestUniverse, semantic diff, free admission, canary, root manifest, capacity, and fixed iteration-budget receipts (depends: 15.5)
- [ ] 15.7 Monitor closure rounds, exact dependency additions, every endpoint/result/parameter/period/field scope, physical shard exactness, calls, rows, and terminal dispositions (depends: 15.6)
- [ ] 15.8 Prove every successful occurrence has exact public-safe body or typed bodyless authority, exactly one public value representation, body/table projection equality, exact W2 operation readback, and explicit fate/temporal/MODEL status for every additive field (depends: 15.7)
- [ ] 15.9 Monitor each checkpoint's candidate/build/uploaded-verified/committed transition and verify all request/body/representation/W2/field/temporal/model associated digests plus database/report/artifact receipts (depends: 15.7-15.8)
- [ ] 15.10 Monitor circuit suppressions and every failure/timeout/unattempted call as unresolved outstanding coverage (depends: 15.7)
- [ ] 15.11 Verify each child is the exact returned dispatch identity at the same source/authority and consumes only the committed next-manifest receipt (depends: 15.9)
- [ ] 15.12 Revalidate free eligibility and runner-local canaries before every new provider wave; preserve committed progress and emit `not_fresh` on capacity loss (depends: 15.4, 15.11)
- [ ] 15.13 Stop on any guessed request, missing period/field/body, predicted pointer, overwrite, receipt mismatch, authority drift, post-expiry call, non-monotonic generation, or coverage regression (depends: 15.7-15.12)
- [ ] 15.14 Apply only evidence-backed fixes, repeat local and exact-SHA gates, and resume only from the latest identical-authority same-chain committed receipt (depends: 15.13)
- [ ] 15.15 Continue bounded iterations until the independent verifier accounts for every RequestUniverse invocation as one permitted terminal disposition and MODEL-GREEN has no unclassified field (depends: 15.7-15.14)
- [ ] 15.16 Obtain exact post-run zero-cost usage readback and record the terminal chain/run/checkpoint/request/body/field/model inventories and artifact receipts (depends: 15.15)

## 16. Terminal Assurance And Kaggle Publication

- [ ] 16.1 Download the exact terminal committed manifest/checkpoint and every associated request/body/field/model receipt by artifact ID (depends: 15.16)
- [ ] 16.2 Freeze one terminal event cutoff and build baseline-to-cutoff completion, declared recent overlap refresh, whole-history request/field hole repair, and one frozen live snapshot (depends: 8J.10, 16.1)
- [ ] 16.3 Record every catch-up call's observation start/end, exclude post-seal observations, and commit the exact final observation window/seal (depends: 16.2)
- [ ] 16.4 Require the TerminalCatchup candidate/build/uploaded-verified/committed transaction and exact parent/request/body/field/cutoff/overlap/hole/live/seal/database/report/artifact receipts (depends: 16.3)
- [ ] 16.5 Run every stable transform and configured export without publication credentials; separately record each admitted/withheld experimental model (depends: 16.4)
- [ ] 16.6 Produce and exact-receipt-bind the workflow request-closure observation inventory, then pass its artifact ID/digest into full scan (depends: 8K.6, 16.4)
- [ ] 16.7 Run `scan --fail-on error --full-publication` and independently require zero request/body/bodyless/result/field/temporal/checkpoint/catch-up/seal/tail/staging/model/schema/cardinality/export/assured-file errors (depends: 16.5-16.6)
- [ ] 16.8 Build and verify the assured artifact manifest and sorted file SHA-256 inventory bound to every authority receipt (depends: 16.7)
- [ ] 16.9 Require exact post-run zero-cost usage readback for initial extraction and catch-up before publication admission (depends: 8E.9, 16.8)
- [ ] 16.10 Resolve any persisted unresolved Kaggle publication marker and prove zero active writers/no unresolved durable intent (depends: 15.2, 16.9)
- [ ] 16.11 Reconfirm remote default branch equals the pinned source and dispatch one receipt-bound publication replay with the exact assured/checkpoint/catch-up identities (depends: 16.10)
- [ ] 16.12 Require a positive exact Kaggle version and valid marker, page the complete version inventory, and stream SHA-256 readback for every resource (depends: 16.11)
- [ ] 16.13 Derive table/resource counts from frozen runtime registries and require DuckDB/SQLite/CSV/Parquet inventory, ordered-schema, logical-type, row-count, and authority parity without hard-coded stale counts (depends: 16.12)
- [ ] 16.14 Persist the publication receipt and ledger success only after exact marker/version/inventory/hash/assured/checkpoint/catch-up parity succeeds (depends: 16.12-16.13)
- [ ] 16.15 If durable intent becomes ambiguous, reconcile only the exact publisher job in the same run and prove no competing run or second Kaggle call occurs (depends: 8C.32-8C.33, 16.11)
- [ ] 16.16 Refresh checked-in metadata only as the final post-readback step, resolve `M`, and require all six exact-`M` CI jobs when it changes (depends: 8C.34, 16.14)
- [ ] 16.17 Force-download the exact positive version into a new owner-only root and bind its complete inventory/hashes to the publication receipt (depends: 16.14)
- [ ] 16.18 Manually interrogate DuckDB read-only/external-access-disabled and SQLite immutable/read-only for integrity/FK, request/body/field/temporal/model/schema/row/key/cardinality/catch-up/seal/tail/publication parity and unchanged pre/post tree hashes (depends: 16.17)
- [ ] 16.19 With a new strictly-free admission, build one immutable parent-bound TailGeneration for data after the seal and prove next-day daily `fresh` or evidence-backed `not_fresh`/`capacity_blocked` plus trigger coalescing (depends: 8J.10, 16.18)

## 17. Closeout

- [ ] 17.1 Recheck local branch, dirty tree, remote HEAD, exact-SHA CI, extraction chain, terminal assurance, exact Kaggle version, manual interrogation, and TailGeneration/daily receipt from live state (depends: 16.16, 16.18-16.19)
- [ ] 17.2 Confirm no required jobs remain queued or in progress and no stale chain or publisher can launch later (depends: 17.1)
- [ ] 17.3 Confirm diagnostics, candidate artifacts, committed receipts, and publication records have appropriate retention and contain no secrets (depends: 17.2)
- [ ] 17.4 Record exact validation commands, test counts, commits, run IDs, job IDs, artifact IDs/digests, chain generation, Kaggle version/resource count, local download root digest, and manual database-query evidence (depends: 17.1-17.3)
- [ ] 17.5 Archive or close the OpenSpec change only after every normative capability and live gate is evidenced (depends: 17.4)
