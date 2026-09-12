from __future__ import annotations

import ast
import hashlib
import importlib
import json
import pickle
import socket
from collections import Counter
from copy import copy, deepcopy
from dataclasses import fields, replace
from pathlib import Path
from typing import cast

import pytest

import nbadb.core.nba_api_competition_identity_verifier as verifier_module
from nbadb.core.nba_api_competition_identity_verifier import (
    IndependentCompetitionIdentityProof,
    verify_pinned_competition_identity_authority,
)

_RESOURCE = Path("src/nbadb/contracts/nba_api_competition_identity_v1_11_4.json")
_VERIFIER_SOURCE = Path("src/nbadb/core/nba_api_competition_identity_verifier.py")
_COMPETITION_DOMAIN = "nbadb.nba-api.competition-scope.v1"
_VERIFIER_ID = "nbadb_independent_competition_identity_v2"
_TERMINAL_POLICY_SHA256 = "7226e797a685755311b7b9073f905d7288150e3412d52d95423ef0093548388d"
_REQUEST_SURFACE_SHA256 = "ef6195829a9f1dad9f847094b79e88fae24dffc5c4df18e3d3e972f347f83733"
_IMPLICIT_SUPERSESSION_PROOF_SHA256 = (
    "72ef26235ab1ffbc3f3f339ef246151201dfa331f14444a88888eeddd94be7c5"
)
_EXPECTED_PROOF_FIELDS = (
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


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _pretty_bytes(value: object) -> bytes:
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


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _payload() -> dict[str, object]:
    return cast("dict[str, object]", json.loads(_RESOURCE.read_text(encoding="utf-8")))


def _mapping(payload: dict[str, object], name: str) -> dict[str, object]:
    return cast("dict[str, object]", payload[name])


def _rows(payload: dict[str, object], name: str) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", payload[name])


def _surface(payload: dict[str, object], name: str) -> dict[str, object]:
    return next(
        row for row in _rows(payload, "qualified_surface_contracts") if row["surface_name"] == name
    )


def _reseal(payload: dict[str, object]) -> bytes:
    for requirement in _rows(payload, "identity_requirements"):
        role = cast("dict[str, object]", requirement["role_binding"])
        role_body = dict(role)
        role_body.pop("role_binding_sha256", None)
        role["role_binding_sha256"] = _digest(role_body)
        requirement_body = dict(requirement)
        requirement_body.pop("requirement_sha256", None)
        requirement["requirement_sha256"] = _digest(
            {
                "domain_separator": _COMPETITION_DOMAIN,
                "requirement": requirement_body,
            }
        )
    payload["identity_requirements_sha256"] = _digest(payload["identity_requirements"])
    for surface in _rows(payload, "qualified_surface_contracts"):
        surface_body = dict(surface)
        surface_body.pop("surface_contract_sha256", None)
        surface["surface_contract_sha256"] = _digest(surface_body)
    payload["qualified_surface_contracts_sha256"] = _digest(payload["qualified_surface_contracts"])
    authority_body = dict(payload)
    authority_body.pop("authority_sha256", None)
    authority_body.pop("payload_sha256", None)
    payload["authority_sha256"] = _digest(authority_body)
    payload_body = dict(payload)
    payload_body.pop("payload_sha256", None)
    payload["payload_sha256"] = _digest(payload_body)
    return _pretty_bytes(payload)


def _candidate(tmp_path: Path, payload: dict[str, object], name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(_reseal(payload))
    return path


def _assert_rejected(path: Path) -> None:
    with pytest.raises(ValueError):
        verify_pinned_competition_identity_authority(path)


_FORBIDDEN_IMPORT_ROOTS = (
    "nbadb.core.nba_api_competition_identity",
    "nbadb.core.nba_api_terminal_state",
    "nbadb.core.nba_api_request_surface",
    "nbadb.core.nba_api_competition",
    "nbadb.core.nba_api_competition_applicability",
    "nbadb.core.nba_api_implicit_competition",
    "nbadb.orchestrate.request_closure_runtime",
    "nbadb.orchestrate.successor_assurance",
    "nbadb.contracts.assurance",
)
_ALLOWED_NBADB_IMPORT_EDGES = {
    "nbadb.core.nba_api_implicit_competition_verifier",
    ("nbadb.core.nba_api_implicit_competition_verifier._build_implicit_supersession_proof"),
}


def _normalized_import_edges(source: str, module_name: str) -> set[str]:
    tree = ast.parse(source)
    package_parts = module_name.rpartition(".")[0].split(".")
    edges: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            edges.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.level > len(package_parts):
                    edges.add("<invalid-relative-import>")
                    continue
                anchor = package_parts[: len(package_parts) - (node.level - 1)]
                module_parts = [] if node.module is None else node.module.split(".")
                base = ".".join([*anchor, *module_parts])
            else:
                base = node.module or ""
            if base:
                edges.add(base)
            for alias in node.names:
                if alias.name != "*":
                    edges.add(".".join(part for part in (base, alias.name) if part))
    return edges


def _matches_import_boundary(edge: str, root: str) -> bool:
    return edge == root or edge.startswith(f"{root}.")


def _assert_import_independence() -> None:
    source = _VERIFIER_SOURCE.read_text(encoding="utf-8")
    edges = _normalized_import_edges(
        source,
        "nbadb.core.nba_api_competition_identity_verifier",
    )
    nbadb_edges = {edge for edge in edges if edge == "nbadb" or edge.startswith("nbadb.")}
    assert nbadb_edges == _ALLOWED_NBADB_IMPORT_EDGES
    assert not {
        edge
        for edge in edges
        if any(_matches_import_boundary(edge, root) for root in _FORBIDDEN_IMPORT_ROOTS)
    }

    fixture_edges = _normalized_import_edges(
        "\n".join(
            (
                "import nbadb.core.nba_api_competition_identity as primary_alias",
                "from nbadb.core import nba_api_request_surface as request_alias",
                "from . import nba_api_terminal_state as terminal_alias",
                "from ..orchestrate.request_closure_runtime import close_request",
                "import nbadb.core.nba_api_competition_identity_extra",
            )
        ),
        "nbadb.core.synthetic_verifier",
    )
    for root in _FORBIDDEN_IMPORT_ROOTS[:3]:
        assert any(_matches_import_boundary(edge, root) for edge in fixture_edges)
    assert not any(
        _matches_import_boundary(edge, "nbadb.core.nba_api_competition_identity")
        for edge in fixture_edges
        if edge == "nbadb.core.nba_api_competition_identity_extra"
    )


def _assert_candidate_read_order() -> None:
    source = _VERIFIER_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_VERIFIER_SOURCE))
    verifier = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "verify_pinned_competition_identity_authority"
    )
    calls = [
        (node.func.id, node.lineno)
        for node in ast.walk(verifier)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    candidate_lines = [line for name, line in calls if name == "_read_candidate"]
    assert len(candidate_lines) == 1
    candidate_line = candidate_lines[0]
    for required in (
        "_derive_expected_payload",
        "_pretty_bytes",
        "_proof_binding",
        "_prepare_pure_proof_binding",
    ):
        assert [line for name, line in calls if name == required]
        assert max(line for name, line in calls if name == required) < candidate_line
    assert not {
        name
        for name, line in calls
        if line > candidate_line
        and name
        in {
            "_read_packaged_task_packet",
            "_read_packaged_contract_resource",
            "_authenticated_json",
            "_authenticate_packet_chain",
            "_authenticate_current_resources",
            "_derive_expected_payload",
            "_proof_binding",
        }
    }
    derive = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_derive_expected_payload"
    )
    derive_calls = [
        node.func.id
        for node in ast.walk(derive)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert derive_calls.count("_authenticated_implicit_supersession_proof") == 1
    proof_derivation = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_authenticated_implicit_supersession_proof"
    )
    proof_calls = [
        node.func.id
        for node in ast.walk(proof_derivation)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert proof_calls.count("_build_implicit_supersession_proof") == 1


def _explicit_competition_pair(
    payload: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    requirements = _rows(payload, "identity_requirements")
    nba = next(
        row
        for row in requirements
        if row["league_id"] == "00"
        and cast("dict[str, object]", row["role_binding"])["binding_strategy"]
        == "explicit_applicability_cell"
    )
    nba_role = cast("dict[str, object]", nba["role_binding"])
    wnba = next(
        row
        for row in requirements
        if row["league_id"] == "10"
        and row["repo_endpoint_name"] == nba["repo_endpoint_name"]
        and cast("dict[str, object]", row["role_binding"])["provider_occurrence_id"]
        == nba_role["provider_occurrence_id"]
    )
    return nba, wnba


def _dynamic_requirement(payload: dict[str, object]) -> dict[str, object]:
    return next(
        row
        for row in _rows(payload, "identity_requirements")
        if cast("dict[str, object]", row["role_binding"])["binding_strategy"]
        == "receipt_bound_dynamic_root"
    )


def test_independent_verifier_never_sends_provider_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("independent verification attempted a network operation")

    monkeypatch.setattr(socket, "socket", reject_network)
    monkeypatch.setattr(socket, "create_connection", reject_network)

    events: list[str] = []
    original_read_task_packet = verifier_module._read_packaged_task_packet
    original_read_contract_resource = verifier_module._read_packaged_contract_resource
    original_read_candidate = verifier_module._read_candidate
    implicit_verifier = importlib.import_module("nbadb.core.nba_api_implicit_competition_verifier")
    original_w5_derivation = implicit_verifier._build_implicit_supersession_proof

    def tracked_read_task_packet(relative: str) -> bytes:
        events.append(f"package:{relative}")
        return original_read_task_packet(relative)

    def tracked_read_contract_resource(relative: str) -> bytes:
        events.append(f"package:{relative}")
        return original_read_contract_resource(relative)

    def tracked_read_candidate(path: Path | None) -> tuple[bytes, dict[str, object]]:
        events.append("candidate")
        return original_read_candidate(path)

    def tracked_w5_derivation() -> tuple[dict[str, object], bytes, str]:
        events.append("w5:start")
        result = original_w5_derivation()
        events.append("w5:complete")
        return result

    monkeypatch.setattr(verifier_module, "_read_packaged_task_packet", tracked_read_task_packet)
    monkeypatch.setattr(
        verifier_module,
        "_read_packaged_contract_resource",
        tracked_read_contract_resource,
    )
    monkeypatch.setattr(verifier_module, "_read_candidate", tracked_read_candidate)
    monkeypatch.setattr(
        implicit_verifier,
        "_build_implicit_supersession_proof",
        tracked_w5_derivation,
    )

    _assert_import_independence()
    _assert_candidate_read_order()
    proof = verify_pinned_competition_identity_authority()

    assert proof.finding_count == 0
    assert proof.findings == ()
    assert events.count("candidate") == 1
    assert events.count("w5:start") == 1
    assert events.count("w5:complete") == 1
    assert events.index("w5:start") < events.index("w5:complete") < events.index("candidate")
    assert events[-1] == "candidate"
    assert (
        events.index(
            "package:artifacts/assurance/complete-nba-api-sink/J0F/task-packets/"
            "A1.3a-repair-11.json"
        )
        < events.index(
            "package:artifacts/assurance/complete-nba-api-sink/J0F/task-packets/"
            "A1.3a-repair-10.json"
        )
        < events.index(
            "package:artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-9.json"
        )
        < events.index(
            "package:artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-8.json"
        )
        < events.index(
            "package:artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-7.json"
        )
        < events.index(
            "package:artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-6.json"
        )
        < events.index(
            "package:artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-5.json"
        )
        < events.index(
            "package:artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-4.json"
        )
        < events.index(
            "package:artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-3.json"
        )
        < events.index(
            "package:artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-2.json"
        )
        < events.index(
            "package:artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-1.json"
        )
        < events.index(
            "package:artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a.json"
        )
        < events.index(
            "package:artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.2e.json"
        )
        < events.index("candidate")
    )


def test_verifier_rejects_count_preserving_cell_or_surface_replacement(
    tmp_path: Path,
) -> None:
    payload = deepcopy(_payload())
    requirements = _rows(payload, "identity_requirements")
    requirements[0] = deepcopy(requirements[1])
    _assert_rejected(_candidate(tmp_path, payload, "requirement-replacement.json"))

    payload = deepcopy(_payload())
    surfaces = _rows(payload, "qualified_surface_contracts")
    surfaces[0] = deepcopy(surfaces[1])
    _assert_rejected(_candidate(tmp_path, payload, "surface-replacement.json"))

    exact_copy_drifts: tuple[tuple[str, str, object], ...] = (
        ("denominator_counts", "competition_count", 6),
        ("binding_strategy_counts", "fixed_static_root", 5),
        ("provider_request_policy", "wire_parameters_remain_unchanged", False),
        ("false_green_counters", "data_green_claim_count", 1),
        (
            "collision_invariants",
            "competition_scope_prevents_cross_competition_collisions",
            False,
        ),
    )
    for section, key, value in exact_copy_drifts:
        payload = deepcopy(_payload())
        _mapping(payload, section)[key] = value
        _assert_rejected(_candidate(tmp_path, payload, f"{section}-drift.json"))

    payload = deepcopy(_payload())
    separators = cast("list[object]", payload["domain_separators"])
    separators[0], separators[1] = separators[1], separators[0]
    _assert_rejected(_candidate(tmp_path, payload, "domain-order-drift.json"))

    payload = deepcopy(_payload())
    _mapping(payload, "collision_census").pop("source_inventory_inputs_sha256")
    _assert_rejected(_candidate(tmp_path, payload, "nested-missing.json"))

    payload = deepcopy(_payload())
    _mapping(payload, "collision_census")["foreign_field"] = False
    _assert_rejected(_candidate(tmp_path, payload, "nested-additional.json"))

    payload = deepcopy(_payload())
    source_request = _surface(payload, "source_request")
    field_types = cast("dict[str, object]", source_request["identity_field_types"])
    field_types["competition_scope_digest"] = field_types.pop("competition_scope_sha256")
    _assert_rejected(_candidate(tmp_path, payload, "nested-renamed.json"))

    payload = deepcopy(_payload())
    source_request = _surface(payload, "source_request")
    identity_fields = cast("list[object]", source_request["identity_fields"])
    identity_fields[0], identity_fields[1] = identity_fields[1], identity_fields[0]
    _assert_rejected(_candidate(tmp_path, payload, "nested-array-order.json"))

    payload = deepcopy(_payload())
    _mapping(payload, "denominator_counts")["competition_count"] = [5]
    _assert_rejected(_candidate(tmp_path, payload, "nested-scalar-container.json"))


def test_verifier_rejects_same_id_competition_collapse(tmp_path: Path) -> None:
    payload = deepcopy(_payload())
    nba, wnba = _explicit_competition_pair(payload)
    wnba["competition_scope_sha256"] = nba["competition_scope_sha256"]
    _assert_rejected(_candidate(tmp_path, payload, "same-id-scope-collapse.json"))

    payload = deepcopy(_payload())
    nba, wnba = _explicit_competition_pair(payload)
    wnba["league_id"] = nba["league_id"]
    wnba["symbol"] = nba["symbol"]
    wnba["competition_scope_sha256"] = nba["competition_scope_sha256"]
    _assert_rejected(_candidate(tmp_path, payload, "same-id-league-collapse.json"))


def test_verifier_rejects_cross_competition_pagination_rebinding(
    tmp_path: Path,
) -> None:
    payload = deepcopy(_payload())
    series = _surface(payload, "pagination_series")
    series["parent_surface"] = "entity"
    _assert_rejected(_candidate(tmp_path, payload, "pagination-series-parent.json"))

    payload = deepcopy(_payload())
    series = _surface(payload, "pagination_series")
    fields_list = cast("list[object]", series["identity_fields"])
    field_types = cast("dict[str, object]", series["identity_field_types"])
    fields_list[0] = "source_request_sha256"
    field_types["source_request_sha256"] = field_types.pop("competition_scope_sha256")
    _assert_rejected(_candidate(tmp_path, payload, "pagination-series-unqualified.json"))


def test_verifier_rejects_cross_competition_discovery_terminal_unavailable_or_staging_rebinding(
    tmp_path: Path,
) -> None:
    for name in (
        "discovery_generation",
        "terminal_observation",
        "unavailable_evidence",
        "staging_occurrence",
    ):
        payload = deepcopy(_payload())
        _surface(payload, name)["parent_surface"] = "pagination_series"
        _assert_rejected(_candidate(tmp_path, payload, f"{name}-rebound.json"))


def test_verifier_rejects_glalum_role_swap_or_role_collapse(tmp_path: Path) -> None:
    payload = deepcopy(_payload())
    rows = _rows(payload, "identity_requirements")
    person1 = next(
        row
        for row in rows
        if row["league_id"] == "00"
        and cast("dict[str, object]", row["role_binding"])["provider_occurrence_id"]
        == "parameter:stats:GLAlumBoxScoreSimilarityScore:0002:person1_league_id"
    )
    person2 = next(
        row
        for row in rows
        if row["league_id"] == "00"
        and cast("dict[str, object]", row["role_binding"])["provider_occurrence_id"]
        == "parameter:stats:GLAlumBoxScoreSimilarityScore:0005:person2_league_id"
    )
    person1["role_binding"], person2["role_binding"] = (
        person2["role_binding"],
        person1["role_binding"],
    )
    _assert_rejected(_candidate(tmp_path, payload, "glalum-role-swap.json"))

    payload = deepcopy(_payload())
    rows = _rows(payload, "identity_requirements")
    person1 = next(
        row
        for row in rows
        if row["league_id"] == "00"
        and cast("dict[str, object]", row["role_binding"])["provider_occurrence_id"]
        == "parameter:stats:GLAlumBoxScoreSimilarityScore:0002:person1_league_id"
    )
    person2 = next(
        row
        for row in rows
        if row["league_id"] == "00"
        and cast("dict[str, object]", row["role_binding"])["provider_occurrence_id"]
        == "parameter:stats:GLAlumBoxScoreSimilarityScore:0005:person2_league_id"
    )
    person2["role_binding"] = deepcopy(person1["role_binding"])
    _assert_rejected(_candidate(tmp_path, payload, "glalum-role-collapse.json"))


def test_verifier_rejects_missing_or_foreign_applicability_or_root_receipt(
    tmp_path: Path,
) -> None:
    payload = deepcopy(_payload())
    _mapping(payload, "source_authorities").pop("competition_applicability")
    _assert_rejected(_candidate(tmp_path, payload, "missing-applicability.json"))

    payload = deepcopy(_payload())
    authorities = _mapping(payload, "source_authorities")
    applicability = cast("dict[str, object]", authorities["competition_applicability"])
    applicability["authority_sha256"] = "0" * 64
    _assert_rejected(_candidate(tmp_path, payload, "foreign-applicability-authority.json"))

    payload = deepcopy(_payload())
    authorities = _mapping(payload, "source_authorities")
    implicit = cast("dict[str, object]", authorities["implicit_competition"])
    implicit["authority_sha256"] = "1" * 64
    _assert_rejected(_candidate(tmp_path, payload, "foreign-root-authority.json"))

    payload = deepcopy(_payload())
    authorities = _mapping(payload, "source_authorities")
    supersession = cast("dict[str, object]", authorities["implicit_supersession_proof"])
    supersession["proof_sha256"] = "2" * 64
    _assert_rejected(_candidate(tmp_path, payload, "foreign-supersession-proof.json"))

    payload = deepcopy(_payload())
    dynamic = _dynamic_requirement(payload)
    dynamic_role = cast("dict[str, object]", dynamic["role_binding"])
    dynamic_role["root_binding_sha256"] = "3" * 64
    _assert_rejected(_candidate(tmp_path, payload, "foreign-root-binding.json"))


def test_verifier_rejects_raw_implicit_id_default_history_url_or_source_spelling_authority(
    tmp_path: Path,
) -> None:
    mutations = (
        ("raw-implicit-id", "source_cell_id", "ScoreBoard"),
        ("nba-default", "root_state", "default"),
        ("history-url", "source_authority_kind", "history_url"),
        ("source-spelling", "source_authority_kind", "source_spelling"),
    )
    for name, field_name, value in mutations:
        payload = deepcopy(_payload())
        dynamic = _dynamic_requirement(payload)
        role = cast("dict[str, object]", dynamic["role_binding"])
        role[field_name] = value
        _assert_rejected(_candidate(tmp_path, payload, f"{name}.json"))


def test_independent_competition_verifier_rejects_terminal_scope_rebinding(
    tmp_path: Path,
) -> None:
    payload = deepcopy(_payload())
    authorities = _mapping(payload, "source_authorities")
    terminal = cast("dict[str, object]", authorities["terminal_state"])
    terminal["terminal_policy_sha256"] = "4" * 64
    _assert_rejected(_candidate(tmp_path, payload, "terminal-policy-rebinding.json"))

    payload = deepcopy(_payload())
    authorities = _mapping(payload, "source_authorities")
    request = cast("dict[str, object]", authorities["request_surface"])
    request["terminal_policy_sha256"] = "5" * 64
    _assert_rejected(_candidate(tmp_path, payload, "request-terminal-rebinding.json"))

    payload = deepcopy(_payload())
    terminal_surface = _surface(payload, "terminal_observation")
    identity_fields = cast("list[object]", terminal_surface["identity_fields"])
    field_types = cast("dict[str, object]", terminal_surface["identity_field_types"])
    identity_fields[0] = "request_binding_sha256"
    field_types["request_binding_sha256"] = field_types.pop("source_request_sha256")
    _assert_rejected(_candidate(tmp_path, payload, "terminal-surface-rebinding.json"))


def test_verifier_rejects_noncanonical_or_foreign_resource(tmp_path: Path) -> None:
    payload = deepcopy(_payload())
    minified = tmp_path / "minified.json"
    minified.write_bytes(_canonical_bytes(payload) + b"\n")
    _assert_rejected(minified)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_bytes(b'{"schema_version":1,"schema_version":1}\n')
    _assert_rejected(duplicate)

    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_bytes(b'{"schema_version":NaN}\n')
    _assert_rejected(nonfinite)

    foreign = tmp_path / "foreign.json"
    foreign.write_bytes(_pretty_bytes({"schema_version": 1}))
    _assert_rejected(foreign)

    class PathSubclass(type(Path())):
        pass

    with pytest.raises(ValueError, match="candidate path must be an exact Path"):
        verify_pinned_competition_identity_authority(PathSubclass(_RESOURCE))


def test_independent_competition_identity_authority_matches_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_import_independence()
    primary = importlib.import_module("nbadb.core.nba_api_competition_identity")
    primary_payload = cast("dict[str, object]", primary.build_pinned_competition_identity_payload())
    primary_authority = primary.pinned_competition_identity_authority()
    checked = _payload()
    proof = verify_pinned_competition_identity_authority()

    assert primary_payload == checked
    assert primary_authority.authority_sha256 == checked["authority_sha256"]
    assert checked["schema_version"] == 2
    assert checked["task_id"] == "A1.3a-repair-11"
    assert isinstance(proof, IndependentCompetitionIdentityProof)
    assert proof.verifier_id == _VERIFIER_ID
    assert proof.task_packet_sha256 == (
        "5f0cb0d04f9e46f412458489ba0d088193e18ba128f1739a2c03d87b4b5e57da"
    )
    assert proof.immutable_inputs_sha256 == (
        "5806ae72584f96aa45fd9069026543bf850c8d5f3799c3c007f9db7043cd61aa"
    )
    assert proof.source_inventory_inputs_sha256 == (
        "e0795472375627bccefab70ce77764875b03f3152cb44f046ba358d19fd1d7a9"
    )
    assert proof.terminal_policy_sha256 == _TERMINAL_POLICY_SHA256
    assert proof.request_surface_sha256 == _REQUEST_SURFACE_SHA256
    assert proof.implicit_supersession_proof_sha256 == _IMPLICIT_SUPERSESSION_PROOF_SHA256
    assert proof.candidate_authority_sha256 == checked["authority_sha256"]
    assert proof.candidate_payload_sha256 == checked["payload_sha256"]
    assert proof.identity_requirements_sha256 == checked["identity_requirements_sha256"]
    assert proof.qualified_surface_contracts_sha256 == checked["qualified_surface_contracts_sha256"]
    assert proof.qualified_surface_contracts_sha256 == (
        "d63d7842e2e68544afe6fa3eb36566f5b4f29138770fe20e76718bce9133c4b4"
    )
    assert _surface(checked, "terminal_observation")["identity_fields"] == [
        "source_request_sha256",
        "observation_sha256",
        "terminal_observation_sha256",
    ]
    assert _surface(checked, "unavailable_evidence")["identity_fields"] == [
        "source_request_sha256",
        "support_or_availability_authority_sha256",
        "unavailable_evidence_sha256",
    ]
    assert proof.identity_requirement_count == 815
    assert proof.qualified_surface_contract_count == 8
    assert proof.finding_count == 0
    assert proof.findings == ()
    strategy_counts = Counter(
        cast("dict[str, object]", row["role_binding"])["binding_strategy"]
        for row in _rows(checked, "identity_requirements")
    )
    assert strategy_counts == {
        "explicit_applicability_cell": 635,
        "receipt_bound_dynamic_root": 160,
        "fixed_static_root": 4,
        "root_not_exposed": 16,
    }
    source_authorities = _mapping(checked, "source_authorities")
    assert set(source_authorities) == {
        "task_packet",
        "identity_contract",
        "terminal_state",
        "request_surface",
        "competition",
        "competition_applicability",
        "implicit_competition",
        "implicit_supersession_proof",
    }
    assert source_authorities["terminal_state"] == {
        "path": "src/nbadb/contracts/nba_api_terminal_state_v1_11_4.json",
        "resource_sha256": "9389644949a92046ce3e00491842c3786812cfe043d727dbbdc6b0c84d2ab867",
        "payload_sha256": "471f594174107ccb8f582a6ab0459a356acf9daebd75ac55464475b3df792f4d",
        "terminal_policy_sha256": _TERMINAL_POLICY_SHA256,
    }
    assert source_authorities["task_packet"] == {
        "path": "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-11.json",
        "sha256": "5f0cb0d04f9e46f412458489ba0d088193e18ba128f1739a2c03d87b4b5e57da",
    }
    assert source_authorities["identity_contract"] == {
        "path": "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.2e.json",
        "sha256": "d87507bb66d470dfec88626f8fc9c0b8484fa54dbb1244d564693414e18fc64c",
    }
    assert source_authorities["request_surface"] == {
        "path": "src/nbadb/contracts/nba_api_request_surface_v1_11_4.json",
        "resource_sha256": "3082def2aa92b35d55107f5ce8eaf2ffa0532a0e649899d0f1180979f6144981",
        "payload_sha256": "b310313f41cf97cf1b8f55e01bbe95868532f3008527bf5265a985628eca9052",
        "surface_sha256": _REQUEST_SURFACE_SHA256,
        "runtime_contract_payload_sha256": (
            "7c9b59c475cff6b0b9d3619bdfe9a3849e11619980f6d15a1cafd5f269f61b3b"
        ),
        "terminal_policy_sha256": _TERMINAL_POLICY_SHA256,
    }
    assert source_authorities["competition"] == {
        "path": "src/nbadb/contracts/nba_api_competition_v1_11_4.json",
        "resource_sha256": "cfb93458f5efb569995ddccaf33ae37c0c312e25e09d0649c307999ec0057c44",
        "payload_sha256": "1e79989c9d75d671520d868dfa4e63bc828ceb7844c64b28e7325dd11a6ce7e0",
        "authority_sha256": "61c9477221c08f4f36269c8c3050171e0ec472508a0a8ac72ddc6f42d865ef98",
    }
    assert source_authorities["competition_applicability"] == {
        "path": "src/nbadb/contracts/nba_api_competition_applicability_v1_11_4.json",
        "resource_sha256": "daf43b872bd301aa87f1a67b357d970b82e532890e09e7ce0e580545d09cb0aa",
        "payload_sha256": "c1b808dc593d5aa9aea90b02285c2cfb37dc60e60ecd988dcf944d4984a9907a",
        "authority_sha256": "867d64282d6da37b9289c191ec5396e34c2c2ca335ebc94d09329ad89619528f",
    }
    assert source_authorities["implicit_competition"] == {
        "path": "src/nbadb/contracts/nba_api_implicit_competition_v1_11_4.json",
        "resource_sha256": "ed75be5cf84df8975cc32d50b51215648896b618584ed5b3b3aedcb8b6dc2111",
        "payload_sha256": "9fddfad2276884b5d49dc71fca052d7285f73e046d5157427b7fb7b2fcd35ec1",
        "authority_sha256": "fe7fd7581532754b322155ad0a74fcbd4068e1ebc83fbd841fd3736e27616d97",
        "historical": True,
    }
    assert source_authorities["implicit_supersession_proof"] == {
        "proof_sha256": _IMPLICIT_SUPERSESSION_PROOF_SHA256
    }

    def reject_late_io(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("proof DTO validation performed late filesystem I/O")

    monkeypatch.setattr(verifier_module, "_read_packaged_task_packet", reject_late_io)
    monkeypatch.setattr(verifier_module, "_read_packaged_contract_resource", reject_late_io)
    monkeypatch.setattr(verifier_module, "_read_candidate", reject_late_io)
    implicit_verifier = importlib.import_module("nbadb.core.nba_api_implicit_competition_verifier")
    monkeypatch.setattr(
        implicit_verifier,
        "_build_implicit_supersession_proof",
        reject_late_io,
    )

    projection = proof.validated_payload()
    assert projection["findings"] == []
    assert tuple(projection) == tuple(field.name for field in fields(proof))
    assert tuple(projection) == _EXPECTED_PROOF_FIELDS
    assert proof.to_dict() == projection
    proof_constructor = {field.name: getattr(proof, field.name) for field in fields(proof)}
    exact_body = {
        field.name: getattr(proof, field.name)
        for field in fields(proof)
        if field.name != "proof_sha256"
    }

    assert (
        IndependentCompetitionIdentityProof(**proof_constructor).validated_payload() == projection
    )
    assert replace(proof).validated_payload() == projection
    with pytest.raises(ValueError, match="proof digest"):
        replace(proof, proof_sha256="0" * 64)

    foreign_body = {
        **exact_body,
        "candidate_authority_sha256": _digest({"self_resealed": "foreign-authority"}),
    }
    with pytest.raises(ValueError, match="binding differs"):
        replace(
            proof,
            candidate_authority_sha256=cast("str", foreign_body["candidate_authority_sha256"]),
            proof_sha256=_digest(foreign_body),
        )

    class StringSubclass(str):
        pass

    class IntSubclass(int):
        pass

    class TupleSubclass(tuple):
        pass

    class ProofSubclass(IndependentCompetitionIdentityProof):
        pass

    with pytest.raises(ValueError):
        replace(proof, verifier_id=StringSubclass(proof.verifier_id))
    with pytest.raises(ValueError):
        replace(
            proof,
            candidate_payload_sha256=StringSubclass(proof.candidate_payload_sha256),
        )
    for value in (True, IntSubclass(proof.identity_requirement_count)):
        with pytest.raises(ValueError, match="is not exact"):
            replace(proof, identity_requirement_count=value)  # type: ignore[arg-type]
    for value in ([], TupleSubclass(())):
        with pytest.raises(ValueError, match="exact empty concrete tuple"):
            replace(proof, findings=value)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="exact concrete DTO"):
        ProofSubclass(**proof_constructor)
    with pytest.raises(TypeError, match="_validation_context"):
        IndependentCompetitionIdentityProof(
            **proof_constructor,
            _validation_context={"token": "external"},
        )

    assert copy(proof) is proof
    assert deepcopy(proof) is proof
    restored = pickle.loads(pickle.dumps(proof))
    assert type(restored) is IndependentCompetitionIdentityProof
    assert restored.validated_payload() == projection

    tampered = IndependentCompetitionIdentityProof(**proof_constructor)
    object.__setattr__(
        tampered,
        "candidate_authority_sha256",
        foreign_body["candidate_authority_sha256"],
    )
    object.__setattr__(tampered, "proof_sha256", _digest(foreign_body))
    with pytest.raises(ValueError, match="binding differs"):
        tampered.validated_payload()
    with pytest.raises(ValueError, match="binding differs"):
        copy(tampered)
    with pytest.raises(ValueError, match="binding differs"):
        deepcopy(tampered)
    with pytest.raises(ValueError, match="binding differs"):
        pickle.dumps(tampered)
