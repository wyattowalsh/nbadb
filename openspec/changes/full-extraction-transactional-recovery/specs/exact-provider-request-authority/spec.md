## ADDED Requirements

### Requirement: Source freeze uses the latest verified upstream contract

Immediately before freezing the production source, the system MUST compare the
repository pin with the latest authoritative `nba_api` release/source and its
runtime/docs/tools surface. A newer supported upstream MUST be reviewed and
pinned atomically with headers, endpoint descriptors, schemas, routes, models,
and contract tests before RequestUniverse generation. The running chain MUST use
one immutable exact pin; a moving `latest` reference is never authority.

#### Scenario: A newer upstream release is available before source freeze

- **WHEN** authoritative release/source evidence shows a newer supported contract
- **THEN** the repository updates and validates the exact pin before deriving requests

#### Scenario: Upstream changes after the chain starts

- **WHEN** a newer release appears after source and RequestUniverse freeze
- **THEN** the active chain remains on its exact pin and the newer contract enters a later semantic-diff decision

#### Scenario: Latest upstream evidence is unavailable

- **WHEN** the authoritative release/source cannot be resolved or reconciled with runtime/docs/tools
- **THEN** fresh baseline admission remains blocked rather than claiming latest coverage

### Requirement: Request authority is an immutable least-fixed-point generation

The system MUST build a schema-versioned `RequestUniverseGeneration` from every
endpoint/result surface exposed by the exact pinned provider runtime, repository
support contracts, exact parameter domains, static and live providers, temporal
axes, and typed dependency discoveries. It MUST iterate until one complete round
adds no provider-owned identifiers or dependent requests. A separate verifier
MUST independently recompute the least fixed point and bind the source SHA,
upstream contract identity, canonical request inventory, dependency edges,
round receipts, and generation digest.

#### Scenario: A discovery round yields new provider identifiers

- **WHEN** a typed provider response exposes a new identifier required by a supported dependent endpoint
- **THEN** the exact dependent requests enter the next round and closure continues

#### Scenario: A complete round adds no requests

- **WHEN** every discovered provider-owned identifier and dependency edge is already represented
- **THEN** the verifier may seal the generation as the least fixed point

#### Scenario: The execution plan and independent universe differ

- **WHEN** a planned lane is missing, extra, duplicated, overlapping, or has parameters that do not match the independently derived universe
- **THEN** planning fails before sharding or provider access

### Requirement: Physical shards preserve one exact logical universe

The immutable logical request universe MUST be partitioned into bounded,
disjoint, exhaustive execution shards. Shard count, order, indexes, waves,
priorities, and execution slots MUST NOT alter logical request identity or the
universe digest. Each invocation MUST belong to exactly one active shard in an
attempt.

#### Scenario: Capacity changes the number of waves

- **WHEN** the same universe is executed with a different admitted slot count
- **THEN** only physical placement changes and the canonical request inventory remains byte-identical

#### Scenario: Shards overlap or omit a request

- **WHEN** independent shard validation finds an invocation in multiple shards or in none
- **THEN** the manifest is invalid and no extraction starts

### Requirement: Request generation never guesses comparison fan-out

The system MUST generate only exact parameter tuples supported by provider
contracts or provider-owned dependency evidence. It MUST NOT synthesize a
Cartesian product of players, teams, opponents, seasons, lineups, or comparison
identities. A schema-backed endpoint whose exact comparison pairs cannot be
proven remains `contract_not_modeled_yet` and unresolved rather than guessed.

#### Scenario: Player-team affiliation is known but opponent pairings are not

- **WHEN** available evidence cannot prove an exact supported comparison tuple
- **THEN** the endpoint is not fanned out and its explicit support disposition remains release-blocking where required

#### Scenario: Typed evidence proves one sparse pair

- **WHEN** provider-owned discovery proves an exact dependent pair and period
- **THEN** only that pair is added without widening it into a Cartesian product

### Requirement: Every supported period is evaluated per field

For each endpoint, result set, and field, temporal authority MUST record the
parameter period, event-time applicability, first and last observed support,
internal gaps, evidence class, observation window, and revalidation policy.
Endpoint-level season bounds MUST NOT substitute for field-level evidence. The
universe MUST include every supported period exposed by the pinned provider
contract and explicit evidence.

#### Scenario: A field begins after its endpoint

- **WHEN** an endpoint is supported historically but a field first appears in a later period
- **THEN** the field authority records its later applicability without treating earlier field absence as missing extraction

#### Scenario: A field disappears inside its supported interval

- **WHEN** the field is absent in an internal period without evidence of upstream unavailability
- **THEN** the period remains an unresolved field gap and MODEL-GREEN stays red

#### Scenario: Temporal bounds use a fallback guess

- **WHEN** earliest or latest support is inferred from a default rather than exact contract or observation evidence
- **THEN** the authority is unverified and cannot satisfy full-model assurance

### Requirement: Successful parser input is public, exact, and secret-safe

