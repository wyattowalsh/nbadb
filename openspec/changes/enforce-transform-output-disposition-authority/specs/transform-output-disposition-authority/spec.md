## ADDED Requirements

### Requirement: Structural discovery SHALL remain complete and exact

The canonical current transform-output denominator SHALL be
`tuple(sorted(expected_transform_output_tables(include_live=True)))` and SHALL
exactly equal
`tuple(table.output_name for table in compile_star_table_contracts().tables)`.
The verifier SHALL bind `StarModelContractInventory.contract_sha256` and every
ordered per-table contract root. It SHALL derive the current count from these
authorities. The current 261-output first-generation value SHALL be recorded as
a drift-sensitive observation, not a timeless constant.

#### Scenario: Both authorities agree (`DEN-001`, `DEN-002`)

- **WHEN** the structural registry and fresh star-contract compilation return
  the same sorted unique names and table roots
- **THEN** the exact denominator, count, inventory root, and per-table roots are
  admitted as structural evidence
- **AND** no disposition filter is applied to either source.

#### Scenario: Structural evidence differs (`DEN-003`, `DEN-004`)

- **WHEN** either sequence has a missing, extra, duplicate, reordered, foreign,
  blank, or differently normalized name, or any per-table root differs
- **THEN** authority construction fails before a disposition DTO is created.

#### Scenario: A later structural output appears (`DEN-005`, `DEN-006`)

- **WHEN** current structural discovery contains an output absent from the
  authored and independently proven entry set
- **THEN** the generation remains red
- **AND** no compiler manufactures a blocker, state, capability, evidence row,
  or proof for the addition.

### Requirement: Canonical envelope parsing SHALL fresh-reconstruct authority

`VerifiedTransformOutputDispositionAuthorityEnvelopeV1.from_canonical_bytes`
SHALL be the only runtime construction path. It SHALL enforce bounded strict
canonical UTF-8 JSON, rederive every digest/count/root, fresh-run both
structural authorities, reconstruct the current `StarModelContractInventory`,
replay the complete source bundle and prior history, reconstruct every entry,
tombstone, capability, and dependency, independently compile the current
repository-owned `TransformOutputAuthoredDecisionAuthorityV1`, rerun the current
verifier against that authority, and require exact equality among authored
authority, supplied proof, verifier result, and envelope before it constructs
the DTO. The authored authority SHALL be compiled from the checked-in canonical
authored-decision corpus, not projected from the candidate envelope or proof.

#### Scenario: Exact envelope replay succeeds (`ENV-001`, `ENV-002`)

- **WHEN** canonical bytes, current repository authorities, source bundle,
  independently compiled authored decisions, proof inputs, current verifier
  result, and derived roots are exact
- **THEN** one immutable typed envelope is constructed.

#### Scenario: Caller supplies a claimed result (`ENV-003`, `ENV-004`)

- **WHEN** a caller supplies a parsed DTO, `verified` boolean, count, digest,
  state, proof result, source projection, or authority object instead of the
  fresh reconstruction path
- **THEN** construction fails without a permissive overload.

#### Scenario: Canonical bounds or encoding fail (`ENV-005`–`ENV-008`)

- **WHEN** bytes contain duplicate keys, unknown fields, non-finite numbers,
  noncanonical whitespace/order/LF, invalid UTF-8, excessive bytes/depth/nodes/
  collections/string length, or any declared digest mismatch
- **THEN** parsing fails before typed values are exposed.

#### Scenario: Current authored decisions come from one fixed repository source (`ENV-009`)

- **WHEN** current verification reconstructs disposition entries
- **THEN** it fresh-loads one fixed canonical repository corpus with exactly one
  explicit current decision per structural output and every retained removal
  decision
- **AND** each current decision binds output name, reviewed structural-table-
  authority pin, state, complete policy, claims, reason, evidence, and triggers
- **AND** the public verifier accepts no path, source, compiler, registry, mode,
  root, DTO, callback, or boolean override.

### Requirement: Current disposition entries SHALL be strictly table-local

Each `CurrentTransformOutputDispositionV1` SHALL bind only its exact output
name/family, table-local star contract/schema/transform/ordered-column/
dependency identities, current state, complete authored capability policy,
semantic claims, reason/evidence classes and references, revalidation triggers,
and derived table-local entry digest.

The entry and its digest SHALL NOT contain or derive from global structural
inventory or generation roots, proof/source-bundle roots, author/reviewer task
or role strings, change records, operation/transaction identities,
materialization/receipt identities, publication identities, or enclosing
envelope identities. `removed` SHALL NOT be a current entry state.

