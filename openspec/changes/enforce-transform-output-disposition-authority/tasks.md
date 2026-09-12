## A. Freeze Exact Authorities and Consumer Inventory

- [ ] A.1 Derive
  `tuple(sorted(expected_transform_output_tables(include_live=True)))` and
  independently compile `star_table_contract.compile_star_table_contracts()`;
  require exact equality to `tuple(table.output_name for table in
  inventory.tables)`, bind `StarModelContractInventory.contract_sha256` and
  ordered per-table roots, and record 261 only as the current first-generation
  observation (`DEN-001`–`DEN-006`).
- [ ] A.2 Add missing/extra/duplicate/reordered/foreign/name-normalization and
  per-table-root mutation cases; prove neither structural source accepts a
  disposition filter and future counts are derived (depends: A.1).
- [ ] A.3 Freeze exact source bytes/typed projections needed to replay
  discovery, schemas, transforms, columns, dependencies, star contracts, prior
  history, verifier implementation, and proof inputs. Separately freeze the
  checked-in canonical authored-decision corpus and its repository-owned
  compiler; the expected decisions may not be projected from the candidate
  envelope or proof. Freeze each reviewed per-table structural-authority pin and
  deterministic table-local evidence projection (`EVD-001`–`EVD-009`; parallel:
  A.2).
- [ ] A.4 Freeze a machine-readable owner/symbol inventory for every
  transform-output/publication-set constructor and consumer: pipeline,
  orchestrator, `create_multi_loader`/loaders, export CLI/helpers, schema
  registries, scanner, artifact identity, successor assurance/runtime/
  coordinator/inventory, Kaggle metadata/client/ledger/rights, docs generators,
  chat catalog/runtime/SQL, and agent context. Record current source,
  replacement DTO, test owner, and dependency lane.
- [ ] A.5 Derive the current five publication component inventories and
  existing resource projection independently. Record 709/1,422 base and
  711/1,426 with both typed conditionals only as drift-sensitive observations;
  never promote either pair into runtime constants (`PUB-001`–`PUB-005`).

## B. Implement Canonical Entry, Envelope, and Replay Models

- [ ] B.1 Define strict `CurrentTransformOutputDispositionV1` with only
  table-local fields and the three current states; add an explicit digest-
  preimage allowlist excluding every global/generation/proof/source-bundle/
  audit-label/change/operation/receipt/materialization/publication/envelope
  identity (`DTO-LOCAL-001`–`DTO-LOCAL-006`).
- [ ] B.2 Define immutable `TransformOutputRemovedTombstoneV1`, typed capability
  policy, exact change records, dependency authority, source bundle, proof pack,
  and `VerifiedTransformOutputDispositionAuthorityEnvelopeV1`
  (`ENV-001`–`ENV-008`, `ENT-001`–`ENT-010`; parallel: B.1).
- [ ] B.3 Implement bounded strict canonical encoding/parsing: UTF-8, sorted
  keys, no duplicate/unknown keys or nonfinite values, bounded size/depth/nodes/
  collections/strings, deterministic digests, and one LF for persisted bytes
  (`DET-001`–`DET-005`; depends: B.1-B.2).
- [ ] B.4 Implement `from_canonical_bytes` so it fresh-runs both structural
  authorities, reconstructs the current `StarModelContractInventory`, replays
  exact bundle/history, reconstructs entries/tombstones/capabilities/
  dependencies, independently compiles the repository-owned authored decision
  authority, reruns the current verifier, exact-compares authored authority/
  result/proof/envelope, and only then constructs the DTO (depends:
  A.1-A.3,B.1-B.3).
- [ ] B.5 Reject public constructors/overloads accepting parsed DTOs,
  caller-provided authority/proof/result objects, roots/counts, or verified
  booleans; retain author/reviewer task and role only as audit metadata.

## C. Author and Independently Verify the Runtime Barrier

- [ ] C.1 Author exactly one explicit table-local current decision for every
  exact current structural output; no default, placeholder, inferred blocker,
  name-only/SQL-only decision, or current `removed` row. Persist it in the
  canonical repository corpus consumed independently from the candidate
  envelope/proof; every row must carry its reviewed structural-table-authority
  pin and referenced table-local evidence projections (depends: A-B; runtime
  remains red until complete).
- [ ] C.2 Produce a complete typed proof pack with positive, negative, and
  mutation evidence from an independent work lane; task/role labels are audit
  metadata and do not establish admission (`PRF-001`–`PRF-011`; depends: C.1).
