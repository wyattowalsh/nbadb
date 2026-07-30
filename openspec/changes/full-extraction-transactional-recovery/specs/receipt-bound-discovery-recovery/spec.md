## ADDED Requirements

### Requirement: Every independently rerunnable job validates one source-mode contract
Every full-extraction job MUST check out the exact pinned source and MUST run
the same repository-owned attempt/source validator immediately afterward,
before credentials, network calls, artifact reads or writes, state promotion,
dispatch, assurance, or publication. The extract job MAY record its mandatory
job deadline before checkout, but no other meaningful step may precede the
validator.

#### Scenario: First workflow attempt starts fresh
- **WHEN** attempt 1 has no inline manifest, lane source, resume source, or lane artifact metadata
- **THEN** every job classifies the inputs as one fresh source mode

#### Scenario: First workflow attempt uses one manual or cross-run source
- **WHEN** attempt 1 supplies only an inline manifest, one complete lane-source contract, or one resume source
- **THEN** the validator accepts exactly that mutually exclusive mode

#### Scenario: Source inputs are mixed or incomplete
- **WHEN** inline, lane, and resume modes overlap; lane artifact fields are orphaned; receipt ID and digest are asymmetric; or a source ID is invalid or equals the current run
- **THEN** every job fails before using that input surface

#### Scenario: Full or partial workflow rerun is requested
- **WHEN** `run_attempt` exceeds 1 for the primary guard or any generic job
- **THEN** the validator rejects the job before querying duplicate history because attempt artifacts may already have been replaced

#### Scenario: Publication or dispatch reconciliation reruns
- **WHEN** only the publish job or dispatch job is rerun after attempt 1
- **THEN** its dedicated reconciliation role may proceed after complete input validation and stable duplicate admission

### Requirement: Shared attempt validation cannot be bypassed by job reruns
All 15 jobs SHALL have read access to Actions metadata and SHALL execute the
shared validator after exact-SHA checkout even when GitHub reruns only one
failed or specifically selected job. The primary guard SHALL use a
concurrency key derived only from chain and iteration with `queue: max` and
`cancel-in-progress: false`. Every non-guard job MUST also have the primary
guard in its transitive dependency closure.

#### Scenario: A downstream job is rerun without workflow guard
- **WHEN** GitHub starts one independently rerunnable downstream job
- **THEN** that job executes the same attempt/source gate before credentials, NBA or VPN access, state mutation, assurance, dispatch, or publication

#### Scenario: Targeted smoke assurance is rerun
- **WHEN** the targeted-smoke assurance job starts independently
- **THEN** it first checks out the pinned source and executes the shared gate

#### Scenario: Two primary guards contend for one chain iteration
- **WHEN** one guard is active or pending and another guard enters the same concurrency group
- **THEN** the later guard queues without cancelling or replacing the existing pending member

#### Scenario: A new root-level downstream job is introduced
- **WHEN** a workflow change adds a non-guard job whose dependency closure does not contain the primary guard
- **THEN** the workflow contract fails even if that job contains its own partial attempt validator

### Requirement: Exact-title workflow admission uses stable complete inventory
On attempt 1 the primary guard, and on a permitted reconciliation rerun that
specific job, SHALL observe the complete paginated dispatched-run inventory
three times without using an API search parameter that caps the result set.
Each observation MUST have stable page totals and unique positive run IDs, every
entry MUST expose a valid nonempty event, and the final two normalized
unfiltered observations MUST be identical. Admission SHALL then select
`workflow_dispatch` events locally, exclude the current run, and compare the
exact chain-and-iteration display title. These calls SHALL send the recommended
GitHub JSON media type and the repository-pinned `X-GitHub-Api-Version:
2026-03-10` header.

#### Scenario: Active or successful duplicate exists
- **WHEN** another exact-title run is active, successful, or lacks a terminal failure conclusion
- **THEN** the system rejects the current run and reports the blocking run identity

#### Scenario: Only explicitly replaceable history exists
- **WHEN** every exact-title predecessor is completed with `failure`, `cancelled`, `timed_out`, or `action_required`
- **THEN** the duplicate guard permits the current run subject to all other gates

#### Scenario: History is active, successful, or not explicitly replaceable
- **WHEN** an exact-title predecessor is active, successful, conclusion-less, neutral, skipped, stale, unknown, or malformed
- **THEN** the duplicate guard blocks the current run

#### Scenario: Inventory is incomplete or unstable
- **WHEN** pagination omits rows, page totals differ, IDs repeat, or the final two normalized observations differ
- **THEN** the system fails closed instead of assuming no duplicate exists

