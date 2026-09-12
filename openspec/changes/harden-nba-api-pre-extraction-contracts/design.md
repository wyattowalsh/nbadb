## Context

The current local planning snapshot installs and locks `nba-api==1.11.4`, but
the execution authority is not allowed to assume that snapshot remains the
newest compatible stable release. At execution kickoff, nbadb enumerates the
official non-yanked stable releases newest-to-oldest, compatibility-tests each
candidate against the repository stack, and freezes the first passing release
with its distribution/source/docs/tools/runtime evidence. Nbadb already owns
retry, circuit, checkpoint, support-rule, schema, transform, and publication
policy. The provider-boundary work introduced nbadb-owned result packets and
exact release provenance, but the full pre-extraction audit found four
remaining category errors:

1. expected constants were treated as observed provider evidence;
2. generated contract metadata was described as physical bronze;
3. planner fallback/schema presence was described as temporal availability;
4. transform/schema presence was described as semantic gold completeness.

The design must correct those errors without replacing complex upstream
parsers, changing semantic lane identity, or silently dropping provider data.

## Decisions

### 1. Provider ownership is split by responsibility

Generated endpoint classes, parameter encoding, static reference data, and
active V2/V3/live parser implementations remain upstream behind the adapter.
Nbadb owns an independently generated exact-tag contract, invocation/result
value types, headers/timeouts/session policy, failure classes, response
envelope checks, parser conformance, provenance, and replay. Runtime adapter
validation compares returned packets to the nbadb bundle, not to the same
installed class that produced the request.

### 2. Observation authority includes the exact public parser input

Every successful body-bearing provider response is captured immediately after
return and before JSON decoding or parser entry as an exact parser-input body.
That value is the exact byte sequence consumed by the provider parser after any
transport decoding; it is not described as compressed wire bytes or HTTP
framing. The public authority contains or losslessly addresses the complete
body object itself. A digest, byte count, cache path, or private-only object is
not a substitute for public object availability.

The public body record binds its bytes, full SHA-256, length, content encoding,
logical invocation, ordered provider-call occurrence, retry attempt, request
identity, provider authority, and observation provenance. A content-addressed
physical representation MAY deduplicate identical bodies, but every logical
attempt retains its own body receipt and the body remains part of the public
raw authority and Kaggle inventory. A provider path with no parser input uses a
separate explicit bodyless disposition; a transport or rejected response never
invents a successful body record.

Before semantic loss, the same successful observation also preserves endpoint,
provider result name and ordinal, canonical route, ordered headers or nested
paths, source row ordinal, values and types, null/empty/presence state, and
committed logical/result/route/staging receipts. Static providers use
deterministic canonical JSON-derived rows bound to their exact source digest.
For every body-bearing observation, assurance independently parses the exact
public body object and also reconstructs the ordered packet using only the
public structured request/result/header-or-path/value/presence tables. Both
outputs must match each other and the committed packet in result occurrence,
ordered fields, row ordinals, types, presence states, and values. This
table-only reconstruction cannot consult the body object, private caches, or
the extraction-time in-memory packet. Cookies, request headers, proxy/VPN
details, credentials, authorization data, and unrestricted error bodies are
excluded from landings, receipts, logs, exports, and Kaggle staging.

### 2a. Public value authority has its own closed representation domain

Raw Authority V2 remains the exact-four body/request/result/route authority.
`PublicValueAuthorityV1` is a separate schema and digest domain rather than a
silent extension of the raw-authority schema version. Its mandatory base public
relations are `raw_nba_api_result_cell`,
`raw_nba_api_stats_lossless_record`, `raw_nba_api_live_lossless_node`,
`raw_nba_api_value_representation`, `raw_nba_api_route_field_landing`, and
`raw_nba_api_w2_operation`. Conditional stats/live staging tables retain their
observed-only publication policy; they do not substitute for mandatory raw
structured reconstruction rows.