- [ ] C.3 Rerun the current verifier from frozen source/proof inputs and add
  proof-swap, result-substitution, task/role-spoof, verifier-mutation,
  common-mode, blanket-acceptance, and waiver adversaries. Add a protected
  decision-field mutation that coherently reseals the candidate source
  projection, proof pack, verifier-result projection, and envelope roots but
  leaves the independent repository corpus unchanged; it must fail. Expose no
  production caller seam for a path, source, compiler, or alternate authored
  authority. Fictional tests use only a private pure verification kernel
  (`EVD-009`, `PRF-011`; depends: C.2).
- [ ] C.4 Require two clean fresh envelope builds to be byte-identical and
  persist the authored artifact, bundle, proof, and envelope only after exact
  replay succeeds (depends: C.3; barrier for D-K).

## D. Compile Evolution, Capability, and Dependency Authorities

- [ ] D.1 Implement exact initial/prior/current comparison and exhaustive
  `structural_addition`, `state_transition`, `contract_rebind`, and `removal`
  rows that reference entry digests externally (`GEN-001`–`GEN-008`,
  `CHG-001`–`CHG-010`). Explicitly cover semantic-claim, reason/evidence,
  trigger, policy, dependency, and structural-contract-only rebinds so the
  implementation matches the complete authored table-local digest.
- [ ] D.1a Accept same-state semantic-only or structural-only local drift as
  `contract_rebind`; accept state/policy-only drift as `state_transition`; and
  reject combined state plus other local drift as ambiguous until authored in
  separate generations. Require explicit authored removal evidence before a
  tombstone is created (depends: D.1).
- [ ] D.2 Keep additions red until their exact entry/proof exists; verify the
  compiler cannot manufacture a blocker, policy, capability, state, evidence,
  or proof (depends: D.1).
- [ ] D.3 Enforce immutable tombstones, rename-as-removal-plus-addition, and
  permanent V1 name reservation (`TMB-001`–`TMB-007`; depends: D.1).
- [ ] D.4 Classify every dependency as one exact transform output or registered
  staging/input contract; reject unknown, missing, ambiguous, duplicate, self,
  non-executable, and cyclic edges (`DEP-001`–`DEP-012`).
- [ ] D.5 Enforce `active -> active` and experimental to active/experimental,
  and emit exact deterministic executable graph/order roots (depends: D.4).

## E. Split Immutable Receipts from Per-Operation Bindings

- [ ] E.1 Define immutable table-local
  `TransformOutputMaterializationReceiptV1` around the unchanged
  `successor_transform_authority.TransformOutputAttestation` schema/content
  evidence and the original materialization's exact
  `transaction.generation_identity_sha256` (`REC-001`–`REC-008`).
- [ ] E.2 Prove ordered DuckDB schema hashing and duplicate-preserving,
  row-order-independent content hashing; reject schema/content and local-root
  mutations (`REC-001`–`REC-016`; depends: E.1).
- [ ] E.3 Define per-operation `TransformOutputGenerationBindingV1` binding
  current `transaction.generation_identity_sha256`, entry/policy/dependencies,
  immutable receipt, fresh physical attestation replay, canonical relation, and
  verifier-derived reuse/rebuild status (`GEN-009`–`GEN-012`).
- [ ] E.4 Define mandatory `TransformOutputOperationCommitmentV1` containing
  the complete exact binding set/root, structural/executable/active/
  non-executable/tombstone sets, dependency order, and table-local roots
  (depends: D.5,E.3).
- [ ] E.5 Permit receipt reuse only after byte-identical current local
  authority and equal fresh physical attestation; issue a new receipt only for
  an actual rebuild/local drift, never for unrelated global generation change
  (`REC-009`–`REC-016`; depends: E.1-E.4).

## F. Add Fail-Closed Persistence and Transactional Visibility

- [ ] F.1 Add exactly three internal tables in `core/db.py`:
  `_transform_output_disposition_authority`,
  `_transform_output_materialization_receipts`, and
  `_transform_output_operation_commitments`; commitments contain the complete
  generation-binding set (`DB-001`–`DB-010`). Encode one explicit global,
  non-branching authority chain without a DuckDB self-referencing foreign key;
  retain the exact composite commitment-to-authority foreign key and mark
  commitment envelope/byte columns as verified projections of canonical bytes.
