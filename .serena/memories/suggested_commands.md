Setup: `uv sync` or `uv sync --extra dev`.
Quality: `uv run ruff check src/ tests/`, `uv run ruff format src/ tests/`, `uv run ty check src/`, `uv run pytest --import-mode=importlib tests/unit`, `uv run pytest --import-mode=importlib tests/`.
Pipeline: `uv run nbadb init`, `uv run nbadb daily`, `uv run nbadb monthly`, `uv run nbadb export`.
Docs: `uv run nbadb docs-autogen --docs-root docs/content/docs`, `cd docs && pnpm build`, `cd docs && pnpm dev`.