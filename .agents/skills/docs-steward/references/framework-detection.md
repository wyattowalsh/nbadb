# Framework Detection Reference

## 1. Detection Signals

Use positive signals from config files first, then dependency fallbacks.

| Framework | Primary config/file signals | Dependency/package signals |
|-----------|-----------------------------|----------------------------|
| Astro + Starlight | `<site-root>/astro.config.mjs` or `<site-root>/astro.config.ts` + `<site-root>/src/content/docs/` | `astro`, `@astrojs/starlight` |
| Docusaurus | `docusaurus.config.js`, `docusaurus.config.ts`, `sidebars.ts`, `sidebars.js` | `@docusaurus/core`, `@docusaurus/preset-classic` |
| Fumadocs | `next.config.js/ts` + app/docs routes, `source.config.ts` variants | `fumadocs-core`, `fumadocs-ui`, `fumadocs-mdx` |
| Sphinx | `conf.py`, `_static/`, `_templates/` under docs | `Sphinx`, `pydata-sphinx-theme`, `shibuya`, `furo`, `sphinx-book-theme` |
| MkDocs | `mkdocs.yml` or `mkdocs.yaml` | `mkdocs`, `mkdocs-material` |

For Astro + Starlight, treat `src/content/docs/` as canonical **relative to the Astro site root** and derive that root from the config location (for example: `astro.config.mjs` + `src/content/docs/`, `docs/astro.config.mjs` + `docs/src/content/docs/`, `apps/docs/astro.config.ts` + `apps/docs/src/content/docs/`).

## 2. Multi-Framework Heuristic

Repository can contain multiple frameworks when:

1. Multiple config file families exist at once, or
2. Distinct docs directories map to different framework configs, or
3. Migration branches keep legacy and new framework trees concurrently.

Examples:
- `website/docusaurus.config.ts` + `docs/mkdocs.yml`
- `legacy-docs/conf.py` + `apps/docs/next.config.ts` with Fumadocs packages

## 3. Selection Rules

1. If user specifies framework explicitly, trust user override.
2. If exactly one framework is detected, auto-select it.
3. If 2+ frameworks are detected and no explicit target:
   - Ask user which framework to operate on this run.
   - Suggest `matrix` mode when user asks for a full portfolio pass.
4. If no framework is detected:
   - Ask user what stack is used.
   - Do not assume based on folder names only.

## 4. Confidence Scoring (Optional)

Use coarse confidence for routing diagnostics:

- **High**: config file + matching dependencies
- **Medium**: config file only
- **Low**: dependency-only match
- **Unknown**: no strong signal

## 5. Output Contract

Detection output should include:

- `detected_frameworks`: ordered list
- `confidence_by_framework`
- `primary_candidate` (nullable)
- `requires_user_choice` (boolean)
- `evidence`: file paths and package names used

## 6. Safety Notes

- Never delete legacy docs trees during detection.
- Detection should be read-only.
- Preserve manual user framework overrides for the current run.
