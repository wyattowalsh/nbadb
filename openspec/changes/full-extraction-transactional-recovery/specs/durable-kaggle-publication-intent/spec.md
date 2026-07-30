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
- **WHEN** one dataset-wide pending intent matches the bundle and one current executor atomically claims it
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
