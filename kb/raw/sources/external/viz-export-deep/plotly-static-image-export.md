---
title: "Plotly Static Image Export"
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
source_url: https://plotly.com/python/static-image-export/
capture_type: markdown-extract
---

# Plotly Static Image Export

## Source Record
| Field | Value |
|-------|-------|
| URL | `https://plotly.com/python/static-image-export/` |
| Owner | Plotly |
| Scope | Python documentation for exporting Plotly figures to static image formats with Kaleido, browser requirements, and output controls |
| Why it matters to nbadb | This defines the practical path for producing reproducible PNG, SVG, PDF, and related assets from Plotly-based visualizations |

## Summary
The page explains Plotly's static export workflow around Kaleido, including required dependencies, supported file formats, byte export, batch export, and width-height-scale controls. It also documents the browser dependency introduced with Kaleido v1 and the deprecation path for Orca.

## Key Points
- Static export requires Kaleido; Orca remains available only as a deprecated fallback until after September 2025.
- Kaleido v1 no longer bundles Chrome and instead searches for a compatible Chrome or Chromium installation.
- `fig.write_image(...)` supports PNG, JPEG, WebP, SVG, and PDF, with format inferred from filename extension unless set explicitly.
- `plotly.io.write_images(...)` is the faster path for exporting multiple figures in one call.
- `fig.to_image(...)` returns raw bytes and supports `width`, `height`, and `scale` for resolution control.

## nbadb Relevance
- Useful for generating deterministic chart artifacts for docs, reports, and notebook outputs.
- SVG and PDF exports matter for publication-quality visuals and versioned documentation assets.
- Chrome availability is an operational dependency if nbadb adopts Plotly-based export tooling in CI or local scripts.
- Batch export support is relevant if multiple season, team, or player figures are generated together.

## Notable Sections
- Install Dependencies
- Write Image to a File
- Write Multiple Images
- Get Image as Bytes
- Specify Image Dimensions and Scale
- Image Export Settings (Kaleido)
- Additional Information on Browsers with Kaleido

## Provenance
- Fetched from `https://plotly.com/python/static-image-export/` via `trafilatura` extraction on `2026-04-14`
