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
- Restore discovery state only across distinct workflow-run boundaries using
  an exact REST receipt and digest-enforced artifact-ID download.
- Reject overlapping active or successful exact-title workflow runs before
  planning or network allocation.
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
The precheck lists complete unfiltered workflow history, validates and selects
`workflow_dispatch` events locally, and therefore does not inherit GitHub's
1,000-result cap for searches that supply `event` or another search parameter.
Only completed `failure`, `cancelled`, `timed_out`, or `action_required`
predecessors are replaceable; every other status or conclusion blocks the
parent before dispatch.

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

### 9. Discovery recovery is cross-run and receipt-bound

GitHub Actions reruns preserve one workflow-run ID while advancing
`run_attempt`, but artifacts from a prior attempt are not a reliable restore
boundary, and GitHub may delete prior-attempt artifacts before any rerun job
starts. Every one of the 15 jobs therefore checks out the exact pinned source
and immediately runs one stdlib-only repository validator. The extract job
retains only its required deadline initialization before checkout. Attempt 1
admits exactly one of fresh, inline, lane-source, or resume-source mode. Mixed
modes, orphan artifact fields, asymmetric receipts, invalid or same-run source
IDs, and missing explicit chain identity fail before side effects.

The primary guard and every generic downstream job reject `run_attempt > 1`
unconditionally after validating the input shape. A new attempt-1 workflow
bound to immutable cross-run receipts is the recovery mechanism. There are two
narrow exceptions: the publish job may reconcile an ambiguous Kaggle upload,
and the dispatch job may reconcile a failed child dispatch. Both exceptions
still run the shared input validator and stable duplicate admission before
credentials, cache restoration, publication, or dispatch. Publication
preflight is not exempt because the publish job repeats its readiness checks.

The primary guard uses a `queue: max`, `cancel-in-progress: false` job
concurrency key containing only chain and iteration, so a second guard remains
queued instead of replacing the pending guard that owns the same identity. It
lists the workflow's complete history without `actor`, `branch`,
`check_suite_id`, `created`, `event`, `head_sha`, or `status` search parameters
because GitHub caps any such search at 1,000 results. It validates each run's
event, filters `workflow_dispatch` locally, observes the unfiltered inventory
three times, and requires the final two normalized inventories to match. The
touched REST calls explicitly use GitHub API version `2026-03-10`, matching the
repository control plane. Only completed `failure`, `cancelled`, `timed_out`,
and `action_required` predecessors are replaceable. Active, successful,
conclusion-less, neutral, skipped, stale, unknown, malformed, incomplete, or
unstable history blocks admission.

The restore resolver requires the exact source run to be completed with a known
executed conclusion (`success`, `failure`, `cancelled`, or `timed_out`),
originate from `workflow_dispatch`, identify the exact full-extraction workflow
path and a positive workflow ID, and expose a valid attempt and source SHA.
Administrative or non-executed conclusions such as `action_required`, `neutral`,
`skipped`, and `stale` are rejected because they do not prove that a recovery
bundle came from an extraction execution. The resolver observes the complete
artifact inventory three times, requires the final two normalized snapshots to
match, and prefers one unexpired canonical discovery artifact. If none exists,
it accepts only one unexpired recovery artifact whose embedded run ID and
attempt equal the source run's current attempt. A direct GET of the selected
artifact ID must reproduce the normalized receipt before digest-enforced
download.

Before copying restored files, the workflow rejects symlinks, duplicate
discovery manifests, discovery directories, summaries, workload pointers,
workload Parquet candidates, and duplicate relevant basenames. Canonical
restore requires every exact member and a real workload integrity attestation.
Recovery may omit partial workload state, but ambiguity is always fatal. If an
explicit discovery source has no valid receipt or its restored manifest does
not match the active chain, source SHA, and coverage fingerprint, the workflow
does not fall back to a wildcard artifact or scratch discovery.

A dispatch-only reconciliation may consume an exact committed manifest from an
earlier attempt of the current run. Its artifact name must bind the current run,
the exact next iteration, and an artifact attempt no greater than the current
attempt. The owner run must report the current attempt and pinned source SHA,
and the direct artifact receipt must match. The verifier never synthesizes a
current-attempt artifact name when the exact prior receipt is unavailable.

Lane-manifest and resume-source handoffs apply the same owner boundary. A
receipt-aware lane source validates the source run's pinned SHA, exact workflow
identity, attempt, and state before comparing the artifact's exact receipt. A
resume source must be a completed executed run; its complete artifact inventory
stabilizes before selecting the highest exact committed-manifest attempt or one
canonical fallback, and the selected artifact is re-read and downloaded by ID.
The retained transaction-absent legacy lane path is not trusted by run and name
alone: it first upgrades the name to one stable exact artifact ID owned by the
pinned workflow run, directly rechecks the artifact, downloads that ID, verifies
the REST digest when present, and extracts exactly one safe regular expected
manifest member. Every non-guard job also retains the primary guard in its
transitive dependency closure so a future root-level partial job cannot bypass
fresh-run admission.

**Alternative considered:** select the newest same-run recovery artifact by
name wildcard. A rerun cannot reliably access an earlier attempt's artifacts,
and ordering same-name or wildcard results does not bind the selected bytes to
an immutable REST identity.

### 10. Kaggle publication uses a bounded GitHub Deployment transaction

