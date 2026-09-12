from __future__ import annotations

from typing import Any

import polars as pl
import pytest

from nbadb.schemas.star.fact_lineup_stint import FactLineupStintSchema
from nbadb.schemas.star.fact_rapm_design import FactRapmDesignSchema
from nbadb.schemas.star.fact_statistical_possession import (
    FactStatisticalPossessionSchema,
)
from nbadb.transform.derived.fact_lineup_stint import FactLineupStintTransformer
from nbadb.transform.derived.fact_rapm_design import FactRapmDesignTransformer
from nbadb.transform.derived.fact_statistical_possession import (
    FactStatisticalPossessionTransformer,
    _clock_to_elapsed_tenths,
)

GAME = "0022400001"
HOME = 1_610_612_741
AWAY = 1_610_612_742


def _event(
    action_number: int,
    *,
    team_id: int | None,
    location: str | None,
    action_type: str,
    clock: str,
    description: str = "",
    sub_type: str = "",
    shot_result: str | None = None,
    is_field_goal: int = 0,
    shot_value: int | None = None,
    score_home: str = "0",
    score_away: str = "0",
    period: int = 1,
) -> dict[str, Any]:
    return {
        "game_id": GAME,
        "action_number": action_number,
        "clock": clock,
        "period": period,
        "team_id": team_id,
        "location": location,
        "action_type": action_type,
        "sub_type": sub_type,
        "description": description,
        "shot_result": shot_result,
        "is_field_goal": is_field_goal,
        "shot_value": shot_value,
        "score_home": score_home,
        "score_away": score_away,
    }


def _possessions(
    events: list[dict[str, Any]],
    *,
    official_points: list[dict[str, Any]] | None = None,
    official_possessions: list[dict[str, Any]] | None = None,
) -> pl.DataFrame:
    points_frame = (
        pl.DataFrame(official_points)
        if official_points
        else pl.DataFrame(schema={"game_id": pl.String, "team_id": pl.Int64, "pts": pl.Int64})
    )
    possessions_frame = (
        pl.DataFrame(official_possessions)
        if official_possessions
        else pl.DataFrame(schema={"game_id": pl.String, "team_id": pl.Int64, "poss": pl.Float64})
    )
    return FactStatisticalPossessionTransformer().transform(
        {
            "fact_play_by_play": pl.DataFrame(events).lazy(),
            "fact_team_game": points_frame.lazy(),
            "fact_box_score_advanced_team": possessions_frame.lazy(),
        }
    )


def test_offensive_rebound_extends_one_statistical_possession() -> None:
    result = _possessions(
        [
            _event(
                0,
                team_id=None,
                location=None,
                action_type="game",
                description="Start of Period",
                clock="PT12M00S",
            ),
            _event(
                1,
                team_id=HOME,
                location="h",
                action_type="2pt",
                clock="PT11M30S",
                description="MISS Home 2PT Shot",
                shot_result="Missed",
                is_field_goal=1,
                shot_value=2,
            ),
            _event(
                2,
                team_id=HOME,
                location="h",
                action_type="rebound",
                sub_type="offensive",
                description="Home Offensive Rebound",
                clock="PT11M28S",
            ),
            _event(
                3,
                team_id=HOME,
                location="h",
                action_type="2pt",
                description="Home Made 2PT Shot",
                shot_result="Made",
                is_field_goal=1,
                shot_value=2,
                score_home="2",
                clock="PT11M20S",
            ),
            _event(
                4,
                team_id=AWAY,
                location="v",
                action_type="turnover",
                description="Away Turnover",
                score_home="2",
                clock="PT11M05S",
            ),
        ]
    )

    assert result.height == 2
    first = result.row(0, named=True)
    assert first["closure_reason"] == "made_field_goal"
    assert first["field_goal_attempts"] == 2
    assert first["offensive_rebounds"] == 1
    assert first["points"] == 2
    assert first["points_reconciled"] is True
    FactStatisticalPossessionSchema.validate(result)


