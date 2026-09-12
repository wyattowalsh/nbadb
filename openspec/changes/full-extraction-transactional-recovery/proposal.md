## Why

The failed full extraction run `29568624951` proved that checkpoint acceptance
was coupled to mutable scheduling indexes and that the next manifest trusted a
predicted checkpoint before the checkpoint existed. That composition failure
discarded 13 completed lane artifacts after more than 85 hours of extraction.

## What Changes

- Define stable lane identity from semantic scope and coverage units; keep lane
  indexes as attempt-local dispatch metadata.
- Build checkpoint coverage from attested artifacts, then upload, verify, and
  commit the immutable artifact receipt into the next manifest.
- Preserve copy-plus-delta checkpoints even when an iteration makes zero
  progress.
- Resolve prior checkpoints by committed artifact ID and fail on digest or
  provenance mismatch.
- Use the workflow-dispatch API's exact returned run identity instead of
  inventory polling to discover a child run.
- Send only the documented `{ref, inputs}` workflow-dispatch body; the pinned
  GitHub API now returns the created run identity without the removed
  `return_run_details` request field.
- Make the plan job select and receipt-bind the sole source artifact and bundled
  manifest consumed by terminal replay; terminal replay does not enumerate or
  reselect source artifacts.
- Resolve the latest authoritative upstream contract at source freeze, pin it
  immutably, and derive a provider-owned request universe as an independently
  verified least fixed point over exact supported parameters, all provider-
  exposed periods per field, and discovered dependencies. Never guess a
  Cartesian comparison fan-out or silently omit an unresolved request.
- Bind request, successful parser-input body or explicit bodyless, result-set,
  field-fate, and field-temporal authority to every accepted lane and checkpoint
  generation. Additive unknown fields land losslessly but keep MODEL-GREEN red
  until their public fate and temporal applicability are classified.
- Classify authority changes with a canonical semantic diff. A new or changed
  request/body/field/temporal contract requires a fresh exact-SHA attempt-one
  baseline; only an unchanged same-chain committed receipt may resume.
- Replace production VPN/Nord admission with a strictly-free-at-point-of-use
  execution receipt, backend-neutral balanced dispatch slots, and direct
  GitHub/TeamYears/installed-stack canaries on every actual runner. Missing,
  stale, ambiguous, paid, or unverified capacity emits `capacity_blocked` and
  launches no provider work; it never reduces the request universe.
- Run one stdlib-only attempt/source validator immediately after exact-SHA
  checkout in every independently rerunnable job. Reject primary and generic
  downstream reruns because a new attempt can replace artifacts from the prior
  attempt; retain only receipt-bound publication and dispatch reconciliation.
- Treat discovery recovery as a distinct-workflow-run transaction: validate the
  source workflow identity, observe a complete stable artifact inventory,
  resolve one exact canonical or exact-attempt-one recovery receipt, directly
  recheck it by ID, and download it with digest enforcement.
- Reject unsafe exact-title duplicates before planning or reconciliation. Admit
  replacement history only for completed `failure`, `cancelled`, `timed_out`,
  or `action_required` runs after three complete observations stabilize. List
  the unfiltered workflow history to avoid GitHub's 1,000-result filtered-search
  cap, validate each event, and select `workflow_dispatch` runs locally.
- Reject symlinks, duplicate managed members, and ambiguous restored discovery
  layouts before copying state; require canonical bundles to be complete and
  integrity-valid while allowing provenance-valid recovery bundles to reseed
  incomplete workload state.
- Reconcile a dispatch-only rerun from the exact immutable committed-manifest
  receipt of the current run, including its encoded prior attempt, instead of
  synthesizing a current-attempt artifact name.
- Bind every cross-run lane and resume manifest to the source workflow's pinned
  SHA, exact workflow identity, state, and attempt before artifact selection.
  Upgrade the retained transaction-absent legacy name path to one stable exact
  artifact ID and one digest/layout-verified regular manifest member.
- Require every non-guard workflow job to depend transitively on the primary
  guard in addition to running its own attempt/source validator.
- Bound repeated response-contract failures by pattern without recording
  suppressed calls as successes or reducing required coverage.
- Keep the strict direct TeamYears canary and public `NBA_HEADERS` export aligned
  with the exact HTTP header contract of the pinned `nba_api` runtime. Keep the
  installed-stack discovery canaries aligned with discovery's bounded fast-path
  timeout, provide enough bounded child time for both sequential canaries,
  retain secret-safe outer and root exception types on failure, and use
  recognized roots to distinguish transport from response-contract failures.
- Preserve each successful body-bearing provider occurrence's exact public
  parser-input body and logical body receipt through lane state, copy-plus-delta
  checkpoints, terminal assurance, exports, and publication. Declared
  no-parser-input providers carry explicit bodyless evidence; failure paths
  never invent successful bodies or persist unrestricted error bodies.
