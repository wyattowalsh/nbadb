## ADDED Requirements

### Requirement: Fresh full-model publication gates recurring production

Recurring production MUST remain disabled until one brand-new attempt-one full
extraction from the exact reviewed source and active complete model authority has
produced an initial cumulative Kaggle version. Admission MUST verify that exact
positive version through a complete paginated, streamed SHA-256 readback and
MUST bind it to the initial assurance, model authority, source, cutoff,
publication ledger, schemas, counts, values, and dynamic inventory. The current
incomplete public dataset MUST NOT serve as a production recurring parent.

#### Scenario: Only the current incomplete Kaggle version exists

- **WHEN** recurring implementation is otherwise locally green but no fresh full-model initial publication and exact readback receipt exists
- **THEN** recurring publication remains disabled and the current public version is diagnostic evidence only

#### Scenario: The new initial version is read back completely

- **WHEN** one fresh exact-SHA full extraction publishes an exact positive version whose complete remote bytes and assurance match the active model authority
- **THEN** that immutable version becomes eligible for exact-parent recurring admission

### Requirement: Recurring admission uses one exact public parent

Before daily, monthly, or opportunistic candidate work begins, the system MUST
reconcile any unresolved publication intent and MUST resolve the newest
admissible exact positive Kaggle version from validated marker/version equality
and stabilized current dataset metadata. It MUST pass that version explicitly to
verified-baseline download, force-download and stream-verify the complete API
inventory, install a fresh owner-only immutable parent root, and create the
candidate separately. The repository and Kaggle dataset SHALL be the only source
and dataset authorities.

#### Scenario: A latest cache directory exists

- **WHEN** a local cache or latest alias exists but no exact positive version and complete readback receipt are available
- **THEN** recurring admission fails before candidate mutation or provider work

#### Scenario: The workflow omits the exact version argument

- **WHEN** verified-baseline download is invoked without the resolved positive `--dataset-version N`
- **THEN** the workflow fails before extraction and emits a nonfresh status rather than guessing a parent

#### Scenario: A previous upload is unresolved

- **WHEN** the GitHub Deployment ledger contains one unresolved current publication intent
- **THEN** the system reconciles that exact intent before selecting a parent, building a candidate, or invoking Kaggle again

#### Scenario: A second authority is configured

- **WHEN** admission depends on a private repository, GHCR/OCI package, private baseline, remote generation pointer, table maximum, or `_pipeline_watermarks`
- **THEN** validation rejects that source as parent or cutoff authority

### Requirement: Each logical update owns a stable identity and disposable candidate

Admission MUST freeze `update_transaction_id` from the original logical
scheduler demand, exact parent, cutoff/as-of, and observation window before
candidate or publication-intent derivation. The ID MUST remain stable across run
attempts, child continuations, and cross-run recovery. Every later logical update
MUST receive a new ID even when it uses the same cutoff or produces equal NBA
table bytes. The system SHALL construct one isolated candidate bound to that ID
without mutating the verified parent.

#### Scenario: The same logical update resumes in another run

- **WHEN** parent, cutoff/window, scheduler demand, request universe, and transaction identity match the immutable original update
- **THEN** recovery preserves the original `update_transaction_id` and candidate authority

#### Scenario: A later update has equal table data

- **WHEN** a later admitted logical update has the same cutoff or semantically equal NBA tables
- **THEN** it receives a distinct `update_transaction_id` and is not treated as recovery of the earlier transaction

#### Scenario: Candidate construction stops midway

- **WHEN** extraction, replacement, transform, export, scan, or assurance does not complete
- **THEN** the candidate remains non-authoritative and the exact Kaggle parent remains unchanged

### Requirement: Every recurring plan closes a three-part temporal scope

The system MUST compile `RecurringUpdatePlanV1` and any `TailGenerationV1` as
the deterministic deduplicated union of: exact parent/request/field
cutoff-to-as-of catch-up; conservative endpoint-specific overlap for corrections
and late changes; and explicit older request/game/entity/route/field identity-gap
repair. Event cutoff, each request/field observation, the accepted observation
window, and final seal MUST remain distinct. Missing trustworthy observation
authority MUST cause whole-scope refresh or incompleteness, never a guessed
watermark.

#### Scenario: Daily planning closes the expected prior day

