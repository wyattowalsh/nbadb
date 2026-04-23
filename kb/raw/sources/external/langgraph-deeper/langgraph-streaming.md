---
title: LangGraph Streaming
kind: raw-source
status: captured
source_url: https://langchain-ai.github.io/langgraph/concepts/streaming/
captured_on: 2026-04-15
capture_type: webfetch-markdown-via-redirect
why_it_matters: Captures LangGraph's current streaming contract, including stream modes, unified v2 output shape, subgraph namespaces, and checkpoint or task event streaming.
---

## Source Record

- Source URL: `https://langchain-ai.github.io/langgraph/concepts/streaming/`
- Fetch method: `webfetch` on the requested URL, then `webfetch` on resolved page `https://docs.langchain.com/oss/python/langgraph/streaming`
- Capture date: `2026-04-15`

## Why It Matters

Streaming is the main runtime surface for exposing LangGraph execution in real time. This page defines the current stream modes, the `version="v2"` `StreamPart` shape, how token streams and custom events work, and how parent graphs surface subgraph activity.

## Key Excerpts

> "LangGraph implements a streaming system to surface real-time updates."

> "Pass `version="v2"` to `stream()` or `astream()` to get a unified output format."

> "Every chunk is a `StreamPart` dict with a consistent shape"

> "Use the `messages` streaming mode to stream Large Language Model (LLM) outputs token by token from any part of your graph"

## Capture Notes

- The legacy `langchain-ai.github.io` concept URL now redirects into the Mintlify docs site.
- The current page centers on the v2 contract: each stream chunk has `type`, `ns`, and `data`, even when combining multiple modes or subgraphs.
- The most relevant modes for runtime integration are `updates`, `values`, `messages`, `custom`, `checkpoints`, `tasks`, and `debug`.
- Subgraph streaming is now explicitly namespaced through the `ns` field rather than only tuple-based v1 outputs.
