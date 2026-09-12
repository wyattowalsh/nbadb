from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, ClassVar

import polars as pl

from nbadb.transform.base import BaseTransformer

POSSESSION_ALGORITHM_VERSION = "nba_stats_possession_v1"

_CLOCK_RE = re.compile(
    r"^PT(?:(?P<minutes>\d+)M)?(?P<seconds>\d+(?:\.\d+)?)S$",
    re.IGNORECASE,
)
_FREE_THROW_SEQUENCE_RE = re.compile(r"(?P<attempt>\d+)\s+of\s+(?P<total>\d+)", re.IGNORECASE)
_ADMIN_ACTIONS = {
    "foul",
    "timeout",
    "substitution",
    "replay",
    "instant replay",
    "review",
    "game",
}
_POSSESSION_LOSS_VIOLATIONS = (
    "backcourt",
    "double dribble",
    "kicked ball turnover",
    "offensive goaltending",
    "out of bounds lost ball",
    "palming",
    "shot clock",
    "travel",
)


def _text(value: object) -> str:
    return " ".join(str(value or "").strip().lower().replace("-", " ").split())


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _clock_to_elapsed_tenths(period: int, clock: object) -> int | None:
    """Convert the V3 ISO period clock to elapsed game tenths.

    Regulation periods are 12 minutes and overtime periods are 5 minutes.  A
    malformed clock remains unknown; callers must not use a guessed time.
    """
    if period < 1 or not isinstance(clock, str):
        return None
    match = _CLOCK_RE.fullmatch(clock.strip())
    if match is None:
        return None
    minutes = int(match.group("minutes") or 0)
    seconds = float(match.group("seconds"))
    remaining_tenths = round((minutes * 60 + seconds) * 10)
    period_tenths = 7_200 if period <= 4 else 3_000
    if not 0 <= remaining_tenths <= period_tenths:
        return None
    period_start = (period - 1) * 7_200 if period <= 4 else 28_800 + (period - 5) * 3_000
    return period_start + period_tenths - remaining_tenths


def _is_made(row: dict[str, Any]) -> bool:
    result = _text(row.get("shot_result"))
    description = _text(row.get("description"))
    return result == "made" or " made " in f" {description} " or description.startswith("made ")


def _is_free_throw(row: dict[str, Any]) -> bool:
    action = _text(row.get("action_type"))
    description = _text(row.get("description"))
    return "free throw" in action or "free throw" in description


def _is_non_possession_free_throw(row: dict[str, Any]) -> bool:
    payload = f"{_text(row.get('sub_type'))} {_text(row.get('description'))}"
    return any(
        label in payload for label in ("technical", "flagrant", "clear path", "away from play")
    )


def _is_final_free_throw(row: dict[str, Any]) -> bool:
    payload = f"{_text(row.get('sub_type'))} {_text(row.get('description'))}"
    match = _FREE_THROW_SEQUENCE_RE.search(payload)
    return match is not None and match.group("attempt") == match.group("total")


def _event_kind(row: dict[str, Any]) -> str:
    action = _text(row.get("action_type"))
    description = _text(row.get("description"))
    subtype = _text(row.get("sub_type"))
    payload = f"{action} {subtype} {description}"
    if action == "period" or "end of period" in payload or "end period" in payload:
        return "period_end"
    if _is_free_throw(row):
        return "free_throw"
    if action in {"2pt", "3pt", "shot"} or _optional_int(row.get("is_field_goal")) == 1:
        return "made_field_goal" if _is_made(row) else "missed_field_goal"
    if "offensive rebound" in payload or "rebound offensive" in payload:
        return "offensive_rebound"
    if "defensive rebound" in payload or "rebound defensive" in payload:
        return "defensive_rebound"
    if action == "rebound" or "team rebound" in payload:
        return "rebound"
    if action == "turnover" or "turnover" in payload:
        return "turnover"
    if action == "jump ball" or action == "jumpball" or "jump ball" in payload:
        return "jump_ball"
    if action == "violation" or "violation" in payload:
        return "violation"
    if action in _ADMIN_ACTIONS:
        return "administrative"
    return "other"