Before parsed rows or a success journal record become durable, every successful
body-bearing provider occurrence MUST store the exact parser-input bytes in a
public-safe content-addressed object and emit a logical receipt binding request
identity, call ordinal, retry attempt, result occurrence, byte length, SHA-256,
media/encoding contract, and object path. Providers that produce no parser input
MUST emit an explicit typed bodyless disposition. Persisted success bytes MUST
pass deterministic secret and public-safety classification without mutation.

#### Scenario: A successful response yields rows

- **WHEN** parsing succeeds from a body-bearing provider occurrence
- **THEN** its digest-matching public object and logical receipt exist before journal success

#### Scenario: A successful response is present-empty

- **WHEN** the provider returns a valid empty result set
- **THEN** the exact parser input is preserved and the empty result remains evidence-backed success

#### Scenario: Exact bytes are unsafe for public release

- **WHEN** deterministic classification finds credentials, authorization data, private cookies, or other prohibited secret material
- **THEN** the occurrence fails public-authority admission and the system does not redact bytes while claiming exactness

#### Scenario: A failure includes an unrestricted body

- **WHEN** a provider call fails or its response contract is invalid
- **THEN** only allowlisted failure metadata may persist and no unrestricted failure body becomes public authority

### Requirement: Public value closure is exact, representation-complete, and pre-journal

Raw Authority V2 SHALL remain the exact-four source/request/result/route
authority. A separate `PublicValueAuthorityV1` MUST derive the complete ordered
expected-unit denominator from each selected-terminal Raw Authority V2 bundle
and assign exactly one `ValueRepresentationAssignmentV1` to every unit. The
expected units are every selected result occurrence plus a response unit whenever exact
conditional decoding yields records not owned by an occurrence or an admitted
fixed-zero response has no occurrences. The representation domain MUST be
exactly `rectangular_result_cells_v1`, `stats_lossless_records_v1`,
`live_lossless_nodes_v1`, `response_lossless_records_v1`, and
`response_fixed_zero_v1`; source-input kind MUST be separately classified as
`parser_input_body` or `declared_bodyless_packet`. Missing, extra, duplicate,
reordered, dual, or foreign assignments MUST fail request closure.

Every selected stats/live observation MUST own one exhaustive
`LosslessOwnershipReceiptV1` over the exact decoded-record denominator. Every
record MUST have exactly one occurrence or response-residual owner; every
selected occurrence MUST have a partition even at zero records; and a zero
response residual MUST be explicit rather than inferred from sparse omission.
Every selected static observation MUST bind exact persisted
`DeclaredBodylessPacketV1` bytes and a matching
`DeclaredBodylessPacketReadbackReceiptV1`; digest-only bodyless evidence is
insufficient. Selected live observations MUST emit mandatory live-node public
authority even when no conditional drift route exists.

The mandatory base public relations MUST be exactly
`raw_nba_api_result_cell`, `raw_nba_api_stats_lossless_record`,
`raw_nba_api_live_lossless_node`, `raw_nba_api_value_representation`,
`raw_nba_api_route_field_landing`, and `raw_nba_api_w2_operation` for this
authority version. Conditional stats/live staging routes remain observed-only
outputs and MUST NOT substitute for any mandatory base relation.

One `W2OperationReceiptV1` per finalized logical-call bundle MUST bind the raw
bundle and persistence receipt, exact body/bodyless authority, expected-unit and
representation roots, mandatory public value table schema/row/inventory roots,
committed staging receipt and readback inventory, field-fate and conditional/
live-plan roots, ordered route-field landing receipts,
`BodyValueProjectionReceiptV1`, `PublicTableValueProjectionReceiptV1`, their
exact `ValueProjectionEqualityReceiptV1`, bounded resource totals, and the
operation semantic digest. The table projection MUST be derived only
from public structured rows and MUST NOT consult body payloads, private caches,
extraction memory, production parser/staging code, or receipt-embedded values.
The operation MUST bind schemas for all six mandatory relations but row roots
for only the first five, excluding its own W2 row to avoid a hash cycle. A
separate `W2OperationPersistenceReceiptV1` MUST bind the inserted operation row
and exact post-commit W2 table readback. The stable operation key MUST exclude
response/table content so same-key/different-semantic state is a collision.

The exact parser-input body or bodyless packet MUST be persisted and read back
before parser-derived staging becomes an accepted success candidate. Staging MAY
commit as a crash-recoverable candidate so its exact post-commit readback can be
derived, but it MUST NOT become coverage, resume, checkpoint, or journal-success
authority until the W2 operation is durably persisted and read back. Same-key,
same-content replay MAY be a verified no-op; partial state, a content collision,
foreign root, reordered inventory, or post-commit ambiguity without exact
readback MUST remain nonterminal. This two-phase boundary MUST NOT defer or
weaken capture of exact parser-input bytes before parsing.

#### Scenario: Staging is durable but public value closure is absent

- **WHEN** a staging candidate commits and the process stops before exact W2 operation readback
- **THEN** the journal does not record success, the candidate supplies no coverage, and only an identical-authority retry may complete it

