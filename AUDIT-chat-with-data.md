# Audit Report: Chat with Data (apps/chat + notebooks)

**Date**: 2026-04-02
**Skills Applied**: /research, /python-conventions, /javascript-conventions, /honest-review, /frontend-designer, /host-panel, /simplify
**Scope**: `apps/chat/` (25 Python files, 874-line Chainlit frontend), `notebooks/` (14 Kaggle notebooks), `src/nbadb/agent/`, `src/nbadb/kaggle/`, `docs/` (81 TS/TSX files)

---

## Executive Summary

The chat application is well-architected with good separation of concerns, pluggable LLM providers, and layered security. However, the audit found **8 P0 security issues** (including a crash bug and multiple injection vectors), **4 P1 architectural improvements**, and **3 P2 UX fixes**. The docs site frontend scores 4-4.5/5 across all UX categories. ~300 lines of code can be simplified through deduplication.

---

## 1. Security Findings (P0)

### 1.1 CRITICAL: `__aexit__` Crash on Every Cleanup
- **File**: `apps/chat/server/agent.py:52`
- **Issue**: `await self._mcp_client.__aexit__(None, None, None)` raises `NotImplementedError` in langchain-mcp-adapters >= 0.1.0
- **Impact**: Crashes on every settings update and session end, leaving MCP subprocess zombies
- **Fix**: Remove the `__aexit__` call — MCP client is now stateless (each tool call creates/destroys its own session)
- **Source**: RR-05 (confidence 0.99)

### 1.2 HIGH: AST Sandbox Escape via `__objclass__`
- **File**: `apps/chat/server/_sandbox_exec.py:132-143`
- **Issue**: `_BLOCKED_ATTRS` missing `__objclass__` — known escape vector (CVE-2026-27577)
- **Fix**: Add `"__objclass__"`, `"__init_subclass__"`, `"__set_name__"`, `"__class_getitem__"`, `"__reduce__"`, `"__reduce_ex__"` to `_BLOCKED_ATTRS`
- **Source**: RR-15, HR-11

### 1.3 HIGH: Triple-Quote Breakout in Exported Session Code
- **File**: `apps/chat/chainlit_app.py:280,355`
- **Issue**: `f'query("""{entry["code"]}""")'` — SQL containing `"""` injects arbitrary Python into exported .py scripts
- **Fix**: Use `repr()`: `f'query({entry["code"]!r})'`
- **Source**: HR-02 (confidence 0.92)

### 1.4 HIGH: Path Traversal in Template Save
- **File**: `apps/chat/chainlit_app.py:299`
- **Issue**: `name = action.payload.get("name")` used directly in file path — `../../.bashrc` writes anywhere
- **Fix**: `name = Path(name).stem; assert re.match(r'^[a-zA-Z0-9_-]+$', name)`
- **Source**: HR-03 (confidence 0.90)

### 1.5 HIGH: SQL Injection in SQLite→DuckDB Conversion
- **File**: `apps/chat/server/db.py:57,63`
- **Issue**: `f"ATTACH '{sqlite_path}'"` and `f'CREATE TABLE "{table_name}"'` — attacker-controlled via crafted Kaggle dataset
- **Fix**: Escape paths (`str(path).replace("'", "''")`), validate table names (`^[a-zA-Z0-9_]+$`)
- **Source**: HR-04, HR-05 (confidence 0.88)

### 1.6 HIGH: XSS in AG Grid HTML Templates
- **Files**: `chainlit_app.py:800-873`, `_preamble.py:237-320`
- **Issue**: `name`, `rows_json`, `columns_json` interpolated into HTML/JS without escaping — `</script>` breaks out
- **Fix**: `html.escape(name)` for HTML context; replace `</` with `<\/` in JSON for script blocks
- **Source**: HR-14, JS-conventions

### 1.7 HIGH: MCP Server Config Override
- **File**: `apps/chat/server/mcp_client.py:36`
- **Issue**: `servers.update(settings.extra_mcp_servers)` allows overriding `nbadb-sql` / `nbadb-sandbox` with arbitrary commands
- **Fix**: Reject keys colliding with built-in server names
- **Source**: HR-07 (confidence 0.90)

### 1.8 HIGH: Copilot `PermissionHandler.approve_all`
- **File**: `apps/chat/server/copilot_backend.py:212`
- **Issue**: Every Copilot SDK tool call auto-approved with no scoping
- **Fix**: Implement a scoped handler allowing only the 4 registered NBA tools
- **Source**: HR-13 (confidence 0.82)

---

## 2. Architecture Findings (P1)

