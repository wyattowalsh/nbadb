## ADDED Requirements

### Requirement: Successful parser inputs and results are preserved before semantic loss

For every successful body-bearing response, the system MUST durably capture the
exact provider parser-input body before JSON decoding or parser entry and MUST
preserve the successful result packets before result selection, pandas/Polars
construction, renaming, coercion, or schema stripping. The parser-input body is
the exact complete byte sequence consumed by the parser after transport
decoding; it is not claimed to be compressed wire bytes or HTTP framing. The
public authority SHALL contain or losslessly address the complete body object,
not only its digest, byte count, cache path, or a private copy, and SHALL bind
body bytes, full SHA-256 and length to canonical request identity,
logical invocation, ordered provider-call occurrence, retry attempt, provider
result name and ordinal, ordered headers or nested paths, source row ordinal,
values and types, null/empty/presence state, provider/observation provenance,
and committed body/logical/result/route receipts. Static or other no-parser-
input records MUST use an explicit bodyless disposition and deterministic
canonical JSON-derived evidence.

#### Scenario: A response is malformed or non-successful

- **WHEN** a response exists but later status, JSON, or parser validation fails
- **THEN** a secret-safe failure receipt records only the allowlisted failure class, no unrestricted error body becomes durable authority, and the attempt does not count as successful coverage

#### Scenario: A transport fails before a response exists

- **WHEN** the request raises before any response is available
- **THEN** an immutable no-body attempt receipt records the stable failure class without inventing a body digest

#### Scenario: A successful body-bearing call lacks its body

- **WHEN** parsed results or staging rows exist but the exact parser-input body or its verified readback receipt is absent
- **THEN** completion, resume, assurance, export, and publication fail for that provider-call occurrence

#### Scenario: A provider path has no parser input

- **WHEN** an embedded static or other declared bodyless provider produces canonical records without a parser-input body
- **THEN** the attempt carries the declared bodyless disposition and no synthetic body bytes or digest are created

### Requirement: Physical bronze is public-safe, lossless, and reconstructible

The durable bronze authority SHALL preserve every successful body-bearing
request's exact parser input plus every result, header/path ordinal, value,
presence state, and provenance identity in public raw/typed/universal landings
with immutable receipts. It MUST support two independent reconstructions:
parsing the exact public body object, and reconstructing the complete ordered
packet from public structured tables alone without consulting the body object,
private caches, or extraction-time memory. Both MUST match the committed packet
for result occurrence, ordered fields, row ordinals, types, presence states,
values, and semantic hash. A content-addressed body store MAY
deduplicate identical bytes and MAY use bounded deterministic compression, but
it MUST use full SHA-256 identities, atomic verified writes, public export
membership, and per-attempt logical receipts. It is a baseline, completeness,
resume, assurance, and publication dependency for body-bearing calls.

#### Scenario: Identical bodies occur for different attempts

- **WHEN** two requests return identical parser-input bytes
- **THEN** the physical body object may be deduplicated while both attempts retain distinct logical body/result receipts and exact public reconstruction

#### Scenario: Only a body digest is public

- **WHEN** a public receipt names a parser-input digest but the exact verified body object is absent, private-only, corrupt, or not exported
- **THEN** reconstruction, completion, resume, terminal assurance, and publication fail for that body-bearing occurrence

#### Scenario: Structured reconstruction consults the body store

- **WHEN** the table-only verifier reads body bytes, a private cache, or the extraction-time packet to fill a structured-table gap
- **THEN** the verifier fails; structured losslessness must be proven from the public request/result/header-or-path/value/presence tables alone

#### Scenario: The two reconstructions differ

- **WHEN** independent body parsing and structured-table reconstruction differ in any occurrence, order, type, presence state, row ordinal, or value
- **THEN** the observation remains incomplete and no downstream route, checkpoint, export, or publication may count it as conserved

#### Scenario: Sensitive transport data reach a persistence boundary

- **WHEN** a body, landing, receipt, diagnostic, log, export, metadata file, or archive contains cookies, authorization data, request headers, proxy/VPN details, credentials, or unrestricted error-body content
- **THEN** persistence or terminal/publication assurance fails before upload

### Requirement: Public value authority assigns one closed representation to every unit

The system MUST define a `PublicValueAuthorityV1` schema domain layered on the
exact-four Raw Authority V2 source/request/result/route relations. It MUST NOT
change Raw Authority V2 table membership, reuse the raw-authority schema version
for value rows, or accept a compatibility alias or projection from an older
value schema. The public-value schema SHALL derive an ordered expected-unit set
independently from selected-terminal Raw Authority V2 observations: one
`result_occurrence` unit for every selected result occurrence, plus one
`response` unit whenever independently decoded conditional records are not
owned by a result occurrence or an admitted fixed-zero response has no result
occurrences. Every expected unit MUST have exactly one
`ValueRepresentationAssignmentV1`; missing, duplicate, additive, reordered,
cross-observation, or foreign assignments invalidate the observation.

