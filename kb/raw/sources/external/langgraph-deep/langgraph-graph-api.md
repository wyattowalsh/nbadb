---
title: LangGraph Graph API Overview
kind: raw-source
status: captured
source_url: https://langchain-ai.github.io/langgraph/concepts/low_level/
captured_on: 2026-04-14
capture_type: webfetch-markdown-via-docs-index
why_it_matters: Captures the current LangGraph low-level execution model: state, nodes, edges, reducers, commands, and graph compilation semantics.
---

## Source Record

- Source URL: `https://langchain-ai.github.io/langgraph/concepts/low_level/`
- Fetch method: `webfetch` on the requested URL, then `webfetch` on resolved page `https://docs.langchain.com/oss/python/langgraph/graph-api`
- Capture date: `2026-04-14`

## Why It Matters

This is the core runtime contract for how LangGraph executes agent workflows. It defines the graph primitives that matter downstream for any durable agent runtime: shared state, reducer behavior, node signatures, command-driven control flow, and recursion handling.

## Key Excerpts

> "At its core, LangGraph models agent workflows as graphs."

> "nodes do the work, edges tell what to do next"

> "You **MUST** compile your graph before you can use it."

> `Command` can combine `update`, `goto`, `graph`, and `resume`, making it the central control primitive for routing, state mutation, and interrupt resumption.

## Capture Notes

- The original `concepts/low_level` URL now redirects into the new Mintlify docs structure.
- The replacement page is the real low-level reference; it covers `StateGraph`, reducers, `MessagesState`, conditional edges, `Send`, `Command`, and runtime context.
- It also documents recursion-limit behavior and managed `RemainingSteps`, which are important for long-running agent safety.