#### Scenario: Unrelated global authority changes (`DTO-LOCAL-001`)

- **WHEN** all table-local entry bytes are unchanged but an unrelated table,
  proof bundle, generation, operation, or publication identity changes
- **THEN** this entry's canonical bytes and digest remain identical.

#### Scenario: Table-local evidence changes (`DTO-LOCAL-002`)

- **WHEN** the table contract, schema, transform, columns, dependencies, state,
  policy, claim, evidence, or revalidation trigger changes
- **THEN** the entry digest changes and an exact compatible change record is
  required.

#### Scenario: A forbidden global field is added (`DTO-LOCAL-003`–`DTO-LOCAL-006`)

- **WHEN** any global, audit-label, operation, receipt, materialization, or
  publication field is inserted into an entry or its digest preimage
- **THEN** strict parsing or mutation validation fails.

### Requirement: Source and independent proof SHALL be complete and replayable

The source bundle SHALL contain exact safe canonical bytes or typed projections
needed to replay structural discovery, star contracts, source identities,
authored entries, dependencies, prior envelopes/change history, verifier
implementation identity, and proof inputs. Each member SHALL bind normalized
path, media type, byte length, and SHA-256. Admission SHALL rerun the current
independent verifier and require the full reconstructed output to equal the
proof pack and envelope.

Author/reviewer task and role strings SHALL be retained only as audit metadata.
String inequality SHALL NOT establish independence or admission.
The expected current decisions SHALL come from the independently compiled
repository-owned authored-decision corpus. Production SHALL expose no caller
DTO, root, boolean, or alternate-authority injection path.

The main corpus and deterministic table-local evidence projections SHALL be
embedded as replay evidence. Current verification SHALL exact-compare them to a
fresh fixed-resource load; historical verification SHALL replay the immutable
source embedded in that historical envelope. Evidence references SHALL bind
table-local projection digests rather than a self-referential whole-corpus root.

#### Scenario: Authored evidence is not current authored authority (`EVD-009`)

- **WHEN** an embedded authored corpus or evidence projection differs from the
  fresh fixed repository resource, its per-table structural pin is stale, or a
  caller attempts to replace the loader/compiler
- **THEN** current verification fails before an entry or proof result is
  admitted.

#### Scenario: Complete proof replay succeeds (`EVD-001`, `PRF-001`)

- **WHEN** all exact members replay and the current verifier independently
  reconstructs every supported per-entry decision and validation class
- **THEN** the proof root may enter envelope reconstruction.

#### Scenario: Source member is unsafe or incomplete (`EVD-002`–`EVD-008`)

- **WHEN** a member is missing, extra, unsafe, duplicate-normalized, symlinked,
  nonregular, length/digest mismatched, or only references mutable checkout
  state
- **THEN** replay fails before proof admission.

#### Scenario: Independence is spoofed (`PRF-002`–`PRF-010`)

- **WHEN** proof/results are swapped, task or role strings are changed,
  verifier implementation bytes differ, a precomputed result is substituted,
  producer/reviewer fixtures share a common-mode assumption, acceptance is
  blanket/name-only/SQL-only, or evidence/implementation is waived
- **THEN** fresh verifier reconstruction fails
- **AND** no capability, receipt, or accepted decision is emitted.

#### Scenario: Candidate decisions are coherently resealed (`PRF-011`)

- **WHEN** a protected decision field is changed and the candidate source
  projection, proof pack, verifier-result projection, and every enclosing
  envelope root are coherently recomputed while the repository-owned authored
  corpus remains unchanged
- **THEN** exact authored-authority comparison fails
- **AND** no production caller seam can substitute the mutated expectation.

### Requirement: Current states SHALL map to one exact authored policy

Every current entry SHALL use exactly one state and the complete policy below:

| State | Execute | Primary materialize | Stable load | Active transform publication component | Chat ceiling |
| --- | ---: | ---: | ---: | ---: | ---: |
| `active` | yes | yes | yes | yes | yes |
| `observed_only_experimental` | yes | yes | no | no | no |
| `contract_not_modeled` | no | no | no | no | no |

The compiler SHALL verify the authored policy and SHALL NOT fill it. V1 SHALL
provide no experimental export path.

#### Scenario: Exact policy is admitted (`ENT-001`, `CAP-001`–`CAP-006`)

- **WHEN** an authored current entry contains the exact policy for its state
- **THEN** the verifier derives its executable, stable-load, transform-
  publication, and chat-ceiling membership without inference.

