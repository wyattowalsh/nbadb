---
title: "swar/nba_api GitHub Repository"
kind: raw-source
status: captured
source_url: "https://github.com/swar/nba_api"
captured_on: "2026-04-14"
capture_type: repository-homepage
why_it_matters: "Authoritative upstream repository for source code, release cadence, package layout, and the docs tree that nbadb can use to trace endpoint wrappers back to implementation."
---

## Source Record

- Source: upstream GitHub repository homepage for `swar/nba_api`
- Scope captured: repository purpose, visible project layout, community metadata, and current release signal
- Capture date: `2026-04-14`

## Why It Matters

This repository is the durable upstream implementation source behind the generated docs. It exposes where endpoint wrappers live, how docs are organized, and whether the package is actively maintained enough for nbadb to track contract drift.

## Key Excerpts

> "An API Client package to access the APIs for NBA.com"

> Visible top-level areas include docs, the upstream package source tree, tests, and tooling.

> Repository metadata at capture time: about `3.6k` stars, `698` forks, `479` commits, latest release `v1.11.4` dated `2026-02-20`.

> "A significant purpose of this package is to continuously map and analyze as many endpoints on NBA.com as possible."

## Capture Notes

- GitHub HTML includes a large amount of navigation chrome; only repository-level facts were retained here.
- The visible repo layout confirms separate source, docs, and tests trees, which is useful when tracing endpoint behavior beyond the generated docs.
- The current release date suggests the package is still maintained and should be treated as a live upstream contract source.