def _location_side(value: object) -> str | None:
    normalized = _text(value)
    if normalized in {"h", "home"}:
        return "home"
    if normalized in {"v", "visitor", "away"}:
        return "away"
    return None


@dataclass
class _Possession:
    game_id: str
    number: int
    period: int
    offense_team_id: int | None
    defense_team_id: int | None
    home_team_id: int | None
    away_team_id: int | None
    start_action_number: int
    start_clock: str | None
    start_elapsed_tenths: int | None
    score_before_home: int | None
    score_before_away: int | None
    end_action_number: int = 0
    end_clock: str | None = None
    end_elapsed_tenths: int | None = None
    score_after_home: int | None = None
    score_after_away: int | None = None
    event_count: int = 0
    field_goal_attempts: int = 0
    free_throw_attempts: int = 0
    non_possession_free_throw_attempts: int = 0
    non_possession_free_throw_points: int = 0
    turnovers: int = 0
    offensive_rebounds: int = 0
    legal_control_boundary_count: int = 0
    derived_points: int = 0
    derived_points_complete: bool = True
    ambiguity: set[str] = field(default_factory=set)

    def consume(self, row: dict[str, Any], kind: str) -> None:
        self.end_action_number = int(row["action_number"])
        self.end_clock = row.get("clock") if isinstance(row.get("clock"), str) else None
        self.end_elapsed_tenths = _clock_to_elapsed_tenths(self.period, row.get("clock"))
        self.event_count += 1
        if kind in {"made_field_goal", "missed_field_goal"}:
            self.field_goal_attempts += 1
            if kind == "made_field_goal":
                shot_value = _optional_int(row.get("shot_value"))
                if shot_value in {2, 3}:
                    self.derived_points += shot_value
                else:
                    self.derived_points_complete = False
        elif kind == "free_throw":
            if _is_non_possession_free_throw(row):
                self.non_possession_free_throw_attempts += 1
                if _is_made(row):
                    self.non_possession_free_throw_points += 1
            else:
                self.free_throw_attempts += 1
                if _is_made(row):
                    self.derived_points += 1
        elif kind == "turnover":
            self.turnovers += 1
        elif kind == "offensive_rebound":
            self.offensive_rebounds += 1
        if kind in {"turnover", "defensive_rebound", "jump_ball", "period_end", "violation"}:
            self.legal_control_boundary_count += 1


