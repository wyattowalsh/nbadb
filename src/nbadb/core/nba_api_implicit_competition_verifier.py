"""Independent offline verifier for implicit competition closure.

The candidate checked resource is deliberately the last input read.  Before
that read, this module re-derives the explicit/implicit partition from the
pinned distribution, checked predecessor resources, the live registry, and
the exact extractor source inventory.  It performs no provider or network
request and has no dependency on the primary compiler.
"""

from __future__ import annotations

import ast
import base64
import csv
import hashlib
import importlib.metadata
import io
import json
import re
import stat
from copy import deepcopy
from dataclasses import dataclass, fields
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Final, SupportsIndex, cast

_PACKAGED_IMPLICIT_PROVENANCE_ROOT: Final = (
    "provenance",
    "nba_api_v1_11_4",
    "implicit_competition",
)
_PACKAGED_IDENTITY_PROVENANCE_ROOT: Final = (
    "provenance",
    "nba_api_v1_11_4",
    "competition_identity",
)
_TASK_PACKET_REL: Final = "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.2d.json"
_SUCCESSOR_TASK_PACKET_REL: Final = (
    "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-11.json"
)
_EVIDENCE_REL: Final = (
    "artifacts/assurance/complete-nba-api-sink/A1.2d/source-inputs/"
    "implicit-competition-root-evidence.json"
)
_SOURCE_REVIEW_REL: Final = (
    "artifacts/assurance/complete-nba-api-sink/A1.2d/source-inputs/source-review.json"
)
_RESOURCE: Final = "nba_api_implicit_competition_v1_11_4.json"
_RESOURCE_REL: Final = f"src/nbadb/contracts/{_RESOURCE}"
_CURRENT_SOURCE_RESOURCE: Final = "nba_api_implicit_competition_current_source_v1_11_4.json"
_CURRENT_SOURCE_RESOURCE_RAW_SHA256: Final = (
    "41863f896fa0e0bed167472cea3f308c2387d75f016866675cec4fb62a90afc2"
)
_CURRENT_SOURCE_AUTHORITY_SHA256: Final = (
    "cb16435d02467e2aae1888e665f806593a74736faaf9e6fcfbc83c133097acfc"
)
_CURRENT_SOURCE_CANDIDATE_SHA256: Final = (
    "081ea4e47c4b4a9f718ceced87ac4aca7e97b657408c51068ae2a9e2db30dcbf"
)
_CURRENT_SOURCE_PROOF_SHA256: Final = (
    "88b688030a6ef5ce4a5e854adf7d80b160a1893e7fbac4390cbb6670dae733c1"
)
_CURRENT_SOURCE_REVIEW_SHA256: Final = (
    "d2edd3ef4e71c4067979a18013a65148f5c939f83345fce391ec839ed8097fcf"
)
_CURRENT_SOURCE_PROVIDER_AUTHORITY_SHA256: Final = (
    "e5981c0223c99ecd4a483606781d1433cc23f22b26ec71c41a3b12b9ad827085"
)
_CURRENT_SOURCE_RESOURCE_SIZE: Final = 10022
_TASK_PACKET_SHA256: Final = "acc12887aa5525a0ed9cc8047264c7efda3da92da745c5145138b4eb2a72e1bb"
_SUCCESSOR_TASK_PACKET_SHA256: Final = (
    "5f0cb0d04f9e46f412458489ba0d088193e18ba128f1739a2c03d87b4b5e57da"
)
_HISTORICAL_OPENING_ROWS_SHA256: Final = (
    "923d931c5f8e58f6a74d29aa4d245fcaa9a9df1a52b1e632e1b0a3bc772cb653"
)
_SUCCESSOR_PATHS_SHA256: Final = "ff9e7db0ac7f7e2d6845f36ff21facc04ca9479cf7cfe6bbc639e70e7451c2c1"
_CURRENT_SUCCESSOR_ROWS_SHA256: Final = (
    "745517a7ec7dfa3bd4527a02b594feb04d962bc976cccb7cb8e3d69bdb5998bb"
)
_HISTORICAL_IMPLICIT_RESOURCE_SHA256: Final = (
    "ed75be5cf84df8975cc32d50b51215648896b618584ed5b3b3aedcb8b6dc2111"
)
_HISTORICAL_IMPLICIT_AUTHORITY_SHA256: Final = (
    "fe7fd7581532754b322155ad0a74fcbd4068e1ebc83fbd841fd3736e27616d97"
)
_HISTORICAL_IMPLICIT_PAYLOAD_SHA256: Final = (
    "9fddfad2276884b5d49dc71fca052d7285f73e046d5157427b7fb7b2fcd35ec1"
)
_HISTORICAL_IMPLICIT_RESOURCE_SIZE: Final = 343817
_SUCCESSOR_PATHS: Final = (
    "src/nbadb/core/nba_api_request_surface.py",
    "src/nbadb/core/nba_api_request_surface_verifier.py",
    "src/nbadb/contracts/nba_api_request_surface_v1_11_4.json",
    "src/nbadb/contracts/nba_api_competition_occurrences_v1_11_4.json",
    "src/nbadb/core/nba_api_competition_applicability.py",
    "src/nbadb/core/nba_api_competition_applicability_verifier.py",
    "src/nbadb/contracts/nba_api_competition_applicability_v1_11_4.json",
)
_HISTORICAL_OPENING_ROWS: Final = (
    {
        "path": _SUCCESSOR_PATHS[0],
        "sha256": "ff5f5bc589876a5b624f93692f8a43021cf3a2465a9cdd18475c3497dab0fc96",
    },
    {
        "path": _SUCCESSOR_PATHS[1],
        "sha256": "e85960d3577daf967136ef31f519ea03f27c849d58e1450ee86ab88cf5959308",
    },
    {
        "path": _SUCCESSOR_PATHS[2],
        "sha256": "c5b1de0b1e6e05541eec90df9c92ce3ca9e3c1cae490fe6723410137f947e608",
    },
    {
        "path": _SUCCESSOR_PATHS[3],
        "sha256": "28f72468be47dce5b13429e43140f96277422892ee8dc21ab723ef1c606bc700",
    },
    {
        "path": _SUCCESSOR_PATHS[4],
        "sha256": "271bfa9855bf4c3e8f51bc3eaff82d6225c5a89569fdc319a7d43856d0085cda",
    },
    {
        "path": _SUCCESSOR_PATHS[5],
        "sha256": "a847dff632338981aa522646ce766a2e029aa43a95c4adcc3e0fb427e06a7ebd",
    },
    {
        "path": _SUCCESSOR_PATHS[6],
        "sha256": "2542f2b0a5fd0ba3faefc8ce7b4bf2b1f1870b12beb6d98172cdd7e3857e1b53",
    },
)
_CURRENT_SUCCESSOR_ROWS: Final = (
    {
        "path": _SUCCESSOR_PATHS[0],
        "sha256": "9567f8f6b14cbdc9585bb3bd7197580213c14298cbde1ad5025cc28f73c5e268",
    },
    {
        "path": _SUCCESSOR_PATHS[1],
        "sha256": "8dbf18e9424daaf497eb864329d4e5ab9a8ab15535538346f733785bae45e499",
    },
    {
        "path": _SUCCESSOR_PATHS[2],
        "sha256": "3082def2aa92b35d55107f5ce8eaf2ffa0532a0e649899d0f1180979f6144981",
    },
    {
        "path": _SUCCESSOR_PATHS[3],
        "sha256": "8bd3365806aa3118e3ec265a6e70647390b54aab203050805c59b6e6d9bce459",
    },
    {
        "path": _SUCCESSOR_PATHS[4],
        "sha256": "41baeba9f6a767fb76f3cb5796668810cf29ac48adba6ef80d658e35575f99b9",
    },
    {
        "path": _SUCCESSOR_PATHS[5],
        "sha256": "cd6f3a1665453ceb61f1003ad3b2fdd3fa5f41f12008d30e8f059ffe149a0a78",
    },
    {
        "path": _SUCCESSOR_PATHS[6],
        "sha256": "daf43b872bd301aa87f1a67b357d970b82e532890e09e7ce0e580545d09cb0aa",
    },
)
_EVIDENCE_SHA256: Final = "ff848edf46d65bbfc5748e0b30a59d45e2be2a981a578fab73170089aa1c12ba"
_EVIDENCE_AUTHORITY_SHA256: Final = (
    "96a166d692a07becea6a0a011072c20bae95833487ce092ee0a02debee5143ac"
)
_EVIDENCE_PAYLOAD_SHA256: Final = "905bfadce66e678af78415347c5c3a6dd4d575149b8848b6b0473b80aa0bcebb"
_EVIDENCE_CANONICALIZATION_SHA256: Final = (
    "d58db0edc23f101e5bff8ef086b4dcecc48730b77239c5f3c176a1ce24991e99"
)
_RECEIPT_POLICY_SHA256: Final = "a53080ffbeafd3196ab4f258c508c54ac771af43abccf7c675fbf75e641dc4bd"
_SOURCE_REVIEW_SHA256: Final = "d028c60baa78832991d83cbd977d0d555b32b6ebc38a281bb14e7592d76f37e8"
_SOURCE_REVIEW_AUTHORITY_SHA256: Final = (
    "cfb8b6f52204d645a8206a7cf5799c76a8aed4c37990339c489f4698a5f721a3"
)
_SOURCE_REVIEW_PAYLOAD_SHA256: Final = (
    "fddd62b89999ef7a1d43ded8aef6f5511c6ffe0d0c1884125b9b54ce41c172b2"
)
_SOURCE_REVIEW_CANONICALIZATION_SHA256: Final = (
    "bc7963a2135272174cf1959733d0b18e8a5caedd1ea1b1529430442d54130817"
)
_VERIFIER_ID: Final = "nbadb_independent_implicit_competition_v1"
_CONCRETE_PATH_TYPE: Final = type(Path())
_DISTRIBUTION: Final = "nba-api"
_VERSION: Final = "1.11.4"
_DISTRIBUTION_RECORD_AUTHORITY_SHA256: Final = (
    "c644ee6a70347b2f49a0064d237aebaaf82f4522e2b78faf5347afe99c516aa8"
)
_DISTRIBUTION_RECORD_SHA256: Final = (
    "b75304af37c0d8a1bcc8f429bccb4a7d58e707586af6da9efa5cb0d730aa72f1"
)
_DISTRIBUTION_ENTRIES_SHA256: Final = (
    "a4ce72f52e3a54dd6a2425121c12a9208fca060830569e1fe2115daaa114c1aa"
)
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)
_COMPETITIONS: Final = (
    ("00", "nba"),
    ("01", "aba"),
    ("10", "wnba"),
    ("15", "summer_league"),
    ("20", "g_league"),
)
_STATIC_ASSIGNMENTS: Final = {
    "static_players": ("get_players", "players", "00", "nba"),
    "static_teams": ("get_teams", "teams", "00", "nba"),
    "static_wnba_players": ("get_wnba_players", "wnba_players", "10", "wnba"),
    "static_wnba_teams": ("get_wnba_teams", "wnba_teams", "10", "wnba"),
}
_CURRENT_PREDECESSOR_RESOURCE_HASHES: Final = {
    "nba_api_competition_v1_11_4.json": (
        "cfb93458f5efb569995ddccaf33ae37c0c312e25e09d0649c307999ec0057c44"
    ),
    "nba_api_competition_occurrences_v1_11_4.json": (
        "8bd3365806aa3118e3ec265a6e70647390b54aab203050805c59b6e6d9bce459"
    ),
    "nba_api_request_surface_v1_11_4.json": (
        "3082def2aa92b35d55107f5ce8eaf2ffa0532a0e649899d0f1180979f6144981"
    ),
    "nba_api_runtime_contract_v1_11_4.json": (
        "24ed29f72f19de9e9c02ed4e4f8363b0e2b0809ce59886975f2f739cc80665b4"
    ),
    "nba_api_competition_applicability_v1_11_4.json": (
        "daf43b872bd301aa87f1a67b357d970b82e532890e09e7ce0e580545d09cb0aa"
    ),
}
_CURRENT_RUNTIME_IDENTITY: Final = {
    "contracts_sha256": "a9838c5464d5410210fc3d5af3d3f75c1a796eb46ff999079749a1a4b77f4309",
    "live_contracts_sha256": "18750aec673db6c1a2c7d43b7425ec90b4a354c193491664bf24b34d8cda7543",
    "payload_sha256": "7c9b59c475cff6b0b9d3619bdfe9a3849e11619980f6d15a1cafd5f269f61b3b",
    "schema_version": 4,
    "static_contracts_sha256": "ccd209d3d89356c9d368b8d45db94cf9c119d1329b2dc4764fbc112a1990caff",
}
_CURRENT_REQUEST_IDENTITY: Final = {
    "manifest_sha256": "cdbcd18750178371d393256d0c773735b53003bd28591aaa28a5a99db04f7d87",
    "parameter_occurrences_sha256": (
        "77b6de7f99f47da168372251547b48f4714d4653baf40bba39444a1e360dadee"
    ),
    "payload_sha256": "b310313f41cf97cf1b8f55e01bbe95868532f3008527bf5265a985628eca9052",
    "resource_sha256": _CURRENT_PREDECESSOR_RESOURCE_HASHES["nba_api_request_surface_v1_11_4.json"],
    "schema_version": 3,
    "surface_sha256": "ef6195829a9f1dad9f847094b79e88fae24dffc5c4df18e3d3e972f347f83733",
}
_CURRENT_OCCURRENCE_IDENTITY: Final = {
    "authority_sha256": "4ef38c7ee185ff10fea4b4de611648af1b30be04f700399549233e809cd53935",
    "package_endpoint_count": 111,
    "package_occurrence_count": 112,
    "payload_sha256": "ed06098b67f31e19eca8d9d1e51b25d03681c3d7c0ecfae4b83e84dd7642f179",
    "repo_alias_count": 126,
    "repo_aliases_sha256": "46e2fe360fcc1f14a84db6c1a4938112baa948c517effe0ac4a54e184577f0f9",
    "resource_sha256": _CURRENT_PREDECESSOR_RESOURCE_HASHES[
        "nba_api_competition_occurrences_v1_11_4.json"
    ],
    "schema_version": 1,
    "upstream_request_surface": {
        "payload_sha256": _CURRENT_REQUEST_IDENTITY["payload_sha256"],
        "resource": "nba_api_request_surface_v1_11_4.json",
        "resource_sha256": _CURRENT_REQUEST_IDENTITY["resource_sha256"],
        "surface_sha256": _CURRENT_REQUEST_IDENTITY["surface_sha256"],
    },
}
_CURRENT_APPLICABILITY_IDENTITY: Final = {
    "alias_role_competition_cell_count": 635,
    "authority_sha256": "867d64282d6da37b9289c191ec5396e34c2c2ca335ebc94d09329ad89619528f",
    "endpoint_competition_cell_count": 555,
    "parameter_axis_competition_cell_count": 560,
    "payload_sha256": "c1b808dc593d5aa9aea90b02285c2cfb37dc60e60ecd988dcf944d4984a9907a",
    "resource_sha256": _CURRENT_PREDECESSOR_RESOURCE_HASHES[
        "nba_api_competition_applicability_v1_11_4.json"
    ],
    "schema_version": 1,
    "source_authorities": {
        "competition_occurrences": {
            "authority_sha256": _CURRENT_OCCURRENCE_IDENTITY["authority_sha256"]
        },
        "request_surface": {"surface_sha256": _CURRENT_REQUEST_IDENTITY["surface_sha256"]},
    },
    "typed_declared_axis_cell_count": 1750,
}
_SEMANTIC_PROJECTION_FIELDS: Final = (
    "endpoint_bindings",
    "alias_bindings",
    "physical_competition_cells",
    "alias_competition_cells",
    "denominator_counts",
    "receipt_bound_root_policy",
)
_PARTITION_COUNTS: Final = {
    "physical_sources": {"explicit": 111, "implicit": 36, "total": 147},
    "repo_aliases": {"explicit": 126, "implicit": 36, "total": 162},
    "physical_competition_cells": {"explicit": 555, "implicit": 180, "total": 735},
    "parameter_axis_competition_cells": {
        "explicit": 560,
        "implicit": 180,
        "total": 740,
    },
    "projected_alias_roles": {"explicit": 127, "implicit": 36, "total": 163},
    "alias_role_competition_cells": {"explicit": 635, "implicit": 180, "total": 815},
}
_W5_PROOF_KIND: Final = "nbadb_implicit_competition_supersession_proof"
_HISTORICAL_SOURCE_AUTHORITIES_SHA256: Final = (
    "33c4183f786d633a5a064f88550e8339838f75a294f52d1ea8b6d7fcbe23c1d3"
)
_HISTORICAL_EVIDENCE_IMMUTABLES_SHA256: Final = (
    "60a23f5f08f992c75750d0d40a61b8d1bcb81e8c667368989da0fbd7f53d737a"
)
_HISTORICAL_PACKET_IMMUTABLES_SHA256: Final = (
    "887a2b2b91fb61baa21f3c37f80a9a94ad50b48a66bb5b6ad5f7cef3065dc56e"
)
_ENDPOINT_BINDING_KEYS: Final = frozenset(
    {
        "binding_sha256",
        "explicit_competition_axis_occurrence_ids",
        "explicit_competition_axis_status",
        "extractor_module",
        "extractor_qualname",
        "forwarding_behavior",
        "physical_endpoint_key",
        "provider_contract_sha256",
        "provider_endpoint_id",
        "provider_source_path",
        "provider_source_sha256",
        "provider_source_size",
        "repo_endpoint_name",
        "repo_source_path",
        "repo_source_sha256",
        "repo_source_size",
        "root_evidence",
        "root_kind",
        "root_mode",
        "source_family",
    }
)
_ALIAS_BINDING_KEYS: Final = frozenset(
    {"provider_endpoint_id", "repo_endpoint_name", "source_family", "source_path"}
)
_PHYSICAL_CELL_KEYS: Final = frozenset(
    {
        "assignment_authority",
        "cell_id",
        "endpoint_support_status",
        "league_id",
        "physical_endpoint_key",
        "provider_availability_status",
        "provider_endpoint_id",
        "provider_probe_executed",
        "request_terminal_state",
        "root_binding_sha256",
        "root_kind",
        "root_state",
        "source_family",
        "symbol",
    }
)
_ALIAS_CELL_KEYS: Final = _PHYSICAL_CELL_KEYS | {"repo_endpoint_name"}
_ROOT_PARAMETER_KEYS: Final = frozenset(
    {
        "coverage_policy",
        "domain_kind",
        "location",
        "name",
        "nullable",
        "occurrence_id",
        "ordinal",
        "query_name",
        "required",
        "semantic_role",
        "source_signature_sha256",
        "typed_domain_sha256",
        "value_types",
    }
)
_PROOF_DIGEST_FIELDS: Final = (
    "task_packet_sha256",
    "evidence_sha256",
    "evidence_authority_sha256",
    "source_review_sha256",
    "source_review_authority_sha256",
    "candidate_authority_sha256",
    "candidate_payload_sha256",
    "endpoint_bindings_sha256",
    "alias_bindings_sha256",
    "physical_competition_cells_sha256",
    "alias_competition_cells_sha256",
    "proof_sha256",
)
_PROOF_COUNT_FIELDS: Final = (
    "endpoint_binding_count",
    "alias_binding_count",
    "physical_cell_count",
    "alias_cell_count",
    "cumulative_physical_competition_cell_count",
    "cumulative_parameter_axis_count",
    "cumulative_parameter_axis_cell_count",
    "cumulative_projected_alias_role_count",
    "cumulative_alias_role_cell_count",
)
_PROOF_RESULT_FIELDS: Final = ("missing_ids", "foreign_ids", "mismatched_ids")
_PROOF_BODY_FIELDS: Final = frozenset(
    (
        "verifier_id",
        *_PROOF_DIGEST_FIELDS[:-1],
        *_PROOF_COUNT_FIELDS,
        *_PROOF_RESULT_FIELDS,
    )
)


