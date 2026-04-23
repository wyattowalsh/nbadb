---
title: SQL Validator Service
tags:
  - kb
  - topics
  - chat
  - sql
  - validator
  - service
aliases:
  - Chat SQL Validator Service
  - SQL Validation and Repair Service
kind: concept
status: active
updated: 2026-04-22
source_count: 7
---

# SQL Validator Service

Use this note for the shortest grounded answer to "what does `src/nbadb/chat/sql/service.py` actually validate before chat SQL is explained, risk-scored, or repaired?"

## Purpose
`src/nbadb/chat/sql/service.py` is an advisory SQL analysis layer for the chat stack.

It does five things:
- extracts referenced tables from `FROM` and `JOIN` clauses
- skips locally defined CTE names so they are not treated as warehouse surfaces
- checks whether referenced catalog surfaces look grain-compatible
- asks DuckDB to `EXPLAIN` the query as a parse-and-plan validation step
- converts validation output into warnings, risk levels, and repair suggestions

It is not the primary read-only trust boundary. That still comes from `ReadOnlyGuard` and the execution wrappers described in [[wiki/topics/query-safety|Query Safety]].

## Table extraction and CTE skipping
The service uses two regexes:
- `_CTE_PATTERN` finds `WITH foo AS (` and `, bar AS (` names
- `_TABLE_PATTERN` finds identifiers after `FROM` and `JOIN`

`_extract_referenced_tables(query)` normalizes each match with `_normalize_table_name(...)` by:
- trimming whitespace and trailing commas
- stripping surrounding double quotes
- dropping any schema prefix and keeping only the last segment

CTE names are collected first, lowercased, then excluded from the final table list. This means a query like `WITH recent AS (...) SELECT ... FROM recent JOIN fact_game ...` reports only real warehouse surfaces, not `recent`.

The function also preserves first-seen order and de-duplicates table names.

## Grain-consistency checks
`check_grain_consistency(...)` maps extracted table names onto catalog objects, then compares the surfaces that are actually known.

Returned fields:
- `tables`: extracted table references
- `families`: catalog families for matched surfaces
- `grains`: catalog grain strings
- `shared_join_keys`: intersection of all non-empty `join_keys`
- `shared_entities`: intersection of all non-empty `primary_entities`
- `warnings`: grain-level review messages

Status rules:
- `unknown` when no extracted tables resolve to catalog surfaces
- `consistent` by default when matched surfaces do not trigger any review rule
- `review` when any of these hold:
  - more than one raw surface is referenced, where raw means `fact` or `bridge`
  - multiple surfaces share no obvious join key
  - multiple surfaces span different grains and also share no primary entity

The service treats `fact` and `bridge` as the risky raw families because they are most likely to duplicate rows when joined without explicit aggregation.

## Validation and EXPLAIN flow
`validate_sql_query(...)` is the main preflight entry point.

Validation order:
1. reject empty SQL
2. run `ReadOnlyGuard.validate(...)`
3. extract referenced tables
4. reject unknown tables not found in the catalog
5. open DuckDB in `read_only=True`, disable external access, and run `EXPLAIN <query>`
6. compute grain warnings and heuristic query warnings

The `EXPLAIN` step is used as a parser and planner sanity check. If DuckDB raises an error, the service returns `ok: false` with a generic `DuckDB rejected query: <ErrorType>` message instead of exposing raw engine text.

`explain_sql_query(...)` reuses `validate_sql_query(...)` first, then runs `EXPLAIN` again and returns the plan rows alongside the same warning and grain metadata.

## Heuristic warnings
Beyond structural validation, the service adds review hints for common analyst mistakes:
- `SELECT *` triggers a warning to project only needed columns
- any `JOIN` without `GROUP BY` or `DISTINCT` triggers duplicate-risk review
- missing `LIMIT` triggers an exploratory-scope reminder
- querying a raw `fact` or `bridge` surface without `WHERE` triggers a scope warning

These warnings are advisory only. They do not block otherwise valid SQL.

## Risk scoring
`estimate_query_risk(...)` converts validation output into a small severity label.

Risk rules:
- `blocked` when validation failed
- `low` by default for valid queries
- `medium` when grain status is `review`
- `high` when more than one raw surface is referenced
- `medium` when exactly one raw surface is used without a `WHERE`, or when the warning list reaches three or more items

The model is intentionally simple: it is meant to flag suspicious analytical shapes, not to estimate runtime cost.

## Repair suggestions
`repair_sql_query(...)` is a fallback helper for recovery prompts and UI guidance.

It builds suggestions from the validation result:
- for each unknown table, call `search_catalog(...)` and suggest up to three nearby known surfaces
- if `SELECT *` appears, suggest explicit column selection
- if any `JOIN` appears, suggest re-checking join keys and requested grain with `check_grain_consistency(...)`

If none of those produce a suggestion, it falls back to a generic repair kit:
- confirm names with `describe_table`
- reduce to one semantic surface first
- re-check requested grain and season filters

The return shape keeps the original query, error context, validation payload, candidate replacement surfaces, and de-duplicated suggestions.

## Practical reading
Treat this file as the chat SQL advisor for surface-awareness, grain review, and recovery hints.

Use [[wiki/topics/query-safety|Query Safety]] for the real enforcement boundary, and use catalog notes when you need to understand where `family`, `grain`, `join_keys`, and `primary_entities` come from.

## Related notes
- [[wiki/topics/query-safety|Query Safety]]
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/query-agent|Query Agent]]
- [[wiki/topics/query-cookbook-families|Query Cookbook Families]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| service purpose and exported helpers | `src/nbadb/chat/sql/service.py` | defines `check_grain_consistency`, `validate_sql_query`, `explain_sql_query`, `estimate_query_risk`, and `repair_sql_query` |
| table extraction and CTE skipping | `src/nbadb/chat/sql/service.py` | `_CTE_PATTERN`, `_TABLE_PATTERN`, `_normalize_table_name`, `_extract_referenced_tables` |
| grain-consistency rules | `src/nbadb/chat/sql/service.py` | uses catalog `family`, `grain`, `join_keys`, and `primary_entities`; review state for multi-raw, no shared key, or no shared entity |
| EXPLAIN validation path | `src/nbadb/chat/sql/service.py` | `ReadOnlyGuard.validate`, unknown-table rejection, DuckDB `read_only=True`, `SET enable_external_access = false`, and `EXPLAIN` |
| heuristic warnings | `src/nbadb/chat/sql/service.py` | `SELECT *`, join-without-aggregation review, missing `LIMIT`, and raw-surface-without-`WHERE` checks |
| risk scoring | `src/nbadb/chat/sql/service.py` | maps validation and warning state into `low`, `medium`, `high`, or `blocked` |
| repair suggestions | `src/nbadb/chat/sql/service.py` | unknown-table candidate surfaces via `search_catalog(...)`, plus `SELECT *`, join, and generic fallback repairs |
