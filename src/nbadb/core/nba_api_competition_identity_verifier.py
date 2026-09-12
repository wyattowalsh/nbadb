"""Independent offline verifier for the pinned competition identity authority.

The candidate checked resource is deliberately the final input read.  Before
that read, this module authenticates the repair, superseded, and semantic
packets, their inventory commitments, and only the required current resources.
It then independently reconstructs all requirement and qualified-surface rows
without reading stale source-inventory paths.  It performs no network or
provider operation and has no dependency on the compiler that writes the
candidate.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, fields
from importlib import resources
from pathlib import Path
from typing import Final, SupportsIndex, cast

_PACKAGED_TASK_PACKET_ROOT: Final = (
    "provenance",
    "nba_api_v1_11_4",
    "competition_identity",
)
_TASK_PACKET_REL: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-11.json"
)
_TASK_PACKET_SHA256: Final = "5f0cb0d04f9e46f412458489ba0d088193e18ba128f1739a2c03d87b4b5e57da"
_REPAIR_10_TASK_PACKET_REL: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-10.json"
)
_REPAIR_10_TASK_PACKET_SHA256: Final = (
    "86841cb180f840f545e11bcb8351e0d8c33dc73b35131e4343dad4f2c69493fb"
)
_REPAIR_9_TASK_PACKET_REL: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-9.json"
)
_REPAIR_9_TASK_PACKET_SHA256: Final = (
    "2e3ba24efd741f36843cc6889a566a56479c140ebf5b940f8e087a509c1f26b1"
)
_REPAIR_8_TASK_PACKET_REL: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-8.json"
)
_REPAIR_8_TASK_PACKET_SHA256: Final = (
    "cdcc5ebfd9a421dfad4687a875e321758df4af1bf65b10523146474843a6ffd5"
)
_REPAIR_7_TASK_PACKET_REL: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-7.json"
)
_REPAIR_7_TASK_PACKET_SHA256: Final = (
    "edcac7bc3665b75abb27f6620e6bee6beae8e8004d54dab0ea14964f3ce9fb90"
)
_REPAIR_6_TASK_PACKET_REL: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-6.json"
)
_REPAIR_6_TASK_PACKET_SHA256: Final = (
    "3f70b85f91b6ac00cbaf0afb6f29b17c116e03feddf4db3b6c50b1ac20d26b81"
)
_REPAIR_5_TASK_PACKET_REL: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-5.json"
)
_REPAIR_5_TASK_PACKET_SHA256: Final = (
    "e580c8b09906b0c61d5963ba254621733ac1b5342d1e336b004e7103f200a28f"
)
_REPAIR_4_TASK_PACKET_REL: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-4.json"
)
_REPAIR_4_TASK_PACKET_SHA256: Final = (
    "50a6a3aac9ae745310abd70cd6329b0ae0fccf400f6abf95812e973541cfc7cc"
)
_REPAIR_3_TASK_PACKET_REL: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-3.json"
)
_REPAIR_3_TASK_PACKET_SHA256: Final = (
    "fb416dae2138193e46f0176b5ffe614ccae1f9f63732cbc7dc539117f7b27313"
)
_REPAIR_2_TASK_PACKET_REL: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-2.json"
)
_REPAIR_2_TASK_PACKET_SHA256: Final = (
    "edd3d85dffc4274a6423c32ed5491adfcecafe401d7ad84f42ff261f7d1e4277"
)
_REPAIR_1_TASK_PACKET_REL: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-1.json"
)
_REPAIR_1_TASK_PACKET_SHA256: Final = (
    "d4b8f42ce99a7aa587f123e1bdb3640a50a8f61343a24701d8f662c3b226cb1c"
)
_ORIGINAL_TASK_PACKET_REL: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a.json"
)
_ORIGINAL_TASK_PACKET_SHA256: Final = (
    "a2fea5fc1ef45404d9d917ed13107fc4356646810c222bb9234c832bdb7ed660"
)
_IDENTITY_CONTRACT_REL: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.2e.json"
)
_IDENTITY_CONTRACT_SHA256: Final = (
    "d87507bb66d470dfec88626f8fc9c0b8484fa54dbb1244d564693414e18fc64c"
)
_RESOURCE: Final = "nba_api_competition_identity_v1_11_4.json"
_TERMINAL_RESOURCE: Final = "src/nbadb/contracts/nba_api_terminal_state_v1_11_4.json"
_COMPETITION_RESOURCE: Final = "src/nbadb/contracts/nba_api_competition_v1_11_4.json"
_REQUEST_RESOURCE: Final = "src/nbadb/contracts/nba_api_request_surface_v1_11_4.json"
_APPLICABILITY_RESOURCE: Final = (
    "src/nbadb/contracts/nba_api_competition_applicability_v1_11_4.json"
)
_IMPLICIT_RESOURCE: Final = "src/nbadb/contracts/nba_api_implicit_competition_v1_11_4.json"
_TERMINAL_RESOURCE_SHA256: Final = (
    "9389644949a92046ce3e00491842c3786812cfe043d727dbbdc6b0c84d2ab867"
)
_REQUEST_RESOURCE_SHA256: Final = "3082def2aa92b35d55107f5ce8eaf2ffa0532a0e649899d0f1180979f6144981"
_HISTORICAL_TASK_PACKET_REQUEST_RESOURCE_SHA256: Final = (
    "f156a3583fb4e075cd941971a6287e92e1410077a282e56a9abd033587cd69c1"
)
_COMPETITION_RESOURCE_SHA256: Final = (
    "cfb93458f5efb569995ddccaf33ae37c0c312e25e09d0649c307999ec0057c44"
)
_APPLICABILITY_RESOURCE_SHA256: Final = (
    "daf43b872bd301aa87f1a67b357d970b82e532890e09e7ce0e580545d09cb0aa"
)
_HISTORICAL_TASK_PACKET_APPLICABILITY_RESOURCE_SHA256: Final = (
    "5012a741760f06e10b189da1ac87f00e36dbdac263da08c29457825d46602cbe"
)
_IMPLICIT_RESOURCE_SHA256: Final = (
    "ed75be5cf84df8975cc32d50b51215648896b618584ed5b3b3aedcb8b6dc2111"
)
_TERMINAL_POLICY_SHA256: Final = "7226e797a685755311b7b9073f905d7288150e3412d52d95423ef0093548388d"
_REQUEST_SURFACE_SHA256: Final = "ef6195829a9f1dad9f847094b79e88fae24dffc5c4df18e3d3e972f347f83733"
_IMPLICIT_SUPERSESSION_PROOF_SHA256: Final = (
    "72ef26235ab1ffbc3f3f339ef246151201dfa331f14444a88888eeddd94be7c5"
)
_QUALIFIED_SURFACES_SHA256: Final = (
    "d63d7842e2e68544afe6fa3eb36566f5b4f29138770fe20e76718bce9133c4b4"
)
_IMMUTABLE_INPUTS_SHA256: Final = "5806ae72584f96aa45fd9069026543bf850c8d5f3799c3c007f9db7043cd61aa"
_MUTABLE_OPENING_INPUTS_SHA256: Final = (
    "1b7a7f8df1101678331f5a5f548c62bab63c4a23ecae0f50ce9822b4ac09c568"
)
_SOURCE_INVENTORY_INPUTS_SHA256: Final = (
    "e0795472375627bccefab70ce77764875b03f3152cb44f046ba358d19fd1d7a9"
)
_TERMINAL_PAYLOAD_SHA256: Final = "471f594174107ccb8f582a6ab0459a356acf9daebd75ac55464475b3df792f4d"
_REQUEST_PAYLOAD_SHA256: Final = "b310313f41cf97cf1b8f55e01bbe95868532f3008527bf5265a985628eca9052"
_REQUEST_RUNTIME_PAYLOAD_SHA256: Final = (
    "7c9b59c475cff6b0b9d3619bdfe9a3849e11619980f6d15a1cafd5f269f61b3b"
)
_REQUEST_DERIVATION_POLICY_SHA256: Final = (
    "cca1558a0c0af0fa5ba669e53e020b98da95d45499470d4c9406df1bba577aba"
)
_COMPETITION_AUTHORITY_SHA256: Final = (
    "61c9477221c08f4f36269c8c3050171e0ec472508a0a8ac72ddc6f42d865ef98"
)
_COMPETITION_PAYLOAD_SHA256: Final = (
    "1e79989c9d75d671520d868dfa4e63bc828ceb7844c64b28e7325dd11a6ce7e0"
)
_OCCURRENCE_AUTHORITY_SHA256: Final = (
    "4ef38c7ee185ff10fea4b4de611648af1b30be04f700399549233e809cd53935"
)
_APPLICABILITY_AUTHORITY_SHA256: Final = (
    "867d64282d6da37b9289c191ec5396e34c2c2ca335ebc94d09329ad89619528f"
)
_APPLICABILITY_PAYLOAD_SHA256: Final = (
    "c1b808dc593d5aa9aea90b02285c2cfb37dc60e60ecd988dcf944d4984a9907a"
)
_IMPLICIT_AUTHORITY_SHA256: Final = (
    "fe7fd7581532754b322155ad0a74fcbd4068e1ebc83fbd841fd3736e27616d97"
)
_IMPLICIT_PAYLOAD_SHA256: Final = "9fddfad2276884b5d49dc71fca052d7285f73e046d5157427b7fb7b2fcd35ec1"
_VERIFIER_ID: Final = "nbadb_independent_competition_identity_v2"
_TASK_ID: Final = "A1.3a-repair-11"
_REPAIR_10_TASK_ID: Final = "A1.3a-repair-10"
_REPAIR_9_TASK_ID: Final = "A1.3a-repair-9"
_REPAIR_8_TASK_ID: Final = "A1.3a-repair-8"
_REPAIR_7_TASK_ID: Final = "A1.3a-repair-7"
_REPAIR_6_TASK_ID: Final = "A1.3a-repair-6"
_REPAIR_5_TASK_ID: Final = "A1.3a-repair-5"
_REPAIR_4_TASK_ID: Final = "A1.3a-repair-4"
_REPAIR_3_TASK_ID: Final = "A1.3a-repair-3"
_REPAIR_2_TASK_ID: Final = "A1.3a-repair-2"
_REPAIR_1_TASK_ID: Final = "A1.3a-repair-1"
_IDENTITY_CONTRACT_TASK_ID: Final = "A1.2e"
_ORIGINAL_TASK_ID: Final = "A1.3a"
_SCHEMA_VERSION: Final = 2
_KIND: Final = "nbadb_nba_api_competition_identity_authority"
_COMPETITION_DOMAIN: Final = "nbadb.nba-api.competition-scope.v1"
_CONCRETE_PATH_TYPE: Final = type(Path())
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)
_EXPECTED_REQUIREMENT_COUNT: Final = 815
_EXPECTED_EXECUTABLE_COUNT: Final = 799
_EXPECTED_SURFACE_COUNT: Final = 8
_EXPECTED_IMMUTABLE_INPUT_COUNT: Final = 127
_EXPECTED_MUTABLE_INPUT_COUNT: Final = 8
_EXPECTED_SOURCE_INPUT_COUNT: Final = 25

_REQUIREMENT_KEYS: Final = (
    "requirement_id",
    "source_family",
    "physical_endpoint_key",
    "provider_endpoint_id",
    "repo_endpoint_name",
    "league_id",
    "symbol",
    "competition_scope_sha256",
    "role_binding",
    "executable",
    "provider_availability_status",
    "request_terminal_state",
    "requirement_sha256",
)
_ROLE_KEYS: Final = (
    "binding_strategy",
    "source_authority_kind",
    "source_authority_sha256",
    "source_cell_id",
    "source_cell_sha256",
    "constructor_name",
    "provider_occurrence_id",
    "wire_name",
    "temporal_companion_occurrence_ids",
    "participant_axis_binding",
    "root_binding_sha256",
    "root_kind",
    "root_mode",
    "root_state",
    "static_chain_sha256",
    "role_binding_sha256",
)
_SURFACE_KEYS: Final = frozenset(
    {
        "competition_qualified",
        "domain_separator",
        "identity_field_types",
        "identity_fields",
        "legacy_unqualified_input_permitted",
        "parent_surface",
        "surface_contract_sha256",
        "surface_name",
    }
)
_TOP_LEVEL_KEYS: Final = frozenset(
    {
        "schema_version",
        "kind",
        "task_id",
        "source_authorities",
        "collision_census",
        "domain_separators",
        "identity_requirements",
        "identity_requirements_sha256",
        "qualified_surface_contracts",
        "qualified_surface_contracts_sha256",
        "denominator_counts",
        "binding_strategy_counts",
        "provider_request_policy",
        "provider_availability_values",
        "false_green_counters",
        "collision_invariants",
        "independent_proof",
        "authority_sha256",
        "payload_sha256",
    }
)
_PROOF_FIELDS: Final = (
    "verifier_id",
    "task_packet_sha256",
    "immutable_inputs_sha256",
    "source_inventory_inputs_sha256",
    "terminal_policy_sha256",
    "request_surface_sha256",
    "competition_applicability_authority_sha256",
    "implicit_competition_authority_sha256",
    "implicit_supersession_proof_sha256",
    "candidate_authority_sha256",
    "candidate_payload_sha256",
    "identity_requirements_sha256",
    "qualified_surface_contracts_sha256",
    "identity_requirement_count",
    "qualified_surface_contract_count",
    "finding_count",
    "findings",
    "proof_sha256",
)
_PROOF_DIGEST_FIELDS: Final = (
    "task_packet_sha256",
    "immutable_inputs_sha256",
    "source_inventory_inputs_sha256",
    "terminal_policy_sha256",
    "request_surface_sha256",
    "competition_applicability_authority_sha256",
    "implicit_competition_authority_sha256",
    "implicit_supersession_proof_sha256",
    "candidate_authority_sha256",
    "candidate_payload_sha256",
    "identity_requirements_sha256",
    "qualified_surface_contracts_sha256",
    "proof_sha256",
)
_PROOF_COUNT_FIELDS: Final = (
    "identity_requirement_count",
    "qualified_surface_contract_count",
    "finding_count",
)


class _CompetitionIdentityVerificationError(ValueError):
    """The independent competition-identity proof failed closed."""


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
        raise _CompetitionIdentityVerificationError(
            "competition identity value is not canonical JSON"
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
        raise _CompetitionIdentityVerificationError(
            "competition identity value is not canonical JSON"
        ) from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_digest(value: object, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise _CompetitionIdentityVerificationError(f"{label} must be an exact canonical SHA-256")
    return value


def _require_string(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise _CompetitionIdentityVerificationError(f"{label} must be an exact nonempty str")
    return value


def _require_exact_int(value: object, expected: int, label: str) -> int:
    if type(value) is not int or value != expected:
        raise _CompetitionIdentityVerificationError(f"{label} is not exact")
    return value


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _CompetitionIdentityVerificationError(
                f"competition identity input contains duplicate object key: {key}"
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise _CompetitionIdentityVerificationError(
        f"competition identity input contains non-finite constant: {value}"
    )


def _parse_object(
    raw: bytes,
    *,
    label: str,
    canonical_format: str | None,
) -> dict[str, object]:
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except _CompetitionIdentityVerificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _CompetitionIdentityVerificationError(f"{label} cannot be decoded") from exc
    if type(value) is not dict:
        raise _CompetitionIdentityVerificationError(f"{label} is not canonical JSON")
    if canonical_format == "pretty":
        expected = _pretty_bytes(value)
    elif canonical_format == "minified":
        expected = _canonical_bytes(value) + b"\n"
    elif canonical_format is None:
        expected = raw
    else:
        raise _CompetitionIdentityVerificationError("internal canonical format is invalid")
    if raw != expected:
        raise _CompetitionIdentityVerificationError(f"{label} is not canonical JSON")
    return cast("dict[str, object]", value)


def _dict(value: object, label: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise _CompetitionIdentityVerificationError(f"{label} must be an exact object")
    return cast("dict[str, object]", value)


def _list(value: object, label: str) -> list[object]:
    if type(value) is not list:
        raise _CompetitionIdentityVerificationError(f"{label} must be an exact array")
    return cast("list[object]", value)


def _rows(value: object, label: str) -> list[dict[str, object]]:
    values = _list(value, label)
    if any(type(item) is not dict for item in values):
        raise _CompetitionIdentityVerificationError(f"{label} must contain exact objects")
    return cast("list[dict[str, object]]", values)


def _require_keys(
    value: dict[str, object], expected: set[str] | frozenset[str], label: str
) -> None:
    if set(value) != expected:
        raise _CompetitionIdentityVerificationError(f"{label} has missing or foreign fields")


def _exact_equal(left: object, right: object) -> bool:
    """Compare JSON values without Python's bool/int coercive equality."""

    if type(left) is not type(right):
        return False
    if type(left) is dict:
        left_dict = cast("dict[str, object]", left)
        right_dict = cast("dict[str, object]", right)
        return set(left_dict) == set(right_dict) and all(
            _exact_equal(left_dict[key], right_dict[key]) for key in left_dict
        )
    if type(left) is list:
        left_list = cast("list[object]", left)
        right_list = cast("list[object]", right)
        return len(left_list) == len(right_list) and all(
            _exact_equal(a, b) for a, b in zip(left_list, right_list, strict=True)
        )
    return bool(left == right)


