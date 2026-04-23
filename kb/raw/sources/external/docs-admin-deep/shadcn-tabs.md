---
title: shadcn/ui Tabs
kind: raw-source
status: captured
source_url: https://ui.shadcn.com/docs/components/tabs
captured_on: 2026-04-15
capture_type: webfetch-markdown-summary
why_it_matters: Captures the tabbed layout primitive that docs-admin pages can use to switch between overview, analytics, reports, and settings views without leaving the page.
---

## Source Record

- Source URL: `https://ui.shadcn.com/docs/components/tabs`
- Fetch method: `webfetch` in markdown mode
- Capture date: `2026-04-15`

## Why It Matters

Tabs are a likely primitive for docs-admin screens that need to segment related content panels without adding route depth. This page shows the base API, composition, and a few style and orientation variants that are directly relevant for an admin UI.

## Key Excerpts

> "A set of layered sections of content-known as tab panels-that are displayed one at a time."

> "pnpm dlx shadcn@latest add tabs"

> "Use the following composition to build `Tabs`:"

> "See the [Radix Tabs](https://www.radix-ui.com/docs/primitives/components/tabs#api-reference) documentation."

## Capture Notes

- The page exposes a minimal import surface: `Tabs`, `TabsContent`, `TabsList`, and `TabsTrigger`.
- The examples most relevant to docs-admin work are `variant=\"line\"` for a lighter visual treatment and `orientation=\"vertical\"` for sidebar-like panel navigation.
- The page includes RTL and upstream Radix API-reference links, which helps distinguish the shadcn wrapper surface from the underlying primitive behavior.
