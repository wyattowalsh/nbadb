## Context

The full-extraction control plane schedules thousands of semantic coverage units
through bounded GitHub Actions matrix waves. Each matrix wave assigns mutable
dispatch metadata such as `lane_index`, `planned_wave`, priority, and execution slot,
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
identity than a reusable artifact name. Under the pinned GitHub API, workflow
dispatch accepts only `ref` and `inputs` and returns the created run identity in
the successful response. The removed `return_run_details` field is invalid.

Run `30511585896` later failed at the chain safety cap after two identical
zero-progress `box_score_hustle` response-contract failures for game
`0024800300`. It produced no committed checkpoint, assured artifact, or
publication receipt. Its artifacts are therefore diagnostic evidence only, not
fresh-cutover recovery input.

User choice B establishes a new authority boundary: the next production result
is a new full-model baseline, not an incremental repair of the current Kaggle
dataset. Existing Kaggle bytes, run artifacts, and checkpoints may support
diagnosis and deterministic fixtures, but none may satisfy coverage or resume
the new baseline. The new authority must be derived at the exact source SHA from
provider-owned request, body/bodyless, result-set, field-fate, and field-level
temporal evidence.

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
  integration, CI, direct smoke, full-extraction, terminal-assurance, and Kaggle
  publication gates.
- Preserve mandatory public parser-input body authority for every successful
  body-bearing call through each checkpoint generation and final publication.
- Derive the exact provider-owned request universe to an independently verified
  least fixed point, including every supported period per field and dependency,
  without guessed Cartesian requests.
- Admit production only with fresh, authoritative proof that the actual runners
  and resources are strictly free at the point of use and pass bounded direct
  canaries; otherwise stop as `capacity_blocked` without shrinking coverage.
- Complete a crash-safe terminal catch-up and observation seal before assurance,
  then bind later recurring work to an immutable parent `TailGeneration`.
- Verify the exact Kaggle version by complete remote readback and manual
  read-only interrogation only after the new full-model baseline is assured.

**Non-Goals:**

- Increasing NBA API request concurrency beyond already configured network and
  endpoint safety limits.
- Treating a runner label, account allowance, device count, or historical zero
  charge as proof that the current execution is free-at-point-of-use.
- Synthesizing unsupported endpoint parameter contracts or reducing the
  repository's declared `nba_api` coverage.
- Converting response-contract suppression into terminal
  `contract_blocked` evidence. Contract blocking remains governed by the
  independently validated support rules.
- Replacing lane-state attestations, discovery-seed verification, terminal scan,
  or Kaggle exact readback.
- Publishing a dataset from a targeted smoke run or from an uncommitted
  checkpoint.
- Adding a second repository/private state package, a paid proxy or VPN,
  another production scheduler, or an optional successful-body path. The one
  public repository, one Kaggle dataset, and GitHub Actions remain the complete
  control topology.

## Decisions

### 1. Stable lane identity is semantic and dispatch-independent

A durable lane contract is identified by `lane_id` and its
`coverage_units_hash`. Checkpoint coverage additionally records a canonical,
sorted lane inventory digest and the semantic coverage fingerprint. Mutable
fields including `lane_index`, `planned_wave`, scheduling priority, queue class,
and execution slot are excluded.

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
with no transaction field may use one bounded attested rebuild over its exact
authorized run IDs. Each owner attestation is consumed as the selection
snapshot, its stable complete inventory selects a unique logical name, and a
direct REST receipt binds the positive artifact ID and archive digest before an
exact-ID download. The logical name is never download authority. A present but
malformed, non-committed, or mismatched transaction never falls back to legacy
behavior. The first successful post-change checkpoint emits a receipt-bound
committed transaction, after which all later restores use the committed artifact
ID directly.

**Alternative considered:** reject every pre-change manifest immediately. That
would discard otherwise attested recovery work and unnecessarily repeat API
extraction.

### 6. Child dispatch uses the returned run identity

