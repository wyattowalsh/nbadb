## ADDED Requirements

### Requirement: Redispatch occurs only after durable checkpoint commit
The system MUST dispatch an incomplete chain's next iteration only after the
current iteration has uploaded and verified its checkpoint and published the
receipt-bound committed next manifest.

#### Scenario: Current checkpoint is committed
- **WHEN** unresolved active lanes remain and checkpoint and manifest commit gates succeed
- **THEN** the system may attempt exactly one next-iteration dispatch

#### Scenario: Checkpoint transaction is incomplete
- **WHEN** any checkpoint build, upload, receipt, or committed-manifest gate fails
- **THEN** the system does not dispatch a child iteration

### Requirement: Dispatch returns the authoritative child identity
The system SHALL request workflow dispatch with exact run details and SHALL use
the returned positive workflow-run ID and URLs as the authoritative child
identity.

#### Scenario: Dispatch returns a valid identity
- **WHEN** the API response contains a positive run ID and matching run and HTML URLs
- **THEN** the system records that exact identity and reads that exact run for acknowledgement

#### Scenario: Dispatch response lacks exact identity
- **WHEN** the API response is empty, malformed, or contains inconsistent IDs or URLs
- **THEN** the system fails closed and does not infer the child from workflow-run inventory

### Requirement: Returned child provenance is independently verified
The system MUST read the exact returned child run and verify its ID, expected
chain-and-iteration title, `workflow_dispatch` event, exact trusted branch-tip
head SHA observed immediately before dispatch, and HTML URL before acknowledging
dispatch. The separately forwarded pinned source SHA remains the extraction
content-provenance identity.

#### Scenario: Exact child matches
- **WHEN** the returned run's complete provenance matches the planned child
- **THEN** the system acknowledges the child and exposes its run ID and URL

#### Scenario: Exact child provenance differs
- **WHEN** any run ID, title, event, trusted branch-tip head SHA, or URL differs
- **THEN** acknowledgement fails and cleanup attempts to cancel the unacknowledged child

### Requirement: Redispatch remains idempotent
Before dispatch, the system SHALL inspect exact-title history and SHALL refuse a
new child unless every existing matching run is completed with exactly
`failure`, `cancelled`, `timed_out`, or `action_required`. It MUST list complete
workflow history without a result-capping API search filter and MUST select
`workflow_dispatch` events locally.

#### Scenario: Blocking child already exists
- **WHEN** exact chain-and-iteration history contains an active or successful matching child
- **THEN** the system refuses duplicate dispatch and reports the blocking run identities

#### Scenario: Only explicitly replaceable history exists
- **WHEN** all exact-title predecessors are completed with `failure`, `cancelled`, `timed_out`, or `action_required`
- **THEN** the system may create one replacement child subject to all other gates

#### Scenario: A nonreplaceable terminal conclusion exists
- **WHEN** an exact-title predecessor is completed with success, neutral, skipped, stale, an absent conclusion, or an unknown conclusion
- **THEN** the system blocks redispatch before enqueueing a child

#### Scenario: Non-dispatch history shares the child title
- **WHEN** an unfiltered workflow inventory contains a same-title run from another event
- **THEN** redispatch ignores that row only after evaluating its local event field

### Requirement: Dispatch preserves source and manifest provenance
The system MUST verify the pinned source SHA, trusted branch ancestry, workflow
file blob, committed manifest artifact identity, iteration budget, and all
forwarded extraction inputs before posting the child payload.

#### Scenario: Workflow source is unchanged
- **WHEN** the checked-out source, trusted branch workflow blob, and committed manifest all match their expected provenance
- **THEN** the system forwards the exact chain and extraction inputs to the child

#### Scenario: Source or workflow definition drifts
- **WHEN** ancestry, checked-out SHA, workflow blob, or committed manifest identity differs
- **THEN** the system blocks dispatch

### Requirement: Unacknowledged children receive bounded cleanup
The system SHALL install exit and signal cleanup before posting dispatch and
SHALL attempt to cancel the exact returned child if the parent exits before
acknowledgement.

#### Scenario: Parent fails after parsing child identity
- **WHEN** dispatch created a child but exact provenance validation or a later acknowledgement step fails
- **THEN** cleanup attempts to cancel that exact run ID

#### Scenario: Dispatch may exist but response cannot be parsed
- **WHEN** the POST may have succeeded but no exact child ID can be extracted
- **THEN** a bounded run-inventory comparison may be used only to identify cancellation candidates and never to acknowledge a child

### Requirement: Dispatch acknowledgement is observable
The system SHALL expose the exact child run ID and URL as job outputs and record
them in the workflow summary.

#### Scenario: Child is acknowledged
- **WHEN** exact returned identity and provenance checks pass
- **THEN** operators and later automation receive the same positive child run ID and URL

### Requirement: Dispatch-only reruns consume the exact prior-attempt receipt
The dispatch job MAY reconcile a failed dispatch on a later run attempt only
from the immutable committed-manifest receipt exposed by checkpoint outputs.
The manifest artifact name MUST encode the current workflow run, the exact next
iteration, and a positive artifact attempt no greater than the current
`run_attempt`. The owner run's current attempt and source SHA, and the direct
artifact ID, digest, size, expiry, name, and workflow provenance MUST match.

#### Scenario: Prior-attempt committed receipt remains available
- **WHEN** a dispatch-only rerun receives an exact artifact from an earlier positive attempt of the current run and all receipt provenance matches
- **THEN** it may continue through idempotent child admission and dispatch acknowledgement

#### Scenario: Receipt claims a future or different identity
- **WHEN** the artifact name claims another run, a non-next iteration, or an attempt greater than the current run attempt
- **THEN** redispatch fails before using the artifact

#### Scenario: Full rerun deleted the immutable receipt
- **WHEN** the exact checkpoint output artifact is absent or its REST identity no longer matches
- **THEN** redispatch fails closed and does not synthesize a current-attempt artifact name
