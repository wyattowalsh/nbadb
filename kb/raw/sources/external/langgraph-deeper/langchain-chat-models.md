---
title: LangChain Chat Models
kind: raw-source
status: captured
source_url: https://python.langchain.com/docs/concepts/chat_models/
captured_on: 2026-04-15
capture_type: webfetch-markdown-via-redirect
why_it_matters: Captures LangChain's current standard model interface, including initialization, invocation, streaming, batching, tool calling, structured output, and model capability metadata.
---

## Source Record

- Source URL: `https://python.langchain.com/docs/concepts/chat_models/`
- Fetch method: `webfetch` on the requested URL, then `webfetch` on resolved page `https://docs.langchain.com/oss/python/langchain/models`
- Capture date: `2026-04-15`

## Why It Matters

This page is the current upstream contract for how LangChain wants applications to talk to chat models. It defines the standard interface (`init_chat_model`, `invoke`, `stream`, `batch`), shows how tools and structured output layer onto that interface, and documents runtime capability surfaces like profiles and multimodal content.

## Key Excerpts

> "Models are the reasoning engine of agents."

> "The easiest way to get started with a standalone model in LangChain is to use `init_chat_model`"

> "The same model interface works in both contexts"

> "Each provider package implements the same standard interface, so you can swap providers without rewriting application logic."

## Capture Notes

- The requested `python.langchain.com` concept URL now redirects to the new docs site and the page title is simply `Models`.
- The page treats `invoke`, `stream`, and `batch` as the primary execution methods and then layers tool calling and structured output on top.
- `init_chat_model` is the canonical cross-provider entrypoint, with provider-specific classes still shown as direct alternatives.
- The page also introduces `profile` as a capability surface for model-aware routing and feature gating.
