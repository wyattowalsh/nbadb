---
name: docs-steward
description: >-
  Maintain docs across Starlight, Docusaurus, MkDocs. Sync, health checks,
  migrations, ADRs, runbooks. Use when docs change. NOT for backend code, skills
  (skill-creator), or MCP servers (mcp-creator).
argument-hint: "[auto|init|sync|enhance|maintain|research|matrix|migrate|generate api|generate adr|generate runbook|generate onboard|generate glossary|framework <name> <action>]"
license: MIT
model: opus
metadata:
  author: wyattowalsh
  version: "1.0"
---

# Docs Steward

Maintain docs quality, architecture, and framework currency in project-local repositories.

**Input:** `$ARGUMENTS` — mode keywords, framework names, migration goals, or natural-language docs requests.

---

## Canonical Vocabulary

| Term | Meaning | NOT |
|------|---------|-----|
| **docs framework** | Primary platform rendering docs (Starlight, Docusaurus, Fumadocs, Sphinx, MkDocs) | "site generator" (too broad) |
| **theme layer** | Visual and component skin on top of a framework | "framework" |
| **content graph** | Navigation + page relationships + generated indexes | "folder list" |
| **init** | Non-destructive docs bootstrap in an existing repository | "reinitialize/overwrite" |
| **sync** | Regenerate framework artifacts from source docs state | "deploy" |
| **maintain** | Read-only health checks for structure, links, drift, and build integrity | "rewrite" |
| **enhance** | Improve existing docs clarity, structure, UX, and discoverability | "recreate" |
| **matrix run** | Execute workflows for all detected frameworks in one repository | "auto" |
| **migration** | Planned transition from one docs framework to another with parity checks | "instant convert" |
| **version refresh** | Update reference knowledge to latest stable framework/tool versions | "blind upgrade" |
| **project-local** | Skill is installed and used within the current project scope | "global install" |

---

## Dispatch Table

Route `$ARGUMENTS` to mode:

| `$ARGUMENTS` pattern | Mode | Start at |
|----------------------|------|----------|
| (empty) or `auto` | **Auto** | Mode A |
| `framework <name> <action>` (`<action>` ∈ `sync|enhance|maintain|research|migrate`) | **Framework-targeted** | Mode B |
| `framework <name>` | **Framework-targeted** (default action: `maintain`) | Mode B |
| `init` / `init <name>` | **Init** | Mode I |
| `init-sync` / `init-sync <name>` | **Init+Sync** | Mode I |
| `sync` / `sync <name>` | **Sync** | Mode C |
| `enhance` / `enhance <path>` | **Enhance** | Mode D |
| `maintain` / `maintain <name>` | **Maintain** | Mode E |
| `research` / `research versions` | **Research** | Mode F |
| `matrix` | **Matrix** | Mode G |
| `migrate <from> -> <to>` | **Migrate** | Mode H |
| `generate api <module>` | **Generate** | Mode J |
| `generate adr <decision>` | **Generate** | Mode J |
| `generate runbook <process>` | **Generate** | Mode J |
| `generate onboard` | **Generate** | Mode J |
| `generate glossary` | **Generate** | Mode J |
| Natural language: "generate API docs/reference" | **Generate** | Mode J |
| Natural language: "create an ADR/decision record" | **Generate** | Mode J |
| Natural language: "write a runbook/onboarding guide" | **Generate** | Mode J |
| Natural language: "set up `<framework>` docs from scratch and keep it in sync" | **Init+Sync** | Mode I |
| Natural language: "docs are stale/broken/outdated" | **Maintain** | Mode E |
| Natural language: "improve docs UX/content/nav" | **Enhance** | Mode D |
| Natural language: "upgrade latest framework versions" | **Research** | Mode F |
| Requests to build app APIs, skills, or MCP servers | **Refuse** | Redirect |

### Classification Gate

1. Detect frameworks using `references/framework-detection.md`.
2. If one framework is detected, continue with that framework.
3. If multiple frameworks are detected and user did not specify target, **ask user to choose each run** (interactive mode).
4. If no framework signal exists, ask user for docs stack before editing (interactive mode).
5. If the run is headless/non-interactive, apply the Headless Fallback Contract.

### Headless Fallback Contract

