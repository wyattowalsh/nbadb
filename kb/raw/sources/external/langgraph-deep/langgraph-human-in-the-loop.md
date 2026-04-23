---
title: LangGraph Interrupts and Human-in-the-Loop
kind: raw-source
status: captured
source_url: https://langchain-ai.github.io/langgraph/concepts/human_in_the_loop/
captured_on: 2026-04-14
capture_type: webfetch-markdown-via-docs-index
why_it_matters: Captures the runtime pause-and-resume model for human approval, review, validation, and tool-call gating in LangGraph.
---

## Source Record

- Source URL: `https://langchain-ai.github.io/langgraph/concepts/human_in_the_loop/`
- Fetch method: `webfetch` on the requested URL, then `webfetch` on resolved page `https://docs.langchain.com/oss/python/langgraph/human-in-the-loop`
- Capture date: `2026-04-14`

## Why It Matters

This page defines LangGraph's human-in-the-loop runtime semantics. It explains how `interrupt()` pauses execution, why checkpointing and `thread_id` are mandatory, how `Command(resume=...)` continues execution, and what safety rules apply when nodes restart from the top.

## Key Excerpts

> "Interrupts allow you to pause graph execution at specific points and wait for external input before continuing."

> "The `thread_id` you choose is effectively your persistent cursor."

> "The node restarts from the beginning of the node where the `interrupt` was called when resumed"

> The docs explicitly warn not to wrap `interrupt()` in bare `try/except`, reorder interrupts nondeterministically, or perform non-idempotent side effects before an interrupt.

## Capture Notes

- The current page title is `Interrupts`, but it is the effective replacement for the older human-in-the-loop concept URL.
- The most important operational detail is replay behavior: resumed nodes rerun from the start, so pre-interrupt code must be safe to replay.
- The page also covers approval flows, multi-interrupt resume maps, in-tool interrupts, validation loops, and static breakpoints for debugging.
