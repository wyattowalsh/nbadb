---
title: "nba_api ReadTheDocs Index"
kind: raw-source
status: captured
source_url: "https://nba-api-sbang.readthedocs.io/en/latest/"
captured_on: "2026-04-14"
capture_type: docs-index
why_it_matters: "Primary upstream documentation hub for the package surface, usage patterns, and the split between stats and live endpoints that nbadb wraps."
---

## Source Record

- Source: `nba_api` ReadTheDocs landing page
- Scope captured: package purpose, install/runtime expectations, canonical usage examples, and links to endpoint docs
- Capture date: `2026-04-14`

## Why It Matters

This is the top-level contract map for the upstream package nbadb depends on. It establishes the package's two main surfaces, `nba_api.stats` and `nba_api.live.nba`, and points to the endpoint-specific pages that document parameter sets and response shapes.

## Key Excerpts

> "`nba_api` is an API Client for `www.nba.com`. This package intends to make the APIs of NBA.com easily accessible and provide extensive documentation about them."

> "from nba_api.stats.endpoints import playercareerstats"

> "from nba_api.live.nba.endpoints import scoreboard"

> "A significant purpose of this package is to continuously map and analyze as many endpoints on NBA.com as possible."

## Capture Notes

- The page is a documentation index, not a single endpoint contract.
- It links directly to endpoint docs and example notebooks that are more useful for field-level extraction contracts.
- The landing page still presents the package as the canonical entry point for both stats and live NBA data access.
