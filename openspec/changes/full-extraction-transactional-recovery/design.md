## Context

The full-extraction control plane schedules thousands of semantic coverage units
through bounded GitHub Actions matrix waves. Each matrix wave assigns mutable
dispatch metadata such as `lane_index`, `planned_wave`, priority, and VPN slot,
while durable extraction artifacts and checkpoint reports represent semantic
coverage across workflow runs.

Run `29568624951` exposed two coupled correctness defects:

1. Thirteen completed lane artifacts were rejected after rescheduling because
   checkpoint validation treated an attempt-local `lane_index` as durable
   identity.
2. Lane control advanced the next manifest to a predicted checkpoint coverage
   hash before the checkpoint database was built and its artifact existed. The
   subsequent build disagreed with the prediction and no durable checkpoint
   could be committed.

The affected boundary spans Python manifest and checkpoint contracts, extraction
failure accounting, the GitHub Actions workflow, child-run dispatch, tests,
operator documentation, and the eventual full extraction and Kaggle publication.
Existing source-SHA ancestry checks, lane-state attestations, checkpoint
provenance checks, terminal assurance, and exact Kaggle readback remain
fail-closed constraints.

GitHub Actions artifacts provide a positive artifact ID, SHA-256 archive digest,
size, workflow-run identity, and source SHA. Those fields form a stronger restore
identity than a reusable artifact name. GitHub workflow dispatch can return the
created run identity directly when `return_run_details` is requested, removing
inventory polling from the authoritative child-discovery path.

## Goals / Non-Goals

**Goals:**

- Separate stable semantic lane identity from attempt-local dispatch placement.
- Make checkpoint publication a transactional
  candidate -> built -> uploaded/verified -> committed state transition.
- Derive checkpoint coverage from accepted, attested artifacts rather than a
  prediction made by lane control.
- Bind every committed checkpoint pointer to immutable artifact and content
  receipts and restore by that exact identity.
- Preserve copy-plus-delta generations, including distinct zero-delta
  generations, without mutating an earlier checkpoint.
- Redispatch exactly once using the child run identity returned by the dispatch
  API and independently validate that run's provenance.
- Bound repeated permanent response-contract failures without classifying
  suppressed calls as successes or weakening required coverage.
- Add deterministic regression, fault-injection, workflow-static, local
  integration, CI, VPN smoke, full-extraction, terminal-assurance, and Kaggle
  publication gates.

**Non-Goals:**

- Increasing NBA API request concurrency beyond already configured network and
  endpoint safety limits.
- Treating GitHub-hosted runners as proof of distinct VPN exit IPs.
- Synthesizing unsupported endpoint parameter contracts or reducing the
  repository's declared `nba_api` coverage.
- Converting response-contract suppression into terminal
  `contract_blocked` evidence. Contract blocking remains governed by the
  independently validated support rules.
- Replacing lane-state attestations, discovery-seed verification, terminal scan,
  or Kaggle exact readback.
- Publishing a dataset from a targeted smoke run or from an uncommitted
  checkpoint.

## Decisions

### 1. Stable lane identity is semantic and dispatch-independent

A durable lane contract is identified by `lane_id` and its
`coverage_units_hash`. Checkpoint coverage additionally records a canonical,
sorted lane inventory digest and the semantic coverage fingerprint. Mutable
fields including `lane_index`, `planned_wave`, scheduling priority, queue class,
and VPN slot are excluded.

`lane_index` remains required, non-boolean, and non-negative where attempt
metadata requires it, but equality with a later manifest's index is not a
durable acceptance condition. Semantic fields, coverage hash, chain, source SHA,
artifact identity, state attestation, and workload scope remain strict.

**Alternative considered:** preserve the first assigned lane index forever.
This couples scheduling and storage, prevents safe reprioritization and splitting,
and does not add semantic integrity beyond the existing lane and coverage hashes.

### 2. Checkpoint publication is a monotonic transaction

For committed generation `n`, generation `n+1` follows these states:

1. **Candidate:** lane control writes a candidate manifest that still points to
   committed generation `n`.
2. **Built:** checkpoint construction copies generation `n`, merges only
   accepted deltas, computes actual coverage, checkpoints DuckDB, and binds the
   database and report SHA-256 values.
3. **Uploaded and verified:** the workflow uploads the complete candidate
   artifact and validates its positive artifact ID, archive digest, size, name,
   workflow run, and source SHA through the Actions API.
