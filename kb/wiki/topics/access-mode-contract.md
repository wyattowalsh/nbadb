---
title: Access Mode Contract
tags:
  - kb
  - topics
  - chat
  - runtime
  - access
  - capabilities
aliases:
  - Access Modes
  - Provider Access Mapping
kind: concept
status: active
updated: 2026-04-15
source_count: 3
---

# Access Mode Contract

This note captures the narrow contract between provider selection, `access_mode` normalization, and the capability flags that the runtime derives from that normalized state.

The contract spans three files:
- `src/nbadb/chat/access/modes.py`
- `src/nbadb/chat/runtime/settings.py`
- `src/nbadb/chat/runtime/capabilities.py`

## Core rule
`ChatSettings` treats `access_mode` as optional input. When it is omitted, `_normalize()` derives it from `provider` via `access_mode_from_provider(...)`.

That makes provider choice the default source of truth for access mode unless a caller explicitly overrides `access_mode`.

## Provider-to-mode mapping
| Provider | Derived access mode | Why it matters downstream |
| --- | --- | --- |
| `ollama` | `local` | local-model session; `browser_use` stays off |
| `lmstudio` | `local` | local-model session; `browser_use` stays off |
| `copilot` | `copilot` | turns `browser_use` on |
| `openai` | `byok` | hosted provider, but treated as API-key style access |
| `anthropic` | `byok` | same |
| `google` | `byok` | same |
| `custom` | `byok` | OpenAI-compatible endpoint still normalizes to BYOK |

## Access modes in play
`AccessMode` defines four values:
- `local`
- `byok`
- `copilot`
- `openai-login`

Only three are reachable from provider mapping today:
- `local`
- `byok`
- `copilot`

Important edge: `openai-login` exists in the enum and is honored by capability derivation, but `access_mode_from_provider(...)` never returns it. It only appears if some caller explicitly sets `access_mode=AccessMode.OPENAI_LOGIN`.

## Settings-layer normalization
`ChatSettings` applies these access- and quality-related rules after loading env, JSON, and constructor values:
- if `access_mode is None`, derive it from `provider`
- if `quality_mode == careful`, force `dual_sql_drafting = true`
- if `quality_mode == fast`, force `answer_judge = false`

Two consequences follow from that ordering:
- capability derivation sees normalized values, not raw user input
- explicit `access_mode` wins over provider inference

## Capability effects
`build_capability_manifest(...)` consumes normalized `access_mode`, `provider`, `quality_mode`, and `sandbox_mode`.

### Browser-use implications
`browser_use` is enabled only when:
- `access_mode == copilot`
- `access_mode == openai-login`

So the practical runtime matrix is:
- `local` -> `browser_use = false`
- `byok` -> `browser_use = false`
- `copilot` -> `browser_use = true`
- `openai-login` -> `browser_use = true`

Because provider mapping never emits `openai-login`, the only provider-driven path that currently enables `browser_use` is `provider=copilot`.

### Quality-mode effects
Quality mode changes two manifest flags:
- `careful` -> `dual_sql_drafting = true`
- `fast` -> `answer_judge = false`
- `balanced` -> leave both at their default runtime behavior

This mirrors the `ChatSettings` normalization step exactly:
- settings force the toggles
- capability manifest re-expresses the same policy as session metadata

### Sandbox note
`build_capability_manifest(...)` accepts `sandbox_mode`, but the current implementation always returns the full supported tuple:
- `local`
- `daytona`
- `e2b`

So `sandbox_mode` is part of the input contract, but it does not currently narrow `supported_sandboxes`.

## Downstream summary
| Input choice | Normalized state | Manifest effect |
| --- | --- | --- |
| `provider=ollama` or `lmstudio` | `access_mode=local` | `browser_use=false` |
| `provider=copilot` | `access_mode=copilot` | `browser_use=true` |
| `provider=openai` / `anthropic` / `google` / `custom` | `access_mode=byok` | `browser_use=false` |
| explicit `access_mode=openai-login` | no provider mapping involved | `browser_use=true` |
| `quality_mode=careful` | settings force drafting on | manifest shows `dual_sql_drafting=true` |
| `quality_mode=fast` | settings force judge off | manifest shows `answer_judge=false` |

## Design implications
- Provider choice is the default access-policy selector.
- `browser_use` is access-mode gated, not provider gated.
- `copilot` is the only built-in provider that currently flips the runtime into a browser-enabled mode.
- `openai-login` is a latent access path supported by capabilities, but not by provider inference.
- Quality mode is both a settings mutation rule and a capability-reporting rule, so UI state and manifest state stay aligned.

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| `AccessMode` enum values and provider-to-mode mapping | `src/nbadb/chat/access/modes.py` | canonical access-mode vocabulary and inference function |
| `ChatSettings` defaults, `access_mode` derivation, and quality-mode normalization | `src/nbadb/chat/runtime/settings.py` | canonical settings-layer normalization contract |
| `ProviderName`, `QualityMode`, `CapabilityManifest`, `browser_use` gating, and sandbox/quality-derived manifest flags | `src/nbadb/chat/runtime/capabilities.py` | canonical capability derivation policy |