Every selected stats/live observation MUST carry one exhaustive
`LosslessOwnershipReceiptV1`. Its decoded-record denominator MUST equal its
ownership-row denominator; every record has exactly one occurrence or response-
residual owner; every selected occurrence has one partition even when its count
is zero; and the response-residual count/root MUST be present even when empty.
Sparse omission MUST NOT prove zero residual. Every selected static observation
MUST instead bind exact persisted `DeclaredBodylessPacketV1` bytes and a matching
`DeclaredBodylessPacketReadbackReceiptV1`; `bodyless_evidence_sha256`, a private
cache, or public derived rows MUST NOT substitute for those bytes.

The closed representation-kind domain SHALL be exactly
`rectangular_result_cells_v1`, `stats_lossless_records_v1`,
`live_lossless_nodes_v1`, `response_lossless_records_v1`, and
`response_fixed_zero_v1`. The orthogonal source-input kind SHALL be exactly
`parser_input_body` or `declared_bodyless_packet`. Representation selection MUST
follow the sealed occurrence/output contract rather than caller-projected shape,
canonical ordinal presence, storage order, or whether fallback rows happen to
be rectangular. Several route receipts MAY cite one representation assignment,
but one expected unit MUST NOT claim several representations.

The base public inventory MUST contain schema-strict
`raw_nba_api_result_cell`, `raw_nba_api_stats_lossless_record`,
`raw_nba_api_live_lossless_node`, `raw_nba_api_value_representation`,
`raw_nba_api_route_field_landing`, and `raw_nba_api_w2_operation` relations.
These mandatory raw relations are distinct from the conditional stats/live
staging routes, which remain present only when their drift route was validly
observed. Table and resource counts MUST be generated from the frozen runtime
registry rather than retained as fixed numeric premises.

#### Scenario: A declared stats fallback is rectangular by coincidence

- **WHEN** the sealed stats occurrence uses the anomaly-aware fallback output contract even though its observed rows have uniform width
- **THEN** its sole representation is `stats_lossless_records_v1`, including raw containers and anomaly identity, and no rectangular-cell digest substitutes for it

#### Scenario: A conditional response contains result-owned and response-wide records

- **WHEN** exact decoding yields both result-occurrence records and residual body records
- **THEN** every result occurrence receives its sole occurrence representation and one separate response unit receives `response_lossless_records_v1`

#### Scenario: A sparse ownership inventory omits residual proof

- **WHEN** a selected stats/live observation omits a decoded record, an occurrence partition, or the explicit zero-residual count and root
- **THEN** expected-unit derivation, representation assignment, W2 closure, and journal success fail

#### Scenario: Static authority provides only a bodyless digest

- **WHEN** a selected static observation has bodyless disposition evidence but lacks exact persisted packet bytes or their exact readback receipt
- **THEN** body projection, W2 closure, and every downstream completion authority fail

#### Scenario: A declared bodyless static result is rectangular

- **WHEN** a pinned static packet yields one exact rectangular result occurrence
- **THEN** the representation is `rectangular_result_cells_v1`, the source-input kind is `declared_bodyless_packet`, and no synthetic parser body is created

#### Scenario: An exact admitted response has no occurrences or drift

- **WHEN** independently rederived policy proves one selected-terminal fixed-zero response with no result occurrence and no conditional residual records
- **THEN** its sole response representation is `response_fixed_zero_v1` with zero rows and the canonical empty inventory root

#### Scenario: One unit is omitted or assigned twice

- **WHEN** the representation inventory omits an expected unit, adds a foreign unit, or gives one unit both rectangular and lossless representations
- **THEN** the public-value authority and every dependent route, checkpoint, assurance, export, and publication receipt fail

### Requirement: Body and public-table value verifiers have disjoint authority

The system MUST emit a `BodyValueProjectionReceiptV1` from exact parser-input
bytes or an exact declared bodyless static packet, a
`PublicTableValueProjectionReceiptV1` from public structured rows alone, and a
`ValueProjectionEqualityReceiptV1` that binds their exact independently derived
expected-unit denominator and comparison result. The body verifier MUST NOT use
public value rows to fill a source gap. The table verifier MUST NOT read parser-
input bytes, body-object payloads, private caches, extraction-time packets,
production parser output, staging-mapper output, or values embedded in a receipt
as substitute source rows. It MAY consume public identity/root columns, but it
MUST reconstruct values, ordering, duplicate multiplicity, paths, ordinals,
types, presence states, and present-empty containers from the declared public
structured relations.