def _read_packaged_task_packet(relative: str) -> bytes:
    packaged_name = relative.rsplit("/", 1)[-1]
    if relative not in {
        _TASK_PACKET_REL,
        _REPAIR_10_TASK_PACKET_REL,
        _REPAIR_9_TASK_PACKET_REL,
        _REPAIR_8_TASK_PACKET_REL,
        _REPAIR_7_TASK_PACKET_REL,
        _REPAIR_6_TASK_PACKET_REL,
        _REPAIR_5_TASK_PACKET_REL,
        _REPAIR_4_TASK_PACKET_REL,
        _REPAIR_3_TASK_PACKET_REL,
        _REPAIR_2_TASK_PACKET_REL,
        _REPAIR_1_TASK_PACKET_REL,
        _ORIGINAL_TASK_PACKET_REL,
        _IDENTITY_CONTRACT_REL,
    }:
        raise _CompetitionIdentityVerificationError(
            "authenticated task packet has no packaged authority"
        )
    try:
        return (
            resources.files("nbadb.contracts")
            .joinpath(*_PACKAGED_TASK_PACKET_ROOT, packaged_name)
            .read_bytes()
        )
    except (AttributeError, OSError) as exc:
        raise _CompetitionIdentityVerificationError(
            f"authenticated task packet cannot be read: {relative}"
        ) from exc