def test_and_one_free_throw_stays_with_made_field_goal() -> None:
    result = _possessions(
        [
            _event(
                0,
                team_id=None,
                location=None,
                action_type="game",
                description="Start of Period",
                clock="PT12M00S",
            ),
            _event(
                1,
                team_id=HOME,
                location="home",
                action_type="2pt",
                description="Home Made Driving Layup",
                shot_result="Made",
                is_field_goal=1,
                shot_value=2,
                score_home="2",
                clock="PT10M00S",
            ),
            _event(
                2,
                team_id=AWAY,
                location="away",
                action_type="foul",
                description="Shooting foul",
                score_home="2",
                clock="PT10M00S",
            ),
            _event(
                3,
                team_id=HOME,
                location="home",
                action_type="free throw",
                description="Free Throw 1 of 1 Made",
                shot_result="Made",
                score_home="3",
                clock="PT10M00S",
            ),
        ]
    )

    assert result.height == 1
    row = result.row(0, named=True)
    assert row["closure_reason"] == "made_final_free_throw"
    assert row["free_throw_attempts"] == 1
    assert row["points"] == 3
    assert row["points_reconciled"] is True


def test_technical_free_throw_does_not_create_or_end_a_possession() -> None:
    result = _possessions(
        [
            _event(
                1,
                team_id=HOME,
                location="home",
                action_type="free throw",
                sub_type="technical",
                description="Technical Free Throw 1 of 1 Made",
                shot_result="Made",
                score_home="1",
                clock="PT12M00S",
            ),
            _event(
                2,
                team_id=AWAY,
                location="away",
                action_type="turnover",
                description="Away Turnover",
                score_home="1",
                clock="PT11M40S",
            ),
        ]
    )

    assert result.height == 1
    row = result.row(0, named=True)
    assert row["offense_team_id"] == AWAY
    assert row["free_throw_attempts"] == 0
    assert row["closure_reason"] == "turnover"


def test_technical_free_throw_inside_sequence_is_separately_accounted() -> None:
    result = _possessions(
        [
            _event(
                0,
                team_id=None,
                location=None,
                action_type="game",
                description="Start of Period",
                clock="PT12M00S",
            ),
            _event(
                1,
                team_id=HOME,
                location="home",
                action_type="2pt",
                description="MISS Home Shot",
                shot_result="Missed",
                is_field_goal=1,
                shot_value=2,
                clock="PT11M00S",
            ),
            _event(
                2,
                team_id=AWAY,
                location="away",
                action_type="free throw",
                sub_type="technical",
                description="Technical Free Throw 1 of 1 Made",
                shot_result="Made",
                score_away="1",
                clock="PT10M59S",
            ),
            _event(
                3,
                team_id=HOME,
                location="home",
                action_type="turnover",
                description="Home Turnover",
                score_away="1",
                clock="PT10M50S",
            ),
        ]
    )

    row = result.row(0, named=True)
    assert row["closure_reason"] == "turnover"
    assert row["free_throw_attempts"] == 0
    assert row["non_possession_free_throw_attempts"] == 1
    assert row["non_possession_free_throw_points"] == 1
    assert row["points"] == 0
    assert "non_possession_free_throw" in row["ambiguity_reason"]


def test_missed_final_free_throw_waits_for_defensive_team_rebound() -> None:
    result = _possessions(
        [
            _event(
                1,
                team_id=HOME,
                location="h",
                action_type="free throw",
                description="Free Throw 2 of 2 Missed",
                shot_result="Missed",
                clock="PT09M00S",
            ),
            _event(
                2,
                team_id=AWAY,
                location="v",
                action_type="rebound",
                description="Away Team Defensive Rebound",
                clock="PT08M59S",
            ),
        ]
    )

    row = result.row(0, named=True)
    assert row["free_throw_attempts"] == 1
    assert row["closure_reason"] == "defensive_rebound"
    assert row["end_action_number"] == 2


