---
title: LangGraph Persistence
kind: raw-source
status: captured
source_url: https://langchain-ai.github.io/langgraph/concepts/persistence/
captured_on: 2026-04-14
capture_type: webfetch-markdown-via-docs-index
why_it_matters: Captures LangGraph's checkpointing model, thread semantics, state snapshots, replay behavior, and cross-thread store abstractions.
---

## Source Record

- Source URL: `https://langchain-ai.github.io/langgraph/concepts/persistence/`
- Fetch method: `webfetch` on the requested URL, then `webfetch` on resolved page `https://docs.langchain.com/oss/python/langgraph/persistence`
- Capture date: `2026-04-14`

## Why It Matters

Persistence is the runtime layer that makes durable agents possible. This page defines how LangGraph saves checkpoints, resumes interrupted threads, exposes state history, and separates thread-local checkpointing from cross-thread store-backed memory.

## Key Excerpts

> "LangGraph has a built-in persistence layer that saves graph state as checkpoints."

> "When invoking a graph with a checkpointer, you **must** specify a `thread_id` as part of the `configurable` portion of the config"

> "Checkpointers allow for \"time travel\""

> The store exists because checkpointers alone cannot share information across threads; cross-thread memory uses `Store`, not thread checkpoints.

## Capture Notes

- The old persistence concept URL now resolves into the new docs site.
- The current page gives the clearest checkpoint contract: `thread_id`, `checkpoint_id`, `StateSnapshot`, `get_state`, `get_state_history`, replay, and `update_state`.
- It also documents production checkpointer options (`sqlite`, `postgres`, `cosmosdb`) plus serializer and encryption hooks.