When no clarifying exchange is possible:
1. If framework target is ambiguous or multiple frameworks are detected without explicit target, run **Mode E (Maintain)** as a read-only **Mode G (Matrix)** across detected frameworks.
2. Only allow mutating auto paths when framework selection is explicit or single-framework high-confidence and trigger category is safe per Mode A.
3. Process frameworks in deterministic order: `starlight/astro`, `docusaurus`, `fumadocs`, `sphinx`, `mkdocs`.
4. Emit a warning when headless fallback was applied and mutating modes (`init`, `init-sync`, `sync`, `enhance`, `research`, `migrate`) were skipped pending explicit framework selection.
5. If no framework is detected, return a read-only maintain report with "framework target required" and no edits.

---

## Live Version Research (Required for "latest")

When user requests latest versions (explicitly or implicitly), always refresh version facts before applying changes:

1. Query package registries (npm/PyPI) with tool-assisted checks.
2. Update framework reference snapshots in `references/*.md`.
3. Record version source and date in the edited reference.
4. Only then propose dependency or config updates.

Never claim "latest" without evidence from current registry data.

---

## Mode A: Auto

Default orchestrator mode.

### A.1 Trigger categories

Classify detected change signals before choosing a mode:
- **Content-only:** page prose/examples/frontmatter edits without nav/config/build impact.
- **Structure/config:** docs/framework/config/navigation/build-related changes (sidebar/nav trees, framework config, docs build wiring, generated docs artifacts).
- **Dependency/version:** docs framework/theme/plugin dependency or lockfile/version changes.

### A.2 Action path

1. Detect docs frameworks.
2. If multiple frameworks, ask which one to operate on this run.
3. Route by trigger category:
   - Content-only -> **Mode D (Enhance)**, then optional **Mode E (Maintain)** check.
   - Structure/config -> **Mode C (Sync)** + **Mode E (Maintain)**.
   - Dependency/version -> **Mode F (Research)** + **Mode C (Sync)** + **Mode E (Maintain)**.
4. If trigger category or intent is unclear, ask one focused clarifying question before edits.

### A.3 Auto-sync safety

1. Auto-sync is allowed only when framework target is explicit or single-framework high-confidence.
2. In headless ambiguous multi-framework runs, preserve read-only fallback (Mode E matrix); do not auto-sync.
3. If confidence is low, framework signals conflict, or scope is not docs-local, downgrade to **Mode E (Maintain)**.

---

## Mode B: Framework-targeted (`framework <name> [<action>]`)

Supported names:
- `astro` / `starlight`
- `docusaurus`
- `fumadocs`
- `sphinx`
- `mkdocs`

Grammar: `framework <name> [<action>]`, where `<action>` is one of `sync`, `enhance`, `maintain`, `research`, or `migrate`.
If `<action>` is omitted, default to `maintain`.
Run the mapped mode for the selected framework: `sync` -> Mode C, `enhance` -> Mode D, `maintain` -> Mode E, `research` -> Mode F, `migrate` -> Mode H.

---

## Mode C: Sync

Bring generated docs artifacts into a consistent state.
- Verify framework-native advanced component support and rendering paths (Mermaid, code snippets, tables, embeds, tabs/admonitions).

### C.1 Astro + Starlight
- Verify Astro config and Starlight integration.
- Regenerate docs artifacts with project commands (for this repo: `uv run wagents docs generate`).
- Build-check docs output.

### C.2 Docusaurus
- Validate `docusaurus.config.*`, sidebars, and docs route structure.
- Rebuild generated docs assets and run build sanity checks.

### C.3 Fumadocs
- Validate `next.config.*`, `fumadocs-*` package setup, and MDX content tree.
- Regenerate indexes/navigation where applicable and run Next build checks.

### C.4 Sphinx
- Validate `conf.py`, extension set, and theme package alignment.
- Build with strict warnings enabled for docs quality gates.

### C.5 MkDocs
- Validate `mkdocs.yml`, plugin stack, and nav structure.
- Run strict build checks and detect plugin drift.

### C.6 Sync output contract
- Include an "Advanced component render check" summary for Mermaid, code snippets, tables, embeds, and tabs/admonitions.
- Note framework-specific support/plugins used and flag unsupported components with safe fallbacks.
- Include accessibility notes (diagram text alternatives, labeled code fences, titled embeds, and tab/admonition semantics).