class _ImplicitCompetitionVerificationError(ValueError):
    """The independent implicit-competition proof failed closed."""


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
        raise _ImplicitCompetitionVerificationError(
            "implicit competition value is not canonical JSON"
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
        raise _ImplicitCompetitionVerificationError(
            "implicit competition value is not canonical JSON"
        ) from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_digest(value: object, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise _ImplicitCompetitionVerificationError(f"{label} must be a canonical SHA-256")
    return value


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _ImplicitCompetitionVerificationError(
                f"implicit competition input contains duplicate key: {key}"
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise _ImplicitCompetitionVerificationError(
        f"implicit competition input contains non-finite constant: {value}"
    )


def _parse(raw: bytes, *, label: str, pretty: bool) -> dict[str, object]:
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except _ImplicitCompetitionVerificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _ImplicitCompetitionVerificationError(f"{label} cannot be decoded") from exc
    expected = _pretty_bytes(value) if pretty else _canonical_bytes(value) + b"\n"
    if not isinstance(value, dict) or raw != expected:
        raise _ImplicitCompetitionVerificationError(f"{label} is not canonical JSON")
    return cast("dict[str, object]", value)


def _read_path(path: Path, *, label: str, pretty: bool) -> tuple[bytes, dict[str, object]]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise _ImplicitCompetitionVerificationError(f"{label} cannot be read") from exc
    return raw, _parse(raw, label=label, pretty=pretty)


def _read_packaged_provenance(
    relative: str, *, label: str, pretty: bool
) -> tuple[bytes, dict[str, object]]:
    if relative == _SUCCESSOR_TASK_PACKET_REL:
        root = _PACKAGED_IDENTITY_PROVENANCE_ROOT
    elif relative in {_TASK_PACKET_REL, _EVIDENCE_REL, _SOURCE_REVIEW_REL}:
        root = _PACKAGED_IMPLICIT_PROVENANCE_ROOT
    else:
        raise _ImplicitCompetitionVerificationError(f"{label} has no packaged authority")
    try:
        raw = (
            resources.files("nbadb.contracts")
            .joinpath(*root, relative.rsplit("/", 1)[-1])
            .read_bytes()
        )
    except (AttributeError, OSError) as exc:
        raise _ImplicitCompetitionVerificationError(f"{label} cannot be read") from exc
    return raw, _parse(raw, label=label, pretty=pretty)


def _read_packaged_source(relative: str) -> bytes:
    prefix = "src/nbadb/"
    suffix = relative.removeprefix(prefix)
    if not relative.startswith(prefix) or not suffix or ".." in suffix.split("/"):
        raise _ImplicitCompetitionVerificationError(f"packaged source path is invalid: {relative}")
    try:
        return resources.files("nbadb").joinpath(*suffix.split("/")).read_bytes()
    except (AttributeError, OSError) as exc:
        raise _ImplicitCompetitionVerificationError(
            f"packaged source cannot be read: {relative}"
        ) from exc


def _parse_minified_object(raw: bytes, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except _ImplicitCompetitionVerificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _ImplicitCompetitionVerificationError(f"{label} cannot be decoded") from exc
    if type(value) is not dict or raw != _canonical_bytes(value):
        raise _ImplicitCompetitionVerificationError(f"{label} is not canonical minified JSON")
    return cast("dict[str, object]", value)


def _read_packaged_current_source_authority() -> tuple[bytes, dict[str, object]]:
    try:
        raw = resources.files("nbadb.contracts").joinpath(_CURRENT_SOURCE_RESOURCE).read_bytes()
    except (AttributeError, OSError) as exc:
        raise _ImplicitCompetitionVerificationError(
            "current implicit-competition source authority cannot be read"
        ) from exc
    if (
        len(raw) != _CURRENT_SOURCE_RESOURCE_SIZE
        or hashlib.sha256(raw).hexdigest() != _CURRENT_SOURCE_RESOURCE_RAW_SHA256
    ):
        raise _ImplicitCompetitionVerificationError(
            "current implicit-competition source authority raw identity drifted"
        )
    return raw, _parse_minified_object(raw, label="current source authority")


def _python_semantic_sha256(raw: bytes, *, path: str) -> str:
    try:
        tree = ast.parse(raw, filename=path)
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise _ImplicitCompetitionVerificationError(
            f"current source is not valid Python: {path}"
        ) from exc
    return hashlib.sha256(
        ast.dump(tree, annotate_fields=True, include_attributes=False).encode("utf-8")
    ).hexdigest()


def _current_source_inventory(
    *,
    historical_paths: tuple[str, ...],
) -> list[dict[str, object]]:
    _raw, authority = _read_packaged_current_source_authority()
    if (
        set(authority)
        != {"authority_sha256", "generation_proof", "kind", "review", "schema_version"}
        or authority.get("kind") != "nbadb_implicit_competition_current_source_authority"
        or type(authority.get("schema_version")) is not int
        or authority.get("schema_version") != 1
    ):
        raise _ImplicitCompetitionVerificationError(
            "current source authority schema identity drifted"
        )
    authority_body = dict(authority)
    authority_sha256 = _require_digest(
        authority_body.pop("authority_sha256", None),
        "current source authority sha256",
    )
    if authority_sha256 != _CURRENT_SOURCE_AUTHORITY_SHA256 or authority_sha256 != _digest(
        authority_body
    ):
        raise _ImplicitCompetitionVerificationError(
            "current source authority semantic identity drifted"
        )

    proof = _dict(authority.get("generation_proof"), "current source generation proof")
    if set(proof) != {
        "candidate",
        "generation_candidate_bytes_sha256s",
        "generation_policy_sha256",
        "kind",
        "proof_sha256",
        "schema_version",
    }:
        raise _ImplicitCompetitionVerificationError("current source proof shape drifted")
    proof_body = dict(proof)
    proof_sha256 = _require_digest(
        proof_body.pop("proof_sha256", None),
        "current source proof sha256",
    )
    if proof_sha256 != _CURRENT_SOURCE_PROOF_SHA256 or proof_sha256 != _digest(proof_body):
        raise _ImplicitCompetitionVerificationError("current source proof identity drifted")

    candidate = _dict(proof.get("candidate"), "current source candidate")
    if set(candidate) != {
        "author_role",
        "author_task_id",
        "candidate_sha256",
        "frozen_bindings",
        "kind",
        "predecessor_receipt_sha256",
        "provider_authority_sha256",
        "schema_version",
        "semantic_projection_sha256",
        "source_bindings",
        "source_inventory_sha256",
    }:
        raise _ImplicitCompetitionVerificationError("current source candidate shape drifted")
    candidate_body = dict(candidate)
    candidate_sha256 = _require_digest(
        candidate_body.pop("candidate_sha256", None),
        "current source candidate sha256",
    )
    if (
        candidate_sha256 != _CURRENT_SOURCE_CANDIDATE_SHA256
        or candidate_sha256 != _digest(candidate_body)
        or candidate.get("provider_authority_sha256") != _CURRENT_SOURCE_PROVIDER_AUTHORITY_SHA256
        or candidate.get("author_task_id") != "A1.3a-repair-12"
        or candidate.get("author_role") != "current-source-author"
    ):
        raise _ImplicitCompetitionVerificationError("current source candidate identity drifted")

    review = _dict(authority.get("review"), "current source review")
    review_body = dict(review)
    review_sha256 = _require_digest(
        review_body.pop("receipt_sha256", None),
        "current source review sha256",
    )
    if (
        review_sha256 != _CURRENT_SOURCE_REVIEW_SHA256
        or review_sha256 != _digest(review_body)
        or review.get("disposition") != "accepted"
        or review.get("findings") != []
        or review.get("reviewer_task_id") != "A1.3a-repair-12-review"
        or review.get("reviewer_role") != "independent-current-source-reviewer"
    ):
        raise _ImplicitCompetitionVerificationError("current source review identity drifted")

    frozen = _rows(candidate.get("frozen_bindings"), "current source frozen bindings")
    sources = _rows(candidate.get("source_bindings"), "current source bindings")
    if len(frozen) != 7 or len(sources) != 13 or len(frozen) + len(sources) != 20:
        raise _ImplicitCompetitionVerificationError(
            "current source provenance binding count drifted"
        )
    source_paths = tuple(str(row.get("path")) for row in sources)
    if source_paths != historical_paths or len(set(source_paths)) != len(source_paths):
        raise _ImplicitCompetitionVerificationError(
            "historical and current source path inventories differ"
        )
    if candidate.get("source_inventory_sha256") != _digest(sources):
        raise _ImplicitCompetitionVerificationError("current source inventory digest drifted")
    semantic_projection = [
        {"path": row.get("path"), "semantic_sha256": row.get("semantic_sha256")} for row in sources
    ]
    if candidate.get("semantic_projection_sha256") != _digest(semantic_projection):
        raise _ImplicitCompetitionVerificationError("current source semantic projection drifted")

    for row in sources:
        if set(row) != {"byte_count", "path", "semantic_sha256", "sha256"}:
            raise _ImplicitCompetitionVerificationError("current source binding shape drifted")
        path = row.get("path")
        byte_count = row.get("byte_count")
        if type(path) is not str or type(byte_count) is not int or byte_count <= 0:
            raise _ImplicitCompetitionVerificationError("current source binding value drifted")
        raw = _read_packaged_source(path)
        if (
            len(raw) != byte_count
            or hashlib.sha256(raw).hexdigest()
            != _require_digest(row.get("sha256"), "current source binding sha256")
            or _python_semantic_sha256(raw, path=path)
            != _require_digest(
                row.get("semantic_sha256"),
                "current source binding semantic sha256",
            )
        ):
            raise _ImplicitCompetitionVerificationError(
                f"current source binding differs from packaged source: {path}"
            )
    return sources


def _verify_payload_digest(payload: dict[str, object], *, label: str) -> None:
    body = dict(payload)
    supplied = body.pop("payload_sha256", None)
    if _require_digest(supplied, f"{label} payload_sha256") != _digest(body):
        raise _ImplicitCompetitionVerificationError(f"{label} payload digest is invalid")


def _dict(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise _ImplicitCompetitionVerificationError(f"{label} must be an object")
    return cast("dict[str, object]", value)


def _rows(value: object, label: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise _ImplicitCompetitionVerificationError(f"{label} must be an object array")
    return cast("list[dict[str, object]]", value)


def _exact_int(value: object, expected: int, label: str) -> None:
    if type(value) is not int or value != expected:
        raise _ImplicitCompetitionVerificationError(f"{label} is not exact")


def _validate_reconciliation_packets(
    historical_raw: bytes,
    historical: dict[str, object],
    successor_raw: bytes,
    successor: dict[str, object],
    evidence: dict[str, object],
) -> None:
    if (
        hashlib.sha256(historical_raw).hexdigest() != _TASK_PACKET_SHA256
        or historical.get("schema") != "TaskPacketV1"
        or historical.get("task_id") != "A1.2d"
    ):
        raise _ImplicitCompetitionVerificationError(
            "historical A1.2d task packet identity is invalid"
        )
    if (
        hashlib.sha256(successor_raw).hexdigest() != _SUCCESSOR_TASK_PACKET_SHA256
        or successor.get("schema") != "TaskPacketV1"
        or successor.get("task_id") != "A1.3a-repair-11"
    ):
        raise _ImplicitCompetitionVerificationError("A1.3a repair task packet identity is invalid")

    immutable = _rows(historical.get("immutable_inputs"), "A1.2d immutable inputs")
    if (
        len(immutable) != 41
        or _digest(immutable) != _HISTORICAL_PACKET_IMMUTABLES_SHA256
        or any(
            set(item) != {"path", "sha256"}
            or type(item.get("path")) is not str
            or not item.get("path")
            or type(item.get("sha256")) is not str
            or _SHA256_RE.fullmatch(cast("str", item.get("sha256"))) is None
            for item in immutable
        )
        or len({cast("str", item["path"]) for item in immutable}) != 41
    ):
        raise _ImplicitCompetitionVerificationError(
            "historical A1.2d immutable-input inventory is invalid"
        )
    evidence_immutable = _rows(
        evidence.get("immutable_inputs"),
        "historical evidence immutable inputs",
    )
    evidence_identities = {
        (cast("str", item["path"]), cast("str", item["sha256"])) for item in evidence_immutable
    }
    packet_identities = {
        (cast("str", item["path"]), cast("str", item["sha256"])) for item in immutable
    }
    packet_only = {
        (_EVIDENCE_REL, _EVIDENCE_SHA256),
        (_SOURCE_REVIEW_REL, _SOURCE_REVIEW_SHA256),
    }
    if evidence_identities | packet_only != packet_identities:
        raise _ImplicitCompetitionVerificationError(
            "historical evidence membership differs from the A1.2d packet"
        )

    immutable_by_path = {cast("str", row["path"]): row for row in immutable}
    historical_paths = set(_SUCCESSOR_PATHS)
    historical_intersection = {
        path: row for path, row in immutable_by_path.items() if path in historical_paths
    }
    expected_opening = list(_HISTORICAL_OPENING_ROWS)
    if (
        set(historical_intersection) != historical_paths
        or historical_intersection != {row["path"]: row for row in expected_opening}
        or [historical_intersection[path] for path in _SUCCESSOR_PATHS] != expected_opening
        or _digest(expected_opening) != _HISTORICAL_OPENING_ROWS_SHA256
        or _digest(list(_SUCCESSOR_PATHS)) != _SUCCESSOR_PATHS_SHA256
    ):
        raise _ImplicitCompetitionVerificationError(
            "historical A1.2d successor membership is invalid"
        )

    checked_contracts = _dict(
        successor.get("checked_resource_contracts"),
        "successor checked-resource contracts",
    )
    supersession = _dict(
        checked_contracts.get("historical_supersession_contract"),
        "historical supersession contract",
    )
    if (
        supersession.get("current_paths_never_reinterpreted_as_historical_bytes") is not True
        or supersession.get("generic_or_implicit_fallback_permitted") is not False
        or supersession.get("implicit_checked_resource_mutation_permitted") is not False
        or supersession.get("implicit_current_semantic_projection_fields")
        != list(_SEMANTIC_PROJECTION_FIELDS)
        or supersession.get("implicit_supersession_proof_authority_depends_on_future_receipt")
        is not False
        or supersession.get("implicit_supersession_proof_public_output") is not False
    ):
        raise _ImplicitCompetitionVerificationError("successor supersession policy is not exact")
    reconciliations = _rows(
        supersession.get("successor_reconciliations"),
        "successor reconciliations",
    )
    matching = [row for row in reconciliations if row.get("historical_task_id") == "A1.2d"]
    expected_reconciliation = {
        "historical_task_id": "A1.2d",
        "historical_task_packet": {
            "path": _TASK_PACKET_REL,
            "sha256": _TASK_PACKET_SHA256,
        },
        "opening_rows": expected_opening,
        "opening_rows_sha256": _HISTORICAL_OPENING_ROWS_SHA256,
        "successor_path_count": 7,
        "successor_paths": list(_SUCCESSOR_PATHS),
        "successor_paths_sha256": _SUCCESSOR_PATHS_SHA256,
    }
    if matching != [expected_reconciliation]:
        raise _ImplicitCompetitionVerificationError("successor A1.2d reconciliation is not exact")
    historical_barriers = _rows(
        supersession.get("historical_barriers"),
        "historical barriers",
    )
    if {
        "path": _RESOURCE_REL,
        "sha256": _HISTORICAL_IMPLICIT_RESOURCE_SHA256,
    } not in historical_barriers:
        raise _ImplicitCompetitionVerificationError(
            "historical implicit resource is absent from the successor barriers"
        )


def _read_current_successor_rows() -> list[dict[str, str]]:
    observed: list[dict[str, str]] = []
    for expected in _CURRENT_SUCCESSOR_ROWS:
        relative = expected["path"]
        raw = _read_packaged_source(relative)
        observed.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    if (
        observed != list(_CURRENT_SUCCESSOR_ROWS)
        or _digest(observed) != _CURRENT_SUCCESSOR_ROWS_SHA256
    ):
        raise _ImplicitCompetitionVerificationError("current seven-row successor authority drifted")
    return observed


def _verify_named_subdigest(payload: dict[str, object], field: str) -> None:
    digest_field = f"{field}_sha256"
    if payload.get(digest_field) != _digest(payload.get(field)):
        raise _ImplicitCompetitionVerificationError(f"{digest_field} is invalid")


def _verify_authority_envelope(
    payload: dict[str, object],
    *,
    label: str,
    expected_authority: str,
    expected_payload: str,
    expected_canonicalization: str,
) -> None:
    canonicalization = _dict(payload.get("canonicalization"), f"{label} canonicalization")
    if (
        payload.get("canonicalization_sha256") != _digest(canonicalization)
        or payload.get("canonicalization_sha256") != expected_canonicalization
    ):
        raise _ImplicitCompetitionVerificationError(
            f"{label} canonicalization authority is invalid"
        )
    authority_fields = canonicalization.get("authority_sha256_fields")
    if (
        not isinstance(authority_fields, list)
        or not authority_fields
        or not all(isinstance(item, str) and item for item in authority_fields)
        or len(authority_fields) != len(set(authority_fields))
        or any(item not in payload for item in authority_fields)
    ):
        raise _ImplicitCompetitionVerificationError(f"{label} authority field list is invalid")
    projection = {field: payload[field] for field in cast("list[str]", authority_fields)}
    if payload.get("authority_sha256") != _digest(projection):
        raise _ImplicitCompetitionVerificationError(f"{label} authority digest is invalid")
    if payload.get("authority_sha256") != expected_authority:
        raise _ImplicitCompetitionVerificationError(f"{label} authority drifted")
    _verify_payload_digest(payload, label=label)
    if payload.get("payload_sha256") != expected_payload:
        raise _ImplicitCompetitionVerificationError(f"{label} payload drifted")


def _verify_sealed_evidence(payload: dict[str, object]) -> None:
    _verify_authority_envelope(
        payload,
        label="implicit root evidence",
        expected_authority=_EVIDENCE_AUTHORITY_SHA256,
        expected_payload=_EVIDENCE_PAYLOAD_SHA256,
        expected_canonicalization=_EVIDENCE_CANONICALIZATION_SHA256,
    )
    if (
        payload.get("schema") != "ImplicitCompetitionRootEvidenceV1"
        or type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != 1
        or payload.get("task_id") != "A1.2d"
        or payload.get("evidence_scope") != "offline_implicit_competition_root_source_input_only"
        or payload.get("network_used") is not False
        or payload.get("provider_probe_executed") is not False
        or payload.get("provider_availability_values") != ["unknown"]
        or payload.get("provider_availability_claim_count") != 0
        or payload.get("terminal_status_claim_count") != 0
        or payload.get("upstream_unavailable_claim_count") != 0
        or payload.get("model_green_asserted") is not False
        or payload.get("data_green_asserted") is not False
        or payload.get("global_completion_asserted") is not False
        or payload.get("live_operations_admissible") is not False
        or payload.get("publication_admissible") is not False
    ):
        raise _ImplicitCompetitionVerificationError(
            "implicit root evidence promotes an unobserved or downstream claim"
        )
    for field in (
        "alias_competition_cells",
        "competition_values",
        "complement_derivations",
        "excluded_inputs",
        "immutable_inputs",
        "implicit_alias_complement",
        "invalidation_triggers",
        "live_raw_root_evidence",
        "physical_competition_cells",
        "receipt_bound_root_policy",
        "repo_source_inventory",
        "retry_and_stop",
        "root_bindings",
        "source_authorities",
        "static_root_chains",
        "workspace_barrier",
    ):
        _verify_named_subdigest(payload, field)
    if payload.get("receipt_bound_root_policy_sha256") != _RECEIPT_POLICY_SHA256:
        raise _ImplicitCompetitionVerificationError("receipt-bound root policy drifted")
    counters = _dict(payload.get("false_green_counters"), "false-green counters")
    if not counters or any(type(value) is not int or value != 0 for value in counters.values()):
        raise _ImplicitCompetitionVerificationError("false-green counters are nonzero or invalid")
    expected_counts = {
        "alias_competition_cell_count": 180,
        "competition_count": 5,
        "immutable_input_count": 39,
        "physical_competition_cell_count": 180,
        "repo_source_file_count": 13,
        "root_binding_count": 36,
        "static_root_chain_count": 4,
    }
    for field, expected in expected_counts.items():
        _exact_int(payload.get(field), expected, field)
    census = _dict(payload.get("census"), "implicit census")
    required_census = {
        "alias_competition_cell_count": 180,
        "competition_count": 5,
        "dynamic_alias_count": 32,
        "dynamic_competition_cell_count": 160,
        "explicit_competition_alias_count": 126,
        "fixed_static_competition_cell_count": 4,
        "game_root_alias_count": 30,
        "implicit_alias_count": 36,
        "implicit_live_alias_count": 4,
        "implicit_physical_endpoint_count": 36,
        "implicit_repo_source_file_count": 13,
        "implicit_static_alias_count": 4,
        "implicit_stats_alias_count": 28,
        "package_physical_endpoint_count": 147,
        "package_registered_alias_count": 162,
        "parameter_root_alias_count": 30,
        "physical_competition_cell_count": 180,
        "player_root_alias_count": 1,
        "request_game_root_alias_count": 28,
        "response_game_collection_root_alias_count": 1,
        "response_game_join_root_alias_count": 1,
        "root_not_exposed_competition_cell_count": 16,
        "static_root_alias_count": 4,
        "team_root_alias_count": 1,
    }
    if census != required_census:
        raise _ImplicitCompetitionVerificationError("implicit census is not exact")

    bindings = _rows(payload.get("root_bindings"), "root bindings")
    if len(bindings) != 36:
        raise _ImplicitCompetitionVerificationError("root-binding denominator is invalid")
    for row in bindings:
        if set(row) != _ENDPOINT_BINDING_KEYS:
            raise _ImplicitCompetitionVerificationError("root-binding field set is invalid")
        body = dict(row)
        supplied = body.pop("binding_sha256", None)
        if _require_digest(supplied, "binding_sha256") != _digest(body):
            raise _ImplicitCompetitionVerificationError("root-binding digest is invalid")
    binding_ids = tuple(str(row["binding_sha256"]) for row in bindings)
    alias_ids = tuple(str(row["repo_endpoint_name"]) for row in bindings)
    physical_ids = tuple(str(row["physical_endpoint_key"]) for row in bindings)
    if (
        alias_ids != tuple(sorted(alias_ids))
        or len(set(alias_ids)) != 36
        or len(set(physical_ids)) != 36
        or len(set(binding_ids)) != 36
    ):
        raise _ImplicitCompetitionVerificationError("root bindings are not sorted and unique")

    aliases = _rows(payload.get("implicit_alias_complement"), "implicit alias complement")
    if (
        len(aliases) != 36
        or any(set(row) != _ALIAS_BINDING_KEYS for row in aliases)
        or tuple(str(row["repo_endpoint_name"]) for row in aliases)
        != tuple(sorted(str(row["repo_endpoint_name"]) for row in aliases))
        or len({str(row["repo_endpoint_name"]) for row in aliases}) != 36
    ):
        raise _ImplicitCompetitionVerificationError("implicit alias complement is invalid")

    physical_cells = _rows(payload.get("physical_competition_cells"), "physical cells")
    alias_cells = _rows(payload.get("alias_competition_cells"), "alias cells")
    if (
        len(physical_cells) != 180
        or len(alias_cells) != 180
        or any(set(row) != _PHYSICAL_CELL_KEYS for row in physical_cells)
        or any(set(row) != _ALIAS_CELL_KEYS for row in alias_cells)
        or len({str(row["cell_id"]) for row in physical_cells}) != 180
        or len({str(row["cell_id"]) for row in alias_cells}) != 180
    ):
        raise _ImplicitCompetitionVerificationError("implicit competition cells are invalid")
    for row in [*physical_cells, *alias_cells]:
        if (
            row.get("endpoint_support_status") != "unknown"
            or row.get("provider_availability_status") != "unknown"
            or row.get("provider_probe_executed") is not False
            or row.get("request_terminal_state") != "not_asserted"
        ):
            raise _ImplicitCompetitionVerificationError(
                "implicit competition cell promotes availability or terminal state"
            )

    immutable = _rows(payload.get("immutable_inputs"), "immutable inputs")
    if (
        len(immutable) != 39
        or payload.get("immutable_inputs_sha256") != _HISTORICAL_EVIDENCE_IMMUTABLES_SHA256
        or _digest(immutable) != _HISTORICAL_EVIDENCE_IMMUTABLES_SHA256
        or any(
            set(item) != {"authority_role", "path", "sha256", "size"}
            or type(item.get("authority_role")) is not str
            or not item.get("authority_role")
            or type(item.get("path")) is not str
            or not item.get("path")
            or type(item.get("sha256")) is not str
            or _SHA256_RE.fullmatch(cast("str", item.get("sha256"))) is None
            or type(item.get("size")) is not int
            or cast("int", item.get("size")) <= 0
            for item in immutable
        )
        or len({cast("str", item["path"]) for item in immutable}) != 39
    ):
        raise _ImplicitCompetitionVerificationError(
            "historical immutable-input inventory is malformed"
        )


def _verify_source_review(payload: dict[str, object], evidence_raw: bytes) -> None:
    _verify_authority_envelope(
        payload,
        label="implicit root source review",
        expected_authority=_SOURCE_REVIEW_AUTHORITY_SHA256,
        expected_payload=_SOURCE_REVIEW_PAYLOAD_SHA256,
        expected_canonicalization=_SOURCE_REVIEW_CANONICALIZATION_SHA256,
    )
    if (
        payload.get("schema") != "IndependentSourceReviewV1"
        or payload.get("task_id") != "A1.2d-source-inputs"
        or payload.get("review_id") != "A1.2d/source-input-admission"
        or payload.get("disposition") != "pass"
        or payload.get("findings") != []
        or payload.get("network_used") is not False
        or payload.get("model_green_asserted") is not False
        or payload.get("data_green_asserted") is not False
        or payload.get("global_completion_asserted") is not False
        or payload.get("live_operations_admissible") is not False
        or payload.get("publication_admissible") is not False
    ):
        raise _ImplicitCompetitionVerificationError(
            "implicit source review is not a finding-free offline admission"
        )
    reviewed = _rows(payload.get("reviewed_inputs"), "source review inputs")
    expected = {
        "authority_sha256": _EVIDENCE_AUTHORITY_SHA256,
        "canonicalization_sha256": _EVIDENCE_CANONICALIZATION_SHA256,
        "network_used_by_issuer": False,
        "path": _EVIDENCE_REL,
        "payload_sha256": _EVIDENCE_PAYLOAD_SHA256,
        "receipt_bound_root_policy_sha256": _RECEIPT_POLICY_SHA256,
        "schema": "ImplicitCompetitionRootEvidenceV1",
        "sha256": hashlib.sha256(evidence_raw).hexdigest(),
    }
    if reviewed != [expected]:
        raise _ImplicitCompetitionVerificationError(
            "implicit source review does not bind the exact evidence input"
        )


def _load_predecessor_resources() -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for name, expected_hash in _CURRENT_PREDECESSOR_RESOURCE_HASHES.items():
        try:
            raw = resources.files("nbadb.contracts").joinpath(name).read_bytes()
        except (AttributeError, OSError) as exc:
            raise _ImplicitCompetitionVerificationError(
                f"checked predecessor resource cannot be read: {name}"
            ) from exc
        if hashlib.sha256(raw).hexdigest() != expected_hash:
            raise _ImplicitCompetitionVerificationError(
                f"checked predecessor resource drifted: {name}"
            )
        payload = _parse(raw, label=name, pretty=False)
        _verify_payload_digest(payload, label=name)
        result[name] = payload
    return result


def _safe_record_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.parts[0] not in {"nba_api", f"nba_api-{_VERSION}.dist-info"}
    ):
        raise _ImplicitCompetitionVerificationError("installed RECORD has an unsafe path")
    return path


def _read_regular(root: Path, relative: PurePosixPath) -> bytes:
    candidate = root.joinpath(*relative.parts)
    try:
        metadata = candidate.stat(follow_symlinks=False)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        if candidate.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise _ImplicitCompetitionVerificationError(
                "installed RECORD member is not a regular file"
            )
        return candidate.read_bytes()
    except _ImplicitCompetitionVerificationError:
        raise
    except (OSError, ValueError) as exc:
        raise _ImplicitCompetitionVerificationError(
            "installed RECORD member cannot be read safely"
        ) from exc


def _distribution_authority() -> tuple[
    importlib.metadata.Distribution,
    Path,
    dict[str, dict[str, object]],
    dict[str, object],
]:
    try:
        distribution = importlib.metadata.distribution(_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError as exc:
        raise _ImplicitCompetitionVerificationError(
            "pinned nba-api distribution is not installed"
        ) from exc
    if distribution.version != _VERSION or distribution.files is None:
        raise _ImplicitCompetitionVerificationError("installed nba-api pin is invalid")
    paths = tuple(str(path) for path in distribution.files)
    record_paths = tuple(path for path in paths if path.endswith(".dist-info/RECORD"))
    if len(record_paths) != 1 or list(paths) != sorted(set(paths)):
        raise _ImplicitCompetitionVerificationError("installed RECORD inventory is invalid")
    root = Path(str(distribution.locate_file(""))).resolve(strict=True)
    record_path = _safe_record_path(record_paths[0])
    record_raw = _read_regular(root, record_path)
    try:
        rows = list(
            csv.reader(
                io.StringIO(record_raw.decode("utf-8", errors="strict"), newline=""),
                strict=True,
            )
        )
    except (UnicodeDecodeError, csv.Error) as exc:
        raise _ImplicitCompetitionVerificationError("installed RECORD cannot be decoded") from exc
    if not rows or any(len(row) != 3 for row in rows):
        raise _ImplicitCompetitionVerificationError("installed RECORD rows are malformed")
    entries: list[dict[str, object]] = []
    by_path: dict[str, dict[str, object]] = {}
    for raw_path, record_hash, record_size in rows:
        relative = _safe_record_path(raw_path)
        raw = _read_regular(root, relative)
        observed = hashlib.sha256(raw).digest()
        observed_hex = observed.hex()
        if record_hash:
            if not record_hash.startswith("sha256="):
                raise _ImplicitCompetitionVerificationError(
                    "installed RECORD hash algorithm is invalid"
                )
            encoded = record_hash.removeprefix("sha256=")
            try:
                decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            except (TypeError, ValueError) as exc:
                raise _ImplicitCompetitionVerificationError(
                    "installed RECORD hash is malformed"
                ) from exc
            if (
                decoded != observed
                or base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != encoded
                or record_size != str(len(raw))
            ):
                raise _ImplicitCompetitionVerificationError(
                    "installed RECORD file differs from its receipt"
                )
            recorded_size: int | None = len(raw)
        else:
            if relative != record_path or record_size:
                raise _ImplicitCompetitionVerificationError(
                    "only installed RECORD may omit its own receipt"
                )
            recorded_size = None
        entry: dict[str, object] = {
            "path": raw_path,
            "record_hash": record_hash or None,
            "record_size": recorded_size,
            "sha256": observed_hex,
            "size": len(raw),
        }
        entries.append(entry)
        by_path[raw_path] = entry
    if [str(row["path"]) for row in entries] != list(paths):
        raise _ImplicitCompetitionVerificationError("installed RECORD paths are incomplete")
    body: dict[str, object] = {
        "schema_version": 1,
        "kind": "nbadb_nba_api_distribution_record_authority",
        "distribution_name": _DISTRIBUTION,
        "distribution_version": _VERSION,
        "entry_count": len(entries),
        "hashed_entry_count": sum(row["record_hash"] is not None for row in entries),
        "unhashed_paths": [str(row["path"]) for row in entries if row["record_hash"] is None],
        "record_sha256": hashlib.sha256(record_raw).hexdigest(),
        "entries": entries,
        "entries_sha256": _digest(entries),
    }
    authority = {**body, "authority_sha256": _digest(body)}
    if (
        len(entries) != 195
        or authority["hashed_entry_count"] != 194
        or authority["unhashed_paths"] != [record_path.as_posix()]
        or authority["record_sha256"] != _DISTRIBUTION_RECORD_SHA256
        or authority["entries_sha256"] != _DISTRIBUTION_ENTRIES_SHA256
        or authority["authority_sha256"] != _DISTRIBUTION_RECORD_AUTHORITY_SHA256
    ):
        raise _ImplicitCompetitionVerificationError(
            "installed RECORD differs from the pinned authority"
        )
    return distribution, root, by_path, authority


def _distribution_summary(authority: dict[str, object]) -> dict[str, object]:
    return {
        key: deepcopy(authority[key])
        for key in (
            "authority_sha256",
            "distribution_name",
            "distribution_version",
            "entries_sha256",
            "entry_count",
            "hashed_entry_count",
            "kind",
            "record_sha256",
            "schema_version",
            "unhashed_paths",
        )
    }


def _provider_entry(
    root: Path,
    record: dict[str, dict[str, object]],
    path: str,
) -> tuple[bytes, str, int]:
    entry = record.get(path)
    if entry is None:
        raise _ImplicitCompetitionVerificationError(
            f"provider source is absent from installed RECORD: {path}"
        )
    raw = _read_regular(root, _safe_record_path(path))
    digest = hashlib.sha256(raw).hexdigest()
    if entry.get("sha256") != digest or entry.get("size") != len(raw):
        raise _ImplicitCompetitionVerificationError(
            f"provider source differs from installed RECORD: {path}"
        )
    return raw, digest, len(raw)


def _registered_classes() -> dict[str, type[object]]:
    from nbadb.extract.registry import registry

    registry.discover()
    classes = {str(item.endpoint_name): item for item in registry.get_all()}
    if len(classes) != 162 or tuple(sorted(classes)) != tuple(
        sorted(str(item.endpoint_name) for item in registry.get_all())
    ):
        raise _ImplicitCompetitionVerificationError(
            "runtime extractor registry is not the exact 162-alias inventory"
        )
    return cast("dict[str, type[object]]", classes)


def _class_node(tree: ast.Module, name: str, *, path: str) -> ast.ClassDef:
    matches = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name]
    if len(matches) != 1:
        raise _ImplicitCompetitionVerificationError(
            f"extractor source has ambiguous class {name}: {path}"
        )
    node = matches[0]
    if not any(
        isinstance(decorator, ast.Attribute)
        and isinstance(decorator.value, ast.Name)
        and decorator.value.id == "registry"
        and decorator.attr == "register"
        for decorator in node.decorator_list
    ):
        raise _ImplicitCompetitionVerificationError(
            f"extractor class lacks registry binding: {name}"
        )
    return node


def _class_endpoint_name(node: ast.ClassDef) -> str:
    values: list[str] = []
    for child in node.body:
        if not isinstance(child, (ast.Assign, ast.AnnAssign)):
            continue
        targets = child.targets if isinstance(child, ast.Assign) else [child.target]
        if any(isinstance(target, ast.Name) and target.id == "endpoint_name" for target in targets):
            if child.value is None:
                continue
            value = ast.literal_eval(child.value)
            if isinstance(value, str):
                values.append(value)
    if len(values) != 1:
        raise _ImplicitCompetitionVerificationError("extractor endpoint_name is not exact")
    return values[0]


def _provider_calls(node: ast.ClassDef) -> tuple[tuple[str, tuple[str | None, ...]], ...]:
    output: list[tuple[str, tuple[str | None, ...]]] = []
    allowed = {
        "_call_nba_api",
        "_from_nba_api",
        "_from_nba_api_multi",
        "_from_nba_live",
        "_from_nba_live_multi",
    }
    for child in ast.walk(node):
        if not isinstance(child, ast.Call) or not isinstance(child.func, ast.Attribute):
            continue
        if child.func.attr not in allowed or not child.args:
            continue
        provider = child.args[0].id if isinstance(child.args[0], ast.Name) else None
        output.append((str(provider), tuple(keyword.arg for keyword in child.keywords)))
    return tuple(output)


def _params_keys(node: ast.ClassDef) -> set[str]:
    values: set[str] = set()
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Subscript)
            and isinstance(child.value, ast.Name)
            and child.value.id == "params"
            and isinstance(child.slice, ast.Constant)
            and isinstance(child.slice.value, str)
        ):
            values.add(child.slice.value)
    return values


def _verify_extractor_ast(
    binding: dict[str, object],
    tree: ast.Module,
    *,
    path: str,
) -> None:
    qualname = str(binding["extractor_qualname"])
    node = _class_node(tree, qualname, path=path)
    alias = str(binding["repo_endpoint_name"])
    if _class_endpoint_name(node) != alias:
        raise _ImplicitCompetitionVerificationError("extractor alias differs from source AST")
    mode = binding["root_mode"]
    provider = str(binding["provider_endpoint_id"])
    if mode == "embedded_static_dataset":
        calls = [
            child
            for child in ast.walk(node)
            if isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "fetch_static_packet"
            and child.args
        ]
        if len(calls) != 1 or ast.literal_eval(calls[0].args[0]) != provider:
            raise _ImplicitCompetitionVerificationError(
                "static extractor dataset binding differs from source AST"
            )
        return
    calls = _provider_calls(node)
    if not calls or any(call[0] != provider for call in calls):
        raise _ImplicitCompetitionVerificationError(
            "dynamic extractor provider binding differs from source AST"
        )
    if mode == "request_parameter":
        root_evidence = _dict(binding["root_evidence"], "root evidence")
        parameter = _dict(root_evidence.get("parameter"), "root parameter")
        name = str(parameter["name"])
        direct_forward = name in _params_keys(node) and any(
            name in keywords for _, keywords in calls
        )
        kwargs_forward = binding.get("source_family") == "live" and any(
            None in keywords for _, keywords in calls
        )
        if not (direct_forward or kwargs_forward):
            raise _ImplicitCompetitionVerificationError(
                "dynamic root is not forwarded from the exact extractor parameter"
            )


def _validate_historical_predecessor_authorities(
    evidence: dict[str, object],
    distribution: dict[str, object],
) -> dict[str, object]:
    authorities = _dict(evidence.get("source_authorities"), "source authorities")
    if _digest(authorities) != _HISTORICAL_SOURCE_AUTHORITIES_SHA256 or authorities.get(
        "distribution_record"
    ) != _distribution_summary(distribution):
        raise _ImplicitCompetitionVerificationError(
            "sealed historical predecessor authorities are invalid"
        )
    return authorities


def _validate_current_predecessor_authorities(
    resources_by_name: dict[str, dict[str, object]],
    historical: dict[str, object],
) -> None:
    competition = resources_by_name["nba_api_competition_v1_11_4.json"]
    occurrences = resources_by_name["nba_api_competition_occurrences_v1_11_4.json"]
    request = resources_by_name["nba_api_request_surface_v1_11_4.json"]
    runtime = resources_by_name["nba_api_runtime_contract_v1_11_4.json"]
    applicability = resources_by_name["nba_api_competition_applicability_v1_11_4.json"]
    current_competition = {
        "authority_sha256": competition.get("authority_sha256"),
        "competition_count": competition.get("competition_count"),
        "competition_values_sha256": competition.get("competition_values_sha256"),
        "payload_sha256": competition.get("payload_sha256"),
    }
    current_runtime = {
        "contracts_sha256": runtime.get("contracts_sha256"),
        "live_contracts_sha256": runtime.get("live_contracts_sha256"),
        "payload_sha256": runtime.get("payload_sha256"),
        "schema_version": runtime.get("schema_version"),
        "static_contracts_sha256": runtime.get("static_contracts_sha256"),
    }
    current_request = {
        "manifest_sha256": request.get("manifest_sha256"),
        "parameter_occurrences_sha256": request.get("parameter_occurrences_sha256"),
        "payload_sha256": request.get("payload_sha256"),
        "resource_sha256": _CURRENT_PREDECESSOR_RESOURCE_HASHES[
            "nba_api_request_surface_v1_11_4.json"
        ],
        "schema_version": request.get("schema_version"),
        "surface_sha256": request.get("surface_sha256"),
    }
    current_occurrences = {
        "authority_sha256": occurrences.get("authority_sha256"),
        "package_endpoint_count": occurrences.get("package_endpoint_count"),
        "package_occurrence_count": occurrences.get("package_occurrence_count"),
        "payload_sha256": occurrences.get("payload_sha256"),
        "repo_alias_count": occurrences.get("repo_alias_count"),
        "repo_aliases_sha256": occurrences.get("repo_aliases_sha256"),
        "resource_sha256": _CURRENT_PREDECESSOR_RESOURCE_HASHES[
            "nba_api_competition_occurrences_v1_11_4.json"
        ],
        "schema_version": occurrences.get("schema_version"),
        "upstream_request_surface": occurrences.get("upstream_request_surface"),
    }
    applicability_sources = _dict(
        applicability.get("source_authorities"),
        "current applicability source authorities",
    )
    current_applicability = {
        "alias_role_competition_cell_count": applicability.get("alias_role_competition_cell_count"),
        "authority_sha256": applicability.get("authority_sha256"),
        "endpoint_competition_cell_count": applicability.get("endpoint_competition_cell_count"),
        "parameter_axis_competition_cell_count": applicability.get(
            "parameter_axis_competition_cell_count"
        ),
        "payload_sha256": applicability.get("payload_sha256"),
        "resource_sha256": _CURRENT_PREDECESSOR_RESOURCE_HASHES[
            "nba_api_competition_applicability_v1_11_4.json"
        ],
        "schema_version": applicability.get("schema_version"),
        "source_authorities": {
            "competition_occurrences": applicability_sources.get("competition_occurrences"),
            "request_surface": applicability_sources.get("request_surface"),
        },
        "typed_declared_axis_cell_count": applicability.get("typed_declared_axis_cell_count"),
    }
    if (
        current_competition != historical.get("competition_values")
        or current_runtime != _CURRENT_RUNTIME_IDENTITY
        or current_request != _CURRENT_REQUEST_IDENTITY
        or current_occurrences != _CURRENT_OCCURRENCE_IDENTITY
        or current_applicability != _CURRENT_APPLICABILITY_IDENTITY
    ):
        raise _ImplicitCompetitionVerificationError(
            "current predecessor authorities differ from the exact successor identities"
        )


def _runtime_contract_digest(family: str, contract: dict[str, object]) -> str:
    if family == "stats":
        return _digest(contract)
    body = dict(contract)
    supplied = body.pop("contract_sha256", None)
    if _require_digest(supplied, "runtime contract digest") != _digest(body):
        raise _ImplicitCompetitionVerificationError("runtime contract digest is invalid")
    return cast("str", supplied)


def _request_parameter_projection(row: dict[str, object]) -> dict[str, object]:
    if set(_ROOT_PARAMETER_KEYS) - set(row):
        raise _ImplicitCompetitionVerificationError("request root occurrence is incomplete")
    return {key: deepcopy(row[key]) for key in _ROOT_PARAMETER_KEYS}


def _verify_live_raw_evidence(
    evidence: dict[str, object],
    runtime: dict[str, object],
    provider_sources: dict[str, bytes],
    repo_trees: dict[str, ast.Module],
) -> None:
    rows = _rows(evidence.get("live_raw_root_evidence"), "live raw-root evidence")
    if len(rows) != 2 or {row.get("provider_endpoint_id") for row in rows} != {
        "Odds",
        "ScoreBoard",
    }:
        raise _ImplicitCompetitionVerificationError("live raw-root inventory is invalid")
    contracts = _dict(runtime.get("live_contracts"), "live contracts")
    by_endpoint = {str(row["provider_endpoint_id"]): row for row in rows}
    for endpoint, row in by_endpoint.items():
        contract = _dict(contracts.get(endpoint), f"{endpoint} live contract")
        if row.get("endpoint_contract_sha256") != _runtime_contract_digest("live", contract):
            raise _ImplicitCompetitionVerificationError("live root contract digest drifted")
        result_sets = _rows(contract.get("result_sets"), f"{endpoint} result sets")
        for name_field, path_field, digest_field in (
            ("result_set_name", "result_set_json_path", "result_set_fields_sha256"),
            (
                "games_result_set_name",
                "games_result_set_json_path",
                "games_result_set_fields_sha256",
            ),
            (
                "league_result_set_name",
                "league_result_set_json_path",
                "league_result_set_fields_sha256",
            ),
        ):
            if name_field not in row:
                continue
            matches = [
                item
                for item in result_sets
                if item.get("name") == row[name_field] and item.get("json_path") == row[path_field]
            ]
            if len(matches) != 1 or matches[0].get("fields_sha256") != row[digest_field]:
                raise _ImplicitCompetitionVerificationError("live result-set authority drifted")
        field_specs = (
            ("game_id_json_path", "game_id_field_evidence_sha256"),
            ("league_id_json_path", "league_id_field_evidence_sha256"),
        )
        all_fields = [
            field for result_set in result_sets for field in _rows(result_set["fields"], "fields")
        ]
        for path_field, digest_field in field_specs:
            if path_field not in row:
                continue
            matches = [field for field in all_fields if field.get("json_path") == row[path_field]]
            if len(matches) != 1 or _digest(matches[0]) != row[digest_field]:
                raise _ImplicitCompetitionVerificationError("live raw field evidence drifted")
        source_path = str(row["provider_source_path"])
        source = provider_sources.get(source_path)
        if source is None:
            raise _ImplicitCompetitionVerificationError("live provider source is unbound")
        tree = ast.parse(source.decode("utf-8", errors="strict"), filename=source_path)
        classes = [
            node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == endpoint
        ]
        if len(classes) != 1:
            raise _ImplicitCompetitionVerificationError("live provider class is ambiguous")
        expected_data: object | None = None
        for child in classes[0].body:
            if isinstance(child, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "expected_data"
                for target in child.targets
            ):
                expected_data = ast.literal_eval(child.value)
        if not isinstance(expected_data, dict):
            raise _ImplicitCompetitionVerificationError("live expected_data is absent")
        if endpoint == "Odds":
            games = expected_data.get("games")
            valid = (
                isinstance(games, list)
                and bool(games)
                and isinstance(games[0], dict)
                and "gameId" in games[0]
                and row.get("game_id_json_path") == "$.games.gameId"
                and row.get("per_game_receipt_join_required") is True
                and row.get("request_level_competition_assignment_permitted") is False
            )
        else:
            scoreboard = expected_data.get("scoreboard")
            games = scoreboard.get("games") if isinstance(scoreboard, dict) else None
            valid = (
                isinstance(scoreboard, dict)
                and "leagueId" in scoreboard
                and isinstance(games, list)
                and bool(games)
                and isinstance(games[0], dict)
                and "gameId" in games[0]
                and row.get("league_id_json_path") == "$.scoreboard.leagueId"
                and row.get("game_id_json_path") == "$.scoreboard.games.gameId"
                and row.get("raw_parser_input_required") is True
                and row.get("league_and_game_receipt_agreement_required") is True
            )
            repo_tree = repo_trees[str(row["repo_source_endpoint"])]
            strings = {
                child.value
                for child in ast.walk(repo_tree)
                if isinstance(child, ast.Constant) and isinstance(child.value, str)
            }
            valid = valid and "$.scoreboard.leagueId" in strings
        if not valid or row.get("typed_projection_sufficient_for_competition") is not False:
            raise _ImplicitCompetitionVerificationError("live root semantics are invalid")


def _data_symbols(source: bytes, path: str) -> dict[str, list[object]]:
    try:
        tree = ast.parse(source.decode("utf-8", errors="strict"), filename=path)
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise _ImplicitCompetitionVerificationError("static data source cannot be parsed") from exc
    output: dict[str, list[object]] = {}
    required = {assignment[1] for assignment in _STATIC_ASSIGNMENTS.values()}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in required:
            continue
        value = ast.literal_eval(node.value)
        if not isinstance(value, list):
            raise _ImplicitCompetitionVerificationError("static source rows are not a list")
        output[target.id] = cast("list[object]", value)
    if set(output) != required:
        raise _ImplicitCompetitionVerificationError("static data symbols are incomplete")
    return output


def _verify_static_chains(
    evidence: dict[str, object],
    runtime: dict[str, object],
    root: Path,
    record: dict[str, dict[str, object]],
) -> None:
    chains = _rows(evidence.get("static_root_chains"), "static root chains")
    if len(chains) != 4:
        raise _ImplicitCompetitionVerificationError("static root-chain denominator is invalid")
    runtime_contracts = _dict(runtime.get("static_contracts"), "static contracts")
    data_paths = {str(row["data_source_path"]) for row in chains}
    if len(data_paths) != 1:
        raise _ImplicitCompetitionVerificationError("static data source is ambiguous")
    data_path = next(iter(data_paths))
    data_raw, data_sha256, _ = _provider_entry(root, record, data_path)
    symbols = _data_symbols(data_raw, data_path)
    for chain in chains:
        body = dict(chain)
        supplied = body.pop("chain_sha256", None)
        if _require_digest(supplied, "static chain_sha256") != _digest(body):
            raise _ImplicitCompetitionVerificationError("static chain digest is invalid")
        dataset = str(chain["dataset_id"])
        assignment = _STATIC_ASSIGNMENTS.get(dataset)
        contract = _dict(runtime_contracts.get(dataset), f"{dataset} static contract")
        if assignment is None:
            raise _ImplicitCompetitionVerificationError("foreign static dataset root")
        getter, symbol, league_id, competition_symbol = assignment
        rows = symbols[symbol]
        ids = [
            row[0] for row in rows if isinstance(row, list) and row and not isinstance(row[0], bool)
        ]
        source_path = str(chain["provider_source_path"])
        provider_raw, provider_sha256, _ = _provider_entry(root, record, source_path)
        provider_tree = ast.parse(
            provider_raw.decode("utf-8", errors="strict"), filename=source_path
        )
        getters = [
            node
            for node in provider_tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == getter
        ]
        if len(getters) != 1:
            raise _ImplicitCompetitionVerificationError("static getter is absent or ambiguous")
        getter_text = ast.unparse(getters[0])
        expected_call = "_get_players" if "players" in dataset else "_get_teams"
        if expected_call not in getter_text or (
            symbol.startswith("wnba_") and symbol not in getter_text
        ):
            raise _ImplicitCompetitionVerificationError("static getter/source-symbol chain drifted")
        expected_fields = {
            "data_source_path": data_path,
            "data_source_sha256": data_sha256,
            "dataset_id": dataset,
            "fixed_league_id": league_id,
            "fixed_symbol": competition_symbol,
            "getter_name": getter,
            "provider_default_used": False,
            "provider_module": contract.get("provider_module"),
            "provider_source_path": source_path,
            "provider_source_sha256": provider_sha256,
            "row_count": len(rows),
            "runtime_contract_sha256": _runtime_contract_digest("static", contract),
            "runtime_static_contracts_sha256": runtime.get("static_contracts_sha256"),
            "source_rows_sha256": _digest(rows),
            "source_symbol": symbol,
            "unique_id_count": len(set(ids)),
        }
        if any(chain.get(field) != value for field, value in expected_fields.items()):
            raise _ImplicitCompetitionVerificationError("static root chain differs from sources")


def _derive_bindings_and_cells(
    evidence: dict[str, object],
    resources_by_name: dict[str, dict[str, object]],
    distribution_root: Path,
    record: dict[str, dict[str, object]],
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    competition = resources_by_name["nba_api_competition_v1_11_4.json"]
    occurrences = resources_by_name["nba_api_competition_occurrences_v1_11_4.json"]
    request = resources_by_name["nba_api_request_surface_v1_11_4.json"]
    runtime = resources_by_name["nba_api_runtime_contract_v1_11_4.json"]
    competition_rows = _rows(competition.get("competitions"), "competition values")
    expected_competitions = [
        {"league_id": league_id, "symbol": symbol} for league_id, symbol in _COMPETITIONS
    ]
    if (
        competition_rows != expected_competitions
        or evidence.get("competition_values") != expected_competitions
    ):
        raise _ImplicitCompetitionVerificationError("competition finite values are not exact")

    stats_contracts = _dict(runtime.get("contracts"), "stats contracts")
    live_contracts = _dict(runtime.get("live_contracts"), "live contracts")
    static_contracts = _dict(runtime.get("static_contracts"), "static contracts")
    physical_universe = {
        *(f"stats:{name}" for name in stats_contracts),
        *(f"live:{name}" for name in live_contracts),
        *(f"static:{name}" for name in static_contracts),
    }
    package_occurrences = _rows(occurrences.get("package_occurrences"), "package occurrences")
    explicit_physical = {f"stats:{row['provider_endpoint_id']}" for row in package_occurrences}
    repo_aliases = _rows(occurrences.get("repo_aliases"), "explicit repo aliases")
    explicit_aliases = {str(row["repo_endpoint_name"]) for row in repo_aliases}
    if (
        len(stats_contracts) != 139
        or len(live_contracts) != 4
        or len(static_contracts) != 4
        or len(physical_universe) != 147
        or len(explicit_physical) != 111
        or len(explicit_aliases) != 126
        or not explicit_physical <= physical_universe
    ):
        raise _ImplicitCompetitionVerificationError(
            "checked physical or explicit partition denominator is invalid"
        )
    implicit_physical = physical_universe - explicit_physical

    classes = _registered_classes()
    implicit_aliases = set(classes) - explicit_aliases
    if (
        len(classes) != 162
        or explicit_aliases & implicit_aliases
        or len(implicit_aliases) != 36
        or len(implicit_physical) != 36
    ):
        raise _ImplicitCompetitionVerificationError(
            "registry explicit/implicit partition is not exact"
        )

    request_rows = _rows(request.get("parameter_occurrences"), "request occurrences")
    request_by_id = {str(row["occurrence_id"]): row for row in request_rows}
    league_axes_by_endpoint: dict[str, list[str]] = {}
    for row in request_rows:
        if row.get("domain_kind") == "league_scope":
            league_axes_by_endpoint.setdefault(str(row["endpoint_id"]), []).append(
                str(row["occurrence_id"])
            )

    source_inventory = _rows(evidence.get("repo_source_inventory"), "repo source inventory")
    if len(source_inventory) != 13 or any(
        set(row) != {"path", "sha256", "size"}
        or type(row.get("path")) is not str
        or not row.get("path")
        or type(row.get("size")) is not int
        or cast("int", row.get("size")) <= 0
        for row in source_inventory
    ):
        raise _ImplicitCompetitionVerificationError(
            "historical extractor source inventory is not exact"
        )
    for row in source_inventory:
        _require_digest(row.get("sha256"), "historical extractor source sha256")
    historical_paths = tuple(cast("str", row["path"]) for row in source_inventory)
    if len(set(historical_paths)) != len(historical_paths):
        raise _ImplicitCompetitionVerificationError(
            "historical extractor source paths are not unique"
        )
    current_source_inventory = _current_source_inventory(
        historical_paths=historical_paths,
    )
    source_rows_by_path = {cast("str", row["path"]): row for row in source_inventory}
    current_source_rows_by_path = {
        cast("str", row["path"]): row for row in current_source_inventory
    }
    repo_trees_by_path: dict[str, ast.Module] = {}
    for path, row in current_source_rows_by_path.items():
        raw = _read_packaged_source(path)
        if row.get("sha256") != hashlib.sha256(raw).hexdigest() or row.get("byte_count") != len(
            raw
        ):
            raise _ImplicitCompetitionVerificationError(f"current extractor source drifted: {path}")
        try:
            repo_trees_by_path[path] = ast.parse(raw.decode("utf-8"), filename=path)
        except (UnicodeDecodeError, SyntaxError) as exc:
            raise _ImplicitCompetitionVerificationError(
                f"extractor source cannot be parsed: {path}"
            ) from exc
    if len(repo_trees_by_path) != 13:
        raise _ImplicitCompetitionVerificationError("extractor source inventory is not exact")

    sealed_bindings = _rows(evidence.get("root_bindings"), "root bindings")
    provider_sources: dict[str, bytes] = {}
    derived_bindings: list[dict[str, object]] = []
    for sealed in sealed_bindings:
        alias = str(sealed["repo_endpoint_name"])
        family = str(sealed["source_family"])
        provider = str(sealed["provider_endpoint_id"])
        physical = f"{family}:{provider}"
        if alias not in implicit_aliases or physical not in implicit_physical:
            raise _ImplicitCompetitionVerificationError(
                "sealed root binding is outside the independently derived complement"
            )
        extractor_cls = classes[alias]
        if (
            extractor_cls.__module__ != sealed.get("extractor_module")
            or extractor_cls.__qualname__ != sealed.get("extractor_qualname")
            or getattr(extractor_cls, "endpoint_name", None) != alias
        ):
            raise _ImplicitCompetitionVerificationError(
                "runtime registry class identity differs from root binding"
            )
        repo_path = str(sealed["repo_source_path"])
        repo_row = source_rows_by_path.get(repo_path)
        if repo_row is None or (
            sealed.get("repo_source_sha256") != repo_row.get("sha256")
            or sealed.get("repo_source_size") != repo_row.get("size")
        ):
            raise _ImplicitCompetitionVerificationError(
                "root binding differs from extractor source inventory"
            )
        module_path = "src/" + str(sealed["extractor_module"]).replace(".", "/") + ".py"
        if module_path != repo_path:
            raise _ImplicitCompetitionVerificationError("extractor module/path binding is invalid")
        _verify_extractor_ast(sealed, repo_trees_by_path[repo_path], path=repo_path)

        if family == "stats":
            contract = _dict(stats_contracts.get(provider), f"{provider} stats contract")
            source_path = str(contract.get("module_name", "")).replace(".", "/") + ".py"
        elif family == "live":
            contract = _dict(live_contracts.get(provider), f"{provider} live contract")
            source_path = str(contract.get("source_path"))
        elif family == "static":
            contract = _dict(static_contracts.get(provider), f"{provider} static contract")
            source_path = str(contract.get("provider_source_path"))
        else:
            raise _ImplicitCompetitionVerificationError("root source family is foreign")
        provider_raw, provider_sha256, provider_size = _provider_entry(
            distribution_root, record, source_path
        )
        provider_sources[source_path] = provider_raw
        _require_digest(
            sealed.get("provider_contract_sha256"),
            "sealed historical provider contract sha256",
        )
        # The sealed root evidence binds the historical contract serializer,
        # while source bytes and the independently rebuilt request occurrence
        # bind current root semantics.  A serializer/schema migration may
        # therefore change the current full-contract digest without rewriting
        # historical evidence; it may not change the provider source, request
        # parameter, or root binding proved below.
        _runtime_contract_digest(family, contract)
        if (
            sealed.get("physical_endpoint_key") != physical
            or sealed.get("provider_source_path") != source_path
            or sealed.get("provider_source_sha256") != provider_sha256
            or sealed.get("provider_source_size") != provider_size
            or sealed.get("explicit_competition_axis_status") != "absent"
            or sealed.get("explicit_competition_axis_occurrence_ids") != []
            or league_axes_by_endpoint.get(provider, [])
        ):
            raise _ImplicitCompetitionVerificationError(
                "root binding differs from provider/request authority"
            )
        mode = sealed.get("root_mode")
        root_kind = sealed.get("root_kind")
        root_evidence = _dict(sealed.get("root_evidence"), "root evidence")
        if mode == "request_parameter":
            if (
                set(root_evidence)
                != {
                    "parameter",
                    "receipt_required_before_request",
                    "repo_root_parameter_name",
                }
                or root_evidence.get("receipt_required_before_request") is not True
            ):
                raise _ImplicitCompetitionVerificationError("request root evidence is incomplete")
            parameter = _dict(root_evidence.get("parameter"), "request root parameter")
            occurrence_id = str(parameter.get("occurrence_id"))
            checked_occurrence = request_by_id.get(occurrence_id)
            expected_kind = {"game_id": "game", "team_id": "team", "player_id": "player"}.get(
                str(parameter.get("name"))
            )
            if (
                checked_occurrence is None
                or parameter != _request_parameter_projection(checked_occurrence)
                or checked_occurrence.get("endpoint_id") != provider
                or root_evidence.get("repo_root_parameter_name") != parameter.get("name")
                or root_kind != expected_kind
                or sealed.get("forwarding_behavior") != "exact_root_value_forwarding"
            ):
                raise _ImplicitCompetitionVerificationError(
                    "request root occurrence/signature/domain binding drifted"
                )
        elif mode in {"response_game_join", "response_game_collection"}:
            if root_kind != "game" or root_evidence.get("receipt_join_required") is not True:
                raise _ImplicitCompetitionVerificationError("live response root is invalid")
        elif mode == "embedded_static_dataset":
            assignment = _STATIC_ASSIGNMENTS.get(provider)
            if (
                assignment is None
                or root_kind != "static"
                or root_evidence.get("fixed_league_id") != assignment[2]
                or root_evidence.get("fixed_symbol") != assignment[3]
                or root_evidence.get("provider_default_used") is not False
                or sealed.get("forwarding_behavior") != "fixed_static_dataset_selection"
            ):
                raise _ImplicitCompetitionVerificationError("static root binding is invalid")
        else:
            raise _ImplicitCompetitionVerificationError("root mode is foreign")
        derived_bindings.append(deepcopy(sealed))

    derived_bindings.sort(key=lambda row: str(row["repo_endpoint_name"]))
    if derived_bindings != sealed_bindings:
        raise _ImplicitCompetitionVerificationError(
            "sealed endpoint bindings differ from independent derivation"
        )
    if {str(row["physical_endpoint_key"]) for row in derived_bindings} != implicit_physical:
        raise _ImplicitCompetitionVerificationError("implicit physical complement is incomplete")

    derived_aliases = [
        {
            "provider_endpoint_id": row["provider_endpoint_id"],
            "repo_endpoint_name": row["repo_endpoint_name"],
            "source_family": row["source_family"],
            "source_path": row["repo_source_path"],
        }
        for row in derived_bindings
    ]
    sealed_aliases = _rows(evidence.get("implicit_alias_complement"), "implicit aliases")
    if (
        derived_aliases != sealed_aliases
        or {str(row["repo_endpoint_name"]) for row in derived_aliases} != implicit_aliases
    ):
        raise _ImplicitCompetitionVerificationError(
            "sealed alias bindings differ from independent registry derivation"
        )

    repo_trees_by_alias = {
        str(row["repo_endpoint_name"]): repo_trees_by_path[str(row["repo_source_path"])]
        for row in derived_bindings
    }
    _verify_live_raw_evidence(
        evidence,
        runtime,
        provider_sources,
        repo_trees_by_alias,
    )
    _verify_static_chains(evidence, runtime, distribution_root, record)

    physical_cells: list[dict[str, object]] = []
    alias_cells: list[dict[str, object]] = []
    for binding in derived_bindings:
        root_evidence = _dict(binding["root_evidence"], "root evidence")
        for competition_row in expected_competitions:
            league_id = str(competition_row["league_id"])
            if binding["root_mode"] == "embedded_static_dataset":
                fixed = league_id == root_evidence["fixed_league_id"]
                root_state = "fixed_static_root" if fixed else "root_not_exposed"
                assignment = (
                    "pinned_static_contract_chain"
                    if fixed
                    else "none_without_an_exposed_static_root"
                )
            else:
                root_state = "receipt_bound_root_required"
                assignment = "ReceiptBoundCompetitionRootV1"
            common = {
                "assignment_authority": assignment,
                "endpoint_support_status": "unknown",
                "league_id": league_id,
                "physical_endpoint_key": binding["physical_endpoint_key"],
                "provider_availability_status": "unknown",
                "provider_endpoint_id": binding["provider_endpoint_id"],
                "provider_probe_executed": False,
                "request_terminal_state": "not_asserted",
                "root_binding_sha256": binding["binding_sha256"],
                "root_kind": binding["root_kind"],
                "root_state": root_state,
                "source_family": binding["source_family"],
                "symbol": competition_row["symbol"],
            }
            physical_cells.append(
                {
                    **common,
                    "cell_id": f"physical:{binding['physical_endpoint_key']}:{league_id}",
                }
            )
            alias_cells.append(
                {
                    **common,
                    "cell_id": f"alias:{binding['repo_endpoint_name']}:{league_id}",
                    "repo_endpoint_name": binding["repo_endpoint_name"],
                }
            )
    physical_cells.sort(key=lambda row: str(row["cell_id"]))
    alias_cells.sort(key=lambda row: str(row["cell_id"]))
    if (
        physical_cells != evidence.get("physical_competition_cells")
        or alias_cells != evidence.get("alias_competition_cells")
        or len(physical_cells) != 180
        or len(alias_cells) != 180
    ):
        raise _ImplicitCompetitionVerificationError(
            "sealed competition cells differ from independent derivation"
        )
    return derived_bindings, derived_aliases, physical_cells, alias_cells


@dataclass(frozen=True, slots=True)
class _DerivedImplicitCompetitionState:
    expected_payload: dict[str, object]
    dto_proof_binding: dict[str, object]
    supersession_proof_body: dict[str, object]
    supersession_proof_bytes: bytes
    supersession_proof_sha256: str


def _semantic_projection(
    *,
    endpoint_bindings: list[dict[str, object]],
    alias_bindings: list[dict[str, object]],
    physical_cells: list[dict[str, object]],
    alias_cells: list[dict[str, object]],
    denominator_counts: object,
    receipt_bound_root_policy: object,
) -> dict[str, object]:
    return {
        "endpoint_bindings": deepcopy(endpoint_bindings),
        "alias_bindings": deepcopy(alias_bindings),
        "physical_competition_cells": deepcopy(physical_cells),
        "alias_competition_cells": deepcopy(alias_cells),
        "denominator_counts": deepcopy(denominator_counts),
        "receipt_bound_root_policy": deepcopy(receipt_bound_root_policy),
    }


def _validate_partition_counts(
    current_resources: dict[str, dict[str, object]],
    current_projection: dict[str, object],
) -> dict[str, dict[str, int]]:
    occurrences = current_resources["nba_api_competition_occurrences_v1_11_4.json"]
    applicability = current_resources["nba_api_competition_applicability_v1_11_4.json"]
    implicit_endpoints = _rows(current_projection.get("endpoint_bindings"), "implicit endpoints")
    implicit_aliases = _rows(current_projection.get("alias_bindings"), "implicit aliases")
    implicit_physical_cells = _rows(
        current_projection.get("physical_competition_cells"),
        "implicit physical cells",
    )
    implicit_alias_cells = _rows(
        current_projection.get("alias_competition_cells"),
        "implicit alias cells",
    )
    explicit_alias_cells = _rows(
        applicability.get("alias_role_competition_cells"),
        "explicit alias-role cells",
    )
    projected_alias_roles = {
        (str(row.get("repo_endpoint_name")), str(row.get("provider_occurrence_id")))
        for row in explicit_alias_cells
    }
    denominators = _dict(current_projection.get("denominator_counts"), "denominator counts")
    actual = {
        "physical_sources": {
            "explicit": cast("int", occurrences.get("package_endpoint_count")),
            "implicit": len(implicit_endpoints),
            "total": cast("int", denominators.get("package_physical_source_count")),
        },
        "repo_aliases": {
            "explicit": cast("int", occurrences.get("repo_alias_count")),
            "implicit": len(implicit_aliases),
            "total": cast("int", denominators.get("package_registered_alias_count")),
        },
        "physical_competition_cells": {
            "explicit": cast("int", applicability.get("endpoint_competition_cell_count")),
            "implicit": len(implicit_physical_cells),
            "total": cast(
                "int",
                denominators.get("cumulative_physical_competition_cell_count"),
            ),
        },
        "parameter_axis_competition_cells": {
            "explicit": cast(
                "int",
                applicability.get("parameter_axis_competition_cell_count"),
            ),
            "implicit": len(implicit_physical_cells),
            "total": cast(
                "int",
                denominators.get("cumulative_parameter_axis_cell_count"),
            ),
        },
        "projected_alias_roles": {
            "explicit": len(projected_alias_roles),
            "implicit": len(implicit_aliases),
            "total": cast(
                "int",
                denominators.get("cumulative_projected_alias_role_count"),
            ),
        },
        "alias_role_competition_cells": {
            "explicit": cast(
                "int",
                applicability.get("alias_role_competition_cell_count"),
            ),
            "implicit": len(implicit_alias_cells),
            "total": cast("int", denominators.get("cumulative_alias_role_cell_count")),
        },
    }
    if actual != _PARTITION_COUNTS or any(
        row["explicit"] + row["implicit"] != row["total"] for row in actual.values()
    ):
        raise _ImplicitCompetitionVerificationError(
            "historical/current explicit-implicit partition is not exact"
        )
    return deepcopy(actual)


def _implicit_supersession_proof_body(
    *,
    historical_projection: dict[str, object],
    current_projection: dict[str, object],
    current_rows: list[dict[str, str]],
    partition_counts: dict[str, dict[str, int]],
) -> dict[str, object]:
    if (
        tuple(historical_projection) != _SEMANTIC_PROJECTION_FIELDS
        or tuple(current_projection) != _SEMANTIC_PROJECTION_FIELDS
        or historical_projection != current_projection
    ):
        raise _ImplicitCompetitionVerificationError(
            "historical and current semantic projections differ"
        )
    historical_field_digests = {
        field: _digest(historical_projection[field]) for field in _SEMANTIC_PROJECTION_FIELDS
    }
    current_field_digests = {
        field: _digest(current_projection[field]) for field in _SEMANTIC_PROJECTION_FIELDS
    }
    if historical_field_digests != current_field_digests:
        raise _ImplicitCompetitionVerificationError(
            "historical and current semantic field digests differ"
        )
    projection_sha256 = _digest(historical_projection)
    body: dict[str, object] = {
        "authority_finalized_without_future_artifact": True,
        "current": {
            "competition_applicability": deepcopy(_CURRENT_APPLICABILITY_IDENTITY),
            "competition_occurrences": deepcopy(_CURRENT_OCCURRENCE_IDENTITY),
            "request_surface": deepcopy(_CURRENT_REQUEST_IDENTITY),
            "semantic_field_sha256": current_field_digests,
            "semantic_projection_sha256": projection_sha256,
            "successor_rows": deepcopy(current_rows),
            "successor_rows_sha256": _CURRENT_SUCCESSOR_ROWS_SHA256,
        },
        "finding_count": 0,
        "findings": [],
        "historical": {
            "implicit_resource": {
                "authority_sha256": _HISTORICAL_IMPLICIT_AUTHORITY_SHA256,
                "path": _RESOURCE_REL,
                "payload_sha256": _HISTORICAL_IMPLICIT_PAYLOAD_SHA256,
                "sha256": _HISTORICAL_IMPLICIT_RESOURCE_SHA256,
                "size": _HISTORICAL_IMPLICIT_RESOURCE_SIZE,
            },
            "opening_rows": deepcopy(list(_HISTORICAL_OPENING_ROWS)),
            "opening_rows_sha256": _HISTORICAL_OPENING_ROWS_SHA256,
            "semantic_field_sha256": historical_field_digests,
            "semantic_projection_sha256": projection_sha256,
            "successor_paths": list(_SUCCESSOR_PATHS),
            "successor_paths_sha256": _SUCCESSOR_PATHS_SHA256,
        },
        "kind": _W5_PROOF_KIND,
        "partition_counts": deepcopy(partition_counts),
        "schema_version": 1,
        "semantic_projection_equal": True,
        "semantic_projection_fields": list(_SEMANTIC_PROJECTION_FIELDS),
        "task_packets": {
            "historical": {"path": _TASK_PACKET_REL, "sha256": _TASK_PACKET_SHA256},
            "successor": {
                "path": _SUCCESSOR_TASK_PACKET_REL,
                "sha256": _SUCCESSOR_TASK_PACKET_SHA256,
            },
        },
    }
    if any(key in body for key in ("receipt", "temporary_path", "w9")):
        raise _ImplicitCompetitionVerificationError(
            "supersession proof acquired a future or temporary dependency"
        )
    return body


def _derive_expected_state() -> _DerivedImplicitCompetitionState:
    packet_raw, packet = _read_packaged_provenance(
        _TASK_PACKET_REL, label="A1.2d task packet", pretty=True
    )
    successor_raw, successor = _read_packaged_provenance(
        _SUCCESSOR_TASK_PACKET_REL,
        label="A1.3a repair task packet",
        pretty=True,
    )
    evidence_raw, evidence = _read_packaged_provenance(
        _EVIDENCE_REL, label="implicit root evidence", pretty=True
    )
    review_raw, review = _read_packaged_provenance(
        _SOURCE_REVIEW_REL, label="implicit root source review", pretty=True
    )
    if hashlib.sha256(evidence_raw).hexdigest() != _EVIDENCE_SHA256:
        raise _ImplicitCompetitionVerificationError("implicit root evidence file drifted")
    if hashlib.sha256(review_raw).hexdigest() != _SOURCE_REVIEW_SHA256:
        raise _ImplicitCompetitionVerificationError("implicit source review file drifted")
    _verify_sealed_evidence(evidence)
    _verify_source_review(review, evidence_raw)
    _validate_reconciliation_packets(
        packet_raw,
        packet,
        successor_raw,
        successor,
        evidence,
    )
    source_input_authority = _dict(packet.get("source_input_authority"), "source authority")
    expected_source_input = {
        "implicit_competition_roots": {
            "authority_sha256": _EVIDENCE_AUTHORITY_SHA256,
            "canonicalization_sha256": _EVIDENCE_CANONICALIZATION_SHA256,
            "path": _EVIDENCE_REL,
            "payload_sha256": _EVIDENCE_PAYLOAD_SHA256,
            "receipt_bound_root_policy_sha256": _RECEIPT_POLICY_SHA256,
            "schema": "ImplicitCompetitionRootEvidenceV1",
            "sha256": _EVIDENCE_SHA256,
        },
        "independent_source_review": {
            "authority_sha256": _SOURCE_REVIEW_AUTHORITY_SHA256,
            "canonicalization_sha256": _SOURCE_REVIEW_CANONICALIZATION_SHA256,
            "disposition": "pass",
            "findings": [],
            "path": _SOURCE_REVIEW_REL,
            "payload_sha256": _SOURCE_REVIEW_PAYLOAD_SHA256,
            "review_id": "A1.2d/source-input-admission",
            "schema": "IndependentSourceReviewV1",
            "sha256": _SOURCE_REVIEW_SHA256,
            "task_id": "A1.2d-source-inputs",
        },
    }
    if source_input_authority != expected_source_input:
        raise _ImplicitCompetitionVerificationError("task-packet source authority drifted")

    current_rows = _read_current_successor_rows()
    resources_by_name = _load_predecessor_resources()
    _, distribution_root, record, distribution_authority = _distribution_authority()
    historical_authorities = _validate_historical_predecessor_authorities(
        evidence,
        distribution_authority,
    )
    _validate_current_predecessor_authorities(resources_by_name, historical_authorities)
    endpoint_bindings, alias_bindings, physical_cells, alias_cells = _derive_bindings_and_cells(
        evidence,
        resources_by_name,
        distribution_root,
        record,
    )
    historical_projection = _semantic_projection(
        endpoint_bindings=_rows(evidence.get("root_bindings"), "historical endpoint bindings"),
        alias_bindings=_rows(
            evidence.get("implicit_alias_complement"),
            "historical alias bindings",
        ),
        physical_cells=_rows(
            evidence.get("physical_competition_cells"),
            "historical physical cells",
        ),
        alias_cells=_rows(
            evidence.get("alias_competition_cells"),
            "historical alias cells",
        ),
        denominator_counts=packet.get("denominator_authority"),
        receipt_bound_root_policy=evidence.get("receipt_bound_root_policy"),
    )
    current_projection = _semantic_projection(
        endpoint_bindings=endpoint_bindings,
        alias_bindings=alias_bindings,
        physical_cells=physical_cells,
        alias_cells=alias_cells,
        denominator_counts=packet.get("denominator_authority"),
        receipt_bound_root_policy=evidence.get("receipt_bound_root_policy"),
    )
    partition_counts = _validate_partition_counts(resources_by_name, current_projection)
    supersession_body = _implicit_supersession_proof_body(
        historical_projection=historical_projection,
        current_projection=current_projection,
        current_rows=current_rows,
        partition_counts=partition_counts,
    )
    supersession_bytes = _canonical_bytes(supersession_body)
    supersession_sha256 = hashlib.sha256(supersession_bytes).hexdigest()

    source_authorities = {
        "task_packet": {"path": _TASK_PACKET_REL, "sha256": _TASK_PACKET_SHA256},
        "implicit_competition_roots": deepcopy(
            source_input_authority["implicit_competition_roots"]
        ),
        "independent_source_review": deepcopy(source_input_authority["independent_source_review"]),
        "predecessor_receipts": deepcopy(packet["predecessor_receipts"]),
        "predecessor_resources": deepcopy(evidence["source_authorities"]),
    }
    body: dict[str, object] = {
        "kind": "nbadb_nba_api_implicit_competition_authority",
        "schema_version": 1,
        "task_id": "A1.2d",
        "source_authorities": source_authorities,
        "receipt_bound_root_policy": deepcopy(evidence["receipt_bound_root_policy"]),
        "receipt_bound_root_policy_sha256": _RECEIPT_POLICY_SHA256,
        "endpoint_bindings": endpoint_bindings,
        "endpoint_bindings_sha256": _digest(endpoint_bindings),
        "alias_bindings": alias_bindings,
        "alias_bindings_sha256": _digest(alias_bindings),
        "physical_competition_cells": physical_cells,
        "physical_competition_cells_sha256": _digest(physical_cells),
        "alias_competition_cells": alias_cells,
        "alias_competition_cells_sha256": _digest(alias_cells),
        "denominator_counts": deepcopy(packet["denominator_authority"]),
        "false_green_counters": deepcopy(packet["false_green_counters"]),
        "provider_availability_values": ["unknown"],
        "independent_proof": {"required": True, "verifier_id": _VERIFIER_ID},
    }
    body["authority_sha256"] = _digest(body)
    body["payload_sha256"] = _digest(body)
    expected_raw = _pretty_bytes(body)
    if (
        len(expected_raw) != _HISTORICAL_IMPLICIT_RESOURCE_SIZE
        or hashlib.sha256(expected_raw).hexdigest() != _HISTORICAL_IMPLICIT_RESOURCE_SHA256
        or body.get("authority_sha256") != _HISTORICAL_IMPLICIT_AUTHORITY_SHA256
        or body.get("payload_sha256") != _HISTORICAL_IMPLICIT_PAYLOAD_SHA256
    ):
        raise _ImplicitCompetitionVerificationError(
            "derived historical implicit authority differs from the immutable barrier"
        )
    dto_binding = _proof_binding_from_expected_payload(body)
    return _DerivedImplicitCompetitionState(
        expected_payload=body,
        dto_proof_binding=dto_binding,
        supersession_proof_body=supersession_body,
        supersession_proof_bytes=supersession_bytes,
        supersession_proof_sha256=supersession_sha256,
    )


def _proof_binding_from_expected_payload(payload: dict[str, object]) -> dict[str, object]:
    """Project the complete public proof body from independent expected authority."""

    denominator_counts = _dict(payload.get("denominator_counts"), "denominator counts")
    expected_denominators: dict[str, int] = {
        "cumulative_physical_competition_cell_count": 735,
        "cumulative_parameter_axis_count": 148,
        "cumulative_parameter_axis_cell_count": 740,
        "cumulative_projected_alias_role_count": 163,
        "cumulative_alias_role_cell_count": 815,
    }
    for name, expected in expected_denominators.items():
        _exact_int(denominator_counts.get(name), expected, name)
    endpoint_bindings = _rows(payload.get("endpoint_bindings"), "endpoint bindings")
    alias_bindings = _rows(payload.get("alias_bindings"), "alias bindings")
    physical_cells = _rows(payload.get("physical_competition_cells"), "physical cells")
    alias_cells = _rows(payload.get("alias_competition_cells"), "alias cells")
    return {
        "verifier_id": _VERIFIER_ID,
        "task_packet_sha256": _TASK_PACKET_SHA256,
        "evidence_sha256": _EVIDENCE_SHA256,
        "evidence_authority_sha256": _EVIDENCE_AUTHORITY_SHA256,
        "source_review_sha256": _SOURCE_REVIEW_SHA256,
        "source_review_authority_sha256": _SOURCE_REVIEW_AUTHORITY_SHA256,
        "candidate_authority_sha256": _require_digest(
            payload.get("authority_sha256"), "expected authority_sha256"
        ),
        "candidate_payload_sha256": _require_digest(
            payload.get("payload_sha256"), "expected payload_sha256"
        ),
        "endpoint_binding_count": len(endpoint_bindings),
        "endpoint_bindings_sha256": _require_digest(
            payload.get("endpoint_bindings_sha256"), "expected endpoint_bindings_sha256"
        ),
        "alias_binding_count": len(alias_bindings),
        "alias_bindings_sha256": _require_digest(
            payload.get("alias_bindings_sha256"), "expected alias_bindings_sha256"
        ),
        "physical_cell_count": len(physical_cells),
        "physical_competition_cells_sha256": _require_digest(
            payload.get("physical_competition_cells_sha256"),
            "expected physical_competition_cells_sha256",
        ),
        "alias_cell_count": len(alias_cells),
        "alias_competition_cells_sha256": _require_digest(
            payload.get("alias_competition_cells_sha256"),
            "expected alias_competition_cells_sha256",
        ),
        **expected_denominators,
        "missing_ids": (),
        "foreign_ids": (),
        "mismatched_ids": (),
    }


def _expected_dto_proof_binding() -> dict[str, object]:
    """Return the sealed proof binding without consulting the filesystem."""

    return {
        "verifier_id": _VERIFIER_ID,
        "task_packet_sha256": _TASK_PACKET_SHA256,
        "evidence_sha256": _EVIDENCE_SHA256,
        "evidence_authority_sha256": _EVIDENCE_AUTHORITY_SHA256,
        "source_review_sha256": _SOURCE_REVIEW_SHA256,
        "source_review_authority_sha256": _SOURCE_REVIEW_AUTHORITY_SHA256,
        "candidate_authority_sha256": _HISTORICAL_IMPLICIT_AUTHORITY_SHA256,
        "candidate_payload_sha256": _HISTORICAL_IMPLICIT_PAYLOAD_SHA256,
        "endpoint_binding_count": 36,
        "endpoint_bindings_sha256": (
            "b0ad3c2f49ec579011e23ce483f730ccd55d7367fd8bfff2e7ae588268e283bb"
        ),
        "alias_binding_count": 36,
        "alias_bindings_sha256": (
            "54f1da07f08dc206e4b7dd5059e1c7e8d978adb56713cdb3d838f772bd487585"
        ),
        "physical_cell_count": 180,
        "physical_competition_cells_sha256": (
            "655f0e189bf48905b85d4fe3efca6352b05a2e430f4bf1fbb2121edd49d91fbc"
        ),
        "alias_cell_count": 180,
        "alias_competition_cells_sha256": (
            "b7ae01ce242c25945cac8d39fedd756d3e17bdb58609e804f425d6b8577e0c27"
        ),
        "cumulative_physical_competition_cell_count": 735,
        "cumulative_parameter_axis_count": 148,
        "cumulative_parameter_axis_cell_count": 740,
        "cumulative_projected_alias_role_count": 163,
        "cumulative_alias_role_cell_count": 815,
        "missing_ids": (),
        "foreign_ids": (),
        "mismatched_ids": (),
    }


def _read_implicit_candidate(path: Path | None) -> bytes:
    """Read exactly one candidate after every authority input has been derived."""

    if path is None:
        try:
            return resources.files("nbadb.contracts").joinpath(_RESOURCE).read_bytes()
        except (AttributeError, OSError) as exc:
            raise _ImplicitCompetitionVerificationError(
                "checked implicit competition resource cannot be read"
            ) from exc
    if type(path) is not _CONCRETE_PATH_TYPE:
        raise _ImplicitCompetitionVerificationError("candidate path must be an exact Path")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise _ImplicitCompetitionVerificationError(
            "candidate implicit competition resource cannot be read"
        ) from exc


def _validate_implicit_candidate(
    raw: bytes,
    expected: dict[str, object],
) -> dict[str, object]:
    """Validate already-read candidate bytes with no subsequent input access."""

    candidate = _parse(raw, label="implicit competition candidate", pretty=True)
    _verify_payload_digest(candidate, label="implicit competition candidate")
    if candidate != expected or raw != _pretty_bytes(expected):
        raise _ImplicitCompetitionVerificationError(
            "checked implicit competition authority differs from independent sources"
        )
    return candidate


def _build_implicit_supersession_proof() -> tuple[dict[str, object], bytes, str]:
    """Build the private deterministic W5 proof after one final candidate read."""

    state = _derive_expected_state()
    candidate_raw = _read_implicit_candidate(None)
    _validate_implicit_candidate(candidate_raw, state.expected_payload)
    return (
        deepcopy(state.supersession_proof_body),
        state.supersession_proof_bytes,
        state.supersession_proof_sha256,
    )


@dataclass(frozen=True, slots=True)
class IndependentImplicitCompetitionProof:
    """Exact proof that the checked implicit authority matches independent sources."""

    verifier_id: str
    task_packet_sha256: str
    evidence_sha256: str
    evidence_authority_sha256: str
    source_review_sha256: str
    source_review_authority_sha256: str
    candidate_authority_sha256: str
    candidate_payload_sha256: str
    endpoint_binding_count: int
    endpoint_bindings_sha256: str
    alias_binding_count: int
    alias_bindings_sha256: str
    physical_cell_count: int
    physical_competition_cells_sha256: str
    alias_cell_count: int
    alias_competition_cells_sha256: str
    cumulative_physical_competition_cell_count: int
    cumulative_parameter_axis_count: int
    cumulative_parameter_axis_cell_count: int
    cumulative_projected_alias_role_count: int
    cumulative_alias_role_cell_count: int
    missing_ids: tuple[str, ...]
    foreign_ids: tuple[str, ...]
    mismatched_ids: tuple[str, ...]
    proof_sha256: str

    def __post_init__(self) -> None:
        self._validated_body()

    def _validated_body(self) -> dict[str, object]:
        if type(self) is not IndependentImplicitCompetitionProof:
            raise _ImplicitCompetitionVerificationError(
                "independent proof must be the exact concrete DTO"
            )
        for name in ("verifier_id", *_PROOF_DIGEST_FIELDS):
            if type(getattr(self, name)) is not str:
                raise _ImplicitCompetitionVerificationError(f"{name} must be an exact str")
        if self.verifier_id != _VERIFIER_ID:
            raise _ImplicitCompetitionVerificationError("independent verifier ID is invalid")
        for name in _PROOF_DIGEST_FIELDS:
            _require_digest(getattr(self, name), name)
        exact_counts = {
            "endpoint_binding_count": 36,
            "alias_binding_count": 36,
            "physical_cell_count": 180,
            "alias_cell_count": 180,
            "cumulative_physical_competition_cell_count": 735,
            "cumulative_parameter_axis_count": 148,
            "cumulative_parameter_axis_cell_count": 740,
            "cumulative_projected_alias_role_count": 163,
            "cumulative_alias_role_cell_count": 815,
        }
        for name, expected in exact_counts.items():
            _exact_int(getattr(self, name), expected, name)
        for name in _PROOF_RESULT_FIELDS:
            value = getattr(self, name)
            if (
                type(value) is not tuple
                or any(type(item) is not str or not item for item in value)
                or value != tuple(sorted(set(value)))
                or value
            ):
                raise _ImplicitCompetitionVerificationError(
                    f"{name} must be an exact empty concrete tuple on PASS"
                )
        proof_body = {
            field.name: getattr(self, field.name)
            for field in fields(self)
            if field.name != "proof_sha256"
        }
        expected_binding = _expected_dto_proof_binding()
        if set(proof_body) != _PROOF_BODY_FIELDS or proof_body != expected_binding:
            raise _ImplicitCompetitionVerificationError(
                "independent proof binding differs from the independently derived authority"
            )
        if self.proof_sha256 != _digest(proof_body):
            raise _ImplicitCompetitionVerificationError("independent proof digest is invalid")
        return proof_body

    def validated_payload(self) -> dict[str, object]:
        """Return the exact proof payload after pure in-memory revalidation."""

        return {**self._validated_body(), "proof_sha256": self.proof_sha256}

    def __copy__(self) -> IndependentImplicitCompetitionProof:
        self._validated_body()
        return self

    def __deepcopy__(self, _memo: dict[int, object]) -> IndependentImplicitCompetitionProof:
        self._validated_body()
        return self

    def __reduce_ex__(
        self,
        _protocol: SupportsIndex,
    ) -> tuple[type[IndependentImplicitCompetitionProof], tuple[object, ...]]:
        self._validated_body()
        return (
            IndependentImplicitCompetitionProof,
            tuple(getattr(self, field.name) for field in fields(self)),
        )


def verify_pinned_implicit_competition_authority(
    path: Path | None = None,
) -> IndependentImplicitCompetitionProof:
    """Re-derive and verify the installed or explicit checked resource."""

    state = _derive_expected_state()
    candidate_raw = _read_implicit_candidate(path)
    candidate = _validate_implicit_candidate(candidate_raw, state.expected_payload)
    expected_proof_binding = state.dto_proof_binding
    proof_body = {
        "verifier_id": _VERIFIER_ID,
        "task_packet_sha256": _TASK_PACKET_SHA256,
        "evidence_sha256": _EVIDENCE_SHA256,
        "evidence_authority_sha256": _EVIDENCE_AUTHORITY_SHA256,
        "source_review_sha256": _SOURCE_REVIEW_SHA256,
        "source_review_authority_sha256": _SOURCE_REVIEW_AUTHORITY_SHA256,
        "candidate_authority_sha256": candidate["authority_sha256"],
        "candidate_payload_sha256": candidate["payload_sha256"],
        "endpoint_binding_count": len(cast("list[object]", candidate["endpoint_bindings"])),
        "endpoint_bindings_sha256": candidate["endpoint_bindings_sha256"],
        "alias_binding_count": len(cast("list[object]", candidate["alias_bindings"])),
        "alias_bindings_sha256": candidate["alias_bindings_sha256"],
        "physical_cell_count": len(cast("list[object]", candidate["physical_competition_cells"])),
        "physical_competition_cells_sha256": candidate["physical_competition_cells_sha256"],
        "alias_cell_count": len(cast("list[object]", candidate["alias_competition_cells"])),
        "alias_competition_cells_sha256": candidate["alias_competition_cells_sha256"],
        "cumulative_physical_competition_cell_count": 735,
        "cumulative_parameter_axis_count": 148,
        "cumulative_parameter_axis_cell_count": 740,
        "cumulative_projected_alias_role_count": 163,
        "cumulative_alias_role_cell_count": 815,
        "missing_ids": (),
        "foreign_ids": (),
        "mismatched_ids": (),
    }
    if proof_body != expected_proof_binding:
        raise _ImplicitCompetitionVerificationError(
            "verified candidate proof projection differs from independent authority"
        )
    return IndependentImplicitCompetitionProof(
        verifier_id=_VERIFIER_ID,
        task_packet_sha256=_TASK_PACKET_SHA256,
        evidence_sha256=_EVIDENCE_SHA256,
        evidence_authority_sha256=_EVIDENCE_AUTHORITY_SHA256,
        source_review_sha256=_SOURCE_REVIEW_SHA256,
        source_review_authority_sha256=_SOURCE_REVIEW_AUTHORITY_SHA256,
        candidate_authority_sha256=cast("str", candidate["authority_sha256"]),
        candidate_payload_sha256=cast("str", candidate["payload_sha256"]),
        endpoint_binding_count=36,
        endpoint_bindings_sha256=cast("str", candidate["endpoint_bindings_sha256"]),
        alias_binding_count=36,
        alias_bindings_sha256=cast("str", candidate["alias_bindings_sha256"]),
        physical_cell_count=180,
        physical_competition_cells_sha256=cast(
            "str", candidate["physical_competition_cells_sha256"]
        ),
        alias_cell_count=180,
        alias_competition_cells_sha256=cast("str", candidate["alias_competition_cells_sha256"]),
        cumulative_physical_competition_cell_count=735,
        cumulative_parameter_axis_count=148,
        cumulative_parameter_axis_cell_count=740,
        cumulative_projected_alias_role_count=163,
        cumulative_alias_role_cell_count=815,
        missing_ids=(),
        foreign_ids=(),
        mismatched_ids=(),
        proof_sha256=_digest(proof_body),
    )


__all__ = [
    "IndependentImplicitCompetitionProof",
    "verify_pinned_implicit_competition_authority",
]