- **WHEN** a scheduled daily demand targets the expected prior NBA calendar day in the configured timezone
- **THEN** the frozen plan includes all three scope components, current/open-season and active-entity closure, every applicable route, and active-live roots through the target as-of

#### Scenario: Monthly planning performs deeper repair

- **WHEN** a monthly demand is compiled
- **THEN** its plan includes daily closure, deeper recent-season season-local discovery, and a whole-history audit of request, game, entity, route, field identity, field-introduction, and internal-gap evidence

#### Scenario: Opportunistic demand targets a newer cutoff

- **WHEN** a faster refresh is requested while genuinely free capacity and the complete proof budget are available
- **THEN** it uses the same three-part closure and cannot weaken or supersede queued deeper scope

#### Scenario: A provider-owned foundation is valid empty

- **WHEN** a dependent endpoint's exact foundation response is present, committed, schema-valid, and contains zero rows
- **THEN** the dependent scope closes as typed-zero complete and no guessed provider call is scheduled

#### Scenario: A dependency is missing or partial

- **WHEN** required game, player, team, lineup, matchup, cumulative workload, request observation, or field observation evidence is absent, malformed, partial, or unreceipted
- **THEN** the request universe remains incomplete and no Cartesian, default-value, or table-maximum request is synthesized

### Requirement: One durable coordinator coalesces all recurring demand

Daily, monthly, and opportunistic workflows MUST submit immutable demand records
to one durable cross-workflow coordinator. The coordinator MUST retain the
newest required cutoff, union deeper scopes and explicit gap repairs, coalesce
redundant queued demand, admit at most one active candidate/writer, record every
union or supersession decision, and prove no older required cutoff remains in an
unaccounted backlog.

#### Scenario: Monthly demand arrives during a daily transaction

- **WHEN** a deeper monthly scope arrives while one daily candidate is active
- **THEN** the coordinator preserves the active transaction identity, queues or unions the deeper scope by immutable rule, and does not erase next-day daily freshness

#### Scenario: Opportunistic demand is redundant

- **WHEN** a queued or active demand already closes the opportunistic cutoff and scope
- **THEN** the coordinator coalesces the redundant demand with a durable decision receipt and does not create a second writer

#### Scenario: Recovery observes a newer queued cutoff

- **WHEN** the coordinator resumes after interruption with an active immutable transaction and a newer compatible demand
- **THEN** it preserves the active transaction, retains the newest queued cutoff, and never mutates the active parent or publication intent in place

### Requirement: Successful provider data include exact public parser-input authority

For every successful body-bearing provider response, the system MUST capture
the exact parser-input body before decoding or parsing and MUST durably preserve
the bytes, full SHA-256, length, logical invocation, ordered provider-call
occurrence, retry attempt, canonical request identity, output-changing
parameters, endpoint, result name and ordinal, canonical route, source row
ordinal, ordered headers or nested paths, values and types, null/empty/presence
state, provider authority, observation provenance, and committed body/logical/
result/route/staging receipts. A declared provider with no parser input MUST
instead carry an explicit bodyless disposition.

#### Scenario: One response contains several result sets

- **WHEN** one logical call returns multiple ordered provider result packets
- **THEN** one logical receipt closes the declared ordered result/route receipts without requiring one logical root per table

#### Scenario: A valid additive field appears

- **WHEN** a successful response contains a header or nested path absent from the reviewed semantic contract
- **THEN** its identity, ordinal, value, presence, request, and provenance land in the public-safe typed lossless drift surface and semantic model assurance remains blocked pending review

#### Scenario: A result is present but empty

- **WHEN** the provider returns a declared result packet with valid headers and zero rows
- **THEN** the system records present-empty distinctly from optional-absent, failure, blocked, or unavailable

#### Scenario: A required public body is missing

- **WHEN** a body-bearing provider occurrence has parsed results but its exact parser-input body or verified readback receipt is absent
- **THEN** extraction completion, resume, assurance, export, and publication fail for that occurrence

#### Scenario: Sensitive transport data are observed

- **WHEN** cookies, authorization data, request headers, proxy or VPN details, credentials, or unrestricted error-body content reach a public body, landing, receipt, diagnostic, export, metadata, or log boundary
- **THEN** the boundary fails before persistence or publication

