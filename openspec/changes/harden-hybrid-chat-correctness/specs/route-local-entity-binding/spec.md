## ADDED Requirements

### Requirement: Every routed catalog entry declares entity capability
Each routed entry MUST declare player, team, or no entity support. An
entity-capable route MUST declare one numeric ID column or one symmetric pair of
numeric ID columns for executable SQL and its route-local season probe. A route
MAY remain league-wide without an entity unless one of its reviewed cues requires
a fixed entity count.

#### Scenario: Generic route is legitimately league-wide
- **WHEN** a user asks for a generic game log without naming a player
- **THEN** the route remains executable without an entity predicate

#### Scenario: Route cue requires an entity
- **WHEN** `who played for` matches the roster route without one resolvable team
- **THEN** planning returns `needs_params` before a season probe or SQL generation

### Requirement: Entity resolution uses fixed warehouse lookups
The resolver MUST query only fixed identity columns from `dim_player` or
`dim_team` through a read-only DuckDB connection with external access disabled.
It MUST match original question tokens against warehouse-returned aliases and
MUST NOT interpolate raw question text into SQL.

#### Scenario: Unique full identity is present
- **WHEN** a question contains one uniquely matched player or team name
- **THEN** the resolver returns that warehouse identity and canonical display name

#### Scenario: Alias is ambiguous
- **WHEN** the highest-specificity alias belongs to multiple warehouse identities
- **THEN** planning returns reason `ambiguous_entity` without probing, SQL, or entity metadata

#### Scenario: Required identity is unresolved
- **WHEN** a reviewed required cue contains no resolvable warehouse identity
- **THEN** planning returns reason `unresolved_entity` with bounded guidance

### Requirement: Entity IDs are parameter-bound into route and probe SQL
Every resolved entity ID MUST be a positive integer and MUST enter SQL only as a
positional parameter attached to a static route-declared predicate. The same
predicate MUST constrain a missing-year route-local probe.

#### Scenario: Two players ask for the same route
- **WHEN** LeBron James and Stephen Curry are each resolved for a player game-log request
- **THEN** their plans carry distinct entity parameters and each result contains only the requested player

#### Scenario: Two teams ask for the same route
- **WHEN** Boston and Miami are each resolved for a roster request
- **THEN** their plans carry distinct team parameters and each result contains only the requested team

#### Scenario: Symmetric matchup has two identities
- **WHEN** two unique identities are supplied to a symmetric matchup route
- **THEN** the predicate binds both orientations and returns only that pair

### Requirement: Failed entity planning has no query side effects
Missing, unresolved, or ambiguous required entities MUST return `needs_params`
before season probing, SQL binding, dry-run, or execution. Such a response MUST
omit SQL, SQL hash, season execution metadata, entity IDs, and entity names.

#### Scenario: Ambiguity coexists with a valid season
- **WHEN** an ambiguous entity and a valid season occur in one question
- **THEN** entity failure wins and no warehouse season probe or executable SQL is produced
