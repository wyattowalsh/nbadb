## Why

The current repository has broad name-level coverage—162 registered extractors,
434 staging routes, and 261 schema-backed transform outputs—but the mandatory
pre-extraction audits proved that those counts are not sufficient assurance.
Generated bronze files describe declarations rather than durable response
capture; temporal ledgers conflate a 1946 planner fallback with observed
availability; field-fate checks can accept passthrough or same-name inference;
most public grains are inferred; and generated reports can come from different
source snapshots. The initial extraction must not begin on those false-green
premises.

The same audits also found concrete adapter and model defects: non-2xx status
can be lost by the upstream client unless nbadb captures it, mixed pandas
conversion can destroy values, structured headers can be misnamed, live empty
packets can become a null row, raw schemas can strip pinned-provider fields,
several aggregate tables misstate their grain, and a player snapshot explicitly
classified as provenance-blocked is still consumed as discovery evidence.

## What Changes

- At execution kickoff, enumerate official non-yanked stable `nba_api`
  releases newest-to-oldest, compatibility-test them against the repository
  stack, and freeze the first compatible release. The current local
  `nba-api==1.11.4` pin is planning evidence, not a perpetual latest-release
  assertion. Make observed distribution/source/docs/tools/runtime evidence—not
  repository constants—the resulting extraction authority.
- Capture every successful body-bearing response's exact provider parser-input
  body before parsing and publish it with public-safe request/result/header/
  ordinal/value/presence/provenance landings and committed receipts. Calls that
  have no parser input MUST carry an explicit bodyless disposition; failures
  MUST NOT invent a body or publish unrestricted error content. Bind body and
  parsed receipts to journals, staging chunks, lane state, checkpoints,
  terminal assurance, and the Kaggle resource inventory.
- Treat the current 434-route silver contract as a regression floor, then add
  deterministic universal fallback routes for every observed additive result
  set, header occurrence, heterogeneous cell, and nested path. No successful
  provider field may disappear while waiting for semantic classification.
- Reconcile all 139 pinned stats classes, four live classes, four embedded
  NBA/WNBA static arrays, every repo extractor/alias, and every output-changing
  parameter through a scope-relative least-fixed-point request manifest.
- Account for every package-exposed stats/live/static/helper module, physical
  route, constructor and wire parameter, result occurrence, nested path,
  duplicate header occurrence, field, competition, staging key, and public
  sink. An implementation gap, warning-and-omit import, or
  `contract_not_modeled` disposition remains MODEL-red.
- Replace blanket temporal support claims with evidence-aware, discontinuous
  intervals and an exact field-occurrence ledger. Every declared or observed
  field records applicability, earliest/latest evidence, internal gaps, and
  distinct nonexistent/nonapplicable/missing/null/present-empty/populated states
  by endpoint, result occurrence, competition, season type, and request scope.
- Define a safe foundation-to-observed-workload-to-dependent-child DAG for
  matchup and lineup endpoints; never generate Cartesian player or lineup
  requests.
- Model `CumeStatsPlayerGames` and `CumeStatsTeamGames` as required foundation
  calls for `CumeStatsPlayer` and `CumeStatsTeam`. Bind each dependent call to
  the exact ordered provider game-ID workload instead of invoking a required
  `game_ids` parameter with an incomplete planner shape.
- Independently derive a complete model-candidate census, then issue one
  `StableModelDispositionV1` covering every current and newly defensible source,
  raw, staging, dimension, fact, bridge, aggregate, analytics, live-snapshot,
  and conditional lossless model. Compile explicit contracts for all 261
  current public outputs plus every admitted addition, including grain, key
  policy, joins, SCD behavior, row operations, lineage, temporal meaning, and
  transform/schema digests. A withheld implementation gap cannot pass as an
  exclusion.
- Add a versioned metric and use-case registry for every sourced field and
  derived public measure. Repair evidence-backed defects, add stable event,
  possession, stint, lineup, on/off, shot-context, tracking, form, clutch, and
  workload features, and isolate fitted RAPM/xFG/WPA/rating models under an
  explicitly experimental non-gating namespace.
