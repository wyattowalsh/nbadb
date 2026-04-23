---
title: LangChain Prompt Templates URL Stub
kind: raw-source
status: stub
source_url: https://python.langchain.com/docs/concepts/prompt_templates/
captured_on: 2026-04-14
capture_type: redirect-collapsed-to-overview-stub
why_it_matters: Records that the requested prompt-templates concept URL no longer resolves to a dedicated concept page in the current LangChain docs surface.
---

## Source Record

- Source URL: `https://python.langchain.com/docs/concepts/prompt_templates/`
- Fetch method: `webfetch` in markdown mode, then `trafilatura` retry, plus docs-index lookup for a current replacement
- Capture date: `2026-04-14`

## Why It Matters

Prompt-template concepts matter for agent runtime composition, but this exact legacy URL no longer returns a dedicated prompt-template page. Tracking that break helps distinguish a moved source from a missed capture.

## Key Excerpts

> Direct fetches of the exact URL resolved to the generic `LangChain overview` page instead of prompt-template content.

> The current `docs.langchain.com/llms.txt` index exposed a `Tools` page but did not expose an equivalent `oss/python/langchain/...` prompt-templates concept page.

## Capture Notes

- `webfetch` and `trafilatura` both collapsed to the overview page rather than prompt-template material.
- A docs-index and search pass did not surface a clear current replacement in the new LangChain Python concept docs.
- This note is intentionally a stub so the broken or migrated source remains tracked for later manual resolution.