### 2.1 Diverged ReadOnlyGuard Forks
- **Files**: `apps/chat/server/_safety.py` (119 lines) vs `src/nbadb/agent/safety.py` (103 lines)
- **Issue**: Chat version has `RESET` keyword, 6 extra dangerous functions, smarter `wrap_with_limit()`. Core is less secure.
- **Panel verdict**: Merge chat improvements into core, delete fork. Core gains: `RESET`, `read_xlsx`, `scan_csv`, `scan_parquet`, `scan_json`, `getenv`, `current_setting`, `query_table`, `_statement_prefix()`, passthrough prefix handling
- **Source**: HR-01, S-1, Panel Topic 2 (unanimous)

### 2.2 Code-as-String Preamble
- **File**: `apps/chat/server/_preamble.py` (351 lines)
- **Issue**: 336-line Python program as string literal — unlintable, untestable, no IDE support
- **Panel verdict**: Extract display/export helpers to real `sandbox_runtime.py` module (~200 lines become testable). Reduce preamble string to ~110 lines (bootstrap only).
- **Source**: S-6, Panel Topic 4 (unanimous)

### 2.3 No `[tool.ty]` Config for Chat App
- **File**: `apps/chat/pyproject.toml`
- **Issue**: Root `[tool.ty.src]` only covers `["src"]` — chat app type errors go undetected. 9 real ty errors found.
- **Fix**: Add `[tool.ty]` section with `src = ["."]`, `python-version = "3.12"`
- **Source**: Python conventions audit (C1)

### 2.4 Exception Messages Leaked in Public Demo
- **Files**: `chainlit_app.py:497,544,620`
- **Issue**: Full exception strings shown to users — can expose paths, API keys, schema details
- **Fix**: Generic user-facing errors when `public_demo_mode=True`, full details logged server-side
- **Source**: HR-08, FD-014

---

## 3. Simplification Opportunities (~300 lines)

| # | Target | Impact | Lines Saved | Risk |
|---|--------|--------|-------------|------|
| S-1 | ReadOnlyGuard unification | HIGH | ~99 | Medium |
| S-2 | AG Grid template dedup | MEDIUM | ~70 | Low |
| S-3 | Download callback dedup | MEDIUM | ~25 | Very low |
| S-4 | chainlit_app.py decomposition (874→~150 lines) | HIGH | restructure | Medium |
| S-5 | Schema context dedup | LOW | ~20 | Low-medium |
| S-6 | Preamble extraction to real module | HIGH | ~50 + testability | Medium |
| S-7 | Template script dedup | LOW | ~20 | Very low |
| S-13 | Providers init cleanup | LOW | ~2 | Very low |

**Dependency order**: S-13, S-3, S-7 (independent) → S-1 → S-2 → S-6 → S-4 → S-5

---

## 4. Python Conventions (P1-P2)

| ID | Severity | Finding | Action |
|----|----------|---------|--------|
| C1 | CRITICAL | No `[tool.ty]` config for chat app | Add config to `apps/chat/pyproject.toml` |
| C2 | HIGH | 2 null-safety errors: `df.to_json()` → `str | None` | Add null guards at `chainlit_app.py:215,234` |
| C3 | MEDIUM | 5 `Step.actions` unresolved-attribute errors | Suppress with `# type: ignore` (Chainlit SDK gap) |
| C7 | LOW | 4 unsuppressed E402 in `notebooks/kaggle_update.py` | Add to `[tool.ruff.lint.per-file-ignores]` |
| C8 | LOW | Error messages say "pip install" instead of "uv add" | Update `tracing.py:49`, `db.py:34` |

**Passing**: All 37 `.py` files have `from __future__ import annotations`. Ruff clean. uv used everywhere. All `# noqa` comments justified.

---

## 5. JavaScript/TypeScript Conventions (P2)

| ID | Severity | Finding | Action |
|----|----------|---------|--------|
| JS-1 | MEDIUM | `next-env.d.ts` tracked in git | Add to `docs/.gitignore` |
| JS-2 | LOW | No `packageManager` field in `package.json` | Add `"packageManager": "pnpm@10.x.x"` |
| JS-3 | LOW | Dual Radix UI packages | Evaluate if `@radix-ui/react-slot` is redundant |
| JS-4 | LOW | 3 `@apply` usages in CSS base layer | Acceptable for base resets |

**Passing**: pnpm-only, ESLint clean (1 warning), TypeScript strict, Tailwind v4 fully migrated, shadcn v4.1 current.

---

## 6. Frontend/UX Audit

### UX Scorecard