Before dispatch, the workflow retains its exact-title idempotency precheck and
source-ref/workflow-blob ancestry gates. It posts the complete dispatch payload
with a body containing exactly `ref` and `inputs`, validates the returned
positive run ID and URLs, then reads that exact run and checks title, event, head
SHA, and HTML URL.
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
rate-limit, timeout, network-egress, and infrastructure failures do not open
this circuit.

After the threshold, queued calls for that endpoint are not sent upstream, but
each remains an eligible failed call with a distinct circuit-open error and a
failure journal record. No success journal row, extracted row, completed
coverage unit, or terminal support classification is synthesized. Normal
zero-progress abort and resume logic therefore preserve the outstanding
coverage.

**Alternative considered:** mark the rest of a homogeneous batch successful
empty. That improves runtime at the cost of silently losing required data and is
incompatible with terminal assurance.

### 8. Every direct production canary mirrors the pinned `nba_api` contract

Each actual production runner executes a bounded direct GitHub control-plane
probe, a strict response-shape-validated TeamYears request, and installed-stack
`common_all_players` plus `league_game_log` canaries before provider work. The
TeamYears request headers are an exact copy of `nba_api 1.11.4`
`STATS_HEADERS`; the public `nbadb.core.NBA_HEADERS` mapping is a defensive copy
of that runtime source. Unit contract tests fail on ordered header or public-
export drift. A canary receipt binds the runner, source, workflow job, attempt,
start and expiry times, endpoint shapes, and sanitized classifications and is
rechecked immediately before that runner's first provider call.

Installed-stack failures preserve the outer exception class and the explicit
exception chain's root class as bounded ASCII tokens. They never include
exception messages, response bodies, parameters, cookies, authorization data,
or credentials. A recognized root becomes the transport-versus-response-
contract classification input; the validated outer type remains the fallback
when the root is absent or invalid. Every endpoint and child-process deadline
remains bounded inside the job finalization reserve.

**Alternative considered:** reuse a canary from another job or keep a browser-
like subset of headers. The former does not attest the actual runner; the latter
can turn missing client-hint headers into false network failures. Runner-local,
receipt-bound direct canaries close both gaps without adding a paid egress
dependency.

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
it accepts only one unexpired recovery artifact whose embedded run ID names the
source run and whose attempt is exactly one. A direct GET of the selected
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

A dispatch-only reconciliation may run on a later workflow attempt only through
its dedicated non-mutating role and may consume only the exact committed manifest
produced by attempt one. Its artifact name must bind the current run, the exact
next iteration, and producing attempt one. The owner run may report the later
reconciliation attempt but must retain the same producing head SHA,
while the manifest retains the pinned semantic source SHA, and the direct
artifact receipt must match the owner. The verifier never synthesizes a
replacement artifact name when the exact receipt is unavailable.

Lane-manifest and resume-source handoffs apply the same owner boundary. A
receipt-aware lane source distinguishes pinned semantic source `S` from owner
run head `H`, validates the exact workflow identity, attempt, and state, proves
`S == H` or `S` is an ancestor of `H`, and compares identical
full-extraction-workflow bytes at both commits before checking the artifact's
exact `H`-owned receipt. A
resume source must be a completed executed attempt-one run; its complete artifact
inventory stabilizes before selecting one unique exact-attempt-one committed
manifest or one canonical fallback, and the selected artifact is re-read and
downloaded by ID.
The retained transaction-absent legacy lane path is not trusted by run and name
alone: it first upgrades the name to one stable exact artifact ID owned by the
pinned workflow run head after the same `S`/`H` ancestry and workflow-byte
attestation, directly rechecks the artifact, downloads that ID, verifies the
REST digest when present, and extracts exactly one safe regular expected
manifest member. Current-run artifacts instead bind their owner directly to
`GITHUB_SHA` while preserving semantic source fields. Every non-guard job also retains the primary guard in its
transitive dependency closure so a future root-level partial job cannot bypass
fresh-run admission.