The expected representation denominator is independently derived from each
selected-terminal Raw Authority V2 bundle. It contains one result-occurrence
unit per selected occurrence plus one response unit whenever independently
decoded conditional rows are not owned by an occurrence or an admitted
fixed-zero response has no occurrences. Every unit receives exactly one
`ValueRepresentationAssignmentV1` from the closed domain
`rectangular_result_cells_v1`, `stats_lossless_records_v1`,
`live_lossless_nodes_v1`, `response_lossless_records_v1`, or
`response_fixed_zero_v1`. The orthogonal source-input kind is
`parser_input_body` or `declared_bodyless_packet`. A representation follows the
sealed output contract, so an anomaly-aware stats fallback remains lossless even
when its rows are rectangular. Missing, extra, duplicate, reordered, or
cross-observation assignments fail the complete bundle.

Raw Authority V2 does not itself prove hybrid response-residual ownership and
its `bodyless_evidence_sha256` is not the exact static packet. Every selected
stats/live observation therefore owns one exhaustive `LosslessOwnershipReceiptV1`
that partitions every decoded record between an occurrence and the response
residual, emits zero-record partitions for selected occurrences, and proves a
zero residual explicitly. Static observations additionally require an exact
persisted `DeclaredBodylessPacketV1` and
`DeclaredBodylessPacketReadbackReceiptV1`; digest-only evidence never satisfies
body projection. Mandatory live-node authority is emitted even when no
conditional live drift route exists.

`BodyValueProjectionReceiptV1` is derived only from exact parser-input bytes or
the exact declared bodyless packet. `PublicTableValueProjectionReceiptV1` is
derived only from public structured rows; it cannot read body payloads, private
caches, extraction memory, production parser/staging code, or receipt-embedded
values. `ValueProjectionEqualityReceiptV1` performs exact built-in-type and
cardinality comparison across units, result/provider/duplicate order, paths,
ordinals, types, values, presence states, and present-empty containers. These
three receipts remain separate mandatory assurance children so neither
projection can validate itself.

### 3. Durability is ordered and idempotent

The safe order is two-phase without weakening pre-parser capture. First capture,
persist, and read back the exact parser-input body or explicit bodyless packet
authority before parser-derived staging becomes an accepted candidate. Then
persist the exact post-normalization staging frame in one DuckDB transaction and
read back its committed receipt outside that transaction. The staging commit is
a crash-recoverable candidate, not successful coverage.

After committed readback, build and validate the public-value representation,
both independent projections and their equality receipt, route-field landing
receipts, and one `W2OperationReceiptV1`. That operation binds the Raw Authority
V2 bundle/persistence receipt, body/bodyless identity, expected-unit and
representation roots, public table schema/row roots, committed staging receipt/
readback inventory, field-fate/conditional/live-plan roots, ordered route-field
receipt inventory, verifier receipts, and resource totals. It is durably
persisted and read back before request closure or journal success. Exact replay
is a no-op; partial state, same-key/different-content, foreign roots, or reordered
inventories fail. A crash before exact W2 readback leaves nonterminal journal
state and cannot satisfy request, checkpoint, resume, assurance, or publication
completion.

The operation binds schemas for all six mandatory relations but row roots for
only the first five; including the operation row in its own semantic digest
would create a hash cycle. A separate `W2OperationPersistenceReceiptV1` binds
the inserted operation row and exact post-commit table readback. Its stable key
is content-independent, so same-key/different-semantic state is a detectable
collision rather than a different operation.

### 4. Coverage identity remains semantic

Provider, parser-input, schema, and route digests are associated attestations.
They do not enter `lane_id`, `coverage_units_hash`, or checkpoint coverage
identity. This preserves the transactional recovery contract while making
provider drift fail admission.

### 5. Temporal evidence is independent of planning policy

