.PHONY: install dev test lint typecheck docs build clean

install:
	uv sync

dev:
	uv sync --extra dev

test:
	uv run pytest tests/unit

test-all:
	uv run pytest

lint:
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

format:
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/

typecheck:
	uv run ty check src/

docs:
	cd docs && pnpm build

build:
	uv build

clean:
	rm -rf dist/ build/ .pytest_cache/ .coverage htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