- Generate endpoint, bronze, temporal, route, field-fate, star, metric, model,
  and documentation evidence in one fresh directory and publish one
  exact-source-bound assurance manifest only after every compatibility edge
  validates.
- Emit an independently verified `AuthoritySemanticDiffV1` before every
  extraction or update admission. Exactly enumerable additive or bounded
  compatible changes may select delta refresh/backfill; broad, identity-, key-,
  type-, meaning-, route-, header-, or coverage-breaking changes and every
  ambiguity require a fresh full authority.
- Treat every pre-change extraction checkpoint as diagnostic/migration evidence
  only. The new parser-input, request-universe, field-conservation, and model
  identities require one brand-new initial extraction from the exact reviewed
  source SHA; no older checkpoint may satisfy terminal completeness.
- Use the single public repository's GitHub Actions workflows as the only
  initial, catch-up, daily, monthly, and publication control plane. Production
  execution may use only services and capacity independently proven free at the
  point of use; it MUST NOT depend on NordVPN, another paid proxy/VPN, a trial,
  or an existing paid subscription. One proven slot may execute serially. If no
  free NBA-reachable path exists, execution reports `capacity_blocked` without
  reducing semantic coverage.
- Close DATA-GREEN only after the exact published Kaggle version is forced into
  a new local root and manually interrogated through read-only DuckDB and
  immutable/read-only SQLite checks against the publication receipts.

## Capabilities

### New Capabilities

- `pinned-nba-api-provider-boundary`: observed exact-release authority,
  latest-stable-compatible selection, complete package/request/result authority,
  nbadb-owned failure contracts, mandatory public-safe exact parser-input body
  authority for body-bearing calls, explicit bodyless dispositions, and
  immutable no-network fixtures.
- `generated-bronze-and-temporal-contracts`: declarative and public-safe
  physical bronze, structured table-only reconstruction, exact route/field
  dispositions, field-occurrence earliest/latest/internal-gap temporal evidence,
  and safe dependent workload contracts.
- `warehouse-model-contract-assurance`: explicit silver and 261-output gold
  semantics, independently derived stable/experimental model dispositions,
  column lineage, metric definitions, and finite use-case coverage.
- `atomic-pre-extraction-assurance`: fresh-generation compatibility checks,
  independently derived mandatory child membership, deterministic semantic
  digests, `AuthoritySemanticDiffV1`, one manifest, and a strict `MODEL-GREEN`
  decision distinct from later `DATA-GREEN` evidence.

### Modified Capabilities

None in the base-spec delta at this stage. The active
`full-extraction-transactional-recovery` change remains the authority for
checkpoint transactions, workflow admission mechanics, egress operations,
terminal replay, and Kaggle publication. Before implementation can pass
cross-change assurance, its capacity clauses MUST be reconciled with this
change's accepted free-at-the-point-of-use constraint; a paid/VPN minimum or
fixed four-to-six-slot requirement is a blocking conflict. This change adds the
provider/model-assurance prerequisites without duplicating recovery mechanics.

## Impact

This change affects the nba_api adapter boundary, extraction attempt and staging
receipts, lane/checkpoint artifacts, endpoint and temporal generation,
raw/staging/star validation, dependent workload planning, metrics and consumer
metadata, CLI assurance commands, generated documentation, OpenSpec ledgers,
and focused/full local tests. It preserves current public table names when their
grain and meaning remain valid, versions semantic replacements, dynamically
generates the final table/resource inventory, and preserves the semantic lane
identity/coverage-hash contract. The repository and Kaggle dataset remain the
only source and public-data authorities; no second state repository is added.

Commit, push, exact-SHA CI, workflow dispatch, free-capacity/egress use, NBA API
requests, extraction, Kaggle download/upload/readback/manual interrogation,
repository settings, and qualified legal/permission review remain explicit
external gates and are not completed merely by authoring this change.
