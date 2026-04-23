---
title: Next.js Server and Client Components
kind: raw-source
status: captured
source_url: https://nextjs.org/docs/app/building-your-application/rendering/client-components
captured_on: 2026-04-14
capture_type: webfetch-markdown-summary
why_it_matters: Captures the current Next.js guidance for client-component boundaries, server-client composition, hydration, and bundle-size tradeoffs; the requested URL now resolves to the newer server-and-client-components page.
---

## Source Record

- Source URL: `https://nextjs.org/docs/app/building-your-application/rendering/client-components`
- Fetch method: `webfetch` in markdown mode
- Capture date: `2026-04-14`

## Why It Matters

This is the canonical runtime explanation for where `'use client'` boundaries belong in a Next.js App Router app. It matters because docs UI often mixes server-rendered layout/content with client-only search, navigation, theming, and third-party interactive components.

## Key Excerpts

> "By default, layouts and pages are Server Components."

> "`'use client'` is used to declare a boundary between the Server and Client module graphs."

> "To reduce the size of your client JavaScript bundles, add `'use client'` to specific interactive components instead of marking large parts of your UI as Client Components."

## Capture Notes

- The requested URL resolved to the current page titled `Server and Client Components`, indicating the older path has been consolidated.
- The page explains first-load rendering in terms of HTML, the RSC payload, and hydration, then contrasts that with subsequent navigations.
- It also covers provider placement, interleaving server content inside client shells, and `server-only` or `client-only` guards against environment poisoning.