- Build terminal catch-up as its own receipt-bound transaction over a frozen
  event cutoff: baseline-to-cutoff completion, recent overlap refresh,
  whole-history request/field hole repair, and a frozen live snapshot. Seal the
  observation window, reject post-seal observations, and derive later daily or
  opportunistic work only as a parent-bound `TailGeneration`.
- Make the workflow produce the exact request-closure observation inventory
  consumed by full-publication scan. Scan must independently reconcile that
  inventory with checkpoint, body/bodyless, field-temporal, catch-up, seal,
  tail, transform, schema, cardinality, and assured-file receipts.
- Keep stable source/silver/gold outputs release-gating and separately record
  admitted or withheld RAPM, xFG, WPA, forecast, rating, and prospect-value
  experiments. After exact Kaggle readback, force-download the exact positive
  version and manually interrogate its DuckDB and SQLite databases read-only.

## Capabilities

### New Capabilities

- `transactional-full-extraction-checkpoints`: Stable lane identity,
  candidate/build/upload/commit checkpoint transitions, receipt-bound restore,
  and copy-plus-delta recovery.
- `exact-full-extraction-redispatch`: Idempotent self-dispatch with an exact
  returned child run identity and provenance validation.
- `receipt-bound-discovery-recovery`: All-job attempt/source validation,
  cross-run-only discovery restore with exact artifact receipt selection,
  stable duplicate-run admission, provenance validation, digest-enforced
  download, and ambiguity-resistant restored-state installation.
- `bounded-extraction-failure-circuits`: Pattern-aware repeated
  response-contract suppression that preserves failed-call accounting and
  resume coverage.
- `nba-stats-probe-contract-parity`: Exact pinned-runtime HTTP headers for the
  fail-closed direct TeamYears canary and public `nbadb.core.NBA_HEADERS`
  request-header contract, plus runner-local installed-stack canaries with
  secret-safe, root-classified failure attestations and expiring receipts.
- `durable-kaggle-publication-intent`: Constant-bound GitHub Deployment
  write-ahead intent, exact executor and publisher-mutex admission,
  ambiguity-safe claims, retention-compacted terminal receipts, branch-head
  rechecks, same-run publisher reconciliation, run-scoped cache recovery,
  exact metadata-child CI, and full/daily/monthly publisher integration.
- `receipt-bound-terminal-replay`: Plan-selected exact artifact and bundled
  manifest receipts as the sole terminal-replay recovery authority.
- `exact-provider-request-authority`: Independently verified least-fixed-point
  request coverage, terminal observation dispositions, public parser-input
  authority, field fate, field-level temporal evidence, and semantic diff.
- `strictly-free-execution-admission`: Receipt-bound free-at-point-of-use
  capacity, backend-neutral balanced slots, direct canaries, fail-closed
  `capacity_blocked`, and coalesced recurring admission.
- `transactional-terminal-catchup-and-tail`: Frozen-cutoff terminal catch-up,
  observation windows and seals, overlap and whole-history hole repair, frozen
  live state, and crash-safe parent-bound tail generations.
- `full-model-terminal-assurance`: Workflow-produced request-closure authority,
  independent full scan, exact assured bundle, and initial publication/readback
  prerequisites.

### Modified Capabilities

None. This repository did not previously contain OpenSpec capability files.

## Impact

The change affects the full-extraction request universe, public observation and
field authority, manifest and checkpoint artifact contracts, GitHub Actions
orchestration, strictly-free admission, terminal catch-up and tail generation,
extraction retry policy, control-plane tests and fixtures, discovery recovery
boundaries, full-publication scan, the public
`nbadb.core.NBA_HEADERS` request-header contract, the pinned `nba_api`
dependency coupling, operator documentation, and the next full extraction and
Kaggle publication run. Kaggle publication additionally requires a
GitHub Deployment ledger with `deployments: write`, bounded REST reads, an
exact active-executor claim, and an approved current default-head receipt.
Existing source-SHA trust gates, lane-state
attestations, terminal assurance, and publication verification remain
fail-closed.

The public repository and existing Kaggle dataset remain the only production
topology, but user choice B makes the current Kaggle contents and every old
checkpoint diagnostic-only inputs for the new full-model baseline. GitHub
Actions is the only initial, catch-up, daily, monthly, opportunistic, and
publication control plane; this recovery design adds no private repository,
paid VPN dependency, package, state service, or alternate scheduler.

Run `30511585896` is a second incident baseline: its repeated
`box_score_hustle` response-contract failure reached the chain safety cap with
unchanged durable progress. Its artifacts are diagnostic only. A bounded,
secret-safe target-and-controls probe must classify that failure before a fresh
exact-source chain; ambiguous evidence stops release and never widens support
exclusions to an entire lane or season range.
