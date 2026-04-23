---
title: Next.js Open Graph Image Conventions
kind: raw-source
status: captured
source_url: https://nextjs.org/docs/app/api-reference/file-conventions/metadata/opengraph-image
captured_on: 2026-04-14
capture_type: webfetch-markdown-summary
why_it_matters: Captures the App Router metadata-image conventions for static and generated Open Graph and Twitter images, including route-handler behavior and metadata exports.
---

## Source Record

- Source URL: `https://nextjs.org/docs/app/api-reference/file-conventions/metadata/opengraph-image`
- Fetch method: `webfetch` in markdown mode
- Capture date: `2026-04-14`

## Why It Matters

This page defines how social preview images are attached to route segments in Next.js, either as literal assets or generated code. It matters because docs pages often need route-specific share images, alt text, and static or dynamic image generation semantics.

## Key Excerpts

> "The `opengraph-image` and `twitter-image` file conventions allow you to set Open Graph and Twitter images for a route segment."

> "By default, generated images are statically optimized."

> "`opengraph-image` and `twitter-image` are specialized Route Handlers."

## Capture Notes

- Static file conventions support image files plus `.alt.txt` companions for accessibility metadata.
- Generated images export `alt`, `size`, and `contentType`, and typically return `new ImageResponse(...)` from `next/og`.
- The page also documents promised `params` for dynamic image routes and notes external-data and local-asset patterns.