def _read_packaged_contract_resource(relative: str) -> bytes:
    prefix = "src/nbadb/contracts/"
    if not relative.startswith(prefix) or "/" in relative.removeprefix(prefix):
        raise _CompetitionIdentityVerificationError(
            "authenticated contract resource path is invalid"
        )
    try:
        return (
            resources.files("nbadb.contracts").joinpath(relative.removeprefix(prefix)).read_bytes()
        )
    except (AttributeError, OSError) as exc:
        raise _CompetitionIdentityVerificationError(
            f"authenticated contract resource cannot be read: {relative}"
        ) from exc


def _declared_input_rows(
    packet: dict[str, object],
    *,
    field: str,
    digest_field: str,
    expected_count: int,
) -> tuple[list[dict[str, object]], dict[str, str]]:
    rows = _rows(packet.get(field), field)
    _require_exact_int(len(rows), expected_count, f"{field} count")
    expected_digest = _require_digest(packet.get(digest_field), digest_field)
    if _digest(rows) != expected_digest:
        raise _CompetitionIdentityVerificationError(f"{field} digest is invalid")
    result: dict[str, str] = {}
    for row in rows:
        _require_keys(row, {"path", "sha256"}, f"{field} row")
        relative = _require_string(row.get("path"), f"{field} path")
        supplied = _require_digest(row.get("sha256"), f"{field} SHA-256")
        if relative in result:
            raise _CompetitionIdentityVerificationError(f"{field} contains a duplicate path")
        result[relative] = supplied
    return rows, result


def _load_fixed_packet(
    relative: str,
    expected_sha256: str,
    expected_task_id: str,
    *,
    label: str,
) -> tuple[dict[str, object], bytes]:
    raw = _read_packaged_task_packet(relative)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise _CompetitionIdentityVerificationError(f"{label} hash drifted")
    packet = _parse_object(raw, label=label, canonical_format=None)
    if packet.get("schema") != "TaskPacketV1" or packet.get("task_id") != expected_task_id:
        raise _CompetitionIdentityVerificationError(f"{label} identity is invalid")
    return packet, raw