`min_season=None` may continue to yield a 1946 planner fallback, but it means
`fallback_attempt_unverified`, not supported availability. A temporal scope is
provider-, endpoint-, result-occurrence-, competition-, parameter-pattern-,
season-type-, and workload-bound and owns ordered non-overlapping intervals.
Every field occurrence is keyed by endpoint, result ordinal, nested path or
ordered header occurrence, request scope, competition, and season type. It
records exact applicability, earliest and latest evidence, every internal gap,
and distinct nonexistent, nonapplicable, result-missing, field-missing, null,
present-empty, populated, valid-empty, unavailable, blocked, snapshot,
unknown, and transient-failure states. Schema presence is only `sink_ready`.
Unknown, inferred, or unprobed field ranges remain blocking; neither an
endpoint interval nor a planner fallback may be projected into field evidence.

### 6. Dependent requests are a second phase

Foundation endpoints run and checkpoint first. A verified builder derives only
directly observed directional player-matchup, team-player, and exact five-v-five
stint workloads. A later child manifest schedules those units. Group IDs or
affiliations cannot synthesize opponent pairs; an incomplete lineup state
produces typed zero/blocked evidence, never a Cartesian fallback.

### 6a. Cumulative-stat requests have their own foundation barrier

The pinned `CumeStatsPlayer` and `CumeStatsTeam` constructors require an exact
pipe-delimited `game_ids` value. Their paired `CumeStatsPlayerGames` and
`CumeStatsTeamGames` endpoints are the provider-owned authority for that list.
The planner therefore persists and attests the paired games result first, then
creates one immutable workload value bound to entity kind and ID, season,
season type, ordered unique game IDs, provider authority, and the foundation
receipt. The dependent stats call may run only from that value.

A structurally valid zero-row foundation is typed-zero completion and schedules
no dependent provider call. Missing, malformed, duplicated, unreceipted, or
inconclusive foundation evidence remains resumable incomplete state. A league
game log may corroborate team scopes but cannot replace the player-specific
provider foundation. This dependency changes neither semantic lane identity nor
the coverage hash; its workload digest is a required associated attestation.

### 6b. Landing rows retain request and observation identity

Provider result rows are not self-describing. Every persisted stats, live, and
static row therefore carries an nbadb-owned provenance envelope derived from
the verified logical-call receipt: source endpoint and result-set occurrence,
canonical request identity, explicit output-changing request dimensions,
observation timestamp or snapshot date where applicable, provider authority,
and source row ordinal. These columns are additive landing metadata and never
replace or overwrite provider columns. Sensitive transport details and
unbounded request values remain outside public tables.

Request-owned packets such as shot-chart league averages MUST retain the same
season, season type, competition, player/team/group, and context-measure
identity as the detail request that produced them. A downstream join may use a
benchmark only when its complete request identity is compatible; zone names
alone are never sufficient and can otherwise multiply rows across historical
requests.

Snapshot endpoints MUST NOT be backcast into historical versions. In
particular, `CommonPlayerInfo` accepts a player identifier but no season and
describes current identity/team state. Its observations may build history only
from explicit observation timestamps collected since adoption. Historical
player-team-season membership comes from season-bearing roster, game-log, or
career sources, not a fabricated `season` column on `CommonPlayerInfo`.

### 7. Model admission is census-driven and disposition-complete

An independent candidate census starts from the complete frozen provider
surface, request/result/field routes, source concepts, current registries,
transforms, schemas, and documented analytical needs; it is not derived only
from the models already implemented. One versioned `StableModelDispositionV1`
accounts for every candidate as `stable`, `experimental`, `withheld`, or
`rejected`, with evidence, owner, reason, implementation status, dependencies,
promotion/revalidation path, and public-gate effect. A candidate needed for
losslessness or a defensible stable model cannot be marked withheld merely
because implementation is missing; that state remains MODEL-red.

