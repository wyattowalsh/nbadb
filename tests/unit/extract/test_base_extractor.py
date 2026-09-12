from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import MagicMock

import polars as pl
import pytest
from nba_api.live.nba.endpoints import ScoreBoard
from nba_api.stats.endpoints import LeagueGameLog, VideoEvents

from nbadb.core.errors import ResponseContractError
from nbadb.core.errors import ValidationError as NbaDbValidationError
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_runtime_contract import (
    endpoint_contract_sha256,
    owned_contract_sha256,
    pinned_endpoint_contract,
    pinned_live_endpoint_contract,
    pinned_static_dataset_contract,
)
from nbadb.extract.base import BaseExtractor
from nbadb.extract.bronze import ParserInputContext
from nbadb.extract.nba_api_adapter import (
    LOSSLESS_FALLBACK_SCHEMA,
    NbaApiCaptureContract,
    NbaApiLosslessFallback,
    NbaApiResultPacket,
    NbaApiResultPackets,
    NbaApiUnknownResponse,
)
from nbadb.extract.raw_schema_registry import get_raw_schema


class _StubExtractor(BaseExtractor):
    endpoint_name = "stub"
    category = "test"

    async def extract(self, **params: Any) -> pl.DataFrame:
        return pl.DataFrame({"a": [1, 2]})


def _capture_contract(attempt_id: str = "base-extractor") -> NbaApiCaptureContract:
    return NbaApiCaptureContract(
        sink=MagicMock(),
        context=ParserInputContext(attempt_id=attempt_id),
        provider_authority_sha256=expected_nba_api_provider_authority()["authority_sha256"],
        endpoint_contract_sha256="0" * 64,
    )


def _lossless_fallback(*, expected_result_set_count: int = 1) -> NbaApiLosslessFallback:
    frame = pl.DataFrame(
        [
            {
                "response_receipt_sha256": None,
                "endpoint_slug": "leaguegamelog",
                "record_kind": "missing_expected",
                "result_set_name": "Missing",
                "result_set_occurrence": 0,
                "provider_index": None,
                "canonical_index": 0,
                "header_name": None,
                "header_ordinal": None,
                "row_ordinal": None,
                "value_kind": None,
                "canonical_json": None,
                "anomaly_codes_json": '["missing_result_set"]',
            }
        ],
        schema=LOSSLESS_FALLBACK_SCHEMA,
        orient="row",
    )
    return NbaApiLosslessFallback(
        endpoint_slug="leaguegamelog",
        reason_codes=("missing_result_set",),
        provider_result_set_count=0,
        expected_result_set_count=expected_result_set_count,
        result_set_receipts=(),
        frame=frame,
    )


def _unknown_response(
    *,
    receipt_sha256: str | None = "a" * 64,
) -> NbaApiUnknownResponse:
    contract = pinned_endpoint_contract(VideoEvents)
    canonical_payload = '{"data":{}}'
    return NbaApiUnknownResponse(
        endpoint_id=contract.runtime_class_name,
        endpoint_slug=cast("str", contract.endpoint_slug),
        parameters_sha256="1" * 64,
        provider_authority_sha256=expected_nba_api_provider_authority()["authority_sha256"],
        endpoint_contract_sha256=endpoint_contract_sha256(contract),
        response_mode_authority_sha256=contract.response_contract.authority_sha256,
        parser_input_sha256="2" * 64,
        canonical_payload_json=canonical_payload,
        canonical_payload_sha256=hashlib.sha256(canonical_payload.encode()).hexdigest(),
        state="generic_nested_json",
        legacy_envelope_name=None,
        occurrences=(),
        response_receipt_sha256=receipt_sha256,
    )


