---
title: "Polars Database IO"
tags:
  - kb
  - raw
  - source
  - external
  - warehouse-deep
  - polars
  - database
aliases: []
kind: raw-source
status: active
updated: 2026-04-14
source_url: https://docs.pola.rs/user-guide/io/database/
capture_type: markdown-extract
---

# Polars Database IO

## Source Record
| Field | Value |
|-------|-------|
| URL | `https://docs.pola.rs/user-guide/io/database/` |
| Owner | Polars project |
| Scope | User-guide page for reading from and writing to databases from Polars |
| Why it matters to nbadb | `nbadb` uses Polars as its primary dataframe layer and bridges warehouse execution with SQL and Arrow-friendly tools |

## Summary
This page explains how Polars reads and writes database-backed data. It distinguishes URI-based reads from connection-object reads, documents the supported engines, and clarifies which paths stay Arrow-native versus which paths materialize through other dataframe layers.

## Key Points
- `pl.read_database_uri` is for URI/connection-string reads, while `pl.read_database` takes an existing connection object such as SQLAlchemy.
- `read_database_uri` is typically faster than `read_database` when the alternative path would move rows through Python first.
- Read engines are ConnectorX and ADBC, both described as Arrow-native and zero-copy friendly.
- ConnectorX is the default engine; ADBC is explicit and currently narrower in database support.
- Writes use `DataFrame.write_database` with either SQLAlchemy or ADBC.
- SQLAlchemy writes route through a pandas DataFrame backed by PyArrow before insertion.

## nbadb Relevance
- Helpful when choosing the lowest-copy path between SQL systems and Polars.
- Clarifies where Arrow-native interchange is preserved versus where a pandas bridge appears.
- Useful upstream reference for future database export/import features or metadata sync tasks.

## Notable Sections
- Difference between `read_database_uri` and `read_database`
- ConnectorX
- ADBC
- `write_database`
- SQLAlchemy vs. ADBC write engines

## Provenance
- Fetched from `https://docs.pola.rs/user-guide/io/database/` on `2026-04-14`
