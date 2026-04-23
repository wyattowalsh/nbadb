# Frontmatter Fields

## Required for maintained wiki pages
| Field | Use |
|-------|-----|
| `title` | Stable display title |
| `tags` | Classification |
| `aliases` | Migration-safe alternate note names |
| `kind` | Page type |
| `status` | `bootstrap`, `active`, `partial`, `needs-review`, `historical` |
| `updated` | Last meaningful update date |
| `source_count` | Quick signal for source-backed density |

## Optional
| Field | Use |
|-------|-----|
| `cssclasses` | Project-safe styling hooks |
| `summary` | Short note summary |
| `project` | Useful when notes may span multiple repos later |

## Notes
- Keep fields flat and Dataview-safe.
- Prefer note-level metadata in frontmatter rather than inline fields.