The attestation file is a consumed schema-v1 selection snapshot, not a discarded
precheck. Immediately before any cross-run artifact selection, the consumer
re-reads the exact owner and requires equality on repository, workflow, event,
branch, run, attempt one, state, semantic source, and producing head. Resume
metadata, partial lane state, completed lane databases, paired lane metadata,
discovery inputs, and transaction-absent checkpoint rebuild inputs all resolve
through stable complete inventories and direct positive-ID receipt rechecks.
Their GitHub archive digests travel separately from DuckDB database SHA-256
commitments through the lane model, manifest matrix, restore, and checkpoint
merge; a logical name never authorizes a download.

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
6. obtain a fresh current-executor receipt, require the resolving execution's
   run, attempt, job, admission digest, deployment origin, nonce, and claim to
   match, bracket the final exact remote claim observation with active-executor
   checks so status drift during the first check and executor drift during the
   claim observation are rejected, and write a terminal success status containing
   full claim and resolution commitments.

Ambiguous deployment or status writes are read-recovered by exact identity and
never blindly repeated. The terminal status repeats the full claim and
resolution digests because GitHub may retain the latest status after deleting
older statuses. A retained terminal status must therefore be independently
verifiable without its earlier claim status.

Direct resolution belongs only to the exact currently admitted execution. A
later attempt of the same run may close already-verified remote state only
through the explicit reconciliation path; another run may do neither. Any
executor or origin drift raises the pending-intent error and produces no success
status POST.

GitHub does not expose a compare-and-set that atomically couples workflow/job
liveness with Deployment status creation. The paired observations therefore
close every drift they observe, while the mandatory non-cancelling FIFO
publisher mutex excludes concurrent repository-sanctioned writers. This design
does not claim atomic protection from an arbitrary out-of-band token appending a
status after the final claim observation; that stronger threat model would need
a different single-resource lease or conditional-write primitive.

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

Cache restoration is scoped to
`nbadb-kaggle-publication-state-${run_id}-`. Before durable intent, one new
zero-active replay may replace a failed publisher only after stable no-writer
and no-intent proof. After pending or in-progress intent exists, reconciliation
reruns only the exact publisher job in the same workflow run and reuses the same
assured bundle and intent. If remote and ledger success already exist, the rerun
skips Kaggle and resumes only post-publication work.

After verified publication, metadata head `M` is either the frozen source or one
direct, non-merge, byte-reproducible metadata-only child. A distinct `M` receives
an explicit CI dispatch whose returned run and six required jobs are verified
at exact `M`; a token-authenticated metadata push is not assumed to trigger CI.

**Alternative considered:** use only the repository cache and
`kaggle-publication-state.json` as the intent ledger. That state is not a
cross-host transaction boundary and can be absent after an interrupted
ephemeral runner, so it cannot prevent an unsafe second upload.

### 11. Terminal replay consumes the plan-selected receipt

The plan job selects one exact source manifest artifact, directly verifies its
receipt, and bundles its bytes as `resume-source-input-manifest.json` beside a
schema-v1 `resume-source-selection.json`. The selection receipt binds resolution
mode, source artifact ID/name/digest/size, unexpired state, archive URL, owner
run/exact attempt one/workflow/source,
chain, and bundled member name/size/SHA-256. Here `source` is the semantic SHA,
while the artifact owner is its producing run head. The plan proves the semantic
source is equal to or an ancestor of that head and the workflow bytes are
identical. After a final owner re-read, the uploaded current-run plan artifact
is itself directly verified for exact ID, name, archive digest, positive size,
unexpired state, archive URL, owner run at attempt one, and `GITHUB_SHA`; it
retains the semantic source separately, and its exact receipt becomes a job
output.

Terminal replay downloads only that output artifact ID, validates both members,
and consumes the bundled manifest. It does not enumerate or reselect source
artifacts. A committed checkpoint resolves only by its exact transaction ID; a
transaction-absent manifest may use only the existing attested rebuild over its
exact authorized run IDs. Candidate or diagnostic state fails closed.

