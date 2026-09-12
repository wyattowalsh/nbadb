from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.schemas.registry import get_output_schema
from nbadb.transform.derived.agg_on_off_splits import AggOnOffSplitsTransformer

PLAYER_ID = 201566
TEAM_ID = 1610612738


def _run(staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        for key, val in staging.items():
            conn.register(key, val.collect())
        transformer = AggOnOffSplitsTransformer()
        transformer._conn = conn
        return transformer.transform(staging)
    finally:
        conn.close()


def _summary_frame(
    *,
    on: bool,
    season_type: str = "Regular Season",
    player_id: int = PLAYER_ID,
) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "vs_player_id": [player_id],
            "team_id": [TEAM_ID],
            "season_year": ["2024-25"],
            "season_type": [season_type],
            "gp": [65 if on else 60],
            "min": [2100.0 if on else 1350.0],
            "plus_minus": [8.0 if on else -3.0],
            "off_rating": [120.0 if on else 110.0],
            "def_rating": [108.0 if on else 112.0],
            "net_rating": [12.0 if on else -2.0],
        }
    )


def _detail_frame(
    *,
    on: bool,
    season_type: str = "Regular Season",
    player_id: int = PLAYER_ID,
) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "vs_player_id": [player_id],
            "team_id": [TEAM_ID],
            "season_year": ["2024-25"],
            "season_type": [season_type],
            "gp": [65 if on else 60],
            "min": [2100.0 if on else 1350.0],
            "w": [48 if on else 30],
            "l": [17 if on else 30],
            "w_pct": [0.738 if on else 0.5],
            "fgm": [900.0 if on else 500.0],
            "fga": [1800.0 if on else 1100.0],
            # Deliberately differ from recomputed values: provider and derived
            # values must remain independently inspectable.
            "fg_pct": [0.49 if on else 0.44],
            "fg3m": [300.0 if on else 150.0],
            "fg3a": [800.0 if on else 450.0],
            "fg3_pct": [0.37 if on else 0.32],
            "ftm": [350.0 if on else 190.0],
            "fta": [420.0 if on else 250.0],
            "ft_pct": [0.82 if on else 0.75],
            "oreb": [200.0 if on else 120.0],
            "dreb": [600.0 if on else 360.0],
            "reb": [800.0 if on else 480.0],
            "ast": [550.0 if on else 280.0],
            "tov": [240.0 if on else 160.0],
            "stl": [120.0 if on else 70.0],
            "blk": [90.0 if on else 50.0],
            "blka": [70.0 if on else 45.0],
            "pf": [310.0 if on else 190.0],
            "pfd": [330.0 if on else 200.0],
            "pts": [2450.0 if on else 1340.0],
            "plus_minus": [8.0 if on else -3.0],
        }
    )


def _overall_frame(*, season_type: str = "Regular Season") -> pl.DataFrame:
    return _detail_frame(on=True, season_type=season_type).drop("vs_player_id")


def _staging(**overrides: pl.DataFrame) -> dict[str, pl.LazyFrame]:
    frames = {
        "stg_on_off_details_overall": _overall_frame(),
        "stg_on_off_details_off_court": _detail_frame(on=False),
        "stg_on_off_details_on_court": _detail_frame(on=True),
        "stg_on_off_summary_off_court": _summary_frame(on=False),
        "stg_on_off_summary_on_court": _summary_frame(on=True),
    }
    frames.update(overrides)
    return {name: frame.lazy() for name, frame in frames.items()}


def _player_rows(result: pl.DataFrame) -> pl.DataFrame:
    return result.filter(pl.col("entity_type") == "player").sort("on_off")


class TestContract:
    def test_metadata_uses_exact_provider_result_sets(self) -> None:
        assert AggOnOffSplitsTransformer.output_table == "agg_on_off_splits"
        assert set(AggOnOffSplitsTransformer.depends_on) == {
            "stg_on_off_details_overall",
            "stg_on_off_details_off_court",
            "stg_on_off_details_on_court",
            "stg_on_off_summary_off_court",
            "stg_on_off_summary_on_court",
        }

    def test_output_is_schema_valid(self) -> None:
        result = _run(_staging())
        schema = get_output_schema("agg_on_off_splits")
        assert schema is not None
        schema.validate(result)


