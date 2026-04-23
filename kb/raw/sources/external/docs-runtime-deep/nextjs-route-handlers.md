---
title: Next.js Route Handlers
kind: raw-source
status: captured
source_url: https://nextjs.org/docs/app/api-reference/file-conventions/route
captured_on: 2026-04-14
capture_type: webfetch-markdown-summary
why_it_matters: Captures the App Router route-handler contract for HTTP methods, typed params, caching, streaming, and non-UI responses that underpin API endpoints in a Next.js docs app.
---

## Source Record

- Source URL: `https://nextjs.org/docs/app/api-reference/file-conventions/route`
- Fetch method: `webfetch` in markdown mode
- Capture date: `2026-04-14`

## Why It Matters

This is the core runtime reference for API-style endpoints in the App Router. It defines how `route.ts` files receive `Request` and promised `params`, which HTTP methods exist, and how segment config, caching, streaming, and non-HTML responses behave.

## Key Excerpts

> "Route Handlers allow you to create custom request handlers for a given route using the Web Request and Response APIs."

> "The following HTTP methods are supported: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `HEAD`, and `OPTIONS`."

> "Route Handlers use the same route segment configuration as pages and layouts."

## Capture Notes

- `context.params` is now promise-based, and the page calls out `RouteContext<'/users/[id]'>` as the typed helper.
- The examples cover cookies, headers, CORS, webhooks, streaming, and RSS-style non-UI responses.
- Version history notes two important behavior changes in v15 RC: promised params and `GET` shifting from static to dynamic by default.