The 261 existing output names and every newly admitted stable or experimental
output each get a compiled contract with explicit purpose, grain columns,
either a key/uniqueness policy or reviewed bag policy, join/SCD semantics, row
operations, lineage, temporal applicability, stability, and ordered output
parity. Raw, staging, star, conditional typed-lossless, metadata, docs, export,
and Kaggle inventories are generated from the frozen disposition/contract
registries rather than duplicated constants. Every stable provider result has
a typed lossless raw/staging route or an explicit admissible public-safe
universal route while drift is reviewed.

A correction that changes grain or meaning uses a versioned replacement and
deprecation entry rather than a silent break. Experimental outputs live under
an explicitly segregated namespace, do not satisfy stable coverage, do not
gate stable publication, and cannot be promoted without a reviewed versioned
contract, deterministic implementation, lineage, temporal scope, validation,
and a new disposition. Table and Kaggle resource counts are generated from the
frozen manifest rather than hard-coded.

An existing SCD label is not preserved merely for compatibility when its source
has no temporal discriminator. The compiled table disposition must either bind
versions to real observation authority, demote the table to a truthful current
snapshot, or replace it with a versioned model sourced from historical facts.

### 8. Field fate is exhaustive; metric completeness is finite

Every declared or observed field has one storage and semantic fate, but not
every field must produce a metric. The registry covers every public sourced
measure and every computed numeric alias. SQL expressions and implementation
digests are generated; semantic qualifiers (unit, scale, weighting,
aggregation, eligibility, tie/window/null
policy, season/era applicability, use cases, and misuse risks) are reviewed
overrides. Unsupported qualifications are marked `blocked_pending_evidence` or
quarantined from semantic consumers. No proprietary score or arbitrary feature
is invented.

### 9. Assurance is one generation

One command freezes a source/provider/tool context, writes all children to a
fresh directory, validates required membership and parent digests, writes the
manifest last, and verifies a second semantic generation. Timestamps and local
paths are nonsemantic; parameter, result-set, column, route, and dependency
orders remain semantic. A directory of individually valid files is not proof.

The mandatory child set is independently derived from the assurance profile
schema and frozen registries, never accepted from a hand-maintained child-name
tuple or from whatever files happen to exist. At minimum it closes provider and
package surface authority, request/constraint/competition closure, exact body
and structured table-only reconstruction, route and field conservation,
field-occurrence temporal evidence, model dispositions/contracts,
metric/use-case and lineage coverage, semantic-diff policy, deterministic
generation, exact local-test receipts, and independent-review receipts. Every
child binds its own inputs and declared parents; an omitted, duplicate, stale,
unbound, or implementation-gap child keeps MODEL-GREEN red.

### 9a. Authority changes choose full versus delta conservatively

Before any initial extraction, daily/monthly update, backfill, resume, or
publication admission, an independently verified `AuthoritySemanticDiffV1`
compares the previous admitted authority with the complete newly frozen
authority. It classifies every provider/package/request/result/header/field,
temporal, competition, route, model, schema, key, type, meaning, lineage, and
assurance-child change and records the exact affected scope and proof.

Only an exactly enumerable additive or bounded compatible change may select a
delta: since-last-observed refresh, recent-window refresh, or targeted backfill
over the proven affected scopes. Any identity, key, type, meaning, route,
header-occurrence, coverage, temporal, competition, model-disposition, or
reconstruction break—and every unknown, ambiguous, incomplete, or missing
baseline—requires a fresh full authority. The selected mode and bounds are
receipt-bound to planning and workflow admission; callers cannot override a
full decision with a cheaper delta. The first extraction under this change is
always full regardless of diff classification.

### 10. The first assured dataset is a fresh GitHub Actions restart

Parser-input observations, fixed-point request identities, universal field
routes, competition keys, and corrected model semantics change what a complete
checkpoint means. Historical checkpoint artifacts remain valuable incident and
migration evidence, but they cannot be promoted into the new assured identity.
After local MODEL-GREEN and separately authorized release materialization, the
initial DATA-GREEN chain starts at attempt one from an empty candidate under the
exact new source SHA. Later recovery may use only checkpoints created under
that identical contract/source identity.

