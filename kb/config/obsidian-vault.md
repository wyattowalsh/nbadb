# Obsidian Vault Conventions

## Vault mode
- Mode: obsidian-native
- KB root: `kb`
- Default note link style: Obsidian wikilink syntax
- Strategy: companion KB over existing repo docs and code

## Shared `.obsidian/` surfaces
- `.obsidian/templates/`
- `.obsidian/snippets/`

## Attachment path
- Local supporting assets live under `raw/assets/` unless a stronger existing convention already exists.

## Template usage
- Use `.obsidian/templates/wiki-note-template.md` for maintained synthesis pages.
- Use `.obsidian/templates/source-note-template.md` for source-summary notes.
- Keep maintained `wiki` pages Dataview-safe and easy to refactor.

## Dataview metadata contract
- Recommended fields: `title`, `tags`, `aliases`, `kind`, `status`, `updated`, `source_count`, `cssclasses`

## Shared naming rules
- Use kebab-case filenames under `wiki/`, `raw/`, `schema/`, `config/`, and `indexes/`.
- Prefer human-readable titles in frontmatter and stable filenames on disk.
- Preserve current repo paths as code references instead of pretending they are vault notes.

## Out-of-scope volatile state
- Workspace panes and session layout
- Recent files and UI history
- Machine-personal appearance settings

## Notes
- Existing repo docs under `docs/` remain `canonical material`.
- Existing code under `src/` and `apps/` remains `canonical material`.
- Generated docs artifacts can be cited and summarized, but their generator/code source remains authoritative.