### Requirement: Request-owned source scopes are replaced transactionally

Every mutable route MUST declare an exact request-owned source-scope key. Before
opening a DuckDB replacement transaction, the system MUST have a complete
schema-valid replacement set and terminal request receipts. A successful request
SHALL atomically apply corrections, insertions, deletions, provider-valid
duplicate multiplicity, and explicit present-empty deletion. A missing frame or
unreceipted empty result MUST NOT authorize deletion. Journal, watermark, or
cutoff authority MUST advance only after committed receipt readback and required
stable dependent rebuilds.

#### Scenario: A previously published row disappears upstream

- **WHEN** a complete refresh of the same request-owned scope no longer returns that row
- **THEN** the candidate removes it while leaving every out-of-scope historical row unchanged

#### Scenario: Extraction returns no frame without valid-empty evidence

- **WHEN** a mutable request has no schema-valid complete replacement set or explicit provider present-empty receipt
- **THEN** the transaction does not delete prior rows and recurring assurance remains incomplete

#### Scenario: Replacement fails after beginning

- **WHEN** any deletion, insertion, multiplicity, receipt, or dependent-rebuild check fails
- **THEN** the transaction rolls back, the candidate is discarded as authority, and no journal/watermark/cutoff advances

### Requirement: Candidate output and four-format resource inventory are complete

The system MUST rebuild every convention-discovered affected stable output,
materialize schema-valid empty outputs, export DuckDB, Parquet, SQLite, and CSV,
and freeze a resource manifest derived from active staging and transform
registries. DuckDB and Parquet MUST have complete logical type/value equality.
All four formats MUST have ordered-schema and row-count parity, and SQLite/CSV
MUST satisfy explicitly defined normalization-projected decoded value parity.
Product logic MUST NOT hard-code a table or resource denominator.

#### Scenario: No conditional lossless table is materialized

- **WHEN** neither conditional typed lossless route was validly observed
- **THEN** the frozen manifest contains only the runtime-derived base inventory

#### Scenario: One or both conditional surfaces are materialized

- **WHEN** valid stats or live drift is observed
- **THEN** the frozen manifest adds exactly the observed conditional tables and declared resources without changing unobserved inventory

#### Scenario: A transform returns valid empty

- **WHEN** a stable transform succeeds with its declared schema and zero rows
- **THEN** the candidate publishes that empty output instead of retaining stale rows

#### Scenario: Convenience values do not decode to the canonical row

- **WHEN** SQLite or CSV has matching schema and row count but normalization-projected decoded values diverge from DuckDB/Parquet authority
- **THEN** format parity and publication assurance fail

### Requirement: Every recurring execution emits truthful freshness status

The system MUST emit canonical `RecurringRunStatusV1` from an `if: always()` or
trap-style finalizer, including failures before extraction. The receipt MUST bind
the expected prior NBA calendar day and timezone, provider-availability cutoff,
scheduled deadline, actual completion, parent version/cutoff, latest assured
remote cutoff, transaction/coordinator identity, `fresh` or `not_fresh`, reason
class, and no-mutation proof. Workflow success MUST NOT imply freshness.

#### Scenario: Exact parent resolution fails

- **WHEN** the workflow fails before candidate creation because the parent version is missing or invalid
- **THEN** the finalizer emits `not_fresh` with parent-admission reason and proof that no provider or Kaggle mutation occurred

#### Scenario: A no-game day is completely closed

- **WHEN** calendar/provider evidence and the full request universe prove no game or other missing update through the expected day
- **THEN** the receipt may report `fresh` even though NBA table data are semantically unchanged

#### Scenario: A job exits successfully after a late or partial update

- **WHEN** the newest assured remote cutoff does not meet the expected day or any required closure remains incomplete
- **THEN** `RecurringRunStatusV1` reports `not_fresh` regardless of workflow conclusion

### Requirement: UpdateAssuranceV1 gates recurring publication

The system MUST issue one canonical `UpdateAssuranceV1` binding the exact parent
and fingerprint, stable `update_transaction_id`, coordinator demand, source SHA,
mode, cutoff/as-of/observation-window/seal, three-part request universe, logical/
result/route/staging receipt closure, typed-zero evidence, observation and field
conservation, replacement transaction, stable model attestations, full scan,
four-format identities/parity, free-execution admission, dynamic resource
manifest, and `RecurringRunStatusV1`. Missing or conflicting evidence MUST fail
assurance, and local assurance MUST NOT assert DATA-GREEN.