- [ ] F.2 Implement all-absent-only transactional creation, exact DDL
  introspection, and empty readback through an explicit installer. Normalize
  persistent and temporary catalog observations instead of binding unstable
  OIDs/names/raw DDL text. Runtime init never auto-installs; explicit migrate
  classifies all absent, all-three-exact empty/populated, partial, wrong, and
  conflicting states. Track owned transaction state; roll back only a
  successfully begun transaction; poison/reopen/classify after a commit
  exception. Partial, reordered, extra, missing, wrong-type/constraint/version,
  legacy, or conflicting state is repair required; no upgrade/coercion/
  synthetic receipt.
- [ ] F.3 Implement one verifier-owned DuckDB transaction: verify authority;
  replay exact current-operation Raw, detailed W2, and typed cumulative
  conditional evidence from the transaction's own snapshot; derive one
  non-admitting `OperationDataEvidenceV1` and require its common operation/
  generation roots;
  build hidden candidates; fresh-attest; reuse or persist/readback immutable
  receipts; atomically swap the complete canonical set; reattest canonical;
  close bindings; persist/readback the commitment containing bindings and
  `operation_data_evidence_sha256`; commit. After commit, fresh-read the exact
  commitment/evidence pair to seal the final verified operation-data wrappers
  (`TX-001`–`TX-020`; depends: E,F.1-F.2,F.5-F.9).
- [ ] F.4 Fault-inject before/after candidate creation, attestation, receipt
  insert/readback, every swap, canonical reattestation, binding closure,
  commitment insert/readback, immediately before commit, and at commit. Prove
  owned pre-commit rollback leaves no mixed canonical or internal state; prove
  commit-uncertain poison/reopen recovery observes either the complete old or
  complete new state and rejects every mixed state (depends: F.3).
- [ ] F.5 Define strict historical codecs for
  `DurableRawTerminalManifestLocatorV1`, `VerifiedOperationRawSnapshotV1`,
  `FullExtractionRawOperationDenominatorV1`,
  `SuccessorRawOperationDenominatorV1`,
  `OperationDataEvidenceV1`,
  `VerifiedOperationConditionalStagingAuthorityV1`, and
  `VerifiedOperationDataAuthorityV1`. Represent every history-dependent Raw,
  route, W2, attribution, and conditional inventory as a domain-separated
  ordered streaming count/root commitment rather than a canonical member
  array or authoritative chunk list. Exclude compiler HMACs, capability
  tokens, physical table names, booleans, caller maps, untyped conditional
  sources, and cross-prior component pairing from durable authority; normalize
  bounded-codec resource failures and reject foreign subclasses
  (`OPA-001`–`OPA-004`).
- [ ] F.6 Implement streaming verifier-owned manifest-journal discovery and
  exact replay of canonical bytes, projections, generation chains, operation
  rows, persistence receipts, Raw exact-four, bundle journal, and durable
  locators. Recompute ordered count/root commitments directly from the owned
  snapshot, reject unreferenced bundle/exact-four rows, and for a successor
  prove the complete current stream equals the prior committed stream plus one
  exact delta by matching the prior commitment at its exact prefix boundary and
  requiring that exact delta as the sole suffix member.
  Derive bounds from native codecs and the exact denominator; add no
  uncharacterized aggregate ceiling, materialized history array, or truncation
  (depends: F.5).
- [ ] F.7 Integrate one Raw operation across the whole successor plan and bind
  its exact dispatch call inventory and requested-scope route union. Extend the
  baseline with mandatory prior cumulative Raw/W2/conditional roots; a legacy
  baseline requires full assured rebuild (`OPA-005`, `OPA-006`; depends: F.6).
- [ ] F.8 Add exactly one content-addressed discovery Raw authority database,
  install its journal/exact-four/bundle/W2 state into the checkpoint, and add
  exactly one typed discovery member. Inject Raw V2 into `live-snapshot`, emit
  exactly one typed live member, persist it to the final database, and move
  live capture before the F.3 transaction. Rebuild every live-derived transform
  from those fresh live staging bytes; no pre-live transform result is current
  (`OPA-007`–`OPA-010`; depends: F.6).
- [ ] F.9 Verify the full denominator as one Raw member per exact complete
  executable lane plus discovery plus live, with exact disjoint canonical
  blocked evidence; verify prior/checkpoint W2 as an exact multiset subset of
  final W2 with additions attributable only to typed members; derive cumulative
  conditional membership only from exact typed route admissions/landings/
  receipts. Prove typed control canaries contribute no dataset member and
  cannot be reused as data (`OPA-011`–`OPA-018`; depends: F.7-F.8).
