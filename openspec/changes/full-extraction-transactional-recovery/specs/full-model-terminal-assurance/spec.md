## ADDED Requirements

### Requirement: The workflow produces the request-closure scan authority

The full-extraction workflow MUST publish an immutable, exact-receipt-bound
`request-closure-observation-inventory.json` derived from the same committed
RequestUniverse, invocation observations, body/bodyless objects, field-temporal
authority, and checkpoint generation used by terminal processing. Terminal scan
MUST consume that exact artifact ID and digest; a checkout-local file or
recomputed best-effort inventory MUST NOT substitute for it.

#### Scenario: Workflow inventory and checkpoint agree

- **WHEN** every canonical invocation, observation, body/bodyless receipt, result set, field, temporal disposition, and checkpoint association matches
- **THEN** scan may continue to catch-up and model assurance

#### Scenario: The inventory file is absent

- **WHEN** the workflow reaches full-publication scan without the exact receipt-bound inventory
- **THEN** scan emits an error and no assured artifact is created

#### Scenario: A same-name inventory appears later

- **WHEN** artifact inventory changes after the committed receipt was selected
- **THEN** scan remains bound to the exact ID/digest and rejects name-based substitution

### Requirement: Full scan independently reconciles every authority layer

`scan --fail-on error --full-publication` MUST independently verify the
RequestUniverse least-fixed-point receipt; every invocation's sole terminal
disposition; parser-input body or bodyless authority; result-set and field
inventory; field fate and temporal evidence; checkpoint transaction; terminal-
catch-up components/window/seal; optional TailGeneration; staging journals;
stable model/schema/lineage contracts; row-count and row-preserving cardinality
anchors; all export formats; and the assured-file inventory. A declaration in
the manifest MUST NOT substitute for independent recomputation.

#### Scenario: An invocation is skipped or circuit-suppressed

- **WHEN** it lacks one permitted evidence-backed terminal disposition
- **THEN** full scan fails even if all curated tables are populated

#### Scenario: Unknown additive drift is staged

- **WHEN** a result set or field has no reviewed fate, lineage, type/key, or temporal contract
- **THEN** DATA may remain lossless but MODEL-GREEN and full publication fail

#### Scenario: Public representations disagree

- **WHEN** DuckDB, SQLite, CSV, or Parquet differ in declared table inventory, ordered schema, logical type authority, row count, or assured digest
- **THEN** full scan fails before publication

#### Scenario: A catch-up call crosses the seal

- **WHEN** any accepted terminal observation ends after the committed seal
- **THEN** full scan rejects the catch-up generation and requires a parent-bound tail

### Requirement: Only the new full-model baseline can become initially assured

For user choice B, initial assurance MUST require a fresh exact-SHA workflow
attempt one with no old lane-manifest, resume-source, checkpoint, recovery,
public-body, or Kaggle-data authority. Recovery within that chain MUST bind the
same source, RequestUniverse, public-observation, field-temporal, model, and
checkpoint-associated authority digests.

#### Scenario: Current Kaggle data could fill a missing table

- **WHEN** current public bytes predate the complete model and authority contracts
- **THEN** they remain diagnostic/comparison evidence and cannot satisfy initial scan coverage

#### Scenario: A same-chain committed receipt is exact

- **WHEN** source SHA and every authority digest are unchanged and the artifact receipt is exact
- **THEN** crash recovery may resume from that committed generation

#### Scenario: An authority digest changes

- **WHEN** request, body, field, temporal, or model identity differs
- **THEN** recovery is rejected and another fresh attempt-one baseline is required

### Requirement: Assured artifact creation is receipt-bound and all-or-nothing

Only a zero-error full scan over the exact committed checkpoint and catch-up may
create `assured-artifact-manifest.json`. The manifest MUST bind source SHA,
chain, RequestUniverse, public observation/body/bodyless, field-temporal, model,
checkpoint, catch-up seal, optional tail, terminal report, and the sorted SHA-
256 inventory of every exported file. Experimental outputs MUST carry explicit
admitted or withheld dispositions and MUST NOT weaken stable-model gates.

#### Scenario: Stable models pass and an experiment is withheld

- **WHEN** the experiment has its own exact reviewed disposition and is excluded from stable output claims
- **THEN** the stable assured bundle may proceed while recording that disposition

#### Scenario: One associated receipt is missing

- **WHEN** any required authority or file digest is absent, ambiguous, or mismatched
- **THEN** no assured artifact is published

### Requirement: Initial Kaggle publication requires exact remote and manual proof

The initial new-baseline upload MUST consume only the exact assured artifact and
the durable publication ledger. Success requires a positive exact Kaggle
version, stable marker reconciliation, complete paginated resource inventory,
streamed SHA-256 readback of every resource, runtime-derived table/resource and
schema/row-count parity, and a publication receipt binding all assured
authorities. Generic latest, upload submission, HTTP success, or dataset metadata
version alone MUST NOT close publication.

#### Scenario: Upload returns but exact readback is incomplete

- **WHEN** any version, marker, inventory page, resource hash, schema, table, row count, or authority digest cannot be verified
- **THEN** publication remains unresolved and no second upload is admitted

#### Scenario: Exact remote readback succeeds

- **WHEN** the exact positive version and every declared resource match the assured receipt
- **THEN** remote publication is verified but final DATA-GREEN remains open pending manual interrogation

### Requirement: Manual verification uses the exact downloaded version

The exact positive version MUST be force-downloaded into a new owner-only local
root with an inventory/hash receipt. Manual verification MUST open DuckDB read-
only with external access disabled and SQLite immutable/read-only, run integrity
and foreign-key checks, and interrogate request, body/bodyless, field-temporal,
model/schema, row/key/cardinality, catch-up/seal, tail, and publication receipts.
Pre/post file-tree hashes MUST prove the verification did not mutate the bundle.

#### Scenario: Manual verification uses a cache or generic latest

- **WHEN** the local bytes are not bound to the exact positive published version
- **THEN** manual assurance and final closeout remain incomplete

#### Scenario: Database interrogation finds a mismatch

- **WHEN** any read-only query contradicts the assured or publication receipts
- **THEN** DATA-GREEN fails and the existing remote version is reconciled as a defect rather than silently replaced
