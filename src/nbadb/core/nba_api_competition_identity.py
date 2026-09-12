"""Competition-qualified identities for the pinned ``nba-api==1.11.4`` surface.

This compiler is deliberately offline.  It joins the explicit competition
applicability authority with the implicit competition-root complement and then
wraps, rather than replaces, canonical provider-request identities.  Typed
runtime receipts are admitted only at the qualifier that consumes them.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import InitVar, dataclass, field, fields, is_dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal, SupportsIndex, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

from nbadb.core.errors import ParserInputCaptureIntegrityError
from nbadb.core.nba_api_competition import (
    load_pinned_competition_payload,
    pinned_competition_authority,
)
from nbadb.core.nba_api_competition_applicability import (
    CompetitionApplicabilityCell,
    load_pinned_competition_applicability_payload,
    pinned_competition_applicability_authority,
)
from nbadb.core.nba_api_implicit_competition import (
    ImplicitCompetitionCell,
    ReceiptBoundCompetitionRoot,
    load_pinned_implicit_competition_payload,
    pinned_implicit_competition_authority,
)
from nbadb.core.nba_api_request_surface import (
    AuthoritativeRouteManifest,
    CanonicalProviderRequest,
    IndependentClosureProof,
    RequestClosureIteration,
    RequestClosureReceipt,
    RequestExpansionEvidence,
    RequestRouteBinding,
    RequestScopeDimension,
    RequestScopeManifest,
    RequestTerminalEvidence,
    RouteRequestSpec,
    load_pinned_request_surface_payload,
    materialize_provider_request,
    pinned_request_surface_authority,
)
from nbadb.core.nba_api_terminal_state import (
    TerminalRequestBinding,
    TypedUpstreamUnavailableEvidence,
    UpstreamUnavailableSupportAuthority,
    build_terminal_request_binding,
    build_typed_upstream_unavailable_evidence,
    load_pinned_terminal_state_payload,
)

COMPETITION_IDENTITY_SCHEMA_VERSION: Final = 2
COMPETITION_IDENTITY_RESOURCE: Final = "nba_api_competition_identity_v1_11_4.json"

_PACKAGED_TASK_PACKET_ROOT: Final = (
    "provenance",
    "nba_api_v1_11_4",
    "competition_identity",
)
_TASK_PACKET: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-11.json"
)
_TASK_PACKET_SHA256: Final = "5f0cb0d04f9e46f412458489ba0d088193e18ba128f1739a2c03d87b4b5e57da"
_REPAIR_10_TASK_PACKET: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-10.json"
)
_REPAIR_10_TASK_PACKET_SHA256: Final = (
    "86841cb180f840f545e11bcb8351e0d8c33dc73b35131e4343dad4f2c69493fb"
)
_REPAIR_9_TASK_PACKET: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-9.json"
)
_REPAIR_9_TASK_PACKET_SHA256: Final = (
    "2e3ba24efd741f36843cc6889a566a56479c140ebf5b940f8e087a509c1f26b1"
)
_REPAIR_8_TASK_PACKET: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-8.json"
)
_REPAIR_8_TASK_PACKET_SHA256: Final = (
    "cdcc5ebfd9a421dfad4687a875e321758df4af1bf65b10523146474843a6ffd5"
)
_REPAIR_7_TASK_PACKET: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-7.json"
)
_REPAIR_7_TASK_PACKET_SHA256: Final = (
    "edcac7bc3665b75abb27f6620e6bee6beae8e8004d54dab0ea14964f3ce9fb90"
)
_REPAIR_6_TASK_PACKET: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-6.json"
)
_REPAIR_6_TASK_PACKET_SHA256: Final = (
    "3f70b85f91b6ac00cbaf0afb6f29b17c116e03feddf4db3b6c50b1ac20d26b81"
)
_REPAIR_5_TASK_PACKET: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-5.json"
)
_REPAIR_5_TASK_PACKET_SHA256: Final = (
    "e580c8b09906b0c61d5963ba254621733ac1b5342d1e336b004e7103f200a28f"
)
_REPAIR_4_TASK_PACKET: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-4.json"
)
_REPAIR_4_TASK_PACKET_SHA256: Final = (
    "50a6a3aac9ae745310abd70cd6329b0ae0fccf400f6abf95812e973541cfc7cc"
)
_REPAIR_3_TASK_PACKET: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-3.json"
)
_REPAIR_3_TASK_PACKET_SHA256: Final = (
    "fb416dae2138193e46f0176b5ffe614ccae1f9f63732cbc7dc539117f7b27313"
)
_REPAIR_2_TASK_PACKET: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-2.json"
)
_REPAIR_2_TASK_PACKET_SHA256: Final = (
    "edd3d85dffc4274a6423c32ed5491adfcecafe401d7ad84f42ff261f7d1e4277"
)
_REPAIR_1_TASK_PACKET: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-1.json"
)
_REPAIR_1_TASK_PACKET_SHA256: Final = (
    "d4b8f42ce99a7aa587f123e1bdb3640a50a8f61343a24701d8f662c3b226cb1c"
)
_ORIGINAL_TASK_PACKET: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a.json"
)
_ORIGINAL_TASK_PACKET_SHA256: Final = (
    "a2fea5fc1ef45404d9d917ed13107fc4356646810c222bb9234c832bdb7ed660"
)
_TASK_PACKET_IMMUTABLE_INPUTS_SHA256: Final = (
    "5806ae72584f96aa45fd9069026543bf850c8d5f3799c3c007f9db7043cd61aa"
)
_TASK_PACKET_MUTABLE_OPENING_INPUTS_SHA256: Final = (
    "1b7a7f8df1101678331f5a5f548c62bab63c4a23ecae0f50ce9822b4ac09c568"
)
_IDENTITY_CONTRACT_PACKET: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.2e.json"
)
_IDENTITY_CONTRACT_PACKET_SHA256: Final = (
    "d87507bb66d470dfec88626f8fc9c0b8484fa54dbb1244d564693414e18fc64c"
)
_TERMINAL_POLICY_SHA256: Final = "7226e797a685755311b7b9073f905d7288150e3412d52d95423ef0093548388d"
_TERMINAL_RESOURCE_PATH: Final = "src/nbadb/contracts/nba_api_terminal_state_v1_11_4.json"
_TERMINAL_RESOURCE_SHA256: Final = (
    "9389644949a92046ce3e00491842c3786812cfe043d727dbbdc6b0c84d2ab867"
)
_TERMINAL_PAYLOAD_SHA256: Final = "471f594174107ccb8f582a6ab0459a356acf9daebd75ac55464475b3df792f4d"
_REQUEST_SURFACE_SHA256: Final = "ef6195829a9f1dad9f847094b79e88fae24dffc5c4df18e3d3e972f347f83733"
_REQUEST_RESOURCE_PATH: Final = "src/nbadb/contracts/nba_api_request_surface_v1_11_4.json"
_REQUEST_RESOURCE_SHA256: Final = "3082def2aa92b35d55107f5ce8eaf2ffa0532a0e649899d0f1180979f6144981"
_REQUEST_PAYLOAD_SHA256: Final = "b310313f41cf97cf1b8f55e01bbe95868532f3008527bf5265a985628eca9052"
_REQUEST_RUNTIME_CONTRACT_PAYLOAD_SHA256: Final = (
    "7c9b59c475cff6b0b9d3619bdfe9a3849e11619980f6d15a1cafd5f269f61b3b"
)
_COMPETITION_AUTHORITY_SHA256: Final = (
    "61c9477221c08f4f36269c8c3050171e0ec472508a0a8ac72ddc6f42d865ef98"
)
_COMPETITION_RESOURCE_PATH: Final = "src/nbadb/contracts/nba_api_competition_v1_11_4.json"
_COMPETITION_RESOURCE_SHA256: Final = (
    "cfb93458f5efb569995ddccaf33ae37c0c312e25e09d0649c307999ec0057c44"
)
_COMPETITION_PAYLOAD_SHA256: Final = (
    "1e79989c9d75d671520d868dfa4e63bc828ceb7844c64b28e7325dd11a6ce7e0"
)
_APPLICABILITY_AUTHORITY_SHA256: Final = (
    "867d64282d6da37b9289c191ec5396e34c2c2ca335ebc94d09329ad89619528f"
)
_APPLICABILITY_RESOURCE_PATH: Final = (
    "src/nbadb/contracts/nba_api_competition_applicability_v1_11_4.json"
)
_APPLICABILITY_RESOURCE_SHA256: Final = (
    "daf43b872bd301aa87f1a67b357d970b82e532890e09e7ce0e580545d09cb0aa"
)
_HISTORICAL_TASK_PACKET_APPLICABILITY_RESOURCE_SHA256: Final = (
    "5012a741760f06e10b189da1ac87f00e36dbdac263da08c29457825d46602cbe"
)
_APPLICABILITY_PAYLOAD_SHA256: Final = (
    "c1b808dc593d5aa9aea90b02285c2cfb37dc60e60ecd988dcf944d4984a9907a"
)
_IMPLICIT_AUTHORITY_SHA256: Final = (
    "fe7fd7581532754b322155ad0a74fcbd4068e1ebc83fbd841fd3736e27616d97"
)
_IMPLICIT_RESOURCE_PATH: Final = "src/nbadb/contracts/nba_api_implicit_competition_v1_11_4.json"
_IMPLICIT_RESOURCE_SHA256: Final = (
    "ed75be5cf84df8975cc32d50b51215648896b618584ed5b3b3aedcb8b6dc2111"
)
_IMPLICIT_PAYLOAD_SHA256: Final = "9fddfad2276884b5d49dc71fca052d7285f73e046d5157427b7fb7b2fcd35ec1"
_IMPLICIT_SUPERSESSION_PROOF_SHA256: Final = (
    "72ef26235ab1ffbc3f3f339ef246151201dfa331f14444a88888eeddd94be7c5"
)
_EXPECTED_PROVIDER_AUTHORITY_SHA256: Final = (
    "e5981c0223c99ecd4a483606781d1433cc23f22b26ec71c41a3b12b9ad827085"
)
_SOURCE_INVENTORY_INPUTS_SHA256: Final = (
    "e0795472375627bccefab70ce77764875b03f3152cb44f046ba358d19fd1d7a9"
)
_QUALIFIED_SURFACE_CONTRACTS_SHA256: Final = (
    "d63d7842e2e68544afe6fa3eb36566f5b4f29138770fe20e76718bce9133c4b4"
)

_COMPETITION_SCOPE_DOMAIN: Final = "nbadb.nba-api.competition-scope.v1"
_SOURCE_REQUEST_DOMAIN: Final = "nbadb.nba-api.source-request.v1"
_PAGINATION_SERIES_DOMAIN: Final = "nbadb.nba-api.pagination-series.v1"
_PAGINATION_PAGE_DOMAIN: Final = "nbadb.nba-api.pagination-page.v1"
_DISCOVERY_GENERATION_DOMAIN: Final = "nbadb.nba-api.discovery-generation.v1"
_TERMINAL_OBSERVATION_DOMAIN: Final = "nbadb.nba-api.terminal-observation.v1"
_UNAVAILABLE_EVIDENCE_DOMAIN: Final = "nbadb.nba-api.unavailable-evidence.v1"
_STAGING_OCCURRENCE_DOMAIN: Final = "nbadb.nba-api.staging-occurrence.v1"
_ENTITY_DOMAIN: Final = "nbadb.nba-api.entity.v1"

_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)
_BINDING_STRATEGIES: Final = frozenset(
    {
        "explicit_applicability_cell",
        "receipt_bound_dynamic_root",
        "fixed_static_root",
        "root_not_exposed",
    }
)
_EXPECTED_BINDING_COUNTS: Final = {
    "explicit_applicability_cell": 635,
    "fixed_static_root": 4,
    "receipt_bound_dynamic_root": 160,
    "root_not_exposed": 16,
}

BindingStrategy = Literal[
    "explicit_applicability_cell",
    "receipt_bound_dynamic_root",
    "fixed_static_root",
    "root_not_exposed",
]
RequestKind = Literal["provider_request", "static_source"]
JsonScalar = str | int | float | bool | None


class NbaApiCompetitionIdentityError(ValueError):
    """The competition-qualified identity authority or evidence is invalid."""


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
        raise NbaApiCompetitionIdentityError("competition identity is not canonical JSON") from exc


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
        raise NbaApiCompetitionIdentityError("competition identity is not canonical JSON") from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_sha256(value: object, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise NbaApiCompetitionIdentityError(f"{field_name} must be an exact canonical SHA-256")
    return value


def _require_text(value: object, field_name: str) -> str:
    if type(value) is not str or not value:
        raise NbaApiCompetitionIdentityError(f"{field_name} must be an exact nonempty string")
    return value


def _require_nonnegative_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise NbaApiCompetitionIdentityError(f"{field_name} must be an exact nonnegative integer")
    return value


def _require_optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, field_name)


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise NbaApiCompetitionIdentityError(
                f"competition identity contains duplicate object key: {key}"
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise NbaApiCompetitionIdentityError(
        f"competition identity contains non-finite JSON constant: {value}"
    )


def _strict_json(
    raw: bytes,
    *,
    label: str,
    pretty: bool,
    sort_keys: bool = True,
) -> dict[str, object]:
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except NbaApiCompetitionIdentityError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NbaApiCompetitionIdentityError(f"{label} cannot be decoded") from exc
    if type(payload) is not dict:
        raise NbaApiCompetitionIdentityError(f"{label} must be an exact JSON object")
    if pretty and not sort_keys:
        expected = (
            json.dumps(
                payload,
                sort_keys=False,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
    else:
        expected = _pretty_bytes(payload) if pretty else _canonical_bytes(payload) + b"\n"
    if raw != expected:
        raise NbaApiCompetitionIdentityError(f"{label} bytes are not canonical JSON")
    return cast("dict[str, object]", payload)


def _exact_typed_equal(left: object, right: object) -> bool:
    """Compare nested public typed state without Python coercive equality."""

    if type(left) is not type(right):
        return False
    if is_dataclass(left) and not isinstance(left, type):
        return all(
            _exact_typed_equal(getattr(left, item.name), getattr(right, item.name))
            for item in fields(left)
        )
    if type(left) is tuple:
        right_tuple = cast("tuple[object, ...]", right)
        left_tuple = cast("tuple[object, ...]", left)
        return len(left_tuple) == len(right_tuple) and all(
            _exact_typed_equal(a, b) for a, b in zip(left_tuple, right_tuple, strict=True)
        )
    if type(left) is list:
        right_list = cast("list[object]", right)
        left_list = cast("list[object]", left)
        return len(left_list) == len(right_list) and all(
            _exact_typed_equal(a, b) for a, b in zip(left_list, right_list, strict=True)
        )
    if type(left) is dict:
        left_dict = cast("dict[object, object]", left)
        right_dict = cast("dict[object, object]", right)
        if len(left_dict) != len(right_dict):
            return False
        for key, value in left_dict.items():
            matching_keys = [
                candidate for candidate in right_dict if _exact_typed_equal(key, candidate)
            ]
            if len(matching_keys) != 1 or not _exact_typed_equal(
                value, right_dict[matching_keys[0]]
            ):
                return False
        return True
    if type(left) is float:
        left_float = cast("float", left)
        right_float = cast("float", right)
        return (
            math.isfinite(left_float)
            and math.isfinite(right_float)
            and left_float == right_float
            and math.copysign(1.0, left_float) == math.copysign(1.0, right_float)
        )
    return bool(left == right)


def _exact_json_scalar(value: object, *, field_name: str) -> JsonScalar:
    if type(value) not in {str, int, float, bool, type(None)}:
        raise NbaApiCompetitionIdentityError(f"{field_name} is not an exact JSON scalar")
    if type(value) is float and not math.isfinite(cast("float", value)):
        raise NbaApiCompetitionIdentityError(f"{field_name} must be finite")
    return cast("JsonScalar", value)


def _exact_rows(value: object, *, label: str, count: int) -> list[dict[str, object]]:
    if (
        type(value) is not list
        or len(value) != count
        or any(type(row) is not dict for row in value)
    ):
        raise NbaApiCompetitionIdentityError(f"{label} must contain exactly {count} rows")
    return cast("list[dict[str, object]]", value)


def _read_authenticated_packet(
    relative_path: str,
    expected_sha256: str,
    *,
    label: str,
    task_id: str,
) -> tuple[bytes, dict[str, object]]:
    packaged_name = relative_path.rsplit("/", 1)[-1]
    if relative_path not in {
        _TASK_PACKET,
        _REPAIR_10_TASK_PACKET,
        _REPAIR_9_TASK_PACKET,
        _REPAIR_8_TASK_PACKET,
        _REPAIR_7_TASK_PACKET,
        _REPAIR_6_TASK_PACKET,
        _REPAIR_5_TASK_PACKET,
        _REPAIR_4_TASK_PACKET,
        _REPAIR_3_TASK_PACKET,
        _REPAIR_2_TASK_PACKET,
        _REPAIR_1_TASK_PACKET,
        _ORIGINAL_TASK_PACKET,
        _IDENTITY_CONTRACT_PACKET,
    }:
        raise NbaApiCompetitionIdentityError(f"{label} has no packaged authority")
    try:
        raw = (
            resources.files("nbadb.contracts")
            .joinpath(*_PACKAGED_TASK_PACKET_ROOT, packaged_name)
            .read_bytes()
        )
    except (AttributeError, OSError) as exc:
        raise NbaApiCompetitionIdentityError(f"{label} cannot be read") from exc
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise NbaApiCompetitionIdentityError(f"{label} hash drifted")
    packet = _strict_json(raw, label=label, pretty=True, sort_keys=False)
    if packet.get("task_id") != task_id:
        raise NbaApiCompetitionIdentityError(f"{label} identity drifted")
    return raw, packet


@lru_cache(maxsize=1)
def _task_packet_payload() -> dict[str, object]:
    packet_raw, packet = _read_authenticated_packet(
        _TASK_PACKET,
        _TASK_PACKET_SHA256,
        label="A1.3a-repair-11 TaskPacket",
        task_id="A1.3a-repair-11",
    )
    repair_10_raw, repair_10 = _read_authenticated_packet(
        _REPAIR_10_TASK_PACKET,
        _REPAIR_10_TASK_PACKET_SHA256,
        label="A1.3a-repair-10 TaskPacket",
        task_id="A1.3a-repair-10",
    )
    repair_9_raw, repair_9 = _read_authenticated_packet(
        _REPAIR_9_TASK_PACKET,
        _REPAIR_9_TASK_PACKET_SHA256,
        label="A1.3a-repair-9 TaskPacket",
        task_id="A1.3a-repair-9",
    )
    repair_8_raw, repair_8 = _read_authenticated_packet(
        _REPAIR_8_TASK_PACKET,
        _REPAIR_8_TASK_PACKET_SHA256,
        label="A1.3a-repair-8 TaskPacket",
        task_id="A1.3a-repair-8",
    )
    repair_7_raw, repair_7 = _read_authenticated_packet(
        _REPAIR_7_TASK_PACKET,
        _REPAIR_7_TASK_PACKET_SHA256,
        label="A1.3a-repair-7 TaskPacket",
        task_id="A1.3a-repair-7",
    )
    repair_6_raw, repair_6 = _read_authenticated_packet(
        _REPAIR_6_TASK_PACKET,
        _REPAIR_6_TASK_PACKET_SHA256,
        label="A1.3a-repair-6 TaskPacket",
        task_id="A1.3a-repair-6",
    )
    repair_5_raw, repair_5 = _read_authenticated_packet(
        _REPAIR_5_TASK_PACKET,
        _REPAIR_5_TASK_PACKET_SHA256,
        label="A1.3a-repair-5 TaskPacket",
        task_id="A1.3a-repair-5",
    )
    repair_4_raw, repair_4 = _read_authenticated_packet(
        _REPAIR_4_TASK_PACKET,
        _REPAIR_4_TASK_PACKET_SHA256,
        label="A1.3a-repair-4 TaskPacket",
        task_id="A1.3a-repair-4",
    )
    repair_3_raw, repair_3 = _read_authenticated_packet(
        _REPAIR_3_TASK_PACKET,
        _REPAIR_3_TASK_PACKET_SHA256,
        label="A1.3a-repair-3 TaskPacket",
        task_id="A1.3a-repair-3",
    )
    repair_2_raw, repair_2 = _read_authenticated_packet(
        _REPAIR_2_TASK_PACKET,
        _REPAIR_2_TASK_PACKET_SHA256,
        label="A1.3a-repair-2 TaskPacket",
        task_id="A1.3a-repair-2",
    )
    repair_1_raw, repair_1 = _read_authenticated_packet(
        _REPAIR_1_TASK_PACKET,
        _REPAIR_1_TASK_PACKET_SHA256,
        label="A1.3a-repair-1 TaskPacket",
        task_id="A1.3a-repair-1",
    )
    original_raw, _original = _read_authenticated_packet(
        _ORIGINAL_TASK_PACKET,
        _ORIGINAL_TASK_PACKET_SHA256,
        label="original A1.3a TaskPacket",
        task_id="A1.3a",
    )
    packet_byte_identities = (
        (packet_raw, 434834, 8478, "A1.3a-repair-11"),
        (repair_10_raw, 407143, 7989, "A1.3a-repair-10"),
        (repair_9_raw, 385867, 7634, "A1.3a-repair-9"),
        (repair_8_raw, 362821, 7138, "A1.3a-repair-8"),
        (repair_7_raw, 340405, 6755, "A1.3a-repair-7"),
        (repair_6_raw, 318301, 6370, "A1.3a-repair-6"),
        (repair_5_raw, 244906, 4847, "A1.3a-repair-5"),
        (repair_4_raw, 195745, 3766, "A1.3a-repair-4"),
        (repair_3_raw, 168029, 3187, "A1.3a-repair-3"),
        (repair_2_raw, 150660, 2537, "A1.3a-repair-2"),
        (repair_1_raw, 131669, 2305, "A1.3a-repair-1"),
        (original_raw, 97245, 2030, "original A1.3a"),
    )
    for raw, expected_size, expected_lf, label in packet_byte_identities:
        if len(raw) != expected_size or raw.count(b"\n") != expected_lf:
            raise NbaApiCompetitionIdentityError(f"{label} TaskPacket byte identity drifted")
    expected_repair_10 = {
        "line_count": 7989,
        "path": _REPAIR_10_TASK_PACKET,
        "sha256": _REPAIR_10_TASK_PACKET_SHA256,
        "size": 407143,
    }
    expected_repair_9 = {
        "line_count": 7634,
        "path": _REPAIR_9_TASK_PACKET,
        "sha256": _REPAIR_9_TASK_PACKET_SHA256,
        "size": 385867,
    }
    expected_repair_8 = {
        "line_count": 7138,
        "path": _REPAIR_8_TASK_PACKET,
        "sha256": _REPAIR_8_TASK_PACKET_SHA256,
        "size": 362821,
    }
    expected_repair_7 = {
        "line_count": 6755,
        "path": _REPAIR_7_TASK_PACKET,
        "sha256": _REPAIR_7_TASK_PACKET_SHA256,
        "size": 340405,
    }
    expected_repair_6 = {
        "line_count": 6370,
        "path": _REPAIR_6_TASK_PACKET,
        "sha256": _REPAIR_6_TASK_PACKET_SHA256,
        "size": 318301,
    }
    expected_repair_5 = {
        "line_count": 4847,
        "path": _REPAIR_5_TASK_PACKET,
        "sha256": _REPAIR_5_TASK_PACKET_SHA256,
        "size": 244906,
    }
    expected_repair_4 = {
        "line_count": 3766,
        "path": _REPAIR_4_TASK_PACKET,
        "sha256": _REPAIR_4_TASK_PACKET_SHA256,
        "size": 195745,
    }
    expected_repair_3 = {
        "line_count": 3187,
        "path": _REPAIR_3_TASK_PACKET,
        "sha256": _REPAIR_3_TASK_PACKET_SHA256,
        "size": 168029,
    }
    expected_repair_2 = {
        "line_count": 2537,
        "path": _REPAIR_2_TASK_PACKET,
        "sha256": _REPAIR_2_TASK_PACKET_SHA256,
        "size": 150660,
    }
    expected_repair_1 = {
        "line_count": 2305,
        "path": _REPAIR_1_TASK_PACKET,
        "sha256": _REPAIR_1_TASK_PACKET_SHA256,
        "size": 131669,
    }
    expected_original = {
        "line_count": 2030,
        "path": _ORIGINAL_TASK_PACKET,
        "sha256": _ORIGINAL_TASK_PACKET_SHA256,
        "size": 97245,
    }
    chain = (
        (packet, repair_10, expected_repair_10, "A1.3a-repair-10"),
        (repair_10, repair_9, expected_repair_9, "A1.3a-repair-9"),
        (repair_9, repair_8, expected_repair_8, "A1.3a-repair-8"),
        (repair_8, repair_7, expected_repair_7, "A1.3a-repair-7"),
        (repair_7, repair_6, expected_repair_6, "A1.3a-repair-6"),
        (repair_6, repair_5, expected_repair_5, "A1.3a-repair-5"),
        (repair_5, repair_4, expected_repair_4, "A1.3a-repair-4"),
        (repair_4, repair_3, expected_repair_3, "A1.3a-repair-3"),
        (repair_3, repair_2, expected_repair_2, "A1.3a-repair-2"),
        (repair_2, repair_1, expected_repair_1, "A1.3a-repair-1"),
    )
    for current, prior, expected_reference, label in chain:
        supersession = _packet_dict(current, "superseded_packet")
        direct_reference = _packet_dict(supersession, "packet")
        prior_supersession = _packet_dict(supersession, "prior_supersession")
        if not _exact_typed_equal(direct_reference, expected_reference) or not _exact_typed_equal(
            prior_supersession,
            _packet_dict(prior, "superseded_packet"),
        ):
            raise NbaApiCompetitionIdentityError(f"{label} supersession binding drifted")
    repair_1_supersession = _packet_dict(repair_1, "superseded_packet")
    if not _exact_typed_equal(_packet_dict(repair_1_supersession, "packet"), expected_original):
        raise NbaApiCompetitionIdentityError("original A1.3a supersession chain drifted")
    immutable = _exact_rows(
        packet.get("immutable_inputs"),
        label="repair-11 immutable inputs",
        count=127,
    )
    mutable = _exact_rows(
        packet.get("mutable_opening_inputs"),
        label="repair-11 mutable opening inputs",
        count=8,
    )
    if (
        packet.get("immutable_inputs_sha256") != _TASK_PACKET_IMMUTABLE_INPUTS_SHA256
        or _digest(immutable) != _TASK_PACKET_IMMUTABLE_INPUTS_SHA256
        or packet.get("mutable_opening_inputs_sha256") != _TASK_PACKET_MUTABLE_OPENING_INPUTS_SHA256
        or _digest(mutable) != _TASK_PACKET_MUTABLE_OPENING_INPUTS_SHA256
    ):
        raise NbaApiCompetitionIdentityError("repair-11 input inventory authority drifted")
    if (
        not _exact_typed_equal(
            immutable[96],
            {"path": _ORIGINAL_TASK_PACKET, "sha256": _ORIGINAL_TASK_PACKET_SHA256},
        )
        or not _exact_typed_equal(
            immutable[97],
            {"path": _REPAIR_1_TASK_PACKET, "sha256": _REPAIR_1_TASK_PACKET_SHA256},
        )
        or not _exact_typed_equal(
            immutable[98],
            {"path": _REPAIR_2_TASK_PACKET, "sha256": _REPAIR_2_TASK_PACKET_SHA256},
        )
        or not _exact_typed_equal(
            immutable[99],
            {"path": _REPAIR_3_TASK_PACKET, "sha256": _REPAIR_3_TASK_PACKET_SHA256},
        )
        or not _exact_typed_equal(
            immutable[100],
            {"path": _REPAIR_4_TASK_PACKET, "sha256": _REPAIR_4_TASK_PACKET_SHA256},
        )
        or not _exact_typed_equal(
            immutable[101],
            {"path": _REPAIR_5_TASK_PACKET, "sha256": _REPAIR_5_TASK_PACKET_SHA256},
        )
        or not _exact_typed_equal(
            immutable[102],
            {"path": _REPAIR_6_TASK_PACKET, "sha256": _REPAIR_6_TASK_PACKET_SHA256},
        )
        or not _exact_typed_equal(
            immutable[103],
            {"path": _REPAIR_7_TASK_PACKET, "sha256": _REPAIR_7_TASK_PACKET_SHA256},
        )
        or not _exact_typed_equal(
            immutable[104],
            {"path": _REPAIR_8_TASK_PACKET, "sha256": _REPAIR_8_TASK_PACKET_SHA256},
        )
        or not _exact_typed_equal(
            immutable[105],
            {"path": _REPAIR_9_TASK_PACKET, "sha256": _REPAIR_9_TASK_PACKET_SHA256},
        )
        or not _exact_typed_equal(
            immutable[106],
            {"path": _REPAIR_10_TASK_PACKET, "sha256": _REPAIR_10_TASK_PACKET_SHA256},
        )
        or not _exact_typed_equal(
            immutable[125],
            {
                "path": _APPLICABILITY_RESOURCE_PATH,
                "sha256": _HISTORICAL_TASK_PACKET_APPLICABILITY_RESOURCE_SHA256,
            },
        )
    ):
        raise NbaApiCompetitionIdentityError("repair-11 immutable input order drifted")
    successor = _packet_dict(packet, "one_successor_design")
    if (
        successor.get("current_dispatch_authority_after_R0") != _TASK_PACKET
        or successor.get("original_packet_disposition")
        != (
            "repair-10 is the direct immutable superseded authority; repair-9 through "
            "repair-1 and original A1.3a remain nested immutable historical provenance only"
        )
        or successor.get("original_receipt_or_review_creation_permitted") is not False
    ):
        raise NbaApiCompetitionIdentityError("A1.3a-repair-11 successor authority drifted")
    return packet


@lru_cache(maxsize=1)
def _identity_contract_payload() -> dict[str, object]:
    _raw, packet = _read_authenticated_packet(
        _IDENTITY_CONTRACT_PACKET,
        _IDENTITY_CONTRACT_PACKET_SHA256,
        label="A1.2e identity-contract TaskPacket",
        task_id="A1.2e",
    )
    inventory = _exact_rows(
        packet.get("source_inventory_inputs"),
        label="source inventory inputs",
        count=25,
    )
    inventory_digest = _require_sha256(
        packet.get("source_inventory_inputs_sha256"), "source_inventory_inputs_sha256"
    )
    if inventory_digest != _SOURCE_INVENTORY_INPUTS_SHA256:
        raise NbaApiCompetitionIdentityError("source inventory authority drifted")
    if _digest(inventory) != inventory_digest:
        raise NbaApiCompetitionIdentityError("source inventory contract digest drifted")
    surfaces = _exact_rows(
        packet.get("qualified_surface_contracts"),
        label="qualified surface contracts",
        count=8,
    )
    for row in surfaces:
        body = dict(row)
        supplied = body.pop("surface_contract_sha256", None)
        if _require_sha256(supplied, "surface_contract_sha256") != _digest(body):
            raise NbaApiCompetitionIdentityError("qualified surface self-digest drifted")
    if _digest(surfaces) != _QUALIFIED_SURFACE_CONTRACTS_SHA256:
        raise NbaApiCompetitionIdentityError("qualified surface inventory digest drifted")
    return packet


@lru_cache(maxsize=1)
def _implicit_supersession_proof() -> tuple[dict[str, object], str]:
    from nbadb.core.nba_api_implicit_competition_verifier import (
        _build_implicit_supersession_proof,
    )

    body, canonical, supplied = _build_implicit_supersession_proof()
    if (
        type(body) is not dict
        or type(canonical) is not bytes
        or supplied != _IMPLICIT_SUPERSESSION_PROOF_SHA256
        or canonical != _canonical_bytes(body)
        or hashlib.sha256(canonical).hexdigest() != supplied
    ):
        raise NbaApiCompetitionIdentityError("W5 implicit supersession proof drifted")
    return copy.deepcopy(body), supplied


@lru_cache(maxsize=1)
def _explicit_source_cell_index() -> dict[tuple[str, str], CompetitionApplicabilityCell]:
    """Index the sealed explicit source cells by canonical ID and digest."""

    index: dict[tuple[str, str], CompetitionApplicabilityCell] = {}
    for cell in pinned_competition_applicability_authority().alias_role_cells:
        if cell.repo_endpoint_name is None:
            raise NbaApiCompetitionIdentityError(
                "explicit applicability cell has no repository endpoint"
            )
        source_cell_id = (
            f"alias-role:{cell.repo_endpoint_name}:{cell.provider_occurrence_id}:{cell.league_id}"
        )
        key = (source_cell_id, _digest(cell.to_dict()))
        if key in index:
            raise NbaApiCompetitionIdentityError("explicit applicability cell is duplicated")
        index[key] = cell
    return index


@lru_cache(maxsize=1)
def _implicit_source_indexes() -> tuple[
    dict[tuple[str, str], ImplicitCompetitionCell],
    dict[str, tuple[str, str | None]],
]:
    """Index sealed implicit cells and their exact endpoint-root projections."""

    authority = pinned_implicit_competition_authority()
    cells: dict[tuple[str, str], ImplicitCompetitionCell] = {}
    for cell in authority.alias_competition_cells:
        key = (cell.cell_id, _digest(cell.to_dict()))
        if key in cells:
            raise NbaApiCompetitionIdentityError("implicit competition cell is duplicated")
        cells[key] = cell
    roots: dict[str, tuple[str, str | None]] = {}
    for endpoint_binding in authority.endpoint_bindings:
        if endpoint_binding.binding_sha256 in roots:
            raise NbaApiCompetitionIdentityError("implicit endpoint root is duplicated")
        roots[endpoint_binding.binding_sha256] = (
            endpoint_binding.root_requirement.root_mode,
            endpoint_binding.root_requirement.static_chain_sha256,
        )
    return cells, roots


@dataclass(frozen=True, slots=True)
class CompetitionRoleBinding:
    """One exact role-aware source cell projected into identity authority."""

    binding_strategy: BindingStrategy
    source_authority_kind: str
    source_authority_sha256: str
    source_cell_id: str
    source_cell_sha256: str
    constructor_name: str | None
    provider_occurrence_id: str | None
    wire_name: str | None
    temporal_companion_occurrence_ids: tuple[str, ...]
    participant_axis_binding: str | None
    root_binding_sha256: str | None
    root_kind: str | None
    root_mode: str | None
    root_state: str | None
    static_chain_sha256: str | None
    role_binding_sha256: str

    def __post_init__(self) -> None:
        self._revalidate()

    def _body(self) -> dict[str, object]:
        return {
            "binding_strategy": self.binding_strategy,
            "source_authority_kind": self.source_authority_kind,
            "source_authority_sha256": self.source_authority_sha256,
            "source_cell_id": self.source_cell_id,
            "source_cell_sha256": self.source_cell_sha256,
            "constructor_name": self.constructor_name,
            "provider_occurrence_id": self.provider_occurrence_id,
            "wire_name": self.wire_name,
            "temporal_companion_occurrence_ids": list(self.temporal_companion_occurrence_ids),
            "participant_axis_binding": self.participant_axis_binding,
            "root_binding_sha256": self.root_binding_sha256,
            "root_kind": self.root_kind,
            "root_mode": self.root_mode,
            "root_state": self.root_state,
            "static_chain_sha256": self.static_chain_sha256,
        }

    def _source_projection(self) -> tuple[str, str, str, str, str, str]:
        """Reproduce the one exact predecessor cell owned by this binding."""

        if self.binding_strategy == "explicit_applicability_cell":
            cell = _explicit_source_cell_index().get((self.source_cell_id, self.source_cell_sha256))
            if cell is None:
                raise NbaApiCompetitionIdentityError(
                    "explicit role binding is not one exact applicability cell"
                )
            repo_endpoint_name = cell.repo_endpoint_name
            if repo_endpoint_name is None:
                raise NbaApiCompetitionIdentityError(
                    "explicit applicability cell has no repository endpoint"
                )
            if (
                self.constructor_name != cell.constructor_name
                or self.provider_occurrence_id != cell.provider_occurrence_id
                or self.wire_name != cell.wire_name
                or self.temporal_companion_occurrence_ids != cell.temporal_companion_occurrence_ids
                or self.participant_axis_binding != cell.participant_axis_binding
            ):
                raise NbaApiCompetitionIdentityError(
                    "explicit role binding differs from its applicability cell"
                )
            return (
                "stats",
                f"stats:{cell.provider_endpoint_id}",
                cell.provider_endpoint_id,
                repo_endpoint_name,
                cell.league_id,
                cell.symbol,
            )

        cells, roots = _implicit_source_indexes()
        cell = cells.get((self.source_cell_id, self.source_cell_sha256))
        if cell is None:
            raise NbaApiCompetitionIdentityError(
                "implicit role binding is not one exact alias competition cell"
            )
        repo_endpoint_name = cell.repo_endpoint_name
        if repo_endpoint_name is None:
            raise NbaApiCompetitionIdentityError(
                "implicit competition cell has no repository endpoint"
            )
        root_projection = roots.get(cell.root_binding_sha256)
        if root_projection is None:
            raise NbaApiCompetitionIdentityError("implicit role binding has no exact endpoint root")
        root_mode, static_chain_sha256 = root_projection
        if (
            self.root_binding_sha256 != cell.root_binding_sha256
            or self.root_kind != cell.root_kind
            or self.root_state != cell.root_state
            or self.root_mode != root_mode
            or self.static_chain_sha256 != static_chain_sha256
        ):
            raise NbaApiCompetitionIdentityError(
                "implicit role binding differs from its exact endpoint root"
            )
        return (
            cell.source_family,
            cell.physical_endpoint_key,
            cell.provider_endpoint_id,
            repo_endpoint_name,
            cell.league_id,
            cell.symbol,
        )

    def _revalidate(self) -> None:
        if (
            type(self.binding_strategy) is not str
            or self.binding_strategy not in _BINDING_STRATEGIES
        ):
            raise NbaApiCompetitionIdentityError("role binding strategy is invalid")
        _require_text(self.source_authority_kind, "source_authority_kind")
        _require_sha256(self.source_authority_sha256, "source_authority_sha256")
        _require_text(self.source_cell_id, "source_cell_id")
        _require_sha256(self.source_cell_sha256, "source_cell_sha256")
        for name in (
            "constructor_name",
            "provider_occurrence_id",
            "wire_name",
            "participant_axis_binding",
            "root_kind",
            "root_mode",
            "root_state",
        ):
            _require_optional_text(getattr(self, name), name)
        for name in ("root_binding_sha256", "static_chain_sha256"):
            value = getattr(self, name)
            if value is not None:
                _require_sha256(value, name)
        if type(self.temporal_companion_occurrence_ids) is not tuple or any(
            type(item) is not str or not item for item in self.temporal_companion_occurrence_ids
        ):
            raise NbaApiCompetitionIdentityError(
                "temporal companion occurrence IDs must be an exact string tuple"
            )
        explicit = self.binding_strategy == "explicit_applicability_cell"
        if explicit:
            if (
                self.source_authority_kind != "competition_applicability"
                or self.source_authority_sha256 != _APPLICABILITY_AUTHORITY_SHA256
                or any(
                    value is None
                    for value in (
                        self.constructor_name,
                        self.provider_occurrence_id,
                        self.wire_name,
                        self.participant_axis_binding,
                    )
                )
                or any(
                    value is not None
                    for value in (
                        self.root_binding_sha256,
                        self.root_kind,
                        self.root_mode,
                        self.root_state,
                        self.static_chain_sha256,
                    )
                )
            ):
                raise NbaApiCompetitionIdentityError("explicit role binding fields drifted")
        elif (
            self.source_authority_kind != "implicit_competition"
            or self.source_authority_sha256 != _IMPLICIT_AUTHORITY_SHA256
            or self.constructor_name is not None
            or self.provider_occurrence_id is not None
            or self.wire_name is not None
            or self.temporal_companion_occurrence_ids
            or self.participant_axis_binding is not None
            or any(
                value is None
                for value in (
                    self.root_binding_sha256,
                    self.root_kind,
                    self.root_mode,
                    self.root_state,
                )
            )
            or (self.binding_strategy in {"fixed_static_root", "root_not_exposed"})
            != (self.static_chain_sha256 is not None)
        ):
            raise NbaApiCompetitionIdentityError("implicit role binding fields drifted")
        self._source_projection()
        if _require_sha256(self.role_binding_sha256, "role_binding_sha256") != _digest(
            self._body()
        ):
            raise NbaApiCompetitionIdentityError("role binding self-digest is invalid")

    def to_dict(self) -> dict[str, object]:
        self._revalidate()
        return {**self._body(), "role_binding_sha256": self.role_binding_sha256}


@dataclass(frozen=True, slots=True)
class CompetitionIdentityRequirement:
    """One competition-qualified role requirement."""

    requirement_id: str
    source_family: str
    physical_endpoint_key: str
    provider_endpoint_id: str
    repo_endpoint_name: str
    league_id: str
    symbol: str
    competition_scope_sha256: str
    role_binding: CompetitionRoleBinding
    executable: bool
    provider_availability_status: str
    request_terminal_state: str
    requirement_sha256: str

    def __post_init__(self) -> None:
        self._revalidate()

    def _body(self) -> dict[str, object]:
        return {
            "requirement_id": self.requirement_id,
            "source_family": self.source_family,
            "physical_endpoint_key": self.physical_endpoint_key,
            "provider_endpoint_id": self.provider_endpoint_id,
            "repo_endpoint_name": self.repo_endpoint_name,
            "league_id": self.league_id,
            "symbol": self.symbol,
            "competition_scope_sha256": self.competition_scope_sha256,
            "role_binding": self.role_binding.to_dict(),
            "executable": self.executable,
            "provider_availability_status": self.provider_availability_status,
            "request_terminal_state": self.request_terminal_state,
        }

    def _revalidate(self) -> None:
        for name in (
            "requirement_id",
            "source_family",
            "physical_endpoint_key",
            "provider_endpoint_id",
            "repo_endpoint_name",
            "league_id",
            "symbol",
        ):
            _require_text(getattr(self, name), name)
        if type(self.role_binding) is not CompetitionRoleBinding:
            raise NbaApiCompetitionIdentityError("requirement role binding type is invalid")
        self.role_binding._revalidate()
        if (
            self.source_family,
            self.physical_endpoint_key,
            self.provider_endpoint_id,
            self.repo_endpoint_name,
            self.league_id,
            self.symbol,
        ) != self.role_binding._source_projection():
            raise NbaApiCompetitionIdentityError(
                "requirement differs from its exact predecessor source cell"
            )
        if type(self.executable) is not bool:
            raise NbaApiCompetitionIdentityError("requirement executable must be an exact boolean")
        expected_executable = self.role_binding.binding_strategy != "root_not_exposed"
        if self.executable is not expected_executable:
            raise NbaApiCompetitionIdentityError("requirement executable state drifted")
        if self.provider_availability_status != "unknown":
            raise NbaApiCompetitionIdentityError("provider availability must remain unknown")
        if self.request_terminal_state != "not_asserted":
            raise NbaApiCompetitionIdentityError("request terminal state must remain unasserted")
        expected_id = (
            f"competition-requirement:{self.source_family}:{self.repo_endpoint_name}:"
            f"{self.role_binding.source_cell_id}:{self.league_id}"
        )
        if self.requirement_id != expected_id:
            raise NbaApiCompetitionIdentityError("requirement identifier is noncanonical")
        scope = _digest(
            {
                "domain_separator": _COMPETITION_SCOPE_DOMAIN,
                "competition_authority_sha256": _COMPETITION_AUTHORITY_SHA256,
                "league_id": self.league_id,
                "symbol": self.symbol,
            }
        )
        if _require_sha256(self.competition_scope_sha256, "competition_scope_sha256") != scope:
            raise NbaApiCompetitionIdentityError("competition scope digest is invalid")
        expected_requirement = _digest(
            {"domain_separator": _COMPETITION_SCOPE_DOMAIN, "requirement": self._body()}
        )
        if _require_sha256(self.requirement_sha256, "requirement_sha256") != expected_requirement:
            raise NbaApiCompetitionIdentityError("requirement self-digest is invalid")

    def to_dict(self) -> dict[str, object]:
        self._revalidate()
        return {**self._body(), "requirement_sha256": self.requirement_sha256}


def _role_binding(
    *,
    binding_strategy: BindingStrategy,
    source_authority_kind: str,
    source_authority_sha256: str,
    source_cell_id: str,
    source_cell_sha256: str,
    constructor_name: str | None,
    provider_occurrence_id: str | None,
    wire_name: str | None,
    temporal_companion_occurrence_ids: tuple[str, ...],
    participant_axis_binding: str | None,
    root_binding_sha256: str | None,
    root_kind: str | None,
    root_mode: str | None,
    root_state: str | None,
    static_chain_sha256: str | None,
) -> CompetitionRoleBinding:
    body: dict[str, object] = {
        "binding_strategy": binding_strategy,
        "source_authority_kind": source_authority_kind,
        "source_authority_sha256": source_authority_sha256,
        "source_cell_id": source_cell_id,
        "source_cell_sha256": source_cell_sha256,
        "constructor_name": constructor_name,
        "provider_occurrence_id": provider_occurrence_id,
        "wire_name": wire_name,
        "temporal_companion_occurrence_ids": list(temporal_companion_occurrence_ids),
        "participant_axis_binding": participant_axis_binding,
        "root_binding_sha256": root_binding_sha256,
        "root_kind": root_kind,
        "root_mode": root_mode,
        "root_state": root_state,
        "static_chain_sha256": static_chain_sha256,
    }
    return CompetitionRoleBinding(
        binding_strategy=binding_strategy,
        source_authority_kind=source_authority_kind,
        source_authority_sha256=source_authority_sha256,
        source_cell_id=source_cell_id,
        source_cell_sha256=source_cell_sha256,
        constructor_name=constructor_name,
        provider_occurrence_id=provider_occurrence_id,
        wire_name=wire_name,
        temporal_companion_occurrence_ids=temporal_companion_occurrence_ids,
        participant_axis_binding=participant_axis_binding,
        root_binding_sha256=root_binding_sha256,
        root_kind=root_kind,
        root_mode=root_mode,
        root_state=root_state,
        static_chain_sha256=static_chain_sha256,
        role_binding_sha256=_digest(body),
    )


def _requirement(
    *,
    source_family: str,
    physical_endpoint_key: str,
    provider_endpoint_id: str,
    repo_endpoint_name: str,
    league_id: str,
    symbol: str,
    role_binding: CompetitionRoleBinding,
    executable: bool,
) -> CompetitionIdentityRequirement:
    scope = _digest(
        {
            "domain_separator": _COMPETITION_SCOPE_DOMAIN,
            "competition_authority_sha256": _COMPETITION_AUTHORITY_SHA256,
            "league_id": league_id,
            "symbol": symbol,
        }
    )
    requirement_id = (
        f"competition-requirement:{source_family}:{repo_endpoint_name}:"
        f"{role_binding.source_cell_id}:{league_id}"
    )
    body: dict[str, object] = {
        "requirement_id": requirement_id,
        "source_family": source_family,
        "physical_endpoint_key": physical_endpoint_key,
        "provider_endpoint_id": provider_endpoint_id,
        "repo_endpoint_name": repo_endpoint_name,
        "league_id": league_id,
        "symbol": symbol,
        "competition_scope_sha256": scope,
        "role_binding": role_binding.to_dict(),
        "executable": executable,
        "provider_availability_status": "unknown",
        "request_terminal_state": "not_asserted",
    }
    return CompetitionIdentityRequirement(
        requirement_id=requirement_id,
        source_family=source_family,
        physical_endpoint_key=physical_endpoint_key,
        provider_endpoint_id=provider_endpoint_id,
        repo_endpoint_name=repo_endpoint_name,
        league_id=league_id,
        symbol=symbol,
        competition_scope_sha256=scope,
        role_binding=role_binding,
        executable=executable,
        provider_availability_status="unknown",
        request_terminal_state="not_asserted",
        requirement_sha256=_digest(
            {"domain_separator": _COMPETITION_SCOPE_DOMAIN, "requirement": body}
        ),
    )


@lru_cache(maxsize=1)
def compile_competition_identity_requirements() -> tuple[CompetitionIdentityRequirement, ...]:
    """Compile all 635 explicit and 180 implicit alias-role requirements."""

    _task_packet_payload()
    _identity_contract_payload()
    competition = pinned_competition_authority()
    applicability = pinned_competition_applicability_authority()
    implicit = pinned_implicit_competition_authority()
    request_surface = pinned_request_surface_authority()
    if competition.authority_sha256 != _COMPETITION_AUTHORITY_SHA256:
        raise NbaApiCompetitionIdentityError("competition value authority drifted")
    if applicability.authority_sha256 != _APPLICABILITY_AUTHORITY_SHA256:
        raise NbaApiCompetitionIdentityError("competition applicability authority drifted")
    if implicit.authority_sha256 != _IMPLICIT_AUTHORITY_SHA256:
        raise NbaApiCompetitionIdentityError("implicit competition authority drifted")
    if request_surface.surface_sha256 != _REQUEST_SURFACE_SHA256:
        raise NbaApiCompetitionIdentityError("request surface authority drifted")

    stats_endpoint_ids = {
        endpoint.endpoint_id
        for endpoint in request_surface.endpoints
        if endpoint.source_family == "stats"
    }

    requirements: list[CompetitionIdentityRequirement] = []
    for cell in applicability.alias_role_cells:
        if type(cell) is not CompetitionApplicabilityCell or cell.repo_endpoint_name is None:
            raise NbaApiCompetitionIdentityError("explicit applicability cell is not exact")
        source_family = "stats"
        if cell.provider_endpoint_id not in stats_endpoint_ids:
            raise NbaApiCompetitionIdentityError("explicit applicability endpoint join drifted")
        source_cell_id = (
            f"alias-role:{cell.repo_endpoint_name}:{cell.provider_occurrence_id}:{cell.league_id}"
        )
        role = _role_binding(
            binding_strategy="explicit_applicability_cell",
            source_authority_kind="competition_applicability",
            source_authority_sha256=applicability.authority_sha256,
            source_cell_id=source_cell_id,
            source_cell_sha256=_digest(cell.to_dict()),
            constructor_name=cell.constructor_name,
            provider_occurrence_id=cell.provider_occurrence_id,
            wire_name=cell.wire_name,
            temporal_companion_occurrence_ids=cell.temporal_companion_occurrence_ids,
            participant_axis_binding=cell.participant_axis_binding,
            root_binding_sha256=None,
            root_kind=None,
            root_mode=None,
            root_state=None,
            static_chain_sha256=None,
        )
        requirements.append(
            _requirement(
                source_family=source_family,
                physical_endpoint_key=f"{source_family}:{cell.provider_endpoint_id}",
                provider_endpoint_id=cell.provider_endpoint_id,
                repo_endpoint_name=cell.repo_endpoint_name,
                league_id=cell.league_id,
                symbol=cell.symbol,
                role_binding=role,
                executable=True,
            )
        )

    bindings = {item.binding_sha256: item for item in implicit.endpoint_bindings}
    for cell in implicit.alias_competition_cells:
        if type(cell) is not ImplicitCompetitionCell or cell.repo_endpoint_name is None:
            raise NbaApiCompetitionIdentityError("implicit alias cell is not exact")
        endpoint_binding = bindings.get(cell.root_binding_sha256)
        if endpoint_binding is None:
            raise NbaApiCompetitionIdentityError("implicit alias root binding is missing")
        if (
            endpoint_binding.physical_endpoint_key != cell.physical_endpoint_key
            or endpoint_binding.provider_endpoint_id != cell.provider_endpoint_id
            or endpoint_binding.repo_endpoint_name != cell.repo_endpoint_name
            or endpoint_binding.source_family != cell.source_family
        ):
            raise NbaApiCompetitionIdentityError(
                "implicit alias endpoint binding does not reproduce the source cell"
            )
        strategy_by_state: dict[str, BindingStrategy] = {
            "receipt_bound_root_required": "receipt_bound_dynamic_root",
            "fixed_static_root": "fixed_static_root",
            "root_not_exposed": "root_not_exposed",
        }
        try:
            strategy = strategy_by_state[cell.root_state]
        except KeyError as exc:
            raise NbaApiCompetitionIdentityError("implicit root state is unsupported") from exc
        root_requirement = endpoint_binding.root_requirement
        static_chain = (
            root_requirement.static_chain_sha256
            if strategy in {"fixed_static_root", "root_not_exposed"}
            else None
        )
        role = _role_binding(
            binding_strategy=strategy,
            source_authority_kind="implicit_competition",
            source_authority_sha256=implicit.authority_sha256,
            source_cell_id=cell.cell_id,
            source_cell_sha256=_digest(cell.to_dict()),
            constructor_name=None,
            provider_occurrence_id=None,
            wire_name=None,
            temporal_companion_occurrence_ids=(),
            participant_axis_binding=None,
            root_binding_sha256=cell.root_binding_sha256,
            root_kind=cell.root_kind,
            root_mode=root_requirement.root_mode,
            root_state=cell.root_state,
            static_chain_sha256=static_chain,
        )
        requirements.append(
            _requirement(
                source_family=cell.source_family,
                physical_endpoint_key=cell.physical_endpoint_key,
                provider_endpoint_id=cell.provider_endpoint_id,
                repo_endpoint_name=cell.repo_endpoint_name,
                league_id=cell.league_id,
                symbol=cell.symbol,
                role_binding=role,
                executable=strategy != "root_not_exposed",
            )
        )

    compiled = tuple(sorted(requirements, key=lambda item: item.requirement_id))
    counts = Counter(item.role_binding.binding_strategy for item in compiled)
    if (
        len(compiled) != 815
        or len({item.requirement_id for item in compiled}) != 815
        or dict(sorted(counts.items())) != _EXPECTED_BINDING_COUNTS
        or sum(item.executable for item in compiled) != 799
    ):
        raise NbaApiCompetitionIdentityError("competition identity denominator drifted")
    return compiled


def _normalized_requirement(
    requirement: object,
) -> CompetitionIdentityRequirement:
    if type(requirement) is not CompetitionIdentityRequirement:
        raise NbaApiCompetitionIdentityError(
            "requirement must be an exact CompetitionIdentityRequirement"
        )
    typed = requirement
    typed._revalidate()
    matches = [
        item
        for item in compile_competition_identity_requirements()
        if item.requirement_sha256 == typed.requirement_sha256
    ]
    if len(matches) != 1 or not _exact_typed_equal(typed, matches[0]):
        raise NbaApiCompetitionIdentityError("requirement is not exact and pinned")
    return matches[0]


def _normalized_provider_request(provider_request: object) -> CanonicalProviderRequest:
    if type(provider_request) is not CanonicalProviderRequest:
        raise NbaApiCompetitionIdentityError(
            "provider request must be an exact CanonicalProviderRequest"
        )
    request = provider_request
    for name in (
        "request_surface_sha256",
        "runtime_contract_payload_sha256",
        "source_family",
        "endpoint_id",
        "request_method",
        "url_path",
        "query_string",
        "full_url",
        "provider_request_sha256",
    ):
        if type(getattr(request, name)) is not str:
            raise NbaApiCompetitionIdentityError("provider request scalar type drifted")
    if type(request.materialized_parameters) is not tuple:
        raise NbaApiCompetitionIdentityError("provider parameters must be an exact tuple")
    for item in request.materialized_parameters:
        if type(item) is not tuple or len(item) != 2 or type(item[0]) is not str:
            raise NbaApiCompetitionIdentityError("provider parameter entry type drifted")
        _exact_json_scalar(item[1], field_name="provider parameter value")
    try:
        reconstructed = CanonicalProviderRequest(
            request_surface_sha256=request.request_surface_sha256,
            runtime_contract_payload_sha256=request.runtime_contract_payload_sha256,
            source_family=request.source_family,
            endpoint_id=request.endpoint_id,
            request_method=request.request_method,
            url_path=request.url_path,
            query_string=request.query_string,
            full_url=request.full_url,
            materialized_parameters=request.materialized_parameters,
            provider_request_sha256=request.provider_request_sha256,
        )
    except (TypeError, ValueError) as exc:
        raise NbaApiCompetitionIdentityError("provider request did not revalidate") from exc
    if not _exact_typed_equal(request, reconstructed):
        raise NbaApiCompetitionIdentityError("provider request public state drifted")
    return reconstructed


def _dynamic_endpoint_binding(requirement: CompetitionIdentityRequirement) -> Any:
    authority = pinned_implicit_competition_authority()
    matches = [
        item
        for item in authority.endpoint_bindings
        if item.binding_sha256 == requirement.role_binding.root_binding_sha256
    ]
    if len(matches) != 1:
        raise NbaApiCompetitionIdentityError("dynamic endpoint binding is not unique")
    return matches[0]


def _validate_explicit_request(
    requirement: CompetitionIdentityRequirement,
    request: CanonicalProviderRequest,
) -> None:
    role = requirement.role_binding
    if role.binding_strategy != "explicit_applicability_cell" or not requirement.executable:
        raise NbaApiCompetitionIdentityError("requirement is not an executable explicit cell")
    if (
        request.source_family != requirement.source_family
        or request.endpoint_id != requirement.provider_endpoint_id
    ):
        raise NbaApiCompetitionIdentityError("provider request endpoint differs from requirement")
    matches = [
        value for name, value in request.materialized_parameters if name == role.constructor_name
    ]
    if len(matches) != 1 or type(matches[0]) is not str or matches[0] != requirement.league_id:
        raise NbaApiCompetitionIdentityError(
            "provider request competition role differs from requirement"
        )


def _validate_dynamic_request(
    requirement: CompetitionIdentityRequirement,
    receipt: ReceiptBoundCompetitionRoot,
    request: CanonicalProviderRequest,
) -> None:
    if (
        requirement.role_binding.binding_strategy != "receipt_bound_dynamic_root"
        or not requirement.executable
    ):
        raise NbaApiCompetitionIdentityError("requirement is not an executable dynamic root")
    if type(receipt) is not ReceiptBoundCompetitionRoot:
        raise NbaApiCompetitionIdentityError(
            "root receipt must be an exact ReceiptBoundCompetitionRoot"
        )
    try:
        receipt._revalidate()
    except (TypeError, ValueError) as exc:
        raise NbaApiCompetitionIdentityError("dynamic root receipt did not revalidate") from exc
    if (
        request.source_family != requirement.source_family
        or request.endpoint_id != requirement.provider_endpoint_id
        or receipt.root_binding_sha256 != requirement.role_binding.root_binding_sha256
        or receipt.league_id != requirement.league_id
        or receipt.source_endpoint_id != requirement.provider_endpoint_id
        or receipt.source_request_identity_sha256 != request.provider_request_sha256
    ):
        raise NbaApiCompetitionIdentityError("dynamic root receipt/request binding drifted")
    endpoint_binding = _dynamic_endpoint_binding(requirement)
    root_requirement = endpoint_binding.root_requirement
    if root_requirement.root_mode == "request_parameter":
        occurrence_id = root_requirement.provider_occurrence_id
        endpoint = pinned_request_surface_authority().endpoint(
            cast("Any", request.source_family), request.endpoint_id
        )
        parameters = [item for item in endpoint.parameters if item.occurrence_id == occurrence_id]
        if len(parameters) != 1:
            raise NbaApiCompetitionIdentityError("dynamic request root occurrence is not unique")
        root_name = parameters[0].name
        values = [value for name, value in request.materialized_parameters if name == root_name]
        if (
            len(values) != 1
            or type(values[0]) is not type(receipt.root_value)
            or values[0] != receipt.root_value
        ):
            raise NbaApiCompetitionIdentityError("dynamic request root value drifted")
    elif root_requirement.root_mode in {"response_game_collection", "response_game_join"}:
        if root_requirement.provider_occurrence_id is not None:
            raise NbaApiCompetitionIdentityError("response root invented a request parameter")
    else:
        raise NbaApiCompetitionIdentityError("dynamic root mode is unsupported")


def _request_public_body(
    *,
    requirement: CompetitionIdentityRequirement,
    request_kind: RequestKind,
    source_evidence_sha256: str,
    provider_request_sha256: str | None,
) -> dict[str, object]:
    return {
        "domain_separator": _SOURCE_REQUEST_DOMAIN,
        "competition_scope_sha256": requirement.competition_scope_sha256,
        "requirement_sha256": requirement.requirement_sha256,
        "role_binding_sha256": requirement.role_binding.role_binding_sha256,
        "request_kind": request_kind,
        "source_evidence_sha256": source_evidence_sha256,
        "provider_request_sha256": provider_request_sha256,
    }


@dataclass(frozen=True, slots=True)
class CompetitionQualifiedRequest:
    """One provider request or static source bound to a competition requirement."""

    competition_scope_sha256: str
    requirement_sha256: str
    role_binding_sha256: str
    request_kind: RequestKind
    source_evidence_sha256: str
    provider_request_sha256: str | None
    source_request_sha256: str
    requirement_evidence: InitVar[CompetitionIdentityRequirement]
    provider_request_evidence: InitVar[CanonicalProviderRequest | None]
    root_receipt_evidence: InitVar[ReceiptBoundCompetitionRoot | None]
    _requirement_evidence: CompetitionIdentityRequirement = field(
        init=False, repr=False, compare=False
    )
    _provider_request_evidence: CanonicalProviderRequest | None = field(
        init=False, repr=False, compare=False
    )
    _root_receipt_evidence: ReceiptBoundCompetitionRoot | None = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(
        self,
        requirement_evidence: CompetitionIdentityRequirement,
        provider_request_evidence: CanonicalProviderRequest | None,
        root_receipt_evidence: ReceiptBoundCompetitionRoot | None,
    ) -> None:
        object.__setattr__(self, "_requirement_evidence", requirement_evidence)
        object.__setattr__(self, "_provider_request_evidence", provider_request_evidence)
        object.__setattr__(self, "_root_receipt_evidence", root_receipt_evidence)
        self._revalidate()

    def _revalidate(
        self,
    ) -> tuple[
        CompetitionIdentityRequirement,
        CanonicalProviderRequest | None,
        ReceiptBoundCompetitionRoot | None,
    ]:
        requirement = _normalized_requirement(self._requirement_evidence)
        role = requirement.role_binding
        provider: CanonicalProviderRequest | None = None
        receipt: ReceiptBoundCompetitionRoot | None = None
        if role.binding_strategy == "explicit_applicability_cell":
            if self._root_receipt_evidence is not None:
                raise NbaApiCompetitionIdentityError("explicit request retained a root receipt")
            provider = _normalized_provider_request(self._provider_request_evidence)
            _validate_explicit_request(requirement, provider)
            expected_kind: RequestKind = "provider_request"
            expected_source = role.source_cell_sha256
            expected_provider = provider.provider_request_sha256
        elif role.binding_strategy == "receipt_bound_dynamic_root":
            provider = _normalized_provider_request(self._provider_request_evidence)
            if type(self._root_receipt_evidence) is not ReceiptBoundCompetitionRoot:
                raise NbaApiCompetitionIdentityError("dynamic request lost its root receipt")
            receipt = self._root_receipt_evidence
            _validate_dynamic_request(requirement, receipt, provider)
            expected_kind = "provider_request"
            expected_source = receipt.receipt_sha256
            expected_provider = provider.provider_request_sha256
        elif role.binding_strategy == "fixed_static_root":
            if (
                self._provider_request_evidence is not None
                or self._root_receipt_evidence is not None
            ):
                raise NbaApiCompetitionIdentityError("static source retained transport evidence")
            if not requirement.executable or role.static_chain_sha256 is None:
                raise NbaApiCompetitionIdentityError("fixed Static requirement is invalid")
            expected_kind = "static_source"
            expected_source = role.static_chain_sha256
            expected_provider = None
        else:
            raise NbaApiCompetitionIdentityError("root-not-exposed request is nonconstructible")
        expected_body = _request_public_body(
            requirement=requirement,
            request_kind=expected_kind,
            source_evidence_sha256=expected_source,
            provider_request_sha256=expected_provider,
        )
        observed = (
            self.competition_scope_sha256,
            self.requirement_sha256,
            self.role_binding_sha256,
            self.request_kind,
            self.source_evidence_sha256,
            self.provider_request_sha256,
            self.source_request_sha256,
        )
        expected = (
            requirement.competition_scope_sha256,
            requirement.requirement_sha256,
            role.role_binding_sha256,
            expected_kind,
            expected_source,
            expected_provider,
            _digest(expected_body),
        )
        if not _exact_typed_equal(observed, expected):
            raise NbaApiCompetitionIdentityError("competition-qualified request identity drifted")
        return requirement, provider, receipt

    def to_dict(self) -> dict[str, object]:
        self._revalidate()
        return {
            "competition_scope_sha256": self.competition_scope_sha256,
            "requirement_sha256": self.requirement_sha256,
            "role_binding_sha256": self.role_binding_sha256,
            "request_kind": self.request_kind,
            "source_evidence_sha256": self.source_evidence_sha256,
            "provider_request_sha256": self.provider_request_sha256,
            "source_request_sha256": self.source_request_sha256,
        }


def _qualified_request(
    requirement: CompetitionIdentityRequirement,
    *,
    request_kind: RequestKind,
    source_evidence_sha256: str,
    provider_request: CanonicalProviderRequest | None,
    root_receipt: ReceiptBoundCompetitionRoot | None,
) -> CompetitionQualifiedRequest:
    body = _request_public_body(
        requirement=requirement,
        request_kind=request_kind,
        source_evidence_sha256=source_evidence_sha256,
        provider_request_sha256=(
            None if provider_request is None else provider_request.provider_request_sha256
        ),
    )
    return CompetitionQualifiedRequest(
        competition_scope_sha256=requirement.competition_scope_sha256,
        requirement_sha256=requirement.requirement_sha256,
        role_binding_sha256=requirement.role_binding.role_binding_sha256,
        request_kind=request_kind,
        source_evidence_sha256=source_evidence_sha256,
        provider_request_sha256=(
            None if provider_request is None else provider_request.provider_request_sha256
        ),
        source_request_sha256=_digest(body),
        requirement_evidence=requirement,
        provider_request_evidence=provider_request,
        root_receipt_evidence=root_receipt,
    )


def bind_explicit_competition_request(
    requirement: CompetitionIdentityRequirement,
    provider_request: CanonicalProviderRequest,
) -> CompetitionQualifiedRequest:
    """Bind one exact explicit applicability cell to its provider request."""

    normalized_requirement = _normalized_requirement(requirement)
    normalized_request = _normalized_provider_request(provider_request)
    _validate_explicit_request(normalized_requirement, normalized_request)
    return _qualified_request(
        normalized_requirement,
        request_kind="provider_request",
        source_evidence_sha256=normalized_requirement.role_binding.source_cell_sha256,
        provider_request=normalized_request,
        root_receipt=None,
    )


def bind_receipt_root_competition_request(
    requirement: CompetitionIdentityRequirement,
    receipt: ReceiptBoundCompetitionRoot,
    provider_request: CanonicalProviderRequest,
) -> CompetitionQualifiedRequest:
    """Bind one exact dynamic competition-root receipt to a provider request."""

    normalized_requirement = _normalized_requirement(requirement)
    normalized_request = _normalized_provider_request(provider_request)
    _validate_dynamic_request(normalized_requirement, receipt, normalized_request)
    return _qualified_request(
        normalized_requirement,
        request_kind="provider_request",
        source_evidence_sha256=receipt.receipt_sha256,
        provider_request=normalized_request,
        root_receipt=receipt,
    )


def bind_static_competition_source(
    requirement: CompetitionIdentityRequirement,
) -> CompetitionQualifiedRequest:
    """Bind one fixed Static dataset chain without fabricating request evidence."""

    normalized = _normalized_requirement(requirement)
    role = normalized.role_binding
    if (
        role.binding_strategy != "fixed_static_root"
        or not normalized.executable
        or role.static_chain_sha256 is None
    ):
        raise NbaApiCompetitionIdentityError("requirement is not an executable fixed Static root")
    return _qualified_request(
        normalized,
        request_kind="static_source",
        source_evidence_sha256=role.static_chain_sha256,
        provider_request=None,
        root_receipt=None,
    )


def _revalidated_request(
    request: object,
) -> tuple[
    CompetitionQualifiedRequest,
    CompetitionIdentityRequirement,
    CanonicalProviderRequest | None,
    ReceiptBoundCompetitionRoot | None,
]:
    if type(request) is not CompetitionQualifiedRequest:
        raise NbaApiCompetitionIdentityError("request must be an exact CompetitionQualifiedRequest")
    typed = request
    requirement, provider, receipt = typed._revalidate()
    return typed, requirement, provider, receipt


def _pagination_context(
    request: CompetitionQualifiedRequest,
    provider_endpoint_id: object,
    cursor_occurrence_id: object,
    non_cursor_scope_sha256: object,
) -> tuple[
    CompetitionIdentityRequirement,
    CanonicalProviderRequest,
    str,
    dict[str, object],
]:
    qualified, requirement, provider, _receipt = _revalidated_request(request)
    if qualified.request_kind != "provider_request" or provider is None:
        raise NbaApiCompetitionIdentityError("pagination requires a provider request")
    endpoint_id = _require_text(provider_endpoint_id, "provider_endpoint_id")
    occurrence_id = _require_text(cursor_occurrence_id, "cursor_occurrence_id")
    if endpoint_id != requirement.provider_endpoint_id or endpoint_id != provider.endpoint_id:
        raise NbaApiCompetitionIdentityError("pagination endpoint differs from its request")
    endpoint = pinned_request_surface_authority().endpoint(
        cast("Any", provider.source_family), endpoint_id
    )
    occurrences = [item for item in endpoint.parameters if item.occurrence_id == occurrence_id]
    if len(occurrences) != 1 or occurrences[0].semantic_role != "pagination_cursor":
        raise NbaApiCompetitionIdentityError(
            "pagination cursor occurrence is not exact for the provider endpoint"
        )
    cursor_name = occurrences[0].name
    if sum(name == cursor_name for name, _value in provider.materialized_parameters) != 1:
        raise NbaApiCompetitionIdentityError("pagination cursor materialization is not unique")
    non_cursor_parameters = [
        [name, value] for name, value in provider.materialized_parameters if name != cursor_name
    ]
    non_cursor_body: dict[str, object] = {
        "request_surface_sha256": provider.request_surface_sha256,
        "source_family": provider.source_family,
        "provider_endpoint_id": provider.endpoint_id,
        "materialized_parameters": non_cursor_parameters,
    }
    supplied_non_cursor = _require_sha256(non_cursor_scope_sha256, "non_cursor_scope_sha256")
    if supplied_non_cursor != _digest(non_cursor_body):
        raise NbaApiCompetitionIdentityError("pagination non-cursor scope digest is invalid")
    body: dict[str, object] = {
        "domain_separator": _PAGINATION_SERIES_DOMAIN,
        "competition_scope_sha256": requirement.competition_scope_sha256,
        "provider_endpoint_id": endpoint_id,
        "cursor_occurrence_id": occurrence_id,
        "non_cursor_scope_sha256": supplied_non_cursor,
    }
    return requirement, provider, cursor_name, body


@dataclass(frozen=True, slots=True)
class CompetitionQualifiedPaginationSeries:
    """One competition-qualified provider pagination series."""

    competition_scope_sha256: str
    provider_endpoint_id: str
    cursor_occurrence_id: str
    non_cursor_scope_sha256: str
    pagination_series_sha256: str
    request_evidence: InitVar[CompetitionQualifiedRequest]
    _request_evidence: CompetitionQualifiedRequest = field(init=False, repr=False, compare=False)

    def __post_init__(self, request_evidence: CompetitionQualifiedRequest) -> None:
        object.__setattr__(self, "_request_evidence", request_evidence)
        self._revalidate()

    def _revalidate(
        self,
    ) -> tuple[CompetitionQualifiedRequest, CanonicalProviderRequest, str]:
        if type(self._request_evidence) is not CompetitionQualifiedRequest:
            raise NbaApiCompetitionIdentityError("pagination series lost request evidence")
        _requirement_value, provider, cursor_name, body = _pagination_context(
            self._request_evidence,
            self.provider_endpoint_id,
            self.cursor_occurrence_id,
            self.non_cursor_scope_sha256,
        )
        expected = (
            cast("str", body["competition_scope_sha256"]),
            cast("str", body["provider_endpoint_id"]),
            cast("str", body["cursor_occurrence_id"]),
            cast("str", body["non_cursor_scope_sha256"]),
            _digest(body),
        )
        observed = (
            self.competition_scope_sha256,
            self.provider_endpoint_id,
            self.cursor_occurrence_id,
            self.non_cursor_scope_sha256,
            self.pagination_series_sha256,
        )
        if not _exact_typed_equal(observed, expected):
            raise NbaApiCompetitionIdentityError("pagination series identity drifted")
        return self._request_evidence, provider, cursor_name

    def to_dict(self) -> dict[str, object]:
        self._revalidate()
        return {
            "competition_scope_sha256": self.competition_scope_sha256,
            "provider_endpoint_id": self.provider_endpoint_id,
            "cursor_occurrence_id": self.cursor_occurrence_id,
            "non_cursor_scope_sha256": self.non_cursor_scope_sha256,
            "pagination_series_sha256": self.pagination_series_sha256,
        }


def qualify_pagination_series(
    request: CompetitionQualifiedRequest,
    provider_endpoint_id: str,
    cursor_occurrence_id: str,
    non_cursor_scope_sha256: str,
) -> CompetitionQualifiedPaginationSeries:
    """Qualify one exact cursor axis and non-cursor provider scope."""

    _requirement_value, _provider, _cursor_name, body = _pagination_context(
        request,
        provider_endpoint_id,
        cursor_occurrence_id,
        non_cursor_scope_sha256,
    )
    return CompetitionQualifiedPaginationSeries(
        competition_scope_sha256=cast("str", body["competition_scope_sha256"]),
        provider_endpoint_id=cast("str", body["provider_endpoint_id"]),
        cursor_occurrence_id=cast("str", body["cursor_occurrence_id"]),
        non_cursor_scope_sha256=cast("str", body["non_cursor_scope_sha256"]),
        pagination_series_sha256=_digest(body),
        request_evidence=request,
    )


def _page_ordinal(cursor_value: object) -> int:
    if type(cursor_value) not in {str, int, float}:
        raise NbaApiCompetitionIdentityError(
            "pagination cursor must be an exact string, integer, or finite float"
        )
    if type(cursor_value) is str and not cursor_value:
        raise NbaApiCompetitionIdentityError("pagination cursor text must be nonempty")
    try:
        numeric = float(cast("str | int | float", cursor_value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise NbaApiCompetitionIdentityError("pagination cursor is not numeric") from exc
    if (
        not math.isfinite(numeric)
        or not numeric.is_integer()
        or numeric < 0
        or numeric > 2_147_483_647
    ):
        raise NbaApiCompetitionIdentityError(
            "pagination cursor is outside the exact integral provider bounds"
        )
    return int(numeric)


def _pagination_page_body(
    series: CompetitionQualifiedPaginationSeries,
    request: CompetitionQualifiedRequest,
    cursor_value: object,
    page_ordinal: object,
    raw_wire_sha256: object,
) -> dict[str, object]:
    if type(series) is not CompetitionQualifiedPaginationSeries:
        raise NbaApiCompetitionIdentityError(
            "series must be an exact CompetitionQualifiedPaginationSeries"
        )
    retained_request, provider, cursor_name = series._revalidate()
    supplied_request, requirement, supplied_provider, _receipt = _revalidated_request(request)
    if (
        not _exact_typed_equal(retained_request, supplied_request)
        or supplied_provider is None
        or not _exact_typed_equal(provider, supplied_provider)
        or series.competition_scope_sha256 != requirement.competition_scope_sha256
        or series.provider_endpoint_id != requirement.provider_endpoint_id
    ):
        raise NbaApiCompetitionIdentityError("pagination page parent request drifted")
    reproduced = qualify_pagination_series(
        supplied_request,
        series.provider_endpoint_id,
        series.cursor_occurrence_id,
        series.non_cursor_scope_sha256,
    )
    if not _exact_typed_equal(series, reproduced):
        raise NbaApiCompetitionIdentityError("pagination page series was self-resealed")
    retained_values = [
        value for name, value in provider.materialized_parameters if name == cursor_name
    ]
    if len(retained_values) != 1 or not _exact_typed_equal(cursor_value, retained_values[0]):
        raise NbaApiCompetitionIdentityError("pagination cursor encoding drifted")
    ordinal = _require_nonnegative_int(page_ordinal, "page_ordinal")
    if ordinal != _page_ordinal(cursor_value):
        raise NbaApiCompetitionIdentityError("pagination page ordinal differs from cursor")
    wire_digest = _require_sha256(raw_wire_sha256, "raw_wire_sha256")
    return {
        "domain_separator": _PAGINATION_PAGE_DOMAIN,
        "pagination_series_sha256": series.pagination_series_sha256,
        "source_request_sha256": supplied_request.source_request_sha256,
        "cursor_value": cast("str | int | float", cursor_value),
        "page_ordinal": ordinal,
        "raw_wire_sha256": wire_digest,
    }


@dataclass(frozen=True, slots=True)
class CompetitionQualifiedPaginationPage:
    """One exact competition-qualified pagination page identity."""

    pagination_series_sha256: str
    source_request_sha256: str
    cursor_value: str | int | float
    page_ordinal: int
    raw_wire_sha256: str
    pagination_page_sha256: str
    series_evidence: InitVar[CompetitionQualifiedPaginationSeries]
    request_evidence: InitVar[CompetitionQualifiedRequest]
    _series_evidence: CompetitionQualifiedPaginationSeries = field(
        init=False, repr=False, compare=False
    )
    _request_evidence: CompetitionQualifiedRequest = field(init=False, repr=False, compare=False)

    def __post_init__(
        self,
        series_evidence: CompetitionQualifiedPaginationSeries,
        request_evidence: CompetitionQualifiedRequest,
    ) -> None:
        object.__setattr__(self, "_series_evidence", series_evidence)
        object.__setattr__(self, "_request_evidence", request_evidence)
        self._revalidate()

    def _revalidate(self) -> None:
        body = _pagination_page_body(
            self._series_evidence,
            self._request_evidence,
            self.cursor_value,
            self.page_ordinal,
            self.raw_wire_sha256,
        )
        expected = (
            body["pagination_series_sha256"],
            body["source_request_sha256"],
            body["cursor_value"],
            body["page_ordinal"],
            body["raw_wire_sha256"],
            _digest(body),
        )
        observed = (
            self.pagination_series_sha256,
            self.source_request_sha256,
            self.cursor_value,
            self.page_ordinal,
            self.raw_wire_sha256,
            self.pagination_page_sha256,
        )
        if not _exact_typed_equal(observed, expected):
            raise NbaApiCompetitionIdentityError("pagination page identity drifted")

    def to_dict(self) -> dict[str, object]:
        self._revalidate()
        return {
            "pagination_series_sha256": self.pagination_series_sha256,
            "source_request_sha256": self.source_request_sha256,
            "cursor_value": self.cursor_value,
            "page_ordinal": self.page_ordinal,
            "raw_wire_sha256": self.raw_wire_sha256,
            "pagination_page_sha256": self.pagination_page_sha256,
        }


def qualify_pagination_page(
    series: CompetitionQualifiedPaginationSeries,
    request: CompetitionQualifiedRequest,
    cursor_value: str | int | float,
    page_ordinal: int,
    raw_wire_sha256: str,
) -> CompetitionQualifiedPaginationPage:
    """Qualify one exact page while retaining its wire encoding identity."""

    body = _pagination_page_body(series, request, cursor_value, page_ordinal, raw_wire_sha256)
    return CompetitionQualifiedPaginationPage(
        pagination_series_sha256=cast("str", body["pagination_series_sha256"]),
        source_request_sha256=cast("str", body["source_request_sha256"]),
        cursor_value=cast("str | int | float", body["cursor_value"]),
        page_ordinal=cast("int", body["page_ordinal"]),
        raw_wire_sha256=cast("str", body["raw_wire_sha256"]),
        pagination_page_sha256=_digest(body),
        series_evidence=series,
        request_evidence=request,
    )


def _entity_body(
    requirement: CompetitionIdentityRequirement,
    entity_kind: object,
    provider_encoding: object,
    entity_value: object,
) -> tuple[CompetitionIdentityRequirement, dict[str, object]]:
    normalized = _normalized_requirement(requirement)
    kind = _require_text(entity_kind, "entity_kind")
    encoding = _require_text(provider_encoding, "provider_encoding")
    if type(entity_value) is str:
        value: str | int = _require_text(entity_value, "entity_value")
    elif type(entity_value) is int:
        value = entity_value
    else:
        raise NbaApiCompetitionIdentityError("entity_value must be an exact string or integer")
    return normalized, {
        "domain_separator": _ENTITY_DOMAIN,
        "competition_scope_sha256": normalized.competition_scope_sha256,
        "entity_kind": kind,
        "provider_encoding": encoding,
        "entity_value": value,
    }


@dataclass(frozen=True, slots=True)
class CompetitionQualifiedEntityIdentity:
    """One exact provider entity encoding bound to a competition scope."""

    competition_scope_sha256: str
    entity_kind: str
    provider_encoding: str
    entity_value: str | int
    entity_identity_sha256: str
    requirement_evidence: InitVar[CompetitionIdentityRequirement]
    _requirement_evidence: CompetitionIdentityRequirement = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self, requirement_evidence: CompetitionIdentityRequirement) -> None:
        object.__setattr__(self, "_requirement_evidence", requirement_evidence)
        self._revalidate()

    def _revalidate(self) -> None:
        _requirement_value, body = _entity_body(
            self._requirement_evidence,
            self.entity_kind,
            self.provider_encoding,
            self.entity_value,
        )
        expected = (
            body["competition_scope_sha256"],
            body["entity_kind"],
            body["provider_encoding"],
            body["entity_value"],
            _digest(body),
        )
        observed = (
            self.competition_scope_sha256,
            self.entity_kind,
            self.provider_encoding,
            self.entity_value,
            self.entity_identity_sha256,
        )
        if not _exact_typed_equal(observed, expected):
            raise NbaApiCompetitionIdentityError("entity identity drifted")

    def to_dict(self) -> dict[str, object]:
        self._revalidate()
        return {
            "competition_scope_sha256": self.competition_scope_sha256,
            "entity_kind": self.entity_kind,
            "provider_encoding": self.provider_encoding,
            "entity_value": self.entity_value,
            "entity_identity_sha256": self.entity_identity_sha256,
        }


def qualify_entity_identity(
    requirement: CompetitionIdentityRequirement,
    entity_kind: str,
    provider_encoding: str,
    entity_value: str | int,
) -> CompetitionQualifiedEntityIdentity:
    """Bind one exact entity encoding to a pinned competition requirement."""

    normalized, body = _entity_body(requirement, entity_kind, provider_encoding, entity_value)
    return CompetitionQualifiedEntityIdentity(
        competition_scope_sha256=cast("str", body["competition_scope_sha256"]),
        entity_kind=cast("str", body["entity_kind"]),
        provider_encoding=cast("str", body["provider_encoding"]),
        entity_value=cast("str | int", body["entity_value"]),
        entity_identity_sha256=_digest(body),
        requirement_evidence=normalized,
    )


def _expected_provider_authority() -> str:
    from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
    from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority

    provider = expected_nba_api_provider_authority().get("authority_sha256")
    route_provider = staging_route_contract_bundle().provider_authority_sha256
    if (
        type(provider) is not str
        or provider != _EXPECTED_PROVIDER_AUTHORITY_SHA256
        or route_provider != _EXPECTED_PROVIDER_AUTHORITY_SHA256
    ):
        raise NbaApiCompetitionIdentityError("pinned provider authority drifted")
    return provider


def build_competition_terminal_request_binding(
    request: CompetitionQualifiedRequest,
    *,
    route_manifest_sha256: str,
    scope_sha256: str,
    route_ids: tuple[str, ...],
) -> TerminalRequestBinding:
    """Bind one revalidated competition-qualified request to closure authority.

    The caller supplies only the route/scope projection owned by request
    closure.  Competition, provider, and source-request identities are always
    reproduced from the pinned requirement and the exact qualified request;
    callers cannot substitute digest-shaped stand-ins for those authorities.
    """

    qualified, requirement, provider, _root_receipt = _revalidated_request(request)
    if qualified.request_kind != "provider_request" or provider is None:
        raise NbaApiCompetitionIdentityError(
            "terminal request binding requires a competition-qualified provider request"
        )
    surface = pinned_request_surface_authority()
    return build_terminal_request_binding(
        request_surface_sha256=surface.surface_sha256,
        runtime_contract_payload_sha256=surface.runtime_contract_payload_sha256,
        provider_authority_sha256=_expected_provider_authority(),
        route_manifest_sha256=route_manifest_sha256,
        scope_sha256=scope_sha256,
        provider_request_sha256=provider.provider_request_sha256,
        source_request_sha256=qualified.source_request_sha256,
        competition_authority_sha256=_COMPETITION_AUTHORITY_SHA256,
        competition_scope_sha256=requirement.competition_scope_sha256,
        competition_requirement_sha256=requirement.requirement_sha256,
        role_binding_sha256=requirement.role_binding.role_binding_sha256,
        source_evidence_sha256=qualified.source_evidence_sha256,
        source_family=provider.source_family,
        endpoint_id=provider.endpoint_id,
        route_ids=route_ids,
    )


def _normalized_foundation_receipt(receipt: object) -> Any:
    from nbadb.orchestrate.dependent_workload_contract import (
        FoundationAuthorityKind,
        FoundationInputReceipt,
    )

    if type(receipt) is not FoundationInputReceipt:
        raise NbaApiCompetitionIdentityError(
            "discovery receipt must be an exact FoundationInputReceipt"
        )
    typed = cast("Any", receipt)
    if type(typed.authority_kind) is not FoundationAuthorityKind:
        raise NbaApiCompetitionIdentityError("foundation receipt authority kind is not exact")
    if type(typed.logical_parameters) is not tuple:
        raise NbaApiCompetitionIdentityError("foundation logical parameters are not an exact tuple")
    for item in typed.logical_parameters:
        if (
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not str
            or type(item[1]) not in {str, int}
        ):
            raise NbaApiCompetitionIdentityError("foundation logical parameter entry is not exact")
    try:
        reconstructed = FoundationInputReceipt(
            authority_kind=FoundationAuthorityKind(typed.authority_kind.value),
            table_name=typed.table_name,
            chunk_id=typed.chunk_id,
            endpoint_name=typed.endpoint_name,
            logical_call_receipt_sha256=typed.logical_call_receipt_sha256,
            discovery_manifest_sha256=typed.discovery_manifest_sha256,
            logical_parameters=typed.logical_parameters,
            logical_parameters_sha256=typed.logical_parameters_sha256,
            provider_authority_sha256=typed.provider_authority_sha256,
            result_route_id=typed.result_route_id,
            persisted_content_sha256=typed.persisted_content_sha256,
            persisted_schema_sha256=typed.persisted_schema_sha256,
            persisted_row_count=typed.persisted_row_count,
        )
    except (TypeError, ValueError) as exc:
        raise NbaApiCompetitionIdentityError("foundation receipt did not revalidate") from exc
    if not _exact_typed_equal(typed, reconstructed):
        raise NbaApiCompetitionIdentityError("foundation receipt public state drifted")
    return reconstructed


def _normalized_foundation_authority(authority: object) -> Any:
    from nbadb.orchestrate.checkpoint_contract import CheckpointTransaction
    from nbadb.orchestrate.dependent_workload_contract import FoundationAuthority

    if type(authority) is not FoundationAuthority:
        raise NbaApiCompetitionIdentityError(
            "foundation authority must be an exact FoundationAuthority"
        )
    typed = cast("Any", authority)
    if type(typed.checkpoint_transaction) is not CheckpointTransaction:
        raise NbaApiCompetitionIdentityError("foundation checkpoint type drifted")
    try:
        transaction = CheckpointTransaction.from_dict(typed.checkpoint_transaction.to_dict())
        if not _exact_typed_equal(typed.checkpoint_transaction, transaction):
            raise NbaApiCompetitionIdentityError("foundation checkpoint public state drifted")
        receipts = tuple(_normalized_foundation_receipt(item) for item in typed.input_receipts)
        reconstructed = FoundationAuthority(
            checkpoint_transaction=transaction,
            checkpoint_report_sha256=typed.checkpoint_report_sha256,
            checkpoint_database_sha256=typed.checkpoint_database_sha256,
            discovery_artifact_id=typed.discovery_artifact_id,
            discovery_artifact_run_id=typed.discovery_artifact_run_id,
            discovery_artifact_name=typed.discovery_artifact_name,
            discovery_artifact_digest=typed.discovery_artifact_digest,
            provider_authority_sha256=typed.provider_authority_sha256,
            source_sha=typed.source_sha,
            compiler_implementation_sha256=typed.compiler_implementation_sha256,
            query_plan_sha256=typed.query_plan_sha256,
            input_receipts=receipts,
        )
    except NbaApiCompetitionIdentityError:
        raise
    except (TypeError, ValueError) as exc:
        raise NbaApiCompetitionIdentityError("foundation authority did not revalidate") from exc
    if not _exact_typed_equal(typed, reconstructed):
        raise NbaApiCompetitionIdentityError("foundation authority public state drifted")
    return reconstructed


def _discovery_generation_body(
    request: CompetitionQualifiedRequest,
    foundation_authority: object,
    discovery_receipt: object,
) -> tuple[CompetitionQualifiedRequest, Any, Any, dict[str, object]]:
    from nbadb.orchestrate.dependent_workload_contract import (
        FoundationAuthorityKind,
        canonical_sha256,
    )

    qualified, requirement, provider, _root_receipt = _revalidated_request(request)
    if qualified.request_kind != "provider_request" or provider is None:
        raise NbaApiCompetitionIdentityError("discovery generation requires a provider request")
    authority = _normalized_foundation_authority(foundation_authority)
    receipt = _normalized_foundation_receipt(discovery_receipt)
    matches = [
        item for item in authority.input_receipts if item.identity_sha256 == receipt.identity_sha256
    ]
    if (
        len(matches) != 1
        or not _exact_typed_equal(matches[0], receipt)
        or receipt.authority_kind is not FoundationAuthorityKind.DISCOVERY_GENERATION
    ):
        raise NbaApiCompetitionIdentityError("discovery receipt is not one exact authority member")
    expected_provider = _expected_provider_authority()
    if (
        authority.provider_authority_sha256 != expected_provider
        or receipt.provider_authority_sha256 != expected_provider
    ):
        raise NbaApiCompetitionIdentityError("discovery provider authority drifted")
    if (
        receipt.endpoint_name != requirement.repo_endpoint_name
        or requirement.repo_endpoint_name != "league_game_log"
        or requirement.source_family != "stats"
        or requirement.provider_endpoint_id != "LeagueGameLog"
        or provider.source_family != requirement.source_family
        or provider.endpoint_id != requirement.provider_endpoint_id
        or requirement.league_id != "00"
    ):
        raise NbaApiCompetitionIdentityError("discovery request requirement is not admissible")
    logical = dict(receipt.logical_parameters)
    if tuple(sorted(logical)) != ("season", "season_type") or len(logical) != 2:
        raise NbaApiCompetitionIdentityError("discovery logical period scope is not exact")
    surface = pinned_request_surface_authority()
    endpoint = surface.endpoint("stats", "LeagueGameLog")
    try:
        expected_request = materialize_provider_request(
            endpoint,
            {
                "season": logical["season"],
                "season_type_all_star": logical["season_type"],
            },
            request_surface_sha256=surface.surface_sha256,
            runtime_contract_payload_sha256=surface.runtime_contract_payload_sha256,
        )
    except (TypeError, ValueError) as exc:
        raise NbaApiCompetitionIdentityError(
            "discovery period could not reproduce LeagueGameLog request"
        ) from exc
    if not _exact_typed_equal(provider, expected_request):
        raise NbaApiCompetitionIdentityError(
            "discovery request differs from exact full-default materialization"
        )
    body: dict[str, object] = {
        "domain_separator": _DISCOVERY_GENERATION_DOMAIN,
        "competition_scope_sha256": qualified.competition_scope_sha256,
        "native_period_scope_sha256": receipt.logical_parameters_sha256,
        "producer_request_or_root_receipt_inventory_sha256": canonical_sha256([receipt.to_dict()]),
        "schema_sha256": receipt.persisted_schema_sha256,
        "row_count": receipt.persisted_row_count,
        "content_sha256": receipt.persisted_content_sha256,
    }
    return qualified, authority, receipt, body


@dataclass(frozen=True, slots=True)
class CompetitionQualifiedDiscoveryGeneration:
    """One receipt-backed discovery generation bound to a competition."""

    competition_scope_sha256: str
    native_period_scope_sha256: str
    producer_request_or_root_receipt_inventory_sha256: str
    schema_sha256: str
    row_count: int
    content_sha256: str
    discovery_generation_sha256: str
    request_evidence: InitVar[CompetitionQualifiedRequest]
    foundation_authority_evidence: InitVar[object]
    discovery_receipt_evidence: InitVar[object]
    _request_evidence: CompetitionQualifiedRequest = field(init=False, repr=False, compare=False)
    _foundation_authority_evidence: object = field(init=False, repr=False, compare=False)
    _discovery_receipt_evidence: object = field(init=False, repr=False, compare=False)

    def __post_init__(
        self,
        request_evidence: CompetitionQualifiedRequest,
        foundation_authority_evidence: object,
        discovery_receipt_evidence: object,
    ) -> None:
        object.__setattr__(self, "_request_evidence", request_evidence)
        object.__setattr__(self, "_foundation_authority_evidence", foundation_authority_evidence)
        object.__setattr__(self, "_discovery_receipt_evidence", discovery_receipt_evidence)
        self._revalidate()

    def _revalidate(self) -> None:
        _request_value, _authority, _receipt, body = _discovery_generation_body(
            self._request_evidence,
            self._foundation_authority_evidence,
            self._discovery_receipt_evidence,
        )
        expected = (
            body["competition_scope_sha256"],
            body["native_period_scope_sha256"],
            body["producer_request_or_root_receipt_inventory_sha256"],
            body["schema_sha256"],
            body["row_count"],
            body["content_sha256"],
            _digest(body),
        )
        observed = (
            self.competition_scope_sha256,
            self.native_period_scope_sha256,
            self.producer_request_or_root_receipt_inventory_sha256,
            self.schema_sha256,
            self.row_count,
            self.content_sha256,
            self.discovery_generation_sha256,
        )
        if not _exact_typed_equal(observed, expected):
            raise NbaApiCompetitionIdentityError("discovery generation identity drifted")

    def to_dict(self) -> dict[str, object]:
        self._revalidate()
        return {
            "competition_scope_sha256": self.competition_scope_sha256,
            "native_period_scope_sha256": self.native_period_scope_sha256,
            "producer_request_or_root_receipt_inventory_sha256": (
                self.producer_request_or_root_receipt_inventory_sha256
            ),
            "schema_sha256": self.schema_sha256,
            "row_count": self.row_count,
            "content_sha256": self.content_sha256,
            "discovery_generation_sha256": self.discovery_generation_sha256,
        }


def qualify_discovery_generation(
    request: CompetitionQualifiedRequest,
    foundation_authority: object,
    discovery_receipt: object,
) -> CompetitionQualifiedDiscoveryGeneration:
    """Qualify one exact authenticated LeagueGameLog discovery generation."""

    qualified, authority, receipt, body = _discovery_generation_body(
        request, foundation_authority, discovery_receipt
    )
    return CompetitionQualifiedDiscoveryGeneration(
        competition_scope_sha256=cast("str", body["competition_scope_sha256"]),
        native_period_scope_sha256=cast("str", body["native_period_scope_sha256"]),
        producer_request_or_root_receipt_inventory_sha256=cast(
            "str", body["producer_request_or_root_receipt_inventory_sha256"]
        ),
        schema_sha256=cast("str", body["schema_sha256"]),
        row_count=cast("int", body["row_count"]),
        content_sha256=cast("str", body["content_sha256"]),
        discovery_generation_sha256=_digest(body),
        request_evidence=qualified,
        foundation_authority_evidence=authority,
        discovery_receipt_evidence=receipt,
    )


def _normalized_observation(observation: object) -> Any:
    from nbadb.orchestrate.request_closure_runtime import RequestObservation

    if type(observation) is not RequestObservation:
        raise NbaApiCompetitionIdentityError("observation must be an exact RequestObservation")
    typed = cast("Any", observation)
    try:
        reconstructed = RequestObservation.from_dict(typed.to_dict())
    except (TypeError, ValueError) as exc:
        raise NbaApiCompetitionIdentityError("request observation did not revalidate") from exc
    if not _exact_typed_equal(typed, reconstructed):
        raise NbaApiCompetitionIdentityError("request observation public state drifted")
    return reconstructed


def _normalized_execution_authority(authority: object) -> Any:
    from nbadb.core.nba_api_request_surface import (
        AuthoritativeRouteManifest,
        RequestScopeDimension,
        RequestScopeManifest,
        RouteRequestSpec,
    )
    from nbadb.orchestrate.extractor_runner import (
        RequestClosureCompetitionAuthority,
        RequestClosureExecutionAuthority,
        RequestClosureLogicalCallBinding,
        RequestClosureStagingRouteAlias,
    )

    if type(authority) is not RequestClosureExecutionAuthority:
        raise NbaApiCompetitionIdentityError(
            "execution authority must be an exact RequestClosureExecutionAuthority"
        )
    typed = cast("Any", authority)
    try:
        if type(typed.route_manifest) is not AuthoritativeRouteManifest:
            raise NbaApiCompetitionIdentityError("route manifest type drifted")
        routes = []
        for route in typed.route_manifest.routes:
            if type(route) is not RouteRequestSpec:
                raise NbaApiCompetitionIdentityError("route request type drifted")
            routes.append(
                RouteRequestSpec(
                    route_id=route.route_id,
                    source_family=route.source_family,
                    endpoint_id=route.endpoint_id,
                    parameters=route.parameters,
                    pagination_series_id=route.pagination_series_id,
                    pagination_ordinal=route.pagination_ordinal,
                    pagination_terminal=route.pagination_terminal,
                )
            )
        route_manifest = AuthoritativeRouteManifest(
            request_surface_sha256=typed.route_manifest.request_surface_sha256,
            runtime_contract_payload_sha256=(typed.route_manifest.runtime_contract_payload_sha256),
            derivation_policy_sha256=typed.route_manifest.derivation_policy_sha256,
            registry_manifest_sha256=typed.route_manifest.registry_manifest_sha256,
            routes=tuple(routes),
        )
        if type(typed.scope) is not RequestScopeManifest:
            raise NbaApiCompetitionIdentityError("request scope type drifted")
        dimensions = []
        for dimension in typed.scope.dimensions:
            if type(dimension) is not RequestScopeDimension:
                raise NbaApiCompetitionIdentityError("request scope dimension type drifted")
            dimensions.append(
                RequestScopeDimension(
                    dependency_id=dimension.dependency_id,
                    source_kind=dimension.source_kind,
                    source_authority_sha256=dimension.source_authority_sha256,
                    values=dimension.values,
                    endpoint_id=dimension.endpoint_id,
                    parameter_name=dimension.parameter_name,
                )
            )
        scope = RequestScopeManifest(
            request_surface_sha256=typed.scope.request_surface_sha256,
            scope_id=typed.scope.scope_id,
            seed_route_ids=typed.scope.seed_route_ids,
            dimensions=tuple(dimensions),
        )
        aliases = []
        for alias in typed.staging_route_aliases:
            if type(alias) is not RequestClosureStagingRouteAlias:
                raise NbaApiCompetitionIdentityError("staging route alias type drifted")
            aliases.append(
                RequestClosureStagingRouteAlias(
                    manifest_route_id=alias.manifest_route_id,
                    staging_route_id=alias.staging_route_id,
                )
            )
        logical_calls = []
        for logical_call in typed.logical_calls:
            if type(logical_call) is not RequestClosureLogicalCallBinding:
                raise NbaApiCompetitionIdentityError("logical call type drifted")
            logical_calls.append(
                RequestClosureLogicalCallBinding(
                    endpoint_name=logical_call.endpoint_name,
                    logical_parameters_sha256=logical_call.logical_parameters_sha256,
                    provider_request_sha256=logical_call.provider_request_sha256,
                    route_ids=logical_call.route_ids,
                    provider_parameters_sha256=logical_call.provider_parameters_sha256,
                )
            )
        competition_authorities = []
        for competition_authority in typed.competition_authorities:
            if type(competition_authority) is not RequestClosureCompetitionAuthority:
                raise NbaApiCompetitionIdentityError(
                    "request closure competition authority type drifted"
                )
            (
                _qualified,
                requirement,
                provider,
                root_receipt,
            ) = _revalidated_request(competition_authority.qualified_request)
            strategy = requirement.role_binding.binding_strategy
            if strategy == "explicit_applicability_cell":
                if provider is None:
                    raise NbaApiCompetitionIdentityError(
                        "explicit request lost its provider authority"
                    )
                reproduced_request = bind_explicit_competition_request(
                    requirement,
                    provider,
                )
            elif strategy == "receipt_bound_dynamic_root":
                if provider is None or root_receipt is None:
                    raise NbaApiCompetitionIdentityError(
                        "dynamic request lost its receipt-qualified authority"
                    )
                reproduced_request = bind_receipt_root_competition_request(
                    requirement,
                    root_receipt,
                    provider,
                )
            else:
                raise NbaApiCompetitionIdentityError(
                    "execution authority retained a non-provider competition request"
                )
            request_binding = _reconstruct_closure_value(competition_authority.request_binding)
            if type(request_binding) is not TerminalRequestBinding:
                raise NbaApiCompetitionIdentityError(
                    "request closure terminal binding type drifted"
                )
            competition_authorities.append(
                RequestClosureCompetitionAuthority(
                    qualified_request=reproduced_request,
                    request_binding=request_binding,
                )
            )
        reconstructed = RequestClosureExecutionAuthority(
            route_manifest=route_manifest,
            scope=scope,
            staging_route_aliases=tuple(aliases),
            logical_calls=tuple(logical_calls),
            competition_authorities=tuple(competition_authorities),
        )
    except NbaApiCompetitionIdentityError:
        raise
    except (TypeError, ValueError) as exc:
        raise NbaApiCompetitionIdentityError("execution authority did not revalidate") from exc
    if not _exact_typed_equal(typed, reconstructed):
        raise NbaApiCompetitionIdentityError("execution authority public state drifted")
    return reconstructed


def _runtime_evidence_context(
    request: CompetitionQualifiedRequest,
    observation: object,
    execution_authority: object,
) -> tuple[
    CompetitionQualifiedRequest,
    CompetitionIdentityRequirement,
    CanonicalProviderRequest,
    Any,
    Any,
]:
    qualified, requirement, provider, _root_receipt = _revalidated_request(request)
    if qualified.request_kind != "provider_request" or provider is None:
        raise NbaApiCompetitionIdentityError("runtime evidence requires a provider request")
    observed = _normalized_observation(observation)
    authority = _normalized_execution_authority(execution_authority)
    surface = pinned_request_surface_authority()
    if (
        observed.request_surface_sha256 != provider.request_surface_sha256
        or observed.request_surface_sha256 != surface.surface_sha256
        or observed.provider_request_sha256 != provider.provider_request_sha256
        or observed.source_family != provider.source_family
        or observed.source_family != requirement.source_family
        or observed.endpoint_id != provider.endpoint_id
        or observed.endpoint_id != requirement.provider_endpoint_id
        or observed.route_manifest_sha256 != authority.route_manifest.manifest_sha256
        or observed.scope_sha256 != authority.scope.scope_sha256
    ):
        raise NbaApiCompetitionIdentityError("runtime observation parent authority drifted")
    bindings = [
        item
        for item in authority.bindings
        if item.provider_request_sha256 == observed.provider_request_sha256
    ]
    if len(bindings) != 1 or bindings[0].route_ids != observed.route_ids:
        raise NbaApiCompetitionIdentityError("runtime observation route binding drifted")
    if observed.state not in {"success_nonempty", "success_empty"}:
        raise NbaApiCompetitionIdentityError(
            "runtime observation is not successful terminal evidence"
        )
    return qualified, requirement, provider, observed, authority


_CLOSURE_EVIDENCE_TYPES: Final = (
    AuthoritativeRouteManifest,
    IndependentClosureProof,
    RequestClosureIteration,
    RequestClosureReceipt,
    RequestExpansionEvidence,
    RequestRouteBinding,
    RequestScopeDimension,
    RequestScopeManifest,
    RequestTerminalEvidence,
    RouteRequestSpec,
    TerminalRequestBinding,
    TypedUpstreamUnavailableEvidence,
    UpstreamUnavailableSupportAuthority,
)


def _reconstruct_closure_value(value: object) -> object:
    if type(value) in _CLOSURE_EVIDENCE_TYPES:
        try:
            constructor = type(value)
            return constructor(
                **{
                    item.name: _reconstruct_closure_value(getattr(value, item.name))
                    for item in fields(cast("Any", value))
                    if item.init
                }
            )
        except (TypeError, ValueError) as exc:
            raise NbaApiCompetitionIdentityError(
                "request closure typed evidence did not revalidate"
            ) from exc
    if type(value) is tuple:
        return tuple(_reconstruct_closure_value(item) for item in value)
    if type(value) is list:
        return [_reconstruct_closure_value(item) for item in cast("list[object]", value)]
    if type(value) is dict:
        return {
            _reconstruct_closure_value(key): _reconstruct_closure_value(item)
            for key, item in cast("dict[object, object]", value).items()
        }
    if type(value) in {str, int, float, bool, type(None)}:
        return value
    raise NbaApiCompetitionIdentityError("request closure contains an unsupported typed value")


def _normalized_terminal_evidence(evidence: object) -> RequestTerminalEvidence:
    if type(evidence) is not RequestTerminalEvidence:
        raise NbaApiCompetitionIdentityError(
            "terminal evidence must be an exact RequestTerminalEvidence"
        )
    reconstructed = _reconstruct_closure_value(evidence)
    if type(reconstructed) is not RequestTerminalEvidence or not _exact_typed_equal(
        evidence, reconstructed
    ):
        raise NbaApiCompetitionIdentityError("terminal evidence public state drifted")
    return reconstructed


def _normalized_closure_receipt(receipt: object) -> RequestClosureReceipt:
    if type(receipt) is not RequestClosureReceipt:
        raise NbaApiCompetitionIdentityError(
            "closure receipt must be an exact RequestClosureReceipt"
        )
    reconstructed = _reconstruct_closure_value(receipt)
    if type(reconstructed) is not RequestClosureReceipt or not _exact_typed_equal(
        receipt, reconstructed
    ):
        raise NbaApiCompetitionIdentityError("closure receipt public state drifted")
    return reconstructed


def _terminal_evidence_context(
    request: CompetitionQualifiedRequest,
    terminal_evidence: object,
    closure_receipt: object,
) -> tuple[
    CompetitionQualifiedRequest,
    CompetitionIdentityRequirement,
    CanonicalProviderRequest,
    RequestTerminalEvidence,
    RequestClosureReceipt,
    TerminalRequestBinding,
]:
    qualified, requirement, provider, _root_receipt = _revalidated_request(request)
    if qualified.request_kind != "provider_request" or provider is None:
        raise NbaApiCompetitionIdentityError("terminal evidence requires a provider request")
    evidence = _normalized_terminal_evidence(terminal_evidence)
    closure = _normalized_closure_receipt(closure_receipt)
    matches = [
        item
        for item in closure.terminal_evidence
        if item.provider_request_sha256 == provider.provider_request_sha256
    ]
    if len(matches) != 1 or not _exact_typed_equal(matches[0], evidence):
        raise NbaApiCompetitionIdentityError(
            "closure must contain exactly one matching terminal evidence row"
        )
    route_bindings = [
        item
        for item in closure.bindings
        if item.provider_request_sha256 == provider.provider_request_sha256
    ]
    if len(route_bindings) != 1:
        raise NbaApiCompetitionIdentityError(
            "closure must contain exactly one matching provider request binding"
        )
    surface = pinned_request_surface_authority()
    expected_binding = build_terminal_request_binding(
        request_surface_sha256=surface.surface_sha256,
        runtime_contract_payload_sha256=surface.runtime_contract_payload_sha256,
        provider_authority_sha256=_expected_provider_authority(),
        route_manifest_sha256=closure.route_manifest.manifest_sha256,
        scope_sha256=closure.scope.scope_sha256,
        provider_request_sha256=provider.provider_request_sha256,
        source_request_sha256=qualified.source_request_sha256,
        competition_authority_sha256=_COMPETITION_AUTHORITY_SHA256,
        competition_scope_sha256=requirement.competition_scope_sha256,
        competition_requirement_sha256=requirement.requirement_sha256,
        role_binding_sha256=requirement.role_binding.role_binding_sha256,
        source_evidence_sha256=qualified.source_evidence_sha256,
        source_family=provider.source_family,
        endpoint_id=provider.endpoint_id,
        route_ids=route_bindings[0].route_ids,
    )
    if not _exact_typed_equal(evidence.request_binding, expected_binding):
        raise NbaApiCompetitionIdentityError(
            "terminal request binding differs from current competition-qualified authority"
        )
    return qualified, requirement, provider, evidence, closure, expected_binding


def _terminal_observation_body(
    request: CompetitionQualifiedRequest,
    terminal_evidence: object,
    closure_receipt: object,
) -> tuple[
    CompetitionQualifiedRequest,
    RequestTerminalEvidence,
    RequestClosureReceipt,
    dict[str, object],
]:
    qualified, _requirement, _provider, evidence, closure, _binding = _terminal_evidence_context(
        request, terminal_evidence, closure_receipt
    )
    if evidence.state not in {"success_nonempty", "success_empty"}:
        raise NbaApiCompetitionIdentityError(
            "terminal observation requires successful response evidence"
        )
    body: dict[str, object] = {
        "domain_separator": _TERMINAL_OBSERVATION_DOMAIN,
        "source_request_sha256": qualified.source_request_sha256,
        "observation_sha256": evidence.evidence_sha256,
    }
    return qualified, evidence, closure, body


@dataclass(frozen=True, slots=True)
class CompetitionQualifiedTerminalObservation:
    """One successful runtime observation bound to a qualified request."""

    source_request_sha256: str
    observation_sha256: str
    terminal_observation_sha256: str
    request_evidence: InitVar[CompetitionQualifiedRequest]
    terminal_evidence: InitVar[RequestTerminalEvidence]
    closure_receipt: InitVar[RequestClosureReceipt]
    _request_evidence: CompetitionQualifiedRequest = field(init=False, repr=False, compare=False)
    _terminal_evidence: RequestTerminalEvidence = field(init=False, repr=False, compare=False)
    _closure_receipt: RequestClosureReceipt = field(init=False, repr=False, compare=False)

    def __post_init__(
        self,
        request_evidence: CompetitionQualifiedRequest,
        terminal_evidence: RequestTerminalEvidence,
        closure_receipt: RequestClosureReceipt,
    ) -> None:
        object.__setattr__(self, "_request_evidence", request_evidence)
        object.__setattr__(self, "_terminal_evidence", terminal_evidence)
        object.__setattr__(self, "_closure_receipt", closure_receipt)
        self._revalidate()

    def _revalidate(self) -> None:
        _request, _observation, _authority, body = _terminal_observation_body(
            self._request_evidence,
            self._terminal_evidence,
            self._closure_receipt,
        )
        expected = (
            body["source_request_sha256"],
            body["observation_sha256"],
            _digest(body),
        )
        observed = (
            self.source_request_sha256,
            self.observation_sha256,
            self.terminal_observation_sha256,
        )
        if not _exact_typed_equal(observed, expected):
            raise NbaApiCompetitionIdentityError("terminal observation identity drifted")

    def to_dict(self) -> dict[str, object]:
        self._revalidate()
        return {
            "source_request_sha256": self.source_request_sha256,
            "observation_sha256": self.observation_sha256,
            "terminal_observation_sha256": self.terminal_observation_sha256,
        }

    def __copy__(self) -> CompetitionQualifiedTerminalObservation:
        self._revalidate()
        return CompetitionQualifiedTerminalObservation(
            self.source_request_sha256,
            self.observation_sha256,
            self.terminal_observation_sha256,
            self._request_evidence,
            self._terminal_evidence,
            self._closure_receipt,
        )

    def __deepcopy__(
        self,
        _memo: dict[int, object],
    ) -> CompetitionQualifiedTerminalObservation:
        self._revalidate()
        return CompetitionQualifiedTerminalObservation(
            self.source_request_sha256,
            self.observation_sha256,
            self.terminal_observation_sha256,
            copy.deepcopy(self._request_evidence, _memo),
            copy.deepcopy(self._terminal_evidence, _memo),
            copy.deepcopy(self._closure_receipt, _memo),
        )

    def __reduce_ex__(
        self,
        _protocol: SupportsIndex,
    ) -> tuple[type[CompetitionQualifiedTerminalObservation], tuple[object, ...]]:
        self._revalidate()
        return (
            CompetitionQualifiedTerminalObservation,
            (
                self.source_request_sha256,
                self.observation_sha256,
                self.terminal_observation_sha256,
                self._request_evidence,
                self._terminal_evidence,
                self._closure_receipt,
            ),
        )


def qualify_terminal_observation(
    request: CompetitionQualifiedRequest,
    terminal_evidence: RequestTerminalEvidence,
    closure_receipt: RequestClosureReceipt,
) -> CompetitionQualifiedTerminalObservation:
    """Qualify one exact successful terminal row under its complete closure."""

    qualified, evidence, closure, body = _terminal_observation_body(
        request, terminal_evidence, closure_receipt
    )
    return CompetitionQualifiedTerminalObservation(
        source_request_sha256=cast("str", body["source_request_sha256"]),
        observation_sha256=cast("str", body["observation_sha256"]),
        terminal_observation_sha256=_digest(body),
        request_evidence=qualified,
        terminal_evidence=evidence,
        closure_receipt=closure,
    )


@dataclass(frozen=True, slots=True)
class CompetitionQualifiedUnavailableEvidence:
    """One exact typed upstream-unavailable row bound to a qualified request."""

    source_request_sha256: str
    support_or_availability_authority_sha256: str
    unavailable_evidence_sha256: str
    request_evidence: InitVar[CompetitionQualifiedRequest]
    terminal_evidence: InitVar[RequestTerminalEvidence]
    closure_receipt: InitVar[RequestClosureReceipt]
    _request_evidence: CompetitionQualifiedRequest = field(init=False, repr=False, compare=False)
    _terminal_evidence: RequestTerminalEvidence = field(init=False, repr=False, compare=False)
    _closure_receipt: RequestClosureReceipt = field(init=False, repr=False, compare=False)

    def __post_init__(
        self,
        request_evidence: CompetitionQualifiedRequest,
        terminal_evidence: RequestTerminalEvidence,
        closure_receipt: RequestClosureReceipt,
    ) -> None:
        object.__setattr__(self, "_request_evidence", request_evidence)
        object.__setattr__(self, "_terminal_evidence", terminal_evidence)
        object.__setattr__(self, "_closure_receipt", closure_receipt)
        self._revalidate()

    def _body(self) -> dict[str, object]:
        qualified, _requirement, _provider, evidence, _closure, expected_binding = (
            _terminal_evidence_context(
                self._request_evidence,
                self._terminal_evidence,
                self._closure_receipt,
            )
        )
        if evidence.state != "upstream_unavailable":
            raise NbaApiCompetitionIdentityError(
                "unavailable evidence requires upstream_unavailable terminal state"
            )
        typed = evidence.upstream_unavailable_evidence
        if type(typed) is not TypedUpstreamUnavailableEvidence:
            raise NbaApiCompetitionIdentityError(
                "upstream-unavailable row lacks exact typed evidence"
            )
        support = typed.support_authority
        if type(support) is not UpstreamUnavailableSupportAuthority:
            raise NbaApiCompetitionIdentityError(
                "upstream-unavailable support authority type drifted"
            )
        try:
            reconstructed_support = UpstreamUnavailableSupportAuthority(
                **{item.name: getattr(support, item.name) for item in fields(support) if item.init}
            )
            reconstructed = build_typed_upstream_unavailable_evidence(
                expected_binding,
                reconstructed_support,
            )
        except (TypeError, ValueError) as exc:
            raise NbaApiCompetitionIdentityError(
                "typed upstream-unavailable evidence did not revalidate"
            ) from exc
        if not _exact_typed_equal(typed, reconstructed):
            raise NbaApiCompetitionIdentityError(
                "typed upstream-unavailable evidence rebinds its request or support authority"
            )
        return {
            "domain_separator": _UNAVAILABLE_EVIDENCE_DOMAIN,
            "source_request_sha256": qualified.source_request_sha256,
            "support_or_availability_authority_sha256": (reconstructed.unavailable_evidence_sha256),
        }

    def _revalidate(self) -> None:
        body = self._body()
        observed = (
            self.source_request_sha256,
            self.support_or_availability_authority_sha256,
            self.unavailable_evidence_sha256,
        )
        expected = (
            body["source_request_sha256"],
            body["support_or_availability_authority_sha256"],
            _digest(body),
        )
        if not _exact_typed_equal(observed, expected):
            raise NbaApiCompetitionIdentityError("unavailable evidence identity drifted")

    def to_dict(self) -> dict[str, object]:
        self._revalidate()
        return {
            "source_request_sha256": self.source_request_sha256,
            "support_or_availability_authority_sha256": (
                self.support_or_availability_authority_sha256
            ),
            "unavailable_evidence_sha256": self.unavailable_evidence_sha256,
        }

    def __copy__(self) -> CompetitionQualifiedUnavailableEvidence:
        self._revalidate()
        return CompetitionQualifiedUnavailableEvidence(
            self.source_request_sha256,
            self.support_or_availability_authority_sha256,
            self.unavailable_evidence_sha256,
            self._request_evidence,
            self._terminal_evidence,
            self._closure_receipt,
        )

    def __deepcopy__(
        self,
        _memo: dict[int, object],
    ) -> CompetitionQualifiedUnavailableEvidence:
        self._revalidate()
        return CompetitionQualifiedUnavailableEvidence(
            self.source_request_sha256,
            self.support_or_availability_authority_sha256,
            self.unavailable_evidence_sha256,
            copy.deepcopy(self._request_evidence, _memo),
            copy.deepcopy(self._terminal_evidence, _memo),
            copy.deepcopy(self._closure_receipt, _memo),
        )

    def __reduce_ex__(
        self,
        _protocol: SupportsIndex,
    ) -> tuple[type[CompetitionQualifiedUnavailableEvidence], tuple[object, ...]]:
        self._revalidate()
        return (
            CompetitionQualifiedUnavailableEvidence,
            (
                self.source_request_sha256,
                self.support_or_availability_authority_sha256,
                self.unavailable_evidence_sha256,
                self._request_evidence,
                self._terminal_evidence,
                self._closure_receipt,
            ),
        )


def qualify_unavailable_evidence(
    request: CompetitionQualifiedRequest,
    terminal_evidence: RequestTerminalEvidence,
    closure_receipt: RequestClosureReceipt,
) -> CompetitionQualifiedUnavailableEvidence:
    """Qualify exact typed upstream-unavailable evidence under its closure."""

    qualified, _requirement, _provider, evidence, closure, _binding = _terminal_evidence_context(
        request, terminal_evidence, closure_receipt
    )
    if evidence.state != "upstream_unavailable":
        raise NbaApiCompetitionIdentityError(
            "unavailable evidence requires upstream_unavailable terminal state"
        )
    typed = evidence.upstream_unavailable_evidence
    if type(typed) is not TypedUpstreamUnavailableEvidence:
        raise NbaApiCompetitionIdentityError("upstream-unavailable row lacks exact typed evidence")
    body: dict[str, object] = {
        "domain_separator": _UNAVAILABLE_EVIDENCE_DOMAIN,
        "source_request_sha256": qualified.source_request_sha256,
        "support_or_availability_authority_sha256": typed.unavailable_evidence_sha256,
    }
    return CompetitionQualifiedUnavailableEvidence(
        source_request_sha256=qualified.source_request_sha256,
        support_or_availability_authority_sha256=typed.unavailable_evidence_sha256,
        unavailable_evidence_sha256=_digest(body),
        request_evidence=qualified,
        terminal_evidence=evidence,
        closure_receipt=closure,
    )


def _normalized_logical_call_receipt_binding(binding: object) -> Any:
    from nbadb.extract.bronze import LogicalCallReceiptBinding

    if type(binding) is not LogicalCallReceiptBinding:
        raise NbaApiCompetitionIdentityError(
            "logical call receipt binding must be an exact LogicalCallReceiptBinding"
        )
    typed = cast("Any", binding)
    if type(typed.result_route_ids) is not tuple or any(
        type(item) is not str or not item for item in typed.result_route_ids
    ):
        raise NbaApiCompetitionIdentityError("logical call result route IDs are not exact")
    for name in (
        "logical_call_receipt_sha256",
        "endpoint_name",
        "logical_parameters_sha256",
        "provider_authority_sha256",
    ):
        if type(getattr(typed, name)) is not str:
            raise NbaApiCompetitionIdentityError("logical call receipt scalar type drifted")
    try:
        reconstructed = LogicalCallReceiptBinding(
            logical_call_receipt_sha256=typed.logical_call_receipt_sha256,
            endpoint_name=typed.endpoint_name,
            logical_parameters_sha256=typed.logical_parameters_sha256,
            provider_authority_sha256=typed.provider_authority_sha256,
            result_route_ids=typed.result_route_ids,
        )
    except (TypeError, ValueError) as exc:
        raise NbaApiCompetitionIdentityError(
            "logical call receipt binding did not revalidate"
        ) from exc
    if not _exact_typed_equal(typed, reconstructed):
        raise NbaApiCompetitionIdentityError("logical call receipt public state drifted")
    return reconstructed


def _normalized_committed_staging_receipt(receipt: object) -> Any:
    from nbadb.orchestrate.staging_batches import (
        CANONICAL_FRAME_FORMAT,
        FRAME_CONTENT_HASH_CONTRACT,
        FRAME_SCHEMA_HASH_CONTRACT,
        CommittedStagingChunkReceiptV2,
    )

    if type(receipt) is not CommittedStagingChunkReceiptV2:
        raise NbaApiCompetitionIdentityError(
            "committed receipt must be an exact CommittedStagingChunkReceiptV2"
        )
    typed = cast("Any", receipt)
    for name in (
        "chunk_id",
        "staging_key",
        "canonical_frame_format",
        "frame_content_hash_contract",
        "frame_schema_hash_contract",
        "content_hash",
        "persisted_content_sha256",
        "persisted_schema_sha256",
        "logical_call_receipt_sha256",
        "provider_authority_sha256",
        "logical_parameters_sha256",
        "result_route_id",
    ):
        if type(getattr(typed, name, None)) is not str:
            raise NbaApiCompetitionIdentityError("committed receipt scalar type drifted")
    if (
        typed.canonical_frame_format != CANONICAL_FRAME_FORMAT
        or typed.frame_content_hash_contract != FRAME_CONTENT_HASH_CONTRACT
        or typed.frame_schema_hash_contract != FRAME_SCHEMA_HASH_CONTRACT
    ):
        raise NbaApiCompetitionIdentityError(
            "committed staging receipt uses stale or unsupported V2 contract IDs; "
            "full restart required"
        )
    if type(typed.persisted_row_count) is not int:
        raise NbaApiCompetitionIdentityError("committed receipt row count type drifted")
    try:
        reconstructed = CommittedStagingChunkReceiptV2(
            chunk_id=typed.chunk_id,
            staging_key=typed.staging_key,
            canonical_frame_format=typed.canonical_frame_format,
            frame_content_hash_contract=typed.frame_content_hash_contract,
            frame_schema_hash_contract=typed.frame_schema_hash_contract,
            content_hash=typed.content_hash,
            persisted_row_count=typed.persisted_row_count,
            persisted_content_sha256=typed.persisted_content_sha256,
            persisted_schema_sha256=typed.persisted_schema_sha256,
            logical_call_receipt_sha256=typed.logical_call_receipt_sha256,
            provider_authority_sha256=typed.provider_authority_sha256,
            logical_parameters_sha256=typed.logical_parameters_sha256,
            result_route_id=typed.result_route_id,
        )
    except (ParserInputCaptureIntegrityError, TypeError, ValueError) as exc:
        raise NbaApiCompetitionIdentityError(
            "committed staging receipt did not revalidate"
        ) from exc
    if not _exact_typed_equal(typed, reconstructed):
        raise NbaApiCompetitionIdentityError("committed staging receipt public state drifted")
    return reconstructed


def _canonical_staging_route(route: object) -> Any:
    from nbadb.contracts.staging_route_contract import (
        StagingRouteContract,
        staging_route_contract_bundle,
    )

    if type(route) is not StagingRouteContract:
        raise NbaApiCompetitionIdentityError("route must be an exact StagingRouteContract")
    typed = cast("Any", route)
    bundle = staging_route_contract_bundle()
    canonical = bundle.by_route_id.get(typed.route_id)
    if (
        canonical is None
        or type(canonical) is not StagingRouteContract
        or not _exact_typed_equal(typed, canonical)
        or typed.contract_sha256 != canonical.contract_sha256
    ):
        raise NbaApiCompetitionIdentityError("staging route is not exact and pinned")
    return canonical


def _staging_occurrence_body(
    request: CompetitionQualifiedRequest,
    observation: object,
    execution_authority: object,
    logical_call_receipt_binding: object,
    route: object,
    committed_receipt: object,
) -> tuple[CompetitionQualifiedRequest, Any, Any, Any, Any, Any, dict[str, object]]:
    (
        qualified,
        requirement,
        _provider,
        observed,
        authority,
    ) = _runtime_evidence_context(request, observation, execution_authority)
    expected_provider = _expected_provider_authority()
    logical_calls = [
        item
        for item in authority.logical_calls
        if item.provider_request_sha256 == qualified.provider_request_sha256
        and item.endpoint_name == requirement.repo_endpoint_name
    ]
    if len(logical_calls) != 1:
        raise NbaApiCompetitionIdentityError("execution logical call is not unique")
    logical_call = logical_calls[0]
    if logical_call.route_ids != observed.route_ids:
        raise NbaApiCompetitionIdentityError("execution logical-call routes drifted")
    receipt_binding = _normalized_logical_call_receipt_binding(logical_call_receipt_binding)
    aliases = [
        item
        for item in authority.staging_route_aliases
        if item.manifest_route_id in logical_call.route_ids
    ]
    if len(aliases) != len(logical_call.route_ids) or {
        item.manifest_route_id for item in aliases
    } != set(logical_call.route_ids):
        raise NbaApiCompetitionIdentityError("staging route alias projection is incomplete")
    physical_route_ids = tuple(sorted(item.staging_route_id for item in aliases))
    if physical_route_ids != receipt_binding.result_route_ids:
        raise NbaApiCompetitionIdentityError(
            "logical call receipt routes differ from execution aliases"
        )
    canonical_route = _canonical_staging_route(route)
    if sum(item.staging_route_id == canonical_route.route_id for item in aliases) != 1:
        raise NbaApiCompetitionIdentityError("selected route is not one exact execution alias")
    if (
        receipt_binding.endpoint_name != logical_call.endpoint_name
        or receipt_binding.logical_parameters_sha256 != logical_call.logical_parameters_sha256
        or receipt_binding.provider_authority_sha256 != expected_provider
    ):
        raise NbaApiCompetitionIdentityError("logical call receipt authority drifted")
    if (
        canonical_route.source_family != requirement.source_family
        or canonical_route.provider_endpoint_id != requirement.provider_endpoint_id
        or canonical_route.endpoint_name != requirement.repo_endpoint_name
        or canonical_route.provider_authority_sha256 != expected_provider
    ):
        raise NbaApiCompetitionIdentityError("staging route requirement binding drifted")
    if (
        canonical_route.canonical_result_set_name is None
        or canonical_route.provider_result_set_name is None
        or canonical_route.canonical_result_set_name != canonical_route.provider_result_set_name
    ):
        raise NbaApiCompetitionIdentityError(
            "staging route has no exact structural result-set name"
        )
    committed = _normalized_committed_staging_receipt(committed_receipt)
    if (
        committed.result_route_id != canonical_route.route_id
        or committed.staging_key != canonical_route.staging_key
        or committed.provider_authority_sha256 != canonical_route.provider_authority_sha256
        or committed.logical_parameters_sha256 != receipt_binding.logical_parameters_sha256
        or committed.logical_call_receipt_sha256 != receipt_binding.logical_call_receipt_sha256
    ):
        raise NbaApiCompetitionIdentityError("committed staging receipt binding drifted")
    persisted_matches = [
        item
        for item in observed.staging_receipts
        if item.staging_key == canonical_route.staging_key
        and item.result_set_ordinal == canonical_route.declared_result_set_index
        and item.result_set_ordinal == canonical_route.canonical_result_set_ordinal
        and item.result_set_name == canonical_route.canonical_result_set_name
        and item.result_set_name == canonical_route.provider_result_set_name
        and item.staging_receipt_root_sha256 == committed.receipt_root_sha256
    ]
    if len(persisted_matches) != 1:
        raise NbaApiCompetitionIdentityError(
            "observation has no exact persisted staging receipt for the route"
        )
    persisted = persisted_matches[0]
    if persisted.row_count != committed.persisted_row_count:
        raise NbaApiCompetitionIdentityError("persisted staging row count drifted")
    ordinal = _require_nonnegative_int(persisted.result_set_ordinal, "staging result ordinal")
    body: dict[str, object] = {
        "domain_separator": _STAGING_OCCURRENCE_DOMAIN,
        "source_request_sha256": qualified.source_request_sha256,
        "route_contract_sha256": canonical_route.contract_sha256,
        "result_ordinal": ordinal,
        "logical_call_receipt_sha256": committed.logical_call_receipt_sha256,
        "committed_staging_receipt_sha256": committed.receipt_root_sha256,
    }
    return (
        qualified,
        observed,
        authority,
        receipt_binding,
        canonical_route,
        committed,
        body,
    )


@dataclass(frozen=True, slots=True)
class CompetitionQualifiedStagingOccurrence:
    """One exact committed staging occurrence bound to a qualified request."""

    source_request_sha256: str
    route_contract_sha256: str
    result_ordinal: int
    logical_call_receipt_sha256: str
    committed_staging_receipt_sha256: str
    staging_occurrence_sha256: str
    request_evidence: InitVar[CompetitionQualifiedRequest]
    observation_evidence: InitVar[object]
    execution_authority_evidence: InitVar[object]
    logical_call_receipt_binding_evidence: InitVar[object]
    route_evidence: InitVar[object]
    committed_receipt_evidence: InitVar[object]
    _request_evidence: CompetitionQualifiedRequest = field(init=False, repr=False, compare=False)
    _observation_evidence: object = field(init=False, repr=False, compare=False)
    _execution_authority_evidence: object = field(init=False, repr=False, compare=False)
    _logical_call_receipt_binding_evidence: object = field(init=False, repr=False, compare=False)
    _route_evidence: object = field(init=False, repr=False, compare=False)
    _committed_receipt_evidence: object = field(init=False, repr=False, compare=False)

    def __post_init__(
        self,
        request_evidence: CompetitionQualifiedRequest,
        observation_evidence: object,
        execution_authority_evidence: object,
        logical_call_receipt_binding_evidence: object,
        route_evidence: object,
        committed_receipt_evidence: object,
    ) -> None:
        object.__setattr__(self, "_request_evidence", request_evidence)
        object.__setattr__(self, "_observation_evidence", observation_evidence)
        object.__setattr__(self, "_execution_authority_evidence", execution_authority_evidence)
        object.__setattr__(
            self,
            "_logical_call_receipt_binding_evidence",
            logical_call_receipt_binding_evidence,
        )
        object.__setattr__(self, "_route_evidence", route_evidence)
        object.__setattr__(self, "_committed_receipt_evidence", committed_receipt_evidence)
        self._revalidate()

    def _revalidate(self) -> None:
        *_, body = _staging_occurrence_body(
            self._request_evidence,
            self._observation_evidence,
            self._execution_authority_evidence,
            self._logical_call_receipt_binding_evidence,
            self._route_evidence,
            self._committed_receipt_evidence,
        )
        expected = (
            body["source_request_sha256"],
            body["route_contract_sha256"],
            body["result_ordinal"],
            body["logical_call_receipt_sha256"],
            body["committed_staging_receipt_sha256"],
            _digest(body),
        )
        observed = (
            self.source_request_sha256,
            self.route_contract_sha256,
            self.result_ordinal,
            self.logical_call_receipt_sha256,
            self.committed_staging_receipt_sha256,
            self.staging_occurrence_sha256,
        )
        if not _exact_typed_equal(observed, expected):
            raise NbaApiCompetitionIdentityError("staging occurrence identity drifted")

    def to_dict(self) -> dict[str, object]:
        self._revalidate()
        return {
            "source_request_sha256": self.source_request_sha256,
            "route_contract_sha256": self.route_contract_sha256,
            "result_ordinal": self.result_ordinal,
            "logical_call_receipt_sha256": self.logical_call_receipt_sha256,
            "committed_staging_receipt_sha256": self.committed_staging_receipt_sha256,
            "staging_occurrence_sha256": self.staging_occurrence_sha256,
        }


def qualify_staging_occurrence(
    request: CompetitionQualifiedRequest,
    observation: object,
    execution_authority: object,
    logical_call_receipt_binding: object,
    route: object,
    committed_receipt: object,
) -> CompetitionQualifiedStagingOccurrence:
    """Qualify one exact receipt-backed staging route occurrence."""

    (
        qualified,
        observed,
        authority,
        receipt_binding,
        canonical_route,
        committed,
        body,
    ) = _staging_occurrence_body(
        request,
        observation,
        execution_authority,
        logical_call_receipt_binding,
        route,
        committed_receipt,
    )
    return CompetitionQualifiedStagingOccurrence(
        source_request_sha256=cast("str", body["source_request_sha256"]),
        route_contract_sha256=cast("str", body["route_contract_sha256"]),
        result_ordinal=cast("int", body["result_ordinal"]),
        logical_call_receipt_sha256=cast("str", body["logical_call_receipt_sha256"]),
        committed_staging_receipt_sha256=cast("str", body["committed_staging_receipt_sha256"]),
        staging_occurrence_sha256=_digest(body),
        request_evidence=qualified,
        observation_evidence=observed,
        execution_authority_evidence=authority,
        logical_call_receipt_binding_evidence=receipt_binding,
        route_evidence=canonical_route,
        committed_receipt_evidence=committed,
    )


def _packet_dict(packet: Mapping[str, object], name: str) -> dict[str, object]:
    value = packet.get(name)
    if type(value) is not dict:
        raise NbaApiCompetitionIdentityError(f"TaskPacket {name} must be an exact object")
    return cast("dict[str, object]", value)


def _packet_list(packet: Mapping[str, object], name: str) -> list[object]:
    value = packet.get(name)
    if type(value) is not list:
        raise NbaApiCompetitionIdentityError(f"TaskPacket {name} must be an exact array")
    return cast("list[object]", value)


def _authenticate_resource_file(relative_path: str, expected_sha256: str) -> str:
    prefix = "src/nbadb/contracts/"
    if not relative_path.startswith(prefix) or "/" in relative_path.removeprefix(prefix):
        raise NbaApiCompetitionIdentityError(
            f"competition identity predecessor path is invalid: {relative_path}"
        )
    try:
        raw = (
            resources.files("nbadb.contracts")
            .joinpath(relative_path.removeprefix(prefix))
            .read_bytes()
        )
    except (AttributeError, OSError) as exc:
        raise NbaApiCompetitionIdentityError(
            f"competition identity predecessor cannot be read: {relative_path}"
        ) from exc
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise NbaApiCompetitionIdentityError(
            f"competition identity predecessor bytes drifted: {relative_path}"
        )
    return expected_sha256


def _source_authorities() -> dict[str, object]:
    terminal = load_pinned_terminal_state_payload()
    request_payload = load_pinned_request_surface_payload()
    competition_payload = load_pinned_competition_payload()
    applicability_payload = load_pinned_competition_applicability_payload()
    implicit_payload = load_pinned_implicit_competition_payload()
    request = pinned_request_surface_authority()
    competition = pinned_competition_authority()
    applicability = pinned_competition_applicability_authority()
    implicit = pinned_implicit_competition_authority()
    _proof_body, proof_sha256 = _implicit_supersession_proof()
    observed = (
        _authenticate_resource_file(_TERMINAL_RESOURCE_PATH, _TERMINAL_RESOURCE_SHA256),
        terminal.get("payload_sha256"),
        terminal.get("terminal_policy_sha256"),
        _authenticate_resource_file(_REQUEST_RESOURCE_PATH, _REQUEST_RESOURCE_SHA256),
        request_payload.get("payload_sha256"),
        request.surface_sha256,
        request.runtime_contract_payload_sha256,
        request_payload.get("terminal_policy_sha256"),
        _authenticate_resource_file(
            _COMPETITION_RESOURCE_PATH,
            _COMPETITION_RESOURCE_SHA256,
        ),
        competition_payload.get("payload_sha256"),
        competition.authority_sha256,
        _authenticate_resource_file(
            _APPLICABILITY_RESOURCE_PATH,
            _APPLICABILITY_RESOURCE_SHA256,
        ),
        applicability_payload.get("payload_sha256"),
        applicability.authority_sha256,
        _authenticate_resource_file(_IMPLICIT_RESOURCE_PATH, _IMPLICIT_RESOURCE_SHA256),
        implicit_payload.get("payload_sha256"),
        implicit.authority_sha256,
        proof_sha256,
    )
    expected = (
        _TERMINAL_RESOURCE_SHA256,
        _TERMINAL_PAYLOAD_SHA256,
        _TERMINAL_POLICY_SHA256,
        _REQUEST_RESOURCE_SHA256,
        _REQUEST_PAYLOAD_SHA256,
        _REQUEST_SURFACE_SHA256,
        _REQUEST_RUNTIME_CONTRACT_PAYLOAD_SHA256,
        _TERMINAL_POLICY_SHA256,
        _COMPETITION_RESOURCE_SHA256,
        _COMPETITION_PAYLOAD_SHA256,
        _COMPETITION_AUTHORITY_SHA256,
        _APPLICABILITY_RESOURCE_SHA256,
        _APPLICABILITY_PAYLOAD_SHA256,
        _APPLICABILITY_AUTHORITY_SHA256,
        _IMPLICIT_RESOURCE_SHA256,
        _IMPLICIT_PAYLOAD_SHA256,
        _IMPLICIT_AUTHORITY_SHA256,
        _IMPLICIT_SUPERSESSION_PROOF_SHA256,
    )
    if observed != expected:
        raise NbaApiCompetitionIdentityError("competition identity predecessor authority drifted")
    authorities = {
        "task_packet": {"path": _TASK_PACKET, "sha256": _TASK_PACKET_SHA256},
        "identity_contract": {
            "path": _IDENTITY_CONTRACT_PACKET,
            "sha256": _IDENTITY_CONTRACT_PACKET_SHA256,
        },
        "terminal_state": {
            "path": _TERMINAL_RESOURCE_PATH,
            "resource_sha256": _TERMINAL_RESOURCE_SHA256,
            "payload_sha256": _TERMINAL_PAYLOAD_SHA256,
            "terminal_policy_sha256": _TERMINAL_POLICY_SHA256,
        },
        "request_surface": {
            "path": _REQUEST_RESOURCE_PATH,
            "resource_sha256": _REQUEST_RESOURCE_SHA256,
            "payload_sha256": _REQUEST_PAYLOAD_SHA256,
            "surface_sha256": _REQUEST_SURFACE_SHA256,
            "runtime_contract_payload_sha256": (_REQUEST_RUNTIME_CONTRACT_PAYLOAD_SHA256),
            "terminal_policy_sha256": _TERMINAL_POLICY_SHA256,
        },
        "competition": {
            "path": _COMPETITION_RESOURCE_PATH,
            "resource_sha256": _COMPETITION_RESOURCE_SHA256,
            "payload_sha256": _COMPETITION_PAYLOAD_SHA256,
            "authority_sha256": _COMPETITION_AUTHORITY_SHA256,
        },
        "competition_applicability": {
            "path": _APPLICABILITY_RESOURCE_PATH,
            "resource_sha256": _APPLICABILITY_RESOURCE_SHA256,
            "payload_sha256": _APPLICABILITY_PAYLOAD_SHA256,
            "authority_sha256": _APPLICABILITY_AUTHORITY_SHA256,
        },
        "implicit_competition": {
            "path": _IMPLICIT_RESOURCE_PATH,
            "resource_sha256": _IMPLICIT_RESOURCE_SHA256,
            "payload_sha256": _IMPLICIT_PAYLOAD_SHA256,
            "authority_sha256": _IMPLICIT_AUTHORITY_SHA256,
            "historical": True,
        },
        "implicit_supersession_proof": {"proof_sha256": _IMPLICIT_SUPERSESSION_PROOF_SHA256},
    }
    if set(authorities) != {
        "task_packet",
        "identity_contract",
        "terminal_state",
        "request_surface",
        "competition",
        "competition_applicability",
        "implicit_competition",
        "implicit_supersession_proof",
    }:
        raise NbaApiCompetitionIdentityError("source authority keys drifted")
    return authorities


def _collision_census(packet: Mapping[str, object]) -> dict[str, object]:
    contract = _packet_dict(packet, "collision_census_contract")
    inventory = copy.deepcopy(_packet_list(packet, "source_inventory_inputs"))
    return {
        "source_inventory_file_count": contract.get("source_inventory_file_count"),
        "source_inventory_inputs": inventory,
        "source_inventory_inputs_sha256": packet.get("source_inventory_inputs_sha256"),
        "direct_source_inventory_is_sufficient": contract.get(
            "direct_source_inventory_is_sufficient"
        ),
        "separate_authored_source_evidence_required": contract.get(
            "separate_authored_source_evidence_required"
        ),
        "source_spelling_or_history_authorizes_competition": contract.get(
            "source_spelling_or_history_authorizes_competition"
        ),
    }


def _checked_resource_body(
    requirements: tuple[CompetitionIdentityRequirement, ...],
) -> dict[str, object]:
    _task_packet_payload()
    packet = _identity_contract_payload()
    checked = _packet_dict(packet, "checked_resource_contract")
    requirement_rows = [item.to_dict() for item in requirements]
    surfaces = copy.deepcopy(_packet_list(packet, "qualified_surface_contracts"))
    body: dict[str, object] = {
        "schema_version": COMPETITION_IDENTITY_SCHEMA_VERSION,
        "kind": checked.get("kind"),
        "task_id": "A1.3a-repair-11",
        "source_authorities": _source_authorities(),
        "collision_census": _collision_census(packet),
        "domain_separators": copy.deepcopy(_packet_list(packet, "domain_separators")),
        "identity_requirements": requirement_rows,
        "identity_requirements_sha256": _digest(requirement_rows),
        "qualified_surface_contracts": surfaces,
        "qualified_surface_contracts_sha256": _digest(surfaces),
        "denominator_counts": copy.deepcopy(_packet_dict(packet, "denominator_authority")),
        "binding_strategy_counts": copy.deepcopy(_packet_dict(packet, "binding_strategy_counts")),
        "provider_request_policy": copy.deepcopy(_packet_dict(packet, "provider_request_policy")),
        "provider_availability_values": copy.deepcopy(
            _packet_list(checked, "provider_availability_values")
        ),
        "false_green_counters": copy.deepcopy(_packet_dict(packet, "false_green_counters")),
        "collision_invariants": copy.deepcopy(_packet_dict(packet, "collision_invariants")),
        "independent_proof": {
            "required": True,
            "verifier_id": "nbadb_independent_competition_identity_v2",
        },
    }
    expected_keys = _packet_list(checked, "top_level_keys")[:-2]
    if list(body) != expected_keys:
        raise NbaApiCompetitionIdentityError("checked resource body key order drifted")
    if body["qualified_surface_contracts_sha256"] != _QUALIFIED_SURFACE_CONTRACTS_SHA256:
        raise NbaApiCompetitionIdentityError("qualified surface digest drifted")
    return body


@dataclass(frozen=True, slots=True)
class CompetitionIdentityAuthority:
    """Deeply immutable primary authority over all competition requirements."""

    task_packet_sha256: str
    terminal_policy_sha256: str
    request_surface_sha256: str
    competition_authority_sha256: str
    competition_applicability_authority_sha256: str
    implicit_competition_authority_sha256: str
    implicit_supersession_proof_sha256: str
    source_inventory_inputs_sha256: str
    identity_requirements: tuple[CompetitionIdentityRequirement, ...]
    identity_requirements_sha256: str
    qualified_surface_contracts_sha256: str
    binding_strategy_counts: tuple[tuple[str, int], ...]
    collision_invariants: tuple[tuple[str, bool], ...]
    authority_sha256: str

    def __post_init__(self) -> None:
        self._revalidate()

    def _revalidate(self) -> None:
        for name, expected in (
            ("task_packet_sha256", _TASK_PACKET_SHA256),
            ("terminal_policy_sha256", _TERMINAL_POLICY_SHA256),
            ("request_surface_sha256", _REQUEST_SURFACE_SHA256),
            ("competition_authority_sha256", _COMPETITION_AUTHORITY_SHA256),
            (
                "competition_applicability_authority_sha256",
                _APPLICABILITY_AUTHORITY_SHA256,
            ),
            ("implicit_competition_authority_sha256", _IMPLICIT_AUTHORITY_SHA256),
            (
                "implicit_supersession_proof_sha256",
                _IMPLICIT_SUPERSESSION_PROOF_SHA256,
            ),
            ("source_inventory_inputs_sha256", _SOURCE_INVENTORY_INPUTS_SHA256),
            (
                "qualified_surface_contracts_sha256",
                _QUALIFIED_SURFACE_CONTRACTS_SHA256,
            ),
        ):
            if _require_sha256(getattr(self, name), name) != expected:
                raise NbaApiCompetitionIdentityError(f"{name} drifted")
        if (
            type(self.identity_requirements) is not tuple
            or len(self.identity_requirements) != 815
            or any(
                type(item) is not CompetitionIdentityRequirement
                for item in self.identity_requirements
            )
            or not _exact_typed_equal(
                self.identity_requirements, compile_competition_identity_requirements()
            )
        ):
            raise NbaApiCompetitionIdentityError("authority requirement tuple drifted")
        requirement_rows = [item.to_dict() for item in self.identity_requirements]
        if _require_sha256(
            self.identity_requirements_sha256, "identity_requirements_sha256"
        ) != _digest(requirement_rows):
            raise NbaApiCompetitionIdentityError("identity requirement inventory digest drifted")
        packet = _identity_contract_payload()
        expected_counts = tuple(
            sorted(
                (
                    _require_text(key, "binding strategy count key"),
                    _require_nonnegative_int(value, "binding strategy count"),
                )
                for key, value in _packet_dict(packet, "binding_strategy_counts").items()
            )
        )
        if type(self.binding_strategy_counts) is not tuple or not _exact_typed_equal(
            self.binding_strategy_counts, expected_counts
        ):
            raise NbaApiCompetitionIdentityError("binding strategy count tuple drifted")
        expected_invariants = tuple(
            sorted(
                (
                    _require_text(key, "collision invariant key"),
                    value,
                )
                for key, value in _packet_dict(packet, "collision_invariants").items()
            )
        )
        if any(type(value) is not bool for _key, value in expected_invariants) or (
            type(self.collision_invariants) is not tuple
            or not _exact_typed_equal(self.collision_invariants, expected_invariants)
        ):
            raise NbaApiCompetitionIdentityError("collision invariant tuple drifted")
        if _require_sha256(self.authority_sha256, "authority_sha256") != _digest(
            _checked_resource_body(self.identity_requirements)
        ):
            raise NbaApiCompetitionIdentityError("checked resource authority digest drifted")

    def to_dict(self) -> dict[str, object]:
        self._revalidate()
        return {
            "task_packet_sha256": self.task_packet_sha256,
            "terminal_policy_sha256": self.terminal_policy_sha256,
            "request_surface_sha256": self.request_surface_sha256,
            "competition_authority_sha256": self.competition_authority_sha256,
            "competition_applicability_authority_sha256": (
                self.competition_applicability_authority_sha256
            ),
            "implicit_competition_authority_sha256": (self.implicit_competition_authority_sha256),
            "implicit_supersession_proof_sha256": (self.implicit_supersession_proof_sha256),
            "source_inventory_inputs_sha256": self.source_inventory_inputs_sha256,
            "identity_requirements": [item.to_dict() for item in self.identity_requirements],
            "identity_requirements_sha256": self.identity_requirements_sha256,
            "qualified_surface_contracts_sha256": (self.qualified_surface_contracts_sha256),
            "binding_strategy_counts": dict(self.binding_strategy_counts),
            "collision_invariants": dict(self.collision_invariants),
            "authority_sha256": self.authority_sha256,
        }


@lru_cache(maxsize=1)
def build_competition_identity_authority() -> CompetitionIdentityAuthority:
    """Build the complete primary authority from the sealed predecessors."""

    _task_packet_payload()
    packet = _identity_contract_payload()
    requirements = compile_competition_identity_requirements()
    requirement_rows = [item.to_dict() for item in requirements]
    binding_counts = tuple(
        sorted(
            (key, cast("int", value))
            for key, value in _packet_dict(packet, "binding_strategy_counts").items()
        )
    )
    collision_invariants = tuple(
        sorted(
            (key, cast("bool", value))
            for key, value in _packet_dict(packet, "collision_invariants").items()
        )
    )
    body = _checked_resource_body(requirements)
    return CompetitionIdentityAuthority(
        task_packet_sha256=_TASK_PACKET_SHA256,
        terminal_policy_sha256=_TERMINAL_POLICY_SHA256,
        request_surface_sha256=_REQUEST_SURFACE_SHA256,
        competition_authority_sha256=_COMPETITION_AUTHORITY_SHA256,
        competition_applicability_authority_sha256=_APPLICABILITY_AUTHORITY_SHA256,
        implicit_competition_authority_sha256=_IMPLICIT_AUTHORITY_SHA256,
        implicit_supersession_proof_sha256=_IMPLICIT_SUPERSESSION_PROOF_SHA256,
        source_inventory_inputs_sha256=_SOURCE_INVENTORY_INPUTS_SHA256,
        identity_requirements=requirements,
        identity_requirements_sha256=_digest(requirement_rows),
        qualified_surface_contracts_sha256=_QUALIFIED_SURFACE_CONTRACTS_SHA256,
        binding_strategy_counts=binding_counts,
        collision_invariants=collision_invariants,
        authority_sha256=_digest(body),
    )


def build_pinned_competition_identity_payload() -> dict[str, object]:
    """Build the exact canonical checked competition-identity resource."""

    authority = build_competition_identity_authority()
    payload = _checked_resource_body(authority.identity_requirements)
    if _digest(payload) != authority.authority_sha256:
        raise NbaApiCompetitionIdentityError("authority and payload body differ")
    payload["authority_sha256"] = authority.authority_sha256
    payload["payload_sha256"] = _digest(payload)
    checked = _packet_dict(_identity_contract_payload(), "checked_resource_contract")
    if list(payload) != _packet_list(checked, "top_level_keys"):
        raise NbaApiCompetitionIdentityError("checked resource top-level keys drifted")
    return payload


def write_pinned_competition_identity(path: Path, *, check: bool = False) -> bool:
    """Write, or exactly check, the canonical pretty checked resource."""

    if not isinstance(path, Path) or type(check) is not bool:
        raise NbaApiCompetitionIdentityError("writer arguments are not exact")
    encoded = _pretty_bytes(build_pinned_competition_identity_payload())
    if path.is_file() and path.read_bytes() == encoded:
        return True
    if check:
        raise NbaApiCompetitionIdentityError(
            "pinned competition identity authority has generated drift"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return False


def load_pinned_competition_identity_payload(
    path: Path | None = None,
) -> dict[str, object]:
    """Load the checked resource and reproduce every current sealed edge."""

    if path is not None and not isinstance(path, Path):
        raise NbaApiCompetitionIdentityError("resource path must be an exact Path")
    try:
        raw = (
            resources.files("nbadb.contracts").joinpath(COMPETITION_IDENTITY_RESOURCE).read_bytes()
            if path is None
            else path.read_bytes()
        )
    except (AttributeError, OSError) as exc:
        raise NbaApiCompetitionIdentityError(
            "competition identity checked resource cannot be read"
        ) from exc
    payload = _strict_json(raw, label="competition identity checked resource", pretty=True)
    checked = _packet_dict(_identity_contract_payload(), "checked_resource_contract")
    expected_keys = _packet_list(checked, "top_level_keys")
    if set(payload) != set(expected_keys) or len(payload) != len(expected_keys):
        raise NbaApiCompetitionIdentityError("checked resource top-level schema drifted")
    without_payload = dict(payload)
    supplied_payload = without_payload.pop("payload_sha256", None)
    if _require_sha256(supplied_payload, "payload_sha256") != _digest(without_payload):
        raise NbaApiCompetitionIdentityError("checked resource payload digest is invalid")
    without_authority = dict(without_payload)
    supplied_authority = without_authority.pop("authority_sha256", None)
    if _require_sha256(supplied_authority, "authority_sha256") != _digest(without_authority):
        raise NbaApiCompetitionIdentityError("checked resource authority digest is invalid")
    expected = build_pinned_competition_identity_payload()
    if not _exact_typed_equal(payload, expected):
        raise NbaApiCompetitionIdentityError(
            "checked resource differs from current sealed authorities"
        )
    return payload


@lru_cache(maxsize=1)
def pinned_competition_identity_authority() -> CompetitionIdentityAuthority:
    """Return the authority only after checked-resource independent verification."""

    payload = load_pinned_competition_identity_payload()
    authority = build_competition_identity_authority()
    from nbadb.core.nba_api_competition_identity_verifier import (
        verify_pinned_competition_identity_authority,
    )

    proof = verify_pinned_competition_identity_authority()
    if (
        proof.task_packet_sha256 != authority.task_packet_sha256
        or proof.terminal_policy_sha256 != authority.terminal_policy_sha256
        or proof.request_surface_sha256 != authority.request_surface_sha256
        or proof.source_inventory_inputs_sha256 != authority.source_inventory_inputs_sha256
        or proof.competition_applicability_authority_sha256
        != authority.competition_applicability_authority_sha256
        or proof.implicit_competition_authority_sha256
        != authority.implicit_competition_authority_sha256
        or proof.implicit_supersession_proof_sha256 != authority.implicit_supersession_proof_sha256
        or proof.candidate_authority_sha256 != authority.authority_sha256
        or proof.candidate_payload_sha256 != payload.get("payload_sha256")
        or proof.identity_requirements_sha256 != authority.identity_requirements_sha256
        or proof.qualified_surface_contracts_sha256 != authority.qualified_surface_contracts_sha256
        or proof.identity_requirement_count != len(authority.identity_requirements)
        or proof.qualified_surface_contract_count != 8
        or proof.finding_count != 0
        or proof.findings
    ):
        raise NbaApiCompetitionIdentityError(
            "primary and independent competition identity authorities differ"
        )
    return authority


__all__ = [
    "COMPETITION_IDENTITY_RESOURCE",
    "COMPETITION_IDENTITY_SCHEMA_VERSION",
    "CompetitionIdentityAuthority",
    "CompetitionIdentityRequirement",
    "CompetitionQualifiedDiscoveryGeneration",
    "CompetitionQualifiedEntityIdentity",
    "CompetitionQualifiedPaginationPage",
    "CompetitionQualifiedPaginationSeries",
    "CompetitionQualifiedRequest",
    "CompetitionQualifiedStagingOccurrence",
    "CompetitionQualifiedTerminalObservation",
    "CompetitionQualifiedUnavailableEvidence",
    "CompetitionRoleBinding",
    "NbaApiCompetitionIdentityError",
    "bind_explicit_competition_request",
    "bind_receipt_root_competition_request",
    "bind_static_competition_source",
    "build_competition_identity_authority",
    "build_competition_terminal_request_binding",
    "build_pinned_competition_identity_payload",
    "compile_competition_identity_requirements",
    "load_pinned_competition_identity_payload",
    "pinned_competition_identity_authority",
    "qualify_discovery_generation",
    "qualify_entity_identity",
    "qualify_pagination_page",
    "qualify_pagination_series",
    "qualify_staging_occurrence",
    "qualify_terminal_observation",
    "qualify_unavailable_evidence",
    "write_pinned_competition_identity",
]