4. **Committed:** a new manifest atomically advances `latest_checkpoint_*` to
   generation `n+1`, moves generation `n` to `previous_checkpoint_*`, embeds the
   committed transaction receipt, and is uploaded for downstream consumers.

Only the committed manifest can be dispatched or used for terminal merge.
Failure at any earlier state leaves the last committed manifest authoritative.

**Alternative considered:** predict the next coverage hash before the build.
The failed run demonstrated that scheduling, artifact acceptance, and recovery
can change the accepted inventory, so a prediction cannot be a trust root.

### 3. Artifact identity is receipt-bound, not name-bound

The committed receipt binds:

- artifact ID, workflow run ID, logical name, archive SHA-256, and size;
- chain ID, pinned source SHA, and generation;
- semantic coverage fingerprint;
- checkpoint database and checkpoint report SHA-256 values.

Restore resolves the exact positive artifact ID, checks current REST metadata
against the committed receipt, downloads by ID with digest mismatch configured
as an error, and revalidates the database/report and checkpoint provenance.

The logical artifact name is generation-readable but not authoritative. A
first-writer upload for a generation is immutable. If a job retry encounters the
same logical name, it must resolve and validate the existing sibling or fail
closed; it must not overwrite an artifact referenced by a committed receipt.

**Alternative considered:** restore by run ID and artifact name. Names can be
reused or replaced and therefore cannot prove that downloaded bytes are the
bytes committed by the parent.

### 4. Copy-plus-delta remains the checkpoint storage model

Every new generation uses a new output path, copies the previous checkpoint
before merging current deltas, and never writes into the previous artifact.
The merge keeps existing maximum-multiplicity and journal-precedence semantics.
A zero-delta generation still creates and attests a distinct physical database
copy, report, transaction, artifact receipt, and committed manifest.

**Alternative considered:** reuse generation `n` for a zero-delta iteration.
That makes retries and provenance ambiguous and breaks the monotonic transaction
model.

### 5. Legacy pointers have a bounded migration path

Persisted pre-change manifests are concrete compatibility evidence. A manifest
with no transaction field may use the existing run/name provenance verifier for
one restore transition. A present but malformed, non-committed, or mismatched
transaction never falls back to legacy behavior. The first successful
post-change checkpoint emits a receipt-bound committed transaction, after which
all later restores use artifact ID.

**Alternative considered:** reject every pre-change manifest immediately. That
would discard otherwise attested recovery work and unnecessarily repeat API
extraction.

### 6. Child dispatch uses the returned run identity

Before dispatch, the workflow retains its exact-title idempotency precheck and
source-ref/workflow-blob ancestry gates. It posts the complete dispatch payload
with `return_run_details=true`, validates the returned positive run ID and URLs,
then reads that exact run and checks title, event, head SHA, and HTML URL.

Run-list inventory is not used to discover or acknowledge the child. A bounded
inventory fallback is permitted only to cancel a possibly created but
unacknowledged run when the API request succeeded but its response could not be
parsed. The exact returned run is the normal cancellation target.

**Alternative considered:** poll the workflow-run inventory until an exact title
appears. Concurrent history, pagination, propagation delay, and same-title
failed runs make that path ambiguous.

### 7. Response-contract circuits are narrow and accounting-preserving

The circuit is configured explicitly per endpoint and instantiated for one
pattern-result execution. It counts consecutive permanent `response_contract`
failures with the same normalized root-error signature. A valid response resets
the endpoint state; a changed signature begins a new count. Transport,
rate-limit, timeout, VPN, and infrastructure failures do not open this circuit.

After the threshold, queued calls for that endpoint are not sent upstream, but
each remains an eligible failed call with a distinct circuit-open error and a
failure journal record. No success journal row, extracted row, completed
coverage unit, or terminal support classification is synthesized. Normal
zero-progress abort and resume logic therefore preserve the outstanding
coverage.

**Alternative considered:** mark the rest of a homogeneous batch successful
empty. That improves runtime at the cost of silently losing required data and is
incompatible with terminal assurance.

### 8. The VPN canary mirrors the pinned `nba_api` HTTP contract

The TeamYears canary remains a small, strict, response-shape-validated request,
but its request headers are an exact copy of `nba_api 1.11.4`
`STATS_HEADERS`. The public `nbadb.core.NBA_HEADERS` mapping is also a defensive
copy of that runtime source. Unit contract tests import the pinned constant and
fail on connector order/value drift or public-export drift. This preserves the
connector's standard-library execution while ensuring every repository-owned
NBA reachability surface uses the same request contract as the extraction stack
it protects.

