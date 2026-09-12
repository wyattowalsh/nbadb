from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field, fields, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import polars as pl

from nbadb.contracts.raw_request_reconstruction import LiveSnapshotPlanAuthorityV2
from nbadb.core.config import NbaDbSettings, get_settings
from nbadb.core.errors import ParserInputCaptureIntegrityError
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_runtime_contract import owned_contract_sha256, pinned_live_contracts
from nbadb.extract.bronze import (
    BronzeCaptureStore,
    BronzeLimits,
    LogicalCallReceiptBinding,
    ParserInputContext,
    canonical_parameters_sha256,
)
from nbadb.extract.live.endpoints import (
    LiveBoxScoreExtractor,
    LiveOddsExtractor,
    LivePlayByPlayExtractor,
    LiveScoreBoardExtractor,
)
from nbadb.extract.live_lossless import LIVE_LOSSLESS_STAGING_KEY
from nbadb.extract.nba_api_adapter import NbaApiCaptureContract, NbaApiReceiptSnapshot
from nbadb.extract.raw_request_capture import (
    RawRequestCaptureContextV2,
    RawRequestCaptureContract,
    RawRequestCaptureSnapshotV2,
)
from nbadb.orchestrate.extractor_runner import ExtractorRunner, _sync_extract, _sync_extract_all
from nbadb.schemas.registry import get_input_schema

if TYPE_CHECKING:
    from nbadb.extract.base import BaseExtractor

_LIVE_BOX_SCORE_STAGING_KEYS = [
    "stg_live_box_score_game_details",
    "stg_live_box_score_arena",
    "stg_live_box_score_officials",
    "stg_live_box_score_team_stats_home",
    "stg_live_box_score_team_stats_away",
    "stg_live_box_score_player_stats_home",
    "stg_live_box_score_player_stats_away",
]

_LIVE_RAW_SCHEMA_BY_STAGING_KEY = {
    "stg_live_score_board": "raw_live_score_board",
    "stg_live_odds": "raw_live_odds",
    "stg_live_play_by_play": "raw_live_play_by_play",
    "stg_live_box_score_game_details": "raw_live_box_score_game_details",
    "stg_live_box_score_arena": "raw_live_box_score_arena",
    "stg_live_box_score_officials": "raw_live_box_score_officials",
    "stg_live_box_score_team_stats_home": "raw_live_box_score_team_stats",
    "stg_live_box_score_team_stats_away": "raw_live_box_score_team_stats",
    "stg_live_box_score_player_stats_home": "raw_live_box_score_player_stats",
    "stg_live_box_score_player_stats_away": "raw_live_box_score_player_stats",
}

_LIVE_ROUTE_IDS_BY_ENDPOINT = {
    "live_score_board": ("live_score_board:stg_live_score_board:0",),
    "live_odds": ("live_odds:stg_live_odds:0",),
    "live_play_by_play": ("live_play_by_play:stg_live_play_by_play:0",),
    "live_box_score": tuple(
        f"live_box_score:{staging_key}:{result_set_index}"
        for result_set_index, staging_key in enumerate(_LIVE_BOX_SCORE_STAGING_KEYS)
    ),
}

_LIVE_PROVIDER_ENDPOINT_ID_BY_ENDPOINT = {
    "live_score_board": "ScoreBoard",
    "live_odds": "Odds",
    "live_play_by_play": "PlayByPlay",
    "live_box_score": "BoxScore",
}

CaptureContractFactory = Callable[[str, dict[str, object]], NbaApiCaptureContract]
CaptureCompletionCallback = Callable[[LogicalCallReceiptBinding], None]
RawRequestCaptureContextFactory = Callable[
    [str, dict[str, object]],
    RawRequestCaptureContextV2,
]
LivePlanAuthorityBindingFactory = Callable[
    [
        str,
        dict[str, object],
        tuple[str, ...],
        datetime,
        RawRequestCaptureSnapshotV2,
    ],
    tuple[LiveSnapshotPlanAuthorityV2, str],
]
LiveCallAdmission = Callable[[str, dict[str, object], tuple[str, ...]], None]
LiveConditionalRouteAdmission = Callable[
    [str, dict[str, object], tuple[str, ...], tuple[str, ...]],
    None,
]


