## Why

The hybrid thin Q&A surface now has broad route coverage, but its unfinished
implementation can select a season from an unrelated warehouse rowset, report
unsupported season filters that were never applied, resolve known cross-route
matcher collisions by incidental order, and lose preference ownership under
concurrent writes. These are correctness and trust-boundary defects on the
public `nbadb ask` and `nbadb chat` paths.

## What Changes

- Replace the process-global warehouse season lookup with validated,
  route-local probes that mirror each catalog query's visible rowset.
- Fail closed before SQL generation when a season year or type is malformed or
  unsupported by the matched route, and expose stable reason metadata without
  exposing unusable SQL.
- Make catalog specificity deterministic and add a reviewed collision corpus
  that rejects cross-route co-top matches during catalog validation.
- Resolve player and team names only through route-declared warehouse lookups,
  bind validated numeric identities as query parameters, and fail closed when a
  required entity is missing, unresolved, or ambiguous.
- Serialize session-owned preference mutations and reject foreign, null-owned,
  or malformed ownership instead of silently overwriting or deleting records.
- Scope preference and trajectory reads to the requesting session, and make
  saved findings session-scoped, bounded, and collision-safe.
- Render SQL provenance once in Chainlit, as a side element rather than a
  duplicate copy in the main answer.
- Keep the product a catalog-routed, read-only Q&A surface with fail-closed
  warehouse discovery, absolute launcher paths, and no raw-text SQL generation.

## Capabilities

### New Capabilities

- `route-local-season-binding`: Route-specific warehouse defaults, strict
  season-dimension support, reasoned fail-closed planning, and safe response
  metadata.
- `deterministic-catalog-routing`: Specificity ordering and a reviewed
  cross-route collision gate for catalog intents.
- `route-local-entity-binding`: Route-declared player/team capabilities,
  warehouse-only identity resolution, parameterized ID predicates, and
  fail-closed entity planning.
- `session-owned-chat-memory`: Atomic, ownership-preserving preference create,
  update, delete, and read behavior across concurrent sessions.
- `hybrid-chat-runtime-safety`: Consistent CLI, Chainlit, notebook, and source
  inventory behavior around the catalog-only read-only runtime.

### Modified Capabilities

None. This repository does not yet have archived OpenSpec capabilities for the
hybrid chat surface.

## Impact

The change affects chat catalog metadata and validation, query planning and
response metadata, season parsing and SQL binding, SQLite-backed chat memory,
MCP memory wrappers, CLI and Chainlit launch behavior, the companion notebook
and offline season-helper examples, focused tests and fixtures, and
authored/generated docs.
It also changes finding artifact names and Chainlit result presentation without
adding a compatibility path for title-based overwrites or cross-session reads.
It adds no free-form language-model SQL path and no compatibility alias for
incorrect season or ownership behavior.
