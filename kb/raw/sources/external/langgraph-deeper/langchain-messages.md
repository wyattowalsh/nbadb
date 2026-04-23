---
title: LangChain Messages
kind: raw-source
status: captured
source_url: https://python.langchain.com/docs/concepts/messages/
captured_on: 2026-04-15
capture_type: webfetch-markdown-via-redirect
why_it_matters: Captures LangChain's standard message model, including message roles, AI and tool message metadata, content blocks, multimodal payloads, and conversation-state representation.
---

## Source Record

- Source URL: `https://python.langchain.com/docs/concepts/messages/`
- Fetch method: `webfetch` on the requested URL, then `webfetch` on resolved page `https://docs.langchain.com/oss/python/langchain/messages`
- Capture date: `2026-04-15`

## Why It Matters

Messages are the shared data contract between LangChain chat models, tools, and agents. This page defines the role model, explains `AIMessage` and `ToolMessage` semantics, and documents how multimodal and structured content blocks are normalized across providers.

## Key Excerpts

> "Messages are the fundamental unit of context for models in LangChain."

> "LangChain provides a standard message type that works across all model providers"

> "An `AIMessage` represents the output of a model invocation."

> "Tool messages are used to pass the results of a single tool execution back to the model."

## Capture Notes

- The old `python.langchain.com` page redirects to the new docs site.
- The page distinguishes three input styles: plain strings, message objects, and OpenAI-style role dictionaries.
- The most operationally important sections are `AIMessage.tool_calls`, `usage_metadata`, `AIMessageChunk`, and `ToolMessage.tool_call_id` matching.
- `content_blocks` is now the standard provider-normalized representation for text, reasoning, multimodal data, and tool-call payloads.
