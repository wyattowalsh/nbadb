---
title: "Polars Documentation Home"
tags:
  - kb
  - raw
  - source
  - external
  - data-stack
  - polars
aliases: []
kind: raw-source
status: active
updated: 2026-04-14
source_url: https://docs.pola.rs/
capture_type: markdown-extract
---

# Polars Documentation Home

## Source Record
| Field | Value |
|-------|-------|
| URL | `https://docs.pola.rs/` |
| Owner | Polars project |
| Scope | Product overview, philosophy, features, and entrypoint to the user guide and API reference |
| Why it matters to nbadb | Polars is `nbadb`'s primary dataframe engine at the Python boundary |

## Summary
The Polars docs home frames Polars as a Rust-first, Arrow-friendly dataframe library for Python, R, and Node.js. It emphasizes speed, strict schemas, query optimization, parallelism, out-of-core execution, and an intuitive query API.

## Key Points
- Polars is designed around a query optimizer, parallel execution, and strict dtypes.
- It highlights first-class I/O support across files, cloud storage, and databases.
- Arrow interoperability is presented as a core capability, often enabling zero-copy exchange.
- The homepage explicitly steers readers toward lazy scanning and `collect()` workflows.

## nbadb Relevance
- Matches the repo convention of preferring Polars for dataframe manipulation before or around DuckDB execution.
- Reinforces why the project leans on typed schemas and lazy planning instead of ad hoc eager pandas-style flows.
- Supports architectural decisions around large historical workloads where parallelism and memory discipline matter.

## Notable Sections
- Key features
- Philosophy
- Example lazy query
- Getting started entrypoint

## Provenance
- Fetched from `https://docs.pola.rs/` on `2026-04-14`
