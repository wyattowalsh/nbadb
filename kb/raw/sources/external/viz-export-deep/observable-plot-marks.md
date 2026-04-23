---
title: "Observable Plot Marks"
tags:
  - kb
  - raw
  - source
  - external
  - viz-export-deep
  - observable
  - plot
aliases: []
kind: raw-source
status: active
updated: 2026-04-14
source_url: https://observablehq.com/plot/features/marks
capture_type: markdown-extract
---

# Observable Plot Marks

## Source Record
| Field | Value |
|-------|-------|
| URL | `https://observablehq.com/plot/features/marks` |
| Owner | Observable |
| Scope | Feature documentation for Plot's mark model, layering, channels, scales, options, and data-shape expectations |
| Why it matters to nbadb | This is the clearest conceptual reference for building chart primitives compositionally rather than by choosing canned chart types |

## Summary
The page frames Observable Plot around marks as the primary chart-building unit: dots, lines, bars, areas, rules, and related geometries are layered together to form complete plots. It also explains how marks interact with scales, tidy data, channels, defaults, and type semantics.

## Key Points
- Plot deliberately avoids fixed chart types and instead builds charts by composing marks.
- Multiple marks can be layered in one plot, including marks generated conditionally or from multiple datasets.
- Marks usually work in data space through scales rather than literal pixels or colors.
- The docs strongly favor tidy tabular data, while still supporting accessor functions, parallel arrays, and Arrow tables.
- The page emphasizes that mark choice carries type semantics, such as choosing `rect` instead of `bar` when continuous intervals matter.

## nbadb Relevance
- Useful for deciding how warehouse-shaped outputs map into flexible docs or app visualizations.
- The mark-plus-channel model fits NBA analytics work where shot charts, timelines, comparisons, and layered annotations are common.
- The guidance around tidy data and semantic mark choice helps avoid misleading sports charts.
- Relevant if nbadb wants lightweight, editorial-style visualizations instead of heavier dashboard frameworks.

## Notable Sections
- Marks are geometric shapes
- Marks are layered
- Marks use scales
- Marks have tidy data
- Marks imply data types
- Marks have options
- Marks have channels
- Mark options

## Provenance
- Fetched from `https://observablehq.com/plot/features/marks` via `trafilatura` extraction on `2026-04-14`