- [ ] F.10 Add integrated acceptance proving F.3 consumes F.5-F.9 evidence as
  mandatory nonoptional same-snapshot input, persists only its noncyclic
  evidence root inside the transform commitment, and seals final wrappers only
  after committed exact readback. Add cross-snapshot, cross-operation, ABA,
  mutation, lock-order, digest-cycle, and fault boundaries. Prove pre-F.3
  staging exports are scratch-only and no publication resource is promoted when
  F.3 rolls back (depends: F.3-F.4,F.9).

## G. Cut Over Transform Execution and Stable Loading

- [ ] G.1 Make `TransformPipeline` require the verified executable graph/order
  and fail on missing/extra/non-executable transformers or unresolved
  dependencies instead of omitting them (`DEP-007`–`DEP-012`).
- [ ] G.2 Execute and primary-materialize exactly active plus experimental,
  including schema-valid empty outputs, through the transaction protocol; make
  `_transform_and_load` require exact binding/commitment closure.
- [ ] G.3 Make `create_multi_loader` and all loaders/callers require the exact
  active stable commitment and reject nonactive transform outputs.
- [ ] G.4 Remove every Optional/default/flag/compatibility/dual-read/global/
  registry/physical fallback from pipeline, orchestrator, and loader paths.

## H. Build and Consume the Full Stable Publication Union

- [ ] H.0 Add characterization tests freezing only the current correct resource
  semantics: the exact four fixed resources; one CSV and one Parquet resource
  per explicit table; partitioned-directory versus single-file Parquet kinds;
  and zero, one, and both typed conditional-table cases. Do not freeze
  import-global or physical-discovery behavior as authority.
- [ ] H.1 Implement table-only `StablePublicationTableUnionV1` from Raw V2
  exact-four, W2 exact-six, mandatory unique `STAGING_MAP`, cumulative
  `VerifiedOperationConditionalStagingAuthorityV1`, and verified active
  transforms. Consume the Raw/W2/conditional components only through the
  same-snapshot `VerifiedOperationDataAuthorityV1`. Bind the operation
  commitment, component authorities/counts/roots, exact normalized
  disjoint table tuple, count, and table-union root. Reject omission,
  substitution, overlap, physical widening, and conditional or
  active-transform mismatch (`PUB-001`–`PUB-014`; depends: F.10,H.0).
- [ ] H.2 Extract the fixed-resource plus per-table CSV/Parquet path-and-kind
  projection from `src/nbadb/kaggle/metadata.py` into one Kaggle-neutral
  compiler. Define canonical `PublicationResourcePathPolicyV1` and
  `OperationPublicationResourceContractV1`; bind operation, table union,
  policy, typed ordered entries/roles, count, resource-inventory root, and
  contract root. Keep physical observation and caller-supplied conditional
  booleans out of expected-contract compilation (`RES-001`–`RES-005`; depends:
  H.0-H.1).
- [ ] H.3 Seal `StablePublicationUnionV1` only from a matching table union and
  resource contract. Bind per-component and union table/resource roots and add
  operation/table/policy/resource mismatch plus deterministic canonical-replay
  tests. Assert current counts only in drift-sensitive fixtures (depends:
  H.1-H.2).
- [ ] H.4 Implement a separate physical-resource attestor that validates
  existence, regular-file/directory kind, symlink policy, completeness,
  content, and no extras against the immutable resource contract. Add missing,
  extra, file/directory swap, symlink, conditional-widening, and mutate/restore
  negatives proving observation cannot change expected identity (depends:
  H.2-H.3).
- [ ] H.5 At one cutover barrier, make Kaggle metadata,
  `successor_publication_inventory`, `successor_assurance`, and the Kaggle
  client consume the exact operation-bound resource DTO and typed role
  projections. Remove `TABLE_CATEGORIES` membership authority,
  physical/boolean expected-membership inference, manual conditional addition,
  path-based control stripping, duplicate resource traversal, and legacy
  monkeypatch seams. Test two differing operations in both import/execution
  orders; no dual read or compatibility path is permitted (`PUB-028`,
  `PUB-029`; depends: H.3-H.4).
- [ ] H.6 Replace export physical `get_user_tables` authority with the final
  union plus operation/binding/receipt and physical-attestation inputs for
  DuckDB, SQLite, Parquet, and CSV. Make schema validation and scanner retain
  full structural discovery while checking executable primary, active
  transform, nontransform components, exact union resources, and no physical
  widening; reject every absent or extra member (`PUB-015`, `PUB-016`; depends:
  F.10,H.3-H.5).

## I. Propagate Exact Publication Identities

