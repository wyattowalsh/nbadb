from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.transform.views.analytics_player_impact import (
    AnalyticsPlayerImpactTransformer,
)


def _run(transformer, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        for key, val in staging.items():
            conn.register(key, val.collect())
        transformer._conn = conn
        return transformer.transform(staging)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Fixtures: shared mock data builders
# ---------------------------------------------------------------------------


def _make_agg_on_off_splits(
    player_id: int = 201566,
    team_id: int = 1610612738,
    season_year: str = "2024-25",
    season_type: str = "Regular Season",
    on_net: float = 8.0,
    off_net: float = -3.0,
) -> pl.LazyFrame:
    """Two rows per player: On and Off court splits."""
    return pl.DataFrame(
        {
            "entity_type": ["player", "player"],
            "entity_id": [player_id, player_id],
            "team_id": [team_id, team_id],
            "season_year": [season_year, season_year],
            "season_type": [season_type, season_type],
            "on_off": ["On", "Off"],
            "gp": [60, 60],
            "min": [32.0, 16.0],
            "pts": [25.0, 18.0],
            "reb": [6.0, 5.0],
            "ast": [7.0, 5.0],
            "off_rating": [115.0, 108.0],
            "def_rating": [107.0, 111.0],
            "net_rating": [on_net, off_net],
        }
    ).lazy()


def _make_agg_player_season(
    player_id: int = 201566,
    team_id: int = 1610612738,
    season_year: str = "2024-25",
) -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "player_id": [player_id],
            "team_id": [team_id],
            "season_year": [season_year],
            "season_type": ["Regular Season"],
            "gp": [72],
            "total_min": [2400.0],
            "avg_min": [33.3],
            "total_pts": [1800.0],
            "avg_pts": [25.0],
            "total_reb": [432.0],
            "avg_reb": [6.0],
            "total_ast": [504.0],
            "avg_ast": [7.0],
            "total_stl": [86.4],
            "avg_stl": [1.2],
            "total_blk": [36.0],
            "avg_blk": [0.5],
            "total_tov": [216.0],
            "avg_tov": [3.0],
            "total_fgm": [648.0],
            "total_fga": [1440.0],
            "fg_pct": [0.450],
            "total_fg3m": [180.0],
            "total_fg3a": [504.0],
            "fg3_pct": [0.357],
            "total_ftm": [324.0],
            "total_fta": [396.0],
            "ft_pct": [0.818],
            "avg_off_rating": [113.0],
            "avg_def_rating": [108.0],
            "avg_net_rating": [5.0],
            "avg_ts_pct": [0.580],
            "avg_usg_pct": [0.280],
            "avg_pie": [0.150],
        }
    ).lazy()


def _make_dim_player(
    player_id: int = 201566,
    full_name: str = "Russell Westbrook",
    is_current: bool = True,
) -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "player_id": [player_id],
            "full_name": [full_name],
            "is_current": [is_current],
        }
    ).lazy()


def _make_dim_team(
    team_id: int = 1610612738,
    abbreviation: str = "BOS",
) -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "team_id": [team_id],
            "abbreviation": [abbreviation],
        }
    ).lazy()


