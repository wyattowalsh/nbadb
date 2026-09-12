## Context

`nbadb ask` and `nbadb chat` implement hybrid thin Q&A: a question selects one
curated catalog route, validated season literals are attached to that route's
static SQL template, and the query executes through a read-only DuckDB guard.
The current draft already carries per-route season columns and a specificity
score, but the warehouse default still comes from one process-global query over
`agg_player_season` and `dim_game`. A route can therefore receive a season that
has no visible rows in its own joins and predicates.

The same draft can retain an explicit season type in response metadata for a
year-only route even though no type predicate reaches SQL. Preference writes
perform a read followed by an unconditional upsert, so two SQLite connections
can race and transfer ownership. The catalog also lacks a reviewed corpus that
turns known cross-route matcher ties into an authoring failure.

## Goals / Non-Goals

**Goals:**

- Select a missing year from the exact rowset queried by the matched route.
- Reject malformed or unsupported season dimensions before producing SQL.
- Make response metadata describe only predicates that actually reached SQL.
- Detect reviewed cross-route matcher collisions before runtime.
- Resolve route-supported player and team references without interpolating raw
  question text into SQL.
- Make preference ownership atomic, explicit, and stable across sessions.
- Keep preference, trajectory, and saved-finding reads/writes isolated by
  normalized session identity.
- Preserve one catalog-only, read-only behavior contract across every launcher.

**Non-Goals:**

- Free-form LLM natural-language-to-SQL or executable model-generated code.
- Adding season columns or compatibility filters to tables that do not expose
  them.
- Inferring that a null-owned preference is shared with every scoped session.
- Reintroducing `apps/chat/` or making the knowledge base product authority.

## Decisions

### 1. Warehouse season defaults are route-local static probes

Each year-capable route declares an immutable `WarehouseSeasonProbe` containing
static SQL and the tables it reads. The probe replaces the route template's
selected columns with `max(<route year column>)` while retaining the template's
visibility-defining `FROM`, inner joins, and `WHERE` predicates. It does not add
unrelated hint-table joins.

Catalog validation rejects a probe unless its SQL is read-only, its table set
is nonempty and a subset of the route's declared tables, and its placeholder
count matches the route: one season-type placeholder for type-capable routes and
none for year-only routes. The catalog fixture must parse and `EXPLAIN` every
probe. After route matching and capability checks, a `QueryAgent` executes at
most one route-local probe for that request, with the request's effective season
type when the route supports it. Probe results are not retained in process-global,
cross-request, or persistent state, so another route, season type, or request
cannot inherit a scalar maximum.

An explicit valid year bypasses the probe. A probe error, unavailable table or
column, empty result, or invalid maximum falls back to the calendar season and
adds the stable warning `Warehouse season lookup was unavailable; used the
calendar season.`

**Alternative considered:** retain one maximum across player and game tables.
That maximum cannot prove that a standings, roster, split, or box-score route
has a queryable row after its own joins.

### 2. Parsing precedes defaulting and unsupported dimensions fail closed

Season extraction records explicit year and type independently. Relative year
phrases set a year but do not inject a type; `Regular Season` is supplied later
only for a route that has a type column. A valid explicit year wins over a
relative phrase and produces a warning about the ignored relative phrase.

Planning first detects malformed year-shaped tokens and explicit dimensions,
then evaluates the matched route's declared support. A malformed year, an
explicit year on a no-year route, or an explicit type on a no-type route returns
`needs_params` before probing or SQL binding. A valid explicit type on a
type-capable route participates in the route-local probe when the year is
missing. Only after those gates may defaulting and literal binding run.

Candidate detection preserves original text. It recognizes a 19xx/20xx-shaped
four-Unicode-decimal-digit prefix, optional horizontal whitespace, an ASCII
slash or ASCII/Unicode dash, and a one-to-four-digit suffix. Normalized digits
are used only to detect the candidate; only an original adjacent ASCII
`YYYY-YY` token can be valid. Valid full ISO/slash calendar dates, standalone years, and
adjacent alphanumeric identifiers are excluded. Any malformed candidate wins
over another valid or relative season phrase so plausible SQL cannot conceal
bad input.

`QueryPlan` carries an internal `needs_reason` with one of
`invalid_season_year`, `unsupported_season_year`, `unsupported_season_type`, or
`missing_season_year`. A `needs_params` response identifies the catalog entry
and stable guidance, but omits SQL, SQL hash, season values, and season source.
For executable routes, `season_source` describes year provenance only:
`extracted`, `warehouse_default`, `default`, or `missing`.

**Alternative considered:** ignore an unsupported type while echoing it in
metadata. That makes the response claim a filter the database never applied.

### 3. Catalog order cannot conceal a reviewed cross-route collision

Runtime ranking remains deterministic: maximize `match span * 2 - match start`,
then the regex-pattern length, then earlier catalog order. A repository-owned
reviewed corpus pairs representative questions with their expected routes.
Catalog validation evaluates every pattern for each corpus row and rejects a
cross-route co-top semantic match before runtime. Co-top patterns belonging to
the same route are permitted.

**Alternative considered:** rely on catalog order alone. A harmless entry
reorder could silently change the public meaning of a question.

### 4. Scoped preference mutation uses one immediate transaction

At the preference-store boundary, `session_id=None` means unscoped administrator
access; a supplied empty or whitespace-only value is invalid. Scoped create,
update, and delete begin with `BEGIN IMMEDIATE` and deserialize the existing row
through `ProfileRecord.model_validate_json` before authorization.

