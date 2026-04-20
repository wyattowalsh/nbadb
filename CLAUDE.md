# nbadb — Claude Code Instructions

See `AGENTS.md` for full project context, module map, and conventions.

## Quick Reference

```bash
# Quality
uv run ruff check src/ tests/    # Lint
uv run ty check src/             # Type check
uv run pytest tests/unit         # Unit tests (fast)
uv run pytest tests/             # All tests (1205 tests)

# Docs
cd docs && pnpm build            # Build docs site
cd docs && pnpm dev              # Dev server

# Regenerate docs artifacts
uv run nbadb docs-autogen --docs-root docs/content/docs
```

## Key Reminders
- Always use `--import-mode=importlib` for pytest (root `nbadb/` shadows `src/nbadb/`)
- `get_settings()` is cached with `@lru_cache` — tests use autouse fixture to clear
- SQL transformers extend `SqlTransformer` — define `_SQL` ClassVar, no `transform()` override
- Auto-generated docs pages (`er-auto.mdx`, `lineage-auto.mdx`) should not be hand-edited
- Docs framework is Fumadocs 16 + Next.js 16 — use pnpm in `docs/` directory
