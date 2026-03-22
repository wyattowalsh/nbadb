## Description

<!-- What does this PR do and why? -->

## Change Type

- [ ] `feat:` New feature
- [ ] `fix:` Bug fix
- [ ] `refactor:` Code restructuring (no behavior change)
- [ ] `docs:` Documentation only
- [ ] `test:` Test additions or fixes
- [ ] `chore:` Build, CI, or dependency update

## Component

- [ ] extract/
- [ ] transform/ (dimensions / facts / derived / views)
- [ ] schemas/
- [ ] load/
- [ ] orchestrate/
- [ ] cli/
- [ ] agent/
- [ ] kaggle/
- [ ] docs/
- [ ] CI / workflows

## Checklist

- [ ] Tests added or updated (`uv run pytest tests/unit`)
- [ ] Lint passes (`uv run ruff check src/ tests/`)
- [ ] Format passes (`uv run ruff format --check src/ tests/`)
- [ ] Type check passes (`uv run ty check src/`)
- [ ] Docs updated if needed (or regenerated via `uv run nbadb docs-autogen`)
- [ ] No breaking changes to the star schema or public CLI
- [ ] Commit messages follow conventional commits (`feat:`, `fix:`, etc.)

## Related Issues

<!-- Fixes #123 / Closes #456 -->

## Notes for Reviewer

<!-- Optional: anything the reviewer should know -->
