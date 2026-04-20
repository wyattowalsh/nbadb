# Cross-Framework Migration Playbooks

## 1. Principles

1. Migrate in phases, not one-shot rewrites.
2. Preserve URL/slug continuity where possible.
3. Validate parity after each phase.
4. Keep rollback path until parity is confirmed.

## 2. Supported v1 Paths

- Docusaurus -> Fumadocs
- Sphinx -> MkDocs
- Sphinx -> Starlight
- MkDocs -> Docusaurus

## 3. Migration Phases

### Phase A: Inventory

- Content corpus count (pages, guides, references)
- Navigation topology and hierarchy depth
- Embedded components/plugins/extensions in use
- URL and anchor inventory

### Phase B: Mapping

- Frontmatter and metadata mapping
- Admonition/callout syntax mapping
- Code block + tab syntax mapping
- Sidebar/toctree/nav mapping

### Phase C: Theming and UX

- Theme token and component parity goals
- Header/footer/search behavior equivalence
- Landing page and discoverability parity

### Phase D: Build and Quality Gates

- Strict build pass in target framework
- Link and anchor parity checks
- Orphan page check
- Representative user journey check

### Phase E: Rollout

- Dual-run period (legacy + target) where possible
- Redirect plan for changed URLs
- Deprecation and cleanup plan

## 4. Pair-Specific Notes

### Docusaurus -> Fumadocs

- Map sidebars/categories to app-router navigation model.
- Rework MDX/plugin assumptions for Next runtime.
- Validate docs route behavior and dynamic segments.

### Sphinx -> MkDocs

- Convert or adapt RST/MyST patterns for markdown-first flow.
- Replace Sphinx extension-specific directives where needed.
- Validate nav fidelity from toctree to mkdocs nav.

### Sphinx -> Starlight

- Convert source formats with metadata preservation.
- Map to Starlight content structure and frontmatter.
- Rebuild IA for guide-first navigation and discoverability.

### MkDocs -> Docusaurus

- Port nav and markdown conventions.
- Validate admonition/code-tab syntax differences.
- Rebuild sidebars with audience/task pathways.

## 5. Migration Output Template

Return:
- Scope
- Current state summary
- Target framework summary
- Risk register
- Phase-by-phase plan
- Rollback strategy
- Command checklist
