---
title: Fumadocs MDX Getting Started
kind: raw-source
status: captured
source_url: https://fumadocs.dev/docs/mdx
captured_on: 2026-04-14
capture_type: webfetch-markdown-summary
why_it_matters: Explains the content-processing layer that turns MDX and metadata files into typed docs data for the app.
---

## Source Record

- Source URL: `https://fumadocs.dev/docs/mdx`
- Fetch method: `webfetch` in markdown mode
- Capture date: `2026-04-14`

## Why It Matters

This page explains the MDX/content side of the docs stack. It shows that Fumadocs MDX is not a CMS, but a typed content-processing layer that builds collections for docs pages, metadata, TOCs, structured data, and other derived outputs.

## Key Excerpts

> "Fumadocs MDX is a tool to transform content into type-safe data, similar to Content Collections."

> "It is not a full CMS but rather a content processing layer for React frameworks..."

> "Combination of `meta` and `doc` collections, which is needed for Fumadocs."

> "These properties are exported from MDX files by default: `frontmatter`, `toc`, `structuredData`, `extractedReferences`."

## Capture Notes

- The most useful upstream details are the `doc`, `meta`, and `docs` collection types.
- The page also confirms that frontmatter/schema validation and MDX compiler customization are first-class extension points.
- This is the most directly relevant source for how authored docs content becomes typed runtime data.
