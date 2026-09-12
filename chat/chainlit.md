# nbadb Chat

Ask **read-only, catalog-matched** questions about the local nbadb DuckDB warehouse.

This UI is **not** free-form NL→SQL. Questions are matched to curated routes whose season capabilities are explicit: year + type, year only, or seasonless. A missing year on a year-capable route executes that route's visible-rowset maximum probe once for the request; type-capable routes default to Regular Season. Probe state is not shared across requests. If lookup is unavailable or invalid, the route uses the calendar season and reports `Warehouse season lookup was unavailable; used the calendar season.` Answers show rows first; SQL provenance is attached only when a query was planned.

Write an explicit season as adjacent ASCII `YYYY-YY`, for example `2024-25`.
Season-like slash forms, Unicode digits or dashes, separator whitespace, and
wrong-width or nonconsecutive suffixes are rejected before lookup or SQL. Valid
full calendar dates, standalone years, and adjacent alphanumeric identifiers are
not treated as malformed seasons.

## Examples

- Team pace leaders
- Team stats for 2024-25
- Clutch stats for 2024-25
- Franchise championships
- Draft picks

## Commands

- `/save <title>` — save the last successful result as a local finding artifact

## Setup

An existing DuckDB warehouse is required. Point at it with `NBADB_DUCKDB_PATH` (absolute path recommended). `nbadb chat` injects the absolute configured path automatically and fails closed instead of creating a missing warehouse.

The scripts under `chat/skills/nba-data-analytics/` are offline analytics helpers,
not an alternate chat or Q&A entry point. Their season conversion utility accepts
only exact consecutive ASCII `YYYY-YY` values and exact `2YYYY` identifiers.
