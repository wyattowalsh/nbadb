---
title: shadcn/ui Table
kind: raw-source
status: captured
source_url: https://ui.shadcn.com/docs/components/table
captured_on: 2026-04-15
capture_type: webfetch-markdown-summary
why_it_matters: Captures the base table component that docs-admin surfaces can use directly or pair with TanStack Table for richer data-grid behavior.
---

## Source Record

- Source URL: `https://ui.shadcn.com/docs/components/table`
- Fetch method: `webfetch` in markdown mode
- Capture date: `2026-04-15`

## Why It Matters

This page defines the baseline shadcn table primitives for rendering structured records in admin-facing views. It is especially useful because it also points directly to the heavier TanStack Table path for sorting, filtering, and pagination.

## Key Excerpts

> "A responsive table component."

> "pnpm dlx shadcn@latest add table"

> "Use the following composition to build a `Table`:"

> "Combine it with [@tanstack/react-table](https://tanstack.com/table/v8) to create tables with sorting, filtering and pagination."

## Capture Notes

- The current page body presents the component under the newer Radix/Base split while preserving the simple `@/components/ui/table` import surface.
- The most decision-relevant detail is that the primitive stays intentionally small and delegates advanced data-grid behavior to TanStack Table.
- The page includes installation, usage, composition, examples, and RTL support in one place.