| Category | Rating | Notes |
|----------|--------|-------|
| Visual Design | 4/5 | Sophisticated oklch, glassmorphism, court theme. Cross-surface color mismatch. |
| Accessibility | 4/5 | Strong reduced-motion, focus-visible, aria. Chat accent contrast gap, incomplete reduced-motion. |
| Responsiveness | 4.5/5 | Thorough breakpoints, grid fallbacks, touch targets. Minor SQL textarea/schema list heights. |
| Interaction | 4.5/5 | Excellent streaming UX, keyboard shortcuts, IntersectionObserver. Platform-specific shortcut label. |
| Performance | 4/5 | Lazy loading, dynamic imports, SSR guards. 3 infinite CSS animations, backdrop-filter on mobile. |

### Top UX Fixes

| # | Severity | Finding | File |
|---|----------|---------|------|
| FD-042 | MEDIUM | Chat (blue) and docs (orange) use different brand primaries | `theme.json` vs `global.css` |
| FD-008 | MEDIUM | `standings.svg` = `chart.svg` (identical icons) | `public/icons/` |
| FD-004 | MEDIUM | Firefox scrollbar styling missing in chat | `stylesheet.css` |
| FD-001 | LOW | Orange accent fails WCAG AA in light mode (3.1:1 vs 4.5:1) | `theme.json:18` |
| FD-006 | LOW | Chat `prefers-reduced-motion` incomplete vs docs | `stylesheet.css:93-103` |
| FD-038 | LOW | Admin mobile menu button missing `aria-label` | `admin-shell.tsx:165` |

---

## 7. Research Findings

| ID | Finding | Confidence | Action |
|----|---------|------------|--------|
| RR-05 | `__aexit__` raises NotImplementedError | 0.99 | **Fix immediately** (§1.1) |
| RR-15 | `__objclass__` sandbox escape | 0.90 | **Fix immediately** (§1.2) |
| RR-17 | AST sandbox insufficient for untrusted code | 0.95 | Implement E2B for public demo (P1) |
| RR-08 | FastMCP 3.0 available | 0.90 | Consider migration (P2) |
| RR-04 | Chainlit 2.10 MCP feature flags | 0.85 | Potential enhancement |
| RR-12 | DuckDB WASM singleton correctly implemented | 0.90 | No action |

---

## 8. Host Panel Consensus

### Architectural Decisions

1. **Extract `nbadb-core` shared package** — security-critical code needs single source of truth (unanimous)
2. **Merge ReadOnlyGuard** — chat version is strictly superior, port improvements to core (unanimous)
3. **Hybrid sandbox** — fix AST bypasses (P0), implement E2B for public demo (P1), keep local for dev (4-1 consensus)
4. **Extract preamble to real module** — `sandbox_runtime.py` with full lint/test coverage (unanimous)
5. **Priority order**: P0 security (8 items) → P1 architecture (4 items) → P2 UX/polish (3 items)

### Dissenting Opinion
Dr. Chen (Security): AST sandboxing should be deprecated entirely within 90 days. The hybrid approach leaves a fundamentally insecure local mode available. (Panel majority disagrees — local mode is acceptable for self-hosted/dev.)

---

## Priority Implementation Roadmap

### P0 — Security (do first, all small effort)
1. Fix `__aexit__` crash (`agent.py:52`) — remove call
2. Add `__objclass__` + 5 more dunders to `_BLOCKED_ATTRS` (`_sandbox_exec.py`)
3. Fix triple-quote breakout — use `repr()` (`chainlit_app.py:280,355`)
4. Fix path traversal — sanitize name (`chainlit_app.py:299`)
5. Fix SQL injection in `db.py` — parameterize/escape (`db.py:57,63`)
6. Fix XSS in AG Grid templates — escape `name`, sanitize JSON (`chainlit_app.py`, `_preamble.py`)
7. Prevent MCP server override — reject colliding keys (`mcp_client.py:36`)
8. Scope Copilot permissions — replace `approve_all` (`copilot_backend.py:212`)

### P1 — Architecture (medium effort)
9. Unify ReadOnlyGuard — merge chat→core, delete fork
10. Add `[tool.ty]` config to chat app — fix 9 type errors
11. Extract preamble to `sandbox_runtime.py` — deduplicate AG Grid template
12. Sanitize error messages in public demo mode

### P2 — UX & Polish (medium effort)
13. Decompose `chainlit_app.py` (874→~150 lines)
14. Unify brand colors between chat and docs
15. Fix accessibility gaps (accent contrast, reduced-motion, aria-labels)