#### Scenario: Structural census is green but semantic review is incomplete

- **WHEN** route and table inventories compile but field/model/metric dispositions retain blockers
- **THEN** `MODEL-GREEN` remains red and recurring publication is not admitted

#### Scenario: Execution is cancelled

- **WHEN** cancellation occurs before the candidate and its exact proof set are complete
- **THEN** the transaction is non-success and no partial candidate or local report becomes publication or DATA-GREEN authority

#### Scenario: Assurance is regenerated from one frozen candidate

- **WHEN** `UpdateAssuranceV1` is independently generated twice from unchanged canonical inputs
- **THEN** both instances have identical semantic identity and digests

### Requirement: Production control is Actions-only and proven free

GitHub Actions SHALL be the only production initial, catch-up, daily, monthly,
opportunistic, publication, and final-closeout control plane. Notebooks, local
schedulers, fallback scripts, and out-of-band clients MUST NOT mutate Kaggle.
Every provider-working execution MUST carry current `FreeExecutionAdmissionV1`
for authoritative zero-cost eligibility and NBA reachability. A paid proxy, VPN,
subscription, trial, or inferred device capacity MUST NOT be required or used as
a fallback.

#### Scenario: No genuinely free NBA-reachable path is proven

- **WHEN** zero-cost eligibility or NBA reachability cannot be independently verified at the point of use
- **THEN** the run emits `capacity_blocked` and `not_fresh`, performs no provider or Kaggle mutation, and does not reduce coverage

#### Scenario: An out-of-band writer is discovered

- **WHEN** a notebook, stale workflow, local script, or non-Actions client can mutate the production Kaggle dataset
- **THEN** writer-inventory assurance fails and production publication remains disabled

### Requirement: Every distinct assured transaction creates one cumulative version

Automated publication MUST use the non-cancelling `nbadb-kaggle-publish` FIFO
mutex and dataset-specific GitHub Deployment ledger. It MUST recheck the exact
parent, stable transaction, source, executor, and candidate assurance; record
durable `pending` and verified `in_progress`; permit at most one unresolved
mutation; and create exactly one new cumulative Kaggle version for every
distinct fully assured transaction, including no-game or equal-table updates.
The bundle MUST include a truthful transaction-specific generation/assurance
resource so it is distinct without fabricating provider data.

Identity MUST be acyclic: freeze transaction/parent/cutoff/window, build the
truthful generation resource, freeze the candidate inventory under explicit
self-exclusion rules, derive `RecurringPublicationIntentV1`, and then stage the
marker and receipts.

#### Scenario: Retry finds exact success for the same intent

- **WHEN** recovery proves the exact same stable transaction and immutable intent already produced the exact verified remote version and inventory
- **THEN** it records or confirms success without another Kaggle mutation

#### Scenario: A distinct transaction has equal NBA table bytes

- **WHEN** a later fully assured transaction's NBA table data or cutoff equals the prior version
- **THEN** it still creates exactly one new cumulative version using its truthful transaction-specific resource

#### Scenario: Reconciliation evidence belongs to another transaction

- **WHEN** equal marker or bundle evidence has a different stable transaction or immutable intent identity
- **THEN** it cannot suppress the new transaction's mutation or be reconciled as its success

#### Scenario: Publication state is ambiguous

- **WHEN** marker, version, inventory, executor, claim, transaction, intent, or digest evidence is missing, divergent, cyclic, or unstable
- **THEN** every new mutation and successor transaction remains blocked

### Requirement: Exact remote readback closes publication

After a Kaggle submission, the publisher MUST resolve the exact positive version,
paginate the complete API file inventory, and stream every listed resource
through exact path, size, and SHA-256 verification one file at a time. It MUST
prove marker/version/source/assurance/schema/count/value equality and MUST record
ledger success only after a current executor/claim recheck. A submitted upload or
dataset version without complete readback MUST remain unverified.

#### Scenario: One remote resource is missing or mismatched

- **WHEN** complete pagination or streamed readback finds an absent, unexpected, duplicate, unsafe, size-mismatched, digest-mismatched, schema-mismatched, count-mismatched, or value-mismatched resource
- **THEN** publication success is not recorded and later execution is reconciliation-only

