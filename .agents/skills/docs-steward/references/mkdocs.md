# MkDocs Reference

## 1. Version Snapshot (2026-03-05)

- `mkdocs`: `1.6.1`
- `mkdocs-material`: `9.7.4`
- `mkdocs-awesome-pages-plugin`: `2.10.1`
- `mkdocs-git-revision-date-localized-plugin`: `1.5.1`
- `mkdocs-minify-plugin`: `0.8.0`
- `mkdocs-mermaid2-plugin`: `1.2.3`

Re-check before claiming "latest": see `version-refresh.md`.

## 2. Core Project Signals

- `mkdocs.yml` or `mkdocs.yaml`
- `docs/` content directory
- Optional plugin/theme entries under `plugins:` and `theme:`

## 3. High-Value Sync Workflow

1. Validate nav tree and docs paths in `mkdocs.yml`.
2. Validate theme options and plugin compatibility.
3. Build with strict mode to catch broken links/nav issues.
4. Validate generated search metadata and page discoverability.

## 4. Advanced Configuration Focus

- Prefer explicit nav for large docs portfolios.
- Keep Material feature flags intentional and reviewed.
- Keep plugin stack minimal and justified.
- Use markdown extension settings consistently project-wide.

## 5. Health Checks

- Nav entries pointing to missing files
- Plugin load order conflicts
- Stale search index issues after content moves
- Theme overrides drifting after upgrades

## 6. Enhancement Priorities

- Improve landing pages and audience-based pathways.
- Add deeper related-links and cross-section discovery.
- Normalize callouts/tabs/code block styling.
- Reduce duplicated snippets with include-like patterns.

## 7. Common Anti-Patterns

- Over-automated nav with unclear information hierarchy
- Too many plugins with overlapping functionality
- Theme customization spread across unrelated files
- Missing strict build checks in workflow

## 8. Command Skeletons

```bash
# Install/update
uv add mkdocs mkdocs-material mkdocs-awesome-pages-plugin

# Build checks
uv run mkdocs build --strict
uv run mkdocs serve
```

Use project-local wrappers/scripts when present.