**Alternative considered:** keep a browser-like subset of the headers. NBA.com
can silently time out requests missing its current client-hint headers, which
misclassifies working tunnels as network failures and quarantines healthy
servers.

### 9. Verification proceeds from deterministic local evidence to live gates

Validation is staged so inexpensive failures stop before costly network runs:

1. formatting, lint, typing, focused unit/property tests, and OpenSpec strict
   validation;
2. workflow YAML parsing, `actionlint`, static contract assertions, and local
   no-network checkpoint/redispatch simulations;
3. the full unit and integration suite plus extraction completeness and docs
   validation;
4. push and exact-SHA CI monitoring;
5. one-lane VPN targeted smoke with checkpoint attestation;
6. full extraction with per-iteration checkpoint/manifest monitoring;
7. terminal read-only assurance;
8. Kaggle upload followed by exact version and complete resource digest
   readback.

No later wave proceeds when an earlier fail-closed gate is red.

## Risks / Trade-offs

- **[Risk] GitHub returns or reports incomplete artifact metadata.** -> Fail
  before manifest commit, retain the previous pointer, and upload only
  attempt-scoped diagnostics.
- **[Risk] A retry collides with a same-name checkpoint artifact.** -> Use
  first-writer semantics and validate the exact existing sibling; never
  overwrite a receipt-bound generation.
- **[Risk] A legacy checkpoint has expired before migration.** -> Report the
  exact unavailable pointer and resume only from another independently attested
  lane artifact or checkpoint.
- **[Risk] Transaction metadata increases manifest size and validation
  complexity.** -> Use a versioned exact-key schema, canonical JSON digests, and
  focused round-trip/tamper tests.
- **[Risk] A response-contract circuit masks a transiently malformed response.**
  -> Scope it to one pattern execution, require consecutive identical permanent
  classifications, keep every suppressed call failed, and retry it on resume.
- **[Risk] The upstream package changes its request header contract.** -> Pin
  `nba_api`, assert exact header parity in CI, and require the connector and
  runtime dependency to update in one atomic change.
- **[Risk] Exact dispatch response support changes.** -> Validate the returned
  shape and fail closed; do not silently fall back to ambiguous run discovery.
- **[Risk] Full-suite or live validation exceeds practical runtime.** -> Preserve
  the dependency gates and exact evidence for completed waves; never equate a
  focused green subset with full extraction or publication assurance.
- **[Trade-off] Copying a zero-delta DuckDB costs storage and upload time.** ->
  The distinct generation is retained because rollback, provenance, and crash
  recovery are more important than deduplicating a control-plane artifact.

## Migration Plan

1. Freeze run `29568624951` lane reorder and checkpoint failure evidence as
   deterministic fixtures.
2. Land the stable lane and versioned checkpoint transaction contracts with
   focused unit/property tests.
3. Change lane control to emit an uncommitted candidate and checkpoint build to
   compute actual accepted coverage.
4. Upload and verify the checkpoint, commit its receipt into a separate next
   manifest, and make all downstream jobs consume that committed manifest by
   artifact ID.
5. Resolve receipt-aware prior checkpoints by exact artifact ID; retain the
   bounded legacy transition only for transaction-absent manifests.
6. Move self-dispatch to the exact returned run identity and preserve duplicate
   and interruption safety gates.
7. Enable the endpoint-scoped response-contract circuit and confirm failure,
   journal, and resume accounting.
8. Complete local and exact-SHA CI assurance before starting a targeted VPN
   smoke.
9. Run the full extraction without publishing, monitor every checkpoint
   transaction, and require terminal assurance.
10. Publish the exact assured bundle to Kaggle and require version-specific,
    all-resource digest readback before declaring completion.

Rollback before a live extraction removes the new workflow and contract changes
as one atomic release. After a receipt-bound generation is committed, rollback
must retain readers for that transaction schema or explicitly resume from its
previous committed pointer; it must never rewrite the committed artifact.

## Open Questions

- Whether GitHub's exact dispatch response remains generally available for all
  repository plans must be confirmed by exact-SHA CI and the targeted smoke.
- The first-writer collision resolver needs a bounded policy for distinguishing
  a valid prior upload from an ambiguous or partially finalized artifact
  inventory.
- Live evidence is still required to determine whether the configured
  `win_probability` threshold of three gives the best wall-clock savings
  without excessive false opening; coverage semantics do not depend on the
  chosen positive threshold.
