---
title: LangGraph Functional API Overview
kind: raw-source
status: captured
source_url: https://langchain-ai.github.io/langgraph/concepts/functional_api/
captured_on: 2026-04-15
capture_type: webfetch-markdown-via-redirect
why_it_matters: Captures the current Functional API contract for layering persistence, tasks, interrupts, and streaming onto ordinary Python control flow without rewriting an application as an explicit graph.
---

## Source Record

- Source URL: `https://langchain-ai.github.io/langgraph/concepts/functional_api/`
- Fetch method: `webfetch` on the requested URL, then `webfetch` on resolved page `https://docs.langchain.com/oss/python/langgraph/functional-api`
- Capture date: `2026-04-15`

## Why It Matters

The Functional API is the clearest upstream reference for adding LangGraph durability features without fully adopting `StateGraph`. It defines `@entrypoint`, `@task`, resumability, short-term memory via `previous`, and the determinism rules that keep replay safe.

## Key Excerpts

> "The Functional API allows you to add LangGraph's key features ... to your applications with minimal changes to your existing code."

> "The Functional API uses two key building blocks: `@entrypoint` ... and `@task`"

> "The function must accept a single positional argument, which serves as the workflow input."

> "any randomness should be encapsulated inside of tasks"

## Capture Notes

- The legacy concept URL now redirects to the new docs site.
- The page positions Functional API and Graph API as different front doors over the same runtime.
- `@entrypoint` creates a `Pregel` executable and usually needs a checkpointer plus `thread_id` for persistence and interrupts.
- The strongest operational guidance is around JSON-serializable inputs and outputs, task encapsulation, and deterministic replay.
