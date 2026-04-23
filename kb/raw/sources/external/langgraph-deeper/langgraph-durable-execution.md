---
title: LangGraph Durable Execution
kind: raw-source
status: captured
source_url: https://langchain-ai.github.io/langgraph/concepts/durable_execution/
captured_on: 2026-04-15
capture_type: webfetch-markdown-via-redirect
why_it_matters: Captures LangGraph's durable execution model, including checkpointer requirements, replay semantics, durability modes, and constraints around deterministic or idempotent workflow design.
---

## Source Record

- Source URL: `https://langchain-ai.github.io/langgraph/concepts/durable_execution/`
- Fetch method: `webfetch` on the requested URL, then `webfetch` on resolved page `https://docs.langchain.com/oss/python/langgraph/durable-execution`
- Capture date: `2026-04-15`

## Why It Matters

Durable execution is the core runtime guarantee behind LangGraph's pause, resume, and failure-recovery model. This page defines what must be present for durability to work, how replay actually resumes, and which persistence mode trades off performance versus checkpoint safety.

## Key Excerpts

> "Durable execution is a technique in which a process or workflow saves its progress at key points, allowing it to pause and later resume exactly where it left off."

> "If you are using LangGraph with a checkpointer, you already have durable execution enabled."

> "When you resume a workflow run, the code does NOT resume from the same line of code"

> "Wrap any non-deterministic operations ... or operations with side effects ... inside tasks"

## Capture Notes

- The old concept URL now resolves into the current `docs.langchain.com` durable execution page.
- The page makes clear that durability depends on three things: a checkpointer, a `thread_id`, and isolating side effects or randomness into tasks.
- Replay semantics are checkpoint-based, not stack-frame-based; resume starts from the relevant entrypoint or node boundary.
- The durability modes are `exit`, `async`, and `sync`, with `sync` providing the strongest checkpoint guarantee and highest overhead.