#### Scenario: State or policy is incomplete (`ENT-002`–`ENT-010`)

- **WHEN** a state is unknown, `removed` appears as current, a policy field is
  absent/extra, or any capability differs from the table above
- **THEN** proof and runtime admission fail.

### Requirement: Evolution and tombstones SHALL be exhaustive and immutable

Every noninitial generation SHALL encode every actual difference exactly once
as `structural_addition`, `state_transition`, `contract_rebind`, or `removal`.
Change rows SHALL reference table-local old/new entry digests externally. A
removal SHALL create an immutable `TransformOutputRemovedTombstoneV1`; a rename
SHALL be removal plus addition. A tombstoned normalized name SHALL never return
to current discovery in V1.

#### Scenario: Exact generation diff succeeds (`GEN-001`, `CHG-001`–`CHG-004`)

- **WHEN** every current/prior difference maps one-to-one to the compatible
  change kind and all required authored/proof evidence exists
- **THEN** the new generation root is derived without changing unchanged entry
  digests.

#### Scenario: Change classification is invalid (`GEN-002`–`GEN-008`, `CHG-005`–`CHG-010`)

- **WHEN** a change row is missing, extra, duplicate, ambiguous, overlapping,
  incompatible, or embeds generation identity into a table-local entry
- **THEN** generation compilation fails.

#### Scenario: Tombstone is mutated or reused (`TMB-001`–`TMB-007`)

- **WHEN** a tombstone is deleted, altered, reversed, renamed, or its name
  reappears as a current output
- **THEN** V1 authority construction fails permanently for that generation.

### Requirement: Dependencies SHALL be exact before execution

Every transformer dependency SHALL resolve to one exact transform output or
one exact registered staging/input contract. The graph SHALL reject unknown,
missing, ambiguous, duplicate, self, non-executable, and cyclic edges.
`active` SHALL depend only on `active`; experimental SHALL depend only on
active or experimental. The verifier SHALL derive deterministic graph and
topological-order roots.

#### Scenario: Complete graph is valid (`DEP-001`–`DEP-006`)

- **WHEN** every edge has one valid authority and all capability rules hold
- **THEN** one deterministic executable order/root is committed.

#### Scenario: Current sorter would omit an edge (`DEP-007`–`DEP-012`)

- **WHEN** a dependency is absent from the registered transform graph or fails
  any identity, capability, or cycle rule
- **THEN** the whole governed operation fails before materialization
- **AND** no dependent set is silently shrunk.

### Requirement: Materialization receipts SHALL remain immutable local evidence

`TransformOutputMaterializationReceiptV1` SHALL bind one original
materialization identity and its exact
`transaction.generation_identity_sha256`, output name, exact table-local
entry/policy/contract/schema/transform/columns/dependencies,
primary-working-DuckDB scope, and the unchanged `TransformOutputAttestation`
table name, ordered schema digest, row count, and duplicate-preserving
row-multiset content digest.

A receipt SHALL be issued only for a real rebuild or local materialized
schema/content drift. It SHALL NOT be reissued, relabelled, or invalidated only
because an unrelated envelope, proof, source bundle, generation, operation, or
publication identity changes.

#### Scenario: Original materialization is attested (`REC-001`–`REC-008`)

- **WHEN** a transaction freshly attests one candidate relation and all local
  identities match
- **THEN** one immutable receipt is persisted and exact-read back.

#### Scenario: Global authority changes only (`REC-009`, `REC-010`)

- **WHEN** local entry/policy/dependencies and physical attestation are
  unchanged in a later operation
- **THEN** the original receipt remains byte-identical
- **AND** no new receipt is issued solely for the new global generation.

#### Scenario: Local or physical identity changes (`REC-011`–`REC-016`)

- **WHEN** any local root or fresh physical attestation differs
- **THEN** receipt reuse fails and an actual rebuild plus newly justified
  receipt is required.

### Requirement: Generation bindings SHALL authorize receipt use per operation

Every executable table in an operation SHALL have one
`TransformOutputGenerationBindingV1` binding the operation/transaction,
exact current `transaction.generation_identity_sha256`, current envelope and
entry/policy/dependency roots, immutable receipt identity, fresh physical-
attestation replay, exact canonical relation identity, and verifier-derived
reuse/rebuild classification.

`TransformOutputOperationCommitmentV1` SHALL contain the complete exact sorted
binding set/root, structural/executable/active/non-executable/tombstone sets,
dependency order, table-local roots, and derived operation roots.

