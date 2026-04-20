# Sphinx Reference

## 1. Version Snapshot (2026-03-05)

- `Sphinx`: `9.1.0`
- `shibuya`: `2026.1.9`
- `pydata-sphinx-theme`: `0.16.1`
- `furo`: `2025.12.19`
- `sphinx-book-theme`: `1.1.4`
- `myst-parser`: `5.0.0`

Re-check before claiming "latest": see `version-refresh.md`.

## 2. Core Project Signals

- `conf.py`
- `index.rst` or MyST-first index patterns
- `_static/` and `_templates/` directories

## 3. Theme Matrix Guidance

| Theme | Best fit |
|------|----------|
| Shibuya | Modern product docs with strong visual branding |
| PyData | Data/engineering docs with robust nav and search conventions |
| Furo | Minimal, readable docs with low maintenance overhead |
| Book | Tutorial/book-style linear content experiences |

## 4. High-Value Sync Workflow

1. Validate `conf.py` extension and theme settings.
2. Validate docs source format consistency (`.rst` vs MyST markdown).
3. Build with warnings as errors for quality gates.
4. Check xrefs, toctree integrity, and orphan files.

## 5. Health Checks

- Missing toctree references
- Broken `:ref:` and cross-document links
- Theme option drift after version updates
- Extension incompatibility across Sphinx/theme versions

## 6. Enhancement Priorities

- Improve toctree clarity and page discoverability.
- Standardize admonitions and API/object reference style.
- Improve quickstart-to-reference progression.
- Consolidate duplicated RST/MyST snippets.

## 7. Common Anti-Patterns

- Large pages with no section-level IA
- Hidden orphan pages never linked in toctree
- Theme switch without validating custom CSS overrides
- Mixed extension versions with no lock-step update plan

## 8. Command Skeletons

```bash
# Install/update
uv add "Sphinx>=9" shibuya pydata-sphinx-theme furo sphinx-book-theme myst-parser

# Build checks
uv run sphinx-build -b html -W docs docs/_build/html
```

Prefer project task runner commands when defined.