---

## Mode D: Enhance

Improve docs quality without changing framework identity.

Enhancement targets:
- Information architecture (nav clarity, section depth, landing pages)
- Writing quality (scannability, examples, API/task orientation)
- Internal linking (orphan reduction, related-links strategy)
- Visual documentation UX (callouts, tabs, code grouping, admonitions, diagrams, embeds, tables)
- Consistency (style, heading depth, frontmatter, metadata)

Ask clarifying questions when enhancement direction is ambiguous ("developer docs", "marketing docs", "API docs", or "tutorial docs").

### D.1 Advanced component strategy
- Use advanced components when they materially improve comprehension, not decoration.
- Choose framework-native primitives for the active stack and keep syntax/style consistent within each page.
- Prefer: Mermaid for flows/architecture, code snippets for implementation steps, tables for comparisons, embeds for canonical demos/media, tabs/admonitions for variants and cautions.
- Keep outputs accessible: add plain-language context and text fallback for diagrams, language labels on code blocks, meaningful captions/titles, and avoid color-only or tab-only critical content.
- Use `references/advanced-components.md` for framework-specific syntax patterns and safe fallbacks.

### D.2 Enhance output contract
- Summarize which advanced components were added/updated, why they help, and any framework constraints or fallbacks.

---

## Mode E: Maintain

Read-only diagnostics and remediation planning.

Checks:
1. Broken links and anchor drift
2. Stale/generated file mismatch
3. Navigation dead-ends and orphans
4. Theme/plugin dependency drift
5. Build warnings/errors
6. Framework mismatch in mixed repos

Output format:
- Critical (must-fix)
- Warning (should-fix)
- Suggestion (nice-to-have)
- Next commands to run

---

## Mode F: Research

Refresh framework/theme references to latest stable versions and advanced patterns.

Workflow:
1. Resolve package/version facts for each active framework.
2. Update reference snapshot sections.
3. Note migration-relevant deltas (breaking changes, deprecated APIs, config shifts).
4. Return a concise change summary with confidence and citations/source commands.

---

## Mode G: Matrix

Execute a controlled run across **all** detected frameworks in the repository.

Use for:
- Monorepos with multiple docs stacks
- Parallel migration programs
- Framework parity audits

Matrix run output must keep results grouped per framework and include cross-framework conflicts.

---

## Mode H: Migrate (`migrate <from> -> <to>`)

Migration is in scope for v1.

Supported paths:
- Docusaurus -> Fumadocs
- Sphinx -> MkDocs
- Sphinx -> Starlight
- MkDocs -> Docusaurus

Migration phases:
1. Inventory and parity baseline
2. Content and nav mapping
3. Theme/component mapping
4. Build/test parity checks
5. Incremental rollout plan

Do not promise one-shot full conversion; prefer staged migration with checkpoints.

---

## Mode I: Init (`init`, `init <framework>`, `init-sync`, `init-sync <framework>`)

Bootstrap docs site wiring in an existing repository without destructive rewrites.
This mode applies to explicit `init*` commands and implicit "bootstrap docs + keep synced" requests in existing codebases.
Load `references/init-sync-existing-repos.md` plus the selected framework reference before edits.

### I.1 Framework selection behavior
1. If `<framework>` is provided, target that framework directly.
2. If no `<framework>` is provided and exactly one framework is detected, target the detected framework.
3. If multiple frameworks are detected and no explicit target is provided, ask user to choose; in headless runs, apply the Headless Fallback Contract.
4. If no framework is detected and no explicit target is provided, ask user to select a supported framework; in headless runs, return read-only Mode E output with "framework target required."

### I.2 Non-destructive bootstrap contract
- Only create missing docs scaffold/config files; do not overwrite existing files by default.
- Preflight guard: if target docs root already exists and is non-empty, do not recreate or replace that root; continue in-place with missing-file scaffolding only unless user explicitly requests overwrite.
- Preserve existing docs content, navigation, and framework config when present.
- If requested framework conflicts with existing docs framework wiring, stop and return maintain findings + conflict summary (use Mode H for migrations).

### I.3 Follow-up flow
- `init`: bootstrap, then recommend `sync` and `maintain` follow-up.
- `init-sync`: bootstrap, then run **Mode C (Sync)** and **Mode E (Maintain)** in the same run.
- Always report what was created, what was skipped, and why.

