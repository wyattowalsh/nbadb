---
title: LangChain Introduction
kind: raw-source
status: captured
source_url: https://python.langchain.com/docs/introduction/
captured_on: 2026-04-14
capture_type: webfetch-markdown
why_it_matters: Captures LangChain's top-level positioning and product boundaries for agent construction, especially its relationship to LangGraph, Deep Agents, tools, and model integrations.
---

## Source Record

- Source URL: `https://python.langchain.com/docs/introduction/`
- Fetch method: `webfetch` in markdown mode
- Capture date: `2026-04-14`

## Why It Matters

This page is the clearest upstream statement of what LangChain is for: rapid agent construction on top of model and tool integrations, with LangGraph providing the underlying runtime features such as durability, streaming, persistence, and human-in-the-loop control.

## Key Excerpts

> "LangChain is an open source framework with a prebuilt agent architecture and integrations for any model or tool"

> "If you are looking to build an agent, we recommend you start with Deep Agents"

> "Use LangGraph ... when you have more advanced needs that require a combination of deterministic and agentic workflows and heavy customization."

> LangChain's `create_agent` example shows a minimal tool-wrapped agent built in a few lines with a provider-qualified model string.

## Capture Notes

- The fetched page is a concise overview and routing page rather than a deep API contract.
- The most useful signal is the product boundary it draws between LangChain, LangGraph, and Deep Agents.
- The page also points to `docs.langchain.com/llms.txt` as the full docs index.
