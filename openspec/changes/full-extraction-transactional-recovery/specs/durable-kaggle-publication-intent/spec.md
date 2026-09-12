## ADDED Requirements

### Requirement: Every production publisher uses a crash-durable external intent

Full-extraction, daily, and monthly GitHub Actions publishers MUST use the
GitHub Deployment publication ledger and MUST require a durable intent before
entering the Kaggle upload call. The local ledger mode MAY remain available for
non-production use, but it MUST NOT satisfy the durable-intent requirement.

#### Scenario: Production publisher reaches upload

- **WHEN** a full, daily, or monthly publisher has passed extraction, export, metadata, and applicable terminal-assurance gates
- **THEN** it requests the GitHub Deployment ledger and refuses upload unless an exact durable intent and execution claim are verified

#### Scenario: Durable mode is requested outside GitHub Actions

- **WHEN** required repository, run, attempt, workflow, actor, source, API, token, or job context is absent or malformed
- **THEN** the command fails before staging a new Kaggle upload attempt

### Requirement: Publication inventory cost is independent of historical depth

The ledger MUST resolve dataset state from a GraphQL deployment connection with
explicit `CREATED_AT DESC` ordering, a fixed two-deployment head, a fixed status
window, and a fixed stability observation count. REST list page order MUST NOT
be treated as a newest-head contract. The ledger MUST NOT scan, paginate, or
directly read every historical deployment. The complete cold scan request count
MUST remain constant when more than 100 older valid publications exist.

#### Scenario: Dataset has more than 100 resolved publications

- **WHEN** the two newest deployment heads are valid and all older deployments are resolved
- **THEN** the ledger examines only the fixed head window and performs the same bounded number of requests as it would for a short history

#### Scenario: Head inventory does not stabilize

- **WHEN** the final two canonical head observations differ, contain duplicate identities, violate timestamp chronology, or exceed a protocol window
- **THEN** the ledger fails closed without a Kaggle upload

### Requirement: Chronology is timestamp-bound

Deployment and status chronology MUST be derived from strict GitHub
`createdAt`/`created_at` receipts, with every GraphQL deployment summary
revalidated through its exact REST ID. Numeric deployment and status IDs MUST
be treated only as positive identities and MUST NOT establish temporal order.
The complete protocol-sized status set MUST be sorted locally; undocumented
REST response order MUST NOT be an admission dependency.

#### Scenario: Numeric IDs and timestamps disagree

- **WHEN** a lower numeric ID has the newer valid timestamp
- **THEN** the timestamp defines the current record

#### Scenario: Timestamps are equal or non-monotonic

- **WHEN** the bounded inventory cannot prove one strict chronology
- **THEN** the ledger rejects the inventory as ambiguous

### Requirement: The active publisher is independently admitted

Before creating an intent and again before admitting the Kaggle call, the ledger
MUST read the exact Actions run attempt, fully paginate its bounded job
inventory, directly re-read the unique publisher job ID, verify the job's active
state and source/workflow/actor identity, download the workflow definition at
the exact workflow SHA, and prove the publishing job has the shared
`nbadb-kaggle-publish` non-cancelling FIFO mutex. Production workflows MUST grant
`actions: read`, sufficient contents access, and `deployments: write`.
Dynamic Actions `run-name` text MUST NOT be confused with the workflow
definition name supplied by `GITHUB_WORKFLOW`.

#### Scenario: Exact executor and mutex match

- **WHEN** the current run attempt, workflow, actor, job, source, workflow bytes, and structural mutex all match Actions context
- **THEN** the ledger may issue or retain an exact publication intent

#### Scenario: Active job has a pending parent run

- **WHEN** the exact direct publisher job is `in_progress` with no conclusion while the parent run is `pending` or `in_progress`
- **THEN** executor admission treats the direct job receipt as the active authority

#### Scenario: Executor or mutex provenance differs

- **WHEN** the job is absent, inactive, cross-attempt, cross-workflow, cross-source, or does not own the exact shared mutex contract
- **THEN** the ledger fails before a deployment write or Kaggle upload

#### Scenario: Shared history contains another production publisher

- **WHEN** daily, monthly, or full publication reads a valid terminal status written by one of the other production workflows
- **THEN** the historical workflow is verified against its own authoritative definition while only the current executor is compared with current Actions context

### Requirement: Publication uses a verified pending-to-claimed transaction

The ledger MUST first durably verify one exact pending deployment for the
semantic publication intent. Immediately before `kagglehub.dataset_upload`, it
MUST create and durably verify one `in_progress` claim bound to a fresh nonce and
the exact current executor. The Kaggle call MUST be textually and behaviorally
adjacent to that successful claim.

#### Scenario: Pending intent and claim are stable

