## ADDED Requirements

### Requirement: The plan job selects one terminal replay source
The plan job MUST select at most one source manifest artifact from a complete,
stable inventory and MUST directly verify its exact positive artifact ID, name,
`sha256:` digest, positive size, unexpired state, exact archive URL, owning run
and exact attempt one, exact workflow identity, producing head SHA, semantic
source SHA, and chain before
publishing replay outputs. If the producing head differs from the semantic
source, the source MUST be its ancestor and the full-extraction workflow bytes
MUST be identical at both commits. The selected manifest remains semantically
bound to the source; its REST artifact remains bound to the producing run. A
final owner re-read immediately before selection MUST equal the consumed
attestation snapshot on every committed owner field.

#### Scenario: One exact committed source is selected
- **WHEN** the requested distinct source run exposes one valid committed manifest receipt
- **THEN** the plan records that exact artifact as the sole terminal replay source

#### Scenario: Selection is absent or ambiguous
- **WHEN** source inventory is incomplete, unstable, expired, duplicated, or cannot prove one permitted exact receipt
- **THEN** planning fails before terminal replay

### Requirement: The plan artifact binds the selected manifest bytes
The plan artifact MUST include `resume-source-input-manifest.json` and a
schema-v1 `resume-source-selection.json`. The selection receipt MUST bind the
resolution mode, selected artifact identity and provenance, and the bundled
manifest member's safe name, positive size, and SHA-256. After upload, the plan
job MUST directly verify its own exact artifact ID, name, digest, positive size,
unexpired state, archive URL, owning run at exact attempt one, and producing
head SHA, including a final owner re-read, while retaining the selected
semantic source as a separate output commitment.

#### Scenario: Plan bundle is complete
- **WHEN** selected manifest bytes and both plan members match their receipts
- **THEN** the verified plan artifact outputs become terminal replay's only input authority

#### Scenario: Bundled member differs from the source receipt
- **WHEN** the bundled manifest name, size, digest, or selected source provenance differs
- **THEN** the plan artifact is rejected before replay

### Requirement: Terminal replay consumes only the verified plan receipt
Terminal replay MUST download the current run's plan artifact by the exact
output artifact ID, verify its REST identity and archive digest, validate the
schema-v1 selection receipt, and consume the bundled manifest bytes whose digest
matches that receipt. It MUST NOT enumerate, rank, or reselect source manifests
by name, run attempt, or inventory order.

#### Scenario: Exact plan receipt and bundled manifest match
- **WHEN** the plan artifact and selected source receipt pass every identity, provenance, layout, and digest check
- **THEN** terminal replay may continue from the bundled manifest

#### Scenario: Another same-name source artifact appears
- **WHEN** source inventory changes after the plan selected and bundled its manifest
- **THEN** terminal replay ignores the new inventory and remains bound to the exact plan receipt

#### Scenario: Plan receipt is unavailable or mismatched
- **WHEN** the plan artifact ID is expired, missing, owned by another current run head, semantically cross-source, wrong-sized, wrong-named, or digest-mismatched
- **THEN** terminal replay fails without a name-based fallback

### Requirement: Terminal merge consumes exact current-run authority receipts
The committed next-manifest and terminal-replay output artifacts MUST each be
directly verified after upload against their exact positive ID, name,
`sha256:` archive digest, positive size, archive URL, current run at exact attempt
one, and current producing head `GITHUB_SHA`.
Expiry MUST be strictly unexpired, and a final owner re-read MUST match.
Terminal merge MUST receive those
verified outputs and download only their exact IDs with archive-digest mismatch
set to error. It MUST NOT use a raw upload name or same-name lookup.

#### Scenario: Terminal output receipt is exact
- **WHEN** the committed manifest or replay output upload matches the current run, exact attempt one, and producing head through a direct artifact receipt
- **THEN** terminal merge may download that exact artifact ID

#### Scenario: Terminal output is only name-bound
- **WHEN** an output omits its ID or digest, its owner head is absent or different, or merge selects it by name
- **THEN** terminal merge fails before consuming the artifact

### Requirement: Terminal checkpoint resolution remains receipt-bound
When the bundled manifest has a committed checkpoint transaction, terminal
replay MUST use only that exact checkpoint artifact ID and full committed
receipt, including its RequestUniverse, public body/bodyless, field-temporal,
model, and associated authority digests. Outside the choice-B new-baseline
boundary, a transaction-absent replay MAY use only the existing attested rebuild
over the manifest's exact authorized artifact-run IDs. The choice-B baseline
MUST NOT use that compatibility path. A candidate, diagnostic, ambiguous, old-
authority, or malformed transaction MUST fail closed.

#### Scenario: Committed transaction is present
- **WHEN** the manifest contains one valid committed checkpoint receipt
- **THEN** replay downloads and verifies that exact checkpoint ID without inventory selection

#### Scenario: Transaction is absent
- **WHEN** the manifest has no committed transaction but its exact authorized lane inventory supports the defined attested rebuild
- **THEN** replay may rebuild only from those exact run IDs and attested lane/database pairs

#### Scenario: Candidate or malformed transaction is present
- **WHEN** the manifest references a noncommitted, diagnostic, ambiguous, or malformed checkpoint state
- **THEN** replay stops and does not downgrade to a broader fallback

#### Scenario: Choice-B baseline supplies an old source manifest
- **WHEN** terminal replay input predates the complete request/body/field/temporal/model authority
- **THEN** the input remains diagnostic only and cannot seed, rebuild, or satisfy the new baseline

#### Scenario: Same-chain authority is exact
- **WHEN** a committed source matches chain, source SHA, and every associated authority digest
- **THEN** replay may consume only its exact plan-selected and artifact-receipted bytes
