# Version Refresh Workflow

## 1. Purpose

Ensure framework references stay aligned with current stable releases.

This skill must refresh version facts before claiming "latest".

## 2. Refresh Triggers

Run refresh when:
- User asks for "latest", "newest", or "current" setup
- Upgrade/migration mode is requested
- Existing references are older than one month
- Build failures suggest version incompatibility

## 3. Preferred Data Sources

1. Package registry APIs/tooling
2. Official release channels/docs
3. Framework changelogs (for breaking changes)

## 4. Command Patterns

### npm packages

```bash
npm view astro version
npm view @astrojs/starlight version
npm view @docusaurus/core version
npm view fumadocs-core version
```

### Python packages

```bash
uv run python - <<'PY'
import json, urllib.request
for name in ["Sphinx","shibuya","pydata-sphinx-theme","furo","mkdocs","mkdocs-material"]:
    data = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{name}/json"))
    print(name, data["info"]["version"])
PY
```

Use equivalent project-approved tooling if these are unavailable.

## 5. Update Protocol

1. Fetch fresh versions.
2. Update snapshot sections in framework reference files.
3. Add/update "Version Snapshot (YYYY-MM-DD)" heading.
4. Record source commands used.
5. Summarize deltas and potential migration impacts.

## 6. Evidence Rules

- No unsourced version claims.
- If data source fails, state uncertainty and stop short of "latest" wording.
- Prefer "latest stable" over pre-release unless user requested pre-release.

## 7. Recommended Reporting Format

```markdown
## Version Refresh Summary

- Date: YYYY-MM-DD
- Sources: npm view, PyPI JSON
- Updated frameworks: [list]
- Breaking-change risks: [list]
- Follow-up actions: [list]
```