The current run's committed-next-manifest and terminal-replay output are also
authority artifacts. Their uploads are directly verified for exact ID, name,
archive digest, size, expiry, archive URL, run, attempt one, and producing
`GITHUB_SHA`; terminal merge receives those receipts and downloads only their
IDs. The publisher verifies assured data as an immutable attempt-one authority
before requesting the ZIP and repeats the current owner read. A later current
owner attempt may consume that receipt only in the dedicated same-run
publication-reconciliation role; it may not create or substitute assured data.
The publisher then verifies archive digest and safe layout before consuming any
assured member.

**Alternative considered:** repeat source inventory selection in terminal
replay. Inventory may change after planning and creates a second authority that
can disagree with the plan.

### 12. Production execution is admitted only when it is strictly free

`FreeExecutionAdmissionV1` binds the exact source, repository, workflow, run,
attempt, job, runner class, requested resource, authoritative eligibility
source, observation time, expiry, and a zero-cost-at-point-of-use conclusion.
Runner labels, plan names, device allowance, historical billing, or an assumed
GitHub quota are not evidence. The admission and a post-run usage readback must
come from a trusted account/repository evidence surface whose semantics are
contract-tested. If that evidence is unavailable, ambiguous, stale, nonzero, or
cannot cover the requested job, the workflow emits `capacity_blocked` and does
not start provider work.

The trusted execution context is not caller-authored. It combines authenticated
platform claims and direct REST receipts for repository visibility, workflow and
source SHA, run, attempt, actual job, standard GitHub-hosted runner environment,
capacity, mode, and a fresh nonce. Artifact ownership at workflow-run granularity
does not prove the producing job, so positive authority additionally requires an
authenticated job-to-artifact join. The resource plan recursively covers jobs,
runner selectors, reusable workflows/actions, containers, services, artifacts,
caches, packages, custom images, retention, and external billing dependencies.
GitHub's public-repository standard-runner compute eligibility does not imply
that artifact or cache storage is free: current allowance, accrued use,
retention, billing owner, and cross-period liability are all part of admission
and post-run readback. Free-form pricing text, including a `free` substring, is
never authoritative.

Each provider operation receives one single-use authorization bound to that
authenticated context, slot, lane, endpoint, canonical URL/path, parameter/body
identity, operation ordinal, and issued nonce. A changed, replayed, widened, or
self-resealed authorization fails before network access. Ledger restoration
requires an exact receipt-bound checkpoint, safe artifact inventory, and
authenticated creator/job provenance; caller-manufactured state cannot recreate
a positive root.

Production uses direct connectivity only and has no Nord, paid VPN, proxy,
credit, or paid-token dependency. Every actual runner must independently pass
the direct canaries in decision 8. Deterministic round-robin execution slots
retain the existing completeness, contiguity, `ceil(N/S)` balance, and per-slot
non-cancelling queue invariants, but an execution slot is not a network identity
and does not enlarge the admitted capacity. Capacity loss stops new provider
calls, preserves committed state, and records `not_fresh`; it never reduces the
request universe or converts missing work into success.

**Alternative considered:** assume a free hosted-runner allowance or reuse the
existing Nord connector. Neither proves zero cost for this exact execution, and
the latter is a paid production dependency. Both therefore fail the accepted
strictly-free contract.

### 13. Provider request authority is an independently verified fixed point

Immediately before source freeze, authoritative release/source evidence is used
to compare the repository pin with the latest `nba_api` contract. A newer
supported contract is updated atomically with headers, runtime/docs/tools,
schemas, routes, models, and tests. The active chain then uses that one exact
immutable pin; a moving `latest` reference never becomes execution authority.

