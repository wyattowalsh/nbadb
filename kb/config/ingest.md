# Ingest Contract

## Purpose
Use this file to keep `raw` intake consistent across future KB batches.

## Defaults
- Keep `raw` append-only.
- Use `raw/sources/internal/` and `raw/sources/external/` for exact captures where practical.
- Use `raw/extracts/` for normalized summaries, manifests, or grouped extracts.
- Use `raw/assets/` for local supporting files that materially support a source.
- For sources over `50 MB`, prefer a pointer/stub note with checksum, size, original location, and import notes.

## First-wave collections
- project canon
- public docs contract
- upstream NBA API contract
- endpoint coverage and audit surfaces
- analytics skill and query surfaces
- Kaggle distribution surfaces

## Batch rule
Every ingest batch must update:
- the corresponding `raw` path
- `indexes/source-map.md`
- `indexes/coverage.md` if `wiki` coverage changed
- `activity/log.md`
- `indexes/stub-replacement-queue.md` if the batch creates or resolves stub-backed sources

## Related
- [[note-admission|Note Admission]]
- [[provenance|Provenance Contract]]
