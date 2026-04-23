# Knowledge Base

`kb/` is companion repo content for maintainers and agents. It is not build output or local scratch.

Use this surface for:
- Obsidian-native indexes, schema notes, source maps, ingest rules, and curated operational knowledge
- additive companion material that helps repo navigation, provenance, and agent workflows

Do not treat this surface as:
- the source of product or pipeline truth over `README.md`, `AGENTS.md`, `docs/`, or `src/nbadb/`
- a place for disposable exports, one-off scratch notes, or editor-local workspace state

Repo-safe expectations:
- keep shared vault config limited to repo-safe surfaces such as `.obsidian/templates/` and `.obsidian/snippets/` when present
- keep the existing `raw/`, `wiki/`, `schema/`, `config/`, `indexes/`, and `activity/` structure additive-first
- preserve provenance and source mapping instead of rewriting content wholesale

Authority order:
- repo canon lives in root docs, generated docs contracts, and source code
- `kb/` is a companion layer that documents and indexes that canon
