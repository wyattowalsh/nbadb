---
title: "Matplotlib Quick Start"
tags:
  - kb
  - raw
  - source
  - external
  - viz-deep
  - matplotlib
  - python
aliases: []
kind: raw-source
status: active
updated: 2026-04-14
source_url: https://matplotlib.org/stable/users/explain/quick_start.html
capture_type: markdown-extract
---

# Matplotlib Quick Start

## Source Record
| Field | Value |
|-------|-------|
| URL | `https://matplotlib.org/stable/users/explain/quick_start.html` |
| Owner | Matplotlib project |
| Scope | Quick-start tutorial covering figures, axes, styles, labels, scales, and plotting patterns |
| Why it matters to nbadb | Matplotlib remains a baseline Python visualization tool for exploratory analysis, scripts, and static artifact generation |

## Summary
Matplotlib's quick-start guide explains the library's core mental model: figures contain axes, axes own most plotting behavior, and artists render visible elements. It also recommends the object-oriented style for reusable or complex plots while still documenting pyplot for quick work.

## Key Points
- The guide centers the Figure, Axes, Axis, and Artist model.
- `plt.subplots()` is the main entrypoint for creating figure-plus-axes structures.
- The documentation distinguishes explicit object-oriented usage from implicit pyplot usage and recommends OO for larger code.
- It covers styling, labels, annotations, legends, scales, ticks, color mapping, and multiple axes.
- It notes that string and date inputs are supported but can produce surprising categorical behavior if types are wrong.

## nbadb Relevance
- Useful for internal analysis scripts, QA plots, and exported static figures.
- The OO recommendation matches maintainable code patterns for reusable chart helpers.
- Colorbars, secondary axes, and categorical/date handling matter for sports analytics use cases.
- Helps frame when a simple Python-native static chart is preferable to a heavier interactive stack.

## Notable Sections
- A simple example
- Parts of a Figure
- Coding styles
- Styling Artists
- Labelling plots
- Axis scales and ticks
- Color mapped data
- Working with multiple Figures and Axes

## Provenance
- Fetched from `https://matplotlib.org/stable/users/explain/quick_start.html` via `trafilatura` extraction on `2026-04-14`