class FactStatisticalPossessionTransformer(BaseTransformer):
    """Build conservative NBA Stats analytical possessions from V3 events.

    This intentionally is not a reconstruction of every legal team-control
    interval.  It counts statistical possessions only at source-supported
    terminal events and keeps uncertain sequences as flagged rows.
    """

    output_table: ClassVar[str] = "fact_statistical_possession"
    depends_on: ClassVar[list[str]] = [
        "fact_play_by_play",
        "fact_team_game",
        "fact_box_score_advanced_team",
    ]

    @staticmethod
    def _deduplicate(frame: pl.DataFrame) -> list[dict[str, Any]]:
        rows = frame.to_dicts()
        by_key: dict[tuple[str, int], dict[str, Any]] = {}
        for row in rows:
            key = (str(row["game_id"]), int(row["action_number"]))
            prior = by_key.get(key)
            if prior is not None and prior != row:
                raise ValueError(
                    "fact_statistical_possession: conflicting play-by-play rows "
                    f"for game/action key {key!r}"
                )
            by_key[key] = row
        return sorted(
            by_key.values(),
            key=lambda row: (
                str(row["game_id"]),
                int(row["period"]),
                int(row["action_number"]),
            ),
        )

    @staticmethod
    def _team_authority(rows: list[dict[str, Any]]) -> tuple[int | None, int | None, set[int]]:
        home_ids: set[int] = set()
        away_ids: set[int] = set()
        all_ids: set[int] = set()
        for row in rows:
            team_id = _optional_int(row.get("team_id"))
            if team_id is None or team_id <= 0:
                continue
            all_ids.add(team_id)
            side = _location_side(row.get("location"))
            if side == "home":
                home_ids.add(team_id)
            elif side == "away":
                away_ids.add(team_id)
        home = next(iter(home_ids)) if len(home_ids) == 1 else None
        away = next(iter(away_ids)) if len(away_ids) == 1 else None
        if home == away:
            home = away = None
        return home, away, all_ids

    @staticmethod
    def _score(row: dict[str, Any], key: str) -> int | None:
        value = _optional_int(row.get(key))
        return value if value is not None and value >= 0 else None

    @staticmethod
    def _official_authority(
        frame: pl.DataFrame,
        *,
        value_column: str,
    ) -> dict[tuple[str, int], int | float | None]:
        authority: dict[tuple[str, int], int | float | None] = {}
        if not {"game_id", "team_id", value_column}.issubset(frame.columns):
            return authority
        for row in frame.select("game_id", "team_id", value_column).to_dicts():
            key = (str(row["game_id"]), int(row["team_id"]))
            value = row[value_column]
            prior = authority.get(key)
            if key in authority and prior != value:
                raise ValueError(
                    "fact_statistical_possession: conflicting official team rows "
                    f"for game/team key {key!r} and field {value_column!r}"
                )
            authority[key] = value
        return authority

    @staticmethod
    def _starts_possession(kind: str, row: dict[str, Any]) -> bool:
        if kind in {
            "made_field_goal",
            "missed_field_goal",
            "turnover",
            "offensive_rebound",
            "defensive_rebound",
            "rebound",
            "free_throw",
            "violation",
        }:
            if kind == "free_throw" and _is_non_possession_free_throw(row):
                return False
            return _optional_int(row.get("team_id")) is not None
        return False

    @staticmethod
    def _to_row(possession: _Possession, closure_reason: str, *, complete: bool) -> dict[str, Any]:
        scoreboard_points: int | None = None
        if possession.offense_team_id == possession.home_team_id:
            if possession.score_before_home is not None and possession.score_after_home is not None:
                scoreboard_points = possession.score_after_home - possession.score_before_home
        elif (
            possession.offense_team_id == possession.away_team_id
            and possession.score_before_away is not None
            and possession.score_after_away is not None
        ):
            scoreboard_points = possession.score_after_away - possession.score_before_away
        if scoreboard_points is not None and scoreboard_points < 0:
            possession.ambiguity.add("score_correction")
            scoreboard_points = None
        derived_points = possession.derived_points if possession.derived_points_complete else None
        points = scoreboard_points if scoreboard_points is not None else derived_points
        points_reconciled = (
            scoreboard_points == derived_points
            if scoreboard_points is not None and derived_points is not None
            else None
        )
        if points_reconciled is False:
            possession.ambiguity.add("score_event_mismatch")
        if possession.offense_team_id is None:
            possession.ambiguity.add("unknown_offense_team")
        ambiguity_reason = ";".join(sorted(possession.ambiguity)) or None
        return {
            "game_id": possession.game_id,
            "possession_number": possession.number,
            "period": possession.period,
            "offense_team_id": possession.offense_team_id,
            "defense_team_id": possession.defense_team_id,
            "home_team_id": possession.home_team_id,
            "away_team_id": possession.away_team_id,
            "start_action_number": possession.start_action_number,
            "end_action_number": possession.end_action_number,
            "start_clock": possession.start_clock,
            "end_clock": possession.end_clock,
            "start_elapsed_tenths": possession.start_elapsed_tenths,
            "end_elapsed_tenths": possession.end_elapsed_tenths,
            "event_count": possession.event_count,
            "field_goal_attempts": possession.field_goal_attempts,
            "free_throw_attempts": possession.free_throw_attempts,
            "non_possession_free_throw_attempts": (possession.non_possession_free_throw_attempts),
            "non_possession_free_throw_points": possession.non_possession_free_throw_points,
            "turnovers": possession.turnovers,
            "offensive_rebounds": possession.offensive_rebounds,
            "points": points,
            "derived_event_points": derived_points,
            "scoreboard_points": scoreboard_points,
            "points_reconciled": points_reconciled,
            "score_before_home": possession.score_before_home,
            "score_before_away": possession.score_before_away,
            "score_after_home": possession.score_after_home,
            "score_after_away": possession.score_after_away,
            "statistical_possession_count": 1,
            "legal_control_boundary_count": possession.legal_control_boundary_count,
            "closure_reason": closure_reason,
            "is_complete": complete,
            "is_ambiguous": ambiguity_reason is not None,
            "ambiguity_reason": ambiguity_reason,
            "algorithm_version": POSSESSION_ALGORITHM_VERSION,
        }

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        source = staging["fact_play_by_play"].collect()
        rows = self._deduplicate(source)
        output: list[dict[str, Any]] = []

        by_game: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_game.setdefault(str(row["game_id"]), []).append(row)

        for game_id, game_rows in sorted(by_game.items()):
            home_team_id, away_team_id, all_team_ids = self._team_authority(game_rows)
            last_home_score: int | None = None
            last_away_score: int | None = None
            current: _Possession | None = None
            pending_made_field_goal = False
            number = 0

            def close(reason: str, *, complete: bool = True) -> None:
                nonlocal current, pending_made_field_goal
                if current is None:
                    return
                output.append(self._to_row(current, reason, complete=complete))
                current = None
                pending_made_field_goal = False

            for row in game_rows:
                kind = _event_kind(row)
                team_id = _optional_int(row.get("team_id"))
                period = int(row["period"])

                # A made field goal is held open across administrative events so
                # an immediately following ordinary and-one free throw remains
                # in the same statistical possession.
                if pending_made_field_goal and kind not in {"administrative", "free_throw"}:
                    close("made_field_goal")

                if current is not None and period != current.period:
                    current.ambiguity.add("period_changed_without_period_end")
                    close("period_transition", complete=False)

                if current is None and self._starts_possession(kind, row):
                    number += 1
                    defense_team_id = None
                    if team_id is not None and len(all_team_ids) == 2:
                        defense_team_id = next(iter(all_team_ids - {team_id}), None)
                    current = _Possession(
                        game_id=game_id,
                        number=number,
                        period=period,
                        offense_team_id=team_id,
                        defense_team_id=defense_team_id,
                        home_team_id=home_team_id,
                        away_team_id=away_team_id,
                        start_action_number=int(row["action_number"]),
                        start_clock=row.get("clock") if isinstance(row.get("clock"), str) else None,
                        start_elapsed_tenths=_clock_to_elapsed_tenths(period, row.get("clock")),
                        score_before_home=last_home_score,
                        score_before_away=last_away_score,
                    )

                score_home = self._score(row, "score_home")
                score_away = self._score(row, "score_away")
                if score_home is not None:
                    last_home_score = score_home
                if score_away is not None:
                    last_away_score = score_away

                if current is None:
                    continue
                current.score_after_home = last_home_score
                current.score_after_away = last_away_score
                current.consume(row, kind)

                if (
                    team_id is not None
                    and current.offense_team_id is not None
                    and kind
                    not in {
                        "defensive_rebound",
                        "rebound",
                        "jump_ball",
                        "administrative",
                    }
                    and team_id != current.offense_team_id
                ):
                    current.ambiguity.add("opposing_team_event_inside_possession")

                if kind == "made_field_goal":
                    pending_made_field_goal = True
                elif kind == "offensive_rebound":
                    pending_made_field_goal = False
                elif kind == "defensive_rebound":
                    close("defensive_rebound")
                elif kind == "rebound":
                    if team_id is not None and team_id == current.offense_team_id:
                        current.offensive_rebounds += 1
                    elif team_id is not None and current.offense_team_id is not None:
                        close("defensive_or_team_rebound")
                    else:
                        current.ambiguity.add("unclassified_rebound")
                elif kind == "turnover":
                    close("turnover")
                elif kind == "free_throw":
                    if _is_non_possession_free_throw(row):
                        current.ambiguity.add("non_possession_free_throw")
                    elif _is_final_free_throw(row):
                        if _is_made(row):
                            close("made_final_free_throw")
                        else:
                            pending_made_field_goal = False
                    else:
                        payload = f"{_text(row.get('sub_type'))} {_text(row.get('description'))}"
                        if _FREE_THROW_SEQUENCE_RE.search(payload) is None:
                            current.ambiguity.add("free_throw_sequence_unknown")
                elif kind == "violation":
                    payload = f"{_text(row.get('sub_type'))} {_text(row.get('description'))}"
                    if any(label in payload for label in _POSSESSION_LOSS_VIOLATIONS):
                        close("possession_loss_violation")
                    else:
                        current.ambiguity.add("violation_control_unknown")
                elif kind == "jump_ball":
                    current.ambiguity.add("jump_ball_control_unknown")
                elif kind == "period_end":
                    close("period_end")

            if current is not None:
                current.ambiguity.add("unterminated_game_sequence")
                close("end_of_available_events", complete=False)

        official_points = self._official_authority(
            staging["fact_team_game"].collect(), value_column="pts"
        )
        official_possessions = self._official_authority(
            staging["fact_box_score_advanced_team"].collect(), value_column="poss"
        )
        derived_points: dict[tuple[str, int], int] = {}
        derived_possessions: dict[tuple[str, int], int] = {}
        for row in output:
            team_id = row["offense_team_id"]
            if not isinstance(team_id, int):
                continue
            key = (str(row["game_id"]), team_id)
            if isinstance(row["points"], int):
                derived_points[key] = derived_points.get(key, 0) + row["points"]
            if row["is_complete"] is True and row["is_ambiguous"] is False:
                derived_possessions[key] = derived_possessions.get(key, 0) + 1
        for row in output:
            team_id = row["offense_team_id"]
            key = (str(row["game_id"]), team_id) if isinstance(team_id, int) else None
            team_derived_points = derived_points.get(key) if key is not None else None
            team_official_points = official_points.get(key) if key is not None else None
            team_derived_possessions = derived_possessions.get(key) if key is not None else None
            team_official_possessions = official_possessions.get(key) if key is not None else None
            row["derived_team_game_points"] = team_derived_points
            row["official_team_game_points"] = team_official_points
            row["team_game_points_reconciled"] = (
                team_derived_points == team_official_points
                if team_derived_points is not None and team_official_points is not None
                else None
            )
            row["derived_complete_team_possessions"] = team_derived_possessions
            row["official_team_possessions"] = team_official_possessions
            row["team_possessions_reconciled"] = (
                float(team_derived_possessions) == float(team_official_possessions)
                if team_derived_possessions is not None and team_official_possessions is not None
                else None
            )

        return pl.DataFrame(output, schema=_OUTPUT_SCHEMA, orient="row")