#### Scenario: Exact readback succeeds

- **WHEN** every remote resource and publication identity matches the frozen candidate and current executor remains valid
- **THEN** the ledger may close the immutable intent with that exact positive version

### Requirement: Recovery evidence is bounded and non-authoritative

Local checkpoints, GitHub artifacts, and caches MAY preserve same-transaction
progress or diagnostics. They MUST bind the exact parent, source, stable
transaction, cutoffs/window/seal, request universe, coordinator demand, and
candidate identity; MUST expire without affecting public authority; and MUST NOT
serve as a second parent or publication authority.

#### Scenario: All recovery artifacts expire

- **WHEN** a transaction has no unresolved remote intent and its local recovery artifacts are unavailable
- **THEN** a later logical transaction starts from the newest exact verified Kaggle parent without loss of public authority

#### Scenario: A checkpoint identity drifts

- **WHEN** parent, source, transaction, cutoff/window/seal, request universe, coordinator, candidate, or receipt identity differs
- **THEN** the checkpoint is rejected and cannot become a later parent

### Requirement: Performance optimization preserves complete proof

Batching, streaming, partitioning, connection reuse, coalescing, and bounded
concurrency MAY reduce runtime, but every optimization MUST preserve the frozen
request universe, three-part temporal scope, route/result/field denominator,
retry/failure classification, typed-zero and replacement semantics, stable
transaction identity, deterministic receipts, four formats, and final inventory.

#### Scenario: A faster plan samples or caps the provider surface

- **WHEN** an optimization omits valid scopes, drops packets, guesses dependent workloads, weakens receipts, or skips a format/readback layer
- **THEN** the plan is rejected even if its wall-clock runtime is lower

#### Scenario: The exact request universe reaches its native ceiling

- **WHEN** planning contains 250,000 exact committed calls or route-dispatch
  rows
- **THEN** the store persists bounded immutable partitions and a compact scalar
  manifest/execution-plan header rather than one monolithic detailed JSON graph
- **AND** every partition and row is strict-replayed in ordinal order with exact
  count/root, range, byte, route/scope-position, and content-address receipts
- **AND** no caller-sized control budget, duplicate replacement-binding array,
  sampling, truncation, or silent partition omission reduces the denominator.

### Requirement: DATA-GREEN requires initial and accepted successor evidence

The active request, lossless landing, replacement, and model contracts MUST
invalidate the current incomplete Kaggle dataset and older checkpoints as
completeness authority. `DATA-GREEN` MUST remain open until one fresh exact-SHA
attempt-one full extraction passes populated row-level terminal assurance,
publishes and exactly reads back a new full-model cumulative version, and one
real exact-parent daily transaction creates and exactly reads back its own next
cumulative version with truthful expected-day freshness. Monthly and
opportunistic coordination MUST also have bounded nonpublishing acceptance proof.

#### Scenario: The initial version is verified but no successor exists

- **WHEN** the new full-model baseline has exact remote readback but no accepted exact-parent daily successor version and freshness receipt
- **THEN** it is an admissible recurring parent but DATA-GREEN remains open

#### Scenario: A no-game successor is fully assured

- **WHEN** one distinct exact-parent daily transaction proves complete no-game closure and semantically unchanged NBA tables
- **THEN** it must still create and exactly read back its own cumulative version before it can satisfy successor acceptance

### Requirement: Newest exact successor is redownloaded immutably

After required publication readback, the system MUST force-download the newest
exact successor `/versions/N` into a fresh empty owner-only root, validate safe
complete inventory and streamed digests as `ImmutableVersionReadbackV1`, and make
the dataset root non-writable. All query output, temporary databases, decoder
caches, challenges, and receipts MUST reside in a separate evidence root. The
complete immutable tree MUST have identical before/after hashes without
post-hoc exclusions.

#### Scenario: Verification writes a sidecar into the dataset root

- **WHEN** inspection creates a WAL, journal, cache, metadata file, query output, or other new/changed path beneath the immutable dataset root
- **THEN** immutable verification fails and DATA-GREEN remains open

#### Scenario: A latest alias or mutable cache is downloaded

