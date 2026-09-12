## ADDED Requirements

### Requirement: Durable lane identity is independent of dispatch placement

The system SHALL identify durable lane coverage from the lane's semantic
identity and coverage units and SHALL exclude attempt-local scheduling fields
from checkpoint acceptance.

#### Scenario: Completed lane is rescheduled

- **WHEN** a completed lane retains the same lane ID, semantic scope, and coverage-units hash but receives a different lane index, wave, priority, queue class, or execution slot
- **THEN** the system accepts the attested artifact as the same durable lane coverage

#### Scenario: Semantic lane coverage changes

- **WHEN** a lane ID or coverage-units hash differs from the committed or attested contract
- **THEN** the system rejects the artifact even if its dispatch index matches

#### Scenario: Attempt-local index is malformed

- **WHEN** strict attempt metadata omits its lane index or provides a boolean, negative, or non-integer value
- **THEN** the system rejects the metadata as malformed without treating the index as durable identity

### Requirement: Checkpoint coverage is derived from attested artifacts

The system MUST compute checkpoint lane inventory and semantic coverage from
artifacts that pass all current lane, source, chain, run, database, journal,
state-attestation, and workload-contract checks.

#### Scenario: Accepted inventory differs from lane-control prediction

- **WHEN** the set of artifacts accepted by checkpoint validation differs from a provisional lane-control inventory
- **THEN** the checkpoint report records the actual accepted inventory and the system does not trust or require a predicted next coverage hash

#### Scenario: Artifact fails attestation

- **WHEN** a reported-complete lane fails any required artifact, database, journal, scope, or provenance check
- **THEN** that lane is excluded from committed checkpoint coverage and remains unresolved

### Requirement: Checkpoint publication follows a monotonic transaction

The system SHALL enforce the ordered states `candidate`, `built`,
`uploaded_verified`, and `committed`, and SHALL reject skipped, repeated, or
out-of-order transitions.

#### Scenario: Successful checkpoint transaction

- **WHEN** a candidate is built, its immutable artifact receipt is verified, and the transaction is committed
- **THEN** the next manifest advances exactly one checkpoint generation and embeds the committed transaction

#### Scenario: Build or upload fails

- **WHEN** checkpoint construction, upload, receipt verification, or manifest commit fails
- **THEN** the previous committed manifest remains authoritative and no child iteration consumes the candidate

#### Scenario: Illegal transition is requested

- **WHEN** code attempts to commit a candidate or built transaction without an uploaded and verified receipt
- **THEN** the system rejects the transition

### Requirement: Checkpoint build binds immutable content

The system MUST bind the built transaction to the SHA-256 of the regular
checkpoint database file, the SHA-256 of the checkpoint report, the exact
generation, artifact name, source SHA, chain ID, semantic coverage fingerprint,
and canonical lane inventory.

#### Scenario: Database or report changes after build

- **WHEN** either file's bytes change after the built transaction is created
- **THEN** receipt commit fails before the manifest pointer advances

#### Scenario: Zero-delta generation is built

- **WHEN** an iteration accepts no new lane database but has a valid prior checkpoint
- **THEN** the system creates a distinct copied database, report, transaction, and next generation

### Requirement: Committed checkpoint pointers contain exact artifact receipts

The system MUST bind each new committed pointer to a positive artifact ID,
artifact workflow-run ID, logical name, `sha256:` archive digest, positive
archive size, chain ID, source SHA, generation, coverage fingerprint, database
digest, and report digest.

#### Scenario: Receipt matches the built candidate

- **WHEN** every receipt field matches the built checkpoint and current workflow provenance
- **THEN** the system permits the transaction to enter `uploaded_verified` and then `committed`

#### Scenario: Receipt field mismatches

- **WHEN** any artifact, provenance, generation, coverage, database, or report field differs
- **THEN** the system fails closed and does not update the manifest pointer

### Requirement: Prior checkpoints restore by committed artifact identity