def _authenticate_packet_chain() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, str],
    dict[str, str],
]:
    packet, packet_raw = _load_fixed_packet(
        _TASK_PACKET_REL,
        _TASK_PACKET_SHA256,
        _TASK_ID,
        label="competition identity repair-11 task packet",
    )
    immutable_rows, immutable = _declared_input_rows(
        packet,
        field="immutable_inputs",
        digest_field="immutable_inputs_sha256",
        expected_count=_EXPECTED_IMMUTABLE_INPUT_COUNT,
    )
    _mutable_rows, mutable = _declared_input_rows(
        packet,
        field="mutable_opening_inputs",
        digest_field="mutable_opening_inputs_sha256",
        expected_count=_EXPECTED_MUTABLE_INPUT_COUNT,
    )
    if (
        packet.get("immutable_inputs_sha256") != _IMMUTABLE_INPUTS_SHA256
        or packet.get("mutable_opening_inputs_sha256") != _MUTABLE_OPENING_INPUTS_SHA256
    ):
        raise _CompetitionIdentityVerificationError(
            "repair-11 packet input inventory authority drifted"
        )

    original_row = {"path": _ORIGINAL_TASK_PACKET_REL, "sha256": _ORIGINAL_TASK_PACKET_SHA256}
    repair_1_row = {
        "path": _REPAIR_1_TASK_PACKET_REL,
        "sha256": _REPAIR_1_TASK_PACKET_SHA256,
    }
    repair_2_row = {
        "path": _REPAIR_2_TASK_PACKET_REL,
        "sha256": _REPAIR_2_TASK_PACKET_SHA256,
    }
    repair_3_row = {
        "path": _REPAIR_3_TASK_PACKET_REL,
        "sha256": _REPAIR_3_TASK_PACKET_SHA256,
    }
    repair_4_row = {
        "path": _REPAIR_4_TASK_PACKET_REL,
        "sha256": _REPAIR_4_TASK_PACKET_SHA256,
    }
    repair_5_row = {
        "path": _REPAIR_5_TASK_PACKET_REL,
        "sha256": _REPAIR_5_TASK_PACKET_SHA256,
    }
    repair_6_row = {
        "path": _REPAIR_6_TASK_PACKET_REL,
        "sha256": _REPAIR_6_TASK_PACKET_SHA256,
    }
    repair_7_row = {
        "path": _REPAIR_7_TASK_PACKET_REL,
        "sha256": _REPAIR_7_TASK_PACKET_SHA256,
    }
    repair_8_row = {
        "path": _REPAIR_8_TASK_PACKET_REL,
        "sha256": _REPAIR_8_TASK_PACKET_SHA256,
    }
    repair_9_row = {
        "path": _REPAIR_9_TASK_PACKET_REL,
        "sha256": _REPAIR_9_TASK_PACKET_SHA256,
    }
    repair_10_row = {
        "path": _REPAIR_10_TASK_PACKET_REL,
        "sha256": _REPAIR_10_TASK_PACKET_SHA256,
    }
    if (
        not _exact_equal(immutable_rows[96], original_row)
        or not _exact_equal(immutable_rows[97], repair_1_row)
        or not _exact_equal(immutable_rows[98], repair_2_row)
        or not _exact_equal(immutable_rows[99], repair_3_row)
        or not _exact_equal(immutable_rows[100], repair_4_row)
        or not _exact_equal(immutable_rows[101], repair_5_row)
        or not _exact_equal(immutable_rows[102], repair_6_row)
        or not _exact_equal(immutable_rows[103], repair_7_row)
        or not _exact_equal(immutable_rows[104], repair_8_row)
        or not _exact_equal(immutable_rows[105], repair_9_row)
        or not _exact_equal(immutable_rows[106], repair_10_row)
    ):
        raise _CompetitionIdentityVerificationError(
            "repair-11 packet immutable supersession rows are invalid"
        )
    if immutable.get(_IDENTITY_CONTRACT_REL) != _IDENTITY_CONTRACT_SHA256:
        raise _CompetitionIdentityVerificationError(
            "repair-11 packet does not bind the semantic identity contract"
        )

    repair_10, repair_10_raw = _load_fixed_packet(
        _REPAIR_10_TASK_PACKET_REL,
        _REPAIR_10_TASK_PACKET_SHA256,
        _REPAIR_10_TASK_ID,
        label="competition identity repair-10 task packet",
    )
    repair_9, repair_9_raw = _load_fixed_packet(
        _REPAIR_9_TASK_PACKET_REL,
        _REPAIR_9_TASK_PACKET_SHA256,
        _REPAIR_9_TASK_ID,
        label="competition identity repair-9 task packet",
    )
    repair_8, repair_8_raw = _load_fixed_packet(
        _REPAIR_8_TASK_PACKET_REL,
        _REPAIR_8_TASK_PACKET_SHA256,
        _REPAIR_8_TASK_ID,
        label="competition identity repair-8 task packet",
    )
    repair_7, repair_7_raw = _load_fixed_packet(
        _REPAIR_7_TASK_PACKET_REL,
        _REPAIR_7_TASK_PACKET_SHA256,
        _REPAIR_7_TASK_ID,
        label="competition identity repair-7 task packet",
    )
    repair_6, repair_6_raw = _load_fixed_packet(
        _REPAIR_6_TASK_PACKET_REL,
        _REPAIR_6_TASK_PACKET_SHA256,
        _REPAIR_6_TASK_ID,
        label="competition identity repair-6 task packet",
    )
    repair_5, repair_5_raw = _load_fixed_packet(
        _REPAIR_5_TASK_PACKET_REL,
        _REPAIR_5_TASK_PACKET_SHA256,
        _REPAIR_5_TASK_ID,
        label="competition identity repair-5 task packet",
    )
    repair_4, repair_4_raw = _load_fixed_packet(
        _REPAIR_4_TASK_PACKET_REL,
        _REPAIR_4_TASK_PACKET_SHA256,
        _REPAIR_4_TASK_ID,
        label="competition identity repair-4 task packet",
    )
    repair_3, repair_3_raw = _load_fixed_packet(
        _REPAIR_3_TASK_PACKET_REL,
        _REPAIR_3_TASK_PACKET_SHA256,
        _REPAIR_3_TASK_ID,
        label="competition identity repair-3 task packet",
    )
    repair_2, repair_2_raw = _load_fixed_packet(
        _REPAIR_2_TASK_PACKET_REL,
        _REPAIR_2_TASK_PACKET_SHA256,
        _REPAIR_2_TASK_ID,
        label="competition identity repair-2 task packet",
    )
    repair_1, repair_1_raw = _load_fixed_packet(
        _REPAIR_1_TASK_PACKET_REL,
        _REPAIR_1_TASK_PACKET_SHA256,
        _REPAIR_1_TASK_ID,
        label="competition identity repair-1 task packet",
    )
    _original, original_raw = _load_fixed_packet(
        _ORIGINAL_TASK_PACKET_REL,
        _ORIGINAL_TASK_PACKET_SHA256,
        _ORIGINAL_TASK_ID,
        label="original competition identity task packet",
    )
    packet_byte_identities = (
        (packet_raw, 434834, 8478, "repair-11"),
        (repair_10_raw, 407143, 7989, "repair-10"),
        (repair_9_raw, 385867, 7634, "repair-9"),
        (repair_8_raw, 362821, 7138, "repair-8"),
        (repair_7_raw, 340405, 6755, "repair-7"),
        (repair_6_raw, 318301, 6370, "repair-6"),
        (repair_5_raw, 244906, 4847, "repair-5"),
        (repair_4_raw, 195745, 3766, "repair-4"),
        (repair_3_raw, 168029, 3187, "repair-3"),
        (repair_2_raw, 150660, 2537, "repair-2"),
        (repair_1_raw, 131669, 2305, "repair-1"),
        (original_raw, 97245, 2030, "original"),
    )
    for raw, expected_size, expected_lf, label in packet_byte_identities:
        _require_exact_int(len(raw), expected_size, f"{label} task packet size")
        _require_exact_int(raw.count(b"\n"), expected_lf, f"{label} task packet LF count")

    expected_repair_10 = {
        "line_count": 7989,
        "path": _REPAIR_10_TASK_PACKET_REL,
        "sha256": _REPAIR_10_TASK_PACKET_SHA256,
        "size": 407143,
    }
    expected_repair_9 = {
        "line_count": 7634,
        "path": _REPAIR_9_TASK_PACKET_REL,
        "sha256": _REPAIR_9_TASK_PACKET_SHA256,
        "size": 385867,
    }
    expected_repair_8 = {
        "line_count": 7138,
        "path": _REPAIR_8_TASK_PACKET_REL,
        "sha256": _REPAIR_8_TASK_PACKET_SHA256,
        "size": 362821,
    }
    expected_repair_7 = {
        "line_count": 6755,
        "path": _REPAIR_7_TASK_PACKET_REL,
        "sha256": _REPAIR_7_TASK_PACKET_SHA256,
        "size": 340405,
    }
    expected_repair_6 = {
        "line_count": 6370,
        "path": _REPAIR_6_TASK_PACKET_REL,
        "sha256": _REPAIR_6_TASK_PACKET_SHA256,
        "size": 318301,
    }
    expected_repair_5 = {
        "line_count": 4847,
        "path": _REPAIR_5_TASK_PACKET_REL,
        "sha256": _REPAIR_5_TASK_PACKET_SHA256,
        "size": 244906,
    }
    expected_repair_4 = {
        "line_count": 3766,
        "path": _REPAIR_4_TASK_PACKET_REL,
        "sha256": _REPAIR_4_TASK_PACKET_SHA256,
        "size": 195745,
    }
    expected_repair_3 = {
        "line_count": 3187,
        "path": _REPAIR_3_TASK_PACKET_REL,
        "sha256": _REPAIR_3_TASK_PACKET_SHA256,
        "size": 168029,
    }
    expected_repair_2 = {
        "line_count": 2537,
        "path": _REPAIR_2_TASK_PACKET_REL,
        "sha256": _REPAIR_2_TASK_PACKET_SHA256,
        "size": 150660,
    }
    expected_repair_1 = {
        "line_count": 2305,
        "path": _REPAIR_1_TASK_PACKET_REL,
        "sha256": _REPAIR_1_TASK_PACKET_SHA256,
        "size": 131669,
    }
    expected_original = {
        "line_count": 2030,
        "path": _ORIGINAL_TASK_PACKET_REL,
        "sha256": _ORIGINAL_TASK_PACKET_SHA256,
        "size": 97245,
    }
    chain = (
        (packet, repair_10, expected_repair_10, "repair-10"),
        (repair_10, repair_9, expected_repair_9, "repair-9"),
        (repair_9, repair_8, expected_repair_8, "repair-8"),
        (repair_8, repair_7, expected_repair_7, "repair-7"),
        (repair_7, repair_6, expected_repair_6, "repair-6"),
        (repair_6, repair_5, expected_repair_5, "repair-5"),
        (repair_5, repair_4, expected_repair_4, "repair-4"),
        (repair_4, repair_3, expected_repair_3, "repair-3"),
        (repair_3, repair_2, expected_repair_2, "repair-2"),
        (repair_2, repair_1, expected_repair_1, "repair-1"),
    )
    for current, prior, expected_reference, label in chain:
        superseded = _dict(current.get("superseded_packet"), f"{label} supersession")
        direct_reference = _dict(
            superseded.get("packet"), f"{label} direct superseded packet reference"
        )
        prior_supersession = _dict(
            superseded.get("prior_supersession"), f"{label} prior supersession"
        )
        if not _exact_equal(direct_reference, expected_reference):
            raise _CompetitionIdentityVerificationError(
                f"supersession does not bind the {label} task packet"
            )
        if not _exact_equal(
            prior_supersession,
            _dict(prior.get("superseded_packet"), f"{label} sealed authority"),
        ):
            raise _CompetitionIdentityVerificationError(
                f"prior supersession does not reproduce {label} authority"
            )
    repair_1_superseded = _dict(repair_1.get("superseded_packet"), "repair-1 supersession contract")
    if not _exact_equal(
        _dict(repair_1_superseded.get("packet"), "repair-1 original reference"),
        expected_original,
    ):
        raise _CompetitionIdentityVerificationError(
            "repair-1 supersession does not bind the original task packet"
        )
    successor = _dict(packet.get("one_successor_design"), "successor dispatch contract")
    if (
        successor.get("current_dispatch_authority_after_R0") != _TASK_PACKET_REL
        or successor.get("original_packet_disposition")
        != (
            "repair-10 is the direct immutable superseded authority; repair-9 through "
            "repair-1 and original A1.3a remain nested immutable historical provenance only"
        )
        or successor.get("original_receipt_or_review_creation_permitted") is not False
    ):
        raise _CompetitionIdentityVerificationError(
            "repair-11 packet successor dispatch authority drifted"
        )

    identity_contract, _identity_raw = _load_fixed_packet(
        _IDENTITY_CONTRACT_REL,
        _IDENTITY_CONTRACT_SHA256,
        _IDENTITY_CONTRACT_TASK_ID,
        label="semantic competition identity contract",
    )
    _source_rows, _source_inventory = _declared_input_rows(
        identity_contract,
        field="source_inventory_inputs",
        digest_field="source_inventory_inputs_sha256",
        expected_count=_EXPECTED_SOURCE_INPUT_COUNT,
    )
    if identity_contract.get("source_inventory_inputs_sha256") != _SOURCE_INVENTORY_INPUTS_SHA256:
        raise _CompetitionIdentityVerificationError("semantic source inventory authority drifted")

    immutable_requirements = {
        _TERMINAL_RESOURCE: _TERMINAL_RESOURCE_SHA256,
        _REQUEST_RESOURCE: _HISTORICAL_TASK_PACKET_REQUEST_RESOURCE_SHA256,
        _COMPETITION_RESOURCE: _COMPETITION_RESOURCE_SHA256,
        _IMPLICIT_RESOURCE: _IMPLICIT_RESOURCE_SHA256,
        _APPLICABILITY_RESOURCE: _HISTORICAL_TASK_PACKET_APPLICABILITY_RESOURCE_SHA256,
    }
    if any(immutable.get(path) != digest for path, digest in immutable_requirements.items()):
        raise _CompetitionIdentityVerificationError(
            "repair-11 packet current immutable resource bindings drifted"
        )
    candidate_relative = f"src/nbadb/contracts/{_RESOURCE}"
    if candidate_relative not in mutable:
        raise _CompetitionIdentityVerificationError(
            "repair-11 packet does not lease the competition identity candidate"
        )
    return packet, identity_contract, immutable, mutable


def _verify_payload_digest(payload: dict[str, object], label: str) -> None:
    body = dict(payload)
    supplied = body.pop("payload_sha256", None)
    if _require_digest(supplied, f"{label} payload_sha256") != _digest(body):
        raise _CompetitionIdentityVerificationError(f"{label} payload digest is invalid")