#### Scenario: An old receipt is legitimately reused (`GEN-009`, `GEN-010`)

- **WHEN** current entry, policy, contract, and dependencies are byte-identical
  and fresh canonical attestation equals the old receipt
- **THEN** the new operation records a new binding to the unchanged receipt.

#### Scenario: A receipt is treated as operation authority (`GEN-011`, `GEN-012`)

- **WHEN** a consumer omits the current binding/commitment or carries a receipt
  into a mismatched operation
- **THEN** the operation fails; a receipt alone grants no execution,
  publication, or reuse authority.

### Requirement: Internal persistence SHALL use exactly three strict tables

`core/db.py` SHALL create exactly
`_transform_output_disposition_authority`,
`_transform_output_materialization_receipts`, and
`_transform_output_operation_commitments`. The last SHALL persist canonical
operation commitments containing complete generation bindings. The authority
table SHALL encode one global non-branching chain without a DuckDB
self-referencing foreign key; predecessor existence, immediacy, no gaps, and
no cycles SHALL be proved by semantic replay. The commitment table SHALL bind
its projected embedded-envelope and disposition-generation pair to the unique
authority pair. Every projected identity, byte length, and byte digest SHALL
be rederived from canonical bytes during semantic replay.

Runtime initialization SHALL validate but never auto-install. Explicit
migration SHALL install only when all three names are absent, return
already-current when all three exact schemas exist whether empty or populated,
and fail repair-required for partial, wrong, view-conflicted, temporary-
shadowed, or otherwise conflicting state. The installer SHALL create,
normalized-introspect, and empty-readback all three in one owned transaction.
It SHALL NOT bind unstable catalog presentation such as OIDs, generated
constraint names, raw DDL, or engine-formatted constraint text.

#### Scenario: All tables are absent (`DB-001`, `DB-002`)

- **WHEN** none of the three tables exists and all expected DDL shapes validate
- **THEN** they are created and exact-empty-read back atomically.

#### Scenario: Current exact tables are reopened (`DB-003`)

- **WHEN** all three exact table schemas already exist, empty or populated
- **THEN** runtime validation and explicit migration report already-current
- **AND** neither path rewrites, empties, or recreates them.

#### Scenario: State is partial or incompatible (`DB-004`–`DB-010`)

- **WHEN** one or two tables exist, or any table has a legacy, extra, missing,
  reordered, wrong-type, wrong-constraint, wrong-version, conflicting, or
  nonempty pre-cutover shape
- **THEN** migration rolls back and reports explicit repair required
- **AND** no compatibility upgrade, row coercion, or synthetic receipt occurs.

#### Scenario: Installer transaction ownership is fail-closed (`DB-009`, `DB-010`)

- **WHEN** a caller transaction is already active, a pre-commit boundary
  fails, or the commit call raises
- **THEN** the installer never rolls back a caller-owned transaction
- **AND** it rolls back only its own known-active pre-commit transaction
- **AND** a commit-call exception poisons the original connection and uses a
  fresh file-backed connection to classify complete absence, complete exact
  installation, or repair-required mixed state.

### Requirement: Canonical relation admission SHALL be one transaction

One verifier-owned DuckDB transaction SHALL reverify authority, build hidden
candidate relations, freshly attest them, validate/reuse or persist and
readback immutable receipts, atomically swap the complete canonical set,
reattest canonical relations, replay the exact Raw/W2/conditional evidence from
the same transaction snapshot, derive non-admitting `OperationDataEvidenceV1`,
close all generation bindings, persist/readback the operation commitment
containing those bindings and the evidence root, and commit. Only a fresh
post-commit exact readback of that directed evidence-to-commitment pair SHALL
seal the final verified operation-data wrappers. Canonical relations and their
complete commitment SHALL become visible together without a digest cycle or a
fourth internal table.

#### Scenario: Complete transaction commits (`TX-001`, `TX-002`)

- **WHEN** every candidate, attestation, receipt, swap, canonical reattestation,
  same-snapshot Raw/W2/conditional replay, binding, commitment, and readback is
  exact
- **THEN** the new canonical generation and commitment become visible in one
  commit.

#### Scenario: A pre-commit boundary fails (`TX-003`–`TX-019`)

- **WHEN** an injected fault occurs before/after candidate creation,
  attestation, receipt insert/readback, any swap, canonical reattestation,
  binding closure, commitment insert/readback, or immediately before commit
