"""Exact provider, Bronze, and semantic runtime for successor planning.

The runtime is deliberately narrower than the ordinary orchestrator: one
sealed dispatch becomes exactly one provider call, one receipt-bound staging
replacement, and the partition-local semantic members admitted by the frozen
planning driver.  It never derives work from global player, team, game, or
season inventories.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import secrets
import signal
import stat
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

import duckdb
import polars as pl

from nbadb.contracts.logical_provider_parameter_binding import (
    LogicalProviderParameterBindingV1,
    verify_logical_provider_parameter_binding,
)
from nbadb.contracts.raw_request_finalization import (
    finalize_raw_request_capture,
    materialize_raw_request_incomplete_success_snapshot,
)
from nbadb.contracts.raw_request_reconstruction import LiveSnapshotPlanAuthorityV2
from nbadb.contracts.staging_route_contract import (
    ConditionalLiveStagingRouteAdmission,
    ConditionalStagingRouteAdmission,
    KnownConditionalStagingRouteAdmission,
    admit_known_conditional_staging_route,
    staging_route_contract_bundle,
)
from nbadb.core.config import NbaDbSettings
from nbadb.core.errors import ResponseContractError
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.extract.bronze import (
    BronzeLimits,
    LogicalCallReceiptBinding,
    RecordedParserInput,
    canonical_parameters_sha256,
)
from nbadb.extract.live_lossless import (
    LIVE_LOSSLESS_STAGING_KEY,
    validate_live_lossless_frame,
)
from nbadb.extract.nba_api_adapter import validate_lossless_fallback_frame
from nbadb.extract.raw_request_capture import (
    PendingRawRequestSuccessV2,
    RawRequestCaptureContextV2,
    RawRequestCaptureSnapshotV2,
)
from nbadb.extract.registry import (
    EndpointRegistry,
    EndpointRegistryAuthority,
    EndpointRegistryAuthorityError,
)
from nbadb.orchestrate import successor_crash_injection as crash_injection
from nbadb.orchestrate.capture_session import (
    CaptureRunScope,
    CaptureSessionState,
    PrivateCaptureSession,
)
from nbadb.orchestrate.extractor_runner import ExtractorRunner
from nbadb.orchestrate.journal import PipelineJournal
from nbadb.orchestrate.public_value_authority_store import PublicValueAuthorityStore
from nbadb.orchestrate.raw_request_store import (
    RawRequestAuthorityPersistenceReceiptV2,
    RawRequestAuthorityStore,
)
from nbadb.orchestrate.staging_batches import (
    StagingBatchStore,
    StagingChunkMetadata,
    StagingFrameBatch,
    digest_jsonable,
)
from nbadb.orchestrate.staging_map import LOSSLESS_FALLBACK_STAGING_KEY, STAGING_MAP
from nbadb.orchestrate.successor_planner import (
    ConcreteSuccessorPlanningExecutor,
    PlanningCallExecution,
    PlanningWaveSeal,
)
from nbadb.orchestrate.successor_planning_capture_resolver import (
    RetainedBronzePlanningResolver,
)
from nbadb.orchestrate.successor_planning_driver import (
    PlanningExactCallRuntimeRequest,
    PlanningMemberEnvelope,
    PlanningWaveSealRuntimeRequest,
    RequestDrivenSuccessorPlanningDriver,
)
from nbadb.orchestrate.successor_planning_generation_contract import (
    PlanningDataMember,
    SuccessorPlanningWave,
)
from nbadb.orchestrate.successor_planning_program_compiler import (
    SUCCESSOR_PLANNING_SEMANTIC_PARTITIONS_TABLE,
    SUCCESSOR_PLANNING_SEMANTIC_VALUES_TABLE,
    install_successor_planning_semantic_schema,
    successor_planning_database_schema_sha256,
    successor_planning_semantic_write_transaction,
    write_successor_planning_semantic_partition,
)
from nbadb.orchestrate.successor_planning_semantic_contract import (
    PlanningSemanticKind,
)
from nbadb.orchestrate.successor_planning_store import (
    PlanningArtifactSource,
    PlanningDatabaseSource,
    PlanningMemberSource,
    PlanningStoreBudget,
    SuccessorPlanningStore,
)
from nbadb.orchestrate.successor_planning_wave_receipt import (
    PlanningWaveCallBinding,
    PlanningWaveCompletionReceipt,
    PlanningWaveMemberBinding,
)
from nbadb.orchestrate.w2_operation_coordinator import (
    W2SourceCallAdmissionV1,
    coordinate_w2_source_call,
)
from nbadb.orchestrate.w2_operation_store import W2OperationStore
from nbadb.orchestrate.w2_source_call_preparation import W2SourceCallPreparationRuntime
from nbadb.schemas.registry import get_input_schema

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

    from nbadb.orchestrate.staging_map import StagingEntry
    from nbadb.orchestrate.successor_planning_semantic_contract import (
        PlanningSemanticDescriptor,
    )
    from nbadb.orchestrate.successor_update_contract import RequestedRouteScope

    type PlanningRawRequestContextFactoryV1 = Callable[
        [CaptureRunScope, str, dict[str, object]],
        RawRequestCaptureContextV2,
    ]
    type PlanningW2PreparationRuntimeFactoryV1 = Callable[
        [CaptureRunScope],
        W2SourceCallPreparationRuntime,
    ]
    type PlanningRawAuthorityStoreFactoryV1 = Callable[
        [duckdb.DuckDBPyConnection],
        RawRequestAuthorityStore,
    ]
    type PlanningPublicValueStoreFactoryV1 = Callable[
        [duckdb.DuckDBPyConnection],
        PublicValueAuthorityStore,
    ]
    type PlanningW2OperationStoreFactoryV1 = Callable[
        [duckdb.DuckDBPyConnection],
        W2OperationStore,
    ]
    type PlanningLivePlanBindingFactoryV1 = Callable[
        [
            CaptureRunScope,
            PlanningExactCallRuntimeRequest,
            RawRequestCaptureSnapshotV2,
            LogicalCallReceiptBinding,
        ],
        tuple[tuple[LiveSnapshotPlanAuthorityV2, str], ...],
    ]
    type PlanningLogicalProviderParameterBindingFactoryV1 = Callable[
        [CaptureRunScope, PlanningExactCallRuntimeRequest, RawRequestCaptureContextV2],
        tuple[LogicalProviderParameterBindingV1, str],
    ]

__all__ = [
    "ExactPlanningRuntimeConfig",
    "ExactPlanningRuntimeError",
    "ExtractorPlanningExactCallRuntime",
    "PlanningW2AuthorityResourcesV1",
    "build_successor_planning_executor",
    "require_live_plan_authority_available",
    "unavailable_live_plan_binding_factory",
]

_ASCII_GAME_ID_LENGTH = 10
_NBA_LEAGUE_ID = "00"
_MAX_SIGNED_63: Final = (1 << 63) - 1
_PLANNING_FILE_LIMIT_LOCK: Final = threading.Lock()


class ExactPlanningRuntimeError(RuntimeError):
    """Raised when exact planning runtime authority is incomplete or drifts."""


@dataclass(frozen=True, slots=True)
class PlanningW2AuthorityResourcesV1:
    """Explicit effectful authorities required to close one planning call.

    The planning runtime deliberately receives these resources instead of
    deriving store roots, public request identities, or live-plan authority
    from its own provider result.  Construction therefore fails before any
    planning effect when the production composition has not wired W2.
    """

    raw_request_context_factory: PlanningRawRequestContextFactoryV1
    w2_preparation_runtime_factory: PlanningW2PreparationRuntimeFactoryV1
    raw_authority_store_factory: PlanningRawAuthorityStoreFactoryV1
    public_value_store_factory: PlanningPublicValueStoreFactoryV1
    w2_operation_store_factory: PlanningW2OperationStoreFactoryV1
    live_plan_binding_factory: PlanningLivePlanBindingFactoryV1
    logical_provider_parameter_binding_factory: PlanningLogicalProviderParameterBindingFactoryV1

    def __post_init__(self) -> None:
        for field_name in (
            "raw_request_context_factory",
            "w2_preparation_runtime_factory",
            "raw_authority_store_factory",
            "public_value_store_factory",
            "w2_operation_store_factory",
            "live_plan_binding_factory",
            "logical_provider_parameter_binding_factory",
        ):
            if not callable(getattr(self, field_name)):
                raise ExactPlanningRuntimeError(f"{field_name} must be callable")


_LIVE_PLANNING_ENDPOINTS: Final = frozenset({"live_score_board"})


def unavailable_live_plan_binding_factory(
    *_args: object,
    **_kwargs: object,
) -> tuple[tuple[LiveSnapshotPlanAuthorityV2, str], ...]:
    """Typed proof that no live request-closure authority exists today.

    The live scoreboard route cannot currently be closed without collectors
    that remain intentionally unimplemented, so the production composition
    binds this sentinel instead of fabricating live authority.  The planning
    runtime rejects any live dispatch that carries it before any provider,
    store, intent, or upload effect can run.
    """

    raise ExactPlanningRuntimeError(
        "live request-closure authority is intentionally unavailable; "
        "live_score_board planning requires authority that is not implemented"
    )


def require_live_plan_authority_available(
    endpoint_name: str,
    resources: PlanningW2AuthorityResourcesV1,
) -> None:
    """Fail closed before effects when a live dispatch lacks real authority."""

    if (
        endpoint_name in _LIVE_PLANNING_ENDPOINTS
        and resources.live_plan_binding_factory is unavailable_live_plan_binding_factory
    ):
        raise ExactPlanningRuntimeError(
            "live_score_board planning lacks live request-closure authority; "
            "failing before provider, store, intent, or upload effects"
        )


@contextmanager
def _planning_file_size_limit(max_bytes: int) -> Iterator[None]:
    """Install one process-wide POSIX hard write boundary for a planning call."""

    checked_max = _require_positive_signed63(
        max_bytes,
        field_name="planning_driver_database_max_bytes",
    )
    if os.name != "posix" or threading.current_thread() is not threading.main_thread():
        raise ExactPlanningRuntimeError(
            "planning database hard-cap enforcement requires the POSIX main thread"
        )
    try:
        resource = importlib.import_module("resource")
        rlimit_fsize = resource.RLIMIT_FSIZE
        infinity = resource.RLIM_INFINITY
        sigxfsz = signal.SIGXFSZ
    except (AttributeError, ImportError) as exc:
        raise ExactPlanningRuntimeError(
            "planning database hard-cap enforcement is unavailable"
        ) from exc
    if not _PLANNING_FILE_LIMIT_LOCK.acquire(blocking=False):
        raise ExactPlanningRuntimeError("another process-wide planning database hard cap is active")
    previous_limits: tuple[int, int] | None = None
    previous_handler: Any = None
    handler_installed = False
    limit_installed = False
    restoration_error: Exception | None = None
    try:
        previous_limits = resource.getrlimit(rlimit_fsize)
        previous_soft, previous_hard = previous_limits
        effective = checked_max
        if previous_soft != infinity:
            effective = min(effective, previous_soft)
        if previous_hard != infinity:
            effective = min(effective, previous_hard)
        if type(effective) is not int or effective < 1:
            raise ExactPlanningRuntimeError(
                "process file-size authority cannot admit a positive planning cap"
            )
        previous_handler = signal.getsignal(sigxfsz)
        signal.signal(sigxfsz, signal.SIG_IGN)
        handler_installed = True
        resource.setrlimit(rlimit_fsize, (effective, previous_hard))
        limit_installed = True
        yield
    finally:
        if limit_installed and previous_limits is not None:
            try:
                resource.setrlimit(rlimit_fsize, previous_limits)
            except Exception as exc:  # pragma: no cover - catastrophic OS failure
                restoration_error = exc
        if handler_installed:
            try:
                signal.signal(sigxfsz, previous_handler)
            except Exception as exc:  # pragma: no cover - catastrophic OS failure
                restoration_error = restoration_error or exc
        _PLANNING_FILE_LIMIT_LOCK.release()
        if restoration_error is not None:
            raise ExactPlanningRuntimeError(
                "planning database hard-cap authority could not be restored"
            ) from restoration_error


def _bounded_planning_file_size(method: Any) -> Any:
    @wraps(method)
    async def bounded(self: ExtractorPlanningExactCallRuntime, *args: Any, **kwargs: Any) -> Any:
        with _planning_file_size_limit(
            self.config.planning_driver_database_max_bytes,
        ):
            return await method(self, *args, **kwargs)

    return bounded


def _require_aware_utc(value: str, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ExactPlanningRuntimeError(f"{field_name} must be canonical UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ExactPlanningRuntimeError(f"{field_name} must be canonical UTC") from exc
    canonical = parsed.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    if canonical != value:
        raise ExactPlanningRuntimeError(f"{field_name} must be canonical UTC")
    return parsed.astimezone(UTC)


def _require_existing_directory(
    path: Path,
    *,
    field_name: str,
    owner_only: bool,
) -> tuple[Path, os.stat_result]:
    if not isinstance(path, Path) or not path.is_absolute():
        raise ExactPlanningRuntimeError(f"{field_name} must be an absolute Path")
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        try:
            observed = os.lstat(current)
        except OSError as exc:
            raise ExactPlanningRuntimeError(f"{field_name} must exist") from exc
        if stat.S_ISLNK(observed.st_mode):
            raise ExactPlanningRuntimeError(f"{field_name} cannot traverse a symlink")
    try:
        observed = os.stat(absolute, follow_symlinks=False)
    except OSError as exc:
        raise ExactPlanningRuntimeError(f"{field_name} must exist") from exc
    if not stat.S_ISDIR(observed.st_mode):
        raise ExactPlanningRuntimeError(f"{field_name} must be a directory")
    if (
        owner_only
        and os.name == "posix"
        and (observed.st_uid != os.geteuid() or stat.S_IMODE(observed.st_mode) != 0o700)
    ):
        raise ExactPlanningRuntimeError(f"{field_name} must be owner-only mode 0700")
    return absolute, observed


def _directory_identity(observed: os.stat_result) -> tuple[int, int]:
    return observed.st_dev, observed.st_ino


def _has_ancestor_identity(path: Path, identity: tuple[int, int]) -> bool:
    current = path
    while True:
        observed = os.stat(current, follow_symlinks=False)
        if _directory_identity(observed) == identity:
            return True
        if current == current.parent:
            return False
        current = current.parent


def _paths_overlap(
    left: Path,
    right: Path,
    *,
    left_stat: os.stat_result,
    right_stat: os.stat_result,
) -> bool:
    """Reject lexical, case-folded, same-inode, and ancestor aliases."""

    left_parts = tuple(part.casefold() for part in left.parts)
    right_parts = tuple(part.casefold() for part in right.parts)
    left_identity = _directory_identity(left_stat)
    right_identity = _directory_identity(right_stat)
    try:
        return (
            left == right
            or left.is_relative_to(right)
            or right.is_relative_to(left)
            or left_parts[: len(right_parts)] == right_parts
            or right_parts[: len(left_parts)] == left_parts
            or left_identity == right_identity
            or _has_ancestor_identity(left, right_identity)
            or _has_ancestor_identity(right, left_identity)
        )
    except OSError as exc:
        raise ExactPlanningRuntimeError("planning root overlap cannot be verified") from exc


@dataclass(frozen=True, slots=True)
class ExactPlanningRuntimeConfig:
    """Construction authority for one exact planning runtime."""

    settings: NbaDbSettings
    registry: EndpointRegistry
    registry_authority: EndpointRegistryAuthority
    capture_base: Path
    planning_store_root: Path
    public_roots: tuple[Path, ...]
    capture_limits: BronzeLimits
    estimated_checkpoint_bytes: int
    planning_driver_database_max_bytes: int
    monotonic_deadline_seconds: float
    minimum_deadline_headroom_seconds: float
    before_planning_effects_authority: Callable[[], None]
    before_provider_authority: Callable[[], None]
    w2_authority_resources: PlanningW2AuthorityResourcesV1
    monotonic_clock: Callable[[], float] = time.monotonic
    _capture_base_identity: tuple[int, int] = field(init=False, repr=False, compare=False)
    _planning_store_identity: tuple[int, int] = field(init=False, repr=False, compare=False)
    _public_root_identities: tuple[tuple[int, int], ...] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.settings, NbaDbSettings):
            raise ExactPlanningRuntimeError("settings must be NbaDbSettings")
        if not isinstance(self.registry, EndpointRegistry):
            raise ExactPlanningRuntimeError("registry must be EndpointRegistry")
        if not isinstance(self.registry_authority, EndpointRegistryAuthority):
            raise ExactPlanningRuntimeError("registry_authority must be EndpointRegistryAuthority")
        self.require_current_registry()
        if not isinstance(self.capture_limits, BronzeLimits):
            raise ExactPlanningRuntimeError("capture_limits must be BronzeLimits")
        if type(self.w2_authority_resources) is not PlanningW2AuthorityResourcesV1:
            raise ExactPlanningRuntimeError(
                "w2_authority_resources must be the exact planning W2 authority DTO"
            )
        if type(self.public_roots) is not tuple or not self.public_roots:
            raise ExactPlanningRuntimeError("public_roots must be a nonempty tuple")
        if type(self.estimated_checkpoint_bytes) is not int or self.estimated_checkpoint_bytes <= 0:
            raise ExactPlanningRuntimeError("estimated_checkpoint_bytes must be positive")
        _require_positive_signed63(
            self.planning_driver_database_max_bytes,
            field_name="planning_driver_database_max_bytes",
        )
        for value in (
            self.monotonic_deadline_seconds,
            self.minimum_deadline_headroom_seconds,
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ExactPlanningRuntimeError("monotonic admission authority is invalid")
        if (
            self.capture_limits.minimum_deadline_headroom_seconds
            != self.minimum_deadline_headroom_seconds
        ):
            raise ExactPlanningRuntimeError(
                "planning and Bronze deadline headroom authorities differ"
            )
        if not callable(self.monotonic_clock):
            raise ExactPlanningRuntimeError("monotonic admission authority is invalid")
        for field_name in (
            "before_planning_effects_authority",
            "before_provider_authority",
        ):
            if not callable(getattr(self, field_name)):
                raise ExactPlanningRuntimeError(f"{field_name} must be callable")

        capture, capture_stat = _require_existing_directory(
            self.capture_base,
            field_name="capture_base",
            owner_only=True,
        )
        planning, planning_stat = _require_existing_directory(
            self.planning_store_root,
            field_name="planning_store_root",
            owner_only=True,
        )
        public_authorities = tuple(
            _require_existing_directory(
                root,
                field_name="public_root",
                owner_only=False,
            )
            for root in self.public_roots
        )
        public = tuple(path for path, _observed in public_authorities)
        public_stats = tuple(observed for _path, observed in public_authorities)
        roots = (capture, planning, *public)
        root_stats = (capture_stat, planning_stat, *public_stats)
        if any(
            _paths_overlap(
                left,
                right,
                left_stat=root_stats[index],
                right_stat=root_stats[right_index],
            )
            for index, left in enumerate(roots)
            for right_index, right in enumerate(roots[index + 1 :], start=index + 1)
        ):
            raise ExactPlanningRuntimeError(
                "capture, planning-store, and public roots must be disjoint"
            )
        object.__setattr__(self, "capture_base", capture)
        object.__setattr__(self, "planning_store_root", planning)
        object.__setattr__(self, "public_roots", public)
        object.__setattr__(self, "_capture_base_identity", _directory_identity(capture_stat))
        object.__setattr__(self, "_planning_store_identity", _directory_identity(planning_stat))
        object.__setattr__(
            self,
            "_public_root_identities",
            tuple(_directory_identity(observed) for observed in public_stats),
        )

    def require_current_registry(self, *, endpoint_name: str | None = None) -> None:
        """Fail closed unless the planning registry matches its frozen authority."""

        try:
            self.registry_authority.require_current(
                self.registry,
                required_endpoint_name=endpoint_name,
            )
        except EndpointRegistryAuthorityError as exc:
            raise ExactPlanningRuntimeError("planning endpoint registry authority differs") from exc

    def require_deadline_headroom(self, *, stage: str) -> float:
        """Sample and enforce the exact planning-call deadline authority."""

        try:
            raw_now = self.monotonic_clock()
        except Exception as exc:
            raise ExactPlanningRuntimeError(
                f"monotonic clock measurement failed at {stage}"
            ) from exc
        if (
            isinstance(raw_now, bool)
            or not isinstance(raw_now, int | float)
            or not math.isfinite(raw_now)
            or raw_now <= 0
        ):
            raise ExactPlanningRuntimeError(f"monotonic clock reading is invalid at {stage}")
        now = float(raw_now)
        if self.monotonic_deadline_seconds - now < self.minimum_deadline_headroom_seconds:
            raise ExactPlanningRuntimeError(
                f"planning deadline headroom is insufficient at {stage}"
            )
        return now

    def require_current_roots(self) -> None:
        """Fail closed if any configured filesystem authority was substituted."""

        authorities = (
            (
                self.capture_base,
                "capture_base",
                True,
                self._capture_base_identity,
            ),
            (
                self.planning_store_root,
                "planning_store_root",
                True,
                self._planning_store_identity,
            ),
            *tuple(
                (root, "public_root", False, identity)
                for root, identity in zip(
                    self.public_roots,
                    self._public_root_identities,
                    strict=True,
                )
            ),
        )
        observed_authorities: list[tuple[Path, os.stat_result]] = []
        for path, label, owner_only, expected_identity in authorities:
            current_path, observed = _require_existing_directory(
                path,
                field_name=label,
                owner_only=owner_only,
            )
            if _directory_identity(observed) != expected_identity:
                raise ExactPlanningRuntimeError(f"{label} changed identity")
            observed_authorities.append((current_path, observed))
        if any(
            _paths_overlap(
                left,
                right,
                left_stat=observed_authorities[index][1],
                right_stat=observed_authorities[right_index][1],
            )
            for index, (left, _left_stat) in enumerate(observed_authorities)
            for right_index, (right, _right_stat) in enumerate(
                observed_authorities[index + 1 :],
                start=index + 1,
            )
        ):
            raise ExactPlanningRuntimeError(
                "capture, planning-store, and public roots no longer remain disjoint"
            )

    def require_before_provider_authority(self) -> None:
        """Run the fresh aggregate admission immediately before a provider call."""

        try:
            result = self.before_provider_authority()
        except Exception as exc:
            raise ExactPlanningRuntimeError(
                "planning before-provider authority rejected the call"
            ) from exc
        if result is not None:
            raise ExactPlanningRuntimeError("planning before-provider authority must return None")

    def require_before_planning_effects_authority(self) -> None:
        """Admit aggregate capacity before output, capture, or provider effects."""

        try:
            result = self.before_planning_effects_authority()
        except Exception as exc:
            raise ExactPlanningRuntimeError(
                "planning before-effects authority rejected the call"
            ) from exc
        if result is not None:
            raise ExactPlanningRuntimeError("planning before-effects authority must return None")


def _require_positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ExactPlanningRuntimeError(f"{field_name} must be a positive integer")
    return value


def _require_positive_signed63(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 1 or value > _MAX_SIGNED_63:
        raise ExactPlanningRuntimeError(f"{field_name} must be a positive signed-63-bit integer")
    return value


def _require_year(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ExactPlanningRuntimeError(f"{field_name} must be a year")
    try:
        year = int(value)
    except (TypeError, ValueError) as exc:
        raise ExactPlanningRuntimeError(f"{field_name} must be a year") from exc
    if year < 1800 or year > 2200:
        raise ExactPlanningRuntimeError(f"{field_name} must be a plausible year")
    return year


def _season_start_year(season: object) -> int:
    if not isinstance(season, str) or len(season) != 7 or season[4] != "-":
        raise ExactPlanningRuntimeError("season must use exact YYYY-YY form")
    first = season[:4]
    suffix = season[5:]
    if not first.isascii() or not suffix.isascii() or not first.isdigit() or not suffix.isdigit():
        raise ExactPlanningRuntimeError("season must use exact ASCII YYYY-YY form")
    year = int(first)
    if int(suffix) != (year + 1) % 100:
        raise ExactPlanningRuntimeError("season suffix must be consecutive")
    return year


def _as_of_season_start(as_of_utc: str) -> int:
    instant = _require_aware_utc(as_of_utc, field_name="as_of_utc")
    return instant.year if (instant.month, instant.day) >= (10, 1) else instant.year - 1


def _require_game_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _ASCII_GAME_ID_LENGTH
        or not value.isascii()
        or not value.isdigit()
    ):
        raise ExactPlanningRuntimeError("semantic game_id must be exactly ten ASCII digits")
    return value


def _require_iso_date(value: object) -> str:
    if not isinstance(value, str) or len(value) != 10:
        raise ExactPlanningRuntimeError("semantic game_date must be exact YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ExactPlanningRuntimeError("semantic game_date must be exact YYYY-MM-DD") from exc
    if parsed.isoformat() != value or not value.isascii():
        raise ExactPlanningRuntimeError("semantic game_date must be exact ASCII YYYY-MM-DD")
    return value


def _rows(frame: pl.DataFrame) -> list[dict[str, Any]]:
    if not isinstance(frame, pl.DataFrame):
        raise ExactPlanningRuntimeError("planning normalizer requires a Polars DataFrame")
    return frame.to_dicts()


def _normalize_game_date_index(frame: pl.DataFrame) -> tuple[dict[str, object], ...]:
    by_game: dict[str, str] = {}
    for row in _rows(frame):
        game_id = _require_game_id(row.get("game_id"))
        game_date = _require_iso_date(row.get("game_date"))
        existing = by_game.get(game_id)
        if existing is not None and existing != game_date:
            raise ExactPlanningRuntimeError("one game_id maps to multiple game dates")
        by_game[game_id] = game_date
    return tuple(
        {"game_date": game_date, "game_id": game_id}
        for game_id, game_date in sorted(by_game.items(), key=lambda item: (item[1], item[0]))
    )


def _normalize_affiliations(
    frame: pl.DataFrame,
    *,
    season: str,
    season_type: str,
) -> tuple[dict[str, object], ...]:
    pairs: set[tuple[int, int]] = set()
    for row in _rows(frame):
        populated_season = row.get("season_year")
        populated_type = row.get("season_type")
        if populated_season is not None and populated_season != season:
            raise ExactPlanningRuntimeError("affiliation season differs from its dispatch")
        if populated_type is not None and populated_type != season_type:
            raise ExactPlanningRuntimeError("affiliation season type differs from its dispatch")
        player_id = _require_positive_int(row.get("player_id"), field_name="player_id")
        team_id = _require_positive_int(row.get("team_id"), field_name="team_id")
        pairs.add((player_id, team_id))
    return tuple({"player_id": player, "team_id": team} for player, team in sorted(pairs))


def _normalize_season_players(
    frame: pl.DataFrame,
    *,
    season: str,
    current_only: bool,
) -> tuple[dict[str, object], ...]:
    season_year = _season_start_year(season)
    player_ids: set[int] = set()
    for row in _rows(frame):
        player_id = _require_positive_int(row.get("person_id"), field_name="person_id")
        if current_only:
            roster_status = row.get("roster_status")
            if type(roster_status) is not int:
                raise ExactPlanningRuntimeError("roster_status must be an integer")
            if roster_status == 1:
                player_ids.add(player_id)
            continue
        first = _require_year(row.get("from_year"), field_name="from_year")
        last = _require_year(row.get("to_year"), field_name="to_year")
        if first > last:
            raise ExactPlanningRuntimeError("player year range is inverted")
        if first <= season_year <= last:
            player_ids.add(player_id)
    return tuple({"player_id": player_id} for player_id in sorted(player_ids))


def _normalize_teams_for_year(
    frame: pl.DataFrame,
    *,
    season_year: int,
) -> tuple[dict[str, object], ...]:
    team_ids: set[int] = set()
    for row in _rows(frame):
        if row.get("league_id") != _NBA_LEAGUE_ID:
            continue
        team_id = _require_positive_int(row.get("team_id"), field_name="team_id")
        first = _require_year(row.get("min_year"), field_name="min_year")
        last = _require_year(row.get("max_year"), field_name="max_year")
        if first > last:
            raise ExactPlanningRuntimeError("team year range is inverted")
        if first <= season_year <= last:
            team_ids.add(team_id)
    return tuple({"team_id": team_id} for team_id in sorted(team_ids))


def _normalize_live_game_ids(
    frame: pl.DataFrame,
    *,
    as_of_utc: str,
) -> tuple[dict[str, object], ...]:
    expected = _require_aware_utc(as_of_utc, field_name="as_of_utc")
    active: set[str] = set()
    for row in _rows(frame):
        snapshot = row.get("snapshot_at")
        if not isinstance(snapshot, datetime) or snapshot.tzinfo is None:
            raise ExactPlanningRuntimeError("live snapshot_at must be an aware datetime")
        if snapshot.astimezone(UTC) != expected:
            raise ExactPlanningRuntimeError("live snapshot_at differs from as_of_utc")
        if row.get("snapshot_date") != expected.date():
            raise ExactPlanningRuntimeError("live snapshot_date differs from as_of_utc")
        if row.get("source_endpoint") != "live_score_board":
            raise ExactPlanningRuntimeError("live source endpoint differs")
        game_id = _require_game_id(row.get("game_id"))
        status = row.get("game_status")
        if type(status) is not int:
            raise ExactPlanningRuntimeError("live game_status must be an integer")
        if status == 2:
            active.add(game_id)
    return tuple({"game_id": game_id} for game_id in sorted(active))


def _normalize_cume_game_ids(
    frame: pl.DataFrame,
    *,
    game_date_ids: frozenset[str],
) -> tuple[dict[str, object], ...]:
    ordered: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in _rows(frame):
        game_id = _require_game_id(row.get("game_id"))
        if game_id in seen:
            raise ExactPlanningRuntimeError("cume foundation contains a duplicate game_id")
        if game_id not in game_date_ids:
            raise ExactPlanningRuntimeError(
                "cume foundation game_id is outside its game/date partition"
            )
        seen.add(game_id)
        ordered.append({"game_id": game_id})
    return tuple(ordered)


def _normalize_semantic_values(
    semantic_kind: PlanningSemanticKind,
    frame: pl.DataFrame,
    *,
    partition: Mapping[str, object],
    game_date_ids: frozenset[str] | None = None,
) -> tuple[dict[str, object], ...]:
    """Normalize one exact semantic partition without consulting global state."""

    if semantic_kind is PlanningSemanticKind.GAME_DATE_INDEX:
        return _normalize_game_date_index(frame)
    if semantic_kind is PlanningSemanticKind.PLAYER_TEAM_SEASON_AFFILIATION:
        return _normalize_affiliations(
            frame,
            season=str(partition["season"]),
            season_type=str(partition["season_type"]),
        )
    if semantic_kind is PlanningSemanticKind.SEASON_PLAYER_UNIVERSE:
        current_only = partition["current_only"]
        if type(current_only) is not bool:
            raise ExactPlanningRuntimeError("current_only partition must be boolean")
        return _normalize_season_players(
            frame,
            season=str(partition["season"]),
            current_only=current_only,
        )
    if semantic_kind is PlanningSemanticKind.SEASON_TEAM_UNIVERSE:
        return _normalize_teams_for_year(
            frame,
            season_year=_season_start_year(partition["season"]),
        )
    if semantic_kind is PlanningSemanticKind.CURRENT_TEAM_UNIVERSE:
        return _normalize_teams_for_year(
            frame,
            season_year=_as_of_season_start(str(partition["as_of_utc"])),
        )
    if semantic_kind is PlanningSemanticKind.ACTIVE_LIVE_GAME_IDS:
        return _normalize_live_game_ids(frame, as_of_utc=str(partition["as_of_utc"]))
    if semantic_kind in {
        PlanningSemanticKind.PLAYER_CUME_FOUNDATION_GAME_IDS,
        PlanningSemanticKind.TEAM_CUME_FOUNDATION_GAME_IDS,
    }:
        if game_date_ids is None:
            raise ExactPlanningRuntimeError("cume normalization requires game/date authority")
        return _normalize_cume_game_ids(frame, game_date_ids=game_date_ids)
    if semantic_kind is PlanningSemanticKind.AUXILIARY_NO_DERIVED_DATA:
        if partition:
            raise ExactPlanningRuntimeError("auxiliary partition must be empty")
        return ()
    raise ExactPlanningRuntimeError("unrecognized planning semantic kind")


def _semantic_specs(
    request: PlanningExactCallRuntimeRequest,
) -> tuple[tuple[RequestedRouteScope, PlanningSemanticKind, dict[str, object]], ...]:
    """Return the exact driver-required member inventory for one call."""

    seasons = sorted(
        {
            str(scope.parameters["season"])
            for scope in request.request.requested_planning_scopes
            if scope.endpoint_name == "league_game_log"
        }
    )
    result: list[tuple[RequestedRouteScope, PlanningSemanticKind, dict[str, object]]] = []
    for scope in request.requested_route_scopes:
        parameters = scope.parameters
        endpoint = scope.endpoint_name
        if endpoint == "league_game_log":
            result.append(
                (
                    scope,
                    PlanningSemanticKind.GAME_DATE_INDEX,
                    {
                        "season": parameters["season"],
                        "season_type": parameters["season_type"],
                    },
                )
            )
        elif endpoint == "player_game_logs":
            result.append(
                (
                    scope,
                    PlanningSemanticKind.PLAYER_TEAM_SEASON_AFFILIATION,
                    {
                        "season": parameters["season"],
                        "season_type": parameters["season_type"],
                    },
                )
            )
        elif endpoint == "common_all_players":
            raw_current = parameters["is_only_current_season"]
            if type(raw_current) is not int or raw_current not in {0, 1}:
                raise ExactPlanningRuntimeError("current-player flag is invalid")
            result.append(
                (
                    scope,
                    PlanningSemanticKind.SEASON_PLAYER_UNIVERSE,
                    {"season": parameters["season"], "current_only": bool(raw_current)},
                )
            )
        elif endpoint == "common_team_years":
            result.extend(
                (scope, PlanningSemanticKind.SEASON_TEAM_UNIVERSE, {"season": season})
                for season in seasons
            )
            result.append(
                (
                    scope,
                    PlanningSemanticKind.CURRENT_TEAM_UNIVERSE,
                    {"as_of_utc": request.as_of_utc},
                )
            )
            result.append((scope, PlanningSemanticKind.AUXILIARY_NO_DERIVED_DATA, {}))
        elif endpoint == "live_score_board":
            result.append(
                (
                    scope,
                    PlanningSemanticKind.ACTIVE_LIVE_GAME_IDS,
                    {"as_of_utc": request.as_of_utc},
                )
            )
        elif endpoint == "cume_stats_player_games":
            result.append(
                (
                    scope,
                    PlanningSemanticKind.PLAYER_CUME_FOUNDATION_GAME_IDS,
                    parameters,
                )
            )
        elif endpoint == "cume_stats_team_games":
            result.append(
                (
                    scope,
                    PlanningSemanticKind.TEAM_CUME_FOUNDATION_GAME_IDS,
                    parameters,
                )
            )
        else:
            raise ExactPlanningRuntimeError("planning call uses an unrecognized root endpoint")
    return tuple(result)


def _artifact_source(path: Path) -> PlanningArtifactSource:
    descriptor = -1
    try:
        observed = os.stat(path, follow_symlinks=False)
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        opened = os.fstat(descriptor)
    except OSError as exc:
        raise ExactPlanningRuntimeError("planning artifact is unreadable") from exc
    try:
        if (
            not stat.S_ISREG(observed.st_mode)
            or not stat.S_ISREG(opened.st_mode)
            or (observed.st_dev, observed.st_ino) != (opened.st_dev, opened.st_ino)
            or path.is_symlink()
        ):
            raise ExactPlanningRuntimeError("planning artifact must be a regular file")
        digest = hashlib.sha256()
        byte_count = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
            byte_count += len(chunk)
        final = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
        identity = (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        )
        if (
            identity
            != (
                final.st_dev,
                final.st_ino,
                final.st_size,
                final.st_mtime_ns,
                final.st_ctime_ns,
            )
            or (final.st_dev, final.st_ino) != (named.st_dev, named.st_ino)
            or byte_count != opened.st_size
        ):
            raise ExactPlanningRuntimeError("planning artifact changed while measured")
        return PlanningArtifactSource(
            path=Path(os.path.abspath(path)),
            sha256=digest.hexdigest(),
            byte_count=byte_count,
        )
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, encoded: bytes, *, label: str) -> None:
    view = memoryview(encoded)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise ExactPlanningRuntimeError(f"{label} write made no progress")
        view = view[written:]


def _copy_database_source(source: PlanningDatabaseSource, destination: Path) -> None:
    source_path = source.artifact.path
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    source_descriptor = os.open(source_path, flags)
    destination_descriptor = -1
    try:
        before = os.fstat(source_descriptor)
        named = os.stat(source_path, follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or (before.st_dev, before.st_ino) != (named.st_dev, named.st_ino)
            or before.st_size != source.artifact.byte_count
        ):
            raise ExactPlanningRuntimeError("input planning database identity differs")
        destination_descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        digest = hashlib.sha256()
        byte_count = 0
        while chunk := os.read(source_descriptor, 1024 * 1024):
            digest.update(chunk)
            byte_count += len(chunk)
            _write_all(destination_descriptor, chunk, label="planning database copy")
        os.fsync(destination_descriptor)
        after = os.fstat(source_descriptor)
        if (
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or byte_count != source.artifact.byte_count
            or digest.hexdigest() != source.artifact.sha256
        ):
            raise ExactPlanningRuntimeError("input planning database changed during adoption")
    finally:
        os.close(source_descriptor)
        if destination_descriptor >= 0:
            os.close(destination_descriptor)


def _configure_bounded_planning_database(connection: duckdb.DuckDBPyConnection) -> None:
    """Disable spill/WAL growth paths outside the RLIMIT-bounded database file."""

    try:
        connection.execute("SET temp_directory = ''")
        connection.execute("SET max_temp_directory_size = '0 B'")
        connection.execute("SET auto_checkpoint_skip_wal_threshold = 0")
        connection.execute("SET wal_autocheckpoint = '0 B'")
        observed = dict(
            connection.execute(
                """
                SELECT name, value
                FROM duckdb_settings()
                WHERE name IN (
                    'temp_directory',
                    'max_temp_directory_size',
                    'auto_checkpoint_skip_wal_threshold',
                    'wal_autocheckpoint'
                )
                """
            ).fetchall()
        )
    except Exception as exc:
        raise ExactPlanningRuntimeError(
            "planning database hard-cap settings cannot be installed"
        ) from exc
    expected = {
        "temp_directory": "",
        "max_temp_directory_size": "0 bytes",
        "auto_checkpoint_skip_wal_threshold": "0",
        "wal_autocheckpoint": "0 bytes",
    }
    if observed != expected:
        raise ExactPlanningRuntimeError(
            "planning database hard-cap settings differ from exact authority"
        )


def _game_date_authority(
    connection: duckdb.DuckDBPyConnection,
    *,
    season: str,
    season_type: str,
) -> frozenset[str]:
    partition_json = json.dumps(
        {"season": season, "season_type": season_type},
        sort_keys=True,
        separators=(",", ":"),
    )
    rows = connection.execute(
        f"""
        SELECT value_json
        FROM {SUCCESSOR_PLANNING_SEMANTIC_VALUES_TABLE}
        WHERE descriptor_identity_sha256 IN (
            SELECT descriptor_identity_sha256
            FROM {SUCCESSOR_PLANNING_SEMANTIC_PARTITIONS_TABLE}
            WHERE semantic_kind = ? AND partition_json = ?
        )
        ORDER BY ordinal
        """,
        [PlanningSemanticKind.GAME_DATE_INDEX.value, partition_json],
    ).fetchall()
    result: set[str] = set()
    for (encoded,) in rows:
        try:
            value = json.loads(str(encoded))
        except json.JSONDecodeError as exc:
            raise ExactPlanningRuntimeError("game/date authority JSON is invalid") from exc
        if not isinstance(value, dict) or set(value) != {"game_date", "game_id"}:
            raise ExactPlanningRuntimeError("game/date authority value is invalid")
        result.add(_require_game_id(value["game_id"]))
    return frozenset(result)


class _AtomicSuccessJournal(PipelineJournal):
    """Delegate the runner's W2-required journal protocol to one exact journal."""

    def __init__(self, journal: PipelineJournal) -> None:
        self._journal = journal

    def record_start(
        self,
        endpoint: str,
        params: str,
        *,
        require_receipt: bool = False,
        require_w2_operation: bool = False,
    ) -> None:
        self._journal.record_start(
            endpoint,
            params,
            require_receipt=require_receipt,
            require_w2_operation=require_w2_operation,
        )

    def record_failure(self, endpoint: str, params: str, error: str) -> None:
        self._journal.record_failure(endpoint, params, error)

    def was_extracted_batch(
        self,
        items: list[tuple[str, str]],
        *,
        require_receipt: bool = False,
        require_w2_operation: bool = False,
    ) -> set[tuple[str, str]]:
        return self._journal.was_extracted_batch(
            items,
            require_receipt=require_receipt,
            require_w2_operation=require_w2_operation,
        )

    def was_extracted(
        self,
        endpoint: str,
        params: str,
        *,
        require_receipt: bool = False,
        require_w2_operation: bool = False,
    ) -> bool:
        return self._journal.was_extracted(
            endpoint,
            params,
            require_receipt=require_receipt,
            require_w2_operation=require_w2_operation,
        )

    def record_metric(self, *_args: object, **_kwargs: object) -> None:
        # Metrics are not planning authority and the minimal private database
        # intentionally has no ordinary pipeline-metrics table.
        return None

    def record_success(
        self,
        endpoint: str,
        params: str,
        rows: int,
        *,
        receipt_binding: LogicalCallReceiptBinding | None = None,
        w2_admission: W2SourceCallAdmissionV1 | None = None,
    ) -> None:
        if (
            type(receipt_binding) is not LogicalCallReceiptBinding
            or type(w2_admission) is not W2SourceCallAdmissionV1
        ):
            raise ExactPlanningRuntimeError(
                "planning journal success requires exact logical-call and W2 admissions"
            )
        self._journal.record_success(
            endpoint,
            params,
            rows,
            receipt_binding=receipt_binding,
            w2_admission=w2_admission,
        )