@pytest.fixture(autouse=True)
def _adapt_legacy_boundary_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep BaseExtractor normalization tests independent of provider I/O."""

    def _fetch(endpoint_cls: type, **kwargs: Any) -> tuple[NbaApiResultPacket, ...]:
        endpoint = endpoint_cls(**kwargs)
        frames = endpoint.get_data_frames()
        return tuple(
            NbaApiResultPacket(
                name=f"Result{index}",
                provider_index=index,
                canonical_index=index,
                headers=tuple(str(column) for column in frame.columns),
                frame=pl.from_pandas(frame),
            )
            for index, frame in enumerate(frames)
        )

    def _fetch_live(
        endpoint_cls: type,
        packet_roots: dict[str, str],
        **kwargs: Any,
    ) -> dict[str, Any]:
        endpoint = endpoint_cls(**kwargs)
        payloads: dict[str, Any] = {}
        for attr in packet_roots:
            value = getattr(endpoint, attr)
            payloads[attr] = value.get_dict() if hasattr(value, "get_dict") else value
        return payloads

    monkeypatch.setattr("nbadb.extract.base.fetch_stats_packets", _fetch)
    monkeypatch.setattr("nbadb.extract.base.fetch_live_payloads", _fetch_live)


class TestCaptureContractBinding:
    def test_stats_contract_is_bound_when_runtime_endpoint_is_known(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        observed: list[NbaApiCaptureContract | None] = []

        def _fetch(
            _endpoint_cls: type,
            *,
            capture: NbaApiCaptureContract | None = None,
            **_kwargs: Any,
        ) -> tuple[NbaApiResultPacket, ...]:
            observed.append(capture)
            return (
                NbaApiResultPacket(
                    name="LeagueGameLog",
                    provider_index=0,
                    canonical_index=0,
                    headers=("VALUE",),
                    frame=pl.DataFrame({"VALUE": [1]}),
                ),
            )

        monkeypatch.setattr("nbadb.extract.base.fetch_stats_packets", _fetch)
        extractor = _StubExtractor()
        logical_contract = _capture_contract("stats-binding")
        extractor.set_capture_contract(logical_contract)

        result = extractor._from_nba_api(LeagueGameLog, season="2024-25")

        assert result.to_dicts() == [{"value": 1, "season_year": "2024-25"}]
        assert len(observed) == 1
        assert observed[0] is not None
        assert observed[0].receipt_ledger is logical_contract.receipt_ledger
        assert observed[0].endpoint_contract_sha256 == endpoint_contract_sha256(
            pinned_endpoint_contract(LeagueGameLog)
        )

    def test_live_contract_is_bound_when_runtime_endpoint_is_known(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        observed: list[NbaApiCaptureContract | None] = []

        def _fetch_live(
            _endpoint_cls: type,
            _packet_roots: dict[str, str],
            *,
            capture: NbaApiCaptureContract | None = None,
            **_kwargs: Any,
        ) -> dict[str, Any]:
            observed.append(capture)
            return {"games": []}

        monkeypatch.setattr("nbadb.extract.base.fetch_live_payloads", _fetch_live)
        monkeypatch.setattr("nbadb.extract.base.get_raw_schema", lambda _endpoint: None)
        extractor = _StubExtractor()
        logical_contract = _capture_contract("live-binding")
        extractor.set_capture_contract(logical_contract)

        result = extractor._from_nba_live(
            ScoreBoard,
            "games",
            source_endpoint="live_score_board",
            natural_keys=("game_id",),
            game_id="001",
        )

        assert result.is_empty()
        assert len(observed) == 1
        assert observed[0] is not None
        assert observed[0].receipt_ledger is logical_contract.receipt_ledger
        assert observed[0].endpoint_contract_sha256 == owned_contract_sha256(
            pinned_live_endpoint_contract(ScoreBoard)
        )

    def test_static_extractor_binds_its_exact_dataset_authority(self) -> None:
        class _StaticExtractor(BaseExtractor):
            endpoint_name = "static_teams"
            category = "static"

            async def extract(self, **_params: Any) -> pl.DataFrame:
                return pl.DataFrame()

        extractor = _StaticExtractor()
        logical_contract = _capture_contract("static-binding")

        extractor.set_capture_contract(logical_contract)

        assert extractor._capture_contract is not None
        assert extractor._capture_contract.receipt_ledger is logical_contract.receipt_ledger
        assert extractor._capture_contract.endpoint_contract_sha256 == owned_contract_sha256(
            pinned_static_dataset_contract("static_teams")
        )

    def test_unpinned_stats_class_is_rejected_without_inventing_a_digest(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class _UnknownStatsEndpoint:
            endpoint = "unknown"

        fetch = MagicMock()
        monkeypatch.setattr("nbadb.extract.base.fetch_stats_packets", fetch)
        extractor = _StubExtractor()
        extractor.set_capture_contract(_capture_contract("unknown-stats"))

        with pytest.raises(
            ResponseContractError,
            match="stats extractor lacks pinned nbadb capture authority",
        ):
            extractor._from_nba_api(_UnknownStatsEndpoint)

        fetch.assert_not_called()


class TestFromNbaApi:
    def test_lowercase_columns(self) -> None:
        ext = _StubExtractor()
        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [
            pd.DataFrame({"PLAYER_ID": [1], "PTS": [25]})
        ]
        result = ext._from_nba_api(mock_endpoint)
        assert set(result.columns) == {"player_id", "pts"}
        assert result.shape == (1, 2)

    def test_preserves_nba_stat_shorthand_columns(self) -> None:
        ext = _StubExtractor()
        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [
            pd.DataFrame({"FG3M": [4], "FG2A": [7], "PCT_AST_2PM": [0.6]})
        ]
        result = ext._from_nba_api(mock_endpoint)
        assert set(result.columns) == {"fg3m", "fg2a", "pct_ast_2pm"}

    def test_empty_data_frames(self) -> None:
        ext = _StubExtractor()
        mock_endpoint = MagicMock()
        mock_endpoint.return_value.get_data_frames.return_value = []
        result = ext._from_nba_api(mock_endpoint)
        assert result.shape == (0, 0)

    def test_fallback_only_single_result_remains_available_to_runner(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fallback = _lossless_fallback()
        monkeypatch.setattr(
            "nbadb.extract.base.fetch_stats_packets",
            lambda *_args, **_kwargs: NbaApiResultPackets(
                lossless_fallback=fallback,
            ),
        )
        ext = _StubExtractor()
        monkeypatch.setattr(
            ext,
            "_validate",
            lambda _df: (_ for _ in ()).throw(AssertionError("fallback must bypass wide schema")),
        )

        result = ext._from_nba_api(LeagueGameLog, season="2024-25")

        assert result.is_empty()
        assert ext.lossless_fallback_snapshot() == (fallback,)

    def test_later_no_drift_call_clears_prior_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fallback = _lossless_fallback()
        batches = iter(
            [
                NbaApiResultPackets(lossless_fallback=fallback),
                NbaApiResultPackets(
                    (
                        NbaApiResultPacket(
                            name="LeagueGameLog",
                            provider_index=0,
                            canonical_index=0,
                            headers=("VALUE",),
                            frame=pl.DataFrame({"VALUE": [1]}),
                        ),
                    )
                ),
            ]
        )
        monkeypatch.setattr(
            "nbadb.extract.base.fetch_stats_packets",
            lambda *_args, **_kwargs: next(batches),
        )
        ext = _StubExtractor()

        ext._from_nba_api(LeagueGameLog, season="2024-25")
        result = ext._from_nba_api(LeagueGameLog, season="2025-26")

        assert result.to_dicts() == [{"value": 1, "season_year": "2025-26"}]
        assert ext.lossless_fallback_snapshot() == ()


class TestUnknownResponseObservation:
    def test_exact_unknown_packet_is_retained_without_a_fixed_frame(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        observation = _unknown_response()
        monkeypatch.setattr(
            "nbadb.extract.base.fetch_stats_packets",
            lambda *_args, **_kwargs: NbaApiResultPackets(
                unknown_response=observation,
            ),
        )
        extractor = _StubExtractor()

        result = extractor._from_nba_api(
            VideoEvents,
            game_id="0022400001",
            game_event_id=7,
        )

        assert result.equals(pl.DataFrame())
        assert extractor.unknown_response_snapshot() == (observation,)
        assert extractor.lossless_fallback_snapshot() == ()

    def test_exact_unknown_endpoint_rejects_a_missing_typed_observation(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "nbadb.extract.base.fetch_stats_packets",
            lambda *_args, **_kwargs: NbaApiResultPackets(),
        )
        extractor = _StubExtractor()

        with pytest.raises(
            ResponseContractError,
            match="omitted its typed adapter observation",
        ):
            extractor._from_nba_api(
                VideoEvents,
                game_id="0022400001",
                game_event_id=7,
            )

        assert extractor.unknown_response_snapshot() == ()

    def test_unknown_observation_cannot_become_fixed_result_coverage(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        observation = _unknown_response()
        invented_packet = NbaApiResultPacket(
            name="Invented",
            provider_index=0,
            canonical_index=0,
            headers=("VALUE",),
            frame=pl.DataFrame({"VALUE": [1]}),
            response_receipt_sha256=observation.response_receipt_sha256,
        )
        monkeypatch.setattr(
            "nbadb.extract.base.fetch_stats_packets",
            lambda *_args, **_kwargs: NbaApiResultPackets(
                (invented_packet,),
                unknown_response=observation,
            ),
        )
        extractor = _StubExtractor()

        with pytest.raises(
            ResponseContractError,
            match="cannot carry fixed result packets",
        ):
            extractor._from_nba_api(
                VideoEvents,
                game_id="0022400001",
                game_event_id=7,
            )

        assert extractor.unknown_response_snapshot() == ()

    def test_mutated_unknown_authority_marks_the_exact_receipt_incomplete(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        observation = _unknown_response()
        mutated = replace(observation, endpoint_id="VideoDetails")
        monkeypatch.setattr(
            "nbadb.extract.base.fetch_stats_packets",
            lambda *_args, **_kwargs: NbaApiResultPackets(
                unknown_response=mutated,
            ),
        )
        marked: list[tuple[BaseException, str | None]] = []
        extractor = _StubExtractor()

        def _mark(
            exc: BaseException,
            *,
            receipt_sha256: str | None = None,
        ) -> None:
            marked.append((exc, receipt_sha256))

        monkeypatch.setattr(extractor, "_mark_raw_request_downstream_incomplete", _mark)

        with pytest.raises(
            ResponseContractError,
            match="differs from extraction authority",
        ):
            extractor._from_nba_api(
                VideoEvents,
                game_id="0022400001",
                game_event_id=7,
            )

        assert len(marked) == 1
        assert marked[0][1] == observation.response_receipt_sha256
        assert extractor.unknown_response_snapshot() == ()

    def test_attempt_reset_clears_unknown_response_observations(self) -> None:
        extractor = _StubExtractor()
        extractor._unknown_responses = (_unknown_response(),)

        extractor.begin_extraction_attempt()

        assert extractor.unknown_response_snapshot() == ()


class TestFromNbaApiMulti:
    def test_returns_multiple_lowercased(self) -> None:
        ext = _StubExtractor()
        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [
            pd.DataFrame({"GAME_ID": ["001"], "PTS": [100]}),
            pd.DataFrame({"TEAM_ID": [1], "WINS": [50]}),
        ]
        results = ext._from_nba_api_multi(mock_endpoint)
        assert len(results) == 2
        assert "game_id" in results[0].columns
        assert "team_id" in results[1].columns

    def test_skips_unsafe_generic_validation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ext = _StubExtractor()
        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [
            pd.DataFrame({"GAME_ID": ["001"]}),
            pd.DataFrame({"TEAM_ID": [1]}),
        ]
        monkeypatch.setattr(
            ext,
            "_validate",
            lambda _df: (_ for _ in ()).throw(AssertionError("should not validate multi packets")),
        )

        results = ext._from_nba_api_multi(mock_endpoint)
        assert len(results) == 2

    def test_drift_placeholder_preserves_safe_packet_canonical_index(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fallback = _lossless_fallback(expected_result_set_count=2)
        safe_second = NbaApiResultPacket(
            name="Second",
            provider_index=0,
            canonical_index=1,
            headers=("VALUE",),
            frame=pl.DataFrame({"VALUE": [2]}),
        )
        monkeypatch.setattr(
            "nbadb.extract.base.fetch_stats_packets",
            lambda *_args, **_kwargs: NbaApiResultPackets(
                (safe_second,),
                lossless_fallback=fallback,
            ),
        )
        ext = _StubExtractor()

        results = ext._from_nba_api_multi(LeagueGameLog, season="2024-25")

        assert len(results) == 2
        assert results[0].is_empty()
        assert results[1].to_dicts() == [{"value": 2, "season_year": "2024-25"}]
        assert ext.lossless_fallback_snapshot() == (fallback,)

    def test_injects_season_type_and_league_scope_into_every_result_set(self) -> None:
        ext = _StubExtractor()
        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [
            pd.DataFrame({"VALUE": [1]}),
            pd.DataFrame({"OTHER": [2]}),
        ]

        results = ext._from_nba_api_multi(
            mock_endpoint,
            season="2024-25",
            season_type_all_star="Playoffs",
            league_id_nullable="10",
        )

        assert len(results) == 2
        for result in results:
            assert result["season_year"].to_list() == ["2024-25"]
            assert result["season_type"].to_list() == ["Playoffs"]
            assert result["league_id"].to_list() == ["10"]

    def test_provider_scope_columns_are_never_overwritten(self) -> None:
        ext = _StubExtractor()
        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [
            pd.DataFrame(
                {
                    "SEASON_YEAR": ["provider-season"],
                    "SEASON_TYPE": ["provider-type"],
                    "LEAGUE_ID": ["provider-league"],
                }
            )
        ]

        result = ext._from_nba_api_multi(
            mock_endpoint,
            season="2024-25",
            season_type_all_star="Playoffs",
            league_id_nullable="10",
        )[0]

        assert result.to_dicts() == [
            {
                "season_year": "provider-season",
                "season_type": "provider-type",
                "league_id": "provider-league",
            }
        ]


class TestTimeoutInjection:
    def test_timeout_override_injected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NBADB_REQUEST_TIMEOUT", "15")
        ext = _StubExtractor()

        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [pd.DataFrame({"COL": [1]})]
        ext._from_nba_api(mock_endpoint)
        call_kwargs = mock_endpoint.call_args[1]
        assert call_kwargs["timeout"] == 15

    def test_invalid_timeout_override_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NBADB_REQUEST_TIMEOUT", "abc")
        ext = _StubExtractor()

        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [pd.DataFrame({"COL": [1]})]
        ext._from_nba_api(mock_endpoint)
        call_kwargs = mock_endpoint.call_args[1]
        assert "timeout" not in call_kwargs

    def test_runner_timeout_override_takes_precedence(self) -> None:
        ext = _StubExtractor()
        ext._request_timeout_override = 45

        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [pd.DataFrame({"COL": [1]})]
        ext._from_nba_api(mock_endpoint)
        call_kwargs = mock_endpoint.call_args[1]
        assert call_kwargs["timeout"] == 45

    def test_timeout_cap_lowers_runner_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NBADB_REQUEST_TIMEOUT_CAP", "10")
        ext = _StubExtractor()
        ext._request_timeout_override = 45

        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [pd.DataFrame({"COL": [1]})]
        ext._from_nba_api(mock_endpoint)
        call_kwargs = mock_endpoint.call_args[1]
        assert call_kwargs["timeout"] == 10

    def test_invalid_timeout_cap_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NBADB_REQUEST_TIMEOUT_CAP", "abc")
        ext = _StubExtractor()
        ext._request_timeout_override = 45

        mock_endpoint = MagicMock()
        import pandas as pd

        mock_endpoint.return_value.get_data_frames.return_value = [pd.DataFrame({"COL": [1]})]
        ext._from_nba_api(mock_endpoint)
        call_kwargs = mock_endpoint.call_args[1]
        assert call_kwargs["timeout"] == 45

    def test_timeout_cap_lowers_explicit_scalar(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NBADB_REQUEST_TIMEOUT_CAP", "10")
        ext = _StubExtractor()
        kwargs: dict[str, Any] = {"timeout": 30}

        ext._inject_timeout(kwargs)

        assert kwargs["timeout"] == 10

    def test_timeout_cap_lowers_explicit_tuple(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NBADB_REQUEST_TIMEOUT_CAP", "10")
        ext = _StubExtractor()
        kwargs: dict[str, Any] = {"timeout": (3.05, 30)}

        ext._inject_timeout(kwargs)

        assert kwargs["timeout"] == (3.05, 10.0)


class TestExtractIsAbstract:
    def test_cannot_instantiate_base(self) -> None:
        with pytest.raises(TypeError):
            BaseExtractor()  # type: ignore[abstract]


class TestLiveSnapshotContract:
    def test_injects_snapshot_metadata_and_param_backed_keys(self) -> None:
        frame = pl.DataFrame({"action_number": [1]})
        snapshot_at = datetime(2026, 4, 17, 12, 30, tzinfo=UTC)

        result = BaseExtractor._apply_live_snapshot_contract(
            frame,
            source_endpoint="live_play_by_play",
            natural_keys=("game_id", "action_number"),
            snapshot_at=snapshot_at,
            params={"game_id": "001"},
        )

        assert result.columns == [
            "action_number",
            "game_id",
            "snapshot_at",
            "snapshot_date",
            "source_endpoint",
            "payload_json",
        ]
        assert result.to_dicts() == [
            {
                "action_number": 1,
                "game_id": "001",
                "snapshot_at": snapshot_at,
                "snapshot_date": snapshot_at.date(),
                "source_endpoint": "live_play_by_play",
                "payload_json": None,
            }
        ]

    def test_raises_when_non_empty_live_payload_lacks_required_key(self) -> None:
        frame = pl.DataFrame({"value": [1]})

        with pytest.raises(
            NbaDbValidationError,
            match="missing required natural keys: game_id",
        ):
            BaseExtractor._apply_live_snapshot_contract(
                frame,
                source_endpoint="live_score_board",
                natural_keys=("game_id",),
                snapshot_at=datetime(2026, 4, 17, tzinfo=UTC),
                params={},
            )


class TestSchemaValidationTranslation:
    def test_validate_translates_schema_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ext = _StubExtractor()

        class _BrokenSchema:
            @staticmethod
            def validate(_df: pl.DataFrame) -> pl.DataFrame:
                raise ValueError("bad schema")

        monkeypatch.setattr("nbadb.extract.base.get_raw_schema", lambda _endpoint: _BrokenSchema)

        with pytest.raises(NbaDbValidationError, match="stub: raw schema validation failed"):
            ext._validate(pl.DataFrame({"a": [1]}))

    def test_live_validation_translates_schema_errors(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = _StubExtractor()

        class _BrokenSchema:
            @staticmethod
            def validate(_df: pl.DataFrame) -> pl.DataFrame:
                raise ValueError("bad live schema")

        class _LiveEndpoint:
            def __init__(self, **_kwargs: object) -> None:
                self.games = [{"gameId": "001"}]

        monkeypatch.setattr(
            "nbadb.extract.landing_projection.get_raw_schema",
            lambda endpoint: _BrokenSchema if endpoint == "live_score_board" else None,
        )

        live_endpoint_cls: type = _LiveEndpoint
        with pytest.raises(
            NbaDbValidationError,
            match="live_score_board: raw schema validation failed",
        ):
            ext._from_nba_live(
                live_endpoint_cls,
                "games",
                source_endpoint="live_score_board",
                natural_keys=("game_id",),
            )


class TestRawSchemaRegistry:
    def test_get_raw_schema_uses_shared_registry_aliases(self) -> None:
        schedule_schema = get_raw_schema("schedule")
        live_schema = get_raw_schema("live_box_score.home_team_stats")

        assert schedule_schema is not None
        assert schedule_schema.__name__ == "RawScheduleLeagueV2Schema"
        assert live_schema is not None
        assert live_schema.__name__ == "RawLiveBoxScoreTeamStatsSchema"

    def test_get_raw_schema_resolves_misc_leader_endpoints(self) -> None:
        dunk_schema = get_raw_schema("dunk_score_leaders")
        gravity_schema = get_raw_schema("gravity_leaders")

        assert dunk_schema is not None
        assert dunk_schema.__name__ == "RawDunkScoreLeadersSchema"
        assert gravity_schema is not None
        assert gravity_schema.__name__ == "RawGravityLeadersSchema"
