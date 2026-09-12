from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import polars as pl
import pytest
from nba_api.stats.endpoints import GLAlumBoxScoreSimilarityScore

from nbadb.core.errors import ResponseContractError
from nbadb.extract.base import BaseExtractor
from nbadb.extract.nba_api_adapter import NbaApiResultPacket, NbaApiResultPackets
from nbadb.orchestrate.extractor_runner import ExtractorRunner


class _ScopeEndpoint:
    def __init__(
        self,
        team_id: int,
        season: str,
        season_type_all_star: str = "Regular Season",
        league_id_nullable: str = "00",
        measure_type_detailed_defense: str = "Base",
        *,
        timeout: int = 30,
        get_request: bool = True,
    ) -> None: ...


class _ScopeExtractor(BaseExtractor):
    endpoint_name = "scope_forwarding_test"

    async def extract(self, **params: Any) -> pl.DataFrame:
        return self._from_nba_api(
            _ScopeEndpoint,
            team_id=params["team_id"],
            season=params["season"],
            season_type_all_star=params.get("season_type", "Regular Season"),
        )


def _prepared_extractor(params: dict[str, object]) -> _ScopeExtractor:
    runner = object.__new__(ExtractorRunner)
    runner._settings = MagicMock(endpoint_request_timeouts={})
    runner._thread_pool = MagicMock()
    extractor = _ScopeExtractor()
    runner._prepare_extractor(extractor, logical_params=params)
    return extractor


def test_forwards_exact_and_semantic_scope_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_fetch(endpoint_cls: type, **kwargs: object) -> NbaApiResultPackets:
        captured.update(kwargs)
        return NbaApiResultPackets(
            (
                NbaApiResultPacket(
                    name="Rows",
                    provider_index=0,
                    canonical_index=0,
                    headers=("VALUE",),
                    frame=pl.DataFrame({"VALUE": [1]}),
                ),
            )
        )

    monkeypatch.setattr("nbadb.extract.base.fetch_stats_packets", fake_fetch)
    extractor = _prepared_extractor(
        {
            "team_id": 1,
            "season": "2024-25",
            "season_type": "Playoffs",
            "league_id": "10",
            "measure_type_detailed_defense": "Advanced",
            "snapshot_at": "control-only",
            "timeout": 999,
        }
    )

    frames = extractor._call_nba_api(
        _ScopeEndpoint,
        team_id=1,
        season="2024-25",
        season_type_all_star="Playoffs",
    )

    assert frames[0].to_dicts() == [
        {
            "value": 1,
            "season_year": "2024-25",
            "season_type": "Playoffs",
            "league_id": "10",
        }
    ]
    assert captured["league_id_nullable"] == "10"
    assert captured["measure_type_detailed_defense"] == "Advanced"
    assert "snapshot_at" not in captured
    assert captured.get("timeout") != 999


def test_wrapper_cannot_change_explicit_scope() -> None:
    extractor = _prepared_extractor({"league_id": "10"})

    with pytest.raises(ResponseContractError, match="changed an explicit request-scope"):
        extractor._call_nba_api(
            _ScopeEndpoint,
            team_id=1,
            season="2024-25",
            league_id_nullable="00",
        )


def test_conflicting_logical_aliases_fail_before_provider_call() -> None:
    extractor = _prepared_extractor({"league_id": "00", "league_id_nullable": "10"})

    with pytest.raises(ResponseContractError, match="conflicting scope aliases"):
        extractor._call_nba_api(_ScopeEndpoint, team_id=1, season="2024-25")


@pytest.mark.parametrize("league_id", ["00", "10"])
def test_competition_value_changes_provider_kwargs_and_injected_scope_output(
    monkeypatch: pytest.MonkeyPatch,
    league_id: str,
) -> None:
    captured: dict[str, object] = {}

    def fake_fetch(endpoint_cls: type, **kwargs: object) -> NbaApiResultPackets:
        captured.update(kwargs)
        return NbaApiResultPackets(
            (
                NbaApiResultPacket(
                    name="Rows",
                    provider_index=0,
                    canonical_index=0,
                    headers=("VALUE",),
                    frame=pl.DataFrame({"VALUE": [1]}),
                ),
            )
        )

    monkeypatch.setattr("nbadb.extract.base.fetch_stats_packets", fake_fetch)
    extractor = _prepared_extractor({"league_id": league_id})

    frames = extractor._call_nba_api(
        _ScopeEndpoint,
        team_id=1,
        season="2024-25",
    )

    assert captured["league_id_nullable"] == league_id
    assert frames[0]["league_id"].to_list() == [league_id]


def test_forwards_person_competition_roles_by_exact_constructor_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_fetch(endpoint_cls: type, **kwargs: object) -> NbaApiResultPackets:
        captured.update(kwargs)
        return NbaApiResultPackets(
            (
                NbaApiResultPacket(
                    name="Rows",
                    provider_index=0,
                    canonical_index=0,
                    headers=("VALUE",),
                    frame=pl.DataFrame({"VALUE": [1]}),
                ),
            )
        )

    monkeypatch.setattr("nbadb.extract.base.fetch_stats_packets", fake_fetch)
    extractor = _prepared_extractor(
        {
            "person1_id": 1,
            "person2_id": 2,
            "person1_league_id": "10",
            "person2_league_id": "20",
        }
    )

    frames = extractor._call_nba_api(
        GLAlumBoxScoreSimilarityScore,
        person1_id=1,
        person2_id=2,
    )

    assert captured["person1_league_id"] == "10"
    assert captured["person2_league_id"] == "20"
    assert "league_id" not in frames[0].columns


def test_person_competition_roles_are_not_collapsed_into_primary_league_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_fetch(endpoint_cls: type, **kwargs: object) -> NbaApiResultPackets:
        captured.update(kwargs)
        return NbaApiResultPackets(
            (
                NbaApiResultPacket(
                    name="Rows",
                    provider_index=0,
                    canonical_index=0,
                    headers=("VALUE",),
                    frame=pl.DataFrame({"VALUE": [1]}),
                ),
            )
        )

    monkeypatch.setattr("nbadb.extract.base.fetch_stats_packets", fake_fetch)
    extractor = _prepared_extractor({"league_id": "10"})

    frames = extractor._call_nba_api(
        GLAlumBoxScoreSimilarityScore,
        person1_id=1,
        person2_id=2,
    )

    assert "person1_league_id" not in captured
    assert "person2_league_id" not in captured
    assert "league_id" not in captured
    assert "league_id" not in frames[0].columns
