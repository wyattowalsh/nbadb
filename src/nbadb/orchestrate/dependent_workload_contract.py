"""Immutable contracts for receipt-bound post-foundation workloads.

The public committed checkpoint is the sole persistence authority.  A compiler may
consume only exact staging chunks whose logical-call, provider, parameter, schema,
content, and row-count receipts are all bound into that checkpoint.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, ClassVar

from nbadb.extract.bronze import canonical_parameters_sha256
from nbadb.orchestrate.checkpoint_contract import CheckpointState, CheckpointTransaction

DEPENDENT_WORKLOAD_SCHEMA_VERSION = 2
DEPENDENT_WORKLOAD_INTEGRATION_STATE = "post_foundation_ready"

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*")
_REASON_RE = re.compile(r"[a-z0-9][a-z0-9_]*")
_SEASON_RE = re.compile(r"([0-9]{4})-([0-9]{2})")


class DependentWorkloadContractError(ValueError):
    """Raised when a dependent workload contract is unsafe or inconsistent."""


class DependentWorkloadInconclusiveError(DependentWorkloadContractError):
    """Raised when foundation evidence cannot support any terminal disposition."""


class DependentWorkloadKind(StrEnum):
    PLAYER_MATCHUP = "player_matchup"
    TEAM_PLAYER = "team_player"
    FIVE_V_FIVE = "five_v_five"


class FoundationAuthorityKind(StrEnum):
    STAGING_CHUNK = "staging_chunk"
    DISCOVERY_GENERATION = "discovery_generation"


class DependentScopeDisposition(StrEnum):
    COMPLETE = "complete"
    TYPED_ZERO = "typed_zero"
    BLOCKED = "blocked"


def canonical_json_bytes(payload: object) -> bytes:
    """Return the single canonical JSON encoding used by every contract digest."""

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def canonical_decimal(value: Decimal) -> str:
    """Encode a finite decimal without exponent or redundant zeroes."""

    if not value.is_finite():
        raise DependentWorkloadContractError("interval time must be finite")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _require_sha256(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise DependentWorkloadContractError(f"{field_name} must be a lowercase SHA-256")
    return value


def _require_token(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _TOKEN_RE.fullmatch(value) is None:
        raise DependentWorkloadContractError(f"{field_name} must be an exact safe token")
    return value


def _require_reason(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _REASON_RE.fullmatch(value) is None:
        raise DependentWorkloadContractError(f"{field_name} must be a stable reason code")
    return value


def _require_positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise DependentWorkloadContractError(f"{field_name} must be a positive integer")
    return value


def _require_nonnegative_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise DependentWorkloadContractError(f"{field_name} must be a nonnegative integer")
    return value


def _require_season(value: object) -> str:
    if not isinstance(value, str) or (match := _SEASON_RE.fullmatch(value)) is None:
        raise DependentWorkloadContractError("season must use exact consecutive YYYY-YY form")
    start = int(match.group(1))
    if int(match.group(2)) != (start + 1) % 100:
        raise DependentWorkloadContractError("season must use exact consecutive YYYY-YY form")
    return value


@dataclass(frozen=True, slots=True)
class FoundationInputReceipt:
    """Exact receipt binding for one persisted foundation result route."""

    authority_kind: FoundationAuthorityKind
    table_name: str
    chunk_id: str
    endpoint_name: str
    logical_call_receipt_sha256: str | None
    discovery_manifest_sha256: str | None
    logical_parameters: tuple[tuple[str, int | str], ...]
    logical_parameters_sha256: str
    provider_authority_sha256: str
    result_route_id: str
    persisted_content_sha256: str
    persisted_schema_sha256: str
    persisted_row_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.authority_kind, FoundationAuthorityKind):
            raise DependentWorkloadContractError("foundation authority kind is invalid")
        _require_token(self.table_name, field_name="table_name")
        _require_sha256(self.chunk_id, field_name="chunk_id")
        _require_token(self.endpoint_name, field_name="endpoint_name")
        if self.authority_kind is FoundationAuthorityKind.STAGING_CHUNK:
            _require_sha256(
                self.logical_call_receipt_sha256,
                field_name="logical_call_receipt_sha256",
            )
            if self.discovery_manifest_sha256 is not None:
                raise DependentWorkloadContractError(
                    "staging-chunk authority cannot carry a discovery manifest"
                )
        else:
            _require_sha256(
                self.discovery_manifest_sha256,
                field_name="discovery_manifest_sha256",
            )
            if self.logical_call_receipt_sha256 is not None:
                raise DependentWorkloadContractError(
                    "discovery-generation authority cannot claim a logical-call receipt"
                )
        parameters = tuple(self.logical_parameters)
        if any(
            not isinstance(item, tuple) or len(item) != 2 or not isinstance(item[0], str)
            for item in parameters
        ):
            raise DependentWorkloadContractError(
                "logical_parameters must contain exact name/value pairs"
            )
        parameter_names = [name for name, _value in parameters]
        if len(parameter_names) != len(set(parameter_names)):
            raise DependentWorkloadContractError("logical_parameters contain duplicate names")
        for name, value in parameters:
            _require_token(name, field_name="logical_parameter_name")
            if isinstance(value, bool) or not isinstance(value, int | str):
                raise DependentWorkloadContractError(
                    "logical parameter values must be integers or strings"
                )
            if isinstance(value, str) and not value:
                raise DependentWorkloadContractError(
                    "logical parameter string values must be nonempty"
                )
        parameters = tuple(sorted(parameters))
        object.__setattr__(self, "logical_parameters", parameters)
        parameter_digest = _require_sha256(
            self.logical_parameters_sha256,
            field_name="logical_parameters_sha256",
        )
        if canonical_parameters_sha256(dict(parameters)) != parameter_digest:
            raise DependentWorkloadContractError(
                "logical parameter digest differs from its public parameter values"
            )
        _require_sha256(
            self.provider_authority_sha256,
            field_name="provider_authority_sha256",
        )
        _require_token(self.result_route_id, field_name="result_route_id")
        try:
            route_endpoint, route_table, raw_index = self.result_route_id.rsplit(":", 2)
            route_index = int(raw_index)
        except (TypeError, ValueError):
            raise DependentWorkloadContractError("result_route_id is malformed") from None
        if (
            route_endpoint != self.endpoint_name
            or route_table != self.table_name
            or route_index < 0
            or raw_index != str(route_index)
        ):
            raise DependentWorkloadContractError(
                "result route differs from its endpoint or staging table"
            )
        _require_sha256(self.persisted_content_sha256, field_name="persisted_content_sha256")
        _require_sha256(self.persisted_schema_sha256, field_name="persisted_schema_sha256")
        _require_nonnegative_int(self.persisted_row_count, field_name="persisted_row_count")
        if (
            self.authority_kind is FoundationAuthorityKind.DISCOVERY_GENERATION
            and self.chunk_id != self.persisted_content_sha256
        ):
            raise DependentWorkloadContractError(
                "discovery generation identity differs from its persisted content digest"
            )

    @property
    def identity_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_kind": self.authority_kind.value,
            "table_name": self.table_name,
            "chunk_id": self.chunk_id,
            "endpoint_name": self.endpoint_name,
            "logical_call_receipt_sha256": self.logical_call_receipt_sha256,
            "discovery_manifest_sha256": self.discovery_manifest_sha256,
            "logical_parameters": [
                {"name": name, "value": value} for name, value in self.logical_parameters
            ],
            "logical_parameters_sha256": self.logical_parameters_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
            "result_route_id": self.result_route_id,
            "persisted_content_sha256": self.persisted_content_sha256,
            "persisted_schema_sha256": self.persisted_schema_sha256,
            "persisted_row_count": self.persisted_row_count,
        }


@dataclass(frozen=True, slots=True)
class FoundationAuthority:
    """All immutable authorities required before a dependent compiler may run."""

    checkpoint_transaction: CheckpointTransaction
    checkpoint_report_sha256: str
    checkpoint_database_sha256: str
    discovery_artifact_id: int
    discovery_artifact_run_id: int
    discovery_artifact_name: str
    discovery_artifact_digest: str
    provider_authority_sha256: str
    source_sha: str
    compiler_implementation_sha256: str
    query_plan_sha256: str
    input_receipts: tuple[FoundationInputReceipt, ...]
    checkpoint_transaction_sha256: str = field(init=False)
    input_receipts_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        transaction = self.checkpoint_transaction
        if not isinstance(transaction, CheckpointTransaction):
            raise DependentWorkloadContractError(
                "checkpoint_transaction must be a CheckpointTransaction"
            )
        if transaction.state is not CheckpointState.COMMITTED:
            raise DependentWorkloadContractError("foundation checkpoint must be committed")
        if transaction.build is None or transaction.receipt is None:
            raise DependentWorkloadContractError(
                "committed foundation checkpoint is missing build or receipt authority"
            )

        report_sha256 = _require_sha256(
            self.checkpoint_report_sha256,
            field_name="checkpoint_report_sha256",
        )
        database_sha256 = _require_sha256(
            self.checkpoint_database_sha256,
            field_name="checkpoint_database_sha256",
        )
        if transaction.build.report_sha256 != report_sha256:
            raise DependentWorkloadContractError(
                "checkpoint report digest differs from committed transaction"
            )
        if transaction.build.database_sha256 != database_sha256:
            raise DependentWorkloadContractError(
                "checkpoint database digest differs from committed transaction"
            )
        if transaction.identity.source_sha != self.source_sha:
            raise DependentWorkloadContractError(
                "semantic source differs from committed checkpoint"
            )

        _require_positive_int(self.discovery_artifact_id, field_name="discovery_artifact_id")
        _require_positive_int(
            self.discovery_artifact_run_id,
            field_name="discovery_artifact_run_id",
        )
        if self.discovery_artifact_run_id != transaction.committed_receipt.artifact_run_id:
            raise DependentWorkloadContractError(
                "discovery artifact owner differs from the committed checkpoint owner"
            )
        expected_discovery_name = (
            f"full-extraction-discovery-artifacts-{transaction.identity.chain_id}"
        )
        if self.discovery_artifact_name != expected_discovery_name:
            raise DependentWorkloadContractError(
                "discovery artifact name differs from the checkpoint chain"
            )
        _require_sha256(
            self.discovery_artifact_digest,
            field_name="discovery_artifact_digest",
        )

        provider_authority_sha256 = _require_sha256(
            self.provider_authority_sha256,
            field_name="provider_authority_sha256",
        )
        _require_sha256(
            self.compiler_implementation_sha256,
            field_name="compiler_implementation_sha256",
        )
        _require_sha256(self.query_plan_sha256, field_name="query_plan_sha256")

        receipts = tuple(self.input_receipts)
        if not receipts:
            raise DependentWorkloadContractError("foundation input receipt inventory is empty")
        if any(not isinstance(receipt, FoundationInputReceipt) for receipt in receipts):
            raise DependentWorkloadContractError(
                "foundation input receipts must be FoundationInputReceipt values"
            )
        receipts = tuple(
            sorted(
                receipts,
                key=lambda receipt: (
                    receipt.table_name,
                    receipt.chunk_id,
                    receipt.identity_sha256,
                ),
            )
        )
        receipt_ids = [receipt.identity_sha256 for receipt in receipts]
        if len(receipt_ids) != len(set(receipt_ids)):
            raise DependentWorkloadContractError("foundation input receipts contain duplicates")
        authority_routes = [
            (
                receipt.authority_kind.value,
                receipt.table_name,
                receipt.result_route_id,
                receipt.logical_call_receipt_sha256 or receipt.discovery_manifest_sha256,
            )
            for receipt in receipts
        ]
        if len(authority_routes) != len(set(authority_routes)):
            raise DependentWorkloadContractError(
                "foundation input receipts conflict for one persisted authority route"
            )
        if any(
            receipt.provider_authority_sha256 != provider_authority_sha256 for receipt in receipts
        ):
            raise DependentWorkloadContractError(
                "foundation input receipt provider authority differs from checkpoint authority"
            )
        object.__setattr__(self, "input_receipts", receipts)
        object.__setattr__(
            self,
            "checkpoint_transaction_sha256",
            canonical_sha256(transaction.to_dict()),
        )
        object.__setattr__(
            self,
            "input_receipts_sha256",
            canonical_sha256([receipt.to_dict() for receipt in receipts]),
        )

    def to_dict(self) -> dict[str, Any]:
        transaction = self.checkpoint_transaction
        return {
            "checkpoint_transaction": transaction.to_dict(),
            "checkpoint_transaction_sha256": self.checkpoint_transaction_sha256,
            "checkpoint_artifact_id": transaction.committed_receipt.artifact_id,
            "checkpoint_artifact_run_id": transaction.committed_receipt.artifact_run_id,
            "checkpoint_artifact_digest": transaction.committed_receipt.artifact_digest,
            "checkpoint_report_sha256": self.checkpoint_report_sha256,
            "checkpoint_database_sha256": self.checkpoint_database_sha256,
            "discovery_artifact_id": self.discovery_artifact_id,
            "discovery_artifact_run_id": self.discovery_artifact_run_id,
            "discovery_artifact_name": self.discovery_artifact_name,
            "discovery_artifact_digest": self.discovery_artifact_digest,
            "provider_authority_sha256": self.provider_authority_sha256,
            "source_sha": self.source_sha,
            "compiler_implementation_sha256": self.compiler_implementation_sha256,
            "query_plan_sha256": self.query_plan_sha256,
            "input_receipts": [receipt.to_dict() for receipt in self.input_receipts],
            "input_receipts_sha256": self.input_receipts_sha256,
        }


@dataclass(frozen=True, slots=True, order=True)
class WorkloadScope:
    season: str
    season_type: str
    game_id: str
    foundation_receipt_sha256: str
    foundation_row_ordinal: int

    def __post_init__(self) -> None:
        _require_season(self.season)
        _require_token(self.season_type.replace(" ", "_"), field_name="season_type")
        _require_token(self.game_id, field_name="game_id")
        _require_sha256(
            self.foundation_receipt_sha256,
            field_name="foundation_receipt_sha256",
        )
        _require_nonnegative_int(
            self.foundation_row_ordinal,
            field_name="foundation_row_ordinal",
        )

    def to_dict(self) -> dict[str, str | int]:
        return {
            "season": self.season,
            "season_type": self.season_type,
            "game_id": self.game_id,
            "foundation_receipt_sha256": self.foundation_receipt_sha256,
            "foundation_row_ordinal": self.foundation_row_ordinal,
        }


@dataclass(frozen=True, slots=True, order=True)
class SourceRowIdentity:
    input_receipt_sha256: str
    row_ordinal: int

    def __post_init__(self) -> None:
        _require_sha256(self.input_receipt_sha256, field_name="input_receipt_sha256")
        _require_nonnegative_int(self.row_ordinal, field_name="row_ordinal")

    def to_dict(self) -> dict[str, str | int]:
        return {
            "input_receipt_sha256": self.input_receipt_sha256,
            "row_ordinal": self.row_ordinal,
        }


@dataclass(frozen=True, slots=True)
class PlayerMatchupOccurrence:
    scope: WorkloadScope
    player_id: int
    player_team_id: int
    vs_player_id: int
    vs_team_id: int
    source_row: SourceRowIdentity

    def __post_init__(self) -> None:
        if not isinstance(self.scope, WorkloadScope):
            raise DependentWorkloadContractError("player matchup scope is invalid")
        for field_name in ("player_id", "player_team_id", "vs_player_id", "vs_team_id"):
            _require_positive_int(getattr(self, field_name), field_name=field_name)
        if self.player_id == self.vs_player_id:
            raise DependentWorkloadContractError("player matchup players must be distinct")
        if self.player_team_id == self.vs_team_id:
            raise DependentWorkloadContractError("player matchup teams must be distinct")
        if not isinstance(self.source_row, SourceRowIdentity):
            raise DependentWorkloadContractError("player matchup source row is invalid")

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "scope": self.scope.to_dict(),
            "player_id": self.player_id,
            "player_team_id": self.player_team_id,
            "vs_player_id": self.vs_player_id,
            "vs_team_id": self.vs_team_id,
            "source_row": self.source_row.to_dict(),
        }

    @property
    def identity_sha256(self) -> str:
        return canonical_sha256(self._identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {"occurrence_sha256": self.identity_sha256, **self._identity_payload()}


@dataclass(frozen=True, slots=True)
class TeamPlayerOccurrence:
    scope: WorkloadScope
    team_id: int
    vs_player_id: int
    vs_team_id: int
    source_row: SourceRowIdentity

    def __post_init__(self) -> None:
        if not isinstance(self.scope, WorkloadScope):
            raise DependentWorkloadContractError("team-player scope is invalid")
        for field_name in ("team_id", "vs_player_id", "vs_team_id"):
            _require_positive_int(getattr(self, field_name), field_name=field_name)
        if self.team_id == self.vs_team_id:
            raise DependentWorkloadContractError("team-player teams must be distinct")
        if not isinstance(self.source_row, SourceRowIdentity):
            raise DependentWorkloadContractError("team-player source row is invalid")

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "scope": self.scope.to_dict(),
            "team_id": self.team_id,
            "vs_player_id": self.vs_player_id,
            "vs_team_id": self.vs_team_id,
            "source_row": self.source_row.to_dict(),
        }

    @property
    def identity_sha256(self) -> str:
        return canonical_sha256(self._identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {"occurrence_sha256": self.identity_sha256, **self._identity_payload()}


@dataclass(frozen=True, slots=True)
class FiveVsFiveOccurrence:
    scope: WorkloadScope
    interval_start: str
    interval_end: str
    team_id: int
    team_player_ids: tuple[int, ...]
    team_side: str
    vs_team_id: int
    vs_player_ids: tuple[int, ...]
    vs_team_side: str
    source_rows: tuple[SourceRowIdentity, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.scope, WorkloadScope):
            raise DependentWorkloadContractError("five-v-five scope is invalid")
        try:
            start = Decimal(self.interval_start)
            end = Decimal(self.interval_end)
        except InvalidOperation as exc:
            raise DependentWorkloadContractError("five-v-five interval is invalid") from exc
        if (
            canonical_decimal(start) != self.interval_start
            or canonical_decimal(end) != self.interval_end
            or start < 0
            or end <= start
        ):
            raise DependentWorkloadContractError("five-v-five interval is invalid")
        _require_positive_int(self.team_id, field_name="team_id")
        _require_positive_int(self.vs_team_id, field_name="vs_team_id")
        if self.team_id == self.vs_team_id:
            raise DependentWorkloadContractError("five-v-five teams must be distinct")
        if (self.team_side, self.vs_team_side) not in {
            ("away", "home"),
            ("home", "away"),
        }:
            raise DependentWorkloadContractError(
                "five-v-five direction must preserve one exact opposing-team orientation"
            )
        for field_name, players in (
            ("team_player_ids", self.team_player_ids),
            ("vs_player_ids", self.vs_player_ids),
        ):
            if len(players) != 5 or tuple(sorted(players)) != players:
                raise DependentWorkloadContractError(
                    f"{field_name} must contain exactly five ordered players"
                )
            if len(set(players)) != 5:
                raise DependentWorkloadContractError(f"{field_name} players must be distinct")
            for player_id in players:
                _require_positive_int(player_id, field_name=field_name)
        if set(self.team_player_ids) & set(self.vs_player_ids):
            raise DependentWorkloadContractError("five-v-five opposing players must not overlap")
        sources = tuple(self.source_rows)
        if any(not isinstance(source, SourceRowIdentity) for source in sources):
            raise DependentWorkloadContractError(
                "five-v-five source rows must be SourceRowIdentity values"
            )
        sources = tuple(sorted(sources))
        if len(sources) != 10 or len(set(sources)) != 10:
            raise DependentWorkloadContractError(
                "five-v-five occurrence must bind exactly ten distinct source rows"
            )
        object.__setattr__(self, "source_rows", sources)

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "scope": self.scope.to_dict(),
            "interval_start": self.interval_start,
            "interval_end": self.interval_end,
            "team_id": self.team_id,
            "team_player_ids": list(self.team_player_ids),
            "team_side": self.team_side,
            "vs_team_id": self.vs_team_id,
            "vs_player_ids": list(self.vs_player_ids),
            "vs_team_side": self.vs_team_side,
            "source_rows": [source.to_dict() for source in self.source_rows],
        }

    @property
    def identity_sha256(self) -> str:
        return canonical_sha256(self._identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {"occurrence_sha256": self.identity_sha256, **self._identity_payload()}


_PARAMETER_NAMES: dict[DependentWorkloadKind, tuple[str, ...]] = {
    DependentWorkloadKind.PLAYER_MATCHUP: (
        "season",
        "season_type",
        "player_id",
        "vs_player_id",
    ),
    DependentWorkloadKind.TEAM_PLAYER: (
        "season",
        "season_type",
        "team_id",
        "vs_player_id",
    ),
    DependentWorkloadKind.FIVE_V_FIVE: (
        "season",
        "season_type",
        "team_id",
        "vs_team_id",
        "player_id1",
        "player_id2",
        "player_id3",
        "player_id4",
        "player_id5",
        "vs_player_id1",
        "vs_player_id2",
        "vs_player_id3",
        "vs_player_id4",
        "vs_player_id5",
    ),
}

_ENDPOINT_NAMES: dict[DependentWorkloadKind, tuple[str, ...]] = {
    DependentWorkloadKind.PLAYER_MATCHUP: ("player_vs_player",),
    DependentWorkloadKind.TEAM_PLAYER: ("team_vs_player",),
    DependentWorkloadKind.FIVE_V_FIVE: (
        "team_and_players_vs",
        "team_and_players_vs_players",
    ),
}


@dataclass(frozen=True, slots=True)
class DependentExecutableUnit:
    kind: DependentWorkloadKind
    parameters: tuple[tuple[str, int | str], ...]
    occurrence_sha256s: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DependentWorkloadKind):
            raise DependentWorkloadContractError("executable workload kind is invalid")
        if tuple(name for name, _value in self.parameters) != _PARAMETER_NAMES[self.kind]:
            raise DependentWorkloadContractError(
                "executable parameters do not match the workload kind"
            )
        values = dict(self.parameters)
        _require_season(values["season"])
        if not isinstance(values["season_type"], str) or not values["season_type"]:
            raise DependentWorkloadContractError("executable season_type is invalid")
        id_values = {
            name: value for name, value in self.parameters if name not in {"season", "season_type"}
        }
        for name, value in id_values.items():
            _require_positive_int(value, field_name=name)
        if self.kind is DependentWorkloadKind.PLAYER_MATCHUP:
            if values["player_id"] == values["vs_player_id"]:
                raise DependentWorkloadContractError("executable player IDs must be distinct")
        elif self.kind is DependentWorkloadKind.FIVE_V_FIVE:
            if values["team_id"] == values["vs_team_id"]:
                raise DependentWorkloadContractError("executable team IDs must be distinct")
            players = tuple(values[f"player_id{index}"] for index in range(1, 6))
            vs_players = tuple(values[f"vs_player_id{index}"] for index in range(1, 6))
            if len(set(players)) != 5 or len(set(vs_players)) != 5:
                raise DependentWorkloadContractError("executable lineup players must be distinct")
            if set(players) & set(vs_players):
                raise DependentWorkloadContractError(
                    "executable opposing lineup players must not overlap"
                )
        occurrences = tuple(sorted(self.occurrence_sha256s))
        if not occurrences or len(occurrences) != len(set(occurrences)):
            raise DependentWorkloadContractError(
                "executable unit must bind unique observed occurrences"
            )
        for occurrence_sha256 in occurrences:
            _require_sha256(occurrence_sha256, field_name="occurrence_sha256")
        object.__setattr__(self, "occurrence_sha256s", occurrences)

    @property
    def identity_sha256(self) -> str:
        return canonical_sha256(
            {
                "kind": self.kind.value,
                "endpoint_names": list(self.endpoint_names),
                "parameters": [list(item) for item in self.parameters],
            }
        )

    @property
    def endpoint_names(self) -> tuple[str, ...]:
        """Every physical endpoint that must execute this observed workload."""

        return _ENDPOINT_NAMES[self.kind]

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_sha256": self.identity_sha256,
            "kind": self.kind.value,
            "endpoint_names": list(self.endpoint_names),
            "parameters": [{"name": name, "value": value} for name, value in self.parameters],
            "occurrence_sha256s": list(self.occurrence_sha256s),
        }


@dataclass(frozen=True, slots=True)
class ScopeDispositionRecord:
    scope: WorkloadScope
    kind: DependentWorkloadKind
    disposition: DependentScopeDisposition
    reason_code: str
    occurrence_count: int
    executable_unit_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.scope, WorkloadScope):
            raise DependentWorkloadContractError("scope disposition scope is invalid")
        if not isinstance(self.kind, DependentWorkloadKind):
            raise DependentWorkloadContractError("scope disposition kind is invalid")
        if not isinstance(self.disposition, DependentScopeDisposition):
            raise DependentWorkloadContractError("scope disposition is invalid")
        _require_reason(self.reason_code, field_name="reason_code")
        _require_nonnegative_int(self.occurrence_count, field_name="occurrence_count")
        _require_nonnegative_int(
            self.executable_unit_count,
            field_name="executable_unit_count",
        )
        has_work = self.occurrence_count > 0 and self.executable_unit_count > 0
        if (self.disposition is DependentScopeDisposition.COMPLETE) != has_work:
            raise DependentWorkloadContractError(
                "scope disposition counts do not match its terminal state"
            )
        if self.disposition is not DependentScopeDisposition.COMPLETE and (
            self.occurrence_count or self.executable_unit_count
        ):
            raise DependentWorkloadContractError(
                "zero or blocked scope cannot contain executable evidence"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope.to_dict(),
            "kind": self.kind.value,
            "disposition": self.disposition.value,
            "reason_code": self.reason_code,
            "occurrence_count": self.occurrence_count,
            "executable_unit_count": self.executable_unit_count,
        }


def _occurrence_parameters(
    occurrence: PlayerMatchupOccurrence | TeamPlayerOccurrence | FiveVsFiveOccurrence,
) -> tuple[tuple[str, int | str], ...]:
    if isinstance(occurrence, PlayerMatchupOccurrence):
        return (
            ("season", occurrence.scope.season),
            ("season_type", occurrence.scope.season_type),
            ("player_id", occurrence.player_id),
            ("vs_player_id", occurrence.vs_player_id),
        )
    if isinstance(occurrence, TeamPlayerOccurrence):
        return (
            ("season", occurrence.scope.season),
            ("season_type", occurrence.scope.season_type),
            ("team_id", occurrence.team_id),
            ("vs_player_id", occurrence.vs_player_id),
        )
    return (
        ("season", occurrence.scope.season),
        ("season_type", occurrence.scope.season_type),
        ("team_id", occurrence.team_id),
        ("vs_team_id", occurrence.vs_team_id),
        *(
            (f"player_id{index}", player_id)
            for index, player_id in enumerate(occurrence.team_player_ids, start=1)
        ),
        *(
            (f"vs_player_id{index}", player_id)
            for index, player_id in enumerate(occurrence.vs_player_ids, start=1)
        ),
    )


@dataclass(frozen=True, slots=True)
class DependentWorkloadBundle:
    """One immutable, content-addressed compilation result.

    The bundle is executable only after its exact committed checkpoint and every
    public foundation receipt have been revalidated by the post-foundation planner.
    """

    authority: FoundationAuthority
    player_matchup_occurrences: tuple[PlayerMatchupOccurrence, ...]
    team_player_occurrences: tuple[TeamPlayerOccurrence, ...]
    five_v_five_occurrences: tuple[FiveVsFiveOccurrence, ...]
    executable_units: tuple[DependentExecutableUnit, ...]
    scope_dispositions: tuple[ScopeDispositionRecord, ...]

    schema_version: ClassVar[int] = DEPENDENT_WORKLOAD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.authority, FoundationAuthority):
            raise DependentWorkloadContractError("dependent workload authority is invalid")
        player_occurrences = tuple(
            sorted(self.player_matchup_occurrences, key=lambda item: item.identity_sha256)
        )
        team_occurrences = tuple(
            sorted(self.team_player_occurrences, key=lambda item: item.identity_sha256)
        )
        lineup_occurrences = tuple(
            sorted(self.five_v_five_occurrences, key=lambda item: item.identity_sha256)
        )
        units = tuple(sorted(self.executable_units, key=lambda item: item.identity_sha256))
        dispositions = tuple(
            sorted(
                self.scope_dispositions,
                key=lambda item: (item.scope, item.kind.value),
            )
        )
        object.__setattr__(self, "player_matchup_occurrences", player_occurrences)
        object.__setattr__(self, "team_player_occurrences", team_occurrences)
        object.__setattr__(self, "five_v_five_occurrences", lineup_occurrences)
        object.__setattr__(self, "executable_units", units)
        object.__setattr__(self, "scope_dispositions", dispositions)
        self._validate_inventory()

    def _validate_inventory(self) -> None:
        occurrences_by_kind = {
            DependentWorkloadKind.PLAYER_MATCHUP: self.player_matchup_occurrences,
            DependentWorkloadKind.TEAM_PLAYER: self.team_player_occurrences,
            DependentWorkloadKind.FIVE_V_FIVE: self.five_v_five_occurrences,
        }
        identities_by_kind: dict[DependentWorkloadKind, set[str]] = {}
        occurrence_scope: dict[str, WorkloadScope] = {}
        occurrence_by_identity: dict[
            str,
            PlayerMatchupOccurrence | TeamPlayerOccurrence | FiveVsFiveOccurrence,
        ] = {}
        for kind, occurrences in occurrences_by_kind.items():
            identities = [occurrence.identity_sha256 for occurrence in occurrences]
            if len(identities) != len(set(identities)):
                raise DependentWorkloadContractError(
                    f"{kind.value} occurrence inventory contains duplicates"
                )
            identities_by_kind[kind] = set(identities)
            occurrence_scope.update(
                {occurrence.identity_sha256: occurrence.scope for occurrence in occurrences}
            )
            occurrence_by_identity.update(
                {occurrence.identity_sha256: occurrence for occurrence in occurrences}
            )

        lineup_ids = identities_by_kind[DependentWorkloadKind.FIVE_V_FIVE]
        for occurrence in self.five_v_five_occurrences:
            reverse = FiveVsFiveOccurrence(
                scope=occurrence.scope,
                interval_start=occurrence.interval_start,
                interval_end=occurrence.interval_end,
                team_id=occurrence.vs_team_id,
                team_player_ids=occurrence.vs_player_ids,
                team_side=occurrence.vs_team_side,
                vs_team_id=occurrence.team_id,
                vs_player_ids=occurrence.team_player_ids,
                vs_team_side=occurrence.team_side,
                source_rows=occurrence.source_rows,
            )
            if reverse.identity_sha256 not in lineup_ids:
                raise DependentWorkloadContractError(
                    "five-v-five occurrence inventory is missing its exact reverse direction"
                )

        unit_ids = [unit.identity_sha256 for unit in self.executable_units]
        if len(unit_ids) != len(set(unit_ids)):
            raise DependentWorkloadContractError("executable unit inventory contains duplicates")
        reference_counts: dict[str, int] = {}
        units_by_scope_kind: dict[tuple[WorkloadScope, DependentWorkloadKind], set[str]] = {}
        for unit in self.executable_units:
            allowed = identities_by_kind[unit.kind]
            if any(value not in allowed for value in unit.occurrence_sha256s):
                raise DependentWorkloadContractError(
                    "executable unit references an occurrence of the wrong kind"
                )
            for occurrence_sha256 in unit.occurrence_sha256s:
                if unit.parameters != _occurrence_parameters(
                    occurrence_by_identity[occurrence_sha256]
                ):
                    raise DependentWorkloadContractError(
                        "executable unit parameters differ from their observed occurrence"
                    )
                reference_counts[occurrence_sha256] = reference_counts.get(occurrence_sha256, 0) + 1
                key = (occurrence_scope[occurrence_sha256], unit.kind)
                units_by_scope_kind.setdefault(key, set()).add(unit.identity_sha256)
        all_occurrence_ids = set().union(*identities_by_kind.values())
        if set(reference_counts) != all_occurrence_ids or any(
            count != 1 for count in reference_counts.values()
        ):
            raise DependentWorkloadContractError(
                "every observed occurrence must belong to exactly one executable unit"
            )

        disposition_by_key: dict[
            tuple[WorkloadScope, DependentWorkloadKind], ScopeDispositionRecord
        ] = {}
        for disposition in self.scope_dispositions:
            key = (disposition.scope, disposition.kind)
            if key in disposition_by_key:
                raise DependentWorkloadContractError("scope dispositions contain duplicates")
            disposition_by_key[key] = disposition
        for kind, occurrences in occurrences_by_kind.items():
            scopes = {occurrence.scope for occurrence in occurrences}
            for scope in scopes:
                key = (scope, kind)
                disposition = disposition_by_key.get(key)
                occurrence_count = sum(occurrence.scope == scope for occurrence in occurrences)
                unit_count = len(units_by_scope_kind.get(key, set()))
                if (
                    disposition is None
                    or disposition.disposition is not DependentScopeDisposition.COMPLETE
                    or disposition.occurrence_count != occurrence_count
                    or disposition.executable_unit_count != unit_count
                ):
                    raise DependentWorkloadContractError(
                        "complete scope disposition does not match compiled evidence"
                    )
        for key, disposition in disposition_by_key.items():
            kind_occurrences = occurrences_by_kind[disposition.kind]
            actual_occurrences = sum(
                occurrence.scope == disposition.scope for occurrence in kind_occurrences
            )
            actual_units = len(units_by_scope_kind.get(key, set()))
            if (
                disposition.occurrence_count != actual_occurrences
                or disposition.executable_unit_count != actual_units
            ):
                raise DependentWorkloadContractError(
                    "scope disposition inventory does not match compiled evidence"
                )

    def to_payload(self) -> dict[str, Any]:
        occurrence_payloads = {
            DependentWorkloadKind.PLAYER_MATCHUP.value: [
                occurrence.to_dict() for occurrence in self.player_matchup_occurrences
            ],
            DependentWorkloadKind.TEAM_PLAYER.value: [
                occurrence.to_dict() for occurrence in self.team_player_occurrences
            ],
            DependentWorkloadKind.FIVE_V_FIVE.value: [
                occurrence.to_dict() for occurrence in self.five_v_five_occurrences
            ],
        }
        unit_payloads = [unit.to_dict() for unit in self.executable_units]
        disposition_payloads = [item.to_dict() for item in self.scope_dispositions]
        return {
            "schema_version": self.schema_version,
            "kind": "dependent_workload_bundle",
            "integration_state": DEPENDENT_WORKLOAD_INTEGRATION_STATE,
            "authority": self.authority.to_dict(),
            "observed_occurrences": occurrence_payloads,
            "executable_units": unit_payloads,
            "scope_dispositions": disposition_payloads,
            "inventory": {
                "player_matchup_occurrence_count": len(self.player_matchup_occurrences),
                "team_player_occurrence_count": len(self.team_player_occurrences),
                "five_v_five_occurrence_count": len(self.five_v_five_occurrences),
                "executable_unit_count": len(self.executable_units),
                "scope_disposition_count": len(self.scope_dispositions),
                "occurrences_sha256": canonical_sha256(occurrence_payloads),
                "executable_units_sha256": canonical_sha256(unit_payloads),
                "scope_dispositions_sha256": canonical_sha256(disposition_payloads),
            },
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_payload())

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()

    @property
    def generation_basename(self) -> str:
        return f"dependent-workload.{self.content_sha256}.json"
