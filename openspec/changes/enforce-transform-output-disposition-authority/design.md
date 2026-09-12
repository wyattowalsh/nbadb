## Context

The repository currently exposes three distinct evidence layers:

1. `expected_transform_output_tables(include_live=True)` discovers transform
   output names.
2. `star_table_contract.compile_star_table_contracts()` compiles each output's
   schema, transformer, ordered columns, dependencies, and structural identity
   into `StarModelContractInventory`.
3. `successor_transform_authority.TransformOutputAttestation` commits to the
   ordered DuckDB schema and duplicate-preserving, row-order-independent
   multiset content of one physical relation.

None is an authored stable-public disposition. The current canonical
denominator is
`tuple(sorted(expected_transform_output_tables(include_live=True)))`, and it
must exactly equal
`tuple(table.output_name for table in compile_star_table_contracts().tables)`.
The first-generation observation is 261 outputs. That number is evidence about
the current bytes, not a V1 constant; future counts are always derived.

The public bundle is broader than the active transform set. Its exact table
universe is the normalized disjoint union of five typed components: Raw V2
exact-four, W2 exact-six, mandatory unique `STAGING_MAP`, typed-admitted
conditional staging, and verified active transform outputs. Current repository
authorities produce 709 tables/1,422 resources with no conditional staging and
711/1,426 when both conditional staging tables are admitted. These values are
drift-sensitive validation observations only. Runtime authority and the
existing resource contract derive every count and root.

## Goals

- Keep structural discovery complete and disposition-neutral.
- Require an exact authored row and independently replayed proof for every
  current transform output before governed runtime construction.
- Compile the expected current decisions from a repository-owned canonical
  authored corpus that is independent of the candidate envelope and proof.
- Keep each disposition entry digest strictly table-local.
- Make materialization evidence immutable and reusable without confusing it
  with a later operation's authorization.
- Give one verifier-owned transaction sole authority over canonical relation
  visibility, receipt persistence, binding closure, and operation commitment.
- Replace every transform/publication set reconstruction with mandatory typed
  authority and an exact full-publication union.
- Prove the cumulative data-producing operation denominator across lane,
  discovery, live, and successor capture before using Raw, W2, or conditional
  staging as publication components.
- Propagate identical component, union, operation, and receipt identities to
  every local and publication consumer.
- Fail closed on missing, stale, partial, ambiguous, overlapping, widened, or
  fallback evidence.

## Non-Goals

- This design does not author any disposition, synthesize independent review,
  or infer semantic acceptance from names, SQL, schemas, population, or tests.
- It does not filter structural discovery or promise a permanent output count.
- It does not export experimental outputs in V1.
- It does not add compatibility, fallback, dual-read, feature-flag, optional,
  or physical-discovery paths.
- It does not provide external SQL, DuckDB, or filesystem access control.
- It authorizes no live extraction, upload, remote readback, human review,
  commit, push, or green/publication claim.

## Decisions

### 1. Canonical structural authority is an exact two-source equality

The verifier independently computes:

```python
discovered = tuple(sorted(expected_transform_output_tables(include_live=True)))
compiled = compile_star_table_contracts()
assert discovered == tuple(table.output_name for table in compiled.tables)
```

It binds `compiled.contract_sha256` and every ordered per-table contract root.
Both sequences must be sorted, unique, nonblank, and exact. Missing, extra,
duplicate, reordered, foreign, or differently normalized names fail. No
disposition filter is accepted inside either structural authority.

The first authority generation records the current 261-row observation. Later
generations derive current count and roots from the same equality; they never
take a caller-supplied expected count. A new structural output leaves runtime
red until its authored entry and proof are complete. A compiler cannot generate
`contract_not_modeled`, a blocker, policy, capability, evidence, or proof.

### 2. Current entries are table-local; removed names are tombstones

`CurrentTransformOutputDispositionV1` contains only:

- exact normalized output name and table family;
- table-local star contract, schema, transformer, ordered-column, and exact
  dependency identities;