---

## Mode J: Generate (`generate <type> [<target>]`)

Generate technical documentation from source code. Load `references/generate-mode.md` for detailed procedures, output formats, and script usage.

Sub-modes:

| Command | Output | Key Script |
|---------|--------|------------|
| `generate api <module>` | API reference with signatures, docstrings, coverage | `api-surface-extractor.py`, `doc-coverage-analyzer.py` |
| `generate adr <decision>` | MADR-format architecture decision record | `adr-scaffolder.py` |
| `generate runbook <process>` | Operational runbook with commands from codebase | — |
| `generate onboard` | New contributor onboarding guide | — |
| `generate glossary` | Term definitions extracted from code and docs | — |

### J.1 Workflow

1. Identify target scope (module path, process name, or whole repo).
2. Run applicable scripts to extract structured data from source.
3. Transform extracted data into documentation following the format in `references/generate-mode.md`.
4. Present draft for review. Ask clarifying questions if context is ambiguous.
5. Write output to appropriate location (e.g., `docs/api/`, `docs/decisions/`).

### J.2 Generate output contract

- Generated docs must trace to source code (include file paths and line numbers).
- Never fabricate API signatures or docstrings; extract or flag as undocumented.
- ADRs follow MADR v3 format from `data/adr-template.json`.
- Use docstring format conventions from `data/docstring-formats.json` matching the project's language and style.

---

## Scope Boundaries

**In scope:** Docs framework operations, non-destructive docs bootstrap, version refresh, build/health diagnostics, quality enhancement, docs migrations, technical documentation generation from code.

**NOT for:**
- Creating/editing unrelated product features or backend APIs
- Creating new skills, agents, or MCP servers
- CI/CD redesign outside docs pipeline needs
- Non-docs frontend application implementation

---

## Reference File Index

Load references on demand; do not load all at once.

| File | Content | Load When |
|------|---------|-----------|
| `references/framework-detection.md` | Framework signal map, multi-framework routing rules | All modes |
| `references/advanced-components.md` | Framework-specific Mermaid/codeblocks/tables/embeds patterns with safe fallbacks | sync/enhance |
| `references/init-sync-existing-repos.md` | Non-destructive framework-aware bootstrap + follow-up sync workflows for existing repos | init/init-sync |
| `references/astro-starlight.md` | Astro + Starlight advanced setup and checks | framework/sync/maintain/enhance |
| `references/docusaurus.md` | Docusaurus advanced config and plugin checks | framework/sync/maintain/enhance |
| `references/fumadocs.md` | Fumadocs + Next advanced setup and checks | framework/sync/maintain/enhance |
| `references/sphinx.md` | Sphinx + theme matrix (Shibuya/PyData/Furo/Book) | framework/sync/maintain/enhance |
| `references/mkdocs.md` | MkDocs + Material/plugin stack checks | framework/sync/maintain/enhance |
| `references/migrations.md` | Migration playbooks and parity templates | migrate/matrix |
| `references/version-refresh.md` | Latest-version refresh workflow and evidence rules | research + any latest-version request |
| `references/generate-mode.md` | Generate sub-mode procedures, output formats, script usage | generate |
| `data/docstring-formats.json` | Docstring format standards per language (Google, NumPy, Sphinx, JSDoc, TSDoc) | generate api |
| `data/adr-template.json` | MADR v3 template structure and file naming conventions | generate adr |

---

## Critical Rules

1. Ask at least one clarifying question before edits when user intent or target framework is ambiguous.
2. In multi-framework repositories, `auto` mode must ask which framework to operate on each run unless explicitly overridden.
3. Never claim "latest" versions without fresh registry-backed evidence and a reference snapshot update.
4. Keep operations project-local by default; do not assume global install context.
5. Run framework-appropriate build or validation checks after docs changes.
6. Maintain mode is read-only: diagnose first, then propose concrete fixes.
7. Migration mode must be phased and reversible; avoid destructive one-pass rewrites.
8. Refuse out-of-scope requests and route to the correct specialized skill.
9. Init mode is non-destructive in existing repos: create missing files only unless user explicitly requests overwrite.
10. Generate mode must extract from source code; never fabricate signatures, docstrings, or API details.