For receipt-aware manifests, the system SHALL resolve and download the previous
checkpoint by its committed artifact ID and SHALL verify REST metadata, archive
digest, workflow run and producing head SHA, semantic source SHA, database
digest, report digest, chain, generation, coverage, and lane inventory before
use. When the owner run head differs from the semantic source, the source MUST
equal or be an ancestor of the producing head and the full-extraction workflow
bytes MUST be identical at both commits. The artifact receipt MUST remain bound
to the producing run while checkpoint contents remain bound to the semantic
source.

#### Scenario: Exact prior checkpoint is available

- **WHEN** artifact metadata and downloaded contents match the complete committed receipt
- **THEN** the system may use that checkpoint as the immutable base of the next copy-plus-delta generation

#### Scenario: Artifact ID is expired or mismatched

- **WHEN** the artifact is unavailable, expired, ambiguous, or disagrees with any committed receipt field
- **THEN** the system rejects the prior checkpoint before inspecting or merging its lane inventory

#### Scenario: Prior checkpoint was produced by a safe descendant

- **WHEN** the exact owner run is a trusted descendant of the semantic source and the workflow bytes match
- **THEN** the system may restore the receipt-bound checkpoint without rewriting its semantic source identity

#### Scenario: Transaction field is malformed

- **WHEN** a checkpoint pointer contains a transaction field that is non-committed, malformed, or provenance-mismatched
- **THEN** the system fails closed and does not downgrade to name-based legacy restore

### Requirement: Historical lane inputs restore by exact owner-bound receipts

Resume metadata, partial lane state, completed lane databases, lane metadata,
and discovery inputs restored from another run MUST be selected from stable,
complete artifact inventories. Each selection MUST bind a positive artifact ID,
exact name, `sha256:` archive digest, positive size, unexpired state, exact
archive URL, owner run, and producing head `H`; the selected ID MUST be directly
re-read before an exact-ID download with archive-digest mismatch set to error.
The lane contract MUST retain the artifact ID and archive digest separately
from the DuckDB database SHA-256. Run/name-only downloads are forbidden except
for the explicit transaction-absent legacy checkpoint migration.

#### Scenario: Durable lane state has an exact receipt

- **WHEN** the active lane carries an attested state artifact ID, archive digest, owner run, and database digest that all match direct evidence
- **THEN** extraction may download that exact ID and separately verify the restored database bytes

#### Scenario: Historical inventory is incomplete or ambiguous

- **WHEN** a candidate lacks ID, digest, size, URL, owner head, or has duplicate, unstable, expired, or direct-read-drifted identity
- **THEN** restore fails before downloading or merging that candidate

#### Scenario: Archive and database digests are confused

- **WHEN** a lane uses its database SHA as the GitHub archive receipt digest or fails to carry either commitment independently
- **THEN** the lane contract is invalid and cannot resume

### Requirement: Legacy checkpoint migration is bounded

Outside the choice-B fresh-baseline authority boundary, the system MAY restore
a persisted pre-transaction pointer for bounded diagnostic or same-contract
legacy-chain recovery only when the transaction field is entirely absent, and
the next successful generation MUST emit a committed receipt-aware transaction.
That compatibility path MUST NOT seed or satisfy the new full-model baseline.

#### Scenario: Transaction-absent legacy pointer is valid

- **WHEN** an existing manifest predates the transaction schema and its legacy artifact passes every existing provenance and content check
- **THEN** the system may use it for one roll-forward generation and commits the result using the new receipt schema

#### Scenario: New manifest omits a transaction

- **WHEN** a post-change workflow attempts to commit a new checkpoint pointer without a receipt-aware transaction
- **THEN** the system rejects the manifest

### Requirement: Checkpoint roll-forward preserves copy-plus-delta semantics

The system MUST create a different physical output for every generation, copy
the prior checkpoint before applying current deltas, preserve legitimate row
multiplicity and journal precedence, and leave the prior artifact unchanged.

#### Scenario: Current deltas are accepted

- **WHEN** one or more attested lane databases are accepted
- **THEN** the new generation contains the previous checkpoint plus accepted deltas and reports their exact lane contracts

#### Scenario: No current delta is accepted

- **WHEN** the prior checkpoint is valid but the current accepted delta set is empty
- **THEN** the new generation is a distinct byte-valid copy whose generation advances by exactly one

