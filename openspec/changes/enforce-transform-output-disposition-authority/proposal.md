## Why

nbadb has three different kinds of evidence that are currently too easy for
repository consumers to conflate: structural transform discovery, compiled
star-table contracts, and physical materialization. None is an authored and
independently verified decision that a transform output is admitted to the
stable public model. Some consumers still derive a public set from registries
or physical tables, and the transform dependency sorter can ignore an absent
transform dependency. A structurally present output can therefore flow into
execution, loading, export, documentation, chat, assurance, or publication
without one mandatory disposition authority shared by every consumer.

The canonical current denominator is
`tuple(sorted(expected_transform_output_tables(include_live=True)))`, and it
must exactly equal
`tuple(table.output_name for table in compile_star_table_contracts().tables)`.
The compiled inventory additionally binds
`StarModelContractInventory.contract_sha256` and every table-local contract
root. The current first-generation observation is 261 outputs; 261 is not a
timeless constant, and every later generation derives its count from these
authorities. Structural discovery stays complete and unfiltered.

Stable publication also includes more than transform outputs. It needs an
exact, normalized, disjoint, operation-bound union of the Raw V2 exact-four,
W2 exact-six, mandatory unique `STAGING_MAP` tables, exact typed-admitted
conditional staging tables, and verified `active` transform outputs. No
component may be omitted, substituted, overlapped, or widened from physical
warehouse discovery. The Raw, W2, and conditional components must come from
one cumulative, same-snapshot operation authority; fixed table names alone do
not prove that the provider calls and typed landings that produced them are
complete.

## What Changes

- Add mandatory
  `VerifiedTransformOutputDispositionAuthorityEnvelopeV1`. Its canonical
  parser fresh-compiles structural and star-model authorities, replays the
  complete source bundle, reruns the current independent verifier, and
  reconstructs entries, dependencies, and proof before constructing the DTO.
  Author/reviewer task and role strings remain audit metadata, never admission
  evidence.
- Add an independent repository-owned
  `TransformOutputAuthoredDecisionAuthorityV1`. The current verifier compiles
  it from the checked-in canonical authored decision corpus, never from the
  candidate envelope or its proof pack, and requires exact row/decision
  equality. Current decision rows own output name, an exact reviewed structural
  table-authority pin, state, the complete five-boolean capability policy,
  semantic claims, reason code, evidence references, and revalidation triggers;
  retained tombstone decisions own their removal reason/evidence and reserved-
  name history. Structural family/contract/schema/transformer/column/dependency
  fields remain independently derived and must match the authored pin. Coherently
  editing an envelope row, its derived proof, and every enclosing root while
  leaving the trusted authored corpus unchanged must fail.
- Require one explicitly authored current entry for every exact structural
  output. Current entries have only `active`,
  `observed_only_experimental`, or `contract_not_modeled`; `removed` exists
  only as an immutable historical tombstone. V1 forbids tombstone mutation and
  name reuse.
- Make `CurrentTransformOutputDispositionV1` strictly table-local. Its digest
  excludes global inventory/generation identities, proof/source-bundle roots,
  author task/role, change records, operation identities, materialization
  evidence, and publication identities.
- Admit evolution only through `structural_addition`, `state_transition`,
  `contract_rebind`, or `removal`. A compiler reports an uncovered addition as
  red; it cannot manufacture a blocker, state, capability, row, or proof.
- Execute and primary-materialize exactly `active` plus
  `observed_only_experimental`; stable load and the transform publication
  component contain only `active`. V1 has no experimental export path.
- Enforce the complete transform dependency graph before execution:
  `active -> active`, experimental to active or experimental, and unknown,
  missing, ambiguous, duplicate, self, non-executable, or cyclic edges fail.
- Split evidence into immutable table-local
  `TransformOutputMaterializationReceiptV1` and per-operation
  `TransformOutputGenerationBindingV1`. A later operation may reuse a receipt
  only after byte-identical current entry/policy/dependencies and fresh
  physical attestation replay. The receipt remains bound to its original
  `transaction.generation_identity_sha256`; the binding records the current
  operation's exact generation identity. Unrelated global generation drift
  never causes a receipt to be reissued or relabelled.