def test_ambiguous_jump_ball_and_unknown_violation_are_retained_as_flags() -> None:
    result = _possessions(
        [
            _event(
                1,
                team_id=HOME,
                location="h",
                action_type="2pt",
                description="MISS Home Shot",
                shot_result="Missed",
                is_field_goal=1,
                shot_value=2,
                clock="PT08M00S",
            ),
            _event(
                2,
                team_id=None,
                location=None,
                action_type="jump ball",
                description="Jump Ball",
                clock="PT07M58S",
            ),
            _event(
                3,
                team_id=HOME,
                location="h",
                action_type="violation",
                description="Lane Violation",
                clock="PT07M58S",
            ),
            _event(
                4,
                team_id=None,
                location=None,
                action_type="period",
                description="End of Period",
                clock="PT00M00S",
            ),
        ]
    )

    row = result.row(0, named=True)
    assert row["closure_reason"] == "period_end"
    assert row["is_ambiguous"] is True
    assert "jump_ball_control_unknown" in row["ambiguity_reason"]
    assert "violation_control_unknown" in row["ambiguity_reason"]
    assert row["legal_control_boundary_count"] == 3


def test_possession_loss_violation_closes_without_guessing_next_team() -> None:
    result = _possessions(
        [
            _event(
                1,
                team_id=HOME,
                location="h",
                action_type="violation",
                description="Shot Clock Violation",
                clock="PT06M00S",
            )
        ]
    )
    assert result["closure_reason"].to_list() == ["possession_loss_violation"]


def test_exact_duplicate_event_is_idempotent_and_conflict_fails_closed() -> None:
    event = _event(
        1,
        team_id=HOME,
        location="h",
        action_type="turnover",
        description="Turnover",
        clock="PT11M00S",
    )
    assert _possessions([event, dict(event)]).height == 1

    conflicting = dict(event, description="Different event")
    with pytest.raises(ValueError, match="conflicting play-by-play rows"):
        _possessions([event, conflicting])


def test_team_totals_reconcile_to_exact_official_sources() -> None:
    event = _event(
        1,
        team_id=HOME,
        location="h",
        action_type="turnover",
        description="Turnover",
        clock="PT11M00S",
    )
    result = _possessions(
        [event],
        official_points=[{"game_id": GAME, "team_id": HOME, "pts": 0}],
        official_possessions=[{"game_id": GAME, "team_id": HOME, "poss": 1.0}],
    )
    row = result.row(0, named=True)
    assert row["derived_team_game_points"] == 0
    assert row["official_team_game_points"] == 0
    assert row["team_game_points_reconciled"] is True
    assert row["derived_complete_team_possessions"] == 1
    assert row["official_team_possessions"] == 1.0
    assert row["team_possessions_reconciled"] is True


def test_conflicting_official_team_key_fails_closed() -> None:
    event = _event(
        1,
        team_id=HOME,
        location="h",
        action_type="turnover",
        description="Turnover",
        clock="PT11M00S",
    )
    with pytest.raises(ValueError, match="conflicting official team rows"):
        _possessions(
            [event],
            official_points=[
                {"game_id": GAME, "team_id": HOME, "pts": 0},
                {"game_id": GAME, "team_id": HOME, "pts": 1},
            ],
        )


def _rotation_frame(*, missing_away_player: bool = False) -> pl.DataFrame:
    rows = []
    for side, team_id, players in (
        ("home", HOME, range(101, 106)),
        ("away", AWAY, range(201, 206)),
    ):
        for player_id in players:
            if missing_away_player and player_id == 205:
                continue
            rows.append(
                {
                    "game_id": GAME,
                    "team_id": team_id,
                    "player_id": player_id,
                    "in_time_real": 0.0,
                    "out_time_real": 600.0,
                    "side": side,
                }
            )
    return pl.DataFrame(rows)


