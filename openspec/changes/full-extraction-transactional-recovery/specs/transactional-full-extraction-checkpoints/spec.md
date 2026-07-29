## ADDED Requirements

### Requirement: Durable lane identity is independent of dispatch placement
The system SHALL identify durable lane coverage from the lane's semantic
identity and coverage units and SHALL exclude attempt-local scheduling fields
from checkpoint acceptance.

#### Scenario: Completed lane is rescheduled
- **WHEN** a completed lane retains the same lane ID, semantic scope, and coverage-units hash but receives a different lane index, wave, priority, queue class, or VPN slot
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
digest, workflow run, source SHA, database digest, report digest, chain,
generation, coverage, and lane inventory before use.

#### Scenario: Exact prior checkpoint is available
- **WHEN** artifact metadata and downloaded contents match the complete committed receipt
- **THEN** the system may use that checkpoint as the immutable base of the next copy-plus-delta generation

#### Scenario: Artifact ID is expired or mismatched
- **WHEN** the artifact is unavailable, expired, ambiguous, or disagrees with any committed receipt field
- **THEN** the system rejects the prior checkpoint before inspecting or merging its lane inventory

#### Scenario: Transaction field is malformed
- **WHEN** a checkpoint pointer contains a transaction field that is non-committed, malformed, or provenance-mismatched
- **THEN** the system fails closed and does not downgrade to name-based legacy restore

### Requirement: Legacy checkpoint migration is bounded
The system MAY restore a persisted pre-change pointer by the existing exact
run/name verifier only when the transaction field is entirely absent, and the
next successful generation MUST emit a committed receipt-aware transaction.

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