- [ ] I.1 Extend the successor terminal report and assured artifact manifest
  with all component roots/counts plus table-union, path-policy,
  resource-inventory, resource-contract, and final-union roots/counts, exact
  public DuckDB, disposition/active-transform, operation, generation-binding,
  receipt, cumulative Raw snapshot, final W2 database, conditional staging,
  operation-data evidence, final verified operation-data, and existing chain/
  source/coverage/artifact identities.
- [ ] I.2 Propagate identical identities through operation-bound metadata,
  publication-ledger intent, publication rights, marker, exact remote readback,
  reconciliation, and success (`PUB-017`–`PUB-027`; depends: H,I.1).
- [ ] I.3 Add cross-layer mutations for every identity plus component
  omission/substitution/overlap/physical widening; prove a valid immutable
  receipt never substitutes for fresh binding or bundle/publication evidence.

## J. Cut Over Docs, Chat, Agent Context, and Every Remaining Consumer

- [ ] J.1 Feed verified disposition/table-local labels into structural docs
  while retaining the full census and separate tombstones; build stable
  publication docs from the exact union through canonical generators only.
- [ ] J.2 Preserve the curated chat route catalog. Classify its current 26
  required tables as 25 transform outputs plus `_pipeline_metadata`; apply
  active/receipt/binding checks only to transform dependencies and add separate
  explicit route authority/availability checks for the internal table
  (`CUT-003`–`CUT-006`).
- [ ] J.3 Recheck chat authority at catalog admission and immediately before
  SQL; prove active does not generate a route and agent context cannot use
  physical discovery.
- [ ] J.4 Implement AST/import/call-site/runtime inventory gates for every A.4
  consumer; reject optional/default inputs, flags, compatibility, dual reads,
  globals, registry reconstruction, component omission/substitution/overlap,
  physical widening, and unclassified consumers (`CUT-007`–`CUT-022`).
- [ ] J.5 Require exact `N inventoried = N migrated = N tested` before source
  acceptance.

## K. Validation and Acceptance

- [ ] K.1 Maintain a test-index artifact mapping every `ENV`, `DEN`, `DET`,
  `EVD`, `ENT`, `DTO-LOCAL`, `PRF`, `GEN`, `CHG`, `TMB`, `DEP`, `CAP`, `REC`,
  `DB`, `TX`, `OPA`, `PUB`, `RES`, and `CUT` ID to an executable assertion.
- [ ] K.2 Run strict OpenSpec validation:
  - `openspec validate enforce-transform-output-disposition-authority --type change --strict --no-interactive`
- [ ] K.3 Run focused new authority/proof/generation/receipt/binding/database/
  union/transaction tests with import isolation. Explicitly create and list any
  new test modules before implementation.
- [ ] K.4 Run existing pipeline/orchestrator/loader/export/scanner/assurance/
  artifact/publication/metadata/docs/chat packets. Export owners are the
  existing `tests/unit/cli/test_io_commands.py` and
  `tests/unit/cli/test_export_performance.py`; do not reference a nonexistent
  export test module.
- [ ] K.5 Run repository static, format, type, bytecode, SQL, and unit gates:
  - `uv run ruff check src/ tests/`
  - `uv run ruff format --check src/ tests/`
  - `uv run ty check src/`
  - `uv run python -m compileall -q src/nbadb tests/unit`
  - `uv run nbadb lint-sql`
  - `uv run pytest --no-cov --import-mode=importlib tests/unit`
- [ ] K.6 Regenerate generated docs only after implementation acceptance, then
  run docs format/lint/type/build and no-drift gates.
- [ ] K.7 Run independent read-only reviews for proof/replay, table-local versus
  operation evidence, transaction/database migration, full-publication union,
  and all-consumer cutover; resolve every finding and rerun owned IDs.
- [ ] K.8 Record exact source hashes, authorities, envelope/proof/bundle roots,
  derived counts, component/union roots, receipt/binding/operation roots,
  commands/exits, and unresolved external evidence gaps.

## L. Explicit External Red Gates

- [ ] L.1 Keep runtime blocked until the complete authored denominator,
  fresh current-verifier proof replay, and clean-break implementation barriers
  are satisfied.
- [ ] L.2 Treat later full extraction, historical coverage, and semantic model
  correctness as separate live evidence.
- [ ] L.3 Treat Kaggle mutation, exact positive version, complete streamed
  remote readback, reconciliation, and manual/human verification as separately
  authorized work.
- [ ] L.4 Do not claim `MODEL-GREEN`, `DATA-GREEN`, publication completion, or
  external SQL/filesystem access control from this OpenSpec or local tests.