def _possession_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": [GAME, GAME],
            "possession_number": [1, 2],
            "start_action_number": [1, 3],
            "end_action_number": [2, 4],
            "offense_team_id": [HOME, AWAY],
            "start_elapsed_tenths": [100, 300],
            "end_elapsed_tenths": [200, 400],
            "points": [2, 0],
            "is_complete": [True, True],
            "is_ambiguous": [False, False],
        }
    )


def _stints(rotation: pl.DataFrame, possessions: pl.DataFrame | None = None) -> pl.DataFrame:
    resolved_possessions = possessions if possessions is not None else _possession_frame()
    return FactLineupStintTransformer().transform(
        {
            "fact_rotation": rotation.lazy(),
            "fact_statistical_possession": resolved_possessions.lazy(),
        }
    )


def test_exact_five_rotation_intervals_create_response_complete_stint() -> None:
    result = _stints(_rotation_frame())
    assert result.height == 1
    row = result.row(0, named=True)
    assert row["home_player_ids"] == "101,102,103,104,105"
    assert row["away_player_ids"] == "201,202,203,204,205"
    assert row["source_interval_count"] == 10
    assert row["home_possessions"] == 1
    assert row["away_possessions"] == 1
    assert row["home_net_points"] == 2
    assert row["first_source_action_number"] == 1
    assert row["last_source_action_number"] == 4
    assert row["response_is_complete"] is True
    FactLineupStintSchema.validate(result)


def test_incomplete_lineup_segment_is_not_emitted() -> None:
    assert _stints(_rotation_frame(missing_away_player=True)).is_empty()


def test_cross_boundary_possession_flags_response_instead_of_allocating_it() -> None:
    possessions = _possession_frame().with_columns(
        pl.when(pl.col("possession_number") == 1)
        .then(550)
        .otherwise(pl.col("start_elapsed_tenths"))
        .alias("start_elapsed_tenths"),
        pl.when(pl.col("possession_number") == 1)
        .then(650)
        .otherwise(pl.col("end_elapsed_tenths"))
        .alias("end_elapsed_tenths"),
    )
    row = _stints(_rotation_frame(), possessions).row(0, named=True)
    assert row["possession_boundary_crossings"] == 1
    assert row["response_is_complete"] is False
    assert row["home_net_points"] is None
    assert row["is_ambiguous"] is True


def test_unplaceable_possession_marks_every_stint_response_incomplete() -> None:
    possessions = _possession_frame().with_columns(
        pl.when(pl.col("possession_number") == 1)
        .then(None)
        .otherwise(pl.col("start_elapsed_tenths"))
        .alias("start_elapsed_tenths")
    )
    row = _stints(_rotation_frame(), possessions).row(0, named=True)
    assert row["unplaced_possession_count"] == 1
    assert row["response_is_complete"] is False
    assert row["home_net_points"] is None


def test_official_team_reconciliation_failure_blocks_rapm_response() -> None:
    event = _event(
        1,
        team_id=HOME,
        location="h",
        action_type="turnover",
        description="Turnover",
        clock="PT11M30S",
    )
    possessions = _possessions(
        [event],
        official_points=[{"game_id": GAME, "team_id": HOME, "pts": 1}],
        official_possessions=[{"game_id": GAME, "team_id": HOME, "poss": 1.0}],
    )

    assert possessions.row(0, named=True)["is_complete"] is True
    assert possessions.row(0, named=True)["team_game_points_reconciled"] is False
    stint = _stints(_rotation_frame(), possessions)
    row = stint.row(0, named=True)
    assert row["response_is_complete"] is False
    assert row["is_ambiguous"] is True
    assert row["ambiguity_reason"] == "official_team_reconciliation_failed"
    assert row["home_net_points"] is None
    assert FactRapmDesignTransformer().transform({"fact_lineup_stint": stint.lazy()}).is_empty()