def _authenticated_json(
    relative: str,
    *,
    expected_sha256: str,
    label: str,
) -> dict[str, object]:
    raw = _read_packaged_contract_resource(relative)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise _CompetitionIdentityVerificationError(f"{label} hash drifted")
    payload = _parse_object(raw, label=label, canonical_format=None)
    _verify_payload_digest(payload, label)
    return payload


def _require_resource_values(
    payload: dict[str, object],
    expected: dict[str, object],
    *,
    label: str,
) -> None:
    if any(not _exact_equal(payload.get(name), value) for name, value in expected.items()):
        raise _CompetitionIdentityVerificationError(f"{label} semantic identity drifted")


def _authenticate_current_resources() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    terminal = _authenticated_json(
        _TERMINAL_RESOURCE,
        expected_sha256=_TERMINAL_RESOURCE_SHA256,
        label="terminal-state checked resource",
    )
    request = _authenticated_json(
        _REQUEST_RESOURCE,
        expected_sha256=_REQUEST_RESOURCE_SHA256,
        label="request-surface checked resource",
    )
    competition = _authenticated_json(
        _COMPETITION_RESOURCE,
        expected_sha256=_COMPETITION_RESOURCE_SHA256,
        label="competition checked resource",
    )
    applicability = _authenticated_json(
        _APPLICABILITY_RESOURCE,
        expected_sha256=_APPLICABILITY_RESOURCE_SHA256,
        label="competition-applicability checked resource",
    )
    implicit = _authenticated_json(
        _IMPLICIT_RESOURCE,
        expected_sha256=_IMPLICIT_RESOURCE_SHA256,
        label="implicit-competition checked resource",
    )

    _require_resource_values(
        terminal,
        {
            "schema_version": 1,
            "kind": "nbadb_nba_api_terminal_state_authority",
            "task_id": _ORIGINAL_TASK_ID,
            "terminal_policy_sha256": _TERMINAL_POLICY_SHA256,
            "payload_sha256": _TERMINAL_PAYLOAD_SHA256,
        },
        label="terminal-state resource",
    )
    _require_resource_values(
        request,
        {
            "schema_version": 3,
            "kind": "nbadb_pinned_nba_api_request_surface",
            "derivation_policy_version": 6,
            "derivation_policy_sha256": _REQUEST_DERIVATION_POLICY_SHA256,
            "runtime_contract_payload_sha256": _REQUEST_RUNTIME_PAYLOAD_SHA256,
            "surface_sha256": _REQUEST_SURFACE_SHA256,
            "terminal_policy_sha256": _TERMINAL_POLICY_SHA256,
            "payload_sha256": _REQUEST_PAYLOAD_SHA256,
        },
        label="request-surface resource",
    )
    _require_resource_values(
        competition,
        {
            "schema_version": 1,
            "kind": "nbadb_nba_api_competition_authority",
            "authority_sha256": _COMPETITION_AUTHORITY_SHA256,
            "payload_sha256": _COMPETITION_PAYLOAD_SHA256,
        },
        label="competition resource",
    )
    _require_resource_values(
        applicability,
        {
            "schema_version": 1,
            "kind": "nbadb_nba_api_competition_applicability_authority",
            "authority_sha256": _APPLICABILITY_AUTHORITY_SHA256,
            "payload_sha256": _APPLICABILITY_PAYLOAD_SHA256,
        },
        label="competition-applicability resource",
    )
    _require_resource_values(
        implicit,
        {
            "schema_version": 1,
            "kind": "nbadb_nba_api_implicit_competition_authority",
            "task_id": "A1.2d",
            "authority_sha256": _IMPLICIT_AUTHORITY_SHA256,
            "payload_sha256": _IMPLICIT_PAYLOAD_SHA256,
        },
        label="implicit-competition resource",
    )
    applicability_sources = _dict(
        applicability.get("source_authorities"),
        "competition-applicability source authorities",
    )
    if (
        _dict(applicability_sources.get("competition_values"), "competition values source").get(
            "authority_sha256"
        )
        != _COMPETITION_AUTHORITY_SHA256
        or _dict(
            applicability_sources.get("competition_occurrences"),
            "competition occurrences source",
        ).get("authority_sha256")
        != _OCCURRENCE_AUTHORITY_SHA256
        or _dict(applicability_sources.get("request_surface"), "request surface source").get(
            "surface_sha256"
        )
        != _REQUEST_SURFACE_SHA256
    ):
        raise _CompetitionIdentityVerificationError(
            "competition-applicability predecessor bindings drifted"
        )
    return terminal, request, competition, applicability, implicit


def _competition_scope(
    competition_authority_sha256: str,
    league_id: str,
    symbol: str,
) -> str:
    return _digest(
        {
            "domain_separator": _COMPETITION_DOMAIN,
            "competition_authority_sha256": competition_authority_sha256,
            "league_id": league_id,
            "symbol": symbol,
        }
    )


def _sealed_role(body: dict[str, object]) -> dict[str, object]:
    if tuple(body) != _ROLE_KEYS[:-1]:
        raise _CompetitionIdentityVerificationError("derived role field order is invalid")
    return {**body, "role_binding_sha256": _digest(body)}


def _sealed_requirement(body: dict[str, object]) -> dict[str, object]:
    if tuple(body) != _REQUIREMENT_KEYS[:-1]:
        raise _CompetitionIdentityVerificationError("derived requirement field order is invalid")
    return {
        **body,
        "requirement_sha256": _digest(
            {"domain_separator": _COMPETITION_DOMAIN, "requirement": body}
        ),
    }


def _competition_values(competition: dict[str, object]) -> tuple[str, dict[str, str]]:
    authority = _require_digest(
        competition.get("authority_sha256"), "competition authority SHA-256"
    )
    rows = _rows(competition.get("competitions"), "competition values")
    values: dict[str, str] = {}
    for row in rows:
        _require_keys(row, {"league_id", "symbol"}, "competition value")
        league_id = _require_string(row.get("league_id"), "league_id")
        symbol = _require_string(row.get("symbol"), "competition symbol")
        if league_id in values:
            raise _CompetitionIdentityVerificationError("competition values contain duplicates")
        values[league_id] = symbol
    if tuple(values.items()) != (
        ("00", "nba"),
        ("01", "aba"),
        ("10", "wnba"),
        ("15", "summer_league"),
        ("20", "g_league"),
    ):
        raise _CompetitionIdentityVerificationError("competition values drifted")
    return authority, values


def _request_endpoint_sources(request: dict[str, object]) -> dict[str, list[str]]:
    manifest = _dict(request.get("manifest"), "request manifest")
    rows = _rows(manifest.get("endpoint_contracts"), "request endpoint contracts")
    result: dict[str, list[str]] = {}
    for row in rows:
        endpoint_id = _require_string(row.get("endpoint_id"), "request endpoint ID")
        source_family = _require_string(row.get("source_family"), "request source family")
        result.setdefault(endpoint_id, []).append(source_family)
    return result


def _explicit_requirements(
    applicability: dict[str, object],
    endpoint_sources: dict[str, list[str]],
    competition_authority: str,
    competitions: dict[str, str],
) -> list[dict[str, object]]:
    source_authority = _require_digest(
        applicability.get("authority_sha256"), "applicability authority SHA-256"
    )
    rows = _rows(
        applicability.get("alias_role_competition_cells"),
        "applicability alias-role cells",
    )
    if len(rows) != 635 or _digest(rows) != applicability.get(
        "alias_role_competition_cells_sha256"
    ):
        raise _CompetitionIdentityVerificationError("applicability alias-role cells drifted")
    output: list[dict[str, object]] = []
    for cell in rows:
        provider_endpoint_id = _require_string(
            cell.get("provider_endpoint_id"), "explicit provider endpoint"
        )
        repo_endpoint_name = _require_string(
            cell.get("repo_endpoint_name"), "explicit repository endpoint"
        )
        league_id = _require_string(cell.get("league_id"), "explicit league ID")
        symbol = _require_string(cell.get("symbol"), "explicit competition symbol")
        if competitions.get(league_id) != symbol:
            raise _CompetitionIdentityVerificationError(
                "explicit cell competition differs from the competition authority"
            )
        source_families = endpoint_sources.get(provider_endpoint_id)
        if source_families != ["stats"]:
            raise _CompetitionIdentityVerificationError(
                "explicit provider endpoint lacks one exact stats join"
            )
        source_family = "stats"
        occurrence_id = _require_string(
            cell.get("provider_occurrence_id"), "explicit provider occurrence"
        )
        companions = _list(
            cell.get("temporal_companion_occurrence_ids"),
            "explicit temporal companion occurrences",
        )
        if any(type(item) is not str or not item for item in companions):
            raise _CompetitionIdentityVerificationError(
                "explicit temporal companion occurrence is invalid"
            )
        source_cell_id = f"alias-role:{repo_endpoint_name}:{occurrence_id}:{league_id}"
        role = _sealed_role(
            {
                "binding_strategy": "explicit_applicability_cell",
                "source_authority_kind": "competition_applicability",
                "source_authority_sha256": source_authority,
                "source_cell_id": source_cell_id,
                "source_cell_sha256": _digest(cell),
                "constructor_name": cell.get("constructor_name"),
                "provider_occurrence_id": occurrence_id,
                "wire_name": cell.get("wire_name"),
                "temporal_companion_occurrence_ids": deepcopy(companions),
                "participant_axis_binding": cell.get("participant_axis_binding"),
                "root_binding_sha256": None,
                "root_kind": None,
                "root_mode": None,
                "root_state": None,
                "static_chain_sha256": None,
            }
        )
        requirement_id = (
            f"competition-requirement:{source_family}:{repo_endpoint_name}:"
            f"{source_cell_id}:{league_id}"
        )
        output.append(
            _sealed_requirement(
                {
                    "requirement_id": requirement_id,
                    "source_family": source_family,
                    "physical_endpoint_key": f"{source_family}:{provider_endpoint_id}",
                    "provider_endpoint_id": provider_endpoint_id,
                    "repo_endpoint_name": repo_endpoint_name,
                    "league_id": league_id,
                    "symbol": symbol,
                    "competition_scope_sha256": _competition_scope(
                        competition_authority, league_id, symbol
                    ),
                    "role_binding": role,
                    "executable": True,
                    "provider_availability_status": "unknown",
                    "request_terminal_state": "not_asserted",
                }
            )
        )
    return output


