## Description

<!-- Briefly describe what this PR does and why. Link to any design docs or discussions. -->

## Related Issues

<!-- Fixes #123 / Closes #456 / Part of #789 -->

---

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

---

## Checklist

- [ ] Tests added or updated (`uv run pytest tests/unit`)
- [ ] Lint passes (`uv run ruff check src/ tests/`)
- [ ] Format passes (`uv run ruff format --check src/ tests/`)
- [ ] Type check passes (`uv run ty check src/`)
- [ ] Docs updated if needed (or regenerated via `uv run nbadb docs-autogen`)
- [ ] No breaking changes to the star schema or public CLI
- [ ] Commit messages follow conventional commits (`feat:`, `fix:`, etc.)

---

## Screenshots / Before-After

<!-- Optional: for UI or docs changes, include screenshots or before/after comparisons. -->
<!-- You can drag-and-drop images here or paste them from your clipboard. -->

## Notes for Reviewer

<!-- Optional: anything the reviewer should know — performance considerations, trade-offs, follow-up work, etc. -->