- **THEN** all new visibility and persistence roll back
- **AND** recovery observes no mixed or partially authoritative generation.

#### Scenario: The commit outcome is uncertain (`TX-020`)

- **WHEN** the commit call raises after the verifier has attempted commit
- **THEN** the original connection is poisoned and never reused
- **AND** a fresh file-backed connection proves either the complete old state
  or the complete new canonical generation plus commitment
- **AND** every mixed or partial state fails repair-required rather than being
  reported as rolled back or committed.

### Requirement: Operation data authority SHALL prove the cumulative provider denominator

`OperationDataEvidenceV1` SHALL bind one
`VerifiedOperationRawSnapshotV1`, the independently replayed detailed final W2
database authority and its `W2DatabaseAuthorityReceiptV1`, and one typed
cumulative conditional evidence inventory to the exact operation, source,
chain, transaction generation, and DuckDB snapshot. Its root SHALL be persisted
inside `TransformOutputOperationCommitmentV1` by the same verifier-owned
transaction. The evidence SHALL NOT embed the commitment. After successful
commit, exact readback SHALL seal
`VerifiedOperationConditionalStagingAuthorityV1` and
`VerifiedOperationDataAuthorityV1` from both the evidence and commitment roots.
Callers SHALL NOT mix authorities from different snapshots or operations.

The Raw verifier SHALL stream the canonical manifest journal, strict-parse each
stored manifest, rederive every stored projection, verify exact generation and
parent chains, replay operation rows and persistence receipts against Raw V2
exact-four and the bundle journal, and derive an HMAC-free
`DurableRawTerminalManifestLocatorV1` for every exact terminal group. It SHALL
reject every missing, extra, duplicate, foreign, partial, unreceipted, or
unaccounted group. Native codec limits and the exact typed denominator SHALL be
the bounds; no uncharacterized aggregate cap or truncation is permitted.
History-dependent inventories SHALL NOT be serialized as member arrays or
authority-bearing chunk lists. They SHALL be compact count plus
domain-separated ordered streaming-root commitments rederived from exact
strict-replayed rows inside the verifier-owned transaction. The framing SHALL
bind a versioned-domain empty state and SHALL fold each one-based ordinal,
prior raw 32-byte root, and next raw 32-byte leaf into a new SHA-256 root so
omission, extra members, substitution, reorder, and duplicate multiplicity all
change the root. The paired exact count SHALL equal the final ordinal. Canonical
envelope collection limits SHALL NOT become extraction history limits.

#### Scenario: Full extraction denominator is exact (`OPA-001`–`OPA-004`)

- **WHEN** a full extraction reaches terminal assurance
- **THEN** it contains exactly one Raw member for every complete executable
  matrix lane, exactly one discovery-seed Raw member, and exactly one
  live-snapshot Raw member
- **AND** complete executable plus canonically contract-blocked lane identities
  equal the normalized manifest-lane denominator
- **AND** blocked members contain no Raw locator and auxiliary discovery/live
  members are not counted as matrix lanes.

#### Scenario: Successor composes prior authority and one delta (`OPA-005`, `OPA-006`)

- **WHEN** one successor plan contains one or more exact dispatches
- **THEN** its cumulative Raw snapshot is the exact prior assured snapshot plus
  exactly one terminal delta manifest whose call inventory equals every unique
  dispatch and whose route inventory equals the union of requested scopes
- **AND** the verifier requires the ordered fold state at the exact prior-count
  boundary to equal the prior commitment, requires the delta as the sole suffix
  member, and recomputes the current count/root from the whole stream
- **AND** a baseline without prior Raw, W2, and conditional roots requires a
  full assured rebuild rather than physical inference.

#### Scenario: Discovery and live are durable data-producing members (`OPA-007`–`OPA-010`)

- **WHEN** discovery-owned provider bytes or post-merge live bytes affect the
  published dataset
- **THEN** discovery publishes a content-addressed Raw authority database that
  is installed into the checkpoint and live capture persists its terminal Raw
  authority before the transform transaction
- **AND** every live-derived transform output is rebuilt from that fresh live
  staging generation
- **AND** publication-grade export begins only after committed operation-data
  wrapper readback; every pre-commit staging export remains unpromoted scratch
- **AND** missing either exact auxiliary member blocks final assurance.

#### Scenario: W2 and conditional authority are cumulative (`OPA-011`–`OPA-014`)

- **WHEN** the final same-snapshot database authority is replayed
- **THEN** the prior successor or checkpoint W2 multiset is an exact subset of
  final W2 and every addition is attributable to an exact typed data-producing
  member
