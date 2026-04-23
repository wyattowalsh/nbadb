---
title: Web Context Tools
tags:
  - kb
  - topics
  - chat
  - tools
  - web
  - security
aliases:
  - Web Search And Fetch Tools
  - Web Context Helpers
kind: concept
status: active
updated: 2026-04-22
source_count: 7
---

# Web Context Tools

This note covers the local web-context lane for the chat runtime.

## Split
The canonical implementations live in:
- `src/nbadb/chat/web/search.py`
- `src/nbadb/chat/web/fetch.py`

The app-local `chat/server/tools/*` modules are compatibility wrappers over those shared implementations.

## Tool pair
### `web_search`
`src/nbadb/chat/web/search.py` provides the lightweight search tool used for discovery-oriented live context.

Its behavior is intentionally simple:
- DuckDuckGo backend
- small hit list
- flattened markdown-style output rather than structured JSON

### `web_fetch`
`src/nbadb/chat/web/fetch.py` provides the guarded text-fetch lane.

Its job is not generic browsing. It is a public-web-only fetcher with:
- scheme and hostname checks
- private-network and loopback blocking
- redirect validation
- content-type filtering
- sanitized error returns

## Runtime attachment
These tools are not universally attached.

They are added only when:
- the deepagents backend is active
- `settings.web_context` is enabled

That attachment happens in `src/nbadb/chat/app/agent.py`.

The Copilot path does not attach this local tool pair directly.

## Practical role
Use this lane only when warehouse-backed data is insufficient and current external NBA context actually matters, such as:
- injuries
- trades
- live breaking context the warehouse has not modeled yet

It supplements warehouse truth. It does not replace it.

## Related notes
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/prompt-assembly-and-capabilities|Prompt Assembly And Capabilities]]
- [[wiki/topics/query-safety|Query Safety]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| canonical web-search implementation | `src/nbadb/chat/web/search.py` | shared search tool |
| canonical guarded web-fetch implementation | `src/nbadb/chat/web/fetch.py` | shared fetch tool and SSRF boundary |
| app-local wrapper layer | `chat/server/tools/web_search.py`; `chat/server/tools/web_fetch.py` | compatibility surface |
| deepagents-only attachment and `settings.web_context` gating | `src/nbadb/chat/app/agent.py` | concrete runtime attachment |
| `web_context` settings field | `src/nbadb/chat/runtime/settings.py` | user-visible runtime toggle |
| prompt-level advertisement of the web tool family | `src/nbadb/chat/prompts.py` | workflow framing |
| current test-backed behavior | `tests/unit/chat/test_web_tools.py` | live behavior guardrails |