- **WHEN** one dataset-wide pending intent matches the bundle and the FIFO-serialized current executor creates and sequentially verifies its exact claim
- **THEN** exactly that executor may enter the Kaggle upload call

#### Scenario: Another unresolved intent exists

- **WHEN** the current head is a different pending or in-progress intent
- **THEN** the new bundle is blocked and the existing publication must be reconciled

#### Scenario: Claim changes before upload admission

- **WHEN** a stability read no longer identifies the exact deployment, nonce, status, or executor claim
- **THEN** no Kaggle upload occurs

### Requirement: Ambiguous writes are never blindly repeated

After an ambiguous deployment or deployment-status POST, the ledger MUST perform
bounded read-only recovery for the exact semantic receipt. It MUST NOT send a
second POST merely because the first response was lost or malformed.

#### Scenario: Ambiguous POST was accepted

- **WHEN** bounded stable reads find exactly one matching receipt
- **THEN** the transaction continues from that receipt without repeating the write

#### Scenario: Ambiguous POST cannot be resolved

- **WHEN** the matching receipt is absent, duplicated, unstable, or malformed
- **THEN** the ledger reports reconciliation required and does not retry the mutation

### Requirement: Default-branch identity is rechecked around claim admission

When default-head enforcement is enabled, the ledger MUST verify the exact
current default-branch ref before intent preparation and both before and after
claim publication. The expected head defaults to the frozen publication source,
but MAY be one separately supplied exact 40-character SHA already approved by
the full-extraction metadata-only-child verifier.

#### Scenario: Default head remains exact

- **WHEN** each REST ref receipt equals the configured expected head
- **THEN** publication may continue while the durable intent remains bound to the frozen data source

#### Scenario: Default head moves during preparation or claim

- **WHEN** any recheck observes another commit or malformed ref identity
- **THEN** the ledger fails before Kaggle upload

### Requirement: Direct publication resolution belongs to the current admitted execution

Immediately before a direct terminal success write, the ledger MUST obtain a
fresh current-executor receipt and require the execution being resolved to
match its workflow run ID, run attempt, publisher job identity, and executor
admission digest. The deployment MUST originate from that same workflow run.
The ledger MUST revalidate the latest exact deployment status, nonce, claim,
and executor commitments, then recheck the current executor immediately before
the success-status POST. The final exact remote claim observation MUST itself be
bracketed by active-executor observations so either a competing status published
during the first executor check or an executor becoming inactive during the
claim observation is rejected before the POST. Any observed ownership drift
MUST raise the pending-intent error and MUST perform no terminal success POST.
A later attempt in the same run MAY use the explicit reconciliation path after
exact remote evidence; it MUST NOT directly resolve the earlier execution. A
different run MUST NOT resolve or reconcile the intent.

The required non-cancelling FIFO publisher mutex MUST serialize every
repository-sanctioned terminal writer. GitHub exposes no conditional status
append that atomically spans Actions job liveness and Deployment status history,
so this sequential handshake MUST NOT be represented as atomic exclusion of an
arbitrary out-of-band status writer after the final claim observation.

#### Scenario: Exact current execution resolves

- **WHEN** run, attempt, job, admission digest, deployment origin, claim, nonce, and remote evidence all match fresh receipts
- **THEN** the ledger may write one terminal success status

#### Scenario: One executor field drifts

- **WHEN** any current or recorded run, attempt, job, admission digest, deployment origin, claim, or nonce differs
- **THEN** the ledger raises the pending-intent error and writes no success status

#### Scenario: A competing status appears during the final executor check

- **WHEN** the pre-write claim is stable but another valid status appears while the current executor is being reverified
- **THEN** the adjacent final remote observation rejects the drift and the ledger writes no success status

#### Scenario: The executor becomes inactive during the final claim observation

- **WHEN** the current executor becomes inactive after the first active check while the final exact claim is being observed
- **THEN** the adjacent final executor recheck rejects the drift and the ledger writes no success status

#### Scenario: A later attempt observes the prior execution

- **WHEN** another attempt of the same workflow run has exact remote evidence for the prior intent
- **THEN** direct resolution is denied and only the explicit same-run reconciliation path may close the intent

### Requirement: Assured publication input is verified before archive download

Before downloading the current run's assured-data archive, the publisher MUST
directly verify its exact positive artifact ID, name, `sha256:` digest, positive
size, unexpired state, archive URL, producing attempt one, and owner producing
head equal to current `GITHUB_SHA`. The owner run MUST be the current run. On the
initial execution its observed attempt MUST be one; on a later attempt, only the
dedicated same-run publication-reconciliation role may reuse the exact immutable
attempt-one authority. No later attempt may create or substitute an assured-data
authority. Only after that receipt and a final current-owner re-read pass may it fetch
archive bytes, verify the archive digest and safe member layout, and consume the
assurance manifest. Metadata validation after an already-started archive
download MUST NOT satisfy this gate.
The complete ZIP inventory MUST validate before extraction. Empty archives,
duplicate normalized member paths, absolute or traversing paths, symlinks,
non-regular special files, and destination collisions MUST fail before any
member is consumed.

