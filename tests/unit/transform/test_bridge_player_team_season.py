from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.transform.facts.bridge_player_team_season import (
    BridgePlayerTeamSeasonTransformer,
)
from nbadb.transform.pipeline import _star_schema_map

_CAREER_SCHEMA = {
    "player_id": pl.Int64,
    "team_id": pl.Int64,
    "season_id": pl.String,
    "league_id": pl.String,
    "team_abbreviation": pl.String,
}


def _career(rows: list[tuple[object, ...]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=_CAREER_SCHEMA, orient="row")


def _staging(
    *,
    regular: list[tuple[object, ...]] | None = None,
    postseason: list[tuple[object, ...]] | None = None,
    allstar: list[tuple[object, ...]] | None = None,
) -> dict[str, pl.LazyFrame]:
    return {
        "stg_player_career_regular": _career(regular or []).lazy(),
        "stg_player_career_postseason": _career(postseason or []).lazy(),
        "stg_player_career_allstar": _career(allstar or []).lazy(),
    }


def _run(transformer, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        for key, val in staging.items():
            conn.register(key, val.collect())
        transformer._conn = conn
        return transformer.transform(staging)
    finally:
        conn.close()


def _assert_schema_valid(table: str, df: pl.DataFrame) -> None:
    schema_cls = _star_schema_map()[table]
    validated = schema_cls.validate(df)
    assert isinstance(validated, pl.DataFrame)


class TestBridgePlayerTeamSeason:
    def test_class_attrs(self) -> None:
        assert BridgePlayerTeamSeasonTransformer.output_table == ("bridge_player_team_season")
        assert BridgePlayerTeamSeasonTransformer.depends_on == [
            "stg_player_career_regular",
            "stg_player_career_postseason",
            "stg_player_career_allstar",
        ]

    def test_membership_comes_from_season_bearing_career_results(self) -> None:
        staging = _staging(
            regular=[(101, 1610612737, "2023-24", "00", "ATL")],
            postseason=[(101, 1610612738, "2024-25", "00", "BOS")],
            allstar=[(101, 1610616833, "2024-25", "00", "EST")],
        )

        result = _run(BridgePlayerTeamSeasonTransformer(), staging)

        assert result.shape[0] == 3
        assert set(result["team_id"].to_list()) == {
            1610612737,
            1610612738,
            1610616833,
        }
        assert set(result["season_type"].to_list()) == {
            "Regular Season",
            "Playoffs",
            "All Star",
        }
        assert set(result["league_id"].to_list()) == {"00"}
        _assert_schema_valid("bridge_player_team_season", result)

    def test_exact_duplicate_membership_is_idempotent(self) -> None:
        row = (101, 1610612737, "2023-24", "00", "ATL")
        result = _run(
            BridgePlayerTeamSeasonTransformer(),
            _staging(regular=[row, row]),
        )

        assert result.shape[0] == 1

    def test_conflicting_membership_payload_fails_at_declared_grain(self) -> None:
        with pytest.raises(duckdb.Error, match="conflicting player-team-season membership rows"):
            _run(
                BridgePlayerTeamSeasonTransformer(),
                _staging(
                    regular=[
                        (101, 1610612737, "2023-24", "00", "ATL"),
                        (101, 1610612737, "2023-24", "00", "OLD"),
                    ]
                ),
            )

    def test_null_and_aggregate_team_memberships_are_filtered(self) -> None:
        result = _run(
            BridgePlayerTeamSeasonTransformer(),
            _staging(
                regular=[
                    (101, 1610612737, "2023-24", "00", "ATL"),
                    (None, 1610612738, "2024-25", "00", "BOS"),
                    (102, None, "2024-25", "00", None),
                    (103, 0, "2024-25", "00", "TOT"),
                ]
            ),
        )

        assert result.shape[0] == 1
        assert result["player_id"].to_list() == [101]


def test_schema_is_discovered() -> None:
    assert "bridge_player_team_season" in _star_schema_map()