def _implicit_requirements(
    implicit: dict[str, object],
    competition_authority: str,
    competitions: dict[str, str],
) -> list[dict[str, object]]:
    source_authority = _require_digest(
        implicit.get("authority_sha256"), "implicit authority SHA-256"
    )
    cells = _rows(implicit.get("alias_competition_cells"), "implicit alias cells")
    bindings = _rows(implicit.get("endpoint_bindings"), "implicit endpoint bindings")
    if len(cells) != 180 or _digest(cells) != implicit.get("alias_competition_cells_sha256"):
        raise _CompetitionIdentityVerificationError("implicit alias cells drifted")
    if len(bindings) != 36 or _digest(bindings) != implicit.get("endpoint_bindings_sha256"):
        raise _CompetitionIdentityVerificationError("implicit endpoint bindings drifted")
    by_alias: dict[str, dict[str, object]] = {}
    for binding in bindings:
        alias = _require_string(binding.get("repo_endpoint_name"), "implicit binding alias")
        if alias in by_alias:
            raise _CompetitionIdentityVerificationError("implicit bindings contain aliases twice")
        by_alias[alias] = binding
    output: list[dict[str, object]] = []
    strategies = {
        "receipt_bound_root_required": "receipt_bound_dynamic_root",
        "fixed_static_root": "fixed_static_root",
        "root_not_exposed": "root_not_exposed",
    }
    for cell in cells:
        repo_endpoint_name = _require_string(
            cell.get("repo_endpoint_name"), "implicit repository endpoint"
        )
        binding = by_alias.get(repo_endpoint_name)
        if binding is None:
            raise _CompetitionIdentityVerificationError(
                "implicit cell lacks its exact endpoint binding"
            )
        for name in (
            "source_family",
            "physical_endpoint_key",
            "provider_endpoint_id",
            "root_kind",
        ):
            if cell.get(name) != binding.get(name):
                raise _CompetitionIdentityVerificationError(
                    "implicit cell differs from its endpoint binding"
                )
        root_binding = _require_digest(
            cell.get("root_binding_sha256"), "implicit root binding SHA-256"
        )
        if root_binding != binding.get("binding_sha256"):
            raise _CompetitionIdentityVerificationError("implicit cell root binding digest drifted")
        root_state = _require_string(cell.get("root_state"), "implicit root state")
        try:
            strategy = strategies[root_state]
        except KeyError as exc:
            raise _CompetitionIdentityVerificationError("implicit root state is foreign") from exc
        league_id = _require_string(cell.get("league_id"), "implicit league ID")
        symbol = _require_string(cell.get("symbol"), "implicit competition symbol")
        if competitions.get(league_id) != symbol:
            raise _CompetitionIdentityVerificationError(
                "implicit cell competition differs from the competition authority"
            )
        root_evidence = _dict(binding.get("root_evidence"), "implicit root evidence")
        static_chain: object = None
        if strategy in {"fixed_static_root", "root_not_exposed"}:
            static_chain = _require_digest(
                root_evidence.get("static_chain_sha256"), "implicit static-chain SHA-256"
            )
            fixed_league = _require_string(
                root_evidence.get("fixed_league_id"), "implicit fixed league ID"
            )
            fixed_symbol = _require_string(
                root_evidence.get("fixed_symbol"), "implicit fixed competition symbol"
            )
            if (strategy == "fixed_static_root") != (
                league_id == fixed_league and symbol == fixed_symbol
            ):
                raise _CompetitionIdentityVerificationError(
                    "implicit static cell has an invalid constructibility state"
                )
        source_cell_id = _require_string(cell.get("cell_id"), "implicit source cell ID")
        role = _sealed_role(
            {
                "binding_strategy": strategy,
                "source_authority_kind": "implicit_competition",
                "source_authority_sha256": source_authority,
                "source_cell_id": source_cell_id,
                "source_cell_sha256": _digest(cell),
                "constructor_name": None,
                "provider_occurrence_id": None,
                "wire_name": None,
                "temporal_companion_occurrence_ids": [],
                "participant_axis_binding": None,
                "root_binding_sha256": root_binding,
                "root_kind": cell.get("root_kind"),
                "root_mode": binding.get("root_mode"),
                "root_state": root_state,
                "static_chain_sha256": static_chain,
            }
        )
        source_family = _require_string(cell.get("source_family"), "implicit source family")
        physical_endpoint_key = _require_string(
            cell.get("physical_endpoint_key"), "implicit physical endpoint"
        )
        provider_endpoint_id = _require_string(
            cell.get("provider_endpoint_id"), "implicit provider endpoint"
        )
        requirement_id = (
            f"competition-requirement:{source_family}:{repo_endpoint_name}:"
            f"{source_cell_id}:{league_id}"
        )
        output.append(
            _sealed_requirement(
                {
                    "requirement_id": requirement_id,
                    "source_family": source_family,
                    "physical_endpoint_key": physical_endpoint_key,
                    "provider_endpoint_id": provider_endpoint_id,
                    "repo_endpoint_name": repo_endpoint_name,
                    "league_id": league_id,
                    "symbol": symbol,
                    "competition_scope_sha256": _competition_scope(
                        competition_authority, league_id, symbol
                    ),
                    "role_binding": role,
                    "executable": strategy != "root_not_exposed",
                    "provider_availability_status": "unknown",
                    "request_terminal_state": "not_asserted",
                }
            )
        )
    return output


def _derive_requirements(
    packet: dict[str, object],
    applicability: dict[str, object],
    implicit: dict[str, object],
    competition: dict[str, object],
    request: dict[str, object],
) -> list[dict[str, object]]:
    competition_authority, competitions = _competition_values(competition)
    requirement_contract = _dict(
        packet.get("identity_requirements_contract"), "identity requirement contract"
    )
    if competition_authority != requirement_contract.get("competition_authority_sha256"):
        raise _CompetitionIdentityVerificationError("competition authority binding drifted")
    requirements = [
        *_explicit_requirements(
            applicability,
            _request_endpoint_sources(request),
            competition_authority,
            competitions,
        ),
        *_implicit_requirements(implicit, competition_authority, competitions),
    ]
    requirements.sort(key=lambda row: cast("str", row["requirement_id"]))
    ids = [cast("str", row["requirement_id"]) for row in requirements]
    if len(requirements) != _EXPECTED_REQUIREMENT_COUNT or len(ids) != len(set(ids)):
        raise _CompetitionIdentityVerificationError("derived requirement inventory is invalid")
    for row in requirements:
        if tuple(row) != _REQUIREMENT_KEYS:
            raise _CompetitionIdentityVerificationError("derived requirement schema is invalid")
        role = _dict(row.get("role_binding"), "derived role binding")
        if tuple(role) != _ROLE_KEYS:
            raise _CompetitionIdentityVerificationError("derived role schema is invalid")
    executable_count = sum(row["executable"] is True for row in requirements)
    _require_exact_int(
        executable_count,
        _EXPECTED_EXECUTABLE_COUNT,
        "derived executable requirement count",
    )
    strategies = Counter(
        cast("str", _dict(row["role_binding"], "derived role")["binding_strategy"])
        for row in requirements
    )
    expected_strategies = _dict(packet.get("binding_strategy_counts"), "strategy counts")
    if not _exact_equal(dict(strategies), expected_strategies):
        raise _CompetitionIdentityVerificationError("derived binding strategy counts drifted")
    return requirements


