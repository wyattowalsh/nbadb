---
title: "Mermaid Theming"
tags:
  - kb
  - raw
  - source
  - external
  - viz-export-deep
  - mermaid
  - theming
aliases: []
kind: raw-source
status: active
updated: 2026-04-14
source_url: https://mermaid.js.org/config/theming.html
capture_type: markdown-extract
---

# Mermaid Theming

## Source Record
| Field | Value |
|-------|-------|
| URL | `https://mermaid.js.org/config/theming.html` |
| Owner | Mermaid project |
| Scope | Configuration reference for Mermaid themes, `themeVariables`, and site-wide versus diagram-local styling |
| Why it matters to nbadb | This defines how Mermaid diagrams can be styled consistently across generated docs, architecture diagrams, and lineage visuals |

## Summary
The page explains Mermaid's theming system, including built-in themes, site-wide initialization, per-diagram frontmatter config, and the `themeVariables` model for customization. A key constraint is that only the `base` theme is directly customizable, while many related colors are derived automatically from a smaller set of hex inputs.

## Key Points
- Mermaid supports built-in `default`, `neutral`, `dark`, `forest`, and `base` themes.
- Site-wide theming is configured through `mermaid.initialize(...)`, while per-diagram theming uses frontmatter config.
- Only the `base` theme is intended for direct customization.
- `themeVariables` exposes a broad set of tokens spanning global colors plus diagram-family-specific values.
- The theming engine expects hex colors and computes many dependent colors automatically from core inputs.

## nbadb Relevance
- Important for keeping Mermaid diagrams visually aligned with the docs site's design system.
- Especially relevant for ER diagrams, lineage diagrams, and architecture flows that may be generated or embedded repeatedly.
- Automatic derivation from base colors can simplify maintaining a coherent visual language.
- The hex-only constraint matters if any docs-generation pipeline emits theme config programmatically.

## Notable Sections
- Available Themes
- Site-wide Theme
- Diagram-specific Themes
- Customizing Themes with `themeVariables`
- Color and Color Calculation
- Theme Variables
- Flowchart Variables
- Sequence Diagram Variables

## Provenance
- Fetched from `https://mermaid.js.org/config/theming.html` via `trafilatura` extraction on `2026-04-14`
