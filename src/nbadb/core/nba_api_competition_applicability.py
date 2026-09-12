"""Offline competition-period applicability authority for ``nba-api==1.11.4``.

This module joins three deliberately disjoint evidence layers:

* official-source competition existence, which may only gate a future probe;
* the pinned package/request declarations, which prove a finite request axis;
* provider availability, which remains unknown until a receipt-bound probe runs.

The compiler never sends a provider request.  In particular, a declared
``LeagueID`` value, its default, and a competition's historical existence are
not treated as evidence that any endpoint supports or returns data for that
competition.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import TYPE_CHECKING, Final, Literal, cast

if TYPE_CHECKING:
    from pathlib import Path

from nbadb.core.nba_api_competition import pinned_competition_authority
from nbadb.core.nba_api_competition_occurrences import (
    COMPETITION_OCCURRENCE_RESOURCE,
    REQUEST_SURFACE_RESOURCE,
    CompetitionOccurrenceAuthority,
    pinned_competition_occurrence_authority,
)

COMPETITION_APPLICABILITY_SCHEMA_VERSION: Final = 1
COMPETITION_APPLICABILITY_RESOURCE: Final = "nba_api_competition_applicability_v1_11_4.json"

_PACKAGED_PROVENANCE_ROOT: Final = (
    "provenance",
    "nba_api_v1_11_4",
    "competition_applicability",
)
_EXISTENCE_SOURCE: Final = (
    "artifacts/assurance/complete-nba-api-sink/A1.2c/source-inputs/"
    "competition-existence-evidence.json"
)
_SUPPORT_SOURCE: Final = (
    "artifacts/assurance/complete-nba-api-sink/A1.2c/source-inputs/endpoint-support-evidence.json"
)
_SOURCE_REVIEW: Final = (
    "artifacts/assurance/complete-nba-api-sink/A1.2c/source-inputs/source-review.json"
)
_HISTORICAL_TASK_PACKET: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.2c.json"
)
_EXPECTED_HISTORICAL_TASK_PACKET_SHA256: Final = (
    "d2f668cd0627562508849423c5df5d8e0e120a2fecc270a44699c9fe4458bf91"
)
_EXPECTED_AUTHORITY_INPUTS_SHA256: Final = (
    "130c673ae6442f99cb5d94f243164b5a0b2d84211ea1c999423bbe6a51622d5f"
)
_EXPECTED_CHECKED_AUTHORITIES_SHA256: Final = (
    "4fb2c5003de66ad0a2a94da7c043370a9f6fe2ad1e718df54ec7dacacb77b138"
)
_HISTORICAL_SUCCESSOR_ROWS: Final = (
    {
        "path": "src/nbadb/core/nba_api_request_surface.py",
        "sha256": "ff5f5bc589876a5b624f93692f8a43021cf3a2465a9cdd18475c3497dab0fc96",
    },
    {
        "path": "src/nbadb/core/nba_api_request_surface_verifier.py",
        "sha256": "e85960d3577daf967136ef31f519ea03f27c849d58e1450ee86ab88cf5959308",
    },
    {
        "path": "src/nbadb/contracts/nba_api_request_surface_v1_11_4.json",
        "sha256": "c5b1de0b1e6e05541eec90df9c92ce3ca9e3c1cae490fe6723410137f947e608",
    },
    {
        "path": "src/nbadb/contracts/nba_api_competition_occurrences_v1_11_4.json",
        "sha256": "28f72468be47dce5b13429e43140f96277422892ee8dc21ab723ef1c606bc700",
    },
)
_EXPECTED_HISTORICAL_SUCCESSOR_ROWS_SHA256: Final = (
    "a94f22cba94539250b6a1e1c8be199dcf903b102f5290ee5ed4ece343bfcac90"
)
_EXPECTED_HISTORICAL_SUCCESSOR_PATHS_SHA256: Final = (
    "99bd793926effc6edaa01c8796c3016410d45040a54e83ff881359f4055f782b"
)
_EXPECTED_CURRENT_REQUEST_RESOURCE_SHA256: Final = (
    "3082def2aa92b35d55107f5ce8eaf2ffa0532a0e649899d0f1180979f6144981"
)
_EXPECTED_CURRENT_REQUEST_PAYLOAD_SHA256: Final = (
    "b310313f41cf97cf1b8f55e01bbe95868532f3008527bf5265a985628eca9052"
)
_EXPECTED_CURRENT_REQUEST_SURFACE_SHA256: Final = (
    "ef6195829a9f1dad9f847094b79e88fae24dffc5c4df18e3d3e972f347f83733"
)
_EXPECTED_CURRENT_OCCURRENCE_RESOURCE_SHA256: Final = (
    "8bd3365806aa3118e3ec265a6e70647390b54aab203050805c59b6e6d9bce459"
)
_EXPECTED_CURRENT_OCCURRENCE_AUTHORITY_SHA256: Final = (
    "4ef38c7ee185ff10fea4b4de611648af1b30be04f700399549233e809cd53935"
)
_EXPECTED_CURRENT_OCCURRENCE_PAYLOAD_SHA256: Final = (
    "ed06098b67f31e19eca8d9d1e51b25d03681c3d7c0ecfae4b83e84dd7642f179"
)
_EXPECTED_SOURCE_SHA256: Final = {
    _EXISTENCE_SOURCE: "876f79c748faa1f477dee8f15071d1799ad423d7e3b32e5b38e7c56cb34ccfa6",
    _SUPPORT_SOURCE: "6db164143c588092acbd2c8497b068a770ff5a39501d1c05e28ef638b6fb6cfb",
    _SOURCE_REVIEW: "accdd459d72d58be7c8b83f9c17e2e2086c058f3112b7714f4f0ea33e588f589",
}
_EXPECTED_SOURCE_AUTHORITY_SHA256: Final = {
    _EXISTENCE_SOURCE: "27f4a84f9ff26caaa8b07234975dc645c386742e6bfbb43522f743d3b31998ad",
    _SUPPORT_SOURCE: "cfaf6b690e9d27c562813df964db05ed945f8430a8a395255643225247ddb7fd",
    _SOURCE_REVIEW: "d626977d4299847eabf5fe84b74551257fdb6552d64bf4fead93380b04749429",
}
_EXPECTED_SOURCE_PAYLOAD_SHA256: Final = {
    _EXISTENCE_SOURCE: "ff113ddb858aa78ea23c3c63fe79dfdb67e548156d26c2db57cae01d7669bc5b",
    _SUPPORT_SOURCE: "82a959b811e5f12cbecef7302a1c003ef2af79fd3cc2584a0420523f2ccc235c",
    _SOURCE_REVIEW: "706b6196787cca666350fa013e3b3a3fb2ae94e5ef0b7d3c1530a1e14d8c1d57",
}

_LEAGUE_IDS: Final = ("00", "01", "10", "15", "20")
_TEMPORAL_SHAPES: Final = frozenset(
    {
        "explicit_season",
        "participant_season_axis",
        "season_type_only",
        "date_or_date_range_only",
        "no_temporal_parameter",
    }
)
_TEMPORAL_SHAPE_COUNTS: Final = {
    "date_or_date_range_only": 3,
    "explicit_season": 96,
    "no_temporal_parameter": 7,
    "participant_season_axis": 2,
    "season_type_only": 4,
}
_ALIAS_TEMPORAL_SHAPE_COUNTS: Final = {
    "date_or_date_range_only": 3,
    "explicit_season": 110,
    "no_temporal_parameter": 7,
    "participant_season_axis": 2,
    "season_type_only": 5,
}
_NON_TEMPORAL_ENDPOINTS: Final = frozenset(
    {
        "CommonPlayerInfo",
        "CommonTeamYears",
        "FranchiseHistory",
        "FranchiseLeaders",
        "GameRotation",
        "PlayerCareerStats",
        "PlayerProfileV2",
    }
)
_SEASON_TYPE_ONLY_ENDPOINTS: Final = frozenset(
    {
        "AllTimeLeadersGrids",
        "FranchisePlayers",
        "PlayerNextNGames",
        "TeamYearByYearStats",
    }
)
_DATE_ONLY_ENDPOINTS: Final = frozenset({"ScoreboardV2", "ScoreboardV3", "VideoStatus"})
_GL_ALUM_ENDPOINT: Final = "GLAlumBoxScoreSimilarityScore"
_GL_ALUM_BINDINGS: Final = {
    "parameter:stats:GLAlumBoxScoreSimilarityScore:0002:person1_league_id": (
        "parameter:stats:GLAlumBoxScoreSimilarityScore:0003:person1_season_year",
        "parameter:stats:GLAlumBoxScoreSimilarityScore:0004:person1_season_type",
    ),
    "parameter:stats:GLAlumBoxScoreSimilarityScore:0005:person2_league_id": (
        "parameter:stats:GLAlumBoxScoreSimilarityScore:0006:person2_season_year",
        "parameter:stats:GLAlumBoxScoreSimilarityScore:0007:person2_season_type",
    ),
}
_EVIDENCE_LAYERS: Final = {
    "competition_existence": (
        "official-source native-period existence gates probe eligibility only"
    ),
    "endpoint_request_contract_support": (
        "pinned declared axes are not endpoint-specific support evidence"
    ),
    "provider_availability": (
        "provider availability remains unknown until later receipt-bound probing"
    ),
}
_DECLARED_AXIS_STATUS: Final = "declared_by_pinned_package_request_contract"
_DECLARED_AXIS_EVIDENCE_KIND: Final = "pinned_package_request_contract"
_ENDPOINT_SUPPORT_STATUS: Final = "unknown_no_independent_endpoint_specific_source"
_ENDPOINT_SUPPORT_EVIDENCE_KIND: Final = "none"
_PROVIDER_AVAILABILITY_STATUS: Final = "unknown"
_PROBE_DISPOSITION: Final = "probe_required"
_SHA256_RE = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)
_SEASON_RE = re.compile(r"([0-9]{4})-([0-9]{2})", flags=re.ASCII)

NativePeriod = str | int
TemporalShape = Literal[
    "explicit_season",
    "participant_season_axis",
    "season_type_only",
    "date_or_date_range_only",
    "no_temporal_parameter",
]
CellKind = Literal["parameter_axis", "alias_role"]


class NbaApiCompetitionApplicabilityError(ValueError):
    """The offline competition-applicability authority is invalid."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NbaApiCompetitionApplicabilityError(
            "competition applicability is not canonical JSON"
        ) from exc