#### Scenario: A selected observation lacks ownership or exact bodyless authority

- **WHEN** selected stats/live records lack an exhaustive ownership receipt or a selected static packet has only digest evidence
- **THEN** expected-unit derivation, projection equality, W2 closure, and journal success fail

#### Scenario: The operation semantic digest includes its own W2 row root

- **WHEN** `W2OperationReceiptV1` attempts to bind the `raw_nba_api_w2_operation` row or table root
- **THEN** the cyclic operation is invalid and no persistence receipt may promote it

#### Scenario: Public representations are both sealed but disagree

- **WHEN** body-derived and strict public-table-derived projections differ in any unit, result/provider/duplicate order, path, ordinal, type, value, presence, or present-empty structure
- **THEN** the W2 operation, request closure, journal success, and downstream authority fail

#### Scenario: Valid unknown drift is conserved exactly

- **WHEN** an additive or unknown result/field has exact body, representation, table-only equality, route, staging, and W2 closure
- **THEN** the call may be journaled as losslessly conserved while the same immutable drift evidence keeps MODEL-GREEN and full publication red pending reviewed fate, type, key, lineage, and temporal authority

### Requirement: Every invocation has one evidence-backed terminal disposition

An exact invocation may become terminal only as successful nonempty,
successful present-empty with valid response evidence, or narrowly evidenced
upstream unavailable/contract-blocked under the independent support rules.
Unattempted, skipped, circuit-suppressed, timed-out, body-missing, parser-failed,
unknown, or guessed-unavailable work MUST remain unresolved.

#### Scenario: A circuit suppresses a call

- **WHEN** a bounded response-contract circuit prevents an upstream request
- **THEN** the invocation remains failed and resumable rather than terminal

#### Scenario: A zero-row result has no response evidence

- **WHEN** staging is empty but no valid present-empty parser input and receipt exist
- **THEN** the invocation cannot be classified as successful empty

#### Scenario: Independent support evidence proves unavailability

- **WHEN** exact endpoint/parameter/period evidence satisfies the canonical support rule
- **THEN** the invocation may carry that narrow evidence-bound terminal disposition

### Requirement: Unknown provider drift lands losslessly but blocks MODEL-GREEN

Additive result sets, fields, and values MUST retain request, body/bodyless,
result-set, field, type, ordinal, and temporal provenance in lossless public
staging. Every observed field MUST receive an explicit public fate and temporal
contract. Unknown, unclassified, untyped, unkeyed, or unreviewed drift MUST keep
MODEL-GREEN red even when DATA extraction is otherwise complete.

#### Scenario: The provider adds a field

- **WHEN** a successful parser input contains an undeclared field
- **THEN** the field lands losslessly and is reported as unclassified without silently dropping it or admitting the model

#### Scenario: A field is intentionally excluded from a curated model

- **WHEN** review establishes its lossless public source route, semantics, type, key role, lineage, and temporal applicability
- **THEN** it may receive an explicit non-star fate without losing source authority

### Requirement: Semantic diff governs fresh versus incremental authority

The system MUST compare provider/runtime identity, endpoint and result-set
contracts, parameter domains, dependency rules, request-universe identity,
ordered fields, logical types, keys/meaning, staging routes, model lineage, and
field-temporal authority. Identity-changing, removed, reinterpreted, or newly
modeled authority MUST require a fresh exact-SHA attempt-one baseline. Only a
meaning-preserving additive change whose affected requests and periods are
fully identified MAY use a bounded delta/backfill.

The initial `PublicValueAuthorityV1` cutover, any new representation kind, any
change to expected-unit or exactly-one-assignment rules, and any public value
table/schema or reconstruction-rule change MUST be classified as a
reconstruction authority break and require fresh full. No old checkpoint,
dataset, cell projection, conditional table, or receipt may be converted into
the new authority through a compatibility alias. After one complete baseline is
admitted, newly observed data under the unchanged representation and schema MAY
use delta/backfill only when the ordinary semantic-diff rule proves its exact
affected scope and meaning preservation.

#### Scenario: The current dataset lacks the complete data model

- **WHEN** the new contract adds previously unmodeled request, field, lineage, or temporal authority
- **THEN** the current Kaggle dataset and old checkpoints are diagnostic only and a fresh baseline is required

#### Scenario: The value representation denominator changes

- **WHEN** a representation kind, expected-unit rule, exactly-one assignment rule, public value schema, or reconstruction rule changes
- **THEN** semantic diff selects fresh full and rejects every compatibility projection or old-checkpoint resume

#### Scenario: A later period adds rows under unchanged authority

- **WHEN** semantic diff proves the existing request, field, type, key, route, and model meanings unchanged
- **THEN** a parent-bound tail or targeted delta may cover the exact new period

#### Scenario: Diff evidence is incomplete

- **WHEN** any compared authority surface is missing or ambiguous
- **THEN** the system fails closed rather than selecting a smaller incremental refresh