The immutable `RequestUniverseGeneration` begins with every endpoint/result
surface exposed by that exact runtime, repository support contracts, static and
live providers, and provider-exposed temporal axes. Discovery rounds may add
only provider-owned identifiers or exact dependent requests proven by typed
responses. Every new identifier is fed through the dependency graph until a
complete round adds no requests. A separate verifier recomputes the least fixed
point from the same frozen inputs and rejects missing, extra, duplicate,
overlapping, or guessed requests.

No comparison endpoint may synthesize Cartesian player/team/opponent pairs.
Every supported period is considered per endpoint and per field, so endpoint-
level season bounds cannot silently narrow a field with different applicability.
Each exact invocation reaches only one terminal disposition: successful
nonempty, successful present-empty with response evidence, or narrowly
evidenced upstream unavailable/contract-blocked. Unattempted, suppressed,
unknown, body-missing, or parser-failed requests remain unresolved.

For every successful body-bearing occurrence, the exact public-safe parser-
input bytes are content-addressed and receipt-bound before parsed rows can be
journaled. A declared no-parser-input provider emits an explicit bodyless
receipt. Failure evidence is allowlisted metadata only. Additive or unknown
result sets and fields land losslessly with request/result/field provenance,
but MODEL-GREEN remains red until field fate, types, keys, lineage, and temporal
applicability are reviewed.

### 13a. Public value closure is a post-staging, pre-journal transaction

Raw Authority V2 remains the exact-four source/request/result/route boundary.
The separately versioned `PublicValueAuthorityV1` derives an ordered unit set
from each selected-terminal bundle: every selected result occurrence and every
response-level residual or admitted fixed-zero unit. Exactly one
`ValueRepresentationAssignmentV1` per unit selects
`rectangular_result_cells_v1`, `stats_lossless_records_v1`,
`live_lossless_nodes_v1`, `response_lossless_records_v1`, or
`response_fixed_zero_v1`; `parser_input_body` versus
`declared_bodyless_packet` remains an orthogonal source-input classification.
The selection follows the sealed output contract, so an anomaly-aware fallback
does not become rectangular merely because its current rows have uniform width.

Two explicit prerequisite authorities close information Raw Authority V2 does
not contain. `LosslessOwnershipReceiptV1` exhaustively partitions every decoded
stats/live lossless record into one selected occurrence or the response residual,
including zero-record occurrence partitions and an explicit zero-residual root.
`DeclaredBodylessPacketV1` plus `DeclaredBodylessPacketReadbackReceiptV1`
persist and exact-read back static packet bytes; `bodyless_evidence_sha256` is
only disposition evidence. Mandatory live-node rows are emitted for selected
live observations even when no conditional drift route exists.

The base public schema always contains `raw_nba_api_result_cell`,
`raw_nba_api_stats_lossless_record`, `raw_nba_api_live_lossless_node`,
`raw_nba_api_value_representation`, `raw_nba_api_route_field_landing`, and
`raw_nba_api_w2_operation`. Conditional stats/live staging tables remain
dynamic route outputs and are not the sole structured reconstruction authority.
Runtime registries derive the complete table/resource count; historical numeric
counts are evidence snapshots, not product premises.

Two disjoint verifiers close the value authority.
`BodyValueProjectionReceiptV1` reads only exact parser-input bytes or the exact
declared bodyless packet. `PublicTableValueProjectionReceiptV1` reads only
structured public rows and cannot consult body payloads, private caches,
extraction memory, production parser/staging code, or receipt-embedded values.
`ValueProjectionEqualityReceiptV1` performs exact type, cardinality, order,
duplicate, path, ordinal, value, and presence comparison over the independently
derived unit denominator.

Durability is deliberately two-phase. Exact body/bodyless authority is captured
and read back before parser-derived staging becomes an accepted candidate.
Staging then commits as a recoverable candidate so the system can derive its
exact post-commit readback. One `W2OperationReceiptV1` binds raw persistence,
body/bodyless, representation/table roots, staging receipts/readbacks, field-
fate/conditional/live-plan roots, route-field receipts, both projections and
their equality, and resource totals. Only exact W2 persistence/readback permits
request closure and journal success. A crash before that point leaves
nonterminal candidate state; identical replay may finish it, while partial,
colliding, foreign, or reordered state fails closed.

