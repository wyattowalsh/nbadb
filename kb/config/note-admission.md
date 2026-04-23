# Note Admission

## Purpose
Use this file to decide whether a new maintained `wiki` note should exist at all.

## Admission gate
A new maintained note is justified only when all three conditions hold:
- it names a stable seam, recurring question, or high-value bridge between existing KB clusters
- it can be backed by `raw` or declared `canonical material` without vague provenance
- it has an obvious freshness trigger, maintenance owner, or review lane

## Default outcomes
| If the material is... | Put it in... |
| --- | --- |
| exact source capture or volatile upstream evidence | `raw/sources/` |
| grouped inventory, manifest, or batch extract | `raw/extracts/` |
| one-source bridge from evidence into synthesis | `wiki/topics/*-source-summary.md` |
| stable explanatory or wayfinding surface with repeated navigation value | maintained `wiki/topics/*.md` |
| not yet worth a maintained note | leave it out and record the gap in `coverage` or `stub-replacement-queue` |

## Fast rejection rules
Do not add a new maintained note when:
- it only duplicates an existing route, family map, or topic note
- the backing source is still only a weak or blocked stub and the note would become speculation
- the content would be better expressed as one row in a manifest or queue
- no one can say what should trigger the next update

## Batch checklist
Every batch that adds or materially expands a maintained note should also update:
- `indexes/coverage.md`
- `indexes/source-map.md` when a new raw or manifest surface is involved
- `indexes/stub-replacement-queue.md` if the note depends on stub-backed sources
- `activity/log.md`

## Related
- [[ingest|Ingest Contract]]
- [[provenance|Provenance Contract]]
