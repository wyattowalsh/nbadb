---
title: Query Agent
tags:
  - kb
  - topics
  - agent
  - query
aliases:
  - Read-only Query Agent
kind: concept
status: active
updated: 2026-04-14
source_count: 6
---

# Query Agent

This note covers the small, local `src/nbadb/agent` query path. It is intentionally narrower than the richer chat application under `chat/`.

## What the local query agent actually does
`QueryAgent` is a pattern-matching read-only helper, not a general text-to-SQL system.

Current behavior:
- accepts a natural-language question and optional result limit
- matches the question against a small fixed set of regex patterns
- if a pattern matches, uses the paired canned SQL template
- if nothing matches, returns schema context and tells the user to write DuckDB SQL directly

## Execution model
When a canned query is selected:
- the limit is clamped
- the query is validated by `ReadOnlyGuard`
- read queries are wrapped in a hard outer `LIMIT`
- DuckDB is opened in `read_only=True` mode
- external access is disabled
- statement timeout is set
- results are rendered as a plain pipe-delimited text table

## Guardrails worth remembering
`ReadOnlyGuard` is stricter than a simple write-keyword blocklist.

It currently:
- Unicode-normalizes SQL with NFKC before checking it
- strips both block comments and line comments before validation
- rejects stacked statements after comment stripping
- rejects write operations and dangerous functions
- allows only `SELECT`, `WITH`, `EXPLAIN`, `SHOW`, and `DESCRIBE` prefixes

## Relationship to the chat app
Use the local query agent for narrow, safe, pattern-driven ask behavior.

Use [[wiki/topics/chat-surface|Chat Surface]] for richer analysis, Python post-processing, charting, and iterative workflows.

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| local query behavior | `src/nbadb/agent/query.py` | regex patterns, limit handling, fallback |
| safety model | `src/nbadb/agent/safety.py` | read-only SQL validation |
| schema fallback | `src/nbadb/agent/context.py` | schema dump fallback path |
| public CLI framing | `README.md` | `nbadb ask` positioning |
| project surface distinction | `wiki/topics/chat-surface.md` | companion KB contrast note |
| repo vocabulary | `AGENTS.md` | current surface map |
