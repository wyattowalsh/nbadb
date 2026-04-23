---
title: "Plotly Interactive HTML Export"
tags:
  - kb
  - raw
  - source
  - external
  - viz-export-deep
  - plotly
  - export
aliases: []
kind: raw-source
status: active
updated: 2026-04-14
source_url: https://plotly.com/python/interactive-html-export/
capture_type: markdown-extract
---

# Plotly Interactive HTML Export

## Source Record
| Field | Value |
|-------|-------|
| URL | `https://plotly.com/python/interactive-html-export/` |
| Owner | Plotly |
| Scope | Python documentation for saving interactive Plotly figures as HTML files and embedding them into templates |
| Why it matters to nbadb | This is the main reference for preserving Plotly interactivity when shipping browser-viewable outputs instead of static screenshots |

## Summary
The page documents Plotly's HTML export path through `write_html(...)` and `to_html(...)`, including the trade-off between self-contained files and external Plotly.js loading. It also shows how to embed figure fragments inside Jinja2 templates using `full_html=False`.

## Key Points
- `fig.write_html(...)` writes a browser-openable interactive HTML file directly to disk.
- Self-contained output is convenient but large because it inlines Plotly.js, typically producing multi-megabyte files.
- The `include_plotlyjs` parameter controls whether Plotly.js is bundled inline or referenced externally.
- `fig.to_html(full_html=False)` emits an embeddable fragment rather than a complete HTML page.
- Jinja2 templating is the recommended pattern for inserting Plotly output into a broader HTML layout.

## nbadb Relevance
- Strong option for shareable interactive exports of dashboards, exploratory charts, or docs-adjacent visual prototypes.
- The file-size trade-off matters if nbadb stores or publishes exported HTML artifacts.
- Template embedding fits well if charts are injected into generated pages or richer report layouts.
- Complements static export by covering the path where hover, zoom, and legend interactivity need to be retained.

## Notable Sections
- Interactive vs Static Export
- Saving to an HTML file
- Controlling the size of the HTML file
- Inserting Plotly Output into HTML using a Jinja2 Template
- Full Parameter Documentation

## Provenance
- Fetched from `https://plotly.com/python/interactive-html-export/` via `trafilatura` extraction on `2026-04-14`