The semantic operation binds all six schema contracts but pre-operation row
roots for only the first five relations; otherwise it would hash its own W2 row.
`W2OperationPersistenceReceiptV1` separately binds that inserted row and exact
post-commit W2 table readback. A stable content-independent operation key makes
same-key/different-semantic state a fail-closed collision.

Losslessly preserved drift may therefore be journaled without being semantically
admitted. Its immutable blocker joins field fate, temporal authority, model
disposition, and semantic diff, keeping MODEL-GREEN and full publication red
until review closes every changed atom.

### 14. Semantic diff decides fresh baseline versus later delta

A canonical semantic diff compares provider/runtime identity, endpoint and
result-set contracts, exact parameter domains, dependency rules, request
universe, ordered fields, logical types, key/meaning, staging routes, model
lineage, and field-level temporal authority. Identity-changing, removed,
reinterpreted, or previously unmodeled authority requires a new exact-SHA
attempt-one baseline. A later additive, meaning-preserving change may use a
bounded delta/backfill only when the previous public authority remains valid and
the diff proves every affected request and period.

The initial public-value cutover and every later representation-kind,
expected-unit, exactly-one-assignment, public table/schema, or reconstruction-
rule change are reconstruction authority breaks and always select fresh full.
No compatibility alias may project an old checkpoint, dataset, conditional
table, or cell receipt into the new authority. After a complete baseline exists,
new rows or a reviewed additive field under the unchanged representation/schema
may use delta only through the ordinary exact affected-scope proof.

Choice B makes the current Kaggle dataset and every pre-change checkpoint
diagnostic only for this cutover. The new baseline starts with no old lane
manifest, resume source, checkpoint, body inventory, or recovery pointer. Once
the baseline begins, recovery may consume only a committed receipt from the same
chain, source SHA, RequestUniverse generation, public-observation authority,
field-temporal authority, and model contract. Any authority drift requires
another fresh attempt-one chain.

### 15. Terminal catch-up is a sealed, crash-safe transaction

After the historical checkpoint reaches fixed-point terminal coverage, a
`TerminalCatchupGeneration` freezes an event-time cutoff and performs four
independently accounted components: baseline-to-cutoff completion, a declared
recent overlap refresh, whole-history request and field hole repair, and one
frozen live snapshot. Each provider call records observation start/end times;
the generation records the maximum accepted observation time and a final seal.
No observation ending after the seal may enter that generation.

Terminal catch-up uses the same `candidate`, `built`, `uploaded_verified`, and
`committed` transition discipline as checkpoints. Its receipt binds the parent
checkpoint, RequestUniverse, body/bodyless inventory, field-temporal authority,
event cutoff, overlap window, hole-repair inventory, live snapshot, observation
window/seal, database/report digests, and exact artifact receipt. A crash before
commit leaves the prior authority unchanged; retry resumes only from the last
committed catch-up receipt rather than rerunning an unreceipted merge or live
snapshot.

### 16. Later work is a parent-bound TailGeneration

Calls observed after the terminal seal belong only to a new `TailGeneration`
whose identity binds its exact parent, event cutoff, observation window, overlap
window, request-universe diff, and authority receipts. Tail publication follows
the same four-state transaction and cannot rewrite its parent. Daily scheduling
targets next-day availability and emits a durable `fresh` or `not_fresh` receipt
even when no data is available or no free capacity is admitted.

Opportunistic triggers may run only with a fresh strictly-free admission. They
coalesce concurrent demand into one active generation, update the desired
cutoff monotonically, and never launch duplicate provider or publisher work.
Monthly or explicit backfill is a wider tail/repair policy, not permission to
skip fixed-point, field-temporal, or body authority.

### 17. Full scan consumes workflow-produced authority