### Requirement: Downstream consumers use only the committed manifest

Redispatch, terminal merge, terminal assurance, and publication preparation
MUST consume the committed next-manifest artifact and committed checkpoint
receipt rather than the lane-control candidate.

#### Scenario: Committed next manifest is uploaded

- **WHEN** checkpoint receipt verification and manifest commit both succeed
- **THEN** downstream jobs download the committed manifest and checkpoint by their exact artifact IDs

#### Scenario: Candidate exists without committed manifest

- **WHEN** lane control succeeded but the checkpoint transaction did not commit
- **THEN** redispatch, terminal merge, terminal assurance, and publication do not start

### Requirement: Checkpoints preserve public parser-input body authority

Every accepted successful body-bearing provider-call occurrence MUST carry an
exact public parser-input body receipt bound to its logical invocation, call
ordinal, retry attempt, request identity, full body SHA-256, length, and stored
object. Copy-plus-delta build, upload, restore, merge, terminal assurance, and
publication MUST verify and conserve those receipts and objects. Declared
no-parser-input providers MUST carry explicit bodyless dispositions; failure
paths MUST NOT invent successful body authority or persist unrestricted error
bodies.

#### Scenario: A lane database exists without one required body object

- **WHEN** parsed rows or a successful call receipt exists but its body-bearing occurrence lacks a readable digest-matching public parser-input body
- **THEN** the lane is not accepted into checkpoint coverage and cannot become terminal

#### Scenario: A pre-body-contract checkpoint is otherwise healthy

- **WHEN** a historical checkpoint predates mandatory public body authority
- **THEN** it remains diagnostic evidence only and cannot seed the fresh baseline

### Requirement: Checkpoint identity binds every extraction authority

Every built and committed checkpoint MUST bind exact schema-versioned digests
for the RequestUniverse generation, canonical invocation inventory, dependency
closure, successful body/bodyless inventory, result-set and field inventory,
field-fate contract, field-level temporal authority, staging/journal authority,
model contract, semantic diff, and any canonical blocked-evidence inventory.
Those associated authority receipts MUST be included in build, artifact, restore,
copy-plus-delta, and terminal-consumer verification; the lane coverage digest
alone is insufficient.

#### Scenario: Lane coverage is unchanged but field authority changes

- **WHEN** the same lane IDs and coverage hashes are presented with a different field-fate or temporal-authority digest
- **THEN** checkpoint restore and commit fail before any pointer advances

#### Scenario: A body object is missing after roll-forward

- **WHEN** the copied checkpoint lacks one object or logical receipt committed by its parent
- **THEN** the candidate cannot enter `built` or replace the parent authority

#### Scenario: An additive unknown field is present

- **WHEN** lossless staging contains the field but its fate/model/temporal authority remains unclassified
- **THEN** the checkpoint may preserve diagnostic DATA authority but cannot claim MODEL-GREEN or terminal publication readiness

### Requirement: The new baseline starts as a fresh attempt-one chain

The first full-model DATA-GREEN extraction under the request, body, result-set,
field-temporal, and stable-model contracts MUST start at the exact source SHA and
workflow attempt one from an empty candidate with no lane-manifest,
resume-source, checkpoint, public-body inventory, Kaggle data, or recovery input
from an older chain. Later recovery MAY consume only committed state created
under the identical chain, source, RequestUniverse, public-observation,
field-temporal, model, and associated-authority identities.

#### Scenario: An old checkpoint has useful completed lanes

- **WHEN** a pre-contract incident checkpoint contains valid diagnostic rows or completed lane artifacts
- **THEN** it may inform tests and planning but cannot enter the fresh chain's accepted coverage

#### Scenario: Current Kaggle data contains apparently reusable tables

- **WHEN** those tables predate the complete full-model authority contracts
- **THEN** they remain diagnostic/comparison evidence and cannot enter the fresh checkpoint

#### Scenario: Same-chain recovery changes an associated authority

- **WHEN** source SHA, RequestUniverse, body/bodyless, field-temporal, or model digest differs from the committed receipt
- **THEN** recovery fails and requires another fresh attempt-one authority chain