#### Scenario: Assured-data receipt matches the current producer

- **WHEN** the direct artifact and owner-run receipts match the current run, exact attempt one, head, and expected upload outputs
- **THEN** the publisher may download and validate the archive

#### Scenario: Dedicated later publication reconciliation reuses attempt-one authority

- **WHEN** the explicit same-run publication-reconciliation role runs in a later attempt and the exact artifact receipt still proves the immutable attempt-one upload and current head
- **THEN** it may download that artifact for reconciliation without creating or selecting later-attempt assured data

#### Scenario: A later attempt tries to substitute assured data

- **WHEN** a later attempt presents an artifact produced outside attempt one or executes without the dedicated publication-reconciliation role
- **THEN** publication fails before reading archive bytes

#### Scenario: Assured archive layout is unsafe

- **WHEN** the downloaded ZIP is empty or contains a duplicate, absolute, traversing, symlinked, special, or colliding member
- **THEN** publication fails before extracting or consuming any member

#### Scenario: Assured-data provenance is missing or checked too late

- **WHEN** owner `H` is absent or mismatched, a receipt field differs, or archive download begins before receipt validation
- **THEN** publication fails before reading archive bytes

### Requirement: Terminal receipts survive GitHub status retention

A terminal success status MUST contain compact, full-length commitments to its
execution claim and resolution. It MUST remain independently verifiable from
the deployment payload, the retained current success status, exact executor
provenance, remote marker identity, exact Kaggle version, and readback
fingerprint after GitHub deletes prior statuses under its retention policy.

#### Scenario: Claim and success statuses are both retained

- **WHEN** both receipts are present
- **THEN** the success claim commitment must equal the recomputed in-progress claim and the resolution commitment must validate

#### Scenario: Only the current success status remains

- **WHEN** GitHub has removed the older in-progress status
- **THEN** the self-contained success receipt remains valid only when its full claim and resolution commitments recompute exactly

#### Scenario: Terminal commitment is truncated or altered

- **WHEN** the retained status omits or changes any claim, version, resolver, marker, or readback commitment
- **THEN** the ledger rejects the historical head

### Requirement: Exact remote evidence resolves publication

The ledger MUST mark success or reconciliation only after the existing Kaggle
marker or post-upload marker identifies the exact semantic intent, positive
version, complete resource inventory, and readback fingerprint. An unresolved
or nonmatching marker MUST block every new bundle.

#### Scenario: Exact remote marker already exists

- **WHEN** the marker, version, resources, and readback match the durable intent
- **THEN** the ledger records a verified terminal resolution and skips a new upload

#### Scenario: Upload outcome is unresolved

- **WHEN** a Kaggle call may have succeeded but exact marker and readback evidence are unavailable
- **THEN** the in-progress intent remains reconciliation-only and no later run creates a new bundle

### Requirement: Publisher integration preserves frozen-source provenance

The full-extraction publisher MUST bind its ledger intent to the terminal
assurance source SHA while passing the exact current default head approved by
its metadata-only-child check. Daily and monthly publishers MUST bind both
source and expected default head to their exact checked-out default-branch SHA.
All three MUST run inside the same dataset-wide FIFO publisher group.

#### Scenario: Full publication runs at the frozen source

- **WHEN** default HEAD equals the extraction source
- **THEN** the source and approved-head receipts contain that same SHA

#### Scenario: Publication reconciliation runs from one approved metadata child

- **WHEN** the existing verifier proves one exact byte-identical metadata-only child
- **THEN** the intent remains bound to the extraction source and the ledger independently rechecks the approved child as current HEAD

#### Scenario: Any publisher omits durable wiring

- **WHEN** a production upload lacks deployment permissions, the GitHub token, source/head environment, durable-ledger mode, or durable-intent requirement
- **THEN** workflow contract validation fails

### Requirement: Durable intent permits only same-run publication reconciliation

Before a durable pending or in-progress intent exists, a failed zero-active
publication replay MAY be replaced only after proving there is no active writer
and no unresolved ledger state. After a valid durable intent exists, the system
MUST NOT start a fresh publication run or new bundle; reconciliation MUST rerun
only the exact publisher job ID in the original workflow run and reuse its exact
assured bundle and intent.

#### Scenario: Publication fails before durable intent

- **WHEN** the publisher is terminal, no writer is active, and stable ledger evidence proves no pending or in-progress intent
- **THEN** one new receipt-bound zero-active publication replay may be admitted

#### Scenario: Durable intent already exists