- **AND** conditional membership is derived only from cumulative exact typed
  stats/live route admissions, authority roots, landings, and receipts
- **AND** every conditional leaf binds a compatible typed Raw source member,
  and Raw, W2, and conditional successor evidence bind one identical prior
  operation-data evidence root
- **AND** a prior conditional table cannot disappear merely because the current
  delta has no new conditional landing.

#### Scenario: A cumulative inventory exceeds canonical array limits

- **WHEN** an exact Raw, route, W2, attribution, or conditional inventory has
  more than 20,000 members
- **THEN** the verifier streams every member into the versioned ordered
  count/root commitment without materializing a durable member array
- **AND** no member is truncated, sampled, moved into an unreceipted chunk
  authority, or omitted from the same-snapshot closure.

#### Scenario: Control canaries remain outside dataset authority (`OPA-015`–`OPA-018`)

- **WHEN** VPN preflight, capacity admission, or installed-stack canaries call
  an endpoint that is also used by a data-producing adapter
- **THEN** the owning typed adapter, not an endpoint name or caller flag,
  classifies the control call as contributing zero Raw dataset members
- **AND** its response bytes cannot be reused as dataset input without becoming
  an exact data-producing member.

### Requirement: A neutral operation-bound resource contract SHALL precede the final union

Publication identity SHALL be compiled in three ordered phases.

First, `StablePublicationTableUnionV1` SHALL contain the normalized
pairwise-disjoint table-only union of Raw V2 exact-four, W2 exact-six, all
mandatory unique `STAGING_MAP` tables, exact cumulative conditional staging
tables, and verified active transform outputs. Raw, W2, and conditional
membership SHALL come only from the same-snapshot
`VerifiedOperationDataAuthorityV1`. It SHALL bind the operation commitment,
every component authority/count/root, exact ordered table tuple, table count,
and content-only table-union root. It SHALL contain no expected resource path
derived from a physical data directory.

Second, a Kaggle-neutral compiler outside `nbadb.kaggle` SHALL consume only the
exact operation commitment, `StablePublicationTableUnionV1`, and canonical
`PublicationResourcePathPolicyV1`. It SHALL produce immutable
`OperationPublicationResourceContractV1` binding the operation, table-union,
path-policy schema/version/root, ordered typed resource entries, exact resource
count, content-only resource-inventory root, and complete contract root. Each
entry SHALL bind its normalized identifier, exact file-or-directory kind,
semantic role, and source table when applicable. The contract SHALL contain
the exact four fixed file resources and exactly one CSV plus one Parquet
resource for every table. Parquet directory-versus-file identity SHALL be
selected only by the canonical path policy.

Third, `StablePublicationUnionV1` SHALL be sealed only from a matching table
union and resource contract. It SHALL reject any operation, component,
table-root, path-policy-root, resource-count, resource-root, or contract-root
mismatch.

Expected membership, identifier, and kind SHALL NOT depend on module globals,
transformer or schema discovery, import order, a physical DuckDB catalog, a
filesystem tree, symlink state, file existence, caller-supplied conditional
booleans, or an observed remote inventory. Physical observation SHALL be a
separate verifier input that can attest existence, regular-file/directory
shape, symlink policy, content, completeness, and absence of extras but cannot
change expected identity.

#### Scenario: Filesystem state cannot change expected identity (`RES-001`)

- **WHEN** identical operation, table-union, and path-policy inputs are compiled
  before and after files are added, removed, replaced, symlinked, or changed
  between file and directory form
- **THEN** the expected entries, count, and content-only resource root remain
  byte-identical
- **AND** the separate physical verifier reports the observed mismatch.

#### Scenario: Typed conditional admission is exclusive (`RES-002`)

- **WHEN** a conditional staging path exists physically but its typed component
  did not admit that table in the cumulative operation authority
- **THEN** the table and its resources are absent from the expected contract
- **AND** the physical path is rejected as unexpected.

#### Scenario: Cross-operation reuse is rejected (`RES-003`)

- **WHEN** byte-identical table/resource inventories are paired with a resource
  contract bound to another operation commitment
- **THEN** final-union construction fails before export, assurance, metadata,
  or publication.

#### Scenario: Partition policy drift is fail-closed (`RES-004`)

- **WHEN** a table's partitioned-versus-single-file policy changes without a
  matching path-policy root and newly compiled resource contract
- **THEN** the stale resource contract is rejected.

#### Scenario: Every consumer uses one resource authority (`RES-005`)

