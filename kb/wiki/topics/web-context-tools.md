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
updated: 2026-04-15
source_count: 7
---

# Web Context Tools

This note covers the two local web helpers under `chat/server/tools/`: `web_search.py` and `web_fetch.py`.

They are small LangChain-style `@tool` functions used only on the deepagents assembly path. Together they give the chat agent a minimal external-context lane: DuckDuckGo search for discovery, then guarded fetch-and-extract for page text.

## Tool pair

### `web_search`
`chat/server/tools/web_search.py` exposes a single `web_search(query: str) -> str` tool.

Its runtime contract is:
- backend: `duckduckgo_search.DDGS`
- query call: `ddgs.text(query, max_results=5)`
- expected hit shape: `title`, `href`, and `body`
- output shape: a single Markdown string, one hit per block
- block format: `**{title}**`, then URL, then snippet body
- separator: `\n---\n`
- empty case: returns `No results found.`

Important nuance: this tool does not return structured JSON to the model. It flattens DDG hits into presentation-oriented Markdown text immediately.

### `web_fetch`
`chat/server/tools/web_fetch.py` exposes `web_fetch(url: str) -> str`.

Its runtime contract is:
- only `http` and `https` URLs are allowed
- fetches with `httpx.get(...)` using `follow_redirects=False`
- timeout is `15.0` seconds
- user agent is `nbadb-chat/1.0`
- text extraction uses `trafilatura.extract(response.text)`
- fallback is the first `10000` characters of `response.text`
- final output is capped at `10000` characters

## SSRF and private-network blocking
The core guardrail is `_is_safe_url(url)`, which is called before the initial fetch and again on every redirect target.

### Validation rules
- rejects any non-`http` or non-`https` scheme
- rejects URLs with no hostname
- rejects direct IP literals that fall into blocked networks
- resolves hostnames with `socket.getaddrinfo(...)` and rejects the URL if any resolved address is blocked

### Blocked network families
The denylist includes:
- RFC1918 private IPv4: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
- link-local and metadata-adjacent IPv4: `169.254.0.0/16`
- loopback IPv4: `127.0.0.0/8`
- carrier-grade NAT: `100.64.0.0/10`
- IPv4 current/reserved/benchmark ranges: `0.0.0.0/8`, `198.18.0.0/15`, `240.0.0.0/4`
- IPv6 loopback: `::1/128`
- IPv4-mapped IPv6: `::ffff:0:0/96`
- IPv6 private and link-local: `fc00::/7`, `fe80::/10`

Operationally, this makes `web_fetch` an SSRF-resistant public-web fetcher, not a generic URL reader.

## Redirect validation
Redirect handling is explicit rather than delegated to `httpx`.

Flow:
1. fetch current URL with redirects disabled
2. if response is a redirect, read `Location`
3. run `_is_safe_url(location)` on that redirect target
4. repeat until a non-redirect response or the hop budget is exhausted

Current redirect policy details:
- maximum redirect chain: 3 hops
- fourth redirect returns `Too many redirects`
- redirect targets must themselves pass the same public-network validation
- relative redirect locations are effectively rejected, because `_is_safe_url(...)` requires a hostname and the code does not resolve relative `Location` headers against the prior URL

That last point is an implementation detail worth remembering: the tool currently accepts only absolute redirect targets.

## Content-type gating
`web_fetch` refuses to run text extraction on clearly non-text responses.

Accepted content types are any header containing:
- `text/`
- `application/json`
- `application/xml`

All other types are rejected before extraction with:
- `Cannot extract text from content-type: <mime>`

This means the tool is intentionally text-first. It will not read PDFs, images, archives, or arbitrary binary payloads through the current path.

## Error surface
The tool returns sanitized string errors rather than raising raw exceptions into the agent layer.

Examples:
- `URL blocked: ...`
- `Redirect blocked: ...`
- `Too many redirects`
- `Failed to fetch URL: <HTTPErrorType>`

Notably, the fetch failure path exposes only the exception class name, not the original exception message. The unit tests explicitly verify that internal addresses and low-level connection details are not leaked back through the tool output.

## Agent assembly
These tools enter the assembled agent in three distinct layers.

### Prompt layer
`src/nbadb/chat/prompts.py` lists `web_search` and `web_fetch` in the base tool inventory inside the shared system prompt.

### Capability layer
`src/nbadb/chat/runtime/capabilities.py` includes `web_search: bool = True` on `CapabilityManifest`.

### Concrete tool attachment
The actual callable tools are wired only in `chat/server/agent.py`:
- `_create_deepagents_agent(...)` imports `web_search` and `web_fetch`
- it builds `local_tools = [web_search, web_fetch] if settings.web_context else []`
- it passes `[*local_tools, *mcp_tools]` into `create_deep_agent(...)`

Implication:
- deepagents backend + `settings.web_context=True`: tools are attached
- deepagents backend + `settings.web_context=False`: tools are omitted
- Copilot backend: these local web tools are not attached on the current assembly path

So the prompt and capability surfaces advertise web context broadly, but the concrete local implementation is currently a deepagents-only, settings-gated attachment.

## Related notes
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/prompt-assembly-and-capabilities|Prompt Assembly And Capabilities]]
- [[wiki/topics/query-agent|Query Agent]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| `web_search` DDG call shape, hit fields, and Markdown formatting | `chat/server/tools/web_search.py` | canonical implementation |
| URL safety validator, blocked network ranges, redirect loop, content-type gate, extraction cap, and sanitized fetch errors | `chat/server/tools/web_fetch.py` | canonical implementation |
| SSRF, redirect, content-type, and error-sanitization expectations | `tests/unit/chat/test_web_tools.py` | behavioral confirmation |
| deepagents-only import and `settings.web_context` gating in assembled agent | `chat/server/agent.py` | canonical assembly path |
| `web_context` default and runtime settings surface | `src/nbadb/chat/runtime/settings.py` | settings contract |
| prompt-level advertisement of `web_search` and `web_fetch` | `src/nbadb/chat/prompts.py` | shared system prompt inventory |
| capability-level advertisement of web search support | `src/nbadb/chat/runtime/capabilities.py` | manifest contract |