def test_foreign_offense_team_blocks_rapm_response() -> None:
    possessions = (
        _possession_frame()
        .head(1)
        .with_columns(
            pl.lit(999_999).alias("offense_team_id"),
            pl.lit(2).alias("points"),
        )
    )

    stint = _stints(_rotation_frame(), possessions)
    row = stint.row(0, named=True)
    assert row["response_is_complete"] is False
    assert row["is_ambiguous"] is True
    assert row["ambiguity_reason"] == "foreign_offense_team_in_possession_response"
    assert row["home_net_points"] is None
    assert FactRapmDesignTransformer().transform({"fact_lineup_stint": stint.lazy()}).is_empty()


def test_conflicting_rotation_source_key_fails_closed() -> None:
    rotation = _rotation_frame()
    conflict = rotation.row(0, named=True)
    conflict["out_time_real"] = 500.0
    with pytest.raises(ValueError, match="conflicting GameRotation rows"):
        _stints(pl.concat([rotation, pl.DataFrame([conflict])]))


def test_same_player_cannot_occupy_both_team_lineups() -> None:
    rotation = _rotation_frame()
    first_away = rotation.filter(pl.col("side") == "away").row(0, named=True)
    conflicting = rotation.with_columns(
        pl.when(
            (pl.col("side") == first_away["side"])
            & (pl.col("player_id") == first_away["player_id"])
        )
        .then(101)
        .otherwise(pl.col("player_id"))
        .alias("player_id")
    )

    with pytest.raises(ValueError, match="one player appears on both teams"):
        _stints(conflicting)


def test_rapm_design_is_long_form_unfitted_and_balanced() -> None:
    stint = _stints(_rotation_frame())
    result = FactRapmDesignTransformer().transform({"fact_lineup_stint": stint.lazy()})

    assert result.height == 10
    assert result.group_by("team_side").len().sort("team_side").to_dicts() == [
        {"team_side": "away", "len": 5},
        {"team_side": "home", "len": 5},
    ]
    assert result["design_value"].sum() == 0.0
    assert result["response_home_net_points"].unique().to_list() == [2]
    assert result["first_source_action_number"].unique().to_list() == [1]
    assert result["last_source_action_number"].unique().to_list() == [4]
    assert result["lineup_is_exact"].all()
    assert result["response_is_complete"].all()
    assert not result["is_ambiguous"].any()
    assert not any(column == "rapm" or "coefficient" in column for column in result.columns)
    FactRapmDesignSchema.validate(result)


def test_rapm_design_rechecks_cross_team_player_disjointness() -> None:
    stint = _stints(_rotation_frame()).with_columns(
        pl.lit("101,202,203,204,205").alias("away_player_ids")
    )

    with pytest.raises(ValueError, match="home and away lineups are not disjoint"):
        FactRapmDesignTransformer().transform({"fact_lineup_stint": stint.lazy()})


@pytest.mark.parametrize(
    ("period", "clock", "expected"),
    [(1, "PT12M00S", 0), (1, "PT00M00S", 7_200), (5, "PT05M00S", 28_800), (5, "PT00M00S", 31_800)],
)
def test_period_clock_conversion(period: int, clock: str, expected: int) -> None:
    assert _clock_to_elapsed_tenths(period, clock) == expected


def test_malformed_period_clock_is_not_guessed() -> None:
    assert _clock_to_elapsed_tenths(1, "11:00") is None


def test_typed_zero_row_outputs_remain_schema_valid() -> None:
    possessions = FactStatisticalPossessionTransformer().transform(
        {
            "fact_play_by_play": pl.DataFrame().lazy(),
            "fact_team_game": pl.DataFrame().lazy(),
            "fact_box_score_advanced_team": pl.DataFrame().lazy(),
        }
    )
    stints = FactLineupStintTransformer().transform(
        {
            "fact_rotation": pl.DataFrame().lazy(),
            "fact_statistical_possession": possessions.lazy(),
        }
    )
    design = FactRapmDesignTransformer().transform({"fact_lineup_stint": stints.lazy()})

    assert possessions.is_empty()
    assert stints.is_empty()
    assert design.is_empty()
    FactStatisticalPossessionSchema.validate(possessions)
    FactLineupStintSchema.validate(stints)
    FactRapmDesignSchema.validate(design)