- **WHEN** metadata, successor inventory, successor assurance, upload
  validation, readback, reconciliation, export, or scanning consumes resources
- **THEN** expected identifiers, kinds, roles, counts, and roots come from the
  exact operation-bound resource contract
- **AND** static and runtime gates reject every parallel derivation.

### Requirement: Stable publication SHALL be an exact five-component union

`StablePublicationUnionV1` SHALL contain the normalized pairwise-disjoint union
of: Raw V2 exact-four; W2 exact-six; all mandatory unique `STAGING_MAP` tables;
exact cumulative typed-admitted conditional staging tables; and verified active
transform outputs. Transform disposition SHALL govern only the fifth component.
The first, second, and fourth components SHALL share the exact
`VerifiedOperationDataAuthorityV1` operation/snapshot roots.

Each component SHALL bind its authority, sorted normalized names, count, and
table-root in `StablePublicationTableUnionV1`, then its typed resource
projection/count/root in the matching
`OperationPublicationResourceContractV1`. The final union SHALL bind both DTOs,
all component roots, and exact union table/resource inventories/counts/roots.
No fixed historical count SHALL be used as authority.

#### Scenario: Runtime components form an exact union (`PUB-001`–`PUB-004`)

- **WHEN** all five typed components are exact and pairwise disjoint
- **THEN** the table union, neutral resource contract, and final union are
  deterministically derived and mutually bound.

#### Scenario: Current structural observations are checked (`PUB-005`)

- **WHEN** a validation-only derivation uses `A=261`, the current structural
  transform-count observation, and evaluates `C=0` and `C=2` typed conditional
  staging cases
- **THEN** a validation fixture may observe 709 tables/1,422 resources with no
  admitted conditional staging and 711/1,426 with both
- **AND** those numbers are asserted only as current drift-sensitive evidence,
  never supplied to runtime as expected constants or treated as disposition
  evidence.

#### Scenario: A component is omitted, substituted, overlapped, or widened (`PUB-006`–`PUB-014`)

- **WHEN** any component/root is absent or replaced, normalized names overlap,
  a conditional table lacks typed admission, active transforms differ, resource
  derivation differs, or physical discovery contributes an extra table
- **THEN** union construction fails before export or publication evidence is
  frozen.

### Requirement: Export and scanning SHALL consume the publication union

Export SHALL require `StablePublicationUnionV1`, the operation commitment,
exact bindings/receipts, component authorities, and a physical attestation of
the exact resource contract. It SHALL create DuckDB, SQLite, Parquet, and CSV
artifacts from the union and SHALL NOT use physical `get_user_tables` as
denominator authority. Scanner/schema validation SHALL preserve the full
structural transform census while separately validating executable primary
scope, active transform scope, all nontransform publication components, exact
union resources, and physical no-widening.

#### Scenario: Extra physical tables exist (`PUB-015`, `CUT-001`)

- **WHEN** the working DuckDB contains experimental, internal, or unrelated
  physical tables outside the exact union
- **THEN** they are reported as drift where applicable and never exported.

#### Scenario: A required member or receipt is absent (`PUB-016`, `CUT-002`)

- **WHEN** a union member, schema, binding, receipt, or resource differs
- **THEN** all-format export and full-publication scan fail before freezing an
  authoritative artifact inventory.

### Requirement: Publication layers SHALL propagate identical roots

The terminal successor report, assured artifact manifest, operation-bound
metadata, publication-ledger intent, publication rights, publication marker,
exact remote readback, reconciliation, and success record SHALL each bind all
five component authority/count/table/resource roots, table-union,
path-policy, resource-inventory, resource-contract, and final-union
counts/roots, exact public DuckDB SHA-256, disposition/active-transform roots,
operation commitment, generation-binding and receipt roots, cumulative Raw
snapshot, W2 database, conditional-staging roots, operation-data evidence/final
authority roots, and each layer's existing chain/source/coverage/artifact
identities.

#### Scenario: Every layer agrees (`PUB-017`, `PUB-018`)

- **WHEN** each downstream layer reconstructs or exact-compares the same typed
  identities
- **THEN** local publication preparation may advance to its next separately
  authorized boundary.

#### Scenario: Cross-layer identity differs (`PUB-019`–`PUB-026`)

- **WHEN** any component, union, DuckDB, disposition, operation, binding,
  receipt, manifest, report, ledger, rights, marker, or readback identity is
  omitted, substituted, stale, or mixed across operations
- **THEN** mutation, reconciliation, or success resolution fails closed.