def _staging(**overrides) -> dict[str, pl.LazyFrame]:
    defaults = {
        "agg_on_off_splits": _make_agg_on_off_splits(),
        "agg_player_season": _make_agg_player_season(),
        "dim_player": _make_dim_player(),
        "dim_team": _make_dim_team(),
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Tests: metadata
# ---------------------------------------------------------------------------


class TestAnalyticsPlayerImpactMetadata:
    def test_output_table(self) -> None:
        t = AnalyticsPlayerImpactTransformer()
        assert t.output_table == "analytics_player_impact"

    def test_depends_on_count(self) -> None:
        t = AnalyticsPlayerImpactTransformer()
        assert len(t.depends_on) == 4

    def test_depends_on_contents(self) -> None:
        t = AnalyticsPlayerImpactTransformer()
        assert set(t.depends_on) == {
            "agg_on_off_splits",
            "agg_player_season",
            "dim_player",
            "dim_team",
        }

    def test_sql_is_non_empty(self) -> None:
        assert AnalyticsPlayerImpactTransformer._SQL.strip()

    def test_no_connection_before_injection(self) -> None:
        t = AnalyticsPlayerImpactTransformer()
        with pytest.raises(RuntimeError, match="No DuckDB connection"):
            t.conn  # noqa: B018


# ---------------------------------------------------------------------------
# Tests: net_rating_diff computation
# ---------------------------------------------------------------------------


class TestNetRatingDiff:
    def test_net_rating_diff_computed_correctly(self) -> None:
        """net_rating_diff = on_net_rating - off_net_rating."""
        on_net, off_net = 8.0, -3.0
        staging = _staging(
            agg_on_off_splits=_make_agg_on_off_splits(on_net=on_net, off_net=off_net),
        )
        result = _run(AnalyticsPlayerImpactTransformer(), staging)

        assert result.shape[0] == 1
        assert result["on_net_rating"][0] == pytest.approx(on_net)
        assert result["off_net_rating"][0] == pytest.approx(off_net)
        assert result["net_rating_diff"][0] == pytest.approx(on_net - off_net)

    def test_negative_net_rating_diff(self) -> None:
        """Player whose team is worse with them on court."""
        staging = _staging(
            agg_on_off_splits=_make_agg_on_off_splits(on_net=-2.0, off_net=5.0),
        )
        result = _run(AnalyticsPlayerImpactTransformer(), staging)

        assert result["net_rating_diff"][0] == pytest.approx(-7.0)

    def test_zero_net_rating_diff(self) -> None:
        staging = _staging(
            agg_on_off_splits=_make_agg_on_off_splits(on_net=4.0, off_net=4.0),
        )
        result = _run(AnalyticsPlayerImpactTransformer(), staging)

        assert result["net_rating_diff"][0] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Tests: dimension joins
# ---------------------------------------------------------------------------


class TestDimensionJoins:
    def test_player_name_and_team_abbreviation_joined(self) -> None:
        result = _run(AnalyticsPlayerImpactTransformer(), _staging())

        assert result["player_name"][0] == "Russell Westbrook"
        assert result["team_abbreviation"][0] == "BOS"

    def test_null_player_name_when_not_current(self) -> None:
        """dim_player join requires is_current = TRUE."""
        staging = _staging(dim_player=_make_dim_player(is_current=False))
        result = _run(AnalyticsPlayerImpactTransformer(), staging)

        assert result.shape[0] == 1
        assert result["player_name"][0] is None

    def test_null_team_abbreviation_when_no_team_match(self) -> None:
        """Unmatched team_id yields NULL abbreviation."""
        staging = _staging(dim_team=_make_dim_team(team_id=9999999))
        result = _run(AnalyticsPlayerImpactTransformer(), staging)

        assert result.shape[0] == 1
        assert result["team_abbreviation"][0] is None


# ---------------------------------------------------------------------------
# Tests: on/off columns forwarded
# ---------------------------------------------------------------------------


class TestOnOffColumns:
    def test_on_court_stats_forwarded(self) -> None:
        result = _run(AnalyticsPlayerImpactTransformer(), _staging())

        assert result["on_off_rating"][0] == pytest.approx(115.0)
        assert result["on_def_rating"][0] == pytest.approx(107.0)
        assert result["on_pts"][0] == pytest.approx(25.0)
        assert result["on_reb"][0] == pytest.approx(6.0)
        assert result["on_ast"][0] == pytest.approx(7.0)

    def test_off_court_stats_forwarded(self) -> None:
        result = _run(AnalyticsPlayerImpactTransformer(), _staging())

        assert result["off_off_rating"][0] == pytest.approx(108.0)
        assert result["off_def_rating"][0] == pytest.approx(111.0)

    def test_null_on_off_when_no_splits(self) -> None:
        """When on/off splits are missing, impact columns are NULL."""
        empty_splits = pl.DataFrame(
            {
                "entity_type": pl.Series([], dtype=pl.Utf8),
                "entity_id": pl.Series([], dtype=pl.Int64),
                "team_id": pl.Series([], dtype=pl.Int64),
                "season_year": pl.Series([], dtype=pl.Utf8),
                "season_type": pl.Series([], dtype=pl.Utf8),
                "on_off": pl.Series([], dtype=pl.Utf8),
                "gp": pl.Series([], dtype=pl.Int64),
                "min": pl.Series([], dtype=pl.Float64),
                "pts": pl.Series([], dtype=pl.Float64),
                "reb": pl.Series([], dtype=pl.Float64),
                "ast": pl.Series([], dtype=pl.Float64),
                "off_rating": pl.Series([], dtype=pl.Float64),
                "def_rating": pl.Series([], dtype=pl.Float64),
                "net_rating": pl.Series([], dtype=pl.Float64),
            }
        ).lazy()
        staging = _staging(agg_on_off_splits=empty_splits)
        result = _run(AnalyticsPlayerImpactTransformer(), staging)

        assert result.shape[0] == 1
        assert result["on_net_rating"][0] is None
        assert result["off_net_rating"][0] is None
        assert result["net_rating_diff"][0] is None


# ---------------------------------------------------------------------------
# Tests: season stats forwarded
# ---------------------------------------------------------------------------


class TestSeasonStats:
    def test_season_stats_columns_present(self) -> None:
        result = _run(AnalyticsPlayerImpactTransformer(), _staging())

        assert result["gp"][0] == 72
        assert result["avg_pts"][0] == pytest.approx(25.0)
        assert result["avg_reb"][0] == pytest.approx(6.0)
        assert result["avg_ast"][0] == pytest.approx(7.0)
        assert result["fg_pct"][0] == pytest.approx(0.450)
        assert result["avg_ts_pct"][0] == pytest.approx(0.580)
        assert result["avg_usg_pct"][0] == pytest.approx(0.280)
        assert result["avg_pie"][0] == pytest.approx(0.150)
        assert result["season_type"][0] == "Regular Season"


# ---------------------------------------------------------------------------
# Tests: season_type join correctness (regression for fan-out bug)
# ---------------------------------------------------------------------------


class TestSeasonTypeJoin:
    """Regression: on/off splits must join on season_type to avoid fan-out.

    Before the fix, agg_on_off_splits lacked season_type so a single
    on/off row would attach to BOTH Regular Season and Playoffs rows
    in agg_player_season, duplicating impact values.
    """

    def test_separate_on_off_per_season_type(self) -> None:
        """Regular Season and Playoffs rows get their own on/off splits."""
        rs_splits = _make_agg_on_off_splits(season_type="Regular Season", on_net=8.0, off_net=-3.0)
        po_splits = _make_agg_on_off_splits(season_type="Playoffs", on_net=12.0, off_net=1.0)
        combined_splits = pl.concat([rs_splits.collect(), po_splits.collect()]).lazy()

        rs_season = _make_agg_player_season()
        po_season_data = rs_season.collect().with_columns(pl.lit("Playoffs").alias("season_type"))
        combined_season = pl.concat([rs_season.collect(), po_season_data]).lazy()

        staging = _staging(
            agg_on_off_splits=combined_splits,
            agg_player_season=combined_season,
        )
        result = _run(AnalyticsPlayerImpactTransformer(), staging)

        assert result.shape[0] == 2

        rs_row = result.filter(pl.col("season_type") == "Regular Season")
        po_row = result.filter(pl.col("season_type") == "Playoffs")

        assert rs_row.shape[0] == 1
        assert po_row.shape[0] == 1

        # Regular Season on/off values
        assert rs_row["on_net_rating"][0] == pytest.approx(8.0)
        assert rs_row["off_net_rating"][0] == pytest.approx(-3.0)
        assert rs_row["net_rating_diff"][0] == pytest.approx(11.0)

        # Playoffs on/off values — must differ from Regular Season
        assert po_row["on_net_rating"][0] == pytest.approx(12.0)
        assert po_row["off_net_rating"][0] == pytest.approx(1.0)
        assert po_row["net_rating_diff"][0] == pytest.approx(11.0)

    def test_no_cross_contamination_when_splits_missing_for_one_type(self) -> None:
        """Playoffs row gets NULL on/off when only Regular Season splits exist."""
        rs_splits = _make_agg_on_off_splits(season_type="Regular Season", on_net=8.0, off_net=-3.0)

        rs_season = _make_agg_player_season()
        po_season_data = rs_season.collect().with_columns(pl.lit("Playoffs").alias("season_type"))
        combined_season = pl.concat([rs_season.collect(), po_season_data]).lazy()

        staging = _staging(
            agg_on_off_splits=rs_splits,
            agg_player_season=combined_season,
        )
        result = _run(AnalyticsPlayerImpactTransformer(), staging)

        assert result.shape[0] == 2

        rs_row = result.filter(pl.col("season_type") == "Regular Season")
        po_row = result.filter(pl.col("season_type") == "Playoffs")

        # Regular Season should have on/off values
        assert rs_row["on_net_rating"][0] == pytest.approx(8.0)
        assert rs_row["net_rating_diff"][0] == pytest.approx(11.0)

        # Playoffs should have NULL on/off values (no splits data)
        assert po_row["on_net_rating"][0] is None
        assert po_row["off_net_rating"][0] is None
        assert po_row["net_rating_diff"][0] is None