- **WHEN** redownload uses an unversioned latest/cache authority or a nonempty mutable destination
- **THEN** `ImmutableVersionReadbackV1` is rejected

### Requirement: Human verification is authenticated and genuinely manual

Automation MUST generate `HumanVerificationChallengeV1` bound to the exact
successor version/readback digest, nonce, and nonempty coverage matrix spanning
raw/lossless data, games, players, teams, rosters, box scores, play-by-play,
shots, standings, draft, aggregates, analytics, live snapshots, earliest/recent
eras, unavailable/zero-row edges, field-introduction/internal-gap boundaries,
and the updated window. A trusted handoff MUST independently record the human
actor. The human MUST manually inspect DuckDB read-only with external access
disabled, SQLite with `mode=ro&immutable=1`, independently decode Parquet and
CSV, inspect the exact Kaggle version page/inventory, record observations and
query-result digests, and acknowledge the nonce and audit time.

#### Scenario: Automation attempts to author the attestation

- **WHEN** an agent, headless workflow, default-success path, `--yes` flag, or workflow-populated acknowledgement supplies the human observations or acceptance
- **THEN** `HumanVerificationReceiptV1` is invalid even if automated hashes pass

#### Scenario: The authenticated human completes all four formats

- **WHEN** the trusted human supplies nonce-bound observations and query-result digests for DuckDB, SQLite, Parquet, CSV, and the exact version page while immutable hashes remain unchanged
- **THEN** automation may validate and preserve the receipt but cannot rewrite its human-authored content

### Requirement: Documentation and metadata match exact remote reality

After remote readback and human inspection, the system MUST generate
`DocsMetadataParityV1` proving authored docs, generated schema/lineage/catalog,
Kaggle metadata, model/temporal/provenance descriptions, cadence, limitations,
and experimental labels match the frozen registries, assurance receipts, and
exact remote successor version/inventory. Documentation MUST NOT claim current/
recent-window planning, full history, freshness, parity, or DATA-GREEN beyond the
implemented and receipt-backed behavior.

#### Scenario: Authored cadence differs from coordinator receipts

- **WHEN** documentation claims a cadence, scope, freshness, model inventory, or limitation that diverges from frozen source or remote receipts
- **THEN** docs parity fails and final closeout remains blocked

### Requirement: DataGreenReceiptV1 is the only final DATA-GREEN authority

One Actions-only, non-Kaggle-writing closeout MUST validate and join the exact
upstream/model authority, fresh extraction/checkpoint/catch-up/scan, initial
publication/readback, accepted daily successor/version/readback/status,
coordinator/monthly/opportunistic proof, four-format parity, immutable newest
redownload, authenticated human receipt, docs parity, source/CI/free-admission,
and external rights evidence into `DataGreenReceiptV1`. It MUST fail for any
missing, stale, mismatched, self-asserted, locally substituted, or incomplete
proof. No local successor report SHALL set or imply `data_green=true`.

#### Scenario: A local successor report declares DATA-GREEN

- **WHEN** publication, newest-version redownload, human receipt, docs parity, or another final proof layer is absent
- **THEN** the local report remains candidate/assured-local and the final join rejects its DATA-GREEN claim

#### Scenario: Every immutable proof joins exactly

- **WHEN** the Actions-only closeout verifies every required receipt against the same source, authority, dataset lineage, versions, and terminal identities
- **THEN** it may emit the sole canonical `DataGreenReceiptV1`

### Requirement: Delivery uses exclusive ownership and receipt-backed joins

Implementation and release work MUST use dependency-safe packets with one
exclusive writer for each file or shared authority, MUST maximize independent
read-only or nonconflicting work in parallel, MUST resolve every dispatch before
its join, and MUST bind validation and delivery evidence to the exact reviewed
source tree. Shared generated surfaces, workflows, Git index operations, and
external mutations MUST be serialized.

#### Scenario: Two packets would edit the same shared hub

- **WHEN** otherwise independent workstreams require the same source file, generated tree, workflow, ledger, Git index, or publication authority
- **THEN** those writers are serialized while nonconflicting read-only work may continue in parallel

#### Scenario: A dispatched worker has not returned evidence

- **WHEN** a dependency join is reached with any child unresolved or without exact touched paths and validation evidence
- **THEN** the join remains blocked and partial dispatch is not reported as completion
