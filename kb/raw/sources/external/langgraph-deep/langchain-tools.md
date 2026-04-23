---
title: LangChain Tools
kind: raw-source
status: captured
source_url: https://python.langchain.com/docs/concepts/tools/
captured_on: 2026-04-14
capture_type: webfetch-markdown-via-docs-index
why_it_matters: Captures the current LangChain tool contract, including schema definition, ToolRuntime access, ToolNode behavior, and state-mutating tool patterns.
---

## Source Record

- Source URL: `https://python.langchain.com/docs/concepts/tools/`
- Fetch method: `webfetch` on the requested URL, then `webfetch` on resolved page `https://docs.langchain.com/oss/python/langchain/tools`
- Capture date: `2026-04-14`

## Why It Matters

Tools are the main bridge between model reasoning and external action. This page captures how LangChain defines tools, how schemas are inferred, how tools access runtime state and memory, and how `ToolNode` executes tools inside LangGraph-backed agents.

## Key Excerpts

> "Tools extend what agents can do"

> "Under the hood, tools are callable functions with well-defined inputs and outputs that get passed to a chat model"

> "Type hints are **required** as they define the tool's input schema."

> `ToolRuntime` exposes state, context, store, stream writer, execution info, server info, config, and the tool call ID.

## Capture Notes

- The old concepts URL now routes through the consolidated docs site; the current tools page is fetchable directly.
- The page is especially relevant for agent runtime work because it ties together `@tool`, `ToolRuntime`, `Command`, and `ToolNode`.
- It also documents reserved parameter names, reducer guidance for parallel tool updates, and the distinction between local tools and provider-side server tools.