- state: `active`, `observed_only_experimental`, or
  `contract_not_modeled`;
- the complete authored capability policy required by that state;
- semantic claims, reason/evidence classes, exact table-local evidence
  references, and revalidation triggers; and
- its derived table-local entry digest.

The digest explicitly excludes structural-inventory and generation roots,
proof-pack and source-bundle roots, author/reviewer task or role strings,
change records, operation/transaction identities, materialization/receipt
identities, publication identities, and enclosing-envelope identities. Moving
an unchanged entry into a new otherwise unrelated authority generation leaves
its canonical bytes and digest unchanged.

`removed` is not a current-entry state. It exists only in an immutable
`TransformOutputRemovedTombstoneV1`, which binds the reserved name, exact prior
entry digest, removal change record/evidence, and first tombstone generation.
V1 forbids tombstone deletion, mutation, reversal, and name reuse.

### 3. Envelope parsing performs fresh local reconstruction

`VerifiedTransformOutputDispositionAuthorityEnvelopeV1` is strict canonical
UTF-8 JSON: sorted object keys, no insignificant whitespace, duplicate keys, or
non-finite numbers, and exactly one LF when persisted. Bounded parsing rejects
oversize bytes, excessive depth/nodes/collections/strings, unsafe paths, and
unknown fields before typed construction.

The envelope carries global facts outside entry digests:

- canonical structural name sequence/root and first-generation observation;
- `StarModelContractInventory.contract_sha256` and ordered per-table roots;
- exact current-entry and tombstone inventories/counts/roots;
- capability and dependency graph/order roots;
- initial marker or exact ordered change set and generation root;
- complete replayable source-bundle descriptor/root;
- independent proof descriptor/root and verifier implementation identity; and
- all derived envelope/component roots.

`from_canonical_bytes` accepts only canonical envelope bytes and a trusted
repository-owned source bundle. Separately, the current verifier compiles
`TransformOutputAuthoredDecisionAuthorityV1` from the checked-in canonical
authored-decision corpus. That authority is not reconstructed from the
candidate envelope, proof pack, or an envelope-carried authored projection.
Before returning a DTO the parser must, in order:

1. enforce bounded strict-canonical parsing and rederive all declared digests;
2. fresh-run both structural authorities and prove exact denominator equality;
3. reconstruct the current `StarModelContractInventory` and per-table roots;
4. replay every frozen source-bundle byte/projection and exact prior history;
5. reconstruct every candidate current entry, tombstone, capability, and
   dependency;
6. independently compile the current repository-owned authored decision
   authority and require exact output-name and complete decision equality;
7. rerun the current repository independent verifier implementation over the
   reconstructed proof inputs and authored authority; and
8. require exact equality between the authored authority, fresh verifier
   result, proof pack, envelope rows, state counts, graph, change set, and all
   roots.

Caller-provided DTOs, booleans, counts, roots, parsed response objects, or
claimed verification results are never accepted in place of this path.
Author/reviewer task and role strings are preserved as audit metadata only.
Inequality between those strings is neither independence nor admission.

### 4. Independent proof is replayed, not trusted by label

The checked-in canonical authored-decision corpus contains one explicit row per
exact current output and one explicit removal decision for every retained
tombstone. Each current decision owns exactly output name, an exact reviewed
`structural_table_authority_sha256` pin, state, all five capability-policy
booleans, semantic claims, reason code, evidence references, and revalidation
triggers. Each tombstone decision owns the reserved output name, prior authored-
decision revision, removal reason/evidence, and first tombstone generation.
Structural family, table contract, schema, transformer, ordered columns, and
dependencies remain independently derived, exact-joined by output name, and
required to equal the authored table-authority pin; derived entry/policy/
inventory/root fields are not authored.
The repository-owned compiler validates strict canonical bytes, sorting,
uniqueness, completeness, revisions, and table-local decision shape but never
fills an authored value. The proof bundle contains typed per-entry decisions
and positive, negative, and mutation evidence sufficient to rerun the current
verifier. The verifier rejects blanket acceptance, name/SQL-only inference,
self-produced inputs, missing implementation/evidence waivers, unsupported
decisions, and every missing/extra/duplicate/foreign/stale row.

