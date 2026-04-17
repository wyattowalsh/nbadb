from __future__ import annotations

import pandera.errors as pa_errors
import polars as pl
import pytest

from nbadb.schemas.staging.league_support import (
    StagingBoxScoreUsageTeamSchema,
    StagingCommonPlayoffSeriesSchema,
    StagingLeaguePlayerClutchSchema,
    StagingTrackingDefenseSchema,
)
from nbadb.schemas.star.fact_league_support import (
    FactDraftCombineDetailSchema,
    FactLeagueHustleSchema,
    FactLeaguePtShotsSchema,
    FactPlayoffSeriesSchema,
)


def test_staging_common_playoff_series_validates_core_columns() -> None:
    df = pl.DataFrame(
        {
            "season_id": ["22024"],
            "series_id": ["E1"],
            "game_id": ["0042400101"],
            "game_number": [1],
            "home_team_id": [1610612738],
            "away_team_id": [1610612748],
            "home_team_abbreviation": ["BOS"],
            "away_team_abbreviation": ["MIA"],
            "wins": [1],
            "losses": [0],
        }
    )

    result = StagingCommonPlayoffSeriesSchema.validate(df)

    assert result.shape == (1, 10)


def test_staging_league_player_clutch_requires_season_year() -> None:
    df = pl.DataFrame(
        {
            "player_id": [2544],
            "player_name": ["LeBron James"],
            "team_id": [1610612747],
            "team_abbreviation": ["LAL"],
            "season_year": [None],
            "gp": [10],
            "min": [22.0],
            "pts": [22.0],
            "fg_pct": [0.48],
            "ft_pct": [0.91],
        }
    )

    with pytest.raises(pa_errors.SchemaError):
        StagingLeaguePlayerClutchSchema.validate(df)


def test_staging_tracking_defense_validates_passthrough_shape() -> None:
    df = pl.DataFrame(
        {
            "player_id": [203999],
            "player_name": ["Nikola Jokic"],
            "team_id": [1610612743],
            "team_abbreviation": ["DEN"],
            "defense_category": ["Overall"],
            "season_year": ["2024-25"],
            "gp": [20],
            "g": [20],
            "freq": [0.33],
            "d_fgm": [4],
            "d_fga": [9],
            "d_fg_pct": [0.444],
            "normal_fg_pct": [0.49],
            "pct_plusminus": [-0.046],
        }
    )

    result = StagingTrackingDefenseSchema.validate(df)

    assert result.shape == (1, 14)


def test_staging_box_score_usage_team_rejects_missing_game_id() -> None:
    df = pl.DataFrame(
        {
            "game_id": [None],
            "team_id": [1610612747],
            "team_abbreviation": ["LAL"],
            "team_city": ["Los Angeles"],
            "team_name": ["Lakers"],
            "min": ["240:00"],
            "usg_pct": [0.5],
            "pct_fgm": [0.5],
            "pct_fga": [0.5],
            "pct_fg3m": [0.5],
            "pct_fg3a": [0.5],
            "pct_ftm": [0.5],
            "pct_fta": [0.5],
            "pct_oreb": [0.5],
            "pct_dreb": [0.5],
            "pct_reb": [0.5],
            "pct_ast": [0.5],
            "pct_tov": [0.5],
            "pct_stl": [0.5],
            "pct_blk": [0.5],
            "pct_blka": [0.5],
            "pct_pf": [0.5],
            "pct_pfd": [0.5],
            "pct_pts": [0.25],
        }
    )

    with pytest.raises(pa_errors.SchemaError):
        StagingBoxScoreUsageTeamSchema.validate(df)


def test_fact_playoff_series_schema_matches_staging_contract() -> None:
    df = pl.DataFrame(
        {
            "season_id": ["22024"],
            "series_id": ["W2"],
            "home_team_id": [1610612743],
            "away_team_id": [1610612750],
        }
    )

    result = FactPlayoffSeriesSchema.validate(df)

    assert result.shape == (1, 4)


def test_fact_draft_combine_detail_accepts_union_discriminator() -> None:
    df = pl.DataFrame(
        {
            "player_id": [1, 2],
            "result": [10.5, None],
            "height": [None, None],
            "pct": [None, 0.47],
            "detail_type": ["drills", "spot_shooting"],
        }
    )

    result = FactDraftCombineDetailSchema.validate(df)

    assert result.shape == (2, 5)


def test_fact_league_pt_shots_accepts_union_rows() -> None:
    df = pl.DataFrame(
        {
            "id": [1, 2],
            "fga": [20, None],
            "dfga": [None, 18],
            "shot_type": ["stats", "team_defend"],
        }
    )

    result = FactLeaguePtShotsSchema.validate(df)

    assert result.shape == (2, 4)


def test_fact_league_hustle_accepts_player_and_team_rows() -> None:
    df = pl.DataFrame(
        {
            "player_id": [2544, None],
            "team_id": [1610612747, 1610612747],
            "player_name": ["LeBron James", None],
            "team_name": ["Lakers", "Lakers"],
            "gp": [10, 10],
            "min": [22.0, None],
            "deflections": [5.0, 14.0],
            "entity_type": ["player", "team"],
        }
    )

    result = FactLeagueHustleSchema.validate(df)

    assert result.shape == (2, 8)
