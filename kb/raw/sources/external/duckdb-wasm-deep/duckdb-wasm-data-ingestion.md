---
title: DuckDB-Wasm Data Ingestion
kind: raw-source
status: captured
source_url: https://duckdb.org/docs/stable/clients/wasm/data_ingestion
captured_on: 2026-04-14
capture_type: webfetch-markdown-summary
why_it_matters: Captures the official ingestion model for getting browser-visible files and in-memory datasets into DuckDB-Wasm.
---

## Source Record

- Source URL: `https://duckdb.org/docs/stable/clients/wasm/data_ingestion`
- Fetch method: `webfetch` in markdown mode via DuckDB's current raw Markdown mirror after redirect
- Capture date: `2026-04-14`

## Why It Matters

This page explains the two-step import pattern that most DuckDB-Wasm data flows use: register data with the browser-facing virtual filesystem, then ingest it with insert helpers or direct SQL. It also shows the supported ingestion shapes for Arrow, CSV, JSON, Parquet, and remote HTTP sources.

## Key Excerpts

> "There are two steps to import data into DuckDB."

> "First, the data file is imported into a local file system using register functions."

> "Then, the data file is imported into DuckDB using insert functions ... or directly using FROM SQL query."

> "If you encounter a Network Error ... when you try to query files from S3, configure the S3 permission CORS header."

## Capture Notes

- The register step is the core mental model: browser file/text/buffer/URL handles become named files DuckDB can read.
- Arrow streaming requires an explicit IPC end-of-stream marker, which is easy to miss if you only skim examples.
- Remote Parquet access is supported both through explicit file registration and by querying URLs directly in SQL.
- S3 and remote object access remain subject to browser CORS rules, not just DuckDB SQL semantics.
