## ADDED Requirements

### Requirement: Assurance artifacts form one exact-source generation

The system MUST freeze one generation context, write all required children to a
fresh directory, validate membership and parent digests, and write a top-level
manifest last. Reused directories or individually valid files without that
manifest MUST NOT satisfy the gate.

The mandatory child set MUST be independently derived from the assurance
profile schema and frozen provider/request/model registries, not from a
hand-maintained child-name tuple or the files present in the output directory.
It SHALL include provider/package authority, request/constraint/competition
closure, exact-body and structured table-only reconstruction, route/field
conservation, exact field-occurrence temporal evidence, model
dispositions/contracts, metric/use-case and lineage coverage,
`AuthoritySemanticDiffV1`, deterministic generation, exact independent local
test receipts, and exact independent read-only review receipts.

#### Scenario: Source changes during generation

- **WHEN** a relevant source or provider input digest differs between the pre- and post-generation snapshots
- **THEN** generation fails and publishes no current assurance pointer

#### Scenario: One child comes from another generation

- **WHEN** a child generation-input or parent digest differs from the manifest
- **THEN** the entire set is rejected even if that child parses independently

#### Scenario: A hard-coded child list omits a new registry authority

- **WHEN** the frozen profile or registries require a child that is absent from a hand-maintained implementation tuple
- **THEN** assurance derives the missing requirement independently, rejects the generation, and keeps MODEL-GREEN red

#### Scenario: Test or review evidence is only self-attested

- **WHEN** a child contains an existence flag, command claim, or receipt not bound to the exact source, generation, command, result, and independent producer
- **THEN** the test/review child is invalid and MODEL-GREEN remains red

### Requirement: Semantic generation is deterministic

The assurance command SHALL produce identical semantic digests from two fresh
directories with identical inputs. Observation timestamps and machine-local
paths are nonsemantic; ordered parameters, result sets, columns, routes, and
dependencies are semantic.

#### Scenario: Only generation time changes

- **WHEN** two otherwise identical generations have different observation times
- **THEN** their byte metadata may differ but their child and set semantic digests match

#### Scenario: Column order changes

- **WHEN** any ordered result, route, schema, or public output column sequence changes
- **THEN** the affected semantic digest and artifact-set digest change

### Requirement: MODEL-GREEN is distinct from DATA-GREEN

The local command MUST emit a `MODEL-GREEN` decision only from exact contracts,
fixtures, implementation, deterministic generation, local tests, and review.
It MUST NOT claim populated-data correctness, live availability, or publication
success. Those require the later separately authorized `DATA-GREEN` gate.

#### Scenario: Every local contract passes but no extraction has run

- **WHEN** the atomic local gate and independent reviews pass
- **THEN** the report may say `MODEL-GREEN: GREEN` while explicitly saying dataset population and `DATA-GREEN` are unproven

#### Scenario: A remote or legal gate is open

- **WHEN** exact-SHA CI, free-capacity/egress probing, NBA probing, extraction, Kaggle readback, or permission review has not occurred
- **THEN** that gate remains separately open and is not converted into a local model failure or false completion

### Requirement: Authority semantic diff governs full versus delta admission

Before initial extraction, resume, daily/monthly refresh, targeted backfill, or
publication admission, the system MUST emit an independently verified
`AuthoritySemanticDiffV1` comparing the previous admitted complete authority
with the newly frozen complete authority. It SHALL classify provider/package,
request/result/header/field, temporal, competition, route, model, schema, key,
type, meaning, lineage, reconstruction, and assurance-child changes and bind
the exact affected scopes and selected mode to planning and workflow admission.

Only exactly enumerable additive or bounded compatible changes MAY select a
since-last-observed refresh, recent-window refresh, or targeted backfill. An
identity, key, type, meaning, route, header-occurrence, coverage, temporal,
competition, model-disposition, reconstruction, or assurance break—and every
unknown, ambiguous, incomplete, or missing baseline—MUST require a fresh full
authority. The first extraction under this change MUST always be full, and a
caller MUST NOT override a full decision with delta mode.

#### Scenario: A small additive field change is bounded

- **WHEN** the independent diff proves one additive field occurrence, its lossless route, exact affected request scopes, and compatible model disposition with no other changes
- **THEN** admission may select a receipt-bound targeted backfill or recent-window delta for exactly those scopes

#### Scenario: A key or meaning changes

- **WHEN** any public key, type, grain, semantic meaning, route identity, or coverage interpretation changes
- **THEN** the diff requires a fresh full authority even if the changed file set is small

#### Scenario: The prior baseline is incomplete

- **WHEN** the previous authority lacks any mandatory child or the diff cannot enumerate an affected scope exactly
- **THEN** the decision is full and no update watermark or recent window can make it delta

### Requirement: DATA-GREEN binds the fresh public body and manual baseline evidence

The later DATA-GREEN gate MUST use one fresh attempt-one GitHub Actions chain,
only capacity and services independently proven free at the point of use,
mandatory public parser-input body authority for every body-bearing provider
occurrence, all stable source/silver/gold outputs, exact Kaggle readback, and a
forced exact-version local download with manual read-only database
interrogation. NordVPN, another paid proxy/VPN, a trial, or an existing paid
subscription MUST NOT be an execution dependency.
Experimental fitted models MUST be evaluated separately and MUST NOT gate a
stable release unless individually promoted by a reviewed admission contract.

#### Scenario: Only one free slot is independently proven

- **WHEN** one NBA-reachable slot passes the complete free-capacity admission and recheck contract
- **THEN** the complete request universe may execute serially; no four-slot or six-slot minimum is inferred

#### Scenario: No free NBA-reachable path is proven

- **WHEN** every candidate path is paid, trial-backed, subscription-backed, unreachable, or unverified
- **THEN** execution reports `capacity_blocked` before provider calls without reducing the request universe or weakening MODEL-GREEN

#### Scenario: Remote readback passes without manual interrogation

- **WHEN** the exact Kaggle version verifies remotely but has not been force-downloaded and interrogated locally under read-only controls
- **THEN** DATA-GREEN remains open

### Requirement: Production control topology remains singular

The public nbadb repository and existing Kaggle dataset MUST be the only source
and dataset authorities, and GitHub Actions MUST be the only production initial,
catch-up, daily, monthly, and publication control plane. A private state
repository/package/service, hosted notebook cron, or alternate scheduler MUST
NOT become admission, completeness, recovery, or publication authority.

#### Scenario: An alternate production scheduler is configured

- **WHEN** a private service, notebook cron, or non-Actions automation can launch extraction or publication independently
- **THEN** MODEL-GREEN fails until that authority is removed