#### Scenario: A local receipt is valid but bundle changes (`PUB-027`)

- **WHEN** an immutable table receipt remains valid but the operation, union,
  public DuckDB, or resource tree changes
- **THEN** fresh binding and exact bundle/publication evidence are still
  required.

### Requirement: Metadata SHALL be operation-bound

Kaggle metadata and publication inventory SHALL take the exact operation,
table-union, resource-contract, and final-union DTOs as mandatory inputs. They
SHALL NOT derive table categories, stable membership, expected resource paths,
or resource kinds from module globals, transformer registries, schema
registries, import order, caller-supplied conditional booleans, or physical
relations. Successor inventory, successor assurance, and the Kaggle client
SHALL consume the same resource DTO and typed role projections without manual
conditional reconstruction, path-based control stripping, or a legacy
derivation path.

#### Scenario: Two operations are generated in either order (`PUB-028`, `PUB-029`)

- **WHEN** two operations have different active/conditional components or roots
- **THEN** each metadata result binds only its supplied operation and union
- **AND** reversing import or execution order does not mix authority.

### Requirement: Documentation and chat SHALL preserve separate authorities

Structural documentation SHALL retain the full current transform census and
label each output with disposition/table-local authority. Removed names SHALL
appear only as tombstones. Stable publication docs SHALL use the exact union.

The current curated chat route catalog's 26 required tables SHALL be handled as
25 transform outputs plus `_pipeline_metadata`. Each transform dependency SHALL
be current `active` with exact receipt/binding rechecked at catalog admission
and immediately before SQL. `_pipeline_metadata` SHALL use a separate explicit
internal-route authority and availability check. Active status SHALL NOT create
a route, alias, or SQL template.

#### Scenario: Active output has no route (`CUT-003`)

- **WHEN** an active output is absent from the curated catalog
- **THEN** no chat capability is generated for it.

#### Scenario: Route dependencies are stale (`CUT-004`, `CUT-005`)

- **WHEN** any of the 25 transform dependencies is nonactive/stale or the
  internal table lacks its separate authority
- **THEN** catalog admission or pre-query recheck fails before SQL.

#### Scenario: Active filter sees the internal table (`CUT-006`)

- **WHEN** generic transform filtering processes the route requirement set
- **THEN** `_pipeline_metadata` is neither dropped nor treated as a transform
- **AND** the explicit internal-route authority remains mandatory.

### Requirement: Every governed consumer SHALL cut over without fallback

Pipeline, orchestrator, loader factory/loaders, export CLI/helpers, schema
registries, scanner, artifact identity, successor assurance/runtime/
coordinator/inventory, Kaggle metadata/client/ledger/rights, docs, chat, and
agent context SHALL require the corrected typed authorities. Signatures and
call sites SHALL contain no `Optional`, `None`/default, feature flag,
compatibility/dual-read branch, module-global authority, transformer/schema
registry reconstruction, or physical-table denominator fallback.

AST and runtime tests SHALL reject component omission/substitution/overlap,
physical widening, and every unclassified constructor or consumer. Acceptance
SHALL require `N inventoried = N migrated = N tested`.

#### Scenario: Static and runtime cutover is complete (`CUT-007`–`CUT-014`)

- **WHEN** the consumer inventory and AST/import/call-site/runtime gates execute
- **THEN** every governed path has one mandatory typed source and exact tests.

#### Scenario: A fallback or new consumer appears (`CUT-015`–`CUT-022`)

- **WHEN** any forbidden signature, reconstruction, physical widening,
  component substitution, or unclassified consumer is introduced
- **THEN** the cutover gate fails.

### Requirement: Local evidence SHALL remain explicitly red at external gates

Implementation, local validation, and independent technical review SHALL NOT
claim live extraction completeness, model/data green, publication completion,
remote inventory/hash verification, qualified human review, or external SQL/
filesystem access control. Live extraction, Kaggle mutation, exact positive
version/readback, and manual verification SHALL remain separately authorized
and evidenced.

#### Scenario: Repository tests pass (`CUT-023`)

- **WHEN** every local acceptance command succeeds
- **THEN** only the repository-controlled authority/cutover implementation is
  locally evidenced
- **AND** all external and live gates remain red until separately executed.

#### Scenario: Direct external access occurs (`CUT-024`)

- **WHEN** a user directly reads a working database or filesystem artifact
- **THEN** this capability makes no access-control claim
- **AND** repository-owned export, chat, assurance, and publication policies
  remain independently enforced.
