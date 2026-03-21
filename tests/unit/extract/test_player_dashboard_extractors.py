from __future__ import annotations

import polars as pl
import pytest

from nbadb.extract.stats.player_dashboard import (
    PlayerDashboardByClutchExtractor,
    PlayerDashShootingSplitsExtractor,
    PlayerDashYoyExtractor,
)


class TestPlayerDashboardExtractors:
    @pytest.mark.asyncio
    async def test_extract_adds_query_context_columns(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        extractor = PlayerDashboardByClutchExtractor()
        dummy_df = pl.DataFrame(
            {"group_set": ["Overall"], "group_value": ["Overall"], "pts": [12.0]}
        )

        monkeypatch.setattr(extractor, "_from_nba_api", lambda endpoint_cls, **kwargs: dummy_df)

        result = await extractor.extract(
            player_id=2544,
            season="2024-25",
            season_type="Regular Season",
        )

        assert result["player_id"].to_list() == [2544]
        assert result["season_year"].to_list() == ["2024-25"]
        assert result["season_type"].to_list() == ["Regular Season"]

    @pytest.mark.asyncio
    async def test_extract_all_adds_query_context_to_each_result_set(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        extractor = PlayerDashYoyExtractor()
        dummy_dfs = [
            pl.DataFrame({"group_set": ["ByYear"], "group_value": ["2023-24"]}),
            pl.DataFrame({"group_set": ["Overall"], "group_value": ["Overall"]}),
        ]

        monkeypatch.setattr(
            extractor, "_from_nba_api_multi", lambda endpoint_cls, **kwargs: dummy_dfs
        )

        result = await extractor.extract_all(
            player_id=2544,
            season="2024-25",
            season_type="Playoffs",
        )

        assert len(result) == 2
        assert all("player_id" in df.columns for df in result)
        assert all("season_year" in df.columns for df in result)
        assert all("season_type" in df.columns for df in result)
        assert result[0]["season_type"].to_list() == ["Playoffs"]

    @pytest.mark.asyncio
    async def test_extract_all_preserves_existing_player_id_columns(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        extractor = PlayerDashShootingSplitsExtractor()
        dummy_dfs = [
            pl.DataFrame(
                {
                    "group_set": ["AssistedBy"],
                    "player_id": [201939],
                    "player_name": ["Stephen Curry"],
                }
            ),
            pl.DataFrame({"group_set": ["Overall"], "group_value": ["Overall"]}),
        ]

        monkeypatch.setattr(
            extractor, "_from_nba_api_multi", lambda endpoint_cls, **kwargs: dummy_dfs
        )

        result = await extractor.extract_all(
            player_id=2544,
            season="2024-25",
            season_type="Regular Season",
        )

        assert result[0]["player_id"].to_list() == [201939]
        assert result[1]["player_id"].to_list() == [2544]
        assert all(df["season_year"].to_list() == ["2024-25"] for df in result)