The equality verifier MUST compare exact built-in types, unit and row
cardinality, result/provider/duplicate order, header/path/field occurrence
ordinals, row/cell/node ordinals, scalar and container values, and missing/null/
empty/present states without invoking caller-defined equality. A stale,
self-resealed, foreign-schema, partially read, or resource-over-bound input MUST
fail closed before producing an equality receipt.

#### Scenario: The table verifier consults the body or receipt values

- **WHEN** structured reconstruction reads body bytes, extraction memory, a private cache, production parser/staging code, or receipt-embedded values to fill a public-table gap
- **THEN** no public-table projection or equality receipt is valid

#### Scenario: Both projections are individually sealed but differ

- **WHEN** body and table projections differ in any unit, order, duplicate, path, ordinal, type, presence, value, or present-empty structure
- **THEN** the observation remains incomplete and no downstream success authority may consume either projection

### Requirement: One W2 operation closes public value authority before journal success

For each finalized logical-call bundle, one `W2OperationReceiptV1` MUST bind the
Raw Authority V2 bundle and persistence receipt; body/bodyless authority;
expected units and representation assignments; public table schema, row, and
inventory roots; committed staging receipts and post-commit readbacks; field-
fate, conditional-route, and authenticated live-plan roots; ordered route-field
landing receipts; body and public-table projection receipts; their equality
receipt; bounded resource totals; and the operation semantic digest. A same-key,
same-content retry MAY return a verified replay receipt. Partial state, a same-
key/different-content collision, foreign root, reordered inventory, or missing
readback MUST fail closed.

The exact body object or bodyless packet authority MUST be persisted and read
back before parser-derived staging becomes an accepted success candidate.
Staging MAY then commit as a crash-recoverable candidate so its exact committed
readback can be derived. That candidate is not coverage or success authority
until the W2 operation is durably persisted and read back. Only then may request
closure and the extraction journal advance. This two-phase protocol MUST NOT
weaken capture of parser-input bytes before parsing.

The W2 operation MUST bind all six mandatory relation schemas but MUST bind row
roots only for the five relations that precede `raw_nba_api_w2_operation`; it
MUST NOT include its own row or table root in its semantic digest. A separate
`W2OperationPersistenceReceiptV1` MUST bind the inserted operation row, exact
post-commit table readback, and replay result. The stable operation key MUST omit
response/table content so same-key/different-semantic state is detected as a
collision.

#### Scenario: Staging commits but W2 closure is interrupted

- **WHEN** the process stops after staging commit but before an exact W2 operation readback
- **THEN** staging remains a recoverable nonterminal candidate, journal success is absent, and an exact retry either completes the same operation or fails on drift

#### Scenario: The W2 operation attempts to bind its own row root

- **WHEN** an operation semantic payload includes the `raw_nba_api_w2_operation` row or table root
- **THEN** the cyclic operation is invalid and no persistence or journal-success receipt may be emitted

#### Scenario: Valid drift is fully conserved

- **WHEN** additive or unknown provider data has exact body, public representation, verifier equality, route, staging, and W2 closure
- **THEN** its data call may be journaled as losslessly conserved while immutable drift blockers keep MODEL-GREEN and full publication red pending semantic review

### Requirement: Every result packet has an exact route and durable state

The system SHALL generate one route contract for every staging entry, including
provider and canonical result-set name/ordinal, exact source and storage columns,
schema, aliases/copies, provider authority, and required/optional/empty policy.

#### Scenario: An optional result set is absent

- **WHEN** an explicitly optional packet is not returned
- **THEN** the system records `absent_optional` distinctly from a present typed zero-row packet

#### Scenario: An unclassified result set is returned

- **WHEN** the exact provider returns a packet without a route or explicit disposition
- **THEN** the gate fails; the packet is not silently dropped

### Requirement: Landing rows preserve request and observation provenance

Every persisted provider row MUST carry collision-safe nbadb provenance that
binds it to the verified logical call, exact endpoint and result-set occurrence,
canonical request identity, all output-changing request dimensions,
observation time where meaningful, competition, provider authority, and source
row ordinal. Provenance MUST be additive, MUST NOT overwrite provider fields,
and MUST exclude credentials, headers, proxy/VPN details, and unrestricted
error bodies.

#### Scenario: A secondary packet depends on its parent request

- **WHEN** a shot-chart request returns detail and league-average packets
- **THEN** both packets retain the same material season, season-type, competition, entity/group, and context-measure request identity so later joins cannot combine unrelated observations by zone alone