The full-extraction workflow, not a local side channel, produces and receipt-
binds `request-closure-observation-inventory.json`. Full-publication scan
downloads that exact artifact and independently reconciles every RequestUniverse
invocation with terminal disposition, body/bodyless object, result-set and
field inventory, field-level temporal evidence, checkpoint generation,
terminal-catch-up seal, optional tail, staging journal, stable transform, schema,
row-count/cardinality anchor, export, and assured-file digest.

Only a zero-error scan may create the assured artifact. Initial publication
then additionally requires a fresh exact-SHA attempt-one chain, committed
checkpoint and catch-up generations, no unresolved request or field authority,
MODEL-GREEN, verified strictly-free execution receipts and post-run usage
readback, exact Kaggle version and all-resource hash readback, and a manual
read-only DuckDB/SQLite interrogation of the force-downloaded exact version.

### 18. The failed hustle lane is classified before fresh cutover

A separately authorized diagnostic may probe target `0024800300` and controls
`0024800299` and `0024800301` only on independently admitted strictly-free
direct runner observations, with zero in-call retries and a bounded total call
count. It retains only status class, content type, response byte length/hash,
allowlisted exception classes, and valid result-set names/counts. If qualifying
free capacity cannot be proven, the diagnostic remains blocked.

Valid JSON with a local failure permits a narrow parser fixture and fix;
transient or runner-varying evidence permits transport classification or bounded
retry correction; valid empty data becomes an ordinary zero-row success;
repeatable target-only unsupported evidence may create only a parameter-scoped
`upstream_unavailable` rule. Ambiguity stops release. No branch resets the
safety cap, fabricates success, or excludes an entire lane or season range.

### 19. Verification proceeds from deterministic local evidence to live gates

Validation is staged so inexpensive failures stop before external work:

1. formatting, lint, typing, focused unit/property tests, and strict OpenSpec;
2. workflow YAML, `actionlint`, static contracts, and no-network transaction
   simulations;
3. the complete test suite, extraction/model completeness, scan fixtures, and
   docs validation;
4. push and exact-SHA CI monitoring;
5. trusted free-capacity evidence and one-lane direct nonpublishing smoke;
6. a fresh attempt-one full-model extraction with per-generation request/body/
   field/checkpoint monitoring;
7. committed terminal catch-up, observation seal, and independent full scan;
8. Kaggle upload followed by exact-version complete-resource digest readback;
9. forced exact-version download into a fresh owner-only root plus manual
   DuckDB read-only/external-access-disabled and SQLite immutable/read-only
   interrogation; and
10. a later parent-bound tail/daily proof when free capacity is available.

No later wave proceeds when an earlier fail-closed gate is red.

## Risks / Trade-offs

- **[Risk] GitHub returns or reports incomplete artifact metadata.** -> Fail
  before manifest commit, retain the previous pointer, and upload only
  attempt-scoped diagnostics.
- **[Risk] A retry collides with a same-name checkpoint artifact.** -> Use
  first-writer semantics and validate the exact existing sibling; never
  overwrite a receipt-bound generation.
- **[Risk] A legacy checkpoint is accidentally treated as new-baseline
  authority.** -> Keep old Kaggle and checkpoint bytes diagnostic-only and
  require a fresh attempt-one empty candidate for the new authority generation.
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
- **[Risk] Plan and replay select different source bytes.** -> Bundle the
  selected manifest in the exact verified plan artifact and remove replay-side
  inventory selection.
- **[Risk] Slot scheduling overloads one admitted runner.** -> Validate
  deterministic balance and completeness before publishing any manifest output;
  the live job count may not exceed the exact free-capacity receipt.
- **[Risk] A provider-owned dependency is omitted from the request universe.**
  -> Independently recompute the least fixed point and reject the generation on
  any missing, extra, duplicate, or guessed request.
- **[Risk] Exact successful bodies are too large or contain secret material.**
  -> Stream content-addressed public-safe parser inputs, classify secret-bearing
  content before persistence, and fail the call rather than redact bytes while
  claiming exact authority.
