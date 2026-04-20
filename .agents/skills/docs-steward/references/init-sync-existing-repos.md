# Init + Sync in Existing Repositories Reference

## 1. Scope

Use this reference when a repository has product code but no docs framework wiring yet, and the request is to initialize docs from scratch (`init`) or initialize and immediately stabilize (`init-sync`).

## 2. Shared Non-Destructive Contract

1. Keep docs bootstrap project-local in a dedicated docs root (`apps/docs`, `website`, or `docs`), reusing an existing docs root when present.
2. Preflight guard: before scaffold commands, if the target docs root already exists and is non-empty, do not recreate/replace that root by default; scaffold missing files in-place unless user explicitly requests overwrite.
3. Detect and follow existing package/runtime tooling (`pnpm`/`npm`/`yarn`, `uv`, lockfiles).
4. Create only missing docs scaffold/config files; do not overwrite existing docs config/content unless user explicitly requests overwrite.
5. After bootstrap, run framework-native sync/build checks and summarize created vs skipped files.
6. If framework target is missing or ambiguous, follow `framework-detection.md` selection + headless fallback rules.
7. Treat explicit `init`/`init-sync` commands and implicit natural-language bootstrap+sync requests for existing codebases as Mode I flows.

## 3. Framework-Aware Init + Sync Playbooks

Preflight note: command skeletons that create a docs root apply only when the target root is missing or empty; if it already exists, do not rerun root-creating scaffolds by default.

### 3.1 Astro + Starlight

Bootstrap targets:
- `<docs-root>/astro.config.mjs|ts`
- `<docs-root>/src/content/docs/`
- Starlight integration and starter nav/content

Command skeletons:
```bash
pnpm create astro@latest apps/docs -- --template starlight
pnpm --dir apps/docs astro check
pnpm --dir apps/docs astro build
```

Sync checks:
- Verify Astro config + Starlight integration.
- Regenerate project docs artifacts when wrappers exist.
- Confirm nav/content graph coherence after bootstrap.

### 3.2 Docusaurus

Bootstrap targets:
- `<docs-root>/docusaurus.config.ts|js`
- `<docs-root>/sidebars.ts|js`
- `<docs-root>/docs/` starter tree

Command skeletons:
```bash
pnpm create docusaurus@latest website classic --typescript
pnpm --dir website docusaurus build
```

Sync checks:
- Validate config/baseUrl/docs plugin wiring.
- Validate sidebar graph against docs tree.
- Confirm no broken route/ID warnings on build.

### 3.3 Fumadocs

Bootstrap targets:
- `<docs-root>/next.config.ts|js`
- `<docs-root>/source.config.ts`
- docs route + MDX content tree

Command skeletons:
```bash
pnpm create next-app@latest apps/docs --ts --eslint --app
pnpm --dir apps/docs add fumadocs-core fumadocs-ui fumadocs-mdx
pnpm --dir apps/docs next build
```

Sync checks:
- Validate `fumadocs-*` package alignment.
- Validate source/content adapters and generated nav.
- Confirm docs routes build cleanly.

### 3.4 Sphinx

Bootstrap targets:
- `<docs-root>/conf.py`
- `<docs-root>/index.rst` or MyST-first equivalent
- `<docs-root>/_static` and `<docs-root>/_templates`

Command skeletons:
```bash
uv add --dev Sphinx pydata-sphinx-theme myst-parser
uv run sphinx-quickstart docs
uv run sphinx-build -b html -W docs docs/_build/html
```

Sync checks:
- Validate extension/theme compatibility in `conf.py`.
- Validate toctree/xref integrity and orphan coverage.
- Keep warnings-as-errors for quality gates.

### 3.5 MkDocs

Bootstrap targets:
- `<docs-root>/mkdocs.yml|yaml`
- `<docs-root>/docs/` starter pages
- theme/plugin baseline (`mkdocs-material` as applicable)

Command skeletons:
```bash
uv add --dev mkdocs mkdocs-material
uv run mkdocs new docs
uv run mkdocs build --strict
```

Sync checks:
- Validate nav paths and plugin compatibility.
- Run strict build to catch link/nav drift.
- Verify generated search/index metadata.

## 4. Init vs Init-Sync Output Contract

- `init`: report scaffold actions and recommend immediate `sync` + `maintain`.
- `init-sync`: bootstrap first, then run full Sync and Maintain checks in the same run.
- Always include: selected framework, docs root path, preflight guard decision, created files, skipped files, build/sync result, and follow-up actions.
