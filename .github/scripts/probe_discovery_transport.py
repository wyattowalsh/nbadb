from __future__ import annotations

import argparse
import json
import re
from typing import Any

from nbadb.extract.stats.game_log import LeagueGameLogExtractor
from nbadb.extract.stats.player_info import CommonAllPlayersExtractor
from nbadb.orchestrate.extractor_runner import _sync_extract

_SAFE_TOKEN = re.compile(r"[^A-Za-z0-9_.-]")


def _safe_token(value: object, default: str) -> str:
    token = _SAFE_TOKEN.sub("_", str(value or ""))[:80]
    return token or default


def _failure(endpoint: str, kind: str, error_type: str) -> dict[str, object]:
    return {
        "status": "failed",
        "endpoint": _safe_token(endpoint, "unknown"),
        "failure_kind": _safe_token(kind, "unknown"),
        "error_type": _safe_token(error_type, "ProbeFailed"),
    }


def run_probe(*, request_timeout_seconds: int, season: str) -> dict[str, object]:
    probes: tuple[tuple[str, object, dict[str, Any], frozenset[str]], ...] = (
        (
            "common_all_players",
            CommonAllPlayersExtractor(),
            {
                "season": season,
                "is_only_current_season": 0,
                "allow_static_fallback": False,
                "timeout": request_timeout_seconds,
            },
            frozenset({"person_id", "team_id"}),
        ),
        (
            "league_game_log",
            LeagueGameLogExtractor(),
            {
                "season": season,
                "season_type": "Regular Season",
                "timeout": request_timeout_seconds,
            },
            frozenset({"game_id", "game_date", "team_id"}),
        ),
    )
    endpoints: dict[str, dict[str, int]] = {}
    for endpoint, extractor, params, required_columns in probes:
        try:
            frame = _sync_extract(extractor, **params)
        except Exception as exc:
            return _failure(endpoint, "exception", type(exc).__name__)
        columns = frozenset(getattr(frame, "columns", ()))
        rows = getattr(frame, "height", None)
        if isinstance(rows, bool) or not isinstance(rows, int) or rows <= 0:
            return _failure(endpoint, "empty", "ProbeContractError")
        if not required_columns <= columns:
            return _failure(endpoint, "missing_columns", "ProbeContractError")
        if endpoint == "common_all_players":
            has_positive_player_team = False
            for row in frame.select("person_id", "team_id").iter_rows(named=True):
                try:
                    player_id = int(row["person_id"])
                    team_id = int(row["team_id"])
                except (TypeError, ValueError):
                    continue
                if player_id > 0 and team_id > 0:
                    has_positive_player_team = True
                    break
            if not has_positive_player_team:
                return _failure(endpoint, "invalid_values", "ProbeContractError")
        endpoints[endpoint] = {"rows": rows}
    return {"status": "passed", "endpoints": endpoints}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe NBA discovery transport through the installed nbadb extraction stack."
    )
    parser.add_argument("--request-timeout-seconds", type=int, required=True)
    parser.add_argument("--season", required=True)
    args = parser.parse_args()
    if args.request_timeout_seconds <= 0:
        parser.error("--request-timeout-seconds must be positive")

    result = run_probe(
        request_timeout_seconds=args.request_timeout_seconds,
        season=args.season,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