@dataclass(frozen=True, slots=True)
class _ValidatedPlanningSourceResultV1:
    frames: dict[str, pl.DataFrame]
    source_params_json: str
    binding: LogicalCallReceiptBinding
    route_mapping: tuple[tuple[str, str], ...]
    raw_snapshot: RawRequestCaptureSnapshotV2
    recorded_static_attempts: tuple[RecordedParserInput, ...]
    plan_live_snapshot_at: datetime | None


class ExtractorPlanningExactCallRuntime:
    """Production exact-call runtime injected beneath the frozen planning driver."""

    def __init__(self, config: ExactPlanningRuntimeConfig) -> None:
        if not isinstance(config, ExactPlanningRuntimeConfig):
            raise ExactPlanningRuntimeError("config must be ExactPlanningRuntimeConfig")
        self._config = config
        self._sessions: dict[tuple[str, int], PrivateCaptureSession] = {}

    @property
    def config(self) -> ExactPlanningRuntimeConfig:
        return self._config

    def _validate_request_authority(self, request: PlanningExactCallRuntimeRequest) -> None:
        if not isinstance(request, PlanningExactCallRuntimeRequest):
            raise ExactPlanningRuntimeError("exact-call request has an invalid type")
        expected_provider = expected_nba_api_provider_authority().get("authority_sha256")
        if request.provider_authority_sha256 != expected_provider:
            raise ExactPlanningRuntimeError("exact-call provider authority differs")
        if request.dispatch.endpoint_name not in {
            scope.endpoint_name for scope in request.requested_route_scopes
        }:
            raise ExactPlanningRuntimeError("exact-call endpoint differs from requested scopes")
        if any(
            scope.endpoint_name != request.dispatch.endpoint_name
            or scope.parameters != request.dispatch.parameters
            or scope.scope_sha256 != request.dispatch.parameters_sha256
            for scope in request.requested_route_scopes
        ):
            raise ExactPlanningRuntimeError("exact-call parameters differ from requested scope")
        if request.dispatch.staging_route_ids != tuple(
            scope.route_id for scope in request.requested_route_scopes
        ):
            raise ExactPlanningRuntimeError("exact-call routes differ from requested scopes")
        _require_aware_utc(request.cutoff_utc, field_name="cutoff_utc")
        _require_aware_utc(request.as_of_utc, field_name="as_of_utc")

    def _capture_scope(
        self,
        *,
        planning_generation_id: str,
        wave_index: int,
        source_sha: str,
        workflow_run_id: int,
        workflow_run_attempt: int,
    ) -> CaptureRunScope:
        return CaptureRunScope(
            semantic_source_sha=source_sha,
            chain_id=planning_generation_id,
            lane_id=f"planning-wave-{wave_index}",
            workflow_run_id=workflow_run_id,
            workflow_run_attempt=workflow_run_attempt,
        )

    def _wave_root(self, planning_generation_id: str, wave_index: int) -> Path:
        generation_root = self._config.capture_base / planning_generation_id
        wave_root = generation_root / f"wave-{wave_index}"
        for path in (generation_root, wave_root):
            try:
                path.mkdir(mode=0o700, exist_ok=True)
                observed = os.stat(path, follow_symlinks=False)
            except OSError as exc:
                raise ExactPlanningRuntimeError(
                    "cannot create private planning capture root"
                ) from exc
            if (
                not stat.S_ISDIR(observed.st_mode)
                or path.is_symlink()
                or (
                    os.name == "posix"
                    and (observed.st_uid != os.geteuid() or stat.S_IMODE(observed.st_mode) != 0o700)
                )
            ):
                raise ExactPlanningRuntimeError(
                    "private planning capture root is not stable owner-only authority"
                )
        return wave_root

    def _session_for_call(
        self,
        request: PlanningExactCallRuntimeRequest,
        *,
        monotonic_now_seconds: float,
    ) -> PrivateCaptureSession:
        key = (request.planning_generation_id, request.wave_index)
        existing = self._sessions.get(key)
        if existing is not None:
            if existing.closed:
                raise ExactPlanningRuntimeError("planning capture session is already closed")
            return existing
        scope = self._capture_scope(
            planning_generation_id=request.planning_generation_id,
            wave_index=request.wave_index,
            source_sha=request.request.source_sha,
            workflow_run_id=request.workflow_run_id,
            workflow_run_attempt=request.workflow_run_attempt,
        )
        session = PrivateCaptureSession(
            self._wave_root(request.planning_generation_id, request.wave_index),
            limits=self._config.capture_limits,
            public_roots=self._config.public_roots,
            scope=scope,
        )
        sealed = session.restore_sealed_identity_if_present()
        if sealed is not None:
            session.close()
            raise ExactPlanningRuntimeError("cannot execute a call in a sealed planning wave")
        session.admit(
            estimated_checkpoint_bytes=self._config.estimated_checkpoint_bytes,
            monotonic_now_seconds=monotonic_now_seconds,
            monotonic_deadline_seconds=self._config.monotonic_deadline_seconds,
        )
        self._sessions[key] = session
        return session

    def _new_output_database(
        self,
        request: PlanningExactCallRuntimeRequest,
    ) -> Path:
        root = Path(os.path.abspath(request.private_work_root))
        observed = os.stat(root, follow_symlinks=False)
        if (
            not stat.S_ISDIR(observed.st_mode)
            or root.is_symlink()
            or (
                os.name == "posix"
                and (observed.st_uid != os.geteuid() or stat.S_IMODE(observed.st_mode) != 0o700)
            )
        ):
            raise ExactPlanningRuntimeError("planning private work root is not owner-only")
        call_root = root / (f"call-{request.dispatch.identity_sha256[:16]}-{secrets.token_hex(8)}")
        call_root.mkdir(mode=0o700)
        database = call_root / "planning.duckdb"
        if request.input_planning_database is not None:
            self._require_driver_database_bound(
                request.input_planning_database,
                label="planning driver input database",
            )
            _copy_database_source(request.input_planning_database, database)
        return database

    def _require_driver_database_bound(
        self,
        database: PlanningDatabaseSource,
        *,
        label: str,
    ) -> None:
        if not isinstance(database, PlanningDatabaseSource):
            raise ExactPlanningRuntimeError(f"{label} is invalid")
        if database.artifact.byte_count > self._config.planning_driver_database_max_bytes:
            raise ExactPlanningRuntimeError(f"{label} exceeds planning_driver_database_max_bytes")

    @staticmethod
    def _entries_for_request(request: PlanningExactCallRuntimeRequest) -> list[StagingEntry]:
        bundle = staging_route_contract_bundle()
        entries: list[StagingEntry] = []
        for route_id in request.dispatch.staging_route_ids:
            route = bundle.by_route_id.get(route_id)
            if route is None or route.ordinal >= len(STAGING_MAP):
                raise ExactPlanningRuntimeError("planning route is absent from current topology")
            entry = STAGING_MAP[route.ordinal]
            expected_route = f"{entry.endpoint_name}:{entry.staging_key}:{entry.result_set_index}"
            if (
                expected_route != route_id
                or entry.endpoint_name != request.dispatch.endpoint_name
                or entry.param_pattern != request.dispatch.pattern
            ):
                raise ExactPlanningRuntimeError("planning route does not map to its staging entry")
            entries.append(entry)
        return entries

    @staticmethod
    def _validated_raw_request_context(
        context: object,
        *,
        scope: CaptureRunScope,
        provider_authority_sha256: str,
    ) -> RawRequestCaptureContextV2:
        if type(context) is not RawRequestCaptureContextV2:
            raise ExactPlanningRuntimeError(
                "planning raw-request factory returned a foreign context"
            )
        if (
            context.provider_authority_sha256 != provider_authority_sha256
            or context.source_sha != scope.semantic_source_sha
            or context.run_id != scope.workflow_run_id
            or context.run_attempt != scope.workflow_run_attempt
            or context.chain_id != scope.chain_id
            or context.lane_id != scope.lane_id
        ):
            raise ExactPlanningRuntimeError(
                "planning raw-request context differs from the capture run scope"
            )
        return context

    @staticmethod
    def _require_bound_raw_snapshot(
        snapshot: RawRequestCaptureSnapshotV2,
        binding: LogicalCallReceiptBinding,
    ) -> RawRequestCaptureSnapshotV2:
        if type(snapshot) is not RawRequestCaptureSnapshotV2:
            raise ExactPlanningRuntimeError(
                "planning raw-request snapshot has a foreign exact type"
            )
        if not snapshot.pending_successes:
            raise ExactPlanningRuntimeError(
                "planning raw-request snapshot has no pending successful provider call"
            )
        for pending in snapshot.pending_successes:
            if (
                type(pending) is not PendingRawRequestSuccessV2
                or pending.logical_receipt_sha256 != binding.logical_call_receipt_sha256
                or pending.aggregate_route_ids != binding.result_route_ids
                or pending.attempt.provider_authority_sha256 != binding.provider_authority_sha256
            ):
                raise ExactPlanningRuntimeError(
                    "planning public capture differs from its private logical-call selection"
                )
        return snapshot

    @staticmethod
    def _validated_live_plan_bindings(
        value: object,
        *,
        scope: CaptureRunScope,
        source: _ValidatedPlanningSourceResultV1,
    ) -> tuple[tuple[LiveSnapshotPlanAuthorityV2, str], ...]:
        if type(value) is not tuple:
            raise ExactPlanningRuntimeError(
                "planning live-plan factory must return one exact tuple"
            )
        live_pending = tuple(
            item
            for item in source.raw_snapshot.pending_successes
            if item.attempt.source_family == "live"
        )
        expected_observations = {item.attempt.observation_sha256 for item in live_pending}
        observed: set[str] = set()
        bindings: list[tuple[LiveSnapshotPlanAuthorityV2, str]] = []
        for item in value:
            if type(item) is not tuple or len(item) != 2:
                raise ExactPlanningRuntimeError("planning live-plan binding has a foreign shape")
            plan, expected_sha256 = item
            if (
                type(plan) is not LiveSnapshotPlanAuthorityV2
                or type(expected_sha256) is not str
                or expected_sha256 != plan.authority_sha256
                or plan.observation_sha256 in observed
                or plan.source_sha != scope.semantic_source_sha
                or plan.run_id != scope.workflow_run_id
                or plan.run_attempt != scope.workflow_run_attempt
                or plan.chain_id != scope.chain_id
                or plan.lane_id != scope.lane_id
                or plan.observation_sha256 not in expected_observations
                or plan.route_ids != source.binding.result_route_ids
                or plan.provider_authority_sha256 != source.binding.provider_authority_sha256
                or plan.live_snapshot_at != source.plan_live_snapshot_at
            ):
                raise ExactPlanningRuntimeError(
                    "planning live-plan binding differs from its external authority"
                )
            observed.add(plan.observation_sha256)
            bindings.append((plan, expected_sha256))
        if observed != expected_observations:
            raise ExactPlanningRuntimeError(
                "planning live-plan bindings do not exactly cover the successful live call"
            )
        return tuple(bindings)

    @staticmethod
    def _validated_source_result(
        request: PlanningExactCallRuntimeRequest,
        source_results: object,
    ) -> _ValidatedPlanningSourceResultV1:
        if not isinstance(source_results, list) or len(source_results) != 1:
            raise ExactPlanningRuntimeError("planning call must expose one source result")
        source = source_results[0]
        if not isinstance(source, dict):
            raise ExactPlanningRuntimeError("planning source result must be an object")
        frames = source.get("frames")
        source_params_json = source.get("source_params_json")
        binding = source.get("receipt_binding")
        route_mapping = source.get("result_route_ids_by_staging_key")
        expected_keys = source.get("expected_staging_keys")
        raw_snapshot = source.get("raw_request_capture_snapshot")
        recorded_static_attempts = source.get("recorded_static_attempts")
        plan_live_snapshot_at = source.get("plan_live_snapshot_at")
        if (
            not isinstance(frames, dict)
            or not all(
                isinstance(key, str) and isinstance(value, pl.DataFrame)
                for key, value in frames.items()
            )
            or not isinstance(source_params_json, str)
            or not isinstance(binding, LogicalCallReceiptBinding)
            or not isinstance(route_mapping, tuple)
            or not isinstance(expected_keys, tuple)
            or type(raw_snapshot) is not RawRequestCaptureSnapshotV2
            or type(recorded_static_attempts) is not tuple
            or any(type(item) is not RecordedParserInput for item in recorded_static_attempts)
        ):
            raise ExactPlanningRuntimeError("planning source result fields are invalid")
        source_families = {
            item.attempt.source_family
            for item in (
                *raw_snapshot.pending_successes,
                *raw_snapshot.observations,
            )
        }
        if source_families == {"live"}:
            if (
                type(plan_live_snapshot_at) is not datetime
                or plan_live_snapshot_at.tzinfo is None
                or plan_live_snapshot_at.utcoffset() is None
            ):
                raise ExactPlanningRuntimeError(
                    "planning live source lacks its sealed-plan timestamp projection"
                )
            plan_live_snapshot_at = plan_live_snapshot_at.astimezone(UTC)
        elif plan_live_snapshot_at is not None:
            raise ExactPlanningRuntimeError(
                "planning non-live source received a live timestamp projection"
            )
        if any(
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not isinstance(item[1], str)
            for item in route_mapping
        ):
            raise ExactPlanningRuntimeError("planning route mapping is invalid")
        normalized_route_mapping = cast("tuple[tuple[str, str], ...]", route_mapping)
        normalized_frames = cast("dict[str, pl.DataFrame]", frames)
        normalized_static_attempts = cast(
            "tuple[RecordedParserInput, ...]",
            recorded_static_attempts,
        )
        routes = staging_route_contract_bundle().by_route_id
        static_key_tuple = tuple(
            routes[item].staging_key for item in request.dispatch.staging_route_ids
        )
        static_mapping = tuple(
            (routes[item].staging_key, item) for item in request.dispatch.staging_route_ids
        )
        static_route_id_set = set(request.dispatch.staging_route_ids)
        conditional_route_ids = tuple(
            route_id for route_id in binding.result_route_ids if route_id not in static_route_id_set
        )
        conditional_admission: KnownConditionalStagingRouteAdmission | None = None
        if conditional_route_ids:
            try:
                conditional_admission = admit_known_conditional_staging_route(
                    endpoint_name=request.dispatch.endpoint_name,
                    static_route_ids=request.dispatch.staging_route_ids,
                    conditional_route_ids=conditional_route_ids,
                    provider_authority_sha256=request.provider_authority_sha256,
                )
            except ValueError as exc:
                raise ExactPlanningRuntimeError(
                    "planning source conditional route lacks typed response authority"
                ) from exc
        conditional_staging_key = (
            conditional_admission.staging_key if conditional_admission is not None else None
        )
        expected_key_tuple = (
            (*static_key_tuple, conditional_staging_key)
            if conditional_staging_key is not None
            else static_key_tuple
        )
        expected_mapping = tuple(
            sorted(
                (
                    *static_mapping,
                    *(
                        (
                            (
                                conditional_staging_key,
                                conditional_admission.route_id,
                            ),
                        )
                        if conditional_admission is not None
                        else ()
                    ),
                )
            )
        )
        if (
            source.get("source_endpoint_name") != request.dispatch.endpoint_name
            or tuple(expected_keys) != expected_key_tuple
            or set(normalized_frames) != set(expected_key_tuple)
            or normalized_route_mapping != expected_mapping
            or binding.endpoint_name != request.dispatch.endpoint_name
            or binding.logical_parameters_sha256 != request.dispatch.parameters_sha256
            or binding.provider_authority_sha256 != request.provider_authority_sha256
            or binding.result_route_ids
            != tuple(
                sorted(
                    (
                        *request.dispatch.staging_route_ids,
                        *((conditional_admission.route_id,) if conditional_admission else ()),
                    )
                )
            )
        ):
            raise ExactPlanningRuntimeError("planning source result differs from sealed dispatch")
        try:
            decoded_parameters = json.loads(source_params_json)
        except json.JSONDecodeError as exc:
            raise ExactPlanningRuntimeError("planning source parameters are invalid") from exc
        if (
            not isinstance(decoded_parameters, dict)
            or canonical_parameters_sha256(decoded_parameters) != request.dispatch.parameters_sha256
        ):
            raise ExactPlanningRuntimeError("planning source parameters differ")
        validated: dict[str, pl.DataFrame] = {}
        for route_id, (staging_key, _mapped_route) in zip(
            request.dispatch.staging_route_ids,
            static_mapping,
            strict=True,
        ):
            route = routes[route_id]
            schema = get_input_schema(route.resolved_schema_table)
            if schema is None:
                raise ExactPlanningRuntimeError("planning route has no input schema")
            candidate = normalized_frames[staging_key]
            if conditional_admission is not None and candidate.is_empty() and candidate.width == 0:
                schema_object = schema.to_schema()
                candidate = pl.DataFrame(
                    schema={
                        column_name: column.dtype.type
                        for column_name, column in schema_object.columns.items()
                    }
                )
            try:
                normalized = schema.validate(candidate)
            except Exception as exc:
                raise ExactPlanningRuntimeError(
                    "planning frame failed its exact input schema"
                ) from exc
            if not isinstance(normalized, pl.DataFrame):
                raise ExactPlanningRuntimeError("input schema returned a non-Polars frame")
            validated[staging_key] = normalized
        if conditional_admission is not None:
            conditional_frame = normalized_frames[conditional_admission.staging_key]
        if isinstance(conditional_admission, ConditionalStagingRouteAdmission):
            fallback = conditional_frame
            try:
                receipt_column = fallback.get_column("response_receipt_sha256")
                endpoint_slug_column = fallback.get_column("endpoint_slug")
            except pl.exceptions.ColumnNotFoundError as exc:
                raise ExactPlanningRuntimeError(
                    "planning fallback frame omitted receipt or endpoint identity"
                ) from exc
            receipts = receipt_column.drop_nulls().unique().to_list()
            endpoint_slugs = endpoint_slug_column.drop_nulls().unique().to_list()
            if (
                fallback.is_empty()
                or receipt_column.null_count()
                or len(receipts) != 1
                or not isinstance(receipts[0], str)
                or endpoint_slug_column.null_count()
                or endpoint_slugs != [conditional_admission.provider_endpoint_slug]
            ):
                raise ExactPlanningRuntimeError(
                    "planning fallback frame differs from its response receipt or endpoint"
                )
            try:
                validate_lossless_fallback_frame(
                    fallback,
                    expected_response_receipt_sha256=receipts[0],
                )
            except ResponseContractError as exc:
                raise ExactPlanningRuntimeError(
                    "planning fallback frame failed its fixed lossless contract"
                ) from exc
            fallback_schema = get_input_schema(LOSSLESS_FALLBACK_STAGING_KEY)
            if fallback_schema is None:
                raise ExactPlanningRuntimeError("planning fallback has no input schema")
            try:
                normalized_fallback = fallback_schema.validate(fallback)
            except Exception as exc:
                raise ExactPlanningRuntimeError(
                    "planning fallback frame failed its exact input schema"
                ) from exc
            if not isinstance(normalized_fallback, pl.DataFrame):
                raise ExactPlanningRuntimeError("input schema returned a non-Polars frame")
            validated[LOSSLESS_FALLBACK_STAGING_KEY] = normalized_fallback
        elif isinstance(conditional_admission, ConditionalLiveStagingRouteAdmission):
            live_lossless = conditional_frame
            expected_snapshot_at = _require_aware_utc(
                request.as_of_utc,
                field_name="as_of_utc",
            )
            required_identity = {
                "provider_authority_sha256": conditional_admission.provider_authority_sha256,
                "endpoint_contract_sha256": conditional_admission.endpoint_contract_sha256,
                "endpoint_id": conditional_admission.provider_endpoint_id,
                "endpoint_slug": conditional_admission.provider_endpoint_slug,
            }
            if live_lossless.is_empty():
                raise ExactPlanningRuntimeError(
                    "planning live-lossless frame omitted response nodes"
                )
            try:
                for column_name, expected_value in required_identity.items():
                    if live_lossless.get_column(column_name).unique().to_list() != [expected_value]:
                        raise ExactPlanningRuntimeError(
                            "planning live-lossless frame differs from its typed authority"
                        )
                request_parameters = (
                    live_lossless.get_column("request_parameters_json").unique().to_list()
                )
                if (
                    len(request_parameters) != 1
                    or not isinstance(request_parameters[0], str)
                    or conditional_admission.logical_parameters_sha256(request_parameters[0])
                    != binding.logical_parameters_sha256
                ):
                    raise ExactPlanningRuntimeError(
                        "planning live-lossless frame differs from its request scope"
                    )
                receipt_frames = live_lossless.partition_by(
                    "response_receipt_sha256",
                    maintain_order=True,
                )
                if not receipt_frames:
                    raise ExactPlanningRuntimeError(
                        "planning live-lossless frame has no response receipt"
                    )
                for receipt_frame in receipt_frames:
                    receipts = (
                        receipt_frame.get_column("response_receipt_sha256").unique().to_list()
                    )
                    snapshots = receipt_frame.get_column("snapshot_at").unique().to_list()
                    if (
                        len(receipts) != 1
                        or not isinstance(receipts[0], str)
                        or len(snapshots) != 1
                        or not isinstance(snapshots[0], datetime)
                        or snapshots[0].tzinfo is None
                        or snapshots[0].astimezone(UTC) != expected_snapshot_at
                    ):
                        raise ExactPlanningRuntimeError(
                            "planning live-lossless receipt or snapshot is ambiguous"
                        )
                    validate_live_lossless_frame(
                        receipt_frame,
                        expected_response_receipt_sha256=receipts[0],
                        expected_result_set_count=(conditional_admission.expected_result_set_count),
                        expected_snapshot_at=snapshots[0],
                        expected_endpoint_id=conditional_admission.provider_endpoint_id,
                        expected_endpoint_slug=conditional_admission.provider_endpoint_slug,
                    )
            except pl.exceptions.ColumnNotFoundError as exc:
                raise ExactPlanningRuntimeError(
                    "planning live-lossless frame omitted receipt or authority columns"
                ) from exc
            except ValueError as exc:
                raise ExactPlanningRuntimeError(
                    "planning live-lossless frame differs from its request scope"
                ) from exc
            except ResponseContractError as exc:
                raise ExactPlanningRuntimeError(
                    "planning live-lossless frame failed its fixed node contract"
                ) from exc
            live_schema = get_input_schema(LIVE_LOSSLESS_STAGING_KEY)
            if live_schema is None:
                raise ExactPlanningRuntimeError("planning live-lossless frame has no input schema")
            try:
                normalized_live = live_schema.validate(live_lossless)
            except Exception as exc:
                raise ExactPlanningRuntimeError(
                    "planning live-lossless frame failed its exact input schema"
                ) from exc
            if not isinstance(normalized_live, pl.DataFrame):
                raise ExactPlanningRuntimeError("input schema returned a non-Polars frame")
            validated[LIVE_LOSSLESS_STAGING_KEY] = normalized_live
        return _ValidatedPlanningSourceResultV1(
            frames=validated,
            source_params_json=source_params_json,
            binding=binding,
            route_mapping=normalized_route_mapping,
            raw_snapshot=raw_snapshot,
            recorded_static_attempts=normalized_static_attempts,
            plan_live_snapshot_at=plan_live_snapshot_at,
        )

    @staticmethod
    def _frame_for_scope(
        request: PlanningExactCallRuntimeRequest,
        frames: Mapping[str, pl.DataFrame],
        scope: RequestedRouteScope,
    ) -> pl.DataFrame:
        route_id = scope.route_id
        route = staging_route_contract_bundle().by_route_id[route_id]
        try:
            return frames[route.staging_key]
        except KeyError as exc:
            raise ExactPlanningRuntimeError("semantic scope lacks its route-local frame") from exc

    @_bounded_planning_file_size
    async def execute_planning_call(
        self,
        request: PlanningExactCallRuntimeRequest,
    ) -> PlanningCallExecution:
        """Execute and atomically persist one exact provider planning call."""
        monotonic_now_seconds = self._config.require_deadline_headroom(stage="planning call entry")
        self._config.require_current_roots()
        self._validate_request_authority(request)
        require_live_plan_authority_available(
            request.dispatch.endpoint_name,
            self._config.w2_authority_resources,
        )
        self._config.require_current_registry(endpoint_name=request.dispatch.endpoint_name)
        self._config.require_before_planning_effects_authority()
        if request.input_planning_database is not None:
            self._require_driver_database_bound(
                request.input_planning_database,
                label="planning driver input database",
            )
        database_path = self._new_output_database(request)
        as_of = _require_aware_utc(request.as_of_utc, field_name="as_of_utc")
        generation = SuccessorPlanningStore.generation_identity(
            request.request,
            request.planning_generation_id,
        )
        connection = duckdb.connect(str(database_path))
        os.chmod(database_path, 0o600)
        source_binding: LogicalCallReceiptBinding | None = None
        source_admission: W2SourceCallAdmissionV1 | None = None
        descriptors: list[tuple[RequestedRouteScope, PlanningSemanticDescriptor]] = []
        try:
            _configure_bounded_planning_database(connection)
            install_successor_planning_semantic_schema(connection)
            staging = StagingBatchStore(connection)
            journal = PipelineJournal(
                connection,
                successor_generation_sha256=generation,
                utc_now=lambda: as_of,
            )
            atomic_journal = _AtomicSuccessJournal(journal)
            entries = self._entries_for_request(request)
            connection.execute("CHECKPOINT")
            pre_provider_database = _artifact_source(database_path)
            if pre_provider_database.byte_count > self._config.planning_driver_database_max_bytes:
                raise ExactPlanningRuntimeError(
                    "planning driver output database exceeds "
                    "planning_driver_database_max_bytes before provider execution"
                )
            session = self._session_for_call(
                request,
                monotonic_now_seconds=monotonic_now_seconds,
            )
            capture_scope = self._capture_scope(
                planning_generation_id=request.planning_generation_id,
                wave_index=request.wave_index,
                source_sha=request.request.source_sha,
                workflow_run_id=request.workflow_run_id,
                workflow_run_attempt=request.workflow_run_attempt,
            )
            resources = self._config.w2_authority_resources
            logical_parameter_authority: (
                tuple[
                    LogicalProviderParameterBindingV1,
                    str,
                ]
                | None
            ) = None

            def raw_request_context_for(
                endpoint_name: str,
                parameters: dict[str, object],
            ) -> RawRequestCaptureContextV2:
                nonlocal logical_parameter_authority
                if (
                    endpoint_name != request.dispatch.endpoint_name
                    or canonical_parameters_sha256(parameters) != request.dispatch.parameters_sha256
                ):
                    raise ExactPlanningRuntimeError(
                        "planning raw-request context request differs from sealed dispatch"
                    )
                try:
                    context = resources.raw_request_context_factory(
                        capture_scope,
                        endpoint_name,
                        dict(parameters),
                    )
                except Exception:
                    raise ExactPlanningRuntimeError(
                        "planning raw-request context factory failed"
                    ) from None
                exact_context = self._validated_raw_request_context(
                    context,
                    scope=capture_scope,
                    provider_authority_sha256=request.provider_authority_sha256,
                )
                if logical_parameter_authority is not None:
                    raise ExactPlanningRuntimeError(
                        "planning logical/provider parameter authority was compiled twice"
                    )
                try:
                    raw_parameter_authority = resources.logical_provider_parameter_binding_factory(
                        capture_scope,
                        request,
                        exact_context,
                    )
                except Exception:
                    raise ExactPlanningRuntimeError(
                        "planning logical/provider parameter authority factory failed"
                    ) from None
                if (
                    type(raw_parameter_authority) is not tuple
                    or len(raw_parameter_authority) != 2
                    or type(raw_parameter_authority[0]) is not LogicalProviderParameterBindingV1
                    or type(raw_parameter_authority[1]) is not str
                ):
                    raise ExactPlanningRuntimeError(
                        "planning logical/provider parameter factory returned a foreign binding"
                    )
                try:
                    parameter_binding = verify_logical_provider_parameter_binding(
                        raw_parameter_authority[0],
                        expected_binding_sha256=raw_parameter_authority[1],
                    )
                except Exception:
                    raise ExactPlanningRuntimeError(
                        "planning logical/provider parameter binding failed external verification"
                    ) from None
                if (
                    parameter_binding.logical_endpoint_name != request.dispatch.endpoint_name
                    or parameter_binding.logical_parameters_sha256
                    != request.dispatch.parameters_sha256
                    or parameter_binding.result_route_ids
                    != tuple(sorted(request.dispatch.staging_route_ids))
                ):
                    raise ExactPlanningRuntimeError(
                        "planning logical/provider parameter binding differs from dispatch"
                    )
                logical_parameter_authority = (
                    parameter_binding,
                    raw_parameter_authority[1],
                )
                return exact_context

            def admit_call(
                endpoint_name: str,
                parameters: dict[str, object],
                route_ids: tuple[str, ...],
            ) -> None:
                if (
                    endpoint_name != request.dispatch.endpoint_name
                    or canonical_parameters_sha256(parameters) != request.dispatch.parameters_sha256
                    or route_ids != tuple(sorted(request.dispatch.staging_route_ids))
                ):
                    raise ExactPlanningRuntimeError(
                        "provider call differs from sealed planning admission"
                    )

            def admit_conditional_routes(
                endpoint_name: str,
                parameters: dict[str, object],
                static_route_ids: tuple[str, ...],
                conditional_route_ids: tuple[str, ...],
            ) -> None:
                admit_call(endpoint_name, parameters, static_route_ids)
                try:
                    admit_known_conditional_staging_route(
                        endpoint_name=endpoint_name,
                        static_route_ids=static_route_ids,
                        conditional_route_ids=conditional_route_ids,
                        provider_authority_sha256=request.provider_authority_sha256,
                    )
                except ValueError as exc:
                    raise ExactPlanningRuntimeError(
                        "provider conditional route differs from typed response authority"
                    ) from exc

            def persist_results(
                _frames: dict[str, pl.DataFrame],
                *,
                source_results: object,
                **_metadata: object,
            ) -> tuple[W2SourceCallAdmissionV1, ...]:
                nonlocal source_admission, source_binding
                source = self._validated_source_result(request, source_results)
                frames = source.frames
                binding = source.binding
                if source_binding is not None or source_admission is not None:
                    raise ExactPlanningRuntimeError("planning call persisted more than once")
                source_binding = binding
                snapshot = self._require_bound_raw_snapshot(
                    source.raw_snapshot,
                    binding,
                )
                if logical_parameter_authority is None:
                    raise ExactPlanningRuntimeError(
                        "planning provider call lacks pre-provider parameter authority"
                    )
                parameter_binding, expected_parameter_binding_sha256 = logical_parameter_authority
                crash_injection.after_durable_step(
                    crash_injection.DurablePlanningStep.PROVIDER_CAPTURE,
                    planning_generation_id=request.planning_generation_id,
                    dispatch_identity_sha256=request.dispatch.identity_sha256,
                    logical_call_receipt_sha256=binding.logical_call_receipt_sha256,
                )
                batch = StagingFrameBatch(
                    frames=frames,
                    metadata=StagingChunkMetadata(
                        run_mode="successor_planning",
                        lane_id=f"planning-wave-{request.wave_index}",
                        pattern=request.dispatch.pattern,
                        chunk_index=0,
                        params_digest=digest_jsonable([request.dispatch.parameters]),
                        entries_digest=digest_jsonable(binding.result_route_ids),
                        source_endpoint_name=request.dispatch.endpoint_name,
                        source_params_digest=request.dispatch.parameters_sha256,
                    ),
                    expected_staging_keys=tuple(frames),
                    replace_existing_chunk=True,
                    receipt_binding=binding,
                    result_route_ids_by_staging_key=source.route_mapping,
                    successor_generation_sha256=generation,
                )
                with (
                    staging.existing_transaction_writer() as staging_writer,
                    successor_planning_semantic_write_transaction(connection) as transaction,
                ):
                    persisted = staging_writer.persist_frame_batches([batch], materialize=True)
                    if len(persisted.replacement_attestations) != len(frames):
                        raise ExactPlanningRuntimeError(
                            "planning staging replacement inventory is incomplete"
                        )
                    for route_scope, semantic_kind, partition in _semantic_specs(request):
                        frame = self._frame_for_scope(request, frames, route_scope)
                        game_ids = None
                        if semantic_kind in {
                            PlanningSemanticKind.PLAYER_CUME_FOUNDATION_GAME_IDS,
                            PlanningSemanticKind.TEAM_CUME_FOUNDATION_GAME_IDS,
                        }:
                            game_ids = _game_date_authority(
                                connection,
                                season=str(partition["season"]),
                                season_type=str(partition["season_type"]),
                            )
                        values = _normalize_semantic_values(
                            semantic_kind,
                            frame,
                            partition=partition,
                            game_date_ids=game_ids,
                        )
                        reason = None
                        if not values:
                            reason = (
                                "no_derived_semantic_values"
                                if semantic_kind is PlanningSemanticKind.AUXILIARY_NO_DERIVED_DATA
                                else (
                                    "foundation_success_empty"
                                    if semantic_kind
                                    in {
                                        PlanningSemanticKind.PLAYER_CUME_FOUNDATION_GAME_IDS,
                                        PlanningSemanticKind.TEAM_CUME_FOUNDATION_GAME_IDS,
                                    }
                                    else "provider_success_empty"
                                )
                            )
                        descriptor = write_successor_planning_semantic_partition(
                            transaction,
                            producing_scope=route_scope,
                            semantic_kind=semantic_kind,
                            partition=partition,
                            values=values,
                            typed_zero_reason_code=reason,
                        )
                        descriptors.append((route_scope, descriptor))
                try:
                    committed = staging.committed_logical_call_receipts(binding)
                    readbacks = tuple(
                        staging.committed_staging_frame_readback(receipt) for receipt in committed
                    )
                except Exception:
                    raise ExactPlanningRuntimeError(
                        "planning committed staging readback failed"
                    ) from None
                try:
                    raw_live_bindings = resources.live_plan_binding_factory(
                        capture_scope,
                        request,
                        snapshot,
                        binding,
                    )
                except Exception:
                    raise ExactPlanningRuntimeError(
                        "planning live-plan authority factory failed"
                    ) from None
                live_plan_bindings = self._validated_live_plan_bindings(
                    raw_live_bindings,
                    scope=capture_scope,
                    source=source,
                )
                if snapshot.issues:
                    try:
                        raw_bundle = materialize_raw_request_incomplete_success_snapshot(
                            snapshot,
                            binding,
                            committed,
                            logical_provider_parameter_binding=parameter_binding,
                            expected_logical_provider_parameter_binding_sha256=(
                                expected_parameter_binding_sha256
                            ),
                        )
                    except Exception:
                        raise ExactPlanningRuntimeError(
                            "planning incomplete raw-request closure failed"
                        ) from None
                else:
                    live_plan = live_plan_bindings[0] if live_plan_bindings else None
                    try:
                        raw_bundle = finalize_raw_request_capture(
                            snapshot,
                            binding,
                            committed,
                            live_plan_authority=(None if live_plan is None else live_plan[0]),
                            expected_live_plan_authority_sha256=(
                                None if live_plan is None else live_plan[1]
                            ),
                            logical_provider_parameter_binding=parameter_binding,
                            expected_logical_provider_parameter_binding_sha256=(
                                expected_parameter_binding_sha256
                            ),
                        )
                    except Exception:
                        raise ExactPlanningRuntimeError(
                            "planning raw-request post-commit closure failed"
                        ) from None
                try:
                    raw_store = resources.raw_authority_store_factory(connection)
                except Exception:
                    raise ExactPlanningRuntimeError(
                        "planning Raw Authority store factory failed"
                    ) from None
                if type(raw_store) is not RawRequestAuthorityStore:
                    raise ExactPlanningRuntimeError(
                        "planning Raw Authority store factory returned a foreign store"
                    )
                try:
                    raw_persistence = raw_store.persist_bundle(raw_bundle)
                except Exception:
                    raise ExactPlanningRuntimeError(
                        "planning Raw Authority persistence failed"
                    ) from None
                if type(raw_persistence) is not RawRequestAuthorityPersistenceReceiptV2:
                    raise ExactPlanningRuntimeError(
                        "planning Raw Authority persistence returned a foreign receipt"
                    )
                try:
                    preparation_runtime = resources.w2_preparation_runtime_factory(capture_scope)
                except Exception:
                    raise ExactPlanningRuntimeError(
                        "planning W2 preparation runtime factory failed"
                    ) from None
                if type(preparation_runtime) is not W2SourceCallPreparationRuntime:
                    raise ExactPlanningRuntimeError(
                        "planning W2 preparation factory returned a foreign runtime"
                    )
                try:
                    candidate = preparation_runtime.prepare(
                        logical_call_binding=binding,
                        raw_authority_persistence_receipt=raw_persistence,
                        expected_raw_authority_persistence_receipt_sha256=(
                            raw_persistence.receipt_sha256
                        ),
                        raw_bundle=raw_bundle,
                        expected_raw_authority_bundle_sha256=raw_bundle.bundle_sha256,
                        committed_staging_readbacks=readbacks,
                        expected_committed_staging_readback_sha256s=tuple(
                            item.readback_receipt_sha256 for item in readbacks
                        ),
                        recorded_static_attempts=source.recorded_static_attempts,
                        live_plan_bindings=live_plan_bindings,
                    )
                except Exception:
                    raise ExactPlanningRuntimeError(
                        "planning W2 source-call preparation failed"
                    ) from None
                try:
                    public_store = resources.public_value_store_factory(connection)
                    operation_store = resources.w2_operation_store_factory(connection)
                except Exception:
                    raise ExactPlanningRuntimeError(
                        "planning W2 persistence store factory failed"
                    ) from None
                if (
                    type(public_store) is not PublicValueAuthorityStore
                    or type(operation_store) is not W2OperationStore
                ):
                    raise ExactPlanningRuntimeError(
                        "planning W2 persistence factory returned a foreign store"
                    )
                try:
                    admission = coordinate_w2_source_call(
                        candidate,
                        public_value_store=public_store,
                        operation_store=operation_store,
                    )
                    exact_admission = W2SourceCallAdmissionV1.from_canonical_bytes(
                        admission.canonical_bytes()
                    )
                except Exception:
                    raise ExactPlanningRuntimeError(
                        "planning W2 source-call persistence failed"
                    ) from None
                if (
                    type(admission) is not W2SourceCallAdmissionV1
                    or exact_admission is admission
                    or exact_admission != admission
                    or admission.logical_call_receipt_sha256 != binding.logical_call_receipt_sha256
                ):
                    raise ExactPlanningRuntimeError("planning W2 admission failed exact replay")
                source_admission = admission
                return (admission,)

            runner = ExtractorRunner(
                self._config.registry,
                self._config.settings,
                atomic_journal,
                rate_limit=self._config.settings.rate_limit,
                capture_contract_factory=session.contract_for,
                raw_request_capture_context_factory=raw_request_context_for,
                call_admission=admit_call,
                conditional_route_admission=admit_conditional_routes,
            )
            try:
                self._config.require_deadline_headroom(stage="planning provider call")
                self._config.require_current_roots()
                self._config.require_current_registry(endpoint_name=request.dispatch.endpoint_name)
                self._config.require_before_provider_authority()
                result = await runner.run_pattern_result(
                    request.dispatch.pattern,
                    [request.dispatch.parameters],
                    entries,
                    persist_chunk_results=persist_results,
                    support_date=as_of.date(),
                    required_route_ids=request.dispatch.staging_route_ids,
                    snapshot_at=as_of,
                )
            finally:
                runner.shutdown()
            if (
                result.eligible_calls != 1
                or result.scheduled_calls != 1
                or result.success_count != 1
                or result.failure_count
                or result.deferred_failure_count
                or result.support_skip_count
                or result.journal_skip_count
                or result.retry_skip_count
                or result.unattempted_eligible_calls
                or result.errors
                or source_binding is None
                or source_admission is None
            ):
                raise ExactPlanningRuntimeError("planning provider call was not exactly complete")
            if len(descriptors) != len(_semantic_specs(request)):
                raise ExactPlanningRuntimeError("planning semantic inventory is incomplete")
            connection.execute("CHECKPOINT")
            crash_injection.after_durable_step(
                crash_injection.DurablePlanningStep.PLANNING_DUCKDB_COMMIT,
                planning_generation_id=request.planning_generation_id,
                dispatch_identity_sha256=request.dispatch.identity_sha256,
            )
            schema_sha256 = successor_planning_database_schema_sha256(connection)
        finally:
            connection.close()
        os.chmod(database_path, 0o600)
        database_artifact = _artifact_source(database_path)
        database_source = PlanningDatabaseSource(
            artifact=database_artifact,
            schema_sha256=schema_sha256,
        )
        self._require_driver_database_bound(
            database_source,
            label="planning driver output database",
        )
        input_sha = (
            None
            if request.input_planning_database is None
            else request.input_planning_database.artifact.sha256
        )
        assert source_binding is not None
        members: list[PlanningMemberSource] = []
        for scope, semantic in descriptors:
            member_id = f"planning-member-v2-{semantic.identity_sha256}"
            envelope = PlanningMemberEnvelope(
                planning_request_sha256=request.request.identity_sha256,
                planning_generation_id=request.planning_generation_id,
                wave_index=request.wave_index,
                producing_scope=scope,
                input_planning_database_sha256=input_sha,
                output_planning_database_sha256=database_artifact.sha256,
                logical_call_receipt_sha256=(source_binding.logical_call_receipt_sha256),
                provider_authority_sha256=request.provider_authority_sha256,
                member_id=member_id,
                semantic=semantic,
            )
            encoded = envelope.canonical_bytes
            path = database_path.parent / f"member-{semantic.identity_sha256}.json"
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                _write_all(descriptor, encoded, label="planning member")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            artifact = _artifact_source(path)
            member = PlanningDataMember(
                member_id=member_id,
                wave_index=request.wave_index,
                producing_scope_sha256=scope.identity_sha256,
                schema_sha256=PlanningMemberEnvelope.schema_sha256,
                content_sha256=artifact.sha256,
                row_count=semantic.value_count,
                semantic=semantic,
                typed_zero_reason_code=semantic.typed_zero_reason_code,
            )
            members.append(
                PlanningMemberSource(
                    member=member,
                    receipt_sha256=source_binding.logical_call_receipt_sha256,
                    artifact=artifact,
                )
            )
        crash_injection.after_durable_step(
            crash_injection.DurablePlanningStep.MEMBER_RECEIPT,
            planning_generation_id=request.planning_generation_id,
            dispatch_identity_sha256=request.dispatch.identity_sha256,
            member_count=len(members),
            logical_call_receipt_sha256=source_binding.logical_call_receipt_sha256,
        )
        return PlanningCallExecution(
            members=tuple(sorted(members, key=lambda item: item.member.identity_sha256)),
            planning_database=database_source,
        )

    async def seal_planning_wave(
        self,
        request: PlanningWaveSealRuntimeRequest,
    ) -> PlanningWaveSeal:
        """Seal or restore one complete committed planning wave."""
        self._config.require_current_roots()
        if not isinstance(request, PlanningWaveSealRuntimeRequest):
            raise ExactPlanningRuntimeError("wave seal request has an invalid type")
        wave_index = request.admission.wave_index
        if tuple(call.sealed_dispatch for call in request.committed_calls) != (
            request.admission.sealed_dispatches
        ):
            raise ExactPlanningRuntimeError("wave seal calls differ from admission")
        envelope_by_member = {envelope.member_id: envelope for envelope in request.member_envelopes}
        member_by_id = {
            member.member.member_id: member.member
            for call in request.committed_calls
            for member in call.members
        }
        if set(envelope_by_member) != set(member_by_id):
            raise ExactPlanningRuntimeError("wave seal envelopes differ from committed members")
        logical_bindings: list[LogicalCallReceiptBinding] = []
        call_bindings: list[PlanningWaveCallBinding] = []
        member_bindings: list[PlanningWaveMemberBinding] = []
        for ordinal, call in enumerate(request.committed_calls):
            if call.ordinal != ordinal or call.wave_index != wave_index:
                raise ExactPlanningRuntimeError("wave seal call ordering differs")
            roots = {member.receipt_sha256 for member in call.members}
            if len(roots) != 1:
                raise ExactPlanningRuntimeError("one planning call has multiple logical roots")
            root = next(iter(roots))
            envelopes = tuple(
                envelope_by_member[member.member.member_id] for member in call.members
            )
            if any(
                envelope.logical_call_receipt_sha256 != root
                or envelope.provider_authority_sha256
                != request.member_envelopes[0].provider_authority_sha256
                or envelope.planning_request_sha256 != request.request.identity_sha256
                or envelope.planning_generation_id != request.planning_generation_id
                or envelope.wave_index != wave_index
                or envelope.member_id != member.member.member_id
                or envelope.semantic != member.member.semantic
                for envelope, member in zip(envelopes, call.members, strict=True)
            ):
                raise ExactPlanningRuntimeError("wave seal envelope authority differs")
            provider = envelopes[0].provider_authority_sha256
            binding = LogicalCallReceiptBinding(
                logical_call_receipt_sha256=root,
                endpoint_name=call.sealed_dispatch.endpoint_name,
                logical_parameters_sha256=call.sealed_dispatch.parameters_sha256,
                provider_authority_sha256=provider,
                result_route_ids=tuple(sorted(call.sealed_dispatch.staging_route_ids)),
            )
            logical_bindings.append(binding)
            member_ids = tuple(sorted(member.member.identity_sha256 for member in call.members))
            call_bindings.append(
                PlanningWaveCallBinding(
                    ordinal=ordinal,
                    sealed_dispatch_identity_sha256=call.sealed_dispatch.identity_sha256,
                    committed_call_identity_sha256=call.identity_sha256,
                    logical_call_receipt_sha256=root,
                    member_identity_sha256s=member_ids,
                )
            )
            member_bindings.extend(
                PlanningWaveMemberBinding(
                    member=member.member,
                    logical_call_receipt_sha256=root,
                )
                for member in call.members
            )

        key = (request.planning_generation_id, wave_index)
        session = self._sessions.get(key)
        scope = self._capture_scope(
            planning_generation_id=request.planning_generation_id,
            wave_index=wave_index,
            source_sha=request.request.source_sha,
            workflow_run_id=request.request.workflow_run_id,
            workflow_run_attempt=request.request.workflow_run_attempt,
        )
        if session is None:
            session = PrivateCaptureSession(
                self._wave_root(request.planning_generation_id, wave_index),
                limits=self._config.capture_limits,
                public_roots=self._config.public_roots,
                scope=scope,
            )
            restored = session.restore_sealed_identity_if_present()
            if restored is None:
                monotonic_now_seconds = self._config.require_deadline_headroom(
                    stage="planning wave seal"
                )
                session.admit(
                    estimated_checkpoint_bytes=self._config.estimated_checkpoint_bytes,
                    monotonic_now_seconds=monotonic_now_seconds,
                    monotonic_deadline_seconds=self._config.monotonic_deadline_seconds,
                )
                session.restore_completed_bindings(logical_bindings)
                private_identity = session.seal()
                crash_injection.after_durable_step(
                    crash_injection.DurablePlanningStep.PRIVATE_SEAL,
                    planning_generation_id=request.planning_generation_id,
                    wave_index=wave_index,
                    private_generation_identity_sha256=private_identity.identity_sha256,
                )
            else:
                private_identity = restored
            self._sessions[key] = session
        elif session.state is CaptureSessionState.ADMITTED:
            # Store commit occurs after execute_planning_call returns.  Therefore
            # only the committed-call inventory supplied to this seal boundary
            # may promote Bronze roots into the completed generation.
            session.restore_completed_bindings(logical_bindings)
            private_identity = session.seal()
            crash_injection.after_durable_step(
                crash_injection.DurablePlanningStep.PRIVATE_SEAL,
                planning_generation_id=request.planning_generation_id,
                wave_index=wave_index,
                private_generation_identity_sha256=private_identity.identity_sha256,
            )
        elif session.state is CaptureSessionState.SEALED:
            private_identity = session.generation_identity
            if private_identity is None:
                raise ExactPlanningRuntimeError("sealed session lacks private identity")
        else:
            raise ExactPlanningRuntimeError("planning capture session cannot be sealed")

        expected_roots = tuple(
            sorted(binding.logical_call_receipt_sha256 for binding in logical_bindings)
        )
        if private_identity.done_call_receipt_sha256s != expected_roots:
            raise ExactPlanningRuntimeError("private generation differs from committed calls")
        requested_scope_ids = request.admission.requested_scope_identity_sha256s
        receipt = PlanningWaveCompletionReceipt(
            planning_request_sha256=request.request.identity_sha256,
            planning_generation_id=request.planning_generation_id,
            wave_index=wave_index,
            parent_wave_identity_sha256=request.admission.parent_wave_identity_sha256,
            wave_admission_identity_sha256=request.admission.identity_sha256,
            sealed_dispatch_identity_sha256s=tuple(
                dispatch.identity_sha256 for dispatch in request.admission.sealed_dispatches
            ),
            committed_calls=tuple(call_bindings),
            requested_scope_identity_sha256s=requested_scope_ids,
            completed_scope_identity_sha256s=requested_scope_ids,
            members=tuple(member_bindings),
            logical_call_bindings=tuple(logical_bindings),
            capture_scope=scope,
            private_generation_identity=private_identity,
            planning_database_sha256=request.planning_database.artifact.sha256,
            planning_database_bytes=request.planning_database.artifact.byte_count,
            planning_database_schema_sha256=request.planning_database.schema_sha256,
        )
        sorted_members = tuple(
            sorted(member_bindings, key=lambda item: item.member_identity_sha256)
        )
        wave = SuccessorPlanningWave(
            wave_index=wave_index,
            parent_wave_identity_sha256=request.admission.parent_wave_identity_sha256,
            requested_scope_identity_sha256s=requested_scope_ids,
            completed_scope_identity_sha256s=requested_scope_ids,
            member_identity_sha256s=tuple(item.member_identity_sha256 for item in sorted_members),
            member_receipt_sha256s=tuple(
                item.logical_call_receipt_sha256 for item in sorted_members
            ),
            private_generation_identity_sha256=private_identity.identity_sha256,
            completion_receipt_sha256=hashlib.sha256(receipt.canonical_bytes).hexdigest(),
        )
        closed_identity = session.close()
        if closed_identity != private_identity:
            raise ExactPlanningRuntimeError("closed capture identity differs from sealed identity")
        self._sessions.pop(key, None)
        return PlanningWaveSeal(
            wave=wave,
            private_generation_identity=private_identity,
            completion_receipt=receipt,
        )


