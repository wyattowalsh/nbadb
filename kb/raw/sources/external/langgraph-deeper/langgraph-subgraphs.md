---
title: LangGraph Subgraphs
kind: raw-source
status: captured
source_url: https://langchain-ai.github.io/langgraph/concepts/subgraphs/
captured_on: 2026-04-15
capture_type: webfetch-markdown-via-redirect
why_it_matters: Captures how LangGraph composes parent graphs and subgraphs, including schema-sharing patterns, persistence modes, namespace isolation, and streamed subgraph outputs.
---

## Source Record

- Source URL: `https://langchain-ai.github.io/langgraph/concepts/subgraphs/`
- Fetch method: `webfetch` on the requested URL, then `webfetch` on resolved page `https://docs.langchain.com/oss/python/langgraph/use-subgraphs`
- Capture date: `2026-04-15`

## Why It Matters

Subgraphs are LangGraph's composition primitive for reusable workflows and multi-agent systems. This page explains the two integration patterns, how persistence changes subgraph memory behavior, and where namespace conflicts appear when stateful subgraphs are invoked repeatedly.

## Key Excerpts

> "A subgraph is a graph that is used as a node in another graph."

> "Call a subgraph inside a node" when parent and subgraph have different state schemas.

> "Add a subgraph as a node" when parent and subgraph share state keys.

> "Per-thread subgraphs do not support parallel tool calls."

## Capture Notes

- The old concept URL resolves to `use-subgraphs` on the new docs site.
- The page's most important distinction is between wrapper-node invocation for schema translation and direct `add_node(subgraph)` composition for shared channels.
- Subgraph persistence has three modes: per-invocation (`None`), per-thread (`True`), and stateless (`False`).
- The per-thread mode introduces checkpoint namespace and parallel-call constraints that matter for agent tool wrappers.