- **WHEN** the exact publication ledger has reached validated pending or in-progress state
- **THEN** recovery is limited to the exact publisher job in the same run and no competing run may call Kaggle

#### Scenario: Durable success precedes a later workflow failure

- **WHEN** exact marker, version, inventory, readback, and ledger success are valid but metadata follow-up failed
- **THEN** same-run reconciliation skips Kaggle and resumes only post-publication work

### Requirement: Publication cache recovery is run-scoped

The full-extraction publisher MUST restore secondary publication state only from
the cache prefix `nbadb-kaggle-publication-state-${run_id}-`. A repository-wide
or cross-run prefix MUST NOT be used as publication authority or reconciliation
input.

#### Scenario: Current-run cache is available

- **WHEN** an exact publisher-job rerun restores a cache entry under its own run-scoped prefix
- **THEN** the cache may assist reconciliation subject to the durable ledger and remote evidence

#### Scenario: Only another run's cache exists

- **WHEN** the current run has no matching cache but a repository-wide search would find another run's state
- **THEN** the publisher ignores that cache and resolves state from durable and remote receipts

### Requirement: Metadata-only publication children receive explicit exact-SHA CI

After verified publication, the workflow MUST resolve metadata head `M` as the
frozen source when checked-in metadata is unchanged or as exactly one direct,
non-merge, metadata-only child of that source when it changes. For a distinct
`M`, the workflow MUST explicitly dispatch CI, directly verify the returned run
identity and `head_sha=M`, and require successful `workflow-lint`, `lint`,
`metadata`, `typecheck`, `docs`, and `test` jobs before closeout.

#### Scenario: Metadata is unchanged

- **WHEN** remote verification produces no checked-in metadata diff
- **THEN** `M` equals the frozen source and no metadata child is created

#### Scenario: One metadata-only child is required

- **WHEN** verified remote inventory reproducibly changes only approved metadata files
- **THEN** the single child is explicitly CI-dispatched and all six required jobs must succeed at its exact SHA

#### Scenario: Child shape or CI provenance differs

- **WHEN** the child is a merge, has another parent or file change, is not byte-reproducible, or its returned CI run or jobs do not bind exact `M`
- **THEN** publication closeout fails without approving the child head

### Requirement: DATA-GREEN requires exact-version manual interrogation

Exact remote readback and publication-ledger success MUST identify one positive
Kaggle version, but they MUST NOT alone close DATA-GREEN. That exact version
MUST be force-downloaded into a new owner-only local root with a complete
inventory/digest receipt. Manual verification MUST open DuckDB read-only with
external access disabled and SQLite immutable/read-only, run integrity,
foreign-key, schema, row, key, parser-input body/bodyless, stable-output, and
experiment-admission queries, and prove unchanged pre/post file-tree hashes.

#### Scenario: Stable data pass but an experiment is withheld

- **WHEN** every stable source/silver/gold contract passes and a separately versioned fitted experiment has a valid withheld disposition
- **THEN** the stable publication remains eligible and the manual report records the experiment without turning the stable release red

#### Scenario: The exact version is not manually downloaded

- **WHEN** remote readback succeeds but local verification uses generic latest, a prior cache root, or no version-qualified download
- **THEN** publication may remain durably resolved but DATA-GREEN and final closeout remain open

### Requirement: Production publication has one public control topology

The public nbadb repository and existing Kaggle dataset MUST be the only source
and dataset authorities. GitHub Actions MUST be the only production initial,
catch-up, daily, monthly, and publication control plane. The publication ledger
MUST reject a private repository/package/state service, hosted notebook cron,
or alternate scheduler as required admission or mutation authority.

#### Scenario: A second production publisher exists

- **WHEN** another repository, hosted notebook, or service can call Kaggle outside the verified GitHub Actions publisher transaction
- **THEN** production admission fails before durable intent or mutation

### Requirement: Initial full-model publication consumes complete authority

The initial choice-B publisher MUST consume an assured artifact produced only by
a fresh exact-SHA attempt-one baseline and committed TerminalCatchup generation.
Its identity MUST bind the independently verified RequestUniverse, public
body/bodyless inventory, field-fate and field-temporal authority, MODEL-GREEN,
checkpoint transaction, observation seal, full scan, free-execution admission,
and post-run zero-cost usage receipt. Existing Kaggle data and old checkpoints
MUST NOT satisfy any of those inputs.

#### Scenario: The assured bundle omits catch-up or free-cost evidence

- **WHEN** any baseline, body, field, model, checkpoint, catch-up/seal, scan, or exact zero-cost receipt is absent or mismatched
- **THEN** publication fails before durable intent or a Kaggle call

#### Scenario: Existing Kaggle resources match some desired outputs

- **WHEN** remote resources predate the complete full-model authority contracts
- **THEN** they remain comparison evidence only and do not reduce initial extraction or assurance scope