def build_successor_planning_executor(
    *,
    store: SuccessorPlanningStore,
    config: ExactPlanningRuntimeConfig,
    fresh_budget: Callable[[], PlanningStoreBudget],
    planning_work_root: Path,
    expected_planning_work_root_identity: tuple[int, int],
) -> ConcreteSuccessorPlanningExecutor:
    """Construct the production executor from exact store and capture roots."""

    if not isinstance(store, SuccessorPlanningStore):
        raise ExactPlanningRuntimeError("store must be SuccessorPlanningStore")
    if Path(store.root) != config.planning_store_root:
        raise ExactPlanningRuntimeError("store root differs from runtime configuration")
    if not callable(fresh_budget):
        raise ExactPlanningRuntimeError("fresh_budget must be callable")
    runtime = ExtractorPlanningExactCallRuntime(config)
    driver = RequestDrivenSuccessorPlanningDriver(runtime)
    resolver = RetainedBronzePlanningResolver(
        config.capture_base,
        limits=config.capture_limits,
        public_roots=config.public_roots,
        planning_store_root=config.planning_store_root,
    )
    return ConcreteSuccessorPlanningExecutor(
        store=store,
        driver=driver,
        private_generation_resolver=resolver,
        fresh_budget=fresh_budget,
        planning_driver_database_max_bytes=config.planning_driver_database_max_bytes,
        planning_work_root=planning_work_root,
        expected_planning_work_root_identity=expected_planning_work_root_identity,
    )