A scoped caller creates an absent key as its owner and may update or delete only
an exact same-owner record. A foreign owner, null owner, or malformed record
rolls back and raises `PermissionError("preference is not owned by this
session")`. An unscoped administrator retains existing owner, notes, and
creation time when omitted. Updates preserve creation time and refresh only the
update time. After authorization, preference updates parse both present
`updated_at` copies as aware timestamps, normalize them to UTC, and advance from
their valid maximum by at least one microsecond even if the wall clock stalls or
moves backward. One missing legacy copy is healed; malformed, naive, doubly
missing, or unadvanceable timestamps use the existing scoped/admin error map.
The JSON and SQL copies are written identically with microsecond precision.
Trajectory timestamps keep their existing precision. Missing deletion returns
`False`.

MCP mutation wrappers still require a nonempty session, bounded payloads, and
explicit delete confirmation. They return the same sanitized ownership failure
without database contents.

**Alternative considered:** conditional upsert after an unlocked read. Separate
connections can both observe absence and let the later commit steal ownership.

### 5. Every chat entry point shares the catalog-only safety boundary

Missing or unreadable warehouses fail closed rather than creating a database.
`nbadb chat` injects absolute `NBADB_DUCKDB_PATH` and `NBADB_DATA_DIR` values
before starting the canonical `chat/` Chainlit app. The CLI, Chainlit app, and
notebook use the same supported route behavior. The offline analytics scripts
under `chat/skills/` are not Q&A entry points; only their exact season
identifier grammar is aligned with the live runtime.

The live execution path retains `ReadOnlyGuard`, DuckDB `read_only=true`, and
`enable_external_access=false`. Catalog `sql_template` values plus validated
literal season binding are the only SQL source; raw question text is never
interpolated. Source inventory fails when packaged bytecode lacks a matching
source file or the retired `apps/chat/` surface reappears. The inventory scans
both canonical roots, maps immediate `__pycache__` names through
`importlib.util.source_from_cache`, maps adjacent legacy bytecode to a sibling
source, and treats malformed, escaping, missing, symlinked, or non-regular
mappings as deterministic orphan paths. It proves source presence, not compiled
freshness.

### 6. Entity filters are route-declared, warehouse-resolved, and parameterized

Every routed catalog entry declares whether it supports a player entity, a team
entity, or no entity filter. Entity-capable routes also declare the exact numeric
ID column or symmetric pair of columns used by both executable SQL and the
route-local season probe. Routes that are meaningful league-wide remain
executable without an entity unless a route-specific cue requires one; for
example, a generic roster listing remains valid while `who played for ...`
requires one team.

Resolution reads only fixed columns from `dim_player` or `dim_team` through a
read-only connection with external access disabled. Original question text is
token-matched against returned warehouse names, first/last names, cities, and
abbreviations. The resolver selects only unique highest-specificity identities.
Equal-specificity identities are ambiguous; required cues with too few resolved
identities are unresolved. Both conditions return `needs_params` before season
probing, SQL binding, dry-run, or execution.

Successful identities are positive integers and enter catalog and probe SQL only
as positional parameters. One identity binds one declared column, or an OR over
a symmetric pair. Two identities bind both directions of a declared symmetric
pair. Season probes receive the same entity predicate, so a missing year is
selected from the entity-visible rowset rather than a league-wide maximum.

### 7. Session scope governs reads and saved-finding identity

Preference and trajectory reads require the same normalized, nonempty scoped
session used by MCP writes. The store validates each decoded record and returns
only exact-owner rows. Null-owned, foreign, or malformed rows are never exposed
through scoped reads. Any trusted administrator-wide inspection is a separately
named store API and is not registered as a general MCP tool.

Saved findings live under a normalized session bucket. Their filenames combine
a bounded human-readable slug with an immutable digest identity, so repeated or
concurrent equal titles never overwrite another finding. Titles and session IDs
are bounded before filesystem access, metadata retains the original session,
and filesystem failures are mapped to one bounded artifact-store error.

Chainlit renders the main answer without verbose SQL details and attaches SQL at
most once as a side element. Warnings remain visible in the main answer.

## Risks / Trade-offs

- **[Risk] Route probe SQL drifts from its template.** -> Validate table
  membership, placeholders, schema, and `EXPLAIN` for the complete catalog
  matrix in one fixture-backed gate.
- **[Risk] A warehouse transient causes an older calendar fallback.** -> Surface
  the stable warning and keep the result's provenance `default`.
- **[Risk] The collision corpus is incomplete.** -> Treat it as a reviewed,
  additive regression surface and retain deterministic runtime ranking for
  uncatalogued wording.
- **[Risk] Immediate SQLite transactions increase brief lock contention.** ->
  Keep the critical section to one row validation and one mutation, and test
  separate-connection races.
- **[Trade-off] Unsupported user dimensions now return guidance instead of a
  partially filtered result.** -> Prefer an honest fail-closed response over a
  plausible but semantically false answer.

## Migration Plan

1. Add and validate probe metadata and the reviewed collision corpus without
   changing executable SQL templates.
2. Move query planning to parse, capability-check, probe, bind, and then expose
   response metadata in that order.
3. Replace preference read/upsert and delete with immediate transactions and
   ownership-parity tests.
4. Reconcile CLI, Chainlit, notebook, source inventory, and docs around the
   shared route behavior, and align the offline helper's season grammar without
   presenting it as a product entry point.
5. Run focused chat/agent/CLI tests, then full lint, type, unit, integration,
   docs, and source-inventory gates.
6. Add route entity metadata and resolution before executing or probing, then
   close cross-session reads, saved-finding collisions, and duplicated SQL.

The behavior is a clean current-state correction. No legacy season-default or
foreign-write compatibility path is retained.

## Open Questions

None. The reviewed corpus can grow additively, but its initial routes, ownership
rules, fallback behavior, and fail-closed metadata contract are fixed here.
