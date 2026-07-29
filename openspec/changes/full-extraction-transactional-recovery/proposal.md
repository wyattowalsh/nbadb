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
- Bound repeated response-contract failures by pattern without recording
  suppressed calls as successes or reducing required coverage.

## Capabilities

### New Capabilities

- `transactional-full-extraction-checkpoints`: Stable lane identity,
  candidate/build/upload/commit checkpoint transitions, receipt-bound restore,
  and copy-plus-delta recovery.
- `exact-full-extraction-redispatch`: Idempotent self-dispatch with an exact
  returned child run identity and provenance validation.
- `bounded-extraction-failure-circuits`: Pattern-aware repeated
  response-contract suppression that preserves failed-call accounting and
  resume coverage.

### Modified Capabilities

None. This repository did not previously contain OpenSpec capability files.

## Impact

The change affects the full-extraction manifest and checkpoint artifact
contracts, GitHub Actions orchestration, extraction retry policy, control-plane
tests and fixtures, operator documentation, and the next full extraction and
Kaggle publication run. Existing source-SHA trust gates, lane-state
attestations, terminal assurance, and publication verification remain
fail-closed.