#### Scenario: A provider column collides with an nbadb provenance name

- **WHEN** a response contains a field whose normalized name matches a reserved provenance column
- **THEN** both values remain losslessly addressable under deterministic non-colliding identities and terminal field conservation remains exact

### Requirement: Temporal availability is evidence-aware and discontinuous

The system MUST represent availability by exact provider, endpoint, result set,
parameter family, season type, entity/workload scope, and ordered non-overlapping
intervals. Planner fallback, sink readiness, and availability evidence MUST be
separate fields.

#### Scenario: A route has no documented minimum season

- **WHEN** planning uses 1946 as a conservative sweep start
- **THEN** the interval is labeled fallback/unverified rather than observed or supported

#### Scenario: A transient request fails

- **WHEN** a timeout, transport error, malformed response, or circuit failure occurs
- **THEN** it becomes inconclusive/transient evidence and cannot create an unavailable or blocked interval

#### Scenario: Support has a historical hole

- **WHEN** evidence contains non-contiguous blocked seasons
- **THEN** the model preserves each interval and the planner subtracts only those exact years

### Requirement: Every exact field occurrence has temporal proof

The temporal authority MUST key every field occurrence by provider, endpoint,
result ordinal, nested path or ordered duplicate-header occurrence, request
scope, competition, and season type. Each applicable occurrence SHALL record
its earliest and latest evidence, every internal gap, exact evidence source,
and distinct nonexistent, nonapplicable, result-missing, field-missing, null,
present-empty, populated, valid-empty, unavailable, blocked, snapshot, unknown,
and transient states. Endpoint support, schema presence, same-name fields, and
planner fallbacks MUST NOT be projected into occurrence evidence.

#### Scenario: A field appears only in the middle of an endpoint interval

- **WHEN** an endpoint result is evidenced from 1996 through 2026 but one exact field occurrence is populated only from 2001 through 2018 with verified absences outside that span
- **THEN** the field records its own earliest/latest evidence and outside states rather than inheriting the endpoint interval

#### Scenario: A field disappears and later returns

- **WHEN** the same exact occurrence has evidence before and after an internal range with verified field-missing or nonapplicable states
- **THEN** the internal range remains an explicit gap and is not collapsed into one continuous supported interval

#### Scenario: A duplicate header occurrence differs temporally

- **WHEN** two ordered occurrences share the same header text but have different observed seasons, values, or presence states
- **THEN** they retain separate temporal identities and neither occurrence may satisfy the other's coverage

#### Scenario: A field range remains unknown

- **WHEN** any applicable competition/season-type/request scope has not been observed or otherwise evidenced at exact field-occurrence granularity
- **THEN** MODEL-GREEN remains red even if the endpoint route and sink schema exist

### Requirement: Dependent comparison workloads are observation-bound

Comparison endpoints MUST execute only after a fully attested foundation
checkpoint produces a verified directional workload artifact. Affiliations and
lineup group IDs MUST NOT create opponent pairs or Cartesian requests.

#### Scenario: An exact player matchup is observed

- **WHEN** a verified foundation row proves a directional player matchup in an exact season/type scope
- **THEN** that exact direction may enter the dependent workload; an unobserved reverse direction is not synthesized

#### Scenario: A complete opposing lineup cannot be reconstructed

- **WHEN** rotations/substitutions do not prove two simultaneous valid five-player sides
- **THEN** the scope records typed zero/blocked evidence and no lineup request is scheduled

### Requirement: Cumulative-stat workloads are provider-foundation-bound

`CumeStatsPlayer` and `CumeStatsTeam` MUST NOT execute until their exact paired
games endpoint has produced a verified workload for the same entity, season,
and season type. The workload SHALL bind the ordered unique game IDs, provider
authority, foundation response receipt, and its own canonical digest. Game IDs
MUST use the provider's pipe-delimited representation and MUST NOT be inferred
from a broader league schedule.

#### Scenario: The paired games endpoint returns valid game IDs

- **WHEN** the exact player/team games foundation returns a structurally valid nonempty ordered game-ID sequence
- **THEN** the dependent cumulative-stat call receives exactly that sequence and persists the foundation/workload receipt binding with its result routes

#### Scenario: The paired games endpoint returns a valid empty result

- **WHEN** the exact foundation response is present, receipted, schema-valid, and contains zero rows
- **THEN** the dependent scope is recorded as typed-zero complete and no cumulative-stat provider call is made

#### Scenario: Foundation evidence is incomplete

- **WHEN** the foundation is missing, malformed, duplicated, unreceipted, timed out, or differs from restored workload authority
- **THEN** the dependent scope remains incomplete/resumable and no guessed or stale `game_ids` value is sent
