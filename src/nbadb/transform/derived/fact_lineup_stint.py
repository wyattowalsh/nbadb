from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

import polars as pl

from nbadb.transform.base import BaseTransformer

LINEUP_STINT_ALGORITHM_VERSION = "game_rotation_exact_five_v1"


@dataclass(frozen=True)
class _Interval:
    game_id: str
    team_id: int
    player_id: int
    start: float
    end: float
    side: str


def _lineup_id(players: tuple[int, ...]) -> str:
    return "-".join(str(player_id) for player_id in players)


class FactLineupStintTransformer(BaseTransformer):
    """Create stints only when GameRotation proves five players per side."""

    output_table: ClassVar[str] = "fact_lineup_stint"
    depends_on: ClassVar[list[str]] = ["fact_rotation", "fact_statistical_possession"]

    @staticmethod
    def _intervals(frame: pl.DataFrame) -> list[_Interval]:
        by_key: dict[tuple[str, int, int, float], dict[str, Any]] = {}
        intervals: list[_Interval] = []
        for row in frame.to_dicts():
            if row.get("in_time_real") is None or row.get("out_time_real") is None:
                continue
            game_id = str(row["game_id"])
            team_id = int(row["team_id"])
            player_id = int(row["player_id"])
            start = float(row["in_time_real"])
            end = float(row["out_time_real"])
            key = (game_id, team_id, player_id, start)
            prior = by_key.get(key)
            if prior is not None and prior != row:
                raise ValueError(
                    "fact_lineup_stint: conflicting GameRotation rows for "
                    f"game/team/player/start key {key!r}"
                )
            by_key[key] = row
        for row in by_key.values():
            start = float(row["in_time_real"])
            end = float(row["out_time_real"])
            if not start >= 0 or not end > start:
                raise ValueError("fact_lineup_stint: invalid non-positive rotation interval")
            intervals.append(
                _Interval(
                    game_id=str(row["game_id"]),
                    team_id=int(row["team_id"]),
                    player_id=int(row["player_id"]),
                    start=start,
                    end=end,
                    side=str(row["side"]),
                )
            )
        return intervals

    @staticmethod
    def _exact_segments(intervals: list[_Interval]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        by_game: dict[str, list[_Interval]] = {}
        for interval in intervals:
            by_game.setdefault(interval.game_id, []).append(interval)
        for game_id, game_intervals in sorted(by_game.items()):
            side_teams: dict[str, set[int]] = {"home": set(), "away": set()}
            for interval in game_intervals:
                if interval.side in side_teams:
                    side_teams[interval.side].add(interval.team_id)
            if len(side_teams["home"]) != 1 or len(side_teams["away"]) != 1:
                continue
            home_team_id = next(iter(side_teams["home"]))
            away_team_id = next(iter(side_teams["away"]))
            if home_team_id == away_team_id:
                continue
            boundaries = sorted(
                {value for interval in game_intervals for value in (interval.start, interval.end)}
            )
            raw: list[dict[str, Any]] = []
            for start, end in zip(boundaries, boundaries[1:], strict=False):
                if end <= start:
                    continue
                active: dict[int, set[int]] = {home_team_id: set(), away_team_id: set()}
                source_count = 0
                for interval in game_intervals:
                    if (
                        interval.start <= start
                        and interval.end >= end
                        and interval.team_id in active
                    ):
                        active[interval.team_id].add(interval.player_id)
                        source_count += 1
                home_players = tuple(sorted(active[home_team_id]))
                away_players = tuple(sorted(active[away_team_id]))
                if len(home_players) != 5 or len(away_players) != 5 or source_count != 10:
                    continue
                if set(home_players).intersection(away_players):
                    raise ValueError(
                        "fact_lineup_stint: one player appears on both teams in an exact segment"
                    )
                candidate = {
                    "game_id": game_id,
                    "home_team_id": home_team_id,
                    "away_team_id": away_team_id,
                    "home_lineup_id": _lineup_id(home_players),
                    "away_lineup_id": _lineup_id(away_players),
                    "home_players": home_players,
                    "away_players": away_players,
                    "stint_start_elapsed_tenths": start,
                    "stint_end_elapsed_tenths": end,
                    "source_interval_count": source_count,
                }
                if (
                    raw
                    and raw[-1]["home_players"] == home_players
                    and raw[-1]["away_players"] == away_players
                    and raw[-1]["stint_end_elapsed_tenths"] == start
                ):
                    raw[-1]["stint_end_elapsed_tenths"] = end
                else:
                    raw.append(candidate)
            output.extend(raw)
        return output

    @staticmethod
    def _attach_responses(
        segments: list[dict[str, Any]], possessions: pl.DataFrame
    ) -> list[dict[str, Any]]:
        by_game: dict[str, list[dict[str, Any]]] = {}
        for possession in possessions.to_dicts():
            by_game.setdefault(str(possession["game_id"]), []).append(possession)
        output: list[dict[str, Any]] = []
        stint_number_by_game: dict[str, int] = {}
        for segment in segments:
            game_id = str(segment["game_id"])
            start = float(segment["stint_start_elapsed_tenths"])
            end = float(segment["stint_end_elapsed_tenths"])
            contained: list[dict[str, Any]] = []
            crossings = 0
            unplaced = 0
            for possession in by_game.get(game_id, []):
                p_start = possession.get("start_elapsed_tenths")
                p_end = possession.get("end_elapsed_tenths")
                if p_start is None or p_end is None:
                    unplaced += 1
                    continue
                overlaps = float(p_end) > start and float(p_start) < end
                is_contained = float(p_start) >= start and float(p_end) <= end
                if is_contained:
                    contained.append(possession)
                elif overlaps:
                    crossings += 1
            complete_possessions = [
                possession
                for possession in contained
                if possession.get("is_complete") is True and possession.get("is_ambiguous") is False
            ]
            home_team_id = int(segment["home_team_id"])
            away_team_id = int(segment["away_team_id"])
            valid_team_ids = {home_team_id, away_team_id}
            has_foreign_offense_team = any(
                possession.get("offense_team_id") not in valid_team_ids
                for possession in complete_possessions
            )
            has_failed_official_reconciliation = any(
                possession.get("team_game_points_reconciled") is False
                or possession.get("team_possessions_reconciled") is False
                for possession in complete_possessions
            )
            all_responses_usable = (
                crossings == 0
                and unplaced == 0
                and len(complete_possessions) == len(contained)
                and all(possession.get("points") is not None for possession in contained)
                and not has_foreign_offense_team
                and not has_failed_official_reconciliation
            )
            home_possessions = sum(
                1
                for possession in complete_possessions
                if possession.get("offense_team_id") == home_team_id
            )
            away_possessions = sum(
                1
                for possession in complete_possessions
                if possession.get("offense_team_id") == away_team_id
            )
            home_points = (
                sum(
                    int(possession["points"])
                    for possession in complete_possessions
                    if possession.get("offense_team_id") == home_team_id
                )
                if all_responses_usable
                else None
            )
            away_points = (
                sum(
                    int(possession["points"])
                    for possession in complete_possessions
                    if possession.get("offense_team_id") == away_team_id
                )
                if all_responses_usable
                else None
            )
            stint_number_by_game[game_id] = stint_number_by_game.get(game_id, 0) + 1
            stint_number = stint_number_by_game[game_id]
            output.append(
                {
                    "game_id": game_id,
                    "stint_number": stint_number,
                    "stint_id": f"{game_id}:{stint_number}",
                    "home_team_id": home_team_id,
                    "away_team_id": away_team_id,
                    "home_lineup_id": segment["home_lineup_id"],
                    "away_lineup_id": segment["away_lineup_id"],
                    "home_player_ids": ",".join(str(value) for value in segment["home_players"]),
                    "away_player_ids": ",".join(str(value) for value in segment["away_players"]),
                    "stint_start_elapsed_tenths": start,
                    "stint_end_elapsed_tenths": end,
                    "duration_seconds": (end - start) / 10.0,
                    "source_interval_count": int(segment["source_interval_count"]),
                    "source_possession_count": len(contained),
                    "first_possession_number": min(
                        (int(possession["possession_number"]) for possession in contained),
                        default=None,
                    ),
                    "last_possession_number": max(
                        (int(possession["possession_number"]) for possession in contained),
                        default=None,
                    ),
                    "first_source_action_number": min(
                        (int(possession["start_action_number"]) for possession in contained),
                        default=None,
                    ),
                    "last_source_action_number": max(
                        (int(possession["end_action_number"]) for possession in contained),
                        default=None,
                    ),
                    "home_possessions": home_possessions,
                    "away_possessions": away_possessions,
                    "home_points": home_points,
                    "away_points": away_points,
                    "home_net_points": home_points - away_points
                    if home_points is not None and away_points is not None
                    else None,
                    "possession_boundary_crossings": crossings,
                    "unplaced_possession_count": unplaced,
                    "lineup_is_exact": True,
                    "response_is_complete": all_responses_usable,
                    "is_ambiguous": not all_responses_usable,
                    "ambiguity_reason": (
                        None
                        if all_responses_usable
                        else (
                            "foreign_offense_team_in_possession_response"
                            if has_foreign_offense_team
                            else (
                                "official_team_reconciliation_failed"
                                if has_failed_official_reconciliation
                                else "possession_response_incomplete_or_crosses_stint"
                            )
                        )
                    ),
                    "algorithm_version": LINEUP_STINT_ALGORITHM_VERSION,
                }
            )
        return output

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        intervals = self._intervals(staging["fact_rotation"].collect())
        segments = self._exact_segments(intervals)
        output = self._attach_responses(
            segments,
            staging["fact_statistical_possession"].collect(),
        )
        return pl.DataFrame(output, schema=_OUTPUT_SCHEMA, orient="row")


_OUTPUT_SCHEMA = pl.Schema(
    {
        "game_id": pl.String,
        "stint_number": pl.Int64,
        "stint_id": pl.String,
        "home_team_id": pl.Int64,
        "away_team_id": pl.Int64,
        "home_lineup_id": pl.String,
        "away_lineup_id": pl.String,
        "home_player_ids": pl.String,
        "away_player_ids": pl.String,
        "stint_start_elapsed_tenths": pl.Float64,
        "stint_end_elapsed_tenths": pl.Float64,
        "duration_seconds": pl.Float64,
        "source_interval_count": pl.Int64,
        "source_possession_count": pl.Int64,
        "first_possession_number": pl.Int64,
        "last_possession_number": pl.Int64,
        "first_source_action_number": pl.Int64,
        "last_source_action_number": pl.Int64,
        "home_possessions": pl.Int64,
        "away_possessions": pl.Int64,
        "home_points": pl.Int64,
        "away_points": pl.Int64,
        "home_net_points": pl.Int64,
        "possession_boundary_crossings": pl.Int64,
        "unplaced_possession_count": pl.Int64,
        "lineup_is_exact": pl.Boolean,
        "response_is_complete": pl.Boolean,
        "is_ambiguous": pl.Boolean,
        "ambiguity_reason": pl.String,
        "algorithm_version": pl.String,
    }
)


__all__ = ["FactLineupStintTransformer", "LINEUP_STINT_ALGORITHM_VERSION"]
