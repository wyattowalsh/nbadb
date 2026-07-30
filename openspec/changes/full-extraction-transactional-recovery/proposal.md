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
- Run one stdlib-only attempt/source validator immediately after exact-SHA
  checkout in every independently rerunnable job. Reject primary and generic
  downstream reruns because a new attempt can replace artifacts from the prior
  attempt; retain only receipt-bound publication and dispatch reconciliation.
- Treat discovery recovery as a distinct-workflow-run transaction: validate the
  source workflow identity, observe a complete stable artifact inventory,
  resolve one exact canonical or current-attempt recovery receipt, directly
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
- Keep the strict VPN TeamYears canary and public `NBA_HEADERS` export aligned
  with the exact HTTP header contract of the pinned `nba_api` runtime.

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
  fail-closed VPN TeamYears canary and public `nbadb.core.NBA_HEADERS`
  request-header contract, with drift detection.
- `durable-kaggle-publication-intent`: Constant-bound GitHub Deployment
  write-ahead intent, exact executor and publisher-mutex admission,
  ambiguity-safe claims, retention-compacted terminal receipts, branch-head
  rechecks, and full/daily/monthly publisher integration.

### Modified Capabilities

None. This repository did not previously contain OpenSpec capability files.

## Impact

The change affects the full-extraction manifest and checkpoint artifact
contracts, GitHub Actions orchestration, extraction retry policy, control-plane
tests and fixtures, discovery recovery boundaries, the public
`nbadb.core.NBA_HEADERS` request-header contract, the pinned `nba_api`
dependency coupling, operator documentation, and the next full extraction and
Kaggle publication run. Kaggle publication additionally requires a
GitHub Deployment ledger with `deployments: write`, bounded REST reads, an
exact active-executor claim, and an approved current default-head receipt.
Existing source-SHA trust gates, lane-state
attestations, terminal assurance, and publication verification remain
fail-closed.