class _RecurringLiveReceiptSession:
    """Single-use private receipts retained until exact W2 admission."""

    def __init__(self, settings: NbaDbSettings) -> None:
        self._temporary_root = tempfile.TemporaryDirectory(prefix="nbadb-recurring-live-receipts-")
        try:
            self.sink = BronzeCaptureStore(
                Path(self._temporary_root.name).resolve() / "bronze",
                limits=BronzeLimits(
                    max_response_bytes=128 * 1024 * 1024,
                    max_generation_stored_bytes=2 * 1024 * 1024 * 1024,
                    minimum_free_bytes=1,
                    max_receipt_count=10_000,
                ),
                public_roots=(settings.data_dir,),
            )
        except BaseException:
            self._temporary_root.cleanup()
            raise
        self.provider_authority_sha256 = expected_nba_api_provider_authority()["authority_sha256"]
        self._call_ordinal = 0
        self._closed = False

    def contract_for(
        self,
        endpoint_name: str,
        params: dict[str, object],
        *,
        raw_context: RawRequestCaptureContextV2,
    ) -> NbaApiCaptureContract:
        expected_routes = _LIVE_ROUTE_IDS_BY_ENDPOINT.get(endpoint_name)
        if expected_routes is None:
            raise ParserInputCaptureIntegrityError(
                "recurring live receipt requested an unknown endpoint"
            )
        scope_sha256 = canonical_parameters_sha256(params)
        ordinal = self._call_ordinal
        self._call_ordinal += 1
        provider_endpoint_id = _LIVE_PROVIDER_ENDPOINT_ID_BY_ENDPOINT.get(endpoint_name)
        if provider_endpoint_id is None:
            raise ParserInputCaptureIntegrityError(
                "recurring live receipt lacks exact provider endpoint authority"
            )
        try:
            endpoint_contract_sha256 = owned_contract_sha256(
                pinned_live_contracts()[provider_endpoint_id]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ParserInputCaptureIntegrityError(
                "recurring live receipt lacks exact endpoint contract authority"
            ) from exc
        return NbaApiCaptureContract(
            sink=self.sink,
            context=ParserInputContext(
                attempt_id=f"recurring-live-{ordinal:06d}-{scope_sha256[:16]}",
                workflow_run_id=raw_context.run_id,
                workflow_run_attempt=raw_context.run_attempt,
                chain_id=raw_context.chain_id,
                lane_id=raw_context.lane_id,
                semantic_source_sha=raw_context.source_sha,
            ),
            provider_authority_sha256=self.provider_authority_sha256,
            endpoint_contract_sha256=endpoint_contract_sha256,
        )

    @staticmethod
    def admit_call(
        endpoint_name: str,
        params: dict[str, object],
        result_route_ids: tuple[str, ...],
    ) -> None:
        expected_routes = _LIVE_ROUTE_IDS_BY_ENDPOINT.get(endpoint_name)
        if expected_routes is None or result_route_ids != expected_routes:
            raise ParserInputCaptureIntegrityError(
                "recurring live call differs from its fixed static route authority"
            )
        if endpoint_name in {"live_score_board", "live_odds"}:
            valid_params = params == {}
        else:
            valid_params = (
                set(params) == {"game_id"}
                and isinstance(params.get("game_id"), str)
                and bool(params["game_id"])
            )
        if not valid_params:
            raise ParserInputCaptureIntegrityError(
                "recurring live call differs from its fixed parameter contract"
            )
        canonical_parameters_sha256(params)

    def admit_conditional_routes(
        self,
        endpoint_name: str,
        params: dict[str, object],
        static_route_ids: tuple[str, ...],
        conditional_route_ids: tuple[str, ...],
    ) -> None:
        self.admit_call(endpoint_name, params, static_route_ids)
        from nbadb.contracts.staging_route_contract import (
            admit_conditional_live_lossless_route,
        )

        try:
            admit_conditional_live_lossless_route(
                endpoint_name=endpoint_name,
                static_route_ids=static_route_ids,
                conditional_route_ids=conditional_route_ids,
                provider_authority_sha256=self.provider_authority_sha256,
            )
        except ValueError as exc:
            raise ParserInputCaptureIntegrityError(
                "recurring live-lossless route differs from typed provider authority"
            ) from exc

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.sink.close()
        finally:
            self._closed = True
            self._temporary_root.cleanup()

    @property
    def available(self) -> bool:
        return not self._closed and self.sink.root.is_dir()


@dataclass(frozen=True, slots=True)
class _LiveLosslessProjection:
    frame: pl.DataFrame
    route_id: str


@dataclass(frozen=True, slots=True)
class _LiveProviderCallEvidence:
    binding: LogicalCallReceiptBinding
    receipt_snapshot: NbaApiReceiptSnapshot
    raw_context: RawRequestCaptureContextV2
    raw_snapshot: RawRequestCaptureSnapshotV2
    live_plan_authority: LiveSnapshotPlanAuthorityV2
    expected_live_plan_authority_sha256: str
    live_lossless: _LiveLosslessProjection | None


@dataclass(frozen=True, slots=True)
class LiveSourceCallResult:
    """Immutable route-local result for one exact live provider call."""

    endpoint_name: str
    parameters_json: str
    _frame_items: tuple[tuple[str, pl.DataFrame], ...]
    expected_staging_keys: tuple[str, ...]
    result_route_ids_by_staging_key: tuple[tuple[str, str], ...]
    receipt_binding: LogicalCallReceiptBinding | None
    call_ordinal: int = 0
    capture_receipt_snapshot: NbaApiReceiptSnapshot | None = None
    raw_request_capture_context: RawRequestCaptureContextV2 | None = None
    raw_request_capture_snapshot: RawRequestCaptureSnapshotV2 | None = None
    live_plan_authority: LiveSnapshotPlanAuthorityV2 | None = None
    expected_live_plan_authority_sha256: str | None = None

    @property
    def params(self) -> dict[str, object]:
        """Return a detached copy of the canonical logical-call parameters."""

        parsed = json.loads(self.parameters_json)
        if not isinstance(parsed, dict):
            raise ParserInputCaptureIntegrityError(
                "live source call parameters are not a JSON object"
            )
        return parsed

    @property
    def frames(self) -> dict[str, pl.DataFrame]:
        """Return detached frame clones keyed by exact staging route."""

        return {staging_key: frame.clone() for staging_key, frame in self._frame_items}

    def replay_exact_source_evidence(
        self,
    ) -> tuple[
        LogicalCallReceiptBinding,
        RawRequestCaptureSnapshotV2,
        LiveSnapshotPlanAuthorityV2,
        str,
    ]:
        """Revalidate the exact per-call evidence before downstream mutation."""

        binding = self.receipt_binding
        receipt_snapshot = self.capture_receipt_snapshot
        raw_context = self.raw_request_capture_context
        raw_snapshot = self.raw_request_capture_snapshot
        authority = self.live_plan_authority
        expected_authority_sha256 = self.expected_live_plan_authority_sha256
        if (
            type(binding) is not LogicalCallReceiptBinding
            or type(receipt_snapshot) is not NbaApiReceiptSnapshot
            or type(raw_context) is not RawRequestCaptureContextV2
            or type(raw_snapshot) is not RawRequestCaptureSnapshotV2
            or type(authority) is not LiveSnapshotPlanAuthorityV2
            or type(expected_authority_sha256) is not str
        ):
            raise ParserInputCaptureIntegrityError(
                "live source call lacks exact Raw V2 and live-plan evidence"
            )
        if type(self.call_ordinal) is not int or self.call_ordinal < 0:
            raise ParserInputCaptureIntegrityError("live source call ordinal is invalid")
        try:
            replayed_context = RawRequestCaptureContextV2.model_validate(
                raw_context.model_dump(mode="python", round_trip=True),
                strict=True,
            )
            replayed_authority = LiveSnapshotPlanAuthorityV2(
                **{item.name: getattr(authority, item.name) for item in fields(authority)}
            )
        except Exception as exc:
            raise ParserInputCaptureIntegrityError(
                "live source call exact authority failed strict replay"
            ) from exc
        if replayed_context != raw_context or replayed_authority != authority:
            raise ParserInputCaptureIntegrityError(
                "live source call exact authority changed during replay"
            )
        try:
            ExtractorRunner._validate_raw_request_capture_snapshot_shape(raw_snapshot)
        except Exception as exc:
            raise ParserInputCaptureIntegrityError(
                "live source call Raw V2 snapshot failed strict replay"
            ) from exc
        pending = raw_snapshot.pending_successes
        attempts = (
            *(item.attempt for item in raw_snapshot.observations),
            *(item.attempt for item in pending),
        )
        if any(
            not ExtractorRunner._attempt_matches_raw_request_context(
                attempt,
                raw_context,
                retry_ordinal=attempt.retry_ordinal,
            )
            for attempt in attempts
        ):
            raise ParserInputCaptureIntegrityError(
                "live source call Raw V2 snapshot crosses its capture context"
            )
        successful_receipts = {
            item.receipt_sha256 for item in receipt_snapshot.entries if item.successful
        }
        route_ids = tuple(
            route_id for _staging_key, route_id in self.result_route_ids_by_staging_key
        )
        if (
            len(pending) != 1
            or raw_snapshot.issues
            or pending[0].private_receipt_sha256 not in successful_receipts
            or pending[0].logical_receipt_sha256 != binding.logical_call_receipt_sha256
            or pending[0].aggregate_route_ids != binding.result_route_ids
            or tuple(sorted(route_ids)) != binding.result_route_ids
            or authority.authority_sha256 != expected_authority_sha256
            or authority.observation_sha256 != pending[0].attempt.observation_sha256
            or len(authority.route_ids) != len(route_ids)
            or set(authority.route_ids) != set(route_ids)
            or authority.live_snapshot_at.tzinfo is not UTC
            or authority.live_snapshot_at.fold != 0
        ):
            raise ParserInputCaptureIntegrityError(
                "live source call evidence crosses its receipt, route, or sealed plan"
            )
        return binding, raw_snapshot, authority, expected_authority_sha256


@dataclass(frozen=True, slots=True)
class LiveSnapshotExtraction:
    """Extraction-only live snapshot evidence, before any warehouse mutation."""

    snapshot_at: datetime
    game_ids: tuple[str, ...]
    source_calls: tuple[LiveSourceCallResult, ...]
    _evidence_lease: _RecurringLiveReceiptSession | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    @property
    def source_evidence_available(self) -> bool:
        """Whether a transferred temporary private-receipt root is still readable."""

        return self._evidence_lease is None or self._evidence_lease.available

    def replay_exact_source_evidence(self) -> None:
        """Prove complete ordered per-call evidence before W2 coordination."""

        if not self.source_evidence_available:
            raise ParserInputCaptureIntegrityError(
                "live snapshot private source evidence was already released"
            )
        if not self.source_calls:
            raise ParserInputCaptureIntegrityError(
                "live snapshot lacks its mandatory scoreboard source call"
            )
        if (
            type(self.game_ids) is not tuple
            or any(type(game_id) is not str or not game_id for game_id in self.game_ids)
            or len(self.game_ids) != len(set(self.game_ids))
        ):
            raise ParserInputCaptureIntegrityError(
                "live snapshot game inventory is not exact ordered unique text"
            )
        expected_calls: list[tuple[str, dict[str, object]]] = [("live_score_board", {})]
        if self.game_ids:
            expected_calls.append(("live_odds", {}))
            for game_id in self.game_ids:
                expected_params: dict[str, object] = {"game_id": game_id}
                expected_calls.append(("live_play_by_play", expected_params))
                expected_calls.append(("live_box_score", dict(expected_params)))
        if len(self.source_calls) != len(expected_calls):
            raise ParserInputCaptureIntegrityError(
                "live snapshot source-call inventory differs from its game plan"
            )
        for expected_ordinal, source_call in enumerate(self.source_calls):
            if type(source_call) is not LiveSourceCallResult:
                raise ParserInputCaptureIntegrityError(
                    "live snapshot contains a foreign source-call result"
                )
            if source_call.call_ordinal != expected_ordinal:
                raise ParserInputCaptureIntegrityError(
                    "live snapshot source-call ordering differs from its exact plan"
                )
            expected_endpoint, expected_params = expected_calls[expected_ordinal]
            if (
                source_call.endpoint_name != expected_endpoint
                or source_call.params != expected_params
            ):
                raise ParserInputCaptureIntegrityError(
                    "live snapshot source-call ordering differs from its exact plan"
                )
            source_call.replay_exact_source_evidence()

    def release_source_evidence(self) -> None:
        """Release temporary private bytes only after W2 admission is durable."""

        if self._evidence_lease is not None:
            self._evidence_lease.close()


@dataclass(frozen=True, slots=True)
class LiveSnapshotResult:
    snapshot_at: datetime
    game_ids: list[str]
    staging_tables_persisted: int
    star_tables_loaded: int
    staging_rows_persisted: int
    star_rows_loaded: int


class LiveSnapshotWarehouse:
    """Live provider extraction plus the standalone append-only warehouse path.

    Standalone ``run`` deliberately avoids the historical journal and
    replace-style flow. Successor orchestration uses ``extract_source_calls``
    and owns route-local replacement persistence itself.
    """

    def __init__(
        self,
        settings: NbaDbSettings | None = None,
        *,
        public_recurring: bool = False,
        capture_contract_factory: CaptureContractFactory | None = None,
        capture_completion_callback: CaptureCompletionCallback | None = None,
        call_admission: LiveCallAdmission | None = None,
        conditional_route_admission: LiveConditionalRouteAdmission | None = None,
        raw_request_capture_context_factory: RawRequestCaptureContextFactory | None = None,
        live_plan_authority_binding_factory: LivePlanAuthorityBindingFactory | None = None,
    ) -> None:
        if not isinstance(public_recurring, bool):
            raise TypeError("public_recurring must be a boolean")
        if public_recurring and any(
            value is not None
            for value in (
                capture_contract_factory,
                capture_completion_callback,
                call_admission,
                conditional_route_admission,
            )
        ):
            raise ValueError(
                "public recurring live receipts cannot be combined with injected capture"
            )
        resolved_settings = settings if settings is not None else get_settings()
        recurring_receipts = (
            _RecurringLiveReceiptSession(resolved_settings) if public_recurring else None
        )
        if recurring_receipts is not None:
            call_admission = recurring_receipts.admit_call
            conditional_route_admission = recurring_receipts.admit_conditional_routes
        if capture_completion_callback is not None and capture_contract_factory is None:
            raise ValueError("live snapshot capture completion requires a capture contract factory")
        if (
            capture_contract_factory is not None
            and capture_completion_callback is None
            and call_admission is None
        ):
            raise ValueError(
                "live snapshot capture factory and completion callback must be paired "
                "outside admitted extraction-only mode"
            )
        if conditional_route_admission is not None and (
            (capture_contract_factory is None and recurring_receipts is None)
            or call_admission is None
        ):
            raise ValueError("live conditional admission requires captured admitted extraction")
        self._settings = resolved_settings
        self._capture_contract_factory = capture_contract_factory
        self._capture_completion_callback = capture_completion_callback
        self._call_admission = call_admission
        self._conditional_route_admission = conditional_route_admission
        self._raw_request_capture_context_factory = raw_request_capture_context_factory
        self._live_plan_authority_binding_factory = live_plan_authority_binding_factory
        self._recurring_receipts = recurring_receipts
        self._capture_provider_authority_sha256 = (
            expected_nba_api_provider_authority()["authority_sha256"]
            if capture_contract_factory is not None or recurring_receipts is not None
            else None
        )

    def _raw_context_for_call(
        self,
        endpoint_name: str,
        params: dict[str, object],
    ) -> RawRequestCaptureContextV2 | None:
        factory = self._raw_request_capture_context_factory
        if factory is None:
            return None
        try:
            context = factory(endpoint_name, dict(params))
        except Exception as exc:
            raise ParserInputCaptureIntegrityError(
                "live snapshot Raw V2 context factory failed"
            ) from exc
        if type(context) is not RawRequestCaptureContextV2:
            raise ParserInputCaptureIntegrityError(
                "live snapshot Raw V2 context factory returned a foreign authority"
            )
        try:
            replayed = RawRequestCaptureContextV2.model_validate(
                context.model_dump(mode="python", round_trip=True),
                strict=True,
            )
        except Exception as exc:
            raise ParserInputCaptureIntegrityError(
                "live snapshot Raw V2 context failed strict replay"
            ) from exc
        provider_endpoint_id = _LIVE_PROVIDER_ENDPOINT_ID_BY_ENDPOINT.get(endpoint_name)
        if provider_endpoint_id is None:
            raise ParserInputCaptureIntegrityError(
                "live snapshot Raw V2 context names an unknown endpoint"
            )
        calls = replayed.provider_calls
        if (
            replayed != context
            or replayed.provider_authority_sha256 != self._capture_provider_authority_sha256
            or len(calls) != 1
            or calls[0].request_ordinal != 0
            or calls[0].source_family != "live"
            or calls[0].endpoint_id != provider_endpoint_id
        ):
            raise ParserInputCaptureIntegrityError(
                "live snapshot Raw V2 context crosses its provider call"
            )
        return context

    def _capture_contract_for_call(
        self,
        endpoint_name: str,
        params: dict[str, object],
        raw_context: RawRequestCaptureContextV2 | None,
    ) -> NbaApiCaptureContract | None:
        if self._recurring_receipts is not None:
            if raw_context is None:
                raise ParserInputCaptureIntegrityError(
                    "recurring live capture lacks its exact Raw V2 context"
                )
            contract = self._recurring_receipts.contract_for(
                endpoint_name,
                dict(params),
                raw_context=raw_context,
            )
        elif self._capture_contract_factory is None:
            return None
        else:
            try:
                contract = self._capture_contract_factory(endpoint_name, dict(params))
            except Exception as exc:
                raise ParserInputCaptureIntegrityError(
                    "live snapshot private capture factory failed"
                ) from exc
        if not isinstance(contract, NbaApiCaptureContract):
            raise ParserInputCaptureIntegrityError(
                "live snapshot capture factory did not return an NBA API capture contract"
            )
        if contract.context.retry_ordinal != 0 or contract.context.request_ordinal != 0:
            raise ParserInputCaptureIntegrityError(
                "live snapshot logical capture context must begin at ordinal zero"
            )
        if contract.provider_authority_sha256 != self._capture_provider_authority_sha256:
            raise ParserInputCaptureIntegrityError(
                "live snapshot capture contract differs from pinned provider authority"
            )
        return contract

    @staticmethod
    def _verified_success_capture_snapshot(
        extractor: BaseExtractor,
        contract: NbaApiCaptureContract,
    ) -> NbaApiReceiptSnapshot:
        contract_snapshot = contract.receipt_snapshot()
        successful_retries = [
            entry.context.retry_ordinal for entry in contract_snapshot.entries if entry.successful
        ]
        if not successful_retries:
            raise ParserInputCaptureIntegrityError(
                "successful live snapshot call has no successful response receipt"
            )
        return ExtractorRunner._verified_success_capture_snapshot(
            extractor,
            contract,
            retry_ordinal=max(successful_retries),
        )

    def _run_provider_call[T](
        self,
        *,
        extractor: BaseExtractor,
        params: dict[str, object],
        result_route_ids: tuple[str, ...],
        snapshot_at: datetime,
        invoke: Callable[[], T],
    ) -> tuple[T, _LiveProviderCallEvidence]:
        endpoint_name = extractor.endpoint_name
        if self._call_admission is not None:
            self._call_admission(endpoint_name, dict(params), result_route_ids)
        raw_context = self._raw_context_for_call(endpoint_name, params)
        contract = self._capture_contract_for_call(endpoint_name, params, raw_context)
        if contract is None or raw_context is None:
            raise ParserInputCaptureIntegrityError(
                "live source extraction lacks exact private and Raw V2 capture authority"
            )
        if (
            contract.endpoint_contract_sha256
            != raw_context.provider_calls[0].endpoint_contract_sha256
        ):
            raise ParserInputCaptureIntegrityError(
                "live private capture differs from its Raw V2 endpoint contract"
            )

        extractor.begin_extraction_attempt()
        extractor.set_logical_request_params(params)
        extractor.set_raw_request_capture_context(raw_context)
        extractor.set_capture_contract(contract)
        raw_capture_contract = getattr(extractor, "_capture_contract", None)
        if type(raw_capture_contract) is not RawRequestCaptureContract:
            raise ParserInputCaptureIntegrityError(
                "live extractor did not retain its exact wrapped Raw V2 capture contract"
            )
        try:
            result = invoke()
        except BaseException as exc:
            integrity_error = ExtractorRunner._seal_terminal_failure_capture(contract)
            if integrity_error is not None:
                raise integrity_error from exc
            raise

        snapshot = self._verified_success_capture_snapshot(extractor, contract)
        landings = ExtractorRunner._verified_live_lossless_landings(
            ExtractorRunner._live_lossless_landings_for_attempt(extractor),
            snapshot,
            retry_ordinal=max(
                entry.context.retry_ordinal for entry in snapshot.entries if entry.successful
            ),
            expected_snapshot_at=snapshot_at,
        )
        ExtractorRunner._verify_live_lossless_request_scope(
            endpoint_name=endpoint_name,
            landings=landings,
            static_route_ids=result_route_ids,
            provider_authority_sha256=contract.provider_authority_sha256,
            logical_params=params,
        )
        merged_landing = ExtractorRunner._merge_live_lossless_landings(
            endpoint_name,
            landings,
        )
        live_projection = (
            _LiveLosslessProjection(frame=merged_landing[0], route_id=merged_landing[1])
            if merged_landing is not None
            else None
        )
        if self._call_admission is None:
            live_projection = None
        conditional_route_ids = (live_projection.route_id,) if live_projection is not None else ()
        if conditional_route_ids:
            if self._conditional_route_admission is None:
                raise ParserInputCaptureIntegrityError(
                    "admitted live snapshot has no conditional live-lossless authority"
                )
            self._conditional_route_admission(
                endpoint_name,
                dict(params),
                result_route_ids,
                conditional_route_ids,
            )
        ordered_route_ids = (*result_route_ids, *conditional_route_ids)
        binding = ExtractorRunner._finalize_logical_call_receipt(
            raw_capture_contract,
            snapshot,
            endpoint_name=endpoint_name,
            params=params,
            result_route_ids=ordered_route_ids,
        )
        expected_routes = tuple(sorted({*result_route_ids, *conditional_route_ids}))
        if (
            binding.logical_parameters_sha256 != canonical_parameters_sha256(params)
            or binding.provider_authority_sha256 != self._capture_provider_authority_sha256
            or binding.result_route_ids != expected_routes
        ):
            raise ParserInputCaptureIntegrityError(
                "live snapshot logical-call receipt binding does not match its provider call"
            )
        raw_snapshot = ExtractorRunner._verified_raw_request_capture_snapshot(
            extractor,
            raw_context,
            retry_ordinal=max(
                entry.context.retry_ordinal for entry in snapshot.entries if entry.successful
            ),
        )
        if raw_snapshot.issues or len(raw_snapshot.pending_successes) != 1:
            raise ParserInputCaptureIntegrityError(
                "successful live call lacks one complete exact Raw V2 response"
            )
        authority_factory = self._live_plan_authority_binding_factory
        if authority_factory is None:
            raise ParserInputCaptureIntegrityError(
                "live source extraction lacks independently pinned sealed-plan authority"
            )
        try:
            authority_binding = authority_factory(
                endpoint_name,
                dict(params),
                ordered_route_ids,
                snapshot_at,
                raw_snapshot,
            )
        except Exception as exc:
            raise ParserInputCaptureIntegrityError(
                "live sealed-plan authority binding factory failed"
            ) from exc
        if type(authority_binding) is not tuple or len(authority_binding) != 2:
            raise ParserInputCaptureIntegrityError(
                "live sealed-plan authority binding has a foreign shape"
            )
        authority, expected_authority_sha256 = authority_binding
        if (
            type(authority) is not LiveSnapshotPlanAuthorityV2
            or type(expected_authority_sha256) is not str
        ):
            raise ParserInputCaptureIntegrityError(
                "live sealed-plan authority binding has a foreign child"
            )
        try:
            replayed_authority = LiveSnapshotPlanAuthorityV2(
                **{item.name: getattr(authority, item.name) for item in fields(authority)}
            )
        except Exception as exc:
            raise ParserInputCaptureIntegrityError(
                "live sealed-plan authority failed strict replay"
            ) from exc
        pending = raw_snapshot.pending_successes[0]
        if (
            replayed_authority != authority
            or authority.authority_sha256 != expected_authority_sha256
            or authority.observation_sha256 != pending.attempt.observation_sha256
            or authority.route_ids != ordered_route_ids
            or authority.live_snapshot_at != snapshot_at
            or authority.live_snapshot_at.tzinfo is not UTC
            or authority.live_snapshot_at.fold != 0
        ):
            raise ParserInputCaptureIntegrityError(
                "live sealed-plan authority crosses its exact response or routes"
            )
        return result, _LiveProviderCallEvidence(
            binding=binding,
            receipt_snapshot=snapshot,
            raw_context=raw_context,
            raw_snapshot=raw_snapshot,
            live_plan_authority=authority,
            expected_live_plan_authority_sha256=expected_authority_sha256,
            live_lossless=live_projection,
        )

    def _source_call_result(
        self,
        *,
        endpoint_name: str,
        call_ordinal: int,
        params: dict[str, object],
        frames: dict[str, pl.DataFrame],
        evidence: _LiveProviderCallEvidence,
    ) -> LiveSourceCallResult:
        route_ids = _LIVE_ROUTE_IDS_BY_ENDPOINT.get(endpoint_name)
        if route_ids is None or len(route_ids) != len(frames):
            raise ParserInputCaptureIntegrityError(
                "live source call has incomplete route authority"
            )
        validated_frames = self._validate_live_contracts(frames)
        route_mapping_items = list(zip(tuple(validated_frames), route_ids, strict=True))
        if evidence.live_lossless is not None:
            validated_frames[LIVE_LOSSLESS_STAGING_KEY] = self._validate_frame(
                LIVE_LOSSLESS_STAGING_KEY,
                evidence.live_lossless.frame,
            )
            route_mapping_items.append((LIVE_LOSSLESS_STAGING_KEY, evidence.live_lossless.route_id))
        staging_keys = tuple(validated_frames)
        route_mapping = tuple(sorted(route_mapping_items))
        expected_routes = tuple(sorted(route_id for _staging_key, route_id in route_mapping))
        if evidence.binding.result_route_ids != expected_routes:
            raise ParserInputCaptureIntegrityError(
                "live source call binding differs from its exact staging routes"
            )
        return LiveSourceCallResult(
            endpoint_name=endpoint_name,
            parameters_json=json.dumps(
                params,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ),
            _frame_items=tuple(
                (staging_key, frame.clone()) for staging_key, frame in validated_frames.items()
            ),
            expected_staging_keys=staging_keys,
            result_route_ids_by_staging_key=route_mapping,
            receipt_binding=evidence.binding,
            call_ordinal=call_ordinal,
            capture_receipt_snapshot=evidence.receipt_snapshot,
            raw_request_capture_context=evidence.raw_context,
            raw_request_capture_snapshot=evidence.raw_snapshot,
            live_plan_authority=evidence.live_plan_authority,
            expected_live_plan_authority_sha256=(evidence.expected_live_plan_authority_sha256),
        )

    @staticmethod
    def _coerce_snapshot_at(value: datetime | date | None) -> datetime:
        if value is None:
            return datetime.now(UTC)
        if isinstance(value, datetime):
            aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
            return aware.astimezone(UTC).replace(fold=0)
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)

    @staticmethod
    def _concat_frames(frames: list[pl.DataFrame]) -> pl.DataFrame:
        non_empty = [frame for frame in frames if not frame.is_empty()]
        if not non_empty:
            return frames[0] if frames else pl.DataFrame()
        if len(non_empty) == 1:
            return non_empty[0]
        return pl.concat(non_empty, how="diagonal_relaxed")

    @staticmethod
    def _ordered_game_ids(frame: pl.DataFrame) -> list[str]:
        if frame.is_empty or "game_id" not in frame.columns:
            return []
        seen: set[str] = set()
        ordered: list[str] = []
        for raw_game_id in frame.get_column("game_id").drop_nulls().to_list():
            game_id = str(raw_game_id)
            if game_id in seen:
                continue
            seen.add(game_id)
            ordered.append(game_id)
        return ordered

    @classmethod
    def _active_game_ids(cls, score_board: pl.DataFrame) -> list[str]:
        if score_board.is_empty:
            return []
        active_rows = score_board
        if "game_status" in score_board.columns:
            active_rows = score_board.filter(pl.col("game_status") == 2)
        return cls._ordered_game_ids(active_rows)

    @staticmethod
    def _filter_game_ids(frame: pl.DataFrame, game_ids: list[str]) -> pl.DataFrame:
        if frame.is_empty or not game_ids or "game_id" not in frame.columns:
            return frame
        return frame.filter(pl.col("game_id").cast(pl.Utf8).is_in(game_ids))

    @staticmethod
    def _schema_columns(table_name: str) -> list[str]:
        schema_cls = get_input_schema(table_name)
        if schema_cls is None:
            raise ValueError(f"No schema registered for {table_name}")
        return list(schema_cls.to_schema().columns)

    @classmethod
    def _conform_columns(cls, table_name: str, frame: pl.DataFrame) -> pl.DataFrame:
        columns = cls._schema_columns(table_name)
        missing = [column for column in columns if column not in frame.columns]
        if not missing:
            return frame
        return frame.with_columns([pl.lit(None).alias(column) for column in missing])

    @classmethod
    def _validate_frame(cls, table_name: str, frame: pl.DataFrame) -> pl.DataFrame:
        schema_cls = get_input_schema(table_name)
        if schema_cls is None:
            raise ValueError(f"No schema registered for {table_name}")
        return schema_cls.validate(cls._conform_columns(table_name, frame))

    def _extract_live_frames(
        self,
        *,
        snapshot_at: datetime,
        game_ids: list[str] | None,
    ) -> LiveSnapshotExtraction:
        source_calls: list[LiveSourceCallResult] = []

        score_board_extractor = LiveScoreBoardExtractor()
        score_board, score_board_evidence = self._run_provider_call(
            extractor=score_board_extractor,
            params={},
            result_route_ids=_LIVE_ROUTE_IDS_BY_ENDPOINT["live_score_board"],
            snapshot_at=snapshot_at,
            invoke=lambda: _sync_extract(score_board_extractor, snapshot_at=snapshot_at),
        )
        effective_game_ids = list(game_ids or self._active_game_ids(score_board))
        if not effective_game_ids and not game_ids:
            source_calls.append(
                self._source_call_result(
                    endpoint_name=score_board_extractor.endpoint_name,
                    call_ordinal=len(source_calls),
                    params={},
                    frames={"stg_live_score_board": score_board},
                    evidence=score_board_evidence,
                )
            )
            return LiveSnapshotExtraction(
                snapshot_at=snapshot_at,
                game_ids=(),
                source_calls=tuple(source_calls),
            )

        score_board = self._filter_game_ids(score_board, effective_game_ids)
        source_calls.append(
            self._source_call_result(
                endpoint_name=score_board_extractor.endpoint_name,
                call_ordinal=len(source_calls),
                params={},
                frames={"stg_live_score_board": score_board},
                evidence=score_board_evidence,
            )
        )
        odds_extractor = LiveOddsExtractor()
        odds, odds_evidence = self._run_provider_call(
            extractor=odds_extractor,
            params={},
            result_route_ids=_LIVE_ROUTE_IDS_BY_ENDPOINT["live_odds"],
            snapshot_at=snapshot_at,
            invoke=lambda: _sync_extract(odds_extractor, snapshot_at=snapshot_at),
        )
        odds = self._filter_game_ids(odds, effective_game_ids)
        source_calls.append(
            self._source_call_result(
                endpoint_name=odds_extractor.endpoint_name,
                call_ordinal=len(source_calls),
                params={},
                frames={"stg_live_odds": odds},
                evidence=odds_evidence,
            )
        )

        for game_id in effective_game_ids:
            call_params: dict[str, object] = {"game_id": game_id}
            play_by_play_extractor = LivePlayByPlayExtractor()
            play_by_play, play_by_play_evidence = self._run_provider_call(
                extractor=play_by_play_extractor,
                params=call_params,
                result_route_ids=_LIVE_ROUTE_IDS_BY_ENDPOINT["live_play_by_play"],
                snapshot_at=snapshot_at,
                invoke=lambda extractor=play_by_play_extractor, active_game_id=game_id: (
                    _sync_extract(
                        extractor,
                        game_id=active_game_id,
                        snapshot_at=snapshot_at,
                    )
                ),
            )
            source_calls.append(
                self._source_call_result(
                    endpoint_name=play_by_play_extractor.endpoint_name,
                    call_ordinal=len(source_calls),
                    params=call_params,
                    frames={"stg_live_play_by_play": play_by_play},
                    evidence=play_by_play_evidence,
                )
            )

            box_score_extractor = LiveBoxScoreExtractor()
            live_box_score_packets, box_score_evidence = self._run_provider_call(
                extractor=box_score_extractor,
                params=call_params,
                result_route_ids=_LIVE_ROUTE_IDS_BY_ENDPOINT["live_box_score"],
                snapshot_at=snapshot_at,
                invoke=lambda extractor=box_score_extractor, active_game_id=game_id: (
                    _sync_extract_all(
                        extractor,
                        game_id=active_game_id,
                        snapshot_at=snapshot_at,
                    )
                ),
            )
            source_calls.append(
                self._source_call_result(
                    endpoint_name=box_score_extractor.endpoint_name,
                    call_ordinal=len(source_calls),
                    params=call_params,
                    frames=dict(
                        zip(
                            _LIVE_BOX_SCORE_STAGING_KEYS,
                            live_box_score_packets,
                            strict=True,
                        )
                    ),
                    evidence=box_score_evidence,
                )
            )

        return LiveSnapshotExtraction(
            snapshot_at=snapshot_at,
            game_ids=tuple(effective_game_ids),
            source_calls=tuple(source_calls),
        )

    def extract_source_calls(
        self,
        *,
        game_ids: list[str] | None = None,
        snapshot_at: datetime | date | None = None,
    ) -> LiveSnapshotExtraction:
        """Extract exact per-provider-call evidence without claiming persistence."""

        if (self._capture_contract_factory is None and self._recurring_receipts is None) or any(
            value is None
            for value in (
                self._call_admission,
                self._conditional_route_admission,
                self._raw_request_capture_context_factory,
                self._live_plan_authority_binding_factory,
            )
        ):
            if self._recurring_receipts is not None:
                self._recurring_receipts.close()
            raise ParserInputCaptureIntegrityError(
                "live source extraction requires exact Raw V2 capture, route admission, "
                "and independently pinned sealed-plan authority"
            )
        try:
            extraction = self._extract_live_frames(
                snapshot_at=self._coerce_snapshot_at(snapshot_at),
                game_ids=game_ids,
            )
            lease = self._recurring_receipts
            if lease is not None:
                extraction = replace(extraction, _evidence_lease=lease)
            extraction.replay_exact_source_evidence()
            if lease is not None:
                self._recurring_receipts = None
            return extraction
        except BaseException:
            if self._recurring_receipts is not None:
                self._recurring_receipts.close()
            raise

    @classmethod
    def _merge_source_frames(
        cls,
        source_calls: tuple[LiveSourceCallResult, ...],
    ) -> dict[str, pl.DataFrame]:
        frames_by_key: dict[str, list[pl.DataFrame]] = {}
        for source_call in source_calls:
            for staging_key, frame in source_call.frames.items():
                frames_by_key.setdefault(staging_key, []).append(frame)
        return {
            staging_key: cls._concat_frames(frames) for staging_key, frames in frames_by_key.items()
        }

    def _validate_live_contracts(
        self,
        raw_frames: dict[str, pl.DataFrame],
    ) -> dict[str, pl.DataFrame]:
        validated: dict[str, pl.DataFrame] = {}
        for staging_key, frame in raw_frames.items():
            raw_table_name = _LIVE_RAW_SCHEMA_BY_STAGING_KEY[staging_key]
            raw_validated = self._validate_frame(raw_table_name, frame)
            validated[staging_key] = self._validate_frame(staging_key, raw_validated)
        return validated

    def run(
        self,
        *,
        game_ids: list[str] | None = None,
        snapshot_at: datetime | date | None = None,
        load_mode: Literal["append"] = "append",
    ) -> LiveSnapshotResult:
        if load_mode != "append":
            raise ValueError("Live snapshot warehousing only supports append mode")
        del game_ids, snapshot_at
        raise ParserInputCaptureIntegrityError(
            "standalone live snapshot cannot claim success before exact W2 admission"
        )
