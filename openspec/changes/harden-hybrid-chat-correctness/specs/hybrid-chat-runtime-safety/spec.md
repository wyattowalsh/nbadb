## ADDED Requirements

### Requirement: Chat launchers require an existing warehouse
`nbadb ask`, `nbadb chat`, and the canonical Chainlit runtime MUST fail closed
when the selected warehouse path is absent, unreadable, or not a regular usable
DuckDB file. They MUST NOT create an empty warehouse as a side effect of Q&A.

#### Scenario: Warehouse path is missing
- **WHEN** a user starts a Q&A entry point with a nonexistent warehouse path
- **THEN** the command returns bounded guidance and creates no database file

### Requirement: The chat launcher passes absolute runtime paths
Before spawning Chainlit with `cwd=chat/`, `nbadb chat` MUST resolve and inject
absolute `NBADB_DUCKDB_PATH` and `NBADB_DATA_DIR` values. It MUST fail closed when
`chat/chainlit_app.py` or `chat/pyproject.toml` is absent.

#### Scenario: Relative data directory is configured
- **WHEN** the CLI resolves a valid warehouse from a relative data directory
- **THEN** the child environment receives absolute database and data-directory paths

#### Scenario: Canonical launcher files are missing
- **WHEN** either required `chat/` launcher file is absent
- **THEN** the CLI refuses to fall back to a retired or implicit app surface

### Requirement: Catalog templates are the sole SQL source
The live Q&A path MUST execute only a matched catalog `sql_template` plus
validated literal season predicates. It MUST retain `ReadOnlyGuard`, open
DuckDB with `read_only=true`, disable external access, and MUST NOT interpolate
raw question text into SQL.

#### Scenario: Catalog route executes
- **WHEN** a question matches a supported route and planning succeeds
- **THEN** the guarded, limited catalog SQL executes through the read-only connection

#### Scenario: Question is unsupported
- **WHEN** no supported catalog route matches
- **THEN** the system returns bounded unsupported guidance without generating or executing SQL

### Requirement: Product entry points expose one supported route contract
The CLI, Chainlit app, and companion notebook MUST describe and exercise the
same catalog-routed behavior, season defaults, unsupported responses, and
read-only boundary. The bundled offline analytics helper scripts are not a Q&A
entry point and MUST NOT be documented as one. Their season conversion helper
MUST accept only the same exact consecutive ASCII `YYYY-YY` grammar used by the
catalog runtime and exact `2YYYY` identifiers.

#### Scenario: Public examples are validated
- **WHEN** maintained examples execute against the fixture warehouse
- **THEN** route, season, SQL-hash presence, and unsupported behavior match the runtime contract

#### Scenario: Offline helper receives a malformed season identifier
- **WHEN** a standalone analytics helper receives a nonconsecutive, Unicode, separated, prefixed, or otherwise non-exact season value
- **THEN** it raises a bounded validation error instead of forwarding a malformed identifier

### Requirement: Packaged chat sources have no orphan runtime surface
The repository source-inventory gate MUST reject packaged chat bytecode without
a matching `.py` source and MUST reject reintroduction of retired `apps/chat/`
launcher content. It MUST inspect every `.pyc` under both canonical chat roots,
map immediate `__pycache__` entries through Python's cache-path contract, map
legacy adjacent bytecode to its sibling `.py`, and report malformed cache names
instead of skipping them. A mapped source MUST remain inside the scanned root
and be a regular source file. Returned paths MUST be sorted. CLI-reported
diagnostics MUST render them as project-relative paths in deterministic order.
This gate proves source presence only; it does not claim
bytecode freshness or content equality.

#### Scenario: Orphan bytecode or retired app appears
- **WHEN** source inventory finds unmatched chat bytecode or a retired chat app surface
- **THEN** validation fails with the offending project-relative path

#### Scenario: Optimized or nested cache bytecode has source
- **WHEN** normal, optimized, package `__init__`, or nested bytecode maps to a regular `.py` inside its canonical chat root
- **THEN** the inventory accepts the bytecode regardless of whether its compiled content is current

#### Scenario: Cache mapping is malformed or escapes the root
- **WHEN** a `.pyc` cache name cannot be mapped, maps outside the root, or maps to a missing, broken, symlinked, or non-regular source
- **THEN** the inventory reports the bytecode path as orphaned

### Requirement: Saved findings are session-scoped and collision-safe
The live `/save` path MUST require a normalized bounded session ID and title,
store findings under that session, and use an immutable bounded slug-plus-digest
identity. Equal titles, including concurrent equal titles, MUST create distinct
findings without overwriting another session. Filesystem errors MUST surface as
one bounded artifact-store error without leaking host paths.

#### Scenario: Two sessions save one title
- **WHEN** two sessions save `Scoring leader`
- **THEN** each receives a distinct durable finding with its original session metadata

#### Scenario: Title exceeds the public bound
- **WHEN** `/save` receives an oversized title
- **THEN** it returns bounded guidance before filesystem access

### Requirement: Chainlit presents SQL provenance once
The main Chainlit answer MUST use the nonverbose result rendering while keeping
warnings visible. When executable SQL exists, it MUST appear only in one side
element and MUST NOT be duplicated in the message body.

#### Scenario: Successful routed answer includes SQL
- **WHEN** a catalog route executes successfully
- **THEN** rows and warnings appear in the main answer and one SQL side element carries provenance