def _validated_surfaces(packet: dict[str, object]) -> list[dict[str, object]]:
    surfaces = deepcopy(_rows(packet.get("qualified_surface_contracts"), "qualified surfaces"))
    if len(surfaces) != _EXPECTED_SURFACE_COUNT:
        raise _CompetitionIdentityVerificationError("qualified surface count drifted")
    names: list[str] = []
    for row in surfaces:
        _require_keys(row, _SURFACE_KEYS, "qualified surface")
        body = dict(row)
        supplied = body.pop("surface_contract_sha256", None)
        if _require_digest(supplied, "surface contract SHA-256") != _digest(body):
            raise _CompetitionIdentityVerificationError("qualified surface digest is invalid")
        names.append(_require_string(row.get("surface_name"), "qualified surface name"))
    if len(names) != len(set(names)):
        raise _CompetitionIdentityVerificationError("qualified surface names are duplicated")
    supplied_array_digest = _require_digest(
        _dict(packet.get("checked_resource_digest_contract"), "resource digest contract").get(
            "qualified_surface_contracts_sha256"
        ),
        "qualified surfaces SHA-256",
    )
    if (
        supplied_array_digest != _QUALIFIED_SURFACES_SHA256
        or _digest(surfaces) != _QUALIFIED_SURFACES_SHA256
    ):
        raise _CompetitionIdentityVerificationError("qualified surface inventory drifted")
    return surfaces


def _authenticated_implicit_supersession_proof() -> str:
    from nbadb.core.nba_api_implicit_competition_verifier import (
        _build_implicit_supersession_proof,
    )

    body, canonical, supplied = _build_implicit_supersession_proof()
    if (
        type(body) is not dict
        or type(canonical) is not bytes
        or type(supplied) is not str
        or _require_digest(supplied, "implicit supersession proof SHA-256")
        != _IMPLICIT_SUPERSESSION_PROOF_SHA256
        or canonical != _canonical_bytes(body)
        or hashlib.sha256(canonical).hexdigest() != supplied
    ):
        raise _CompetitionIdentityVerificationError("W5 implicit supersession proof body drifted")
    return supplied


def _source_authorities(proof_sha256: str) -> dict[str, object]:
    if (
        _require_digest(proof_sha256, "implicit supersession proof SHA-256")
        != _IMPLICIT_SUPERSESSION_PROOF_SHA256
    ):
        raise _CompetitionIdentityVerificationError("implicit supersession proof authority drifted")
    return {
        "task_packet": {"path": _TASK_PACKET_REL, "sha256": _TASK_PACKET_SHA256},
        "identity_contract": {
            "path": _IDENTITY_CONTRACT_REL,
            "sha256": _IDENTITY_CONTRACT_SHA256,
        },
        "terminal_state": {
            "path": _TERMINAL_RESOURCE,
            "resource_sha256": _TERMINAL_RESOURCE_SHA256,
            "payload_sha256": _TERMINAL_PAYLOAD_SHA256,
            "terminal_policy_sha256": _TERMINAL_POLICY_SHA256,
        },
        "request_surface": {
            "path": _REQUEST_RESOURCE,
            "resource_sha256": _REQUEST_RESOURCE_SHA256,
            "payload_sha256": _REQUEST_PAYLOAD_SHA256,
            "surface_sha256": _REQUEST_SURFACE_SHA256,
            "runtime_contract_payload_sha256": _REQUEST_RUNTIME_PAYLOAD_SHA256,
            "terminal_policy_sha256": _TERMINAL_POLICY_SHA256,
        },
        "competition": {
            "path": _COMPETITION_RESOURCE,
            "resource_sha256": _COMPETITION_RESOURCE_SHA256,
            "payload_sha256": _COMPETITION_PAYLOAD_SHA256,
            "authority_sha256": _COMPETITION_AUTHORITY_SHA256,
        },
        "competition_applicability": {
            "path": _APPLICABILITY_RESOURCE,
            "resource_sha256": _APPLICABILITY_RESOURCE_SHA256,
            "payload_sha256": _APPLICABILITY_PAYLOAD_SHA256,
            "authority_sha256": _APPLICABILITY_AUTHORITY_SHA256,
        },
        "implicit_competition": {
            "path": _IMPLICIT_RESOURCE,
            "resource_sha256": _IMPLICIT_RESOURCE_SHA256,
            "payload_sha256": _IMPLICIT_PAYLOAD_SHA256,
            "authority_sha256": _IMPLICIT_AUTHORITY_SHA256,
            "historical": True,
        },
        "implicit_supersession_proof": {
            "proof_sha256": proof_sha256,
        },
    }


def _collision_census(packet: dict[str, object]) -> dict[str, object]:
    contract = _dict(packet.get("collision_census_contract"), "collision census contract")
    return {
        "source_inventory_file_count": contract.get("source_inventory_file_count"),
        "source_inventory_inputs": deepcopy(
            _list(packet.get("source_inventory_inputs"), "source inventory inputs")
        ),
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


def _derive_expected_payload() -> tuple[dict[str, object], str]:
    _packet, identity_contract, _immutable, _mutable = _authenticate_packet_chain()
    terminal, request, competition, applicability, implicit = _authenticate_current_resources()
    requirements = _derive_requirements(
        identity_contract,
        applicability,
        implicit,
        competition,
        request,
    )
    surfaces = _validated_surfaces(identity_contract)
    implicit_supersession_proof_sha256 = _authenticated_implicit_supersession_proof()
    checked = _dict(
        identity_contract.get("checked_resource_contract"),
        "identity checked resource contract",
    )
    base: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "kind": _KIND,
        "task_id": _TASK_ID,
        "source_authorities": _source_authorities(implicit_supersession_proof_sha256),
        "collision_census": _collision_census(identity_contract),
        "domain_separators": deepcopy(
            _list(identity_contract.get("domain_separators"), "domain separators")
        ),
        "identity_requirements": requirements,
        "identity_requirements_sha256": _digest(requirements),
        "qualified_surface_contracts": surfaces,
        "qualified_surface_contracts_sha256": _digest(surfaces),
        "denominator_counts": deepcopy(
            _dict(identity_contract.get("denominator_authority"), "denominator authority")
        ),
        "binding_strategy_counts": deepcopy(
            _dict(identity_contract.get("binding_strategy_counts"), "binding strategy counts")
        ),
        "provider_request_policy": deepcopy(
            _dict(identity_contract.get("provider_request_policy"), "provider request policy")
        ),
        "provider_availability_values": deepcopy(
            _list(checked.get("provider_availability_values"), "provider availability values")
        ),
        "false_green_counters": deepcopy(
            _dict(identity_contract.get("false_green_counters"), "false-green counters")
        ),
        "collision_invariants": deepcopy(
            _dict(identity_contract.get("collision_invariants"), "collision invariants")
        ),
        "independent_proof": {"required": True, "verifier_id": _VERIFIER_ID},
    }
    _require_resource_values(
        terminal,
        {
            "terminal_policy_sha256": _TERMINAL_POLICY_SHA256,
            "payload_sha256": _TERMINAL_PAYLOAD_SHA256,
        },
        label="terminal identity predecessor",
    )
    authority_sha256 = _digest(base)
    with_authority = {**base, "authority_sha256": authority_sha256}
    expected = {**with_authority, "payload_sha256": _digest(with_authority)}
    if set(expected) != _TOP_LEVEL_KEYS:
        raise _CompetitionIdentityVerificationError("derived top-level schema is invalid")
    return expected, implicit_supersession_proof_sha256


def _read_candidate(path: Path | None) -> tuple[bytes, dict[str, object]]:
    if path is None:
        try:
            raw = resources.files("nbadb.contracts").joinpath(_RESOURCE).read_bytes()
        except (AttributeError, OSError) as exc:
            raise _CompetitionIdentityVerificationError(
                "checked competition identity resource cannot be read"
            ) from exc
    else:
        if type(path) is not _CONCRETE_PATH_TYPE:
            raise _CompetitionIdentityVerificationError("candidate path must be an exact Path")
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise _CompetitionIdentityVerificationError(
                "candidate competition identity resource cannot be read"
            ) from exc
    return raw, _parse_object(
        raw,
        label="competition identity candidate",
        canonical_format="pretty",
    )


def _verify_candidate_digests(candidate: dict[str, object]) -> None:
    _require_keys(candidate, _TOP_LEVEL_KEYS, "competition identity candidate")
    payload_body = dict(candidate)
    supplied_payload = payload_body.pop("payload_sha256", None)
    if _require_digest(supplied_payload, "candidate payload SHA-256") != _digest(payload_body):
        raise _CompetitionIdentityVerificationError("candidate payload digest is invalid")
    authority_body = dict(payload_body)
    supplied_authority = authority_body.pop("authority_sha256", None)
    if _require_digest(supplied_authority, "candidate authority SHA-256") != _digest(
        authority_body
    ):
        raise _CompetitionIdentityVerificationError("candidate authority digest is invalid")


