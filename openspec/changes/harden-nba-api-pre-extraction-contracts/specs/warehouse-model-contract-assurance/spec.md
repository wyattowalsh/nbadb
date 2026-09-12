## ADDED Requirements

### Requirement: Every known upstream field has an explicit cross-layer disposition

The system MUST use the exact upstream field identity as the denominator and
record physical-bronze, silver, star, model, and metric dispositions with
reason, evidence, owner, blocker effect, and revalidation path. Same-name,
candidate, passthrough, wildcard, or inferred matches MUST NOT count as proven
lineage.

#### Scenario: A runtime additive field appears

- **WHEN** a valid response contains a field absent from the pinned contract
- **THEN** the public-safe typed lossless landing preserves its request/result/header-or-path ordinal/value/presence/provenance identity, extraction records contract drift, and the field remains semantically unclassified until reviewed

#### Scenario: A SELECT-star output has a closed schema

- **WHEN** a source field reaches a wildcard transform but is absent from the public output schema
- **THEN** the field is not labeled preserved/modelled and the audit reports its explicit non-public fate or blocker

### Requirement: Every public table has an explicit semantic contract

All 261 current public outputs plus every newly admitted output SHALL have a
compiled contract containing purpose, exact grain columns, key or reviewed bag
policy, joins/FKs, SCD rule, source dependencies, ordered schema, column
lineage, row/filter/dedup/union behavior, temporal applicability, stability,
transform digest, and validation expectations. The current count is a
regression floor for this planning snapshot, not a hard-coded future inventory.

#### Scenario: Grain exists only by name inference

- **WHEN** a public table lacks a reviewed explicit or deterministically compiled grain contract
- **THEN** `MODEL-GREEN` fails even if a schema and transform class exist

#### Scenario: Transform output order differs from schema order

- **WHEN** a fixture/runtime compile produces the same column set in a different order
- **THEN** the output is normalized to canonical order or rejected according to its explicit contract, and the order-sensitive digest changes

### Requirement: Stable model disposition covers an independent complete census

The system MUST independently derive a complete model-candidate census from the
frozen provider/request/result/field surface, source concepts, existing
registries, transforms, schemas, and documented analytical needs rather than
from implemented outputs alone. One versioned `StableModelDispositionV1` SHALL
account for every candidate as `stable`, `experimental`, `withheld`, or
`rejected` and bind evidence, owner, reason, implementation status,
dependencies, promotion/revalidation path, and gate effect. A candidate needed
for losslessness or a defensible stable public model MUST remain MODEL-red when
implementation is missing; `withheld` is not an implementation-gap waiver.

#### Scenario: A defensible source-backed model is not implemented

- **WHEN** the independent census identifies a stable model required to represent the frozen source surface but no complete typed model, transform, schema, or validation exists
- **THEN** its disposition records the implementation gap and MODEL-GREEN remains red rather than excluding the candidate from the denominator

#### Scenario: A candidate is intentionally rejected

- **WHEN** evidence proves a candidate is redundant, misleading, legally inadmissible, or unsupported by the frozen source authority
- **THEN** the rejected disposition cites that evidence and revalidation trigger and the candidate cannot silently reappear in stable registries

### Requirement: Model registries and public inventories are dynamic and lossless

Raw, staging, star, conditional typed-lossless, export, metadata, documentation,
and Kaggle inventories MUST be compiled from the frozen provider, disposition,
and model-contract registries. Every admitted stable provider result SHALL have
a typed lossless raw/staging route or a public-safe universal lossless route
until a typed contract is reviewed. Consumers MUST NOT duplicate fixed table or
resource counts as a second authority.

#### Scenario: Stable provider drift is observed

- **WHEN** a valid additive result, nested node, duplicate-header occurrence, or field appears before a typed model is admitted
- **THEN** the universal public-safe lossless route preserves it, the conditional typed-lossless registry records its state, and semantic consumers remain blocked until classification

#### Scenario: A generated consumer omits an admitted model

- **WHEN** the disposition registry admits a model but export, metadata, docs, or Kaggle inventory generation does not include its declared public resources
- **THEN** registry reconciliation and MODEL-GREEN fail with the missing consumer path

### Requirement: Experimental models are segregated and promotion is explicit

Experimental fitted or inferred models MUST use a separately versioned
namespace, MUST NOT satisfy stable source/model coverage, and MUST NOT gate a
stable publication. Promotion to stable requires a reviewed versioned semantic
contract, deterministic implementation, complete lineage and temporal scope,
validation evidence, consumer review, and a new `StableModelDispositionV1`
entry; renaming or moving a table alone is insufficient.

#### Scenario: An experiment fails validation

- **WHEN** an experimental RAPM, xFG, WPA, forecast, rating, or prospect-value model is incomplete or fails its own evaluation
- **THEN** its experimental receipt records the failure while otherwise complete stable MODEL-GREEN and DATA-GREEN decisions remain unaffected

#### Scenario: An experiment is referenced as stable

- **WHEN** stable chat, docs, metadata, or publication contracts expose an experimental model without a completed promotion contract
- **THEN** the stable assurance gate fails before that consumer artifact is accepted

### Requirement: SCD and join semantics prevent fanout

Every relationship SHALL identify its target key and whether it is current-only
or as-of. SCD2 tables MUST enforce unique versions, one current row, and ordered
non-overlapping validity intervals.

#### Scenario: A fact references a nonunique natural player key

- **WHEN** the target is the SCD2 player dimension
- **THEN** the table contract must specify and validate current or as-of semantics instead of treating the annotation as a conventional unique FK

#### Scenario: A current snapshot has no historical discriminator

- **WHEN** `CommonPlayerInfo` returns current player/team identity for a player-only request and exposes no season
- **THEN** the system does not invent a season or backcast the current values; version history begins only from explicit observation timestamps, while historical team membership uses season-bearing sources

#### Scenario: A benchmark packet is request scoped

- **WHEN** a shot is enriched with a league-average packet
- **THEN** the join includes every material request discriminator and fails on conflicting compatible candidates instead of joining by zone labels alone

### Requirement: Metrics and use cases have finite versioned coverage

Every public sourced measure and computed numeric alias MUST have a versioned
definition or explicit nonsemantic disposition. Definitions include formula,
inputs, grain, unit/scale, weighting, null/zero, aggregation, eligibility,
tie/window, season/era, lineage, evidence, use cases, and misuse risks.

#### Scenario: A metric lacks evidence for an official qualification

- **WHEN** the implementation provides an arithmetic ranking but no evidence for official eligibility
- **THEN** it is labeled as the exact unqualified arithmetic result or quarantined; the system does not invent a threshold

#### Scenario: A semantic consumer requests a quarantined metric

- **WHEN** chat, CLI, notebook, or docs metadata references a metric not admitted for that use case
- **THEN** validation fails before generated/public consumer output is accepted
