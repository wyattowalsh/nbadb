---
title: "Matplotlib Backends"
tags:
  - kb
  - raw
  - source
  - external
  - viz-export-deep
  - matplotlib
  - python
aliases: []
kind: raw-source
status: active
updated: 2026-04-14
source_url: https://matplotlib.org/stable/users/explain/figure/backends.html
capture_type: markdown-extract
---

# Matplotlib Backends

## Source Record
| Field | Value |
|-------|-------|
| URL | `https://matplotlib.org/stable/users/explain/figure/backends.html` |
| Owner | Matplotlib project |
| Scope | Reference explaining interactive and non-interactive backends, selection order, configuration methods, and debugging |
| Why it matters to nbadb | Backend choice affects whether Matplotlib charts render inline, open GUI windows, or write files reliably in local, notebook, CI, and server environments |

## Summary
The page explains Matplotlib backends as the rendering and display layer behind the plotting API, split between interactive GUI backends and non-interactive file-writing backends. It also documents backend selection precedence across `matplotlibrc`, `MPLBACKEND`, and `matplotlib.use(...)`, plus default auto-detection and troubleshooting guidance.

## Key Points
- Backends are divided into interactive UI backends and non-interactive hardcopy backends.
- Backend selection can be configured through `rcParams["backend"]`, the `MPLBACKEND` environment variable, or `matplotlib.use(...)`.
- If no backend is set explicitly, Matplotlib auto-detects the first usable backend from a platform-dependent priority list.
- `Agg` is the common raster renderer and fallback non-interactive backend when no display backend is available.
- The docs discourage unnecessary explicit `matplotlib.use(...)` calls because they reduce flexibility for downstream users.

## nbadb Relevance
- Critical for reliable static figure export in notebooks, scripts, CI, and docs-generation jobs.
- Helps explain why visualization code may behave differently between local GUI sessions and headless environments.
- Relevant if nbadb uses Matplotlib for report assets, QA plots, or automation where `savefig(...)` must work without a display.
- Debug guidance is useful if backend issues appear in developer setups or CI containers.

## Notable Sections
- What is a backend?
- Selecting a backend
- The builtin backends
- Static backends
- Interactive backends
- Using non-builtin backends
- Debugging the figure windows not showing

## Provenance
- Fetched from `https://matplotlib.org/stable/users/explain/figure/backends.html` via `trafilatura` extraction on `2026-04-14`
