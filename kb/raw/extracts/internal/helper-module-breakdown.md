# Helper Module Breakdown

## Purpose
Grouped internal extract for the reusable chat skill helper modules under `chat/skills/nba-data-analytics/scripts/`.

## High-value paths
- `chat/skills/nba-data-analytics/scripts/`
- `chat/skills/nba-data-analytics/scripts/court.py`
- `chat/skills/nba-data-analytics/scripts/compare.py`
- `chat/skills/nba-data-analytics/scripts/similarity.py`
- `chat/skills/nba-data-analytics/scripts/lineups.py`
- `chat/skills/nba-data-analytics/scripts/trends.py`
- `chat/skills/nba-data-analytics/scripts/team_colors.py`
- `chat/skills/nba-data-analytics/scripts/season_utils.py`
- `chat/server/_preamble.py`
- `tests/unit/chat/test_court.py`
- `tests/unit/chat/test_compare.py`
- `tests/unit/chat/test_similarity.py`
- `tests/unit/chat/test_lineups.py`
- `tests/unit/chat/test_trends.py`
- `tests/unit/chat/test_skill_scripts.py`
- `tests/unit/chat/test_skill_safety.py`

## Notes
- Visualization helpers: `court.py` draws half-court geometry and produces shot charts, heatmaps, zone charts, and side-by-side shot comparisons.
- Comparison helpers: `compare.py` builds side-by-side player tables, percentile views, radar charts, and pace-normalized rate stats.
- Similarity helpers: `similarity.py` normalizes numeric profiles and exposes nearest-neighbor, clustering, and career-shape similarity utilities.
- Lineup helpers: `lineups.py` computes on/off deltas, aggregates two-man combinations from lineup rows, and charts top or bottom lineup units.
- Trend helpers: `trends.py` adds rolling windows, detects threshold streaks, flags breakout games, and projects season totals from current pace.
- Presentation helpers: `team_colors.py` is the 30-team hex palette lookup used to keep charts aligned with NBA team branding.
- Season helpers: `season_utils.py` converts between `YYYY-YY` and `2YYYY` season formats and resolves the current NBA season from a date.
- Runtime wiring: `_preamble.py` prepends the scripts directory to `sys.path` and imports these helpers into the chat execution surface.
- Test coverage is split by helper domain, while `test_skill_safety.py` enforces the import-safety boundary for the analytics scripts that execute inside chat.

## Planned wiki coverage
- `wiki/agent/chat-helper-surface.md`
- `wiki/agent/visualization-helpers.md`
- `wiki/agent/comparison-and-similarity.md`
- `wiki/agent/lineups-and-trends.md`

## Provenance
- `chat/skills/nba-data-analytics/scripts/court.py`
- `chat/skills/nba-data-analytics/scripts/compare.py`
- `chat/skills/nba-data-analytics/scripts/similarity.py`
- `chat/skills/nba-data-analytics/scripts/lineups.py`
- `chat/skills/nba-data-analytics/scripts/trends.py`
- `chat/skills/nba-data-analytics/scripts/team_colors.py`
- `chat/skills/nba-data-analytics/scripts/season_utils.py`
- `chat/server/_preamble.py`
- `tests/unit/chat/test_court.py`
- `tests/unit/chat/test_compare.py`
- `tests/unit/chat/test_similarity.py`
- `tests/unit/chat/test_lineups.py`
- `tests/unit/chat/test_trends.py`
- `tests/unit/chat/test_skill_scripts.py`
- `tests/unit/chat/test_skill_safety.py`
