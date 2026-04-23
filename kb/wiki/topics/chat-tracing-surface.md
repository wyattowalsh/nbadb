---
title: Chat Tracing Surface
tags:
  - kb
  - topics
  - chat
  - tracing
  - runtime
aliases:
  - Chat Tracing Setup
  - Chat Tracing Providers
kind: concept
status: active
updated: 2026-04-15
source_count: 5
---

# Chat Tracing Surface

This note captures the tracing setup contract shared by `src/nbadb/chat/tracing.py`, the app-local shim in `chat/server/tracing.py`, the `ChatSettings` runtime model, and the current unit-test coverage.

## Surface map
| Surface | Owned by | Role |
| --- | --- | --- |
| `setup_tracing(settings)` | `src/nbadb/chat/tracing.py` | canonical tracing setup entrypoint |
| `_tracing_lock` | `src/nbadb/chat/tracing.py` | serializes tracing setup and env mutation |
| `ChatSettings` tracing fields | `src/nbadb/chat/runtime/settings.py` | runtime knobs and persisted/env-loaded values |
| app wrapper | `chat/server/tracing.py` | compatibility import surface for app code and tests |
| unit coverage | `tests/unit/chat/test_tracing.py` | verifies defaults, env mutation, and warning/fallback branches |

## Setup contract
`setup_tracing(settings)` is lock-guarded.

The public function acquires `_tracing_lock` and then delegates to `_setup_tracing_inner(settings)`. That means provider selection, optional imports, and any direct `os.environ` mutation happen one caller at a time.

What the function returns:
- `[]` when tracing is disabled, unsupported, misconfigured, or handled purely by env-based auto-instrumentation
- `[CallbackHandler(...)]` only for a successful Langfuse setup

## Runtime settings
`ChatSettings` owns these tracing fields:
- `trace_capture: bool = False`
- `tracing_provider: str = "none"`
- `langfuse_host: str | None = None`
- `langfuse_public_key: SecretStr | None = None`
- `langfuse_secret_key: SecretStr | None = None`

These fields live inside the normal `BaseSettings` load path:
- constructor values
- `NBADB_CHAT_...` environment variables
- `~/.nbadb/chat.json`

Important split: the settings model uses the `NBADB_CHAT_` prefix, but the tracing setup function also reads raw provider env vars directly:
- LangSmith: `LANGCHAIN_API_KEY`, `LANGCHAIN_TRACING_V2`, `LANGCHAIN_PROJECT`
- Langfuse: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`

So tracing has two config layers:
1. normalized app settings through `ChatSettings`
2. provider-native env reads and writes inside `setup_tracing(...)`

## Provider routing
| Provider value | Behavior | Env mutation | Return value |
| --- | --- | --- | --- |
| `none` | explicit no-op | none | `[]` |
| `langsmith` | enable LangChain auto-tracing via env | sets `LANGCHAIN_TRACING_V2=true`; `LANGCHAIN_PROJECT` defaults to `nbadb-chat` | `[]` |
| `langfuse` | build a `langfuse.callback.CallbackHandler` if package and keys are available | none | `[CallbackHandler(...)]` |
| anything else | silent fallback | none | `[]` |

`trace_capture` is the outer gate. If it is false, provider selection never runs and the function returns `[]` immediately.

## LangSmith behavior
LangSmith is env-driven rather than callback-driven here.

Behavior details:
- checks `LANGCHAIN_API_KEY`
- warns if the API key is missing
- still sets `LANGCHAIN_TRACING_V2 = "true"`
- uses `os.environ.setdefault("LANGCHAIN_PROJECT", "nbadb-chat")`
- returns no callback handlers

That means the current LangSmith path is best understood as "prepare process env for downstream LangChain auto-instrumentation" rather than "construct a tracing object".

## Langfuse behavior
Langfuse is callback-driven.

Resolution order:
- `langfuse_public_key`: prefer `settings.langfuse_public_key`, then `LANGFUSE_PUBLIC_KEY`
- `langfuse_secret_key`: prefer `settings.langfuse_secret_key`, then `LANGFUSE_SECRET_KEY`
- `langfuse_host`: prefer `settings.langfuse_host`, then `LANGFUSE_HOST`, then `https://cloud.langfuse.com`

If the `langfuse` package imports successfully and both keys resolve, setup returns:

```python
[CallbackHandler(public_key=..., secret_key=..., host=...)]
```

Unlike LangSmith, the Langfuse branch does not mutate env vars during setup.

## Warning and fallback behavior
| Case | Warning | Fallback |
| --- | --- | --- |
| `trace_capture=False` | no | return `[]` |
| `tracing_provider="none"` | no | return `[]` |
| `tracing_provider="langsmith"` with no `LANGCHAIN_API_KEY` | yes | still set LangSmith env flags; return `[]` |
| `tracing_provider="langfuse"` with missing package | yes | return `[]` |
| `tracing_provider="langfuse"` with missing keys | yes | return `[]` |
| unknown provider string | no | return `[]` |

The code therefore prefers soft failure over hard failure. Misconfigured tracing does not block app startup; it degrades to "no callbacks" with warnings on the recognized misconfiguration paths.

## App-local shim
`chat/server/tracing.py` does not implement tracing logic.

It:
- prepends the repo `src/` directory to `sys.path` if needed
- re-exports `setup_tracing` from `nbadb.chat.tracing`

This keeps older app imports and tests pointed at one canonical implementation.

## What tests guarantee
`tests/unit/chat/test_tracing.py` currently covers:
- default settings: `tracing_provider == "none"`; Langfuse fields are unset by default
- no-op path: `tracing_provider="none"` plus `trace_capture=False` returns `[]`
- LangSmith happy-path side effects: with `LANGCHAIN_API_KEY` present, setup returns `[]` and sets `LANGCHAIN_TRACING_V2` and `LANGCHAIN_PROJECT`
- LangSmith missing-key path: returns `[]`
- Langfuse missing-package path: returns `[]`
- Langfuse missing-keys path: returns `[]`

The test fixture clears the relevant tracing env vars before each test, which makes env mutation and env fallback behavior deterministic.

Notably untested today:
- successful Langfuse callback construction
- host precedence across settings vs `LANGFUSE_HOST`
- lock behavior under concurrency
- unknown provider fallback
- warning message text assertions

## Related notes
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/profile-settings-surface|Profile Settings Surface]]
- [[wiki/topics/chainlit-runtime|Chainlit Runtime]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| lock-guarded setup, provider routing, env mutation, and warning/fallback branches | `src/nbadb/chat/tracing.py` | canonical tracing implementation |
| tracing fields, defaults, and `NBADB_CHAT_` settings source behavior | `src/nbadb/chat/runtime/settings.py` | canonical runtime settings model |
| app-local tracing surface is only a shim and re-export | `chat/server/tracing.py` | compatibility wrapper |
| app-local `ChatSettings` import is also a shim over the shared settings model | `chat/server/config.py` | explains why tests import `ChatSettings` from app space |
| defaults, env cleanup, and current guaranteed branches | `tests/unit/chat/test_tracing.py` | current test-backed behavior |