def _pretty_bytes(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NbaApiCompetitionApplicabilityError(
            "competition source evidence is not canonical JSON"
        ) from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise NbaApiCompetitionApplicabilityError(f"{field} must be a canonical SHA-256")
    return value


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise NbaApiCompetitionApplicabilityError(
                f"competition applicability contains duplicate object key: {key}"
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise NbaApiCompetitionApplicabilityError(
        f"competition applicability contains non-finite JSON constant: {value}"
    )


def _strict_json(raw: bytes, *, label: str, pretty: bool) -> dict[str, object]:
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except NbaApiCompetitionApplicabilityError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NbaApiCompetitionApplicabilityError(f"{label} cannot be decoded") from exc
    expected = _pretty_bytes(payload) if pretty else _canonical_bytes(payload) + b"\n"
    if not isinstance(payload, dict) or raw != expected:
        raise NbaApiCompetitionApplicabilityError(f"{label} bytes are not canonical JSON")
    return cast("dict[str, object]", payload)


def _read_packaged_provenance(relative_path: str) -> bytes:
    if relative_path not in {
        _EXISTENCE_SOURCE,
        _SUPPORT_SOURCE,
        _SOURCE_REVIEW,
        _HISTORICAL_TASK_PACKET,
    }:
        raise NbaApiCompetitionApplicabilityError(
            f"applicability source has no packaged authority: {relative_path}"
        )
    try:
        return (
            resources.files("nbadb.contracts")
            .joinpath(*_PACKAGED_PROVENANCE_ROOT, relative_path.rsplit("/", 1)[-1])
            .read_bytes()
        )
    except (AttributeError, OSError) as exc:
        raise NbaApiCompetitionApplicabilityError(
            f"packaged applicability source cannot be read: {relative_path}"
        ) from exc


@lru_cache(maxsize=1)
def _historical_task_packet_inputs() -> tuple[dict[str, str], ...]:
    raw = _read_packaged_provenance(_HISTORICAL_TASK_PACKET)
    if hashlib.sha256(raw).hexdigest() != _EXPECTED_HISTORICAL_TASK_PACKET_SHA256:
        raise NbaApiCompetitionApplicabilityError("historical A1.2c task packet drifted")
    packet = _strict_json(raw, label=_HISTORICAL_TASK_PACKET, pretty=True)
    if packet.get("schema") != "TaskPacketV1" or packet.get("task_id") != "A1.2c":
        raise NbaApiCompetitionApplicabilityError(
            "historical A1.2c task packet identity is invalid"
        )
    raw_inputs = packet.get("immutable_inputs")
    if type(raw_inputs) is not list or len(raw_inputs) != 27:
        raise NbaApiCompetitionApplicabilityError(
            "historical A1.2c immutable input inventory is incomplete"
        )
    inputs: list[dict[str, str]] = []
    for raw_row in raw_inputs:
        if type(raw_row) is not dict or tuple(raw_row) != ("path", "sha256"):
            raise NbaApiCompetitionApplicabilityError(
                "historical A1.2c immutable input row is not exact"
            )
        relative = raw_row.get("path")
        sha256 = raw_row.get("sha256")
        if type(relative) is not str or not relative:
            raise NbaApiCompetitionApplicabilityError(
                "historical A1.2c immutable input path is invalid"
            )
        inputs.append(
            {
                "path": relative,
                "sha256": _require_digest(sha256, "historical immutable input sha256"),
            }
        )
    if any(sum(candidate["path"] == row["path"] for candidate in inputs) != 1 for row in inputs):
        raise NbaApiCompetitionApplicabilityError(
            "historical A1.2c immutable input paths are not unique"
        )

    historical_rows = [dict(row) for row in _HISTORICAL_SUCCESSOR_ROWS]
    historical_paths = [row["path"] for row in historical_rows]
    if (
        _digest(historical_rows) != _EXPECTED_HISTORICAL_SUCCESSOR_ROWS_SHA256
        or _digest(historical_paths) != _EXPECTED_HISTORICAL_SUCCESSOR_PATHS_SHA256
    ):
        raise NbaApiCompetitionApplicabilityError(
            "historical A1.2c successor row commitment is invalid"
        )
    indices: list[int] = []
    for historical_row in historical_rows:
        if inputs.count(historical_row) != 1:
            raise NbaApiCompetitionApplicabilityError(
                "historical A1.2c successor row is not uniquely packet-bound"
            )
        indices.append(inputs.index(historical_row))
    if indices != sorted(indices):
        raise NbaApiCompetitionApplicabilityError(
            "historical A1.2c successor rows are out of order"
        )
    return tuple(inputs)


def _checked_current_resource(
    resource: str,
    *,
    resource_sha256: str,
    payload_sha256: str,
) -> dict[str, object]:
    try:
        raw = resources.files("nbadb.contracts").joinpath(resource).read_bytes()
    except (AttributeError, OSError) as exc:
        raise NbaApiCompetitionApplicabilityError(
            f"current checked resource cannot be read: {resource}"
        ) from exc
    if hashlib.sha256(raw).hexdigest() != resource_sha256:
        raise NbaApiCompetitionApplicabilityError(f"current checked resource drifted: {resource}")
    payload = _strict_json(raw, label=resource, pretty=False)
    body = dict(payload)
    supplied = body.pop("payload_sha256", None)
    if _require_digest(
        supplied, f"{resource} payload_sha256"
    ) != payload_sha256 or supplied != _digest(body):
        raise NbaApiCompetitionApplicabilityError(
            f"current checked resource payload digest is invalid: {resource}"
        )
    return payload


def _current_request_surface_sha256(
    occurrence: CompetitionOccurrenceAuthority,
) -> str:
    request = _checked_current_resource(
        REQUEST_SURFACE_RESOURCE,
        resource_sha256=_EXPECTED_CURRENT_REQUEST_RESOURCE_SHA256,
        payload_sha256=_EXPECTED_CURRENT_REQUEST_PAYLOAD_SHA256,
    )
    occurrence_payload = _checked_current_resource(
        COMPETITION_OCCURRENCE_RESOURCE,
        resource_sha256=_EXPECTED_CURRENT_OCCURRENCE_RESOURCE_SHA256,
        payload_sha256=_EXPECTED_CURRENT_OCCURRENCE_PAYLOAD_SHA256,
    )
    if (
        request.get("kind") != "nbadb_pinned_nba_api_request_surface"
        or request.get("schema_version") != 3
        or request.get("surface_sha256") != _EXPECTED_CURRENT_REQUEST_SURFACE_SHA256
    ):
        raise NbaApiCompetitionApplicabilityError("current request-surface identity is invalid")
    expected_upstream = {
        "payload_sha256": _EXPECTED_CURRENT_REQUEST_PAYLOAD_SHA256,
        "resource": REQUEST_SURFACE_RESOURCE,
        "resource_sha256": _EXPECTED_CURRENT_REQUEST_RESOURCE_SHA256,
        "surface_sha256": _EXPECTED_CURRENT_REQUEST_SURFACE_SHA256,
    }
    if (
        occurrence_payload.get("kind") != "nbadb_nba_api_competition_occurrence_authority"
        or occurrence_payload.get("schema_version") != 1
        or occurrence_payload.get("authority_sha256")
        != _EXPECTED_CURRENT_OCCURRENCE_AUTHORITY_SHA256
        or occurrence_payload.get("upstream_request_surface") != expected_upstream
        or occurrence.authority_sha256 != _EXPECTED_CURRENT_OCCURRENCE_AUTHORITY_SHA256
        or occurrence.request_surface_resource_sha256 != _EXPECTED_CURRENT_REQUEST_RESOURCE_SHA256
        or occurrence.request_surface_payload_sha256 != _EXPECTED_CURRENT_REQUEST_PAYLOAD_SHA256
        or occurrence.request_surface_sha256 != _EXPECTED_CURRENT_REQUEST_SURFACE_SHA256
    ):
        raise NbaApiCompetitionApplicabilityError(
            "current competition-occurrence request binding is invalid"
        )
    return cast("str", expected_upstream["surface_sha256"])


def _source_payload(relative_path: str) -> tuple[bytes, dict[str, object]]:
    raw = _read_packaged_provenance(relative_path)
    observed = hashlib.sha256(raw).hexdigest()
    if observed != _EXPECTED_SOURCE_SHA256[relative_path]:
        raise NbaApiCompetitionApplicabilityError(
            f"required applicability source hash drifted: {relative_path}"
        )
    payload = _strict_json(raw, label=relative_path, pretty=True)
    body = dict(payload)
    payload_sha256 = body.pop("payload_sha256", None)
    if _require_digest(
        payload_sha256, f"{relative_path} payload_sha256"
    ) != _EXPECTED_SOURCE_PAYLOAD_SHA256[relative_path] or payload_sha256 != _digest(body):
        raise NbaApiCompetitionApplicabilityError(
            f"required applicability source payload digest is invalid: {relative_path}"
        )
    if (
        _require_digest(payload.get("authority_sha256"), "authority_sha256")
        != _EXPECTED_SOURCE_AUTHORITY_SHA256[relative_path]
    ):
        raise NbaApiCompetitionApplicabilityError(
            f"required applicability source authority drifted: {relative_path}"
        )
    return raw, payload


def _season_index(value: str) -> int:
    match = _SEASON_RE.fullmatch(value)
    if match is None:
        raise NbaApiCompetitionApplicabilityError(
            "season-label periods must use exact ASCII consecutive YYYY-YY"
        )
    start = int(match.group(1))
    if int(match.group(2)) != (start + 1) % 100:
        raise NbaApiCompetitionApplicabilityError(
            "season-label periods must use exact ASCII consecutive YYYY-YY"
        )
    return start


def _native_period_index(value: NativePeriod, native_period_type: str) -> int:
    if native_period_type == "season_label":
        if not isinstance(value, str):
            raise NbaApiCompetitionApplicabilityError(
                "season-label competition requires a native season string"
            )
        return _season_index(value)
    if native_period_type in {"calendar_year", "event_year"}:
        if isinstance(value, bool) or not isinstance(value, int):
            raise NbaApiCompetitionApplicabilityError(
                "non-NBA calendar/event competition requires its native integer year"
            )
        return value
    raise NbaApiCompetitionApplicabilityError("unknown native competition period type")


@dataclass(frozen=True, slots=True, order=True)
class CompetitionExistenceInterval:
    """One official-source-backed native-period existence interval."""

    league_id: str
    symbol: str
    native_period_type: str
    start: NativePeriod
    end: NativePeriod
    status: str
    explicit_gaps: tuple[NativePeriod, ...]
    planned_future_periods: tuple[NativePeriod, ...]
    source_ids: tuple[str, ...]
    evidence_scope: str = "competition_existence_only"

    def __post_init__(self) -> None:
        if self.league_id not in _LEAGUE_IDS or not self.symbol:
            raise NbaApiCompetitionApplicabilityError("competition existence identity is invalid")
        if self.native_period_type not in {"season_label", "calendar_year", "event_year"}:
            raise NbaApiCompetitionApplicabilityError(
                "competition existence native period type is invalid"
            )
        if self.status not in {
            "confirmed_eligibility",
            "confirmed_eligibility_with_explicit_gaps",
        }:
            raise NbaApiCompetitionApplicabilityError(
                "competition existence interval is not confirmed eligibility"
            )
        if self.evidence_scope != "competition_existence_only":
            raise NbaApiCompetitionApplicabilityError(
                "endpoint support cannot be used as competition existence evidence"
            )
        start = _native_period_index(self.start, self.native_period_type)
        end = _native_period_index(self.end, self.native_period_type)
        if start > end:
            raise NbaApiCompetitionApplicabilityError("competition existence interval is reversed")
        gap_indexes = tuple(
            _native_period_index(item, self.native_period_type) for item in self.explicit_gaps
        )
        if len(gap_indexes) != len(set(gap_indexes)) or any(
            item < start or item > end for item in gap_indexes
        ):
            raise NbaApiCompetitionApplicabilityError(
                "competition existence gaps are duplicate or outside the interval"
            )
        if bool(gap_indexes) != (self.status == "confirmed_eligibility_with_explicit_gaps"):
            raise NbaApiCompetitionApplicabilityError(
                "competition existence gap status is inconsistent"
            )
        planned_indexes = tuple(
            _native_period_index(item, self.native_period_type)
            for item in self.planned_future_periods
        )
        if len(planned_indexes) != len(set(planned_indexes)) or any(
            item <= end for item in planned_indexes
        ):
            raise NbaApiCompetitionApplicabilityError(
                "planned future periods overlap confirmed eligibility"
            )
        if not self.source_ids or self.source_ids != tuple(sorted(set(self.source_ids))):
            raise NbaApiCompetitionApplicabilityError(
                "competition existence source IDs must be sorted and unique"
            )

    def contains(self, period: NativePeriod) -> bool:
        candidate = _native_period_index(period, self.native_period_type)
        start = _native_period_index(self.start, self.native_period_type)
        end = _native_period_index(self.end, self.native_period_type)
        gaps = {_native_period_index(item, self.native_period_type) for item in self.explicit_gaps}
        return start <= candidate <= end and candidate not in gaps

    def to_dict(self) -> dict[str, object]:
        return {
            "end": self.end,
            "evidence_scope": self.evidence_scope,
            "explicit_gaps": list(self.explicit_gaps),
            "league_id": self.league_id,
            "native_period_type": self.native_period_type,
            "planned_future_periods": list(self.planned_future_periods),
            "source_ids": list(self.source_ids),
            "start": self.start,
            "status": self.status,
            "symbol": self.symbol,
        }


@dataclass(frozen=True, slots=True, order=True)
class EndpointCompetitionSupport:
    """One endpoint/competition request-axis cell, not a support claim."""

    provider_endpoint_id: str
    league_id: str
    symbol: str
    provider_occurrence_ids: tuple[str, ...]
    temporal_shape: TemporalShape
    native_period_type: str
    declared_axis_status: str = _DECLARED_AXIS_STATUS
    declared_axis_evidence_kind: str = _DECLARED_AXIS_EVIDENCE_KIND
    endpoint_support_status: str = _ENDPOINT_SUPPORT_STATUS
    endpoint_support_evidence_kind: str = _ENDPOINT_SUPPORT_EVIDENCE_KIND
    provider_availability_status: str = _PROVIDER_AVAILABILITY_STATUS
    probe_disposition: str = _PROBE_DISPOSITION

    def __post_init__(self) -> None:
        _validate_cell_semantics(
            self.declared_axis_status,
            self.declared_axis_evidence_kind,
            self.endpoint_support_status,
            self.endpoint_support_evidence_kind,
            self.provider_availability_status,
            self.probe_disposition,
        )
        if (
            not self.provider_endpoint_id
            or self.league_id not in _LEAGUE_IDS
            or not self.symbol
            or not self.provider_occurrence_ids
            or self.provider_occurrence_ids != tuple(sorted(set(self.provider_occurrence_ids)))
            or self.temporal_shape not in _TEMPORAL_SHAPES
            or self.native_period_type not in {"season_label", "calendar_year", "event_year"}
        ):
            raise NbaApiCompetitionApplicabilityError(
                "endpoint competition support cell is invalid"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "declared_axis_evidence_kind": self.declared_axis_evidence_kind,
            "declared_axis_status": self.declared_axis_status,
            "endpoint_support_evidence_kind": self.endpoint_support_evidence_kind,
            "endpoint_support_status": self.endpoint_support_status,
            "league_id": self.league_id,
            "native_period_type": self.native_period_type,
            "probe_disposition": self.probe_disposition,
            "provider_availability_status": self.provider_availability_status,
            "provider_endpoint_id": self.provider_endpoint_id,
            "provider_occurrence_ids": list(self.provider_occurrence_ids),
            "symbol": self.symbol,
            "temporal_shape": self.temporal_shape,
        }


@dataclass(frozen=True, slots=True, order=True)
class CompetitionApplicabilityCell:
    """One occurrence-axis or registered-alias-role competition cell."""

    cell_kind: CellKind
    provider_endpoint_id: str
    provider_occurrence_id: str
    constructor_name: str
    wire_name: str
    league_id: str
    symbol: str
    temporal_shape: TemporalShape
    temporal_companion_occurrence_ids: tuple[str, ...]
    native_period_type: str
    repo_endpoint_name: str | None = None
    participant_axis_binding: str = "not_applicable"
    joint_cartesian_authority: bool = False
    declared_axis_status: str = _DECLARED_AXIS_STATUS
    declared_axis_evidence_kind: str = _DECLARED_AXIS_EVIDENCE_KIND
    endpoint_support_status: str = _ENDPOINT_SUPPORT_STATUS
    endpoint_support_evidence_kind: str = _ENDPOINT_SUPPORT_EVIDENCE_KIND
    provider_availability_status: str = _PROVIDER_AVAILABILITY_STATUS
    probe_disposition: str = _PROBE_DISPOSITION

    def __post_init__(self) -> None:
        _validate_cell_semantics(
            self.declared_axis_status,
            self.declared_axis_evidence_kind,
            self.endpoint_support_status,
            self.endpoint_support_evidence_kind,
            self.provider_availability_status,
            self.probe_disposition,
        )
        if (
            self.cell_kind not in {"parameter_axis", "alias_role"}
            or not self.provider_endpoint_id
            or not self.provider_occurrence_id
            or self.constructor_name
            not in {
                "league_id",
                "league_id_nullable",
                "person1_league_id",
                "person2_league_id",
            }
            or self.wire_name not in {"LeagueID", "Person1LeagueId", "Person2LeagueId"}
            or self.league_id not in _LEAGUE_IDS
            or not self.symbol
            or self.temporal_shape not in _TEMPORAL_SHAPES
            or self.native_period_type not in {"season_label", "calendar_year", "event_year"}
            or type(self.joint_cartesian_authority) is not bool
            or self.joint_cartesian_authority
            or (self.cell_kind == "parameter_axis") != (self.repo_endpoint_name is None)
        ):
            raise NbaApiCompetitionApplicabilityError(
                "competition applicability axis/role cell is invalid"
            )
        expected_wire = {
            "league_id": "LeagueID",
            "league_id_nullable": "LeagueID",
            "person1_league_id": "Person1LeagueId",
            "person2_league_id": "Person2LeagueId",
        }[self.constructor_name]
        if self.wire_name != expected_wire:
            raise NbaApiCompetitionApplicabilityError(
                "competition applicability constructor/wire binding is invalid"
            )
        expected_binding = (
            "same_person_temporal_companions"
            if self.constructor_name in {"person1_league_id", "person2_league_id"}
            else "not_applicable"
        )
        if self.participant_axis_binding != expected_binding:
            raise NbaApiCompetitionApplicabilityError(
                "GLAlum participant axis binding is collapsed or cross-person"
            )
        if self.constructor_name.startswith("person") and (
            self.provider_endpoint_id != _GL_ALUM_ENDPOINT
            or self.temporal_shape != "participant_season_axis"
            or self.temporal_companion_occurrence_ids
            != _GL_ALUM_BINDINGS.get(self.provider_occurrence_id)
        ):
            raise NbaApiCompetitionApplicabilityError(
                "GLAlum participant temporal binding is invalid"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "cell_kind": self.cell_kind,
            "constructor_name": self.constructor_name,
            "declared_axis_evidence_kind": self.declared_axis_evidence_kind,
            "declared_axis_status": self.declared_axis_status,
            "endpoint_support_evidence_kind": self.endpoint_support_evidence_kind,
            "endpoint_support_status": self.endpoint_support_status,
            "joint_cartesian_authority": self.joint_cartesian_authority,
            "league_id": self.league_id,
            "native_period_type": self.native_period_type,
            "participant_axis_binding": self.participant_axis_binding,
            "probe_disposition": self.probe_disposition,
            "provider_availability_status": self.provider_availability_status,
            "provider_endpoint_id": self.provider_endpoint_id,
            "provider_occurrence_id": self.provider_occurrence_id,
            "repo_endpoint_name": self.repo_endpoint_name,
            "symbol": self.symbol,
            "temporal_companion_occurrence_ids": list(self.temporal_companion_occurrence_ids),
            "temporal_shape": self.temporal_shape,
            "wire_name": self.wire_name,
        }


def _validate_cell_semantics(
    declared_axis_status: str,
    declared_axis_evidence_kind: str,
    endpoint_support_status: str,
    endpoint_support_evidence_kind: str,
    provider_availability_status: str,
    probe_disposition: str,
) -> None:
    if (
        declared_axis_status != _DECLARED_AXIS_STATUS
        or declared_axis_evidence_kind != _DECLARED_AXIS_EVIDENCE_KIND
    ):
        raise NbaApiCompetitionApplicabilityError(
            "request-contract cell is missing its declared-axis classification"
        )
    if endpoint_support_status != _ENDPOINT_SUPPORT_STATUS:
        raise NbaApiCompetitionApplicabilityError(
            "unsupported/supported endpoint cells require absent endpoint-specific evidence"
        )
    if endpoint_support_evidence_kind != _ENDPOINT_SUPPORT_EVIDENCE_KIND:
        raise NbaApiCompetitionApplicabilityError(
            "competition history cannot be promoted into endpoint support"
        )
    if provider_availability_status != _PROVIDER_AVAILABILITY_STATUS:
        raise NbaApiCompetitionApplicabilityError(
            "provider availability or upstream-unavailable claims require later evidence"
        )
    if probe_disposition != _PROBE_DISPOSITION:
        raise NbaApiCompetitionApplicabilityError(
            "provider probe disposition must remain probe_required"
        )


@dataclass(frozen=True, slots=True)
class CompetitionApplicabilityAuthority:
    """Complete offline applicability authority over all three denominators."""

    competition_existence_resource_sha256: str
    competition_existence_payload_sha256: str
    competition_existence_authority_sha256: str
    endpoint_support_resource_sha256: str
    endpoint_support_payload_sha256: str
    endpoint_support_authority_sha256: str
    source_review_resource_sha256: str
    source_review_payload_sha256: str
    source_review_authority_sha256: str
    competition_value_authority_sha256: str
    competition_occurrence_authority_sha256: str
    request_surface_sha256: str
    existence_intervals: tuple[CompetitionExistenceInterval, ...]
    endpoint_cells: tuple[EndpointCompetitionSupport, ...]
    parameter_axis_cells: tuple[CompetitionApplicabilityCell, ...]
    alias_role_cells: tuple[CompetitionApplicabilityCell, ...]
    revalidation_policy_id: str
    revalidation_date: str
    revalidation_network_required: bool
    revalidation_trigger: str

    def __post_init__(self) -> None:
        for field, value in (
            ("competition_existence_resource_sha256", self.competition_existence_resource_sha256),
            ("competition_existence_payload_sha256", self.competition_existence_payload_sha256),
            (
                "competition_existence_authority_sha256",
                self.competition_existence_authority_sha256,
            ),
            ("endpoint_support_resource_sha256", self.endpoint_support_resource_sha256),
            ("endpoint_support_payload_sha256", self.endpoint_support_payload_sha256),
            ("endpoint_support_authority_sha256", self.endpoint_support_authority_sha256),
            ("source_review_resource_sha256", self.source_review_resource_sha256),
            ("source_review_payload_sha256", self.source_review_payload_sha256),
            ("source_review_authority_sha256", self.source_review_authority_sha256),
            ("competition_value_authority_sha256", self.competition_value_authority_sha256),
            (
                "competition_occurrence_authority_sha256",
                self.competition_occurrence_authority_sha256,
            ),
            ("request_surface_sha256", self.request_surface_sha256),
        ):
            _require_digest(value, field)
        if (
            not self.revalidation_policy_id
            or not self.revalidation_date
            or self.revalidation_network_required is not True
            or not self.revalidation_trigger
        ):
            raise NbaApiCompetitionApplicabilityError(
                "competition applicability revalidation metadata is missing"
            )
        if (
            type(self.existence_intervals) is not tuple
            or len(self.existence_intervals) != 5
            or any(
                type(item) is not CompetitionExistenceInterval for item in self.existence_intervals
            )
            or self.existence_intervals
            != tuple(sorted(self.existence_intervals, key=lambda item: item.league_id))
        ):
            raise NbaApiCompetitionApplicabilityError(
                "competition existence intervals are missing, extra, overlapping, or unsorted"
            )
        league_ids = tuple(item.league_id for item in self.existence_intervals)
        if league_ids != _LEAGUE_IDS or len(set(league_ids)) != 5:
            raise NbaApiCompetitionApplicabilityError(
                "competition existence intervals are missing or duplicate"
            )
        self._validate_cells()

    def _validate_cells(self) -> None:
        if (
            type(self.endpoint_cells) is not tuple
            or len(self.endpoint_cells) != 555
            or any(type(item) is not EndpointCompetitionSupport for item in self.endpoint_cells)
            or type(self.parameter_axis_cells) is not tuple
            or len(self.parameter_axis_cells) != 560
            or any(
                type(item) is not CompetitionApplicabilityCell for item in self.parameter_axis_cells
            )
            or type(self.alias_role_cells) is not tuple
            or len(self.alias_role_cells) != 635
            or any(type(item) is not CompetitionApplicabilityCell for item in self.alias_role_cells)
        ):
            raise NbaApiCompetitionApplicabilityError(
                "applicability endpoint/axis/role denominator is incomplete"
            )
        endpoint_keys = tuple(
            (item.provider_endpoint_id, item.league_id) for item in self.endpoint_cells
        )
        axis_keys = tuple(
            (item.provider_occurrence_id, item.league_id) for item in self.parameter_axis_cells
        )
        alias_keys = tuple(
            (item.repo_endpoint_name, item.provider_occurrence_id, item.league_id)
            for item in self.alias_role_cells
        )
        if (
            len(set(endpoint_keys)) != 555
            or len(set(axis_keys)) != 560
            or len(set(alias_keys)) != 635
        ):
            raise NbaApiCompetitionApplicabilityError(
                "applicability contains duplicate endpoint, axis, or alias-role cell"
            )
        if (
            self.endpoint_cells
            != tuple(
                sorted(
                    self.endpoint_cells,
                    key=lambda item: (item.provider_endpoint_id, item.league_id),
                )
            )
            or self.parameter_axis_cells
            != tuple(
                sorted(
                    self.parameter_axis_cells,
                    key=lambda item: (item.provider_occurrence_id, item.league_id),
                )
            )
            or self.alias_role_cells
            != tuple(
                sorted(
                    self.alias_role_cells,
                    key=lambda item: (
                        item.repo_endpoint_name or "",
                        item.provider_occurrence_id,
                        item.league_id,
                    ),
                )
            )
        ):
            raise NbaApiCompetitionApplicabilityError(
                "applicability endpoint, axis, and alias-role cells must be canonical sorted"
            )
        expected_symbols = {item.league_id: item.symbol for item in self.existence_intervals}
        expected_types = {
            item.league_id: item.native_period_type for item in self.existence_intervals
        }
        for item in (*self.endpoint_cells, *self.parameter_axis_cells, *self.alias_role_cells):
            if (
                item.symbol != expected_symbols[item.league_id]
                or item.native_period_type != expected_types[item.league_id]
            ):
                raise NbaApiCompetitionApplicabilityError(
                    "NBA season encoding was substituted for another competition"
                )
        if len({item.provider_endpoint_id for item in self.endpoint_cells}) != 111:
            raise NbaApiCompetitionApplicabilityError("endpoint applicability denominator drifted")
        if len({item.provider_occurrence_id for item in self.parameter_axis_cells}) != 112:
            raise NbaApiCompetitionApplicabilityError("axis applicability denominator drifted")
        if (
            len(
                {
                    (item.repo_endpoint_name, item.provider_occurrence_id)
                    for item in self.alias_role_cells
                }
            )
            != 127
        ):
            raise NbaApiCompetitionApplicabilityError(
                "alias-role applicability denominator drifted"
            )
        axis_shapes = {
            item.provider_occurrence_id: item.temporal_shape for item in self.parameter_axis_cells
        }
        alias_shapes = {
            (item.repo_endpoint_name, item.provider_occurrence_id): item.temporal_shape
            for item in self.alias_role_cells
        }
        if dict(sorted(Counter(axis_shapes.values()).items())) != _TEMPORAL_SHAPE_COUNTS:
            raise NbaApiCompetitionApplicabilityError("axis temporal-shape partition drifted")
        if dict(sorted(Counter(alias_shapes.values()).items())) != _ALIAS_TEMPORAL_SHAPE_COUNTS:
            raise NbaApiCompetitionApplicabilityError("alias-role temporal-shape partition drifted")
        non_temporal = {
            item.provider_endpoint_id
            for item in self.parameter_axis_cells
            if item.temporal_shape == "no_temporal_parameter"
        }
        if non_temporal != _NON_TEMPORAL_ENDPOINTS:
            raise NbaApiCompetitionApplicabilityError("seven non-temporal endpoints are not exact")
        season_type_only = {
            item.provider_endpoint_id
            for item in self.parameter_axis_cells
            if item.temporal_shape == "season_type_only"
        }
        date_only = {
            item.provider_endpoint_id
            for item in self.parameter_axis_cells
            if item.temporal_shape == "date_or_date_range_only"
        }
        if season_type_only != _SEASON_TYPE_ONLY_ENDPOINTS or date_only != _DATE_ONLY_ENDPOINTS:
            raise NbaApiCompetitionApplicabilityError("special temporal-shape sets drifted")
        gl_axes = {
            item.provider_occurrence_id: item.temporal_companion_occurrence_ids
            for item in self.parameter_axis_cells
            if item.provider_endpoint_id == _GL_ALUM_ENDPOINT
        }
        if gl_axes != _GL_ALUM_BINDINGS or any(
            item.joint_cartesian_authority
            for item in self.parameter_axis_cells
            if item.provider_endpoint_id == _GL_ALUM_ENDPOINT
        ):
            raise NbaApiCompetitionApplicabilityError(
                "GLAlum axes were collapsed or granted joint Cartesian authority"
            )

    @property
    def authority_sha256(self) -> str:
        return _digest(_authority_body(self))


@dataclass(frozen=True, slots=True)
class CompetitionProbeEligibility:
    """Read-only resolution of whether a provider probe may be attempted."""

    provider_endpoint_id: str
    provider_occurrence_id: str
    repo_endpoint_name: str | None
    league_id: str
    symbol: str
    temporal_shape: TemporalShape
    native_period_type: str
    native_period: NativePeriod | None
    existence_status: str
    probe_eligible: bool
    probe_disposition: str
    endpoint_support_status: str = _ENDPOINT_SUPPORT_STATUS
    provider_availability_status: str = _PROVIDER_AVAILABILITY_STATUS

    def __post_init__(self) -> None:
        if self.endpoint_support_status != _ENDPOINT_SUPPORT_STATUS:
            raise NbaApiCompetitionApplicabilityError(
                "probe eligibility cannot claim endpoint support"
            )
        if self.provider_availability_status != _PROVIDER_AVAILABILITY_STATUS:
            raise NbaApiCompetitionApplicabilityError(
                "probe eligibility cannot claim provider availability"
            )
        if type(self.probe_eligible) is not bool:
            raise NbaApiCompetitionApplicabilityError("probe eligibility must use an exact boolean")

        authority = pinned_competition_applicability_authority()
        matches = [
            item
            for item in authority.parameter_axis_cells
            if item.provider_endpoint_id == self.provider_endpoint_id
            and item.provider_occurrence_id == self.provider_occurrence_id
            and item.league_id == self.league_id
        ]
        if len(matches) != 1:
            raise NbaApiCompetitionApplicabilityError(
                "probe eligibility requires one exact endpoint occurrence competition axis"
            )
        cell = matches[0]
        if (
            self.symbol != cell.symbol
            or self.temporal_shape != cell.temporal_shape
            or self.native_period_type != cell.native_period_type
        ):
            raise NbaApiCompetitionApplicabilityError(
                "probe eligibility competition or temporal identity differs from its axis"
            )
        if self.repo_endpoint_name is not None:
            alias_matches = [
                item
                for item in authority.alias_role_cells
                if item.repo_endpoint_name == self.repo_endpoint_name
                and item.provider_endpoint_id == self.provider_endpoint_id
                and item.provider_occurrence_id == self.provider_occurrence_id
                and item.league_id == self.league_id
            ]
            if len(alias_matches) != 1:
                raise NbaApiCompetitionApplicabilityError(
                    "probe eligibility repo alias does not project its exact occurrence axis"
                )

        interval = next(
            item for item in authority.existence_intervals if item.league_id == self.league_id
        )
        if self.temporal_shape in {"no_temporal_parameter", "season_type_only"}:
            expected = (
                None,
                "not_applicable_no_effective_period_axis",
                True,
                "probe_required",
            )
        elif self.native_period is None:
            expected = (None, "unknown_native_period_required", False, "unknown")
        else:
            eligible = interval.contains(self.native_period)
            expected = (
                self.native_period,
                ("confirmed_eligibility" if eligible else "outside_confirmed_eligibility"),
                eligible,
                "probe_required" if eligible else "unknown",
            )
        observed = (
            self.native_period,
            self.existence_status,
            self.probe_eligible,
            self.probe_disposition,
        )
        if observed != expected:
            raise NbaApiCompetitionApplicabilityError(
                "probe eligibility period, existence, boolean, and disposition are inconsistent"
            )


def _existence_rows(payload: dict[str, object]) -> tuple[CompetitionExistenceInterval, ...]:
    rows = payload.get("competitions")
    if not isinstance(rows, list) or len(rows) != 5:
        raise NbaApiCompetitionApplicabilityError(
            "competition existence source must contain five competitions"
        )
    result: list[CompetitionExistenceInterval] = []
    for row in rows:
        if not isinstance(row, dict):
            raise NbaApiCompetitionApplicabilityError("competition existence row is malformed")
        intervals = row.get("confirmed_intervals")
        gaps = row.get("explicit_gaps")
        planned = row.get("planned_future_periods")
        source_ids = row.get("source_ids")
        if (
            not isinstance(intervals, list)
            or len(intervals) != 1
            or not isinstance(intervals[0], dict)
            or not isinstance(gaps, list)
            or not isinstance(planned, list)
            or not isinstance(source_ids, list)
        ):
            raise NbaApiCompetitionApplicabilityError(
                "competition existence interval/gap/source shape is malformed"
            )
        if (
            row.get("endpoint_support_claim_count") != 0
            or row.get("provider_availability_claim_count") != 0
            or row.get("evidence_scope") != "competition_existence_only"
        ):
            raise NbaApiCompetitionApplicabilityError(
                "competition existence was promoted into endpoint support or availability"
            )
        gap_periods: list[NativePeriod] = []
        for gap in gaps:
            if not isinstance(gap, dict) or gap.get("status") != "confirmed_gap":
                raise NbaApiCompetitionApplicabilityError(
                    "competition existence gap is not confirmed"
                )
            period = gap.get("period")
            if not isinstance(period, (str, int)) or isinstance(period, bool):
                raise NbaApiCompetitionApplicabilityError(
                    "competition existence gap period is invalid"
                )
            gap_periods.append(period)
        planned_periods: list[NativePeriod] = []
        for future in planned:
            if (
                not isinstance(future, dict)
                or future.get("status") != "planned_future_not_confirmed_eligibility"
            ):
                raise NbaApiCompetitionApplicabilityError(
                    "planned future period was promoted into confirmed eligibility"
                )
            period = future.get("period")
            if not isinstance(period, (str, int)) or isinstance(period, bool):
                raise NbaApiCompetitionApplicabilityError("planned future period is invalid")
            planned_periods.append(period)
        interval = intervals[0]
        start = interval.get("start")
        end = interval.get("end")
        if (
            not isinstance(start, (str, int))
            or isinstance(start, bool)
            or not isinstance(end, (str, int))
            or isinstance(end, bool)
            or not all(isinstance(item, str) for item in source_ids)
        ):
            raise NbaApiCompetitionApplicabilityError(
                "competition existence native periods or sources are invalid"
            )
        result.append(
            CompetitionExistenceInterval(
                league_id=str(row.get("league_id", "")),
                symbol=str(row.get("symbol", "")),
                native_period_type=str(row.get("native_period_type", "")),
                start=start,
                end=end,
                status=str(interval.get("status", "")),
                explicit_gaps=tuple(gap_periods),
                planned_future_periods=tuple(planned_periods),
                source_ids=tuple(sorted(cast("list[str]", source_ids))),
            )
        )
    return tuple(sorted(result, key=lambda item: item.league_id))


def _verify_existence_source(payload: dict[str, object]) -> None:
    competitions = payload.get("competitions")
    sources = payload.get("sources")
    inventory = payload.get("source_url_inventory")
    revalidation = payload.get("revalidation")
    if (
        not isinstance(competitions, list)
        or not isinstance(sources, list)
        or not isinstance(inventory, list)
        or not isinstance(revalidation, dict)
    ):
        raise NbaApiCompetitionApplicabilityError("competition existence source is malformed")
    if (
        payload.get("schema") != "CompetitionExistenceEvidenceV1"
        or payload.get("competition_count") != 5
        or payload.get("source_count") != len(sources)
        or len(sources) != 12
        or payload.get("provider_availability_claim_count") != 0
        or payload.get("typed_endpoint_support_claim_count") != 0
        or payload.get("competitions_sha256") != _digest(competitions)
        or payload.get("sources_sha256") != _digest(sources)
        or payload.get("source_url_inventory_sha256") != _digest(inventory)
        or payload.get("revalidation_sha256") != _digest(revalidation)
    ):
        raise NbaApiCompetitionApplicabilityError(
            "competition existence source counts or component digests are invalid"
        )
    for source in sources:
        if not isinstance(source, dict):
            raise NbaApiCompetitionApplicabilityError("competition existence source row is invalid")
        body = dict(source)
        claim_sha256 = body.pop("claim_sha256", None)
        if _require_digest(claim_sha256, "claim_sha256") != _digest(body):
            raise NbaApiCompetitionApplicabilityError(
                "competition existence claim digest is invalid"
            )
    authority_fields = (
        "authority_exclusions",
        "competition_count",
        "competitions_sha256",
        "evidence_scope",
        "provider_availability_claim_count",
        "revalidation_sha256",
        "retrieval_date",
        "source_count",
        "source_url_inventory_sha256",
        "sources_sha256",
        "typed_endpoint_support_claim_count",
    )
    if payload.get("authority_sha256") != _digest(
        {field: payload.get(field) for field in authority_fields}
    ):
        raise NbaApiCompetitionApplicabilityError(
            "competition existence authority digest is invalid"
        )
    exclusions = payload.get("authority_exclusions")
    if not isinstance(exclusions, dict) or any(
        exclusions.get(field) != "not_authorized"
        for field in {
            "endpoint_support",
            "planned_future_as_confirmed",
            "provider_availability",
            "publication_rights",
            "request_terminal_state",
        }
    ):
        raise NbaApiCompetitionApplicabilityError(
            "competition existence source authority exclusions are incomplete"
        )
    if (
        not revalidation.get("policy_id")
        or not revalidation.get("last_revalidated_date")
        or revalidation.get("network_required") is not True
        or not revalidation.get("trigger")
    ):
        raise NbaApiCompetitionApplicabilityError(
            "competition existence revalidation metadata is missing"
        )


def _support_arrays(
    payload: dict[str, object],
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    endpoint = payload.get("endpoint_competition_cells")
    axes = payload.get("parameter_axis_competition_cells")
    aliases = payload.get("alias_role_competition_cells")
    if (
        not isinstance(endpoint, list)
        or not all(isinstance(item, dict) for item in endpoint)
        or not isinstance(axes, list)
        or not all(isinstance(item, dict) for item in axes)
        or not isinstance(aliases, list)
        or not all(isinstance(item, dict) for item in aliases)
    ):
        raise NbaApiCompetitionApplicabilityError(
            "endpoint support compact cell arrays are malformed"
        )
    return (
        cast("list[dict[str, object]]", endpoint),
        cast("list[dict[str, object]]", axes),
        cast("list[dict[str, object]]", aliases),
    )


def _verify_support_source(payload: dict[str, object]) -> None:
    endpoint, axes, aliases = _support_arrays(payload)
    if (
        payload.get("schema") != "EndpointCompetitionSupportEvidenceV1"
        or payload.get("competition_count") != 5
        or payload.get("package_endpoint_count") != 111
        or payload.get("package_occurrence_count") != 112
        or payload.get("repo_alias_count") != 126
        or payload.get("projected_role_count") != 127
        or payload.get("endpoint_competition_cell_count") != 555
        or payload.get("parameter_axis_competition_cell_count") != 560
        or payload.get("alias_role_competition_cell_count") != 635
        or payload.get("typed_declared_axis_cell_count") != 1750
        or len(endpoint) != 111
        or len(axes) != 112
        or len(aliases) != 127
        or payload.get("endpoint_competition_cells_sha256") != _digest(endpoint)
        or payload.get("parameter_axis_competition_cells_sha256") != _digest(axes)
        or payload.get("alias_role_competition_cells_sha256") != _digest(aliases)
        or payload.get("temporal_shape_counts") != _TEMPORAL_SHAPE_COUNTS
        or payload.get("alias_role_temporal_shape_counts") != _ALIAS_TEMPORAL_SHAPE_COUNTS
        or payload.get("endpoint_specific_supported_claim_count") != 0
        or payload.get("endpoint_specific_unsupported_claim_count") != 0
        or payload.get("provider_availability_claim_count") != 0
        or payload.get("provider_availability_observation_count") != 0
        or payload.get("endpoint_specific_supported_rows") != []
        or payload.get("endpoint_specific_unsupported_rows") != []
        or payload.get("provider_availability_observations") != []
    ):
        raise NbaApiCompetitionApplicabilityError(
            "endpoint support source counts, cells, or false-green counters are invalid"
        )
    for field in (
        "authority_inputs",
        "cell_semantics",
        "checked_authorities",
        "competition_values",
        "temporal_shape_policy",
        "unsupported_evidence_policy",
    ):
        value = payload.get(field)
        digest_field = f"{field}_sha256"
        if value is None or payload.get(digest_field) != _digest(value):
            raise NbaApiCompetitionApplicabilityError(
                f"endpoint support source {field} digest is invalid"
            )
    canonicalization = payload.get("canonicalization")
    if not isinstance(canonicalization, dict):
        raise NbaApiCompetitionApplicabilityError(
            "endpoint support canonicalization metadata is missing"
        )
    fields = canonicalization.get("authority_sha256_fields")
    if (
        not isinstance(fields, list)
        or not all(isinstance(item, str) for item in fields)
        or payload.get("authority_sha256")
        != _digest({field: payload.get(field) for field in fields})
    ):
        raise NbaApiCompetitionApplicabilityError("endpoint support authority digest is invalid")
    semantics = payload.get("cell_semantics")
    if not isinstance(semantics, dict) or semantics != {
        "applies_to_every_encoded_cell": True,
        "declared_axis_status": _DECLARED_AXIS_STATUS,
        "endpoint_support_status": _ENDPOINT_SUPPORT_STATUS,
        "league_default_as_cross_competition_support": "forbidden",
        "probe_disposition": "probe_required_before_any_availability_claim",
        "provider_availability_status": _PROVIDER_AVAILABILITY_STATUS,
    }:
        raise NbaApiCompetitionApplicabilityError(
            "endpoint support cell semantics promoted history/default/availability"
        )
    authority_inputs = payload.get("authority_inputs")
    if (
        type(authority_inputs) is not list
        or len(authority_inputs) != 16
        or payload.get("authority_inputs_sha256") != _EXPECTED_AUTHORITY_INPUTS_SHA256
        or _digest(authority_inputs) != _EXPECTED_AUTHORITY_INPUTS_SHA256
    ):
        raise NbaApiCompetitionApplicabilityError(
            "endpoint support authority input inventory is incomplete"
        )
    packet_inputs = _historical_task_packet_inputs()
    projected_inputs: list[dict[str, str]] = []
    for row in authority_inputs:
        if type(row) is not dict or tuple(row) != ("path", "role", "sha256"):
            raise NbaApiCompetitionApplicabilityError(
                "endpoint support authority input row is invalid"
            )
        relative = row.get("path")
        role = row.get("role")
        expected = row.get("sha256")
        if type(relative) is not str or not relative or type(role) is not str or not role:
            raise NbaApiCompetitionApplicabilityError(
                "endpoint support authority input identity is invalid"
            )
        projected = {
            "path": relative,
            "sha256": _require_digest(expected, "endpoint support authority input sha256"),
        }
        if packet_inputs.count(projected) != 1:
            raise NbaApiCompetitionApplicabilityError(
                f"endpoint support authority input is not uniquely packet-bound: {relative}"
            )
        projected_inputs.append(projected)
    if any(projected_inputs.count(row) != 1 for row in projected_inputs):
        raise NbaApiCompetitionApplicabilityError(
            "endpoint support authority input projection is not unique"
        )

    checked_authorities = payload.get("checked_authorities")
    if (
        type(checked_authorities) is not dict
        or payload.get("checked_authorities_sha256") != _EXPECTED_CHECKED_AUTHORITIES_SHA256
        or _digest(checked_authorities) != _EXPECTED_CHECKED_AUTHORITIES_SHA256
    ):
        raise NbaApiCompetitionApplicabilityError(
            "historical endpoint support checked authorities drifted"
        )


def _verify_source_review(
    payload: dict[str, object], existence_raw: bytes, support_raw: bytes
) -> None:
    canonicalization = payload.get("canonicalization")
    if not isinstance(canonicalization, dict):
        raise NbaApiCompetitionApplicabilityError("source review canonicalization is missing")
    fields = canonicalization.get("authority_sha256_fields")
    if (
        not isinstance(fields, list)
        or not all(isinstance(item, str) for item in fields)
        or payload.get("authority_sha256")
        != _digest({field: payload.get(field) for field in fields})
        or payload.get("schema") != "IndependentSourceReviewV1"
        or payload.get("disposition") != "pass"
        or payload.get("findings") != []
        or payload.get("model_green_asserted") is not False
        or payload.get("data_green_asserted") is not False
        or payload.get("live_operations_admissible") is not False
        or payload.get("publication_admissible") is not False
    ):
        raise NbaApiCompetitionApplicabilityError(
            "independent source review is not a finding-free source-only admission"
        )
    reviewed = payload.get("reviewed_inputs")
    expected = {
        _EXISTENCE_SOURCE: hashlib.sha256(existence_raw).hexdigest(),
        _SUPPORT_SOURCE: hashlib.sha256(support_raw).hexdigest(),
    }
    if not isinstance(reviewed, list) or len(reviewed) != 2:
        raise NbaApiCompetitionApplicabilityError(
            "independent source review input inventory is incomplete"
        )
    observed = {
        str(row.get("path")): str(row.get("sha256")) for row in reviewed if isinstance(row, dict)
    }
    if observed != expected:
        raise NbaApiCompetitionApplicabilityError(
            "independent source review does not bind the sealed source inputs"
        )


def _runtime_source_equality(
    support: dict[str, object], existence: tuple[CompetitionExistenceInterval, ...]
) -> None:
    competition = pinned_competition_authority()
    occurrence = pinned_competition_occurrence_authority()
    values = support.get("competition_values")
    expected_values = [item.to_dict() for item in competition.competitions]
    if values != expected_values:
        raise NbaApiCompetitionApplicabilityError(
            "support competition values differ from the pinned package authority"
        )
    if [(item.league_id, item.symbol) for item in existence] != [
        (item.league_id, item.symbol) for item in competition.competitions
    ]:
        raise NbaApiCompetitionApplicabilityError(
            "competition existence values differ from the pinned package authority"
        )
    endpoint_rows, axis_rows, alias_rows = _support_arrays(support)
    runtime_axes = {item.occurrence_id: item for item in occurrence.package_occurrences}
    if set(runtime_axes) != {str(row.get("provider_occurrence_id")) for row in axis_rows}:
        raise NbaApiCompetitionApplicabilityError(
            "support parameter axes differ from the pinned occurrence authority"
        )
    for row in axis_rows:
        item = runtime_axes[str(row["provider_occurrence_id"])]
        if any(
            row.get(field) != expected
            for field, expected in {
                "constructor_name": item.constructor_name,
                "default": item.default,
                "has_default": item.has_default,
                "league_ids": list(competition.league_ids),
                "nullable": item.nullable,
                "provider_endpoint_id": item.provider_endpoint_id,
                "request_surface_source_signature_sha256": (
                    item.request_surface_source_signature_sha256
                ),
                "request_surface_typed_domain_sha256": (item.request_surface_typed_domain_sha256),
                "wire_name": item.wire_name,
            }.items()
        ):
            raise NbaApiCompetitionApplicabilityError(
                "support parameter axis differs from the pinned occurrence authority"
            )
    by_endpoint: dict[str, list[str]] = {}
    for item in occurrence.package_occurrences:
        by_endpoint.setdefault(item.provider_endpoint_id, []).append(item.occurrence_id)
    expected_endpoint_rows = [
        {
            "league_ids": list(competition.league_ids),
            "provider_endpoint_id": endpoint_id,
            "provider_occurrence_ids": sorted(occurrence_ids),
        }
        for endpoint_id, occurrence_ids in sorted(by_endpoint.items())
    ]
    if endpoint_rows != expected_endpoint_rows:
        raise NbaApiCompetitionApplicabilityError(
            "support endpoint cells differ from the pinned occurrence authority"
        )
    axis_shape = {
        str(row["provider_occurrence_id"]): str(row["temporal_shape"]) for row in axis_rows
    }
    expected_alias_rows = []
    for alias in occurrence.repo_aliases:
        for role in alias.parameter_roles:
            expected_alias_rows.append(
                {
                    "constructor_name": role.constructor_name,
                    "league_ids": list(competition.league_ids),
                    "provider_endpoint_id": role.provider_endpoint_id,
                    "provider_occurrence_id": role.provider_occurrence_id,
                    "repo_endpoint_name": alias.repo_endpoint_name,
                    "temporal_shape": axis_shape[role.provider_occurrence_id],
                    "wire_name": role.wire_name,
                }
            )
    expected_alias_rows.sort(
        key=lambda row: (str(row["repo_endpoint_name"]), str(row["provider_occurrence_id"]))
    )
    if alias_rows != expected_alias_rows:
        raise NbaApiCompetitionApplicabilityError(
            "support alias roles differ from the pinned occurrence authority"
        )


def _compile_cells(
    support: dict[str, object],
    existence: tuple[CompetitionExistenceInterval, ...],
) -> tuple[
    tuple[EndpointCompetitionSupport, ...],
    tuple[CompetitionApplicabilityCell, ...],
    tuple[CompetitionApplicabilityCell, ...],
]:
    endpoint_rows, axis_rows, alias_rows = _support_arrays(support)
    competitions = {item.league_id: item for item in existence}
    axis_by_occurrence = {str(row["provider_occurrence_id"]): row for row in axis_rows}
    endpoint_cells: list[EndpointCompetitionSupport] = []
    for row in endpoint_rows:
        occurrence_ids = row.get("provider_occurrence_ids")
        if not isinstance(occurrence_ids, list) or not all(
            isinstance(item, str) for item in occurrence_ids
        ):
            raise NbaApiCompetitionApplicabilityError("endpoint support occurrence list is invalid")
        occurrence_id_rows = cast("list[str]", occurrence_ids)
        shapes = {str(axis_by_occurrence[item]["temporal_shape"]) for item in occurrence_id_rows}
        if len(shapes) != 1:
            raise NbaApiCompetitionApplicabilityError(
                "endpoint summary combines incompatible temporal shapes"
            )
        shape = cast("TemporalShape", next(iter(shapes)))
        for league_id in _LEAGUE_IDS:
            competition = competitions[league_id]
            endpoint_cells.append(
                EndpointCompetitionSupport(
                    provider_endpoint_id=str(row["provider_endpoint_id"]),
                    league_id=league_id,
                    symbol=competition.symbol,
                    provider_occurrence_ids=tuple(sorted(occurrence_id_rows)),
                    temporal_shape=shape,
                    native_period_type=competition.native_period_type,
                )
            )
    axis_cells: list[CompetitionApplicabilityCell] = []
    for row in axis_rows:
        companions = row.get("temporal_companion_occurrence_ids")
        if not isinstance(companions, list) or not all(
            isinstance(item, str) for item in companions
        ):
            raise NbaApiCompetitionApplicabilityError(
                "parameter-axis temporal companion list is invalid"
            )
        constructor = str(row["constructor_name"])
        for league_id in _LEAGUE_IDS:
            competition = competitions[league_id]
            axis_cells.append(
                CompetitionApplicabilityCell(
                    cell_kind="parameter_axis",
                    provider_endpoint_id=str(row["provider_endpoint_id"]),
                    provider_occurrence_id=str(row["provider_occurrence_id"]),
                    constructor_name=constructor,
                    wire_name=str(row["wire_name"]),
                    league_id=league_id,
                    symbol=competition.symbol,
                    temporal_shape=cast("TemporalShape", str(row["temporal_shape"])),
                    temporal_companion_occurrence_ids=tuple(cast("list[str]", companions)),
                    native_period_type=competition.native_period_type,
                    participant_axis_binding=(
                        "same_person_temporal_companions"
                        if constructor.startswith("person")
                        else "not_applicable"
                    ),
                )
            )
    alias_cells: list[CompetitionApplicabilityCell] = []
    for row in alias_rows:
        axis = axis_by_occurrence[str(row["provider_occurrence_id"])]
        companions = cast("list[str]", axis["temporal_companion_occurrence_ids"])
        constructor = str(row["constructor_name"])
        for league_id in _LEAGUE_IDS:
            competition = competitions[league_id]
            alias_cells.append(
                CompetitionApplicabilityCell(
                    cell_kind="alias_role",
                    provider_endpoint_id=str(row["provider_endpoint_id"]),
                    provider_occurrence_id=str(row["provider_occurrence_id"]),
                    constructor_name=constructor,
                    wire_name=str(row["wire_name"]),
                    league_id=league_id,
                    symbol=competition.symbol,
                    temporal_shape=cast("TemporalShape", str(row["temporal_shape"])),
                    temporal_companion_occurrence_ids=tuple(companions),
                    native_period_type=competition.native_period_type,
                    repo_endpoint_name=str(row["repo_endpoint_name"]),
                    participant_axis_binding=(
                        "same_person_temporal_companions"
                        if constructor.startswith("person")
                        else "not_applicable"
                    ),
                )
            )
    return (
        tuple(sorted(endpoint_cells, key=lambda item: (item.provider_endpoint_id, item.league_id))),
        tuple(sorted(axis_cells, key=lambda item: (item.provider_occurrence_id, item.league_id))),
        tuple(
            sorted(
                alias_cells,
                key=lambda item: (
                    item.repo_endpoint_name or "",
                    item.provider_occurrence_id,
                    item.league_id,
                ),
            )
        ),
    )


def _authority_body(authority: CompetitionApplicabilityAuthority) -> dict[str, object]:
    existence = [item.to_dict() for item in authority.existence_intervals]
    endpoints = [item.to_dict() for item in authority.endpoint_cells]
    axes = [item.to_dict() for item in authority.parameter_axis_cells]
    aliases = [item.to_dict() for item in authority.alias_role_cells]
    return {
        "alias_role_competition_cell_count": len(aliases),
        "alias_role_competition_cells": aliases,
        "alias_role_competition_cells_sha256": _digest(aliases),
        "alias_role_temporal_shape_counts": _ALIAS_TEMPORAL_SHAPE_COUNTS,
        "competition_count": len(existence),
        "competition_existence": existence,
        "competition_existence_sha256": _digest(existence),
        "endpoint_competition_cell_count": len(endpoints),
        "endpoint_competition_cells": endpoints,
        "endpoint_competition_cells_sha256": _digest(endpoints),
        "evidence_layers": _EVIDENCE_LAYERS,
        "false_green_counters": {
            "history_promoted_to_endpoint_support_count": 0,
            "provider_available_claim_count": 0,
            "unclassified_request_contract_cell_count": 0,
            "upstream_unavailable_claim_count": 0,
        },
        "gl_alum_participant_axis_contract": {
            "independent_axis_cell_count": 10,
            "joint_cartesian_cell_count_authorized": False,
            "same_person_temporal_bindings": [
                {
                    "provider_occurrence_id": occurrence_id,
                    "temporal_companion_occurrence_ids": list(companions),
                }
                for occurrence_id, companions in sorted(_GL_ALUM_BINDINGS.items())
            ],
        },
        "kind": "nbadb_nba_api_competition_applicability_authority",
        "parameter_axis_competition_cell_count": len(axes),
        "parameter_axis_competition_cells": axes,
        "parameter_axis_competition_cells_sha256": _digest(axes),
        "provider_availability_values": ["unknown"],
        "revalidation": {
            "last_revalidated_date": authority.revalidation_date,
            "network_required": authority.revalidation_network_required,
            "policy_id": authority.revalidation_policy_id,
            "source_body_bytes_or_digests_retained": False,
            "trigger": authority.revalidation_trigger,
        },
        "schema_version": COMPETITION_APPLICABILITY_SCHEMA_VERSION,
        "source_authorities": {
            "competition_existence": {
                "authority_sha256": authority.competition_existence_authority_sha256,
                "path": _EXISTENCE_SOURCE,
                "payload_sha256": authority.competition_existence_payload_sha256,
                "resource_sha256": authority.competition_existence_resource_sha256,
            },
            "competition_occurrences": {
                "authority_sha256": authority.competition_occurrence_authority_sha256,
            },
            "competition_values": {
                "authority_sha256": authority.competition_value_authority_sha256,
            },
            "endpoint_support": {
                "authority_sha256": authority.endpoint_support_authority_sha256,
                "path": _SUPPORT_SOURCE,
                "payload_sha256": authority.endpoint_support_payload_sha256,
                "resource_sha256": authority.endpoint_support_resource_sha256,
            },
            "independent_source_review": {
                "authority_sha256": authority.source_review_authority_sha256,
                "path": _SOURCE_REVIEW,
                "payload_sha256": authority.source_review_payload_sha256,
                "resource_sha256": authority.source_review_resource_sha256,
            },
            "request_surface": {"surface_sha256": authority.request_surface_sha256},
        },
        "special_temporal_sets": {
            "date_or_date_range_only_endpoint_ids": sorted(_DATE_ONLY_ENDPOINTS),
            "no_temporal_parameter_endpoint_ids": sorted(_NON_TEMPORAL_ENDPOINTS),
            "season_type_only_endpoint_ids": sorted(_SEASON_TYPE_ONLY_ENDPOINTS),
        },
        "temporal_shape_counts": _TEMPORAL_SHAPE_COUNTS,
        "typed_declared_axis_cell_count": len(endpoints) + len(axes) + len(aliases),
    }


@lru_cache(maxsize=1)
def build_competition_applicability_authority() -> CompetitionApplicabilityAuthority:
    """Compile the complete offline authority from the sealed evidence leaves."""

    existence_raw, existence_payload = _source_payload(_EXISTENCE_SOURCE)
    support_raw, support_payload = _source_payload(_SUPPORT_SOURCE)
    review_raw, review_payload = _source_payload(_SOURCE_REVIEW)
    _verify_existence_source(existence_payload)
    _verify_support_source(support_payload)
    _verify_source_review(review_payload, existence_raw, support_raw)
    existence = _existence_rows(existence_payload)
    _runtime_source_equality(support_payload, existence)
    endpoint_cells, axis_cells, alias_cells = _compile_cells(support_payload, existence)
    competition = pinned_competition_authority()
    occurrence = pinned_competition_occurrence_authority()
    revalidation = existence_payload.get("revalidation")
    if not isinstance(revalidation, dict):
        raise NbaApiCompetitionApplicabilityError("source revalidation authority is malformed")
    return CompetitionApplicabilityAuthority(
        competition_existence_resource_sha256=hashlib.sha256(existence_raw).hexdigest(),
        competition_existence_payload_sha256=str(existence_payload["payload_sha256"]),
        competition_existence_authority_sha256=str(existence_payload["authority_sha256"]),
        endpoint_support_resource_sha256=hashlib.sha256(support_raw).hexdigest(),
        endpoint_support_payload_sha256=str(support_payload["payload_sha256"]),
        endpoint_support_authority_sha256=str(support_payload["authority_sha256"]),
        source_review_resource_sha256=hashlib.sha256(review_raw).hexdigest(),
        source_review_payload_sha256=str(review_payload["payload_sha256"]),
        source_review_authority_sha256=str(review_payload["authority_sha256"]),
        competition_value_authority_sha256=competition.authority_sha256,
        competition_occurrence_authority_sha256=occurrence.authority_sha256,
        request_surface_sha256=_current_request_surface_sha256(occurrence),
        existence_intervals=existence,
        endpoint_cells=endpoint_cells,
        parameter_axis_cells=axis_cells,
        alias_role_cells=alias_cells,
        revalidation_policy_id=str(revalidation.get("policy_id", "")),
        revalidation_date=str(revalidation.get("last_revalidated_date", "")),
        revalidation_network_required=cast("bool", revalidation.get("network_required")),
        revalidation_trigger=str(revalidation.get("trigger", "")),
    )


def build_pinned_competition_applicability_payload() -> dict[str, object]:
    """Build the canonical checked applicability resource."""

    authority = build_competition_applicability_authority()
    body = _authority_body(authority)
    payload: dict[str, object] = {
        **body,
        "authority_sha256": authority.authority_sha256,
        "independent_proof": {
            "claim_status": "not_supplied_by_this_artifact",
            "kind": "independent_competition_applicability_source_receipt",
            "required": True,
            "schema_version": 1,
        },
    }
    payload["payload_sha256"] = _digest(payload)
    return payload


def write_pinned_competition_applicability(path: Path, *, check: bool = False) -> bool:
    """Write or verify the canonical checked applicability resource."""

    encoded = _canonical_bytes(build_pinned_competition_applicability_payload()) + b"\n"
    if path.is_file() and path.read_bytes() == encoded:
        return True
    if check:
        raise NbaApiCompetitionApplicabilityError(
            "pinned competition applicability authority has generated drift"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return False


def load_pinned_competition_applicability_payload(
    path: Path | None = None,
) -> dict[str, object]:
    """Load the checked resource and reproduce every current source edge."""

    try:
        raw = (
            resources.files("nbadb.contracts")
            .joinpath(COMPETITION_APPLICABILITY_RESOURCE)
            .read_bytes()
            if path is None
            else path.read_bytes()
        )
    except (AttributeError, OSError) as exc:
        raise NbaApiCompetitionApplicabilityError(
            "competition applicability resource cannot be read"
        ) from exc
    payload = _strict_json(raw, label="competition applicability resource", pretty=False)
    body = dict(payload)
    payload_sha256 = body.pop("payload_sha256", None)
    if _require_digest(payload_sha256, "payload_sha256") != _digest(body):
        raise NbaApiCompetitionApplicabilityError(
            "competition applicability payload digest is invalid"
        )
    if payload != build_pinned_competition_applicability_payload():
        raise NbaApiCompetitionApplicabilityError(
            "competition applicability resource differs from current sealed authorities"
        )
    return payload


@lru_cache(maxsize=1)
def pinned_competition_applicability_authority() -> CompetitionApplicabilityAuthority:
    """Return the authority only after independent source/resource verification."""

    payload = load_pinned_competition_applicability_payload()
    authority = build_competition_applicability_authority()
    from nbadb.core.nba_api_competition_applicability_verifier import (
        verify_pinned_competition_applicability_authority,
    )

    proof = verify_pinned_competition_applicability_authority()
    if (
        proof.authority_sha256 != authority.authority_sha256
        or proof.checked_payload_sha256 != payload.get("payload_sha256")
        or proof.endpoint_competition_cells_sha256
        != _digest([item.to_dict() for item in authority.endpoint_cells])
        or proof.parameter_axis_competition_cells_sha256
        != _digest([item.to_dict() for item in authority.parameter_axis_cells])
        or proof.alias_role_competition_cells_sha256
        != _digest([item.to_dict() for item in authority.alias_role_cells])
    ):
        raise NbaApiCompetitionApplicabilityError(
            "primary and independent competition applicability authorities differ"
        )
    return authority


def resolve_competition_probe_eligibility(
    provider_endpoint_id: str,
    league_id: str,
    native_period: NativePeriod | None = None,
    *,
    provider_occurrence_id: str | None = None,
    repo_endpoint_name: str | None = None,
) -> CompetitionProbeEligibility:
    """Resolve only whether a later provider probe may be attempted.

    The returned provider-availability status is always ``unknown``.  A true
    ``probe_eligible`` value is permission to probe, never evidence of support,
    data availability, or a terminal request state.
    """

    authority = pinned_competition_applicability_authority()
    candidates = [
        item
        for item in authority.parameter_axis_cells
        if item.provider_endpoint_id == provider_endpoint_id and item.league_id == league_id
    ]
    if provider_occurrence_id is not None:
        candidates = [
            item for item in candidates if item.provider_occurrence_id == provider_occurrence_id
        ]
    if len(candidates) != 1:
        raise NbaApiCompetitionApplicabilityError(
            "probe resolution requires one exact endpoint occurrence axis"
        )
    cell = candidates[0]
    if repo_endpoint_name is not None and not any(
        item.repo_endpoint_name == repo_endpoint_name
        and item.provider_occurrence_id == cell.provider_occurrence_id
        and item.league_id == league_id
        for item in authority.alias_role_cells
    ):
        raise NbaApiCompetitionApplicabilityError(
            "probe resolution repo alias does not project the selected occurrence"
        )
    interval = next(item for item in authority.existence_intervals if item.league_id == league_id)
    if cell.temporal_shape in {"no_temporal_parameter", "season_type_only"}:
        if native_period is not None:
            raise NbaApiCompetitionApplicabilityError(
                "endpoint has no explicit native-period request value"
            )
        eligible = True
        existence_status = "not_applicable_no_effective_period_axis"
    elif native_period is None:
        eligible = False
        existence_status = "unknown_native_period_required"
    else:
        eligible = interval.contains(native_period)
        existence_status = "confirmed_eligibility" if eligible else "outside_confirmed_eligibility"
    return CompetitionProbeEligibility(
        provider_endpoint_id=provider_endpoint_id,
        provider_occurrence_id=cell.provider_occurrence_id,
        repo_endpoint_name=repo_endpoint_name,
        league_id=league_id,
        symbol=cell.symbol,
        temporal_shape=cell.temporal_shape,
        native_period_type=cell.native_period_type,
        native_period=native_period,
        existence_status=existence_status,
        probe_eligible=eligible,
        probe_disposition="probe_required" if eligible else "unknown",
    )


__all__ = [
    "COMPETITION_APPLICABILITY_RESOURCE",
    "COMPETITION_APPLICABILITY_SCHEMA_VERSION",
    "CompetitionApplicabilityAuthority",
    "CompetitionApplicabilityCell",
    "CompetitionExistenceInterval",
    "CompetitionProbeEligibility",
    "EndpointCompetitionSupport",
    "NbaApiCompetitionApplicabilityError",
    "build_competition_applicability_authority",
    "build_pinned_competition_applicability_payload",
    "load_pinned_competition_applicability_payload",
    "pinned_competition_applicability_authority",
    "resolve_competition_probe_eligibility",
    "write_pinned_competition_applicability",
]