GitHub Actions is the only initial, catch-up, recurring, and publication control
plane. Production may use only services and capacity independently proven free
at the point of use; NordVPN, another paid proxy/VPN, a free trial, or an
existing paid subscription is not an admissible dependency. One proven
NBA-reachable slot may run the complete request universe serially; additional
slots may increase throughput only after the same free-capacity, route,
reachability, and isolation evidence passes for each slot. If no such path is
available, the chain reports `capacity_blocked` before provider calls and keeps
the complete request universe intact. Planning and execution do not infer
capacity from the user's phone, Mac, account allowance, or prior subscription.
Stable source/silver/gold outputs gate release; fitted RAPM, xFG, WPA, forecast,
rating, and prospect-value outputs remain separately versioned experiments
unless individually admitted and never make a complete stable release fail.

The active `full-extraction-transactional-recovery` change continues to own
checkpoint, queue, lane, replay, and publication mechanics. Its historical
configured-VPN and four-to-six-slot capacity clauses must be reconciled to this
free-only admission rule before cross-change assurance; neither change may be
declared implementation-ready while that normative conflict remains.

Remote readback alone does not close the baseline. The exact positive Kaggle
version must also be force-downloaded into a fresh owner-only local root and
manually interrogated with DuckDB read-only/external-access-disabled and SQLite
immutable/read-only checks. The local database, schema, row, key, format, body,
and receipt observations must bind back to that exact version.

## Alternatives Rejected

- Forking or fully reimplementing `nba_api`: no evidence shows that replacing
  generated declarations or complex parsers is safer.
- Calling decoded response text “raw HTTP”: compressed wire bytes and transport
  framing are intentionally outside this representation contract.
- Treating a private successor store, second repository, or GHCR package as the
  public data authority: the verified Kaggle version already provides the
  recurring baseline and GitHub artifacts already provide bounded recovery.
- Treating passthrough, same-name matches, schemas, or `SELECT *` as semantic
  lineage: these are routing hints, not proof.
- Adding a consolidated public table or renaming current tables solely for
  conceptual purity: public-format impact lacks consumer/migration evidence.
- Sampling, truncating, or dropping successful result packets, fields, values,
  or presence states to fit a guessed budget: capacity failure is a hard stop.
- Supplying an empty, arbitrary, season-wide, or league-log-derived `game_ids`
  value to cumulative-stat endpoints: it changes provider meaning and cannot
  prove player-specific membership.

## Risks And Mitigations

- **Storage amplification:** stream and batch public bodies and public-safe
  landing rows; benchmark representative fixtures; enforce response/lane/
  checkpoint/free-space caps; preserve finalization headroom. Physical body
  deduplication and deterministic compression may reduce storage but never
  remove a logical body receipt or the public parser-input authority.
- **Sensitive transport leakage:** use an explicit public metadata allowlist,
  validate paths and members, scan exports for transport secrets, and exclude
  cookies, headers, credentials, proxy/VPN data, and unrestricted error bodies
  from every durable body/landing and diagnostic boundary.
- **Generated self-proof:** bind a verified checkout receipt and immutable
  fixtures; make import/discovery failures fatal; compare runtime packets to the
  independent bundle.
- **Semantic overclaim:** require explicit dispositions and quarantine
  unsupported metrics/outputs from chat/docs recommendations.
- **Dirty-tree races:** hash relevant inputs before and after generation and
  reject drift; use one writer for overlapping surfaces.

## MODEL-GREEN Versus DATA-GREEN

`MODEL-GREEN` proves local contracts, fixtures, deterministic generation, and
fail-closed planning. It does not prove that the dataset is populated.
`DATA-GREEN` is a later, separately authorized, row-level terminal gate over
actual calls, public parser-input bodies, public-safe bronze receipts,
silver/gold reconciliation, keys, foreign keys, metrics, assured artifacts,
remote publication readback, and exact-version manual database interrogation.
