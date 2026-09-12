## ADDED Requirements

### Requirement: Every year-capable route declares one validated warehouse probe
Each route with a season-year column MUST declare one immutable warehouse probe
with static read-only SQL and a nonempty table set wholly contained in the
route's declared catalog tables. The probe MUST compute the maximum route year
over the route template's visibility-defining rowset.

#### Scenario: Route probe mirrors visible rows
- **WHEN** a route template uses inner joins or fixed predicates to define queryable rows
- **THEN** its probe retains those joins and predicates while replacing selected output columns with the maximum route-year expression

#### Scenario: Probe reads an unrelated table
- **WHEN** a probe declares a table outside the route's catalog table set or adds a join not used to establish route visibility
- **THEN** catalog validation rejects the probe

### Requirement: Probe placeholders match route season-type support
A type-capable route probe MUST contain exactly one positional placeholder for
the effective season type. A year-only route probe MUST contain no placeholder.
Every probe MUST parse and `EXPLAIN` against the catalog validation fixture.

#### Scenario: Type-capable route supplies a type
- **WHEN** the year is missing and the route has a season-type column
- **THEN** the system executes that route's probe with the explicit valid type or `Regular Season`

#### Scenario: Probe placeholder contract differs
- **WHEN** a type-capable probe has zero or multiple placeholders, a year-only probe has a placeholder, or fixture `EXPLAIN` fails
- **THEN** catalog validation fails before the route can execute

### Requirement: Explicit season parsing precedes warehouse defaulting
The system MUST identify valid explicit years, malformed year-shaped tokens,
relative year phrases, and explicit season types before executing a warehouse
probe. A valid explicit year MUST bypass probing and MUST take precedence over
a relative year phrase.

#### Scenario: Explicit year and relative phrase coexist
- **WHEN** a question contains a valid explicit season year and `this season` or `last season`
- **THEN** the explicit year is used and the response warns that the relative phrase was ignored

#### Scenario: Explicit type omits year
- **WHEN** a type-capable route receives a valid explicit season type but no year
- **THEN** the route-local probe uses that type and the resolved year source is `warehouse_default` when the probe succeeds

#### Scenario: Relative phrase omits type
- **WHEN** `this season` or `last season` supplies the year for a type-capable route without an explicit type
- **THEN** the route defaults the type to `Regular Season` after extraction

### Requirement: Unsupported or malformed season dimensions fail before SQL generation
The system MUST return `needs_params` without executable SQL when it encounters a
malformed year-shaped token, an explicit year on a route without a year column,
an explicit type on a route without a type column, or a required year that
cannot be resolved. A season-like candidate is four Unicode decimal digits,
optional horizontal whitespace, one of `-`, `/`, `‐`, `‑`, `‒`, `–`, `—`, or
`−`, and one to four Unicode decimal digits. Unicode digits MAY be normalized
only to decide whether a candidate is year-shaped; accepted syntax MUST remain
the original, adjacent ASCII `YYYY-YY` token. Valid full ISO or slash calendar dates,
standalone years, and candidates embedded in alphanumeric identifiers MUST NOT
be classified as malformed seasons. If a malformed candidate and a valid or
relative season phrase coexist, the malformed candidate MUST win.

#### Scenario: Season year is malformed
- **WHEN** a question contains a year-shaped token such as `2024-99`
- **THEN** planning returns reason `invalid_season_year` and guidance `Specify a valid season year like 2024-25.`

#### Scenario: Confusable or widened syntax is malformed
- **WHEN** a question contains `2024/25`, `2024 - 25`, Unicode decimal digits, a Unicode dash, or a one-, three-, or four-digit suffix
- **THEN** planning returns `invalid_season_year` before a warehouse probe or SQL generation

#### Scenario: A full date or identifier is not a malformed season
- **WHEN** a question contains `2024-10-22`, `2024/10/22`, a standalone `2024`, or a season-shaped substring adjacent to an alphanumeric identifier
- **THEN** that text alone does not trigger `invalid_season_year`

#### Scenario: Malformed candidate coexists with another season phrase
- **WHEN** a question contains a malformed candidate together with a valid season or `this season` or `last season`
- **THEN** planning returns `invalid_season_year` without probing or generating SQL

#### Scenario: Route cannot filter by year
- **WHEN** a no-year route receives an explicit valid season year
- **THEN** planning returns reason `unsupported_season_year` and guidance `This question route does not support a season year.`

#### Scenario: Route cannot filter by type
- **WHEN** a year-only or seasonless route receives an explicit valid season type
- **THEN** planning returns reason `unsupported_season_type` and guidance `This question route does not support a season type.`

#### Scenario: Year-only star routes reject phantom types
- **WHEN** `clutch_performance` or `player_matchups` receives an explicit season type while its schema exposes only `season_year`
- **THEN** planning returns `unsupported_season_type` with no SQL or season-type metadata

#### Scenario: Required year remains unresolved
- **WHEN** a year-capable route has no valid explicit, warehouse, or calendar year
- **THEN** planning returns reason `missing_season_year` and guidance `Specify a season year like 2024-25 (or ask for this/last season).`

### Requirement: Warehouse probe execution is request-local and route-scoped
After route matching and season-capability validation, a query agent MUST
execute at most one warehouse probe for a request whose matched route needs a
default year. It MUST use the matched route's probe and effective season type,
or no parameter for a year-only route. It MUST NOT retain or reuse a maximum in
process-global, cross-request, or persistent state.

#### Scenario: Route rowsets have different maxima
- **WHEN** player scoring has a 2022-23 maximum and standings has a 2023-24 maximum
- **THEN** each request executes its matched route's probe and receives only that route's maximum

#### Scenario: Season types have different maxima
- **WHEN** one type-capable route is planned once for `Regular Season` and once for `Playoffs`
- **THEN** each request executes the route probe with its own effective type and neither request reuses the other's maximum

#### Scenario: Repeated requests do not share probe state
- **WHEN** the same route is requested twice and warehouse contents change between requests
- **THEN** each request executes its own probe and the second request observes the current route rowset

### Requirement: Probe failure falls back visibly to the calendar season
When a route probe raises a database error, references an unavailable table or
column, returns no row, or returns an invalid year, the system MUST use the
validated calendar season, set year provenance to `default`, and include the
warning `Warehouse season lookup was unavailable; used the calendar season.`

#### Scenario: Warehouse maximum is unavailable
- **WHEN** the route probe cannot produce a valid season year
- **THEN** the executable plan uses the calendar season and exposes the stable fallback warning

### Requirement: Response season metadata describes applied SQL only
For executable routes, `season_source` MUST describe year provenance as one of
`extracted`, `warehouse_default`, `default`, or `missing`, and season year/type
metadata MUST appear only when the corresponding validated predicate was bound
to SQL. A `needs_params` response MUST omit SQL, SQL hash, season year, season
type, and season source while retaining its catalog entry, reason, and guidance.

#### Scenario: Explicit type accompanies warehouse year
- **WHEN** a valid explicit type is bound and the year comes from a successful route probe
- **THEN** response metadata reports that type and `season_source=warehouse_default`

#### Scenario: Planning fails closed
- **WHEN** the plan returns `needs_params`
- **THEN** no executable SQL or season execution metadata is exposed