Table-local authored evidence records live in the same canonical repository
resource but are reconstructed as deterministic typed source members below
`transform-output-disposition/evidence/<output-name>/<reference-id>.json`.
Claims and evidence references bind those projection content digests, never the
whole authored-corpus root, avoiding a self-digest cycle and preserving
unchanged entry bytes when unrelated evidence changes. The embedded main corpus
and projections are audit copies: current verification exact-compares them to a
fresh fixed-resource load, while historical replay uses each prior envelope's
immutable embedded authored source.

Admission compares the full reconstructed result, not selected digests or
task/role labels. Proof swaps, author/reviewer-label spoofing, verifier
implementation mutation, result substitution, and common-mode producer/reviewer
fixtures must fail. A protected decision-field mutation remains rejected even
when the candidate proof pack, source projection, verifier-result projection,
and envelope roots are all coherently resealed, because the independently
compiled repository authority is unchanged. Production exposes no caller DTO,
root, boolean, or alternate authored-authority injection path; fictional
fixtures use only a private test compiler. No governed consumer may start until
this replay succeeds.

### 5. Capability policy and dependencies are exact

The authored policy is fixed:

| Current state | Execute | Primary materialize | Stable load | Transform publication component | Chat ceiling |
| --- | ---: | ---: | ---: | ---: | ---: |
| `active` | yes | yes | yes | yes | yes |
| `observed_only_experimental` | yes | yes | no | no | no |
| `contract_not_modeled` | no | no | no | no | no |

Authors provide the complete policy; the compiler only verifies it. Active and
experimental outputs execute in the primary working DuckDB. V1 has no debug,
private, or compatibility export for experimental outputs.

Every dependency is classified as an exact transform-output edge or exact
registered staging/input contract. Unknown, missing, ambiguous, duplicate,
self, non-executable, and cyclic edges fail before execution. Capability edges
are `active -> active` and
`observed_only_experimental -> active | observed_only_experimental` only.
Non-executable entries cannot enter the executable graph. Deterministic graph
and topological-order roots are operation inputs.

### 6. Evolution references table-local entries externally

Each noninitial generation has a complete exact diff using one change kind per
actual change:

- `structural_addition`: newly discovered name plus complete new entry/proof;
- `state_transition`: same table-local contract with reviewed state/policy
  transition;
- `contract_rebind`: same current name with a changed table-local contract,
  claim, evidence, or dependency identity; or
- `removal`: exact prior entry leaves discovery and creates a tombstone.

Generation and change records reference old/new table-local entry digests; they
are not embedded into those digests. Renames are removal plus addition. Extra,
missing, overlapping, ambiguous, or incompatible change rows fail. A structural
addition with no authored/proven entry remains red.

### 7. Operation commitment owns generation bindings

`TransformOutputGenerationBindingV1` is per operation and binds:

- operation identity and exact current
  `transaction.generation_identity_sha256`;
- current envelope/generation and current table entry/policy/dependency roots;
- one immutable materialization receipt identity;
- one fresh physical-attestation replay equal to that receipt's attestation;
- exact canonical relation identity; and
- a reuse/rebuild classification derived by the verifier.

`TransformOutputOperationCommitmentV1` contains the exact sorted binding set,
structural/executable/active/non-executable/tombstone sets, dependency order,
table-local roots, binding root, and derived operation roots. All consumers
receive this DTO as a mandatory nonoptional argument. They cannot reconstruct
it from registries, environment, globals, schemas, filenames, or physical
relations.

It also binds `authored_decision_authority_sha256` and the precommit
`operation_data_evidence_sha256`. The independently compiled authored root is
propagated unchanged through proof results, the current/prior envelope chain,
generation bindings, commitment canonical bytes/projections, final operation
data authority, table/resource/final unions, terminal assurance, metadata,
ledger/rights/marker/readback, reconciliation, and success. It is never inferred
from `source_bundle_sha256`.