#### Scenario: Same-title non-dispatch history exists
- **WHEN** a valid push, schedule, or other non-dispatch run has the exact display title
- **THEN** it remains part of completeness and stability accounting but is ignored only after normalization

#### Scenario: A run event is malformed
- **WHEN** any unfiltered inventory row has an absent, empty, or non-string event
- **THEN** the system rejects the inventory instead of silently treating the row as unrelated

### Requirement: Discovery restore selects one exact source artifact receipt
The system MUST read an exact distinct source run that is completed with
`success`, `failure`, `cancelled`, or `timed_out`, was created by
`workflow_dispatch`, has the exact `.github/workflows/full-extraction.yml` path
and a positive workflow ID, and has a valid source SHA and attempt.
`action_required`, `neutral`, `skipped`, `stale`, absent, and unknown
conclusions MUST be rejected. The system SHALL observe the complete artifact
inventory three times, require the final two normalized snapshots to match,
prefer exactly one unexpired canonical discovery artifact, and otherwise accept
exactly one unexpired recovery artifact whose embedded run ID and attempt equal
the source run's current attempt.

#### Scenario: One canonical artifact is available
- **WHEN** the source inventory has exactly one unexpired canonical artifact
- **THEN** the system selects its positive artifact ID even when one exact current-attempt recovery artifact also exists

#### Scenario: Only current-attempt recovery is available
- **WHEN** no canonical artifact exists and exactly one unexpired recovery artifact names the source run and its current attempt
- **THEN** the system selects that recovery artifact

#### Scenario: Selection is ambiguous or malformed
- **WHEN** exact matches are duplicated, snapshots remain unstable, inventory counts or IDs are inconsistent, a source recovery name is malformed, or it claims a future attempt
- **THEN** the system rejects the source inventory

#### Scenario: Source workflow identity differs
- **WHEN** source status, conclusion, event, workflow path, workflow ID, source SHA, run ID, or attempt is absent or mismatched
- **THEN** the system rejects the source before artifact selection

#### Scenario: Source workflow did not execute extraction
- **WHEN** the source conclusion is `action_required`, `neutral`, `skipped`, `stale`, absent, or unknown
- **THEN** the system rejects its artifacts as recovery evidence

#### Scenario: No usable exact artifact exists
- **WHEN** the source has only expired, stale-attempt, unrelated, or absent discovery artifacts
- **THEN** the system fails without selecting a wildcard or starting discovery from scratch

### Requirement: Selected discovery receipts are provenance-bound
The selected artifact MUST have the expected exact name, positive ID, unexpired
state, `sha256:` archive digest, positive size, exact archive-download URL,
owning workflow-run ID, and owning source SHA.

#### Scenario: REST identity matches
- **WHEN** every selected inventory field matches the exact source workflow run and a direct GET of the selected artifact ID returns the same normalized receipt
- **THEN** the system emits the artifact ID, name, digest, source kind, and source run ID

#### Scenario: REST identity differs
- **WHEN** any digest, size, expiry, URL, workflow-run ID, or source SHA is invalid or mismatched, or the direct selected-ID recheck differs
- **THEN** the system rejects the artifact before download

### Requirement: Discovery download uses exact immutable identity
The system SHALL download the selected artifact by its exact positive artifact
ID from the exact source run and SHALL configure archive digest mismatch as an
error.

#### Scenario: Exact download succeeds
- **WHEN** the selected ID, source run, and archive digest agree
- **THEN** the system may inspect the restored discovery bundle

#### Scenario: Downloaded archive digest differs
- **WHEN** the downloaded artifact archive does not match GitHub's receipt digest
- **THEN** the action fails before discovery state is installed

### Requirement: Restored discovery state matches the active plan
Before installing workload state, the system MUST find exactly one restored
discovery manifest and exactly one active lane manifest and MUST match their
nonempty chain ID, pinned source SHA, and coverage fingerprint.

The system MUST reject every symlink, multiple discovery manifests, multiple
`nba.discovery-artifacts` directories, multiple discovery summaries, multiple
workload pointers, multiple workload Parquet candidates, duplicate relevant
basenames, or otherwise ambiguous layout before copying any restored state.

#### Scenario: Canonical bundle is complete and matching
- **WHEN** manifest provenance matches and exactly one discovery directory, summary, workload pointer, and workload generation are present and integrity-valid
- **THEN** the system installs the bundle for discovery verification and reuse

