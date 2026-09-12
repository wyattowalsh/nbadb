"""Behavioral extractor tests split from the typed registry/attribute module."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import polars as pl
import pytest

from nbadb.extract.stats.draft import (
    DraftBoardExtractor,
)
from nbadb.extract.stats.misc import (
    CumeStatsPlayerExtractor,
    CumeStatsTeamExtractor,
    DunkScoreLeadersExtractor,
    GravityLeadersExtractor,
)
from nbadb.extract.stats.player_info import (
    PlayerCareerStatsExtractor,
)
from nbadb.extract.stats.standings import (
    ISTStandingsExtractor,
)
from nbadb.orchestrate.cume_workload_contract import CumeWorkloadContractError
from tests.unit.extract.test_stats_extractors import _RAW_RESPONSE_UNSET


class _DatetimeSubclass(datetime):
    pass


class TestPlayerCareerStatsExtractor:
    def test_extract_all_fails_closed_on_missing_result_set(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = PlayerCareerStatsExtractor()

        def _boom(*_args: object, **_kwargs: object) -> list[pl.DataFrame]:
            raise KeyError("CareerTotalsCollegeSeason")

        monkeypatch.setattr(ext, "_from_nba_api_multi", _boom)

        with pytest.raises(KeyError, match="CareerTotalsCollegeSeason"):
            asyncio.run(ext.extract_all(player_id=1824))

    def test_extract_all_propagates_jsondecodeerror(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = PlayerCareerStatsExtractor()

        def _boom(*_args: object, **_kwargs: object) -> list[pl.DataFrame]:
            raise json.JSONDecodeError("bad json", "", 0)

        monkeypatch.setattr(ext, "_from_nba_api_multi", _boom)

        with pytest.raises(json.JSONDecodeError, match="bad json"):
            asyncio.run(ext.extract_all(player_id=1629019, timeout=120))


class TestCumeStatsDependentExtractors:
    @pytest.mark.parametrize("method_name", ["extract", "extract_all"])
    @pytest.mark.parametrize(
        "extractor_cls, entity_key, entity_id, game_ids",
        [
            (
                CumeStatsPlayerExtractor,
                "player_id",
                201939,
                ["0022400001", "0022400002"],
            ),
            (
                CumeStatsTeamExtractor,
                "team_id",
                1610612744,
                "0022400001|0022400002",
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_explicit_game_ids_fail_closed_before_provider_construction(
        self,
        monkeypatch: pytest.MonkeyPatch,
        method_name: str,
        extractor_cls: type,
        entity_key: str,
        entity_id: int,
        game_ids: object,
    ) -> None:
        ext = extractor_cls()

        def provider_call(*_args: object, **_kwargs: object) -> None:
            pytest.fail("provider must not be called")

        monkeypatch.setattr(ext, "_from_nba_api", provider_call)
        monkeypatch.setattr(ext, "_from_nba_api_multi", provider_call)

        with pytest.raises(CumeWorkloadContractError, match="serialized cume workload requires"):
            await getattr(ext, method_name)(
                **{
                    entity_key: entity_id,
                    "season": "2024-25",
                    "season_type": "Playoffs",
                    "game_ids": game_ids,
                }
            )

    @pytest.mark.parametrize(
        "extractor_cls, entity_kind, entity_id, provider_key",
        [
            (CumeStatsPlayerExtractor, "player", 201939, "PlayerID"),
            (CumeStatsTeamExtractor, "team", 1610612744, "TeamID"),
        ],
    )
    @pytest.mark.asyncio
    async def test_complete_workload_supplies_exact_bound_scope(
        self,
        monkeypatch: pytest.MonkeyPatch,
        extractor_cls: type,
        entity_kind: str,
        entity_id: int,
        provider_key: str,
    ) -> None:
        from nbadb.orchestrate.cume_workload_contract import (
            CumeEntityKind,
            CumeWorkloadValue,
        )

        ext = extractor_cls()
        captured: dict[str, object] = {}

        def _capture(_cls: type, **kwargs: object) -> pl.DataFrame:
            captured.update(kwargs)
            return pl.DataFrame({"value": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _capture)
        workload = CumeWorkloadValue.complete(
            entity_kind=CumeEntityKind(entity_kind),
            entity_id=entity_id,
            season="2024-25",
            season_type="Regular Season",
            game_ids=("0022400001", "0022400002"),
            foundation_receipt_sha256="a" * 64,
            provider_authority_sha256="b" * 64,
        )

        result = await ext.extract(workload=workload)

        assert result.to_dicts() == [{"value": 1}]
        assert captured == {
            provider_key.lower().replace("id", "_id").strip("_"): entity_id,
            "game_ids": "0022400001|0022400002",
            "season": "2024-25",
            "season_type_all_star": "Regular Season",
        }

    @pytest.mark.parametrize(
        "extractor_cls, entity_kind, entity_id, provider_key",
        [
            (CumeStatsPlayerExtractor, "player", 201939, "player_id"),
            (CumeStatsTeamExtractor, "team", 1610612744, "team_id"),
        ],
    )
    @pytest.mark.asyncio
    async def test_production_serialized_workload_roundtrips_exactly(
        self,
        monkeypatch: pytest.MonkeyPatch,
        extractor_cls: type,
        entity_kind: str,
        entity_id: int,
        provider_key: str,
    ) -> None:
        from nbadb.orchestrate.cume_workload_contract import (
            CumeEntityKind,
            CumeWorkloadValue,
        )
        from nbadb.orchestrate.planning import cume_workload_execution_params

        ext = extractor_cls()
        captured: dict[str, object] = {}

        def _capture(_cls: type, **kwargs: object) -> pl.DataFrame:
            captured.update(kwargs)
            return pl.DataFrame({"value": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _capture)
        workload = CumeWorkloadValue.complete(
            entity_kind=CumeEntityKind(entity_kind),
            entity_id=entity_id,
            season="2024-25",
            season_type="Regular Season",
            game_ids=("0022400001", "0022400002"),
            foundation_receipt_sha256="a" * 64,
            provider_authority_sha256="b" * 64,
        )

        params = cume_workload_execution_params(workload)
        params["snapshot_at"] = datetime(2026, 8, 27, 12, 30, tzinfo=UTC)
        result = await ext.extract(**params)

        assert result.to_dicts() == [{"value": 1}]
        assert captured == {
            provider_key: entity_id,
            "game_ids": "0022400001|0022400002",
            "season": "2024-25",
            "season_type_all_star": "Regular Season",
        }
        assert "snapshot_at" not in captured

    @pytest.mark.parametrize(
        "snapshot_at",
        [
            datetime(2026, 8, 27, 12, 30),
            "2026-08-27T12:30:00Z",
            _DatetimeSubclass(2026, 8, 27, 12, 30, tzinfo=UTC),
        ],
    )
    @pytest.mark.asyncio
    async def test_serialized_workload_rejects_invalid_snapshot_before_provider(
        self,
        monkeypatch: pytest.MonkeyPatch,
        snapshot_at: object,
    ) -> None:
        from nbadb.orchestrate.cume_workload_contract import (
            CumeEntityKind,
            CumeWorkloadValue,
        )
        from nbadb.orchestrate.planning import cume_workload_execution_params

        ext = CumeStatsPlayerExtractor()
        monkeypatch.setattr(
            ext,
            "_from_nba_api",
            lambda *_args, **_kwargs: pytest.fail("provider must not be called"),
        )
        workload = CumeWorkloadValue.complete(
            entity_kind=CumeEntityKind.PLAYER,
            entity_id=201939,
            season="2024-25",
            season_type="Regular Season",
            game_ids=("0022400001", "0022400002"),
            foundation_receipt_sha256="a" * 64,
            provider_authority_sha256="b" * 64,
        )
        params = cume_workload_execution_params(workload)
        params["snapshot_at"] = snapshot_at

        with pytest.raises(CumeWorkloadContractError, match="snapshot_at"):
            await ext.extract(**params)

    @pytest.mark.parametrize(
        "mutation",
        [
            lambda params: params.pop("foundation_receipt_sha256"),
            lambda params: params.pop("provider_authority_sha256"),
            lambda params: params.pop("cume_workload_sha256"),
            lambda params: params.__setitem__("cume_workload_sha256", "0" * 64),
            lambda params: params.__setitem__("game_ids", "0022400001|0022400002"),
            lambda params: params.__setitem__("game_ids", "0022400003|0022400002|0022400001"),
            lambda params: params.__setitem__("unknown_extra", "forbidden"),
        ],
    )
    @pytest.mark.asyncio
    async def test_serialized_workload_rejects_missing_or_rebound_authority_before_provider(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mutation: object,
    ) -> None:
        from nbadb.orchestrate.cume_workload_contract import (
            CumeEntityKind,
            CumeWorkloadValue,
        )
        from nbadb.orchestrate.planning import cume_workload_execution_params

        ext = CumeStatsPlayerExtractor()
        monkeypatch.setattr(
            ext,
            "_from_nba_api",
            lambda *_args, **_kwargs: pytest.fail("provider must not be called"),
        )
        workload = CumeWorkloadValue.complete(
            entity_kind=CumeEntityKind.PLAYER,
            entity_id=201939,
            season="2024-25",
            season_type="Regular Season",
            game_ids=("0022400001", "0022400002", "0022400003"),
            foundation_receipt_sha256="a" * 64,
            provider_authority_sha256="b" * 64,
        )
        params = cume_workload_execution_params(workload)
        mutation(params)  # type: ignore[operator]

        with pytest.raises(CumeWorkloadContractError, match="serialized cume workload"):
            await ext.extract(**params)

    @pytest.mark.parametrize(
        "game_ids",
        [
            "",
            "0022400001|0022400001",
            "0022400001|",
            "0022400001,0022400002",
            ["0022400001", 224000002],
        ],
    )
    @pytest.mark.asyncio
    async def test_explicit_game_ids_fail_closed_before_provider_call(
        self,
        monkeypatch: pytest.MonkeyPatch,
        game_ids: object,
    ) -> None:
        from nbadb.orchestrate.cume_workload_contract import CumeWorkloadContractError

        ext = CumeStatsPlayerExtractor()
        monkeypatch.setattr(
            ext,
            "_from_nba_api",
            lambda *_args, **_kwargs: pytest.fail("provider must not be called"),
        )

        with pytest.raises(CumeWorkloadContractError, match="serialized cume workload requires"):
            await ext.extract(
                player_id=201939,
                season="2024-25",
                game_ids=game_ids,
            )

    @pytest.mark.asyncio
    async def test_missing_or_ambiguous_workload_fails_closed(self) -> None:
        from nbadb.orchestrate.cume_workload_contract import (
            CumeEntityKind,
            CumeWorkloadContractError,
            CumeWorkloadValue,
        )

        ext = CumeStatsPlayerExtractor()
        complete = CumeWorkloadValue.complete(
            entity_kind=CumeEntityKind.PLAYER,
            entity_id=201939,
            season="2024-25",
            season_type="Regular Season",
            game_ids=("0022400001",),
            foundation_receipt_sha256="a" * 64,
            provider_authority_sha256="b" * 64,
        )

        with pytest.raises(CumeWorkloadContractError, match="serialized cume workload requires"):
            await ext.extract(player_id=201939, season="2024-25")
        with pytest.raises(CumeWorkloadContractError, match="not both"):
            await ext.extract(workload=complete, game_ids=("0022400001",))
        with pytest.raises(CumeWorkloadContractError, match="does not match"):
            await ext.extract(workload=complete, player_id=201566)

    @pytest.mark.parametrize(
        "extractor, workload",
        [
            (
                CumeStatsPlayerExtractor(),
                ("player", 201939),
            ),
            (
                CumeStatsTeamExtractor(),
                ("team", 1610612744),
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_typed_zero_is_rejected_as_non_executable(
        self,
        extractor: object,
        workload: tuple[str, int],
    ) -> None:
        from nbadb.orchestrate.cume_workload_contract import (
            CumeEntityKind,
            CumeWorkloadContractError,
            CumeWorkloadValue,
        )

        value = CumeWorkloadValue.typed_zero(
            entity_kind=CumeEntityKind(workload[0]),
            entity_id=workload[1],
            season="2024-25",
            season_type="Regular Season",
            reason_code="foundation_complete_no_games",
            foundation_receipt_sha256="a" * 64,
            provider_authority_sha256="b" * 64,
        )

        with pytest.raises(CumeWorkloadContractError, match="not executable"):
            await extractor.extract(workload=value)  # type: ignore[attr-defined]


class TestMiscLeadersExtractors:
    class _FakeResponse:
        def __init__(
            self,
            payload: object = None,
            raw_response: object = _RAW_RESPONSE_UNSET,
        ) -> None:
            self._payload = payload
            self._raw_response = (
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                if raw_response is _RAW_RESPONSE_UNSET
                else raw_response
            )
            self._status_code = 200

        def get_dict(self) -> dict[str, object]:
            if isinstance(self._payload, Exception):
                raise self._payload
            assert isinstance(self._raw_response, str)
            payload = json.loads(self._raw_response)
            assert isinstance(payload, dict)
            return payload

        def get_response(self) -> object:
            return self._raw_response

    @pytest.mark.asyncio
    async def test_dunk_score_leaders_parses_raw_payload_with_zero_ids(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = DunkScoreLeadersExtractor()
        captured: dict[str, object] = {}

        def _fake_send_api_request(
            self,
            **kwargs: object,
        ) -> TestMiscLeadersExtractors._FakeResponse:
            captured.update(kwargs)
            return TestMiscLeadersExtractors._FakeResponse(
                payload={
                    "params": {"Season": "2025-26"},
                    "dunks": [{"playerId": 1, "dunkScore": 8.5}],
                }
            )

        monkeypatch.setattr(
            "nbadb.extract.nba_api_adapter.NbaDbStatsHTTP.send_api_request",
            _fake_send_api_request,
        )

        result = await ext.extract(season="2025-26", season_type="Regular Season")

        assert result.to_dicts() == [{"player_id": 1, "dunk_score": 8.5}]
        parameters = captured["parameters"]
        assert isinstance(parameters, dict)
        typed_parameters = {str(key): value for key, value in parameters.items()}
        assert typed_parameters["PlayerID"] == "0"
        assert typed_parameters["TeamID"] == "0"
        assert typed_parameters["Season"] == "2025-26"
        assert typed_parameters["SeasonType"] == "Regular Season"

    @pytest.mark.asyncio
    async def test_dunk_score_leaders_fails_closed_for_unavailable_raw_response(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = DunkScoreLeadersExtractor()

        monkeypatch.setattr(
            "nbadb.extract.nba_api_adapter.NbaDbStatsHTTP.send_api_request",
            lambda self, **_kwargs: TestMiscLeadersExtractors._FakeResponse(
                payload=json.JSONDecodeError("bad json", "", 0),
                raw_response="",
            ),
        )

        from nbadb.core.errors import ResponseContractError

        with pytest.raises(ResponseContractError, match="malformed JSON"):
            await ext.extract(season="2025-26", season_type="Playoffs")

    @pytest.mark.asyncio
    async def test_gravity_leaders_parses_raw_payload(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = GravityLeadersExtractor()

        monkeypatch.setattr(
            "nbadb.extract.nba_api_adapter.NbaDbStatsHTTP.send_api_request",
            lambda self, **_kwargs: TestMiscLeadersExtractors._FakeResponse(
                payload={
                    "params": {"Season": "2025-26"},
                    "leaders": [{"PLAYERID": 1, "GRAVITYSCORE": 1.5}],
                }
            ),
        )

        result = await ext.extract(season="2025-26", season_type="Regular Season")

        assert result.to_dicts() == [{"playerid": 1, "gravityscore": 1.5}]

    @pytest.mark.asyncio
    async def test_gravity_leaders_fails_closed_for_forbidden_raw_response(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = GravityLeadersExtractor()

        monkeypatch.setattr(
            "nbadb.extract.nba_api_adapter.NbaDbStatsHTTP.send_api_request",
            lambda self, **_kwargs: TestMiscLeadersExtractors._FakeResponse(
                payload=json.JSONDecodeError("bad json", "", 0),
                raw_response=(
                    "System.Net.WebException: The remote server returned an error: (403) Forbidden."
                ),
            ),
        )

        from nbadb.core.errors import ResponseContractError

        with pytest.raises(ResponseContractError, match="malformed JSON"):
            await ext.extract(season="2024-25", season_type="Regular Season")


class TestDraftBoardExtractor:
    class _FakeResponse:
        def __init__(
            self,
            data_sets: dict[str, object] | Exception,
            raw_response: object = "",
        ) -> None:
            self._data_sets = data_sets
            self._raw_response = raw_response
            self._status_code = 200

        def get_dict(self) -> dict[str, object]:
            if isinstance(self._data_sets, Exception):
                raise self._data_sets
            return {
                "resultSets": [
                    {
                        "name": name,
                        "headers": payload["headers"],
                        "rowSet": payload["data"],
                    }
                    for name, payload in self._data_sets.items()
                    if isinstance(payload, dict)
                ]
            }

        def get_data_sets(self) -> dict[str, object]:
            if isinstance(self._data_sets, Exception):
                raise self._data_sets
            return self._data_sets

        def get_response(self) -> object:
            return self._raw_response

    @pytest.mark.asyncio
    async def test_draft_board_parses_tabular_payload(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = DraftBoardExtractor()
        captured: dict[str, object] = {}

        def _fake_from_nba_api(_endpoint_cls: type, **kwargs: object) -> pl.DataFrame:
            captured.update(kwargs)
            return pl.DataFrame({"person_id": [1], "player_name": ["Prospect"]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake_from_nba_api)

        result = await ext.extract(season="2025-26", season_type="Regular Season")

        assert result.to_dicts() == [
            {
                "person_id": 1,
                "player_name": "Prospect",
                "season": "2025-26",
                "season_type": "Regular Season",
            }
        ]
        assert captured == {"season_year": 2025}

    @pytest.mark.parametrize(
        "raw_response",
        [
            "",
            "System.Net.WebException: The remote server returned an error: (403) Forbidden.",
            (
                "Sap.Data.Hana.HanaException (0x80004005): Connection failed "
                "(RTE:[89013] Socket closed by peer)"
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_draft_board_fails_closed_for_unavailable_response(
        self,
        monkeypatch: pytest.MonkeyPatch,
        raw_response: str,
    ) -> None:
        ext = DraftBoardExtractor()

        monkeypatch.setattr(
            "nbadb.extract.nba_api_adapter.NbaDbStatsHTTP.send_api_request",
            lambda self, **_kwargs: TestDraftBoardExtractor._FakeResponse(
                data_sets=json.JSONDecodeError("bad json", "", 0),
                raw_response=raw_response,
            ),
        )

        from nbadb.core.errors import ResponseContractError

        with pytest.raises(ResponseContractError, match="malformed JSON"):
            await ext.extract(season="2025-26", season_type="Playoffs")

    @pytest.mark.asyncio
    async def test_draft_board_reraises_unknown_jsondecodeerror(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = DraftBoardExtractor()

        monkeypatch.setattr(
            "nbadb.extract.nba_api_adapter.NbaDbStatsHTTP.send_api_request",
            lambda self, **_kwargs: TestDraftBoardExtractor._FakeResponse(
                data_sets=json.JSONDecodeError("bad json", "", 0),
                raw_response='{"unexpected":',
            ),
        )

        from nbadb.core.errors import ResponseContractError

        with pytest.raises(ResponseContractError, match="malformed JSON"):
            await ext.extract(season="2025-26", season_type="Regular Season")


class TestISTStandingsExtractor:
    class _FakeResponse:
        def __init__(self, raw_response: object) -> None:
            self._raw_response = raw_response

        def get_response(self) -> object:
            return self._raw_response

    @pytest.mark.asyncio
    async def test_known_unavailable_season_still_fails_closed(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = ISTStandingsExtractor()

        def _boom(*_args: object, **_kwargs: object) -> pl.DataFrame:
            raise json.JSONDecodeError("bad json", "", 0)

        monkeypatch.setattr(ext, "_from_nba_api", _boom)
        with pytest.raises(json.JSONDecodeError, match="bad json"):
            await ext.extract(season="2021-22")

    @pytest.mark.asyncio
    async def test_other_seasons_still_raise_jsondecodeerror(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = ISTStandingsExtractor()

        def _boom(*_args: object, **_kwargs: object) -> pl.DataFrame:
            raise json.JSONDecodeError("bad json", "", 0)

        def _unexpected_raw_fallback(*_args: object, **_kwargs: object) -> object:
            raise AssertionError("unexpected raw fallback")

        monkeypatch.setattr(ext, "_from_nba_api", _boom)
        monkeypatch.setattr(
            "nbadb.extract.nba_api_adapter.NbaDbStatsHTTP.send_api_request",
            _unexpected_raw_fallback,
        )

        with pytest.raises(json.JSONDecodeError, match="bad json"):
            await ext.extract(season="2022-23")