### 8. Materialization receipts remain tied to original materialization

`TransformOutputMaterializationReceiptV1` is immutable, table-local evidence
for one original materialization. It binds:

- output name and original materialization identity;
- the original materialization's exact
  `transaction.generation_identity_sha256` (never relabelled as the current
  operation's identity);
- exact entry, capability, contract, schema, transformer, ordered-column, and
  dependency roots applicable to that materialization;
- primary-working-DuckDB materialization scope; and
- the unchanged `TransformOutputAttestation` projection: `table_name`, ordered
  schema digest, row count, and duplicate-preserving multiset content digest.

A new receipt is issued only after a table is actually rebuilt or local
materialized bytes/schema drift. An unrelated envelope, generation, proof,
source-bundle, or publication change never creates, relabels, or invalidates a
receipt by itself.

A later operation may reuse an existing receipt only when the current entry,
policy, table contract, and exact dependencies are byte-identical to those in
the receipt and a fresh physical attestation equals the receipt. The operation
records that conclusion in a new generation binding. If any local identity or
physical attestation differs, reuse fails and the verifier requires a real
rebuild and a new immutable receipt. A receipt alone never authorizes an
operation or publication.

### 9. Exactly three internal tables are admitted atomically

An explicit migration installer in `core/db.py` creates, and a separate
read-only runtime path validates, exactly these new tables:

1. `_transform_output_disposition_authority`: immutable canonical verified
   envelope bytes and roots;
2. `_transform_output_materialization_receipts`: immutable receipt bytes and
   primary lookup identities; and
3. `_transform_output_operation_commitments`: immutable operation commitment
   bytes including the complete generation-binding set/root.

The authority table is one global non-branching chain: generation sequence is
globally unique, a non-null prior envelope may have at most one successor, and
generation one is the only null-prior root. DuckDB does not receive a
self-referencing foreign key: exact predecessor existence, immediacy, no-gap,
and no-cycle semantics are application-verifier responsibilities. Authority
rows are inserted oldest-to-newest. The operation table has one commitment per
operation identity and per transaction-generation identity. Its composite
foreign key binds the projected embedded envelope SHA and disposition-
generation SHA to the corresponding unique authority pair, so authority is
inserted first. Receipt-to-commitment closure remains verifier-owned rather
than an insertion-order-incompatible foreign key.

Database columns that are not canonical DTO fields are explicitly derived
projections. In particular, `authority_envelope_sha256` is exactly
`operation_commitment.authority_envelope.envelope_sha256`; canonical byte
length and byte digest columns are computed from the stored BLOB. Semantic
replay requires every projection to equal the decoded canonical DTO. Canonical
BLOB ceilings match the codecs, including their required trailing LF:
134,217,728 bytes for an envelope, 4,194,304 for a receipt, and 33,554,433 for
an operation commitment.

Runtime initialization never auto-installs these tables. It classifies all
three exact tables, whether empty or populated, as current; all three absent as
migration-required; and partial, wrong-shaped, temporary-shadowed, view-
conflicted, or otherwise conflicting state as repair-required. Explicit
`nbadb migrate` invokes the one-shot installer only for the all-absent state,
returns already-current for all-three-exact state, and never repairs or
replaces. Creation, normalized catalog introspection, and empty readback occur
in one installer-owned transaction. Catalog authority includes ordered column
name/type/nullability/default and normalized constraint columns, references,
and check semantics, but excludes unstable OIDs, generated names, raw DDL, and
engine-formatted constraint text. Persistent and temporary schemas are both
examined. There is no shape upgrade, row coercion, imported pre-cutover
receipt, or compatibility read.

A module lock serializes only same-process callers; the DuckDB transaction and
fail-closed post-state validation provide correctness across connections and
processes. The installer tracks `not_started`, `begun`, `commit_attempted`, and
`committed`. It rolls back only a transaction it successfully began. If begin
finds a caller-owned transaction, it leaves that transaction untouched. A
commit exception is uncertain rather than presumed rollbackable: the original
connection is poisoned/closed, a fresh file-backed connection classifies all
absent as a clean failed installation, all three exact as committed, and every
other state as repair-required.

### 10. One verifier-owned transaction controls canonical visibility

For each governed transform operation, a single transaction owned by the
verifier performs this order:

1. reverify the envelope and operation plan;
2. create/execute transaction-private candidate relations while existing
   canonical relations remain the only externally visible generation;
3. compute fresh candidate `TransformOutputAttestation` values;
4. validate and reuse an exact receipt or insert a newly justified immutable
   receipt, then exact-read it back;
5. atomically swap the complete candidate set into canonical names;
6. reattest canonical relations and require equality to candidate/receipt
   evidence;
7. close the exact `TransformOutputGenerationBindingV1` set;
8. construct, persist, and exact-read back the operation commitment containing
   those bindings; and
9. commit, making canonical relations and their complete commitment visible
   together.

Any exception, mismatch, process interruption, or injected fault before the
commit call rolls back the verifier-owned transaction's candidate visibility,
receipt insertions, swaps, bindings, and commitment rows. A commit-call
exception poisons the original connection and is classified from a fresh
file-backed connection because the commit may have succeeded. Fault-injection
tests cover before/after every boundary, including receipt insert/readback,
each swap boundary, post-swap attestation, binding closure, commitment
insert/readback, immediately before commit, and the commit-uncertain path. A
failed pre-commit rollback proves the original all-absent/pre-operation state
and a usable fresh transaction; commit-uncertain recovery proves either the
complete old state or complete new state and rejects every mixed state.

### 11. Cumulative operation data authority precedes transform commitment

The transaction first reconstructs non-admitting `OperationDataEvidenceV1`
from one `VerifiedOperationRawSnapshotV1`, one detailed current database W2
replay plus its public `W2DatabaseAuthorityReceiptV1`, and one typed cumulative
conditional-staging evidence inventory. It binds the exact operation, source,
chain, transaction generation, DuckDB snapshot, component roots, and a derived
evidence root. The transform commitment embeds only
`operation_data_evidence_sha256`; the evidence does not embed the commitment.
After successful commit, a fresh read-only exact replay of the committed
transform commitment and its referenced data evidence seals
`VerifiedOperationConditionalStagingAuthorityV1` and
`VerifiedOperationDataAuthorityV1`, which bind both the evidence and commitment
roots. This directed construction has no digest cycle and requires no fourth
internal table: detailed evidence remains in the existing Raw/W2 journals and
the final wrappers are propagated through terminal assurance artifacts. No
component may be captured before or after the owned snapshot and then paired by
the caller.

Every history-dependent collection in these evidence codecs is represented by
an exact count plus a domain-separated ordered SHA-256 prefix-fold root. The
empty state binds the versioned domain and count zero; each one-based ordinal
folds the prior raw 32-byte root and the next raw 32-byte leaf into a new root.
Order, omission, substitution, and duplicate multiplicity therefore change the
commitment, and a verified prior state can be extended without retaining its
historical member array.
Detailed Raw, W2, attribution, and conditional rows remain in their existing
strict-replayed journals; they are not copied into canonical JSON arrays or a
new authority table. Canonical JSON bounds apply only to the compact durable
envelopes and individual typed leaves. The verifier recomputes every count/root
incrementally from its owned transaction, so the general 20,000-member JSON
collection ceiling is never an extraction-history ceiling. Chunking may change
I/O only and cannot become an independently supplied authority or omission
boundary.

The Raw snapshot is derived by streaming the canonical manifest journal,
strictly parsing every stored manifest byte sequence, rederiving stored
columns, verifying contiguous generation/parent chains, replaying exact
operation rows and persistence receipts against the merged Raw exact-four and
bundle journal, and matching every terminal group to one typed denominator
member. `DurableRawTerminalManifestLocatorV1` contains only stable semantic
source/run/attempt/chain/lane/scope, route/request-closure/field/model/authority
roots, terminal generation/parent/manifest/operation/receipt identities, and
canonical byte length/hash. Process-local compiler HMACs, capability tokens,
physical table names, present booleans, and caller maps are not durable
authority.

Full extraction uses `FullExtractionRawOperationDenominatorV1`:

- exactly one Raw terminal member for every exact complete executable matrix
  lane, including dependent calls inside that lane's closure;
- exactly one discovery-seed Raw terminal member, including the
  discovery-owned `league_game_log` calls;
- exactly one post-merge live-snapshot Raw terminal member; and
- one canonical blocked-evidence member, with no Raw locator, for every exact
  contract-blocked lane.

Complete executable and blocked lane identities form the exact normalized
manifest-lane denominator. Discovery and live are typed auxiliary members, not
synthetic matrix lanes, so the terminal Raw member count is exact complete
executable lane count plus two. The discovery job must publish a
content-addressed Raw authority database whose journal, exact-four, bundle, and
W2 state are installed into the checkpoint. Live capture must finish and
persist its terminal Raw member before the verifier-owned transform transaction
begins; the current transform-then-live ordering is therefore reversed at the
cutover barrier. The exact full order is verified lane/discovery merge and
checkpoint-prefix installation, then one final live capture into that database,
then F.3 candidate transform materialization and canonical swap, then committed
wrapper readback. All live-derived transform outputs are rebuilt in F.3 from
the fresh live staging bytes; no pre-live transform output is reused as current.
All discovery/lane/live network calls finish before the database transaction;
F.3 performs no provider request while holding its snapshot or store locks.
Publication-grade export, physical-resource attestation, and scanning begin only
after committed wrapper readback. Any successor staging export produced before
F.3 is operation-scoped scratch evidence and is never promoted; authoritative
resources are regenerated or promoted only from the committed final union.

Successor execution uses `SuccessorRawOperationDenominatorV1`: an exact prior
cumulative assured snapshot plus exactly one new terminal Raw manifest for the
whole successor plan. Its expected-call inventory equals every unique dispatch
provider call, and its route inventory equals the exact union of all dispatch
requested scopes. A legacy baseline without prior Raw, W2, and conditional
roots requires a full assured rebuild; it has no physical-table fallback.
Ordinary and live successor dispatches are all captured by this single plan
operation before successor transforms; there is no second live operation.
The verifier identifies the exact delta locator once while streaming the
complete current journal, recomputes the current terminal count/root over every
locator, and requires the incremental fold state at the exact prior-count
boundary to equal the strict-replayed prior count/root. The delta must be the
sole suffix member and equal the typed delta locator in full. It never needs a
flat embedded prior-member list or a second database connection.

The detailed final W2 multiset is independently replayed from the same database
snapshot. The prior successor or checkpoint W2 multiset must be an exact subset
of the final multiset, and every addition must be attributable to the exact
delta, discovery, or live member that produced it. Conditional membership is
derived only from cumulative terminal attempts whose exact typed stats/live
route admissions, route-authority roots, landings, and persistence receipts
agree. It is never inferred from source family, a boolean, caller-present keys,
or physical table existence, and previously admitted conditional tables cannot
disappear merely because a successor delta had no new conditional landing.
Each conditional leaf also binds its exact typed Raw source role and member
identity: live-node evidence may originate only from the live-snapshot member
or a route-proven successor delta, while stats-result-cell evidence may
originate only from an executable/discovery member or a route-proven successor
delta. Raw, W2, and conditional successor evidence all bind the same exact
prior `OperationDataEvidenceV1`; F.3 strict-replays that prior evidence before
accepting any prior component root.

VPN preflight, capacity admission, and installed-stack canaries are control
calls and contribute zero dataset Raw members. Classification comes from the
owning typed workflow adapter, not an endpoint name or caller flag: the same
endpoint may be excluded as a control probe and included when discovery uses
its response as dataset input. Control responses cannot be reused as dataset
bytes.

Bounds come from the native strict Raw codecs and the exact typed denominator.
Journal replay is streaming and never truncates or silently drops a group.
Any additional aggregate bound must first be characterized from current and
worst-case planned manifests, encoded as a versioned fail-closed contract, and
covered at its boundary; arbitrary convenience ceilings are not admitted.

### 12. Stable publication is sealed through one neutral resource authority

Transform disposition controls only the active-transform component.
Publication identity is compiled in three ordered phases. First,
`StablePublicationTableUnionV1` is built from the exact transform commitment
and its same-snapshot `VerifiedOperationDataAuthorityV1`:

1. Raw V2 exact-four;
2. W2 exact-six;
3. all mandatory unique normalized `STAGING_MAP` tables;
4. exactly the cumulative conditional staging tables in
   `VerifiedOperationConditionalStagingAuthorityV1`; and
5. exactly the verified `active` transform names and generation bindings.

For each component it binds authority/schema identity, normalized sorted table
names, count, and table-root. It proves pairwise disjointness and derives the
sorted union table names/count/root. Duplicate-normalized names, component
omission/substitution, component overlap, unexpected conditional staging,
active-transform mismatch, or any physical relation offered as membership
authority fails.

Second, a Kaggle-neutral compiler outside `nbadb.kaggle` consumes only the
exact operation commitment, `StablePublicationTableUnionV1`, and canonical
`PublicationResourcePathPolicyV1`. It produces immutable
`OperationPublicationResourceContractV1`, binding the operation, table-union,
path-policy schema/version/root, ordered typed resource entries, exact count,
content-only inventory root, and complete contract root. The policy preserves
the existing correct projection: exactly four fixed file resources and one CSV
file plus one Parquet resource for every table. Parquet directory-versus-file
identity comes only from the canonical partition policy. Typed role projections
bind the two per-table resources back to each of the five components.

Third, `StablePublicationUnionV1` is sealed only from a matching table union and
resource contract. It binds every component table/resource count/root plus the
union table/resource counts/roots and rejects any operation, component,
table-root, policy-root, resource-count, resource-root, or contract-root
mismatch.

Expected resource identity never depends on module globals, transformer or
schema discovery, import order, a physical DuckDB catalog, a filesystem tree,
symlink state, file existence, caller-supplied conditional booleans, or an
observed remote inventory. A separate physical-resource attestor checks
existence, regular-file/directory shape, symlink policy, content, completeness,
and absence of extras against the immutable resource contract. Observation can
report drift but cannot change expected membership, path, or kind.

Kaggle metadata, successor publication inventory and assurance, the Kaggle
client, export, and scanner all consume this same operation-bound resource DTO
and its typed role projections. The cutover removes the legacy Kaggle-owned
membership derivation, manual conditional reconstruction, path-based control
stripping, and duplicate resource traversal in one fail-closed barrier; there
is no dual read or compatibility wrapper.

No fixed table/resource count is an input. A current validation may assert the
drift-sensitive observations 709/1,422 at zero admitted conditionals and
711/1,426 at two, but runtime acceptance derives and binds its values from the
five authorities. Physical `get_user_tables` may be compared as negative drift
evidence; it is never denominator authority.

### 13. Publication identities propagate without substitution

Export, full-publication scan, successor terminal report, assured artifact
manifest, operation-bound Kaggle metadata, publication-ledger intent,
publication rights, publication marker, exact remote readback,
reconciliation, and success resolution each bind:

- all five component authority/count/table/resource roots;
- table-union, path-policy, resource-inventory, resource-contract, and final
  union table/resource counts and roots;
- exact public DuckDB SHA-256;
- verified disposition envelope and active-transform component roots;
- operation commitment, generation-binding, and receipt roots;
- cumulative Raw-snapshot, W2-database, and conditional-staging roots;
- operation-data evidence and final verified operation-data roots; and
- the existing chain/source/coverage/artifact identities required by that
  layer.

Every boundary reconstructs or exact-compares the typed commitment. Omitting or
substituting a component, widening from physical relations, changing resource
derivation, or mixing identities from two operations fails before output
freeze, mutation, reconciliation, or success. A valid old table receipt cannot
substitute for fresh operation binding or new bundle/publication evidence.

### 14. Chat remains explicitly curated, including its internal table

The current curated route catalog requires 26 tables: 25 transform outputs and
the internal `_pipeline_metadata`. Catalog admission and pre-query recheck
apply the `active` disposition and current receipt/binding checks to the 25
transform tables. `_pipeline_metadata` is not a transform output and must have
separate explicit internal-route authority and availability checks. It must not
be dropped by, or smuggled through, the active transform filter.

An active transform creates no route, alias, or SQL. A nonactive/stale transform
dependency or missing internal-table authority blocks the affected catalog or
query before SQL. Agent context follows the same curated authority and cannot
fall back to physical discovery.

### 15. All-consumer cutover is mandatory and mechanically enforced

The cutover inventory covers `TransformPipeline`, orchestrator
`_transform_and_load`, `create_multi_loader` and loaders, export CLI/helpers,
schema registries, scanner, artifact identity, successor
assurance/runtime/coordinator/inventory, Kaggle metadata/client/ledger/rights,
docs generators, chat catalog/runtime/SQL, and agent context.

AST/import/call-site and runtime gates reject optional/default authority,
feature flags, compatibility or dual-read branches, globals, registry-derived
stable sets, `get_user_tables` authority, component omission/substitution,
overlap, physical widening, and unclassified consumers. The migration requires
`N inventoried = N migrated = N tested`.

## Validation Strategy

The implementation test index maps every scenario to executable families:

- `ENV`, `DEN`, `DET`, `EVD`, `ENT`, `DTO-LOCAL`: strict bytes, exact
  denominator, deterministic roots, complete replay, and table-local digest
  exclusions;
- `PRF`: fresh verifier replay, proof/result swaps, task/role spoofing,
  verifier mutation, and common-mode rejection;
- `GEN`, `CHG`, `TMB`, `DEP`, `CAP`: evolution, tombstones, graph, and
  capability policy;
- `REC`, `GEN`: immutable original receipts, fresh physical replay, legitimate
  reuse bindings, and rebuild-only new receipts;
- `DB`, `TX`: exact three-table all-absent migration, shape/readback failures,
  same-snapshot subordinate authority replay, and every transaction fault
  boundary;
- `OPA`: cumulative Raw denominator, durable locator replay, discovery/live/
  successor cardinality, W2 subset attribution, conditional derivation, and
  control-canary exclusion;
- `PUB` and `RES`: five-component table union, neutral operation-bound resource
  derivation, physical attestation, omission/substitution/overlap/widening, and
  cross-layer root propagation; and
- `CUT`: mandatory DTO signatures, complete consumer inventory, chat's
  transform/internal split, and absence of every fallback.

Acceptance runs strict OpenSpec validation, focused contract/runtime/database/
publication/chat packets, repository static and type checks, SQL lint, complete
unit assurance, generated-doc no-drift validation, and independent read-only
reviews. No local result is external publication or model/data-green evidence.

## Migration and Rollback

This is a clean break. Runtime implementation cannot activate until the exact
authored denominator and fresh independent-verifier replay are complete. On an
all-absent database the three internal tables are created atomically. Any
partial or incompatible database blocks and requires an explicit separately
reviewed repair; runtime does not guess or backfill evidence.

Rollback is version control plus restoration of a database taken before the
new transaction protocol. There is no runtime fallback to pre-authority
behavior and no conversion of unverified pre-cutover materializations into
receipts.

## Open Questions

No policy question remains open. Implementation may choose internal SQL column
layouts and bounded parser limits only if they preserve the exact typed models,
three-table shapes, transaction ordering, and fail-closed scenarios above.