def _proof_binding(
    expected: dict[str, object],
    implicit_supersession_proof_sha256: str,
) -> dict[str, object]:
    source_authorities = _dict(expected["source_authorities"], "expected source authorities")
    applicability = _dict(
        source_authorities["competition_applicability"], "expected applicability authority"
    )
    implicit = _dict(source_authorities["implicit_competition"], "expected implicit authority")
    supersession = _dict(
        source_authorities["implicit_supersession_proof"],
        "expected implicit supersession proof",
    )
    if supersession.get("proof_sha256") != implicit_supersession_proof_sha256:
        raise _CompetitionIdentityVerificationError(
            "proof DTO and checked-resource W5 bindings differ"
        )
    requirements = _rows(expected["identity_requirements"], "expected requirements")
    surfaces = _rows(expected["qualified_surface_contracts"], "expected surfaces")
    return {
        "verifier_id": _VERIFIER_ID,
        "task_packet_sha256": _TASK_PACKET_SHA256,
        "immutable_inputs_sha256": _IMMUTABLE_INPUTS_SHA256,
        "source_inventory_inputs_sha256": _SOURCE_INVENTORY_INPUTS_SHA256,
        "terminal_policy_sha256": _TERMINAL_POLICY_SHA256,
        "request_surface_sha256": _REQUEST_SURFACE_SHA256,
        "competition_applicability_authority_sha256": applicability.get("authority_sha256"),
        "implicit_competition_authority_sha256": implicit.get("authority_sha256"),
        "implicit_supersession_proof_sha256": supersession.get("proof_sha256"),
        "candidate_authority_sha256": expected.get("authority_sha256"),
        "candidate_payload_sha256": expected.get("payload_sha256"),
        "identity_requirements_sha256": expected.get("identity_requirements_sha256"),
        "qualified_surface_contracts_sha256": expected.get("qualified_surface_contracts_sha256"),
        "identity_requirement_count": len(requirements),
        "qualified_surface_contract_count": len(surfaces),
        "finding_count": 0,
        "findings": (),
    }


_PURE_PROOF_BINDING: tuple[tuple[str, object], ...] | None = None


def _prepare_pure_proof_binding(
    body: dict[str, object],
) -> tuple[tuple[tuple[str, object], ...], str]:
    if tuple(body) != _PROOF_FIELDS[:-1]:
        raise _CompetitionIdentityVerificationError("independent proof binding field order drifted")
    sealed = tuple((name, deepcopy(body[name])) for name in body)
    if _PURE_PROOF_BINDING is not None and not _exact_equal(
        dict(_PURE_PROOF_BINDING), dict(sealed)
    ):
        raise _CompetitionIdentityVerificationError(
            "independent proof binding changed within this process"
        )
    return sealed, _digest(body)


def _activate_pure_proof_binding(sealed: tuple[tuple[str, object], ...]) -> None:
    global _PURE_PROOF_BINDING

    if _PURE_PROOF_BINDING is not None and not _exact_equal(
        dict(_PURE_PROOF_BINDING), dict(sealed)
    ):
        raise _CompetitionIdentityVerificationError(
            "independent proof binding changed before activation"
        )
    _PURE_PROOF_BINDING = sealed


def _pure_proof_binding() -> dict[str, object]:
    if _PURE_PROOF_BINDING is None:
        raise _CompetitionIdentityVerificationError(
            "independent proof binding is unavailable before verification"
        )
    return dict(_PURE_PROOF_BINDING)


@dataclass(frozen=True, slots=True)
class IndependentCompetitionIdentityProof:
    """Exact proof that the checked authority matches independent sources."""

    verifier_id: str
    task_packet_sha256: str
    immutable_inputs_sha256: str
    source_inventory_inputs_sha256: str
    terminal_policy_sha256: str
    request_surface_sha256: str
    competition_applicability_authority_sha256: str
    implicit_competition_authority_sha256: str
    implicit_supersession_proof_sha256: str
    candidate_authority_sha256: str
    candidate_payload_sha256: str
    identity_requirements_sha256: str
    qualified_surface_contracts_sha256: str
    identity_requirement_count: int
    qualified_surface_contract_count: int
    finding_count: int
    findings: tuple[str, ...]
    proof_sha256: str

    def __post_init__(self) -> None:
        self._validated_body()

    def _validated_body(self) -> dict[str, object]:
        if type(self) is not IndependentCompetitionIdentityProof:
            raise _CompetitionIdentityVerificationError(
                "independent proof must be the exact concrete DTO"
            )
        if type(self.verifier_id) is not str or self.verifier_id != _VERIFIER_ID:
            raise _CompetitionIdentityVerificationError("independent verifier ID is invalid")
        for name in _PROOF_DIGEST_FIELDS:
            value = getattr(self, name)
            if type(value) is not str:
                raise _CompetitionIdentityVerificationError(f"{name} must be an exact str")
            _require_digest(value, name)
        exact_counts = {
            "identity_requirement_count": _EXPECTED_REQUIREMENT_COUNT,
            "qualified_surface_contract_count": _EXPECTED_SURFACE_COUNT,
            "finding_count": 0,
        }
        for name in _PROOF_COUNT_FIELDS:
            _require_exact_int(getattr(self, name), exact_counts[name], name)
        if (
            type(self.findings) is not tuple
            or any(type(item) is not str or not item for item in self.findings)
            or self.findings
        ):
            raise _CompetitionIdentityVerificationError(
                "findings must be an exact empty concrete tuple on PASS"
            )
        body = {
            field.name: getattr(self, field.name)
            for field in fields(self)
            if field.name != "proof_sha256"
        }
        if tuple((*body, "proof_sha256")) != _PROOF_FIELDS:
            raise _CompetitionIdentityVerificationError("independent proof schema drifted")
        if not _exact_equal(body, _pure_proof_binding()):
            raise _CompetitionIdentityVerificationError(
                "independent proof binding differs from independently derived sources"
            )
        if self.proof_sha256 != _digest(body):
            raise _CompetitionIdentityVerificationError("independent proof digest is invalid")
        return body

    def validated_payload(self) -> dict[str, object]:
        """Return the proof JSON projection after pure in-memory revalidation."""

        payload = {**self._validated_body(), "proof_sha256": self.proof_sha256}
        payload["findings"] = list(self.findings)
        return payload

    def to_dict(self) -> dict[str, object]:
        """Return the exact JSON-compatible proof projection without file I/O."""

        return self.validated_payload()

    def __copy__(self) -> IndependentCompetitionIdentityProof:
        self._validated_body()
        return self

    def __deepcopy__(self, _memo: dict[int, object]) -> IndependentCompetitionIdentityProof:
        self._validated_body()
        return self

    def __reduce_ex__(
        self,
        _protocol: SupportsIndex,
    ) -> tuple[type[IndependentCompetitionIdentityProof], tuple[object, ...]]:
        self._validated_body()
        return (
            IndependentCompetitionIdentityProof,
            tuple(getattr(self, field.name) for field in fields(self)),
        )


def verify_pinned_competition_identity_authority(
    path: Path | None = None,
) -> IndependentCompetitionIdentityProof:
    """Re-derive and verify the installed or explicit checked resource."""

    expected, implicit_supersession_proof_sha256 = _derive_expected_payload()
    expected_raw = _pretty_bytes(expected)
    body = _proof_binding(expected, implicit_supersession_proof_sha256)
    sealed_binding, proof_sha256 = _prepare_pure_proof_binding(body)
    raw, candidate = _read_candidate(path)
    _verify_candidate_digests(candidate)
    if not _exact_equal(candidate, expected) or raw != expected_raw:
        raise _CompetitionIdentityVerificationError(
            "checked competition identity authority differs from independent sources"
        )
    _activate_pure_proof_binding(sealed_binding)
    return IndependentCompetitionIdentityProof(
        verifier_id=cast("str", body["verifier_id"]),
        task_packet_sha256=cast("str", body["task_packet_sha256"]),
        immutable_inputs_sha256=cast("str", body["immutable_inputs_sha256"]),
        source_inventory_inputs_sha256=cast("str", body["source_inventory_inputs_sha256"]),
        terminal_policy_sha256=cast("str", body["terminal_policy_sha256"]),
        request_surface_sha256=cast("str", body["request_surface_sha256"]),
        competition_applicability_authority_sha256=cast(
            "str", body["competition_applicability_authority_sha256"]
        ),
        implicit_competition_authority_sha256=cast(
            "str", body["implicit_competition_authority_sha256"]
        ),
        implicit_supersession_proof_sha256=cast("str", body["implicit_supersession_proof_sha256"]),
        candidate_authority_sha256=cast("str", body["candidate_authority_sha256"]),
        candidate_payload_sha256=cast("str", body["candidate_payload_sha256"]),
        identity_requirements_sha256=cast("str", body["identity_requirements_sha256"]),
        qualified_surface_contracts_sha256=cast("str", body["qualified_surface_contracts_sha256"]),
        identity_requirement_count=cast("int", body["identity_requirement_count"]),
        qualified_surface_contract_count=cast("int", body["qualified_surface_contract_count"]),
        finding_count=cast("int", body["finding_count"]),
        findings=cast("tuple[str, ...]", body["findings"]),
        proof_sha256=proof_sha256,
    )


__all__ = [
    "IndependentCompetitionIdentityProof",
    "verify_pinned_competition_identity_authority",
]