Every production publisher creates one immutable GitHub Deployment as a
write-ahead publication intent before entering the Kaggle upload call. The
deployment is bound to the frozen source SHA, exact bundle identity, dataset,
workflow definition, run, attempt, job, actor, and the repository-owned
publisher concurrency group. Admission independently verifies that the current
job is the exact executor by fully paginating the attempt's bounded job
inventory and directly re-reading its unique job ID. The direct job may be
`in_progress` while the parent run is `pending`; the job receipt is
authoritative. Admission also verifies that the workflow's publisher mutex uses
`queue: max` with cancellation disabled.

Ledger discovery is history-independent. A GitHub GraphQL connection with
explicit `CREATED_AT DESC` ordering selects at most the two newest matching
deployments; each selected ID is then revalidated through its exact REST
receipt. The ledger reads at most three statuses for either candidate through
bounded, stable observations. REST list page order is never treated as a
newest-head guarantee, and the complete protocol-sized status set is sorted
locally rather than assuming a REST transport order. `created_at`, not numeric
deployment or status IDs, defines chronology. Any malformed, ambiguous,
unstable, or overlapping inventory fails closed before a Kaggle call.

The publication transaction is:

1. validate the frozen bundle, exact executor, shared mutex, and allowed default
   branch head;
2. create or recover one immutable pending deployment intent;
3. claim it with an `in_progress` status containing a unique nonce and exact
   executor identity;
4. revalidate the claim and default branch immediately before the adjacent
   Kaggle upload call;
5. reconcile the exact Kaggle marker, positive dataset version, and complete
   digest readback;
6. write a terminal success status containing full claim and resolution
   commitments.

Ambiguous deployment or status writes are read-recovered by exact identity and
never blindly repeated. The terminal status repeats the full claim and
resolution digests because GitHub may retain the latest status after deleting
older statuses. A retained terminal status must therefore be independently
verifiable without its earlier claim status.

Executor admission distinguishes the Actions run's dynamic `run-name` from the
workflow definition name in `GITHUB_WORKFLOW`, and default-branch validation
distinguishes the singular Git-ref request route from GitHub's canonical plural
response URL. Both live response shapes are contract-tested.

The full publisher accepts the pinned source as the default branch head or the
single exact byte-identical metadata-only child already permitted by the
publication workflow. Daily and monthly publishers require their frozen source
to remain the exact default branch head. The local publication record remains a
secondary diagnostic and recovery cache; only the durable ledger plus the
exact remote Kaggle marker, version, inventory, and digest readback establish
publication success.

**Alternative considered:** use only the repository cache and
`kaggle-publication-state.json` as the intent ledger. That state is not a
cross-host transaction boundary and can be absent after an interrupted
ephemeral runner, so it cannot prevent an unsafe second upload.

### 11. Verification proceeds from deterministic local evidence to live gates

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
- **[Risk] A rerun cannot recover artifacts created by its prior attempt.** ->
  Reject primary and generic job reruns even when source inputs are present;
  operators must dispatch a new receipt-bound attempt-1 workflow. Permit only
  receipt-bound publish and dispatch reconciliation.
- **[Risk] A source run contains canonical and recovery discovery artifacts.**
  -> Prefer exactly one unexpired canonical receipt; otherwise accept only the
  source run's exact current-attempt recovery receipt, and reject ambiguity.
- **[Risk] GitHub accepts a deployment or status write but the client loses the
  response.** -> Recover the exact intent or claim through bounded stable reads;
  never issue a second POST merely because the first response was ambiguous.
- **[Risk] GitHub deletes prior deployment statuses after the retention
  window.** -> Put full claim and resolution commitments in the latest terminal
  status and verify it without depending on an earlier status.
- **[Risk] GitHub no longer exposes a historical run, job, workflow, or
  deployment receipt.** -> Fail closed and require explicit operator
  reconciliation; unavailable provenance may block publication but must never
  authorize a second upload.
- **[Risk] Another workflow or host attempts to publish concurrently.** ->
  Require exact executor identity and the shared non-cancelling publisher
  concurrency group before creating an intent and again before claiming it.
- **[Risk] The default branch moves between bundle validation and upload.** ->
  Check the allowed head before intent creation and immediately around claim
  admission; fail closed before Kaggle when it changes.
- **[Risk] Deployment history grows without bound.** -> Use GraphQL's explicit
  `CREATED_AT DESC` ordering for a fixed two-deployment head, directly verify
  both REST receipts, use a bounded status head and timestamp chronology, and
  fail closed when the bounded head cannot prove a unique current transaction.
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
7. Install the shared all-job attempt gate, stable exact-title admission, and
   narrow publish/dispatch reconciliation roles.
8. Make discovery restore cross-run-only, select and directly recheck one exact
   REST artifact receipt, and reject ambiguous restored layouts.
9. Enable the endpoint-scoped response-contract circuit and confirm failure,
   journal, and resume accounting.
10. Install the bounded GitHub Deployment publication ledger, wire full, daily,
    and monthly publishers to require it, and prove ambiguous-write,
    concurrency, retention, chronology, and default-head failure cases locally.
11. Complete local and exact-SHA CI assurance before starting a targeted VPN
   smoke.
12. Run the full extraction without publishing, monitor every checkpoint
   transaction, and require terminal assurance.
13. Publish the exact assured bundle to Kaggle and require version-specific,
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
- Whether GitHub exposes a prior attempt's artifacts during a same-run rerun is
  intentionally no longer an operational dependency; exact-SHA CI must prove
  the new cross-run rejection and receipt-bound recovery paths.
- Live evidence is still required to determine whether the configured
  `win_probability` threshold of three gives the best wall-clock savings
  without excessive false opening; coverage semantics do not depend on the
  chosen positive threshold.
