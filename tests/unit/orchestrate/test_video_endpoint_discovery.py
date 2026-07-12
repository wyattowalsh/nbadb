from __future__ import annotations

from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from nbadb.orchestrate.discovery import EntityDiscovery


@pytest.mark.asyncio
async def test_player_team_discovery_preserves_all_exact_affiliations() -> None:
    class _Extractor:
        pass

    registry = MagicMock()
    registry.get.return_value = _Extractor

    def _response(*_args, **kwargs):
        if kwargs["season_type"] == "Regular Season":
            return pl.DataFrame(
                {
                    "player_id": [1, 1, 1],
                    "team_id": [10, 20, 20],
                }
            )
        return pl.DataFrame({"player_id": [1, 2], "team_id": [20, 30]})

    with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_response) as extract:
        result = await EntityDiscovery(registry).discover_player_team_season_params_result(
            ["2024-25"],
            season_types=["Regular Season", "Playoffs"],
        )

    assert registry.get.call_args.args == ("player_game_logs",)
    assert extract.call_count == 2
    assert result.is_complete
    assert result.params == [
        {
            "player_id": 1,
            "team_id": 10,
            "season": "2024-25",
            "season_type": "Regular Season",
        },
        {
            "player_id": 1,
            "team_id": 20,
            "season": "2024-25",
            "season_type": "Regular Season",
        },
        {
            "player_id": 1,
            "team_id": 20,
            "season": "2024-25",
            "season_type": "Playoffs",
        },
        {
            "player_id": 2,
            "team_id": 30,
            "season": "2024-25",
            "season_type": "Playoffs",
        },
    ]


@pytest.mark.asyncio
async def test_player_team_discovery_accepts_typed_zero_row_scope() -> None:
    class _Extractor:
        pass

    registry = MagicMock()
    registry.get.return_value = _Extractor
    empty = pl.DataFrame(schema={"player_id": pl.Int64, "team_id": pl.Int64})

    with patch("nbadb.orchestrate.discovery._sync_extract", return_value=empty):
        result = await EntityDiscovery(registry).discover_player_team_season_params_result(
            ["2024-25"],
            season_types=["All Star"],
        )

    assert result.params == []
    assert result.covered_pairs == {("2024-25", "All Star")}
    assert result.is_complete


@pytest.mark.asyncio
async def test_pre_2019_play_in_discovery_is_classified_without_request() -> None:
    registry = MagicMock()

    with patch("nbadb.orchestrate.discovery._sync_extract") as extract:
        result = await EntityDiscovery(registry).discover_player_team_season_params_result(
            ["2018-19"],
            season_types=["PlayIn"],
        )

    assert extract.call_count == 0
    assert registry.get.call_count == 1
    assert result.params == []
    assert result.covered_pairs == {("2018-19", "PlayIn")}
    assert result.upstream_unavailable_pairs == {
        ("2018-19", "PlayIn"): "competition_not_held_before_2019_20"
    }
    assert result.is_complete


@pytest.mark.asyncio
async def test_pre_2019_play_in_game_discovery_emits_typed_zero_row_frame() -> None:
    registry = MagicMock()
    covered: list[tuple[tuple[str, str], pl.DataFrame]] = []

    with patch("nbadb.orchestrate.discovery._sync_extract") as extract:
        result = await EntityDiscovery(registry).discover_game_ids_result(
            ["2018-19"],
            season_types=["PlayIn"],
            on_combo_covered=lambda combo, frame: covered.append((combo, frame)),
        )

    assert extract.call_count == 0
    assert result.is_complete
    assert result.game_ids == []
    assert result.raw.schema == {"game_id": pl.String, "game_date": pl.String}
    assert covered[0][0] == ("2018-19", "PlayIn")
    assert covered[0][1].is_empty()
    assert result.upstream_unavailable_combos == {
        ("2018-19", "PlayIn"): "competition_not_held_before_2019_20"
    }