_OUTPUT_SCHEMA = pl.Schema(
    {
        "game_id": pl.String,
        "possession_number": pl.Int64,
        "period": pl.Int64,
        "offense_team_id": pl.Int64,
        "defense_team_id": pl.Int64,
        "home_team_id": pl.Int64,
        "away_team_id": pl.Int64,
        "start_action_number": pl.Int64,
        "end_action_number": pl.Int64,
        "start_clock": pl.String,
        "end_clock": pl.String,
        "start_elapsed_tenths": pl.Int64,
        "end_elapsed_tenths": pl.Int64,
        "event_count": pl.Int64,
        "field_goal_attempts": pl.Int64,
        "free_throw_attempts": pl.Int64,
        "non_possession_free_throw_attempts": pl.Int64,
        "non_possession_free_throw_points": pl.Int64,
        "turnovers": pl.Int64,
        "offensive_rebounds": pl.Int64,
        "points": pl.Int64,
        "derived_event_points": pl.Int64,
        "scoreboard_points": pl.Int64,
        "points_reconciled": pl.Boolean,
        "score_before_home": pl.Int64,
        "score_before_away": pl.Int64,
        "score_after_home": pl.Int64,
        "score_after_away": pl.Int64,
        "statistical_possession_count": pl.Int64,
        "legal_control_boundary_count": pl.Int64,
        "closure_reason": pl.String,
        "is_complete": pl.Boolean,
        "is_ambiguous": pl.Boolean,
        "ambiguity_reason": pl.String,
        "algorithm_version": pl.String,
        "derived_team_game_points": pl.Int64,
        "official_team_game_points": pl.Int64,
        "team_game_points_reconciled": pl.Boolean,
        "derived_complete_team_possessions": pl.Int64,
        "official_team_possessions": pl.Float64,
        "team_possessions_reconciled": pl.Boolean,
    }
)


__all__ = [
    "FactStatisticalPossessionTransformer",
    "POSSESSION_ALGORITHM_VERSION",
    "_clock_to_elapsed_tenths",
]