#### Scenario: Canonical bundle is incomplete or invalid
- **WHEN** a canonical workload pointer, generation, integrity attestation, or manifest provenance is incomplete or mismatched
- **THEN** the system fails closed

#### Scenario: Recovery workload is incomplete
- **WHEN** a provenance-valid recovery bundle has partial or invalid workload state
- **THEN** the system removes that partial workload state and reseeds within the same new workflow run

#### Scenario: Restored layout is unsafe or ambiguous
- **WHEN** the restored tree has a symlink, duplicate managed member, multiple candidate, or duplicate relevant basename
- **THEN** canonical and recovery restore both fail before copying state

### Requirement: Cross-run lane and resume manifests are owner-bound
A receipt-aware lane-manifest handoff MUST validate the source run's exact run
ID, pinned source SHA, positive attempt, executed or active state, dispatch
event, full-extraction workflow path, and positive workflow ID before comparing
the artifact's exact positive ID, name, digest, size, expiry, archive URL,
owning run, and owning source SHA. A resume-source run MUST be completed with
`success`, `failure`, `cancelled`, or `timed_out`, and its complete artifact
inventory MUST stabilize before selecting one exact committed next-manifest or,
only when no committed manifest exists, one exact canonical manifest. The
selected artifact MUST be re-read by ID and downloaded with digest mismatch
configured as an error.

#### Scenario: Lane receipt and owner source both match
- **WHEN** the source workflow run and the exact lane-manifest REST artifact agree with the pinned source, workflow identity, receipt fields, and requested chain
- **THEN** the workflow may download the artifact by ID and use its single manifest

#### Scenario: Artifact self-provenance hides a different owner source
- **WHEN** a source run or artifact is owned by another SHA even though the downloaded manifest claims the pinned SHA
- **THEN** the workflow rejects the handoff before download or manifest parsing

#### Scenario: Resume source contains a committed manifest
- **WHEN** a completed source run has one stable, unexpired committed next-manifest whose name binds that run and a positive attempt no greater than the owner attempt
- **THEN** the workflow selects the highest positive committed attempt and directly rechecks its exact artifact ID

#### Scenario: Resume source has only one canonical manifest
- **WHEN** no committed next-manifest exists and exactly one stable, unexpired canonical manifest matches the chain
- **THEN** the bounded canonical fallback may be selected by exact artifact ID

#### Scenario: Resume inventory or direct identity is incomplete
- **WHEN** pagination counts differ, IDs repeat, final snapshots differ, candidates are ambiguous, or the direct selected-ID identity changes
- **THEN** the workflow fails without a name-only download

### Requirement: Legacy name-only lane handoff is bounded and upgraded before use
When both an artifact ID and digest are absent for a persisted legacy
lane-manifest handoff, the system MAY resolve the exact run and artifact name
only after validating the owner run against the pinned source and exact
full-extraction workflow identity. It MUST query the exact artifact name,
require three observations with identical final snapshots, require one
unexpired candidate, directly re-read that candidate by positive ID, and
download that exact ID. When GitHub exposes an archive digest, the downloaded
archive MUST match it. The archive MUST contain exactly one regular,
non-symlink, traversal-free expected `manifest.json` or `next-manifest.json`
member.

#### Scenario: Valid persisted legacy handoff is upgraded
- **WHEN** one stable exact-name artifact belongs to the source-bound workflow run and its exact-ID archive contains one expected regular manifest
- **THEN** the system may use the extracted manifest and continues with normal chain and source validation

#### Scenario: Legacy owner is cross-source or cross-workflow
- **WHEN** the named artifact's owner run has another source SHA, event, workflow path, workflow ID, run ID, or invalid attempt or state
- **THEN** the system rejects the handoff before reading its archive

#### Scenario: Legacy archive is ambiguous or unsafe
- **WHEN** exact-name artifacts are duplicated, expiry is not a strict boolean, the direct identity changes, the digest differs, or the archive has zero, multiple, wrong-name, symlink, special, absolute, or traversal manifest members
- **THEN** the system rejects the legacy handoff

### Requirement: Discovery failure does not advance extraction state
Failure to resolve, download, or validate an explicit discovery source MUST
leave the current workflow failed before matrix extraction, checkpoint
promotion, child redispatch, terminal assurance, or publication.

#### Scenario: Cross-run recovery is unavailable
- **WHEN** any explicit source receipt or restored bundle gate fails
- **THEN** no extraction or publication state advances and recovery requires a new explicitly bound workflow run