class TestReconciliation:
    def test_preserves_compatibility_surfaces_but_curates_player_rows(self) -> None:
        result = _run(_staging())
        counts = dict(result.group_by("entity_type").len().rows())
        assert counts == {"player": 2, "player_detail": 2, "team": 1}
        assert set(_player_rows(result)["on_off"].to_list()) == {"On", "Off"}
        assert set(_player_rows(result)["source_kind"].to_list()) == {"reconciled_summary_detail"}

    def test_summary_ratings_and_detail_counts_share_exact_grain(self) -> None:
        on = _player_rows(_run(_staging())).filter(pl.col("on_off") == "On").row(0, named=True)
        assert on["off_rating"] == pytest.approx(120.0)
        assert on["pts"] == pytest.approx(2450.0)
        assert on["reb"] == pytest.approx(800.0)
        assert on["ast"] == pytest.approx(550.0)

    def test_pair_exposures_and_differentials_are_explicit(self) -> None:
        rows = _player_rows(_run(_staging()))
        for row in rows.iter_rows(named=True):
            assert row["on_off_pair_complete"] is True
            assert row["on_gp"] == 65
            assert row["off_gp"] == 60
            assert row["on_min"] == pytest.approx(2100.0)
            assert row["off_min"] == pytest.approx(1350.0)
            assert row["off_rating_diff"] == pytest.approx(10.0)
            assert row["def_rating_diff"] == pytest.approx(-4.0)
            assert row["net_rating_diff"] == pytest.approx(14.0)
            assert row["plus_minus_diff"] == pytest.approx(11.0)

    def test_rates_are_derived_from_counts_and_provider_values_are_retained(self) -> None:
        on = _player_rows(_run(_staging())).filter(pl.col("on_off") == "On").row(0, named=True)
        assert on["provider_fg_pct"] == pytest.approx(0.49)
        assert on["fg_pct"] == pytest.approx(0.5)
        assert on["fg3_pct"] == pytest.approx(0.375)
        assert on["ft_pct"] == pytest.approx(350 / 420)
        assert on["efg_pct"] == pytest.approx((900 + 0.5 * 300) / 1800)
        assert on["ts_pct"] == pytest.approx(2450 / (2 * (1800 + 0.44 * 420)))
        assert on["pts_per48"] == pytest.approx(2450 * 48 / 2100)

    def test_incomplete_pair_is_retained_and_marked(self) -> None:
        off_summary = _summary_frame(on=False).head(0)
        off_detail = _detail_frame(on=False).head(0)
        result = _player_rows(
            _run(
                _staging(
                    stg_on_off_summary_off_court=off_summary,
                    stg_on_off_details_off_court=off_detail,
                )
            )
        )
        assert result.height == 1
        assert result["on_off"][0] == "On"
        assert result["on_off_pair_complete"][0] is False
        assert result["off_min"][0] is None
        assert result["net_rating_diff"][0] is None

    def test_season_type_is_part_of_pair_grain(self) -> None:
        playoff_frames = {
            "stg_on_off_details_overall": pl.concat(
                [_overall_frame(), _overall_frame(season_type="Playoffs")]
            ),
            "stg_on_off_details_off_court": pl.concat(
                [_detail_frame(on=False), _detail_frame(on=False, season_type="Playoffs")]
            ),
            "stg_on_off_details_on_court": pl.concat(
                [_detail_frame(on=True), _detail_frame(on=True, season_type="Playoffs")]
            ),
            "stg_on_off_summary_off_court": pl.concat(
                [_summary_frame(on=False), _summary_frame(on=False, season_type="Playoffs")]
            ),
            "stg_on_off_summary_on_court": pl.concat(
                [_summary_frame(on=True), _summary_frame(on=True, season_type="Playoffs")]
            ),
        }
        result = _player_rows(_run(_staging(**playoff_frames)))
        assert result.height == 4
        assert set(result["season_type"].to_list()) == {"Regular Season", "Playoffs"}


class TestConflictSafety:
    def test_exact_duplicates_are_idempotent(self) -> None:
        staging = _staging(
            stg_on_off_summary_on_court=pl.concat(
                [_summary_frame(on=True), _summary_frame(on=True)]
            ),
            stg_on_off_details_on_court=pl.concat([_detail_frame(on=True), _detail_frame(on=True)]),
        )
        assert _player_rows(_run(staging)).height == 2

    def test_conflicting_summary_rows_fail_closed(self) -> None:
        conflict = _summary_frame(on=True).with_columns(pl.lit(121.0).alias("off_rating"))
        staging = _staging(
            stg_on_off_summary_on_court=pl.concat([_summary_frame(on=True), conflict])
        )
        with pytest.raises(duckdb.InvalidInputException, match="conflicting provider"):
            _run(staging)

    def test_conflicting_detail_rows_fail_closed(self) -> None:
        conflict = _detail_frame(on=False).with_columns(pl.lit(501.0).alias("fgm"))
        staging = _staging(
            stg_on_off_details_off_court=pl.concat([_detail_frame(on=False), conflict])
        )
        with pytest.raises(duckdb.InvalidInputException, match="conflicting provider"):
            _run(staging)

    @pytest.mark.parametrize(
        ("column", "value"),
        [("gp", 999), ("min", 9999.0), ("plus_minus", 99.0)],
    )
    def test_each_summary_detail_shared_total_must_reconcile(
        self,
        column: str,
        value: int | float,
    ) -> None:
        conflicting_summary = _summary_frame(on=True).with_columns(pl.lit(value).alias(column))

        with pytest.raises(
            duckdb.InvalidInputException,
            match=rf"conflicting provider on/off summary/detail {column}",
        ):
            _run(_staging(stg_on_off_summary_on_court=conflicting_summary))