- Persist exactly three internal authorities: immutable verified envelopes,
  immutable materialization receipts, and operation commitments containing the
  complete generation-binding set. Creation is all-absent and transactional;
  partial, extra, reordered, legacy, or wrong-shape state fails readback.
- Make one verifier-owned DuckDB transaction govern candidate relation
  visibility, fresh attestation, immutable receipt persist/readback, canonical
  swap, generation-binding closure, same-snapshot Raw/W2/conditional replay,
  and operation-commitment persist/readback. Faults at every boundary roll back
  without exposing partial canonical state.
- Add a cumulative `VerifiedOperationDataAuthorityV1`. It uses verifier-derived,
  HMAC-free durable locators for terminal Raw manifests; binds the detailed W2
  database replay and a typed conditional-staging authority; and rejects every
  missing, duplicated, foreign, or unexplained operation member. Full extraction
  requires one member per complete executable lane plus exactly one discovery
  member and one live member, with contract-blocked lanes represented only by
  canonical blocked evidence. A successor requires its prior cumulative roots
  plus exactly one terminal delta manifest covering every exact dispatch.
  Admission-only VPN/capacity canaries never enter the dataset denominator.
  The transaction first derives a non-admitting `OperationDataEvidenceV1` root;
  the transform commitment binds that root; and only committed exact readback
  may seal `VerifiedOperationDataAuthorityV1` from both roots. This avoids a
  digest cycle and adds no fourth internal table.
- Compile publication authority in three ordered phases: a table-only
  `StablePublicationTableUnionV1` from the same verified operation-data
  authority; one Kaggle-neutral, operation-bound
  `OperationPublicationResourceContractV1` using a canonical
  `PublicationResourcePathPolicyV1`; and the final `StablePublicationUnionV1`
  sealed only from those matching DTOs. The neutral contract preserves the
  exact four fixed resources and one CSV plus one policy-selected Parquet
  resource per table. All counts are runtime-derived; the current
  709-table/1,422-resource base and 711-table/1,426-resource maximum are
  drift-sensitive observations only.
- Separate expected resource identity from physical observation. Filesystem,
  DuckDB, and remote inventories may attest the already compiled contract but
  cannot add, remove, relabel, or change the kind of an expected resource.
- Propagate the exact component and union identities through export, scanner,
  terminal successor report, assured manifest, operation-bound metadata,
  publication-ledger intent, publication rights, marker, exact remote
  readback, reconciliation, and success evidence.
- Cut every governed consumer over with mandatory typed inputs and no
  `Optional`, default, feature flag, compatibility branch, dual read,
  module-global authority, registry reconstruction, or physical-table
  fallback.
- Preserve curated chat routing. The current 26-table route requirement is 25
  transform outputs plus the internal `_pipeline_metadata` table. The active
  transform filter applies only to the 25 transform dependencies; the internal
  table requires its own explicit route authority. `active` remains a ceiling,
  not a route generator.

## Capabilities

### New Capabilities

- `transform-output-disposition-authority`: exact authored and independently
  replay-verified transform dispositions, table-local receipt evidence,
  per-operation generation bindings, cumulative Raw/W2/conditional evidence,
  fail-closed transactional admission, neutral operation-bound resource
  derivation, and exact full-publication union authority.

### Modified Capabilities

- `warehouse-model-contract-assurance`: retains the complete structural census
  while stable consumers use verified dispositions and table-local roots.
- `full-extraction-transactional-recovery`: binds terminal materialization,
  export, assurance, and publication to exact operation and publication-union
  identities.
- `assured-recurring-successor-updates`: requires the same current verifier,
  fresh physical replay, bindings, and publication-union contract on every
  operation.

## Impact

Implementation affects transform authority contracts and canonical data,
`TransformPipeline`, orchestration and loader construction, `core/db.py`,
Raw request journals, W2 assurance, discovery and live capture, full-extraction
checkpoint composition, successor baselines, export, schema validation,
scanning, terminal assurance, artifact identity, Kaggle metadata/client/ledger/
rights, documentation registries, curated chat, agent context, workflows, and
their focused tests. Generated documentation is updated only through the
repository generator after implementation acceptance.

This governs repository-controlled paths only. It is not external SQL or
filesystem access control. The OpenSpec authorizes no source implementation,
live extraction, upload, remote readback, human-review fabrication, commit,
push, or `MODEL-GREEN`/publication-complete claim.