- **[Risk] Free execution eligibility cannot be proven or changes mid-run.** ->
  Emit `capacity_blocked`/`not_fresh`, stop new calls, preserve committed state,
  and wait for new trusted evidence; never fall back to a paid service.
- **[Risk] A call crosses the terminal observation seal.** -> Exclude it from
  the sealed catch-up generation and place it only in a later parent-bound tail.
- **[Risk] A publication rerun makes a second Kaggle call.** -> After durable
  intent, permit only exact same-run publisher-job reconciliation and require
  marker/version/readback checks before upload admission.
- **[Risk] The hustle response cannot be classified safely.** -> Stop release;
  old diagnostics never authorize success or a broad support exclusion.
- **[Risk] A rerun cannot recover artifacts created by its prior attempt.** ->
  Reject primary and generic job reruns even when source inputs are present;
  operators must dispatch a new receipt-bound attempt-1 workflow. Permit only
  receipt-bound publish and dispatch reconciliation.
- **[Risk] A source run contains canonical and recovery discovery artifacts.**
  -> Prefer exactly one unexpired canonical receipt; otherwise accept only the
  source run's unique exact-attempt-one recovery receipt, and reject ambiguity.
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

1. Preserve both incident runs, current Kaggle, and old checkpoints as
   diagnostic fixtures only.
2. Retain the implemented stable-lane, exact-receipt, copy-plus-delta,
   redispatch, discovery, replay, and durable-publication transaction semantics.
3. Freeze exact schemas for RequestUniverse, public observations, field fate,
   field-level temporal authority, semantic diff, checkpoint-associated
   authority receipts, free execution, terminal catch-up, seal, and tail.
4. Implement provider-owned fixed-point discovery and its independent verifier;
   prohibit guessed Cartesian fan-out and unresolved terminal dispositions.
5. Persist and read back exact public-safe successful parser-input bytes or
   explicit bodyless packets before accepted parser-derived staging; commit
   staging only as a recoverable candidate until exact W2 operation readback.
6. Implement the closed public-value representation tables, both independent
   projections and equality, route-field receipts, and idempotent
   `W2OperationReceiptV1` before journal success.
7. Extend the existing checkpoint transaction to bind request/body/value/
   representation/W2/field/temporal/model authority while preserving its four
   states and artifact-ID restore rules.
8. Remove Nord and paid egress from production workflows; add trusted free-cost
   admission, runner-local direct canaries, post-run usage readback, and backend-
   neutral balanced execution slots.
9. Make the workflow produce and receipt-bind the request-closure inventory
   consumed by the independent full-publication scan.
10. Complete deterministic tests, exact-SHA CI, and one strictly-free direct
   nonpublishing smoke before any baseline call.
11. Start the new full-model authority as a fresh exact-SHA attempt-one chain
    with no old-source inputs and monitor every request/body/field/checkpoint
    generation.
12. Build and commit terminal catch-up with the frozen cutoff, overlap refresh,
    whole-history hole repair, frozen live snapshot, and observation seal.
13. Run independent full scan and create the exact assured bundle only when
    every stable model and authority is green.
13. Publish through the existing durable ledger, require version-specific all-
    resource digest readback, force-download that version, and complete manual
    read-only DuckDB/SQLite interrogation.
14. Prove a parent-bound TailGeneration and next-day daily `fresh`/`not_fresh`
    behavior when authoritative free capacity is available.

Rollback before a live extraction removes the new workflow and contract changes
as one atomic release. After a receipt-bound generation is committed, rollback
must retain readers for that transaction schema or explicitly resume from its
previous committed pointer; it must never rewrite the committed artifact.

## Open Questions

None. No unverified free execution or egress path is assumed; absent trusted
eligibility remains `capacity_blocked`. Live hustle evidence selects one
predefined handling branch; ambiguity is a release stop, not permission to
invent another recovery or support policy.
