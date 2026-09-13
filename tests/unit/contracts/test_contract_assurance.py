from __future__ import annotations

import json
import os
import shutil
import socket
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from typer.testing import CliRunner

from nbadb.contracts import assurance
from nbadb.contracts.assurance import (
    CHILD_NAMES,
    GENERATION_CONTEXT_NAME,
    ContractAssuranceError,
)

if TYPE_CHECKING:
    from typing import Any


@pytest.fixture(autouse=True)
def _deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access is forbidden in contract assurance tests")

    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket.socket, "connect", _blocked)


def _context(*, observed_at: str = "2026-08-12T00:00:00+00:00") -> dict[str, Any]:
    digest = "a" * 64
    return {
        "semantic": {
            "schema_version": 1,
            "kind": "nbadb_contract_assurance_generation_context",
            "profile": "pre-extraction",
            "project": {
                "git_head_sha": "b" * 40,
                "file_count": 1,
                "source_sha256": "c" * 64,
                "path_record_count": 1,
                "dirty_sha256": "d" * 64,
            },
            "provider": {
                "authority": {"authority_sha256": "e" * 64},
                "evidence_receipt": {"evidence_sha256": digest},
            },
            "tools": {"python_version": "3.12.0"},
            "commands": {"check": ["nbadb", "contract-assurance", "--check"]},
        },
        "observation": {
            "observed_at": observed_at,
            "project_location": "local_project_root",
            "provider_location": "local_exact_provider_checkout",
        },
    }


def _compiled_children(*, ordered_values: tuple[str, ...] = ("a", "b")) -> dict[str, Any]:
    return {
        name: {"kind": name.removesuffix(".json"), "ordered_values": list(ordered_values)}
        for name in CHILD_NAMES
        if name != GENERATION_CONTEXT_NAME
    }


def _install_synthetic_contract_hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    def _semantic(name: str, payload: dict[str, Any]) -> str:
        value = payload["semantic"] if name == GENERATION_CONTEXT_NAME else payload
        return assurance._sha256_json(value)

    def _contract(name: str, payload: dict[str, Any]) -> str:
        return assurance._sha256_json({"name": name, "payload": payload})

    def _parents(
        children: dict[str, dict[str, Any]],
        *,
        generation_context_sha256: str,
    ) -> dict[str, dict[str, str]]:
        assert set(children) == set(CHILD_NAMES)
        return {
            name: (
                {}
                if name == GENERATION_CONTEXT_NAME
                else {"generation_context_sha256": generation_context_sha256}
            )
            for name in CHILD_NAMES
        }

    monkeypatch.setattr(assurance, "_child_semantic_sha256", _semantic)
    monkeypatch.setattr(assurance, "_contract_digest", _contract)
    monkeypatch.setattr(assurance, "_validate_parent_graph", _parents)
    monkeypatch.setattr(
        assurance,
        "_model_blockers",
        lambda _children: [
            {
                "child": "not-generated",
                "scope": "local_assurance",
                "code": "review_pending",
                "occurrence_count": 1,
            }
        ],
    )
    monkeypatch.setattr(
        assurance,
        "_validate_persisted_model_authorities",
        lambda *_args, **_kwargs: None,
    )


def _rewrite_manifest(path: Path, mutate: Any) -> None:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    mutate(manifest)
    manifest.pop("manifest_sha256", None)
    manifest.pop("manifest_semantic_sha256", None)
    manifest["manifest_semantic_sha256"] = assurance._sha256_json(
        assurance._manifest_semantic_payload(manifest)
    )
    manifest["manifest_sha256"] = assurance._sha256_json(manifest)
    manifest_bytes = assurance._canonical_bytes(manifest)
    path.write_bytes(manifest_bytes)

    admission_path = path.parent / assurance.ADMISSION_NAME
    admission = json.loads(admission_path.read_text(encoding="utf-8"))
    admission["assurance_manifest_sha256"] = assurance._sha256_bytes(manifest_bytes)
    admission_path.write_bytes(assurance._canonical_bytes(admission))
    _refresh_root_index(path.parent)


def _refresh_root_index(directory: Path) -> None:
    index_path = directory / assurance.GENERATION_INDEX_NAME
    index = json.loads(index_path.read_text(encoding="utf-8"))
    for record in index["members"]:
        encoded = (directory / record["name"]).read_bytes()
        record["size"] = len(encoded)
        record["file_sha256"] = assurance._sha256_bytes(encoded)
    index_path.write_bytes(assurance._canonical_bytes(index))


def _reseal_tampered_generation_child(
    directory: Path,
    *,
    name: str,
    mutate: Any,
) -> None:
    child_path = directory / name
    child = json.loads(child_path.read_text(encoding="utf-8"))
    mutate(child)
    encoded = assurance._canonical_bytes(child)
    child_path.write_bytes(encoded)

    children = {
        child_name: json.loads((directory / child_name).read_text(encoding="utf-8"))
        for child_name in CHILD_NAMES
    }
    context_sha = assurance._child_semantic_sha256(
        GENERATION_CONTEXT_NAME,
        children[GENERATION_CONTEXT_NAME],
    )
    parents = assurance._validate_parent_graph(
        children,
        generation_context_sha256=context_sha,
    )
    manifest_path = directory / assurance.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = manifest["children"]
    for record in records:
        child_name = record["name"]
        child_encoded = (directory / child_name).read_bytes()
        record.update(
            {
                "size": len(child_encoded),
                "file_sha256": assurance._sha256_bytes(child_encoded),
                "semantic_sha256": assurance._child_semantic_sha256(
                    child_name,
                    children[child_name],
                ),
                "contract_sha256": (
                    context_sha
                    if child_name == GENERATION_CONTEXT_NAME
                    else assurance._contract_digest(child_name, children[child_name])
                ),
                "parents": parents[child_name],
            }
        )
    blockers = assurance._model_blockers(children)
    semantic_sha = assurance._sha256_json(
        assurance._generation_semantic_payload(
            context_sha256=context_sha,
            child_records=records,
            blockers=blockers,
        )
    )
    manifest["model_blockers"] = blockers
    manifest["generation_semantic_sha256"] = semantic_sha
    manifest.pop("manifest_semantic_sha256", None)
    manifest.pop("manifest_sha256", None)
    manifest["manifest_semantic_sha256"] = assurance._sha256_json(
        assurance._manifest_semantic_payload(manifest)
    )
    manifest["manifest_sha256"] = assurance._sha256_json(manifest)
    manifest_encoded = assurance._canonical_bytes(manifest)
    manifest_path.write_bytes(manifest_encoded)

    authority_diff = assurance._first_extraction_authority_diff(
        generation_context=children[GENERATION_CONTEXT_NAME],
        manifest_file_sha256=assurance._sha256_bytes(manifest_encoded),
        generation_semantic_sha256=semantic_sha,
        child_records=records,
    )
    authority_diff_path = directory / assurance.AUTHORITY_SEMANTIC_DIFF_NAME
    authority_diff_encoded = assurance._canonical_bytes(authority_diff)
    authority_diff_path.write_bytes(authority_diff_encoded)
    authority_diff_decision = authority_diff["decision"]
    assert isinstance(authority_diff_decision, dict)
    authority_diff_decision = cast("dict[str, Any]", authority_diff_decision)
    admission = assurance._assurance_admission(
        generation_context=children[GENERATION_CONTEXT_NAME],
        assurance_manifest_sha256=assurance._sha256_bytes(manifest_encoded),
        generation_semantic_sha256=semantic_sha,
        authority_semantic_diff_sha256=assurance._sha256_bytes(authority_diff_encoded),
        authority_update_mode=authority_diff_decision["selected_mode"],
        first_extraction=authority_diff_decision["first_extraction"],
        model_status=manifest["gate_results"]["model_status"],
    )
    (directory / assurance.ADMISSION_NAME).write_bytes(
        assurance._canonical_bytes(admission.to_dict())
    )
    _refresh_root_index(directory)


def _rewrite_fixture_manifest(path: Path, mutate: Any) -> None:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    mutate(manifest)
    manifest["entries_sha256"] = assurance._sha256_json(manifest["entries"])
    manifest.pop("manifest_sha256", None)
    manifest["manifest_sha256"] = assurance._sha256_json(manifest)
    path.write_bytes(assurance._canonical_bytes(manifest))


def test_git_object_id_and_sha256_validators_remain_distinct() -> None:
    assert assurance._is_git_commit_sha("a" * 40)
    assert not assurance._is_git_commit_sha("a" * 64)
    assert assurance._is_sha256("a" * 64)
    assert not assurance._is_sha256("a" * 40)


def test_generation_context_rejects_sha256_sized_git_head() -> None:
    from nbadb.core.nba_api_provenance import (
        expected_nba_api_provider_authority,
        expected_nba_api_provider_evidence_receipt,
    )

    context = _context()
    context["semantic"]["provider"] = {
        "authority": expected_nba_api_provider_authority(),
        "evidence_receipt": expected_nba_api_provider_evidence_receipt(),
    }
    assurance._validate_generation_context_payload(context)
    context["semantic"]["project"]["git_head_sha"] = "b" * 64

    with pytest.raises(ContractAssuranceError, match="exact Git SHA-1"):
        assurance._validate_generation_context_payload(context)


def test_assurance_binds_request_surface_and_independent_inventory() -> None:
    from nbadb.core.nba_api_surface_inventory import build_nba_api_surface_inventory

    payload = build_nba_api_surface_inventory()
    assurance._validate_embedded_contract(assurance.PROVIDER_SURFACE_NAME, payload)

    drifted = json.loads(json.dumps(payload))
    drifted["source_atoms"][0]["endpoint_id"] = "count_preserving_replacement"
    drifted.pop("inventory_sha256")
    drifted["inventory_sha256"] = assurance._sha256_json(drifted)

    with pytest.raises(
        ContractAssuranceError,
        match="differs from the exact installed source",
    ):
        assurance._validate_embedded_contract(assurance.PROVIDER_SURFACE_NAME, drifted)


def test_assurance_binds_terminal_state_child_and_independent_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nbadb.core import nba_api_competition_identity as identity_module
    from nbadb.core import nba_api_competition_identity_verifier as identity_verifier
    from nbadb.core import nba_api_request_surface as request_module
    from nbadb.core import nba_api_request_surface_verifier as request_verifier
    from nbadb.core import nba_api_surface_inventory as surface_module
    from nbadb.core import nba_api_terminal_state as terminal_module
    from nbadb.core import nba_api_terminal_state_verifier as terminal_verifier

    terminal = terminal_module.load_pinned_terminal_state_payload()
    request = request_module.load_pinned_request_surface_payload()
    identity = identity_module.load_pinned_competition_identity_payload()
    surface = surface_module.build_nba_api_surface_inventory()
    terminal_proof = terminal_verifier.verify_pinned_terminal_state_authority()
    request_authority = request_module.pinned_request_surface_authority()
    request_inventory = request_verifier.build_independent_package_inventory()
    identity_proof = identity_verifier.verify_pinned_competition_identity_authority()
    calls: list[str] = []

    def _record(name: str, value: Any) -> Any:
        calls.append(name)
        return value

    monkeypatch.setattr(
        terminal_module,
        "load_pinned_terminal_state_payload",
        lambda: _record("terminal_loader", terminal),
    )
    monkeypatch.setattr(
        request_module,
        "load_pinned_request_surface_payload",
        lambda: _record("request_loader", request),
    )
    monkeypatch.setattr(
        identity_module,
        "load_pinned_competition_identity_payload",
        lambda: _record("identity_loader", identity),
    )
    monkeypatch.setattr(
        surface_module,
        "build_nba_api_surface_inventory",
        lambda: _record("request_independent_surface", surface),
    )
    monkeypatch.setattr(
        terminal_verifier,
        "verify_pinned_terminal_state_authority",
        lambda: _record("terminal_independent_proof", terminal_proof),
    )
    monkeypatch.setattr(
        request_module,
        "pinned_request_surface_authority",
        lambda: _record("request_authority", request_authority),
    )
    monkeypatch.setattr(
        request_verifier,
        "build_independent_package_inventory",
        lambda: _record("request_independent_inventory", request_inventory),
    )
    monkeypatch.setattr(
        identity_verifier,
        "verify_pinned_competition_identity_authority",
        lambda: _record("identity_independent_proof", identity_proof),
    )

    child, bindings = assurance._verified_terminal_state_child()

    assert child == terminal
    assert calls == [
        "terminal_loader",
        "request_loader",
        "identity_loader",
        "request_independent_surface",
        "terminal_independent_proof",
        "request_authority",
        "request_independent_inventory",
        "identity_independent_proof",
    ]
    runtime_index = CHILD_NAMES.index(assurance.RUNTIME_CONTRACT_NAME)
    assert CHILD_NAMES[runtime_index : runtime_index + 4] == (
        assurance.RUNTIME_CONTRACT_NAME,
        assurance.IMPLICIT_COMPETITION_CURRENT_SOURCE_NAME,
        assurance.TERMINAL_STATE_NAME,
        assurance.PROVIDER_SURFACE_NAME,
    )
    assert assurance.TERMINAL_STATE_NAME in assurance.CONTENT_REQUIRED_MEMBERS
    assert assurance.TERMINAL_STATE_NAME in assurance.REQUIRED_MEMBERS
    assert assurance.TERMINAL_STATE_NAME not in assurance.__all__
    assert assurance._contract_digest(assurance.TERMINAL_STATE_NAME, child) == (
        "471f594174107ccb8f582a6ab0459a356acf9daebd75ac55464475b3df792f4d"
    )
    assert bindings == {
        "terminal_policy_sha256": (
            "7226e797a685755311b7b9073f905d7288150e3412d52d95423ef0093548388d"
        ),
        "request_surface_sha256": (
            "ef6195829a9f1dad9f847094b79e88fae24dffc5c4df18e3d3e972f347f83733"
        ),
        "request_surface_payload_sha256": (
            "b310313f41cf97cf1b8f55e01bbe95868532f3008527bf5265a985628eca9052"
        ),
        "competition_identity_authority_sha256": (
            "dcbb1b9a9855b6d241651556f62911028d37b7a3678d0def9ae2a2a0779f8689"
        ),
        "competition_identity_payload_sha256": (
            "1420e8592f51ccdb03a6449dbd9514f87ad192ad4c14c6c7536844f85a0e3378"
        ),
    }
    assert assurance._parent_digests(
        assurance.TERMINAL_STATE_NAME,
        child,
        generation_context_sha256="f" * 64,
        children={},
    ) == {"generation_context_sha256": "f" * 64, **bindings}

    terminal_drift = json.loads(json.dumps(terminal))
    terminal_drift["false_green_counters"]["incomplete_state_promotions"] = 1
    terminal_body = dict(terminal_drift)
    terminal_body.pop("payload_sha256")
    terminal_drift["payload_sha256"] = assurance._sha256_json(terminal_body)
    with pytest.raises(ContractAssuranceError, match="terminal-state independent authority"):
        assurance._verified_terminal_state_child(
            terminal_payload=terminal_drift,
            request_payload=request,
            identity_payload=identity,
            provider_surface=surface,
        )

    request_drift = json.loads(json.dumps(request))
    request_drift["independent_proof"]["claim_status"] = "forged_resealed_claim"
    request_body = dict(request_drift)
    request_body.pop("payload_sha256")
    request_drift["payload_sha256"] = assurance._sha256_json(request_body)
    with pytest.raises(ContractAssuranceError, match="successor parent authorities"):
        assurance._verified_terminal_state_child(
            terminal_payload=terminal,
            request_payload=request_drift,
            identity_payload=identity,
            provider_surface=surface,
        )

    identity_drift = json.loads(json.dumps(identity))
    identity_drift["false_green_counters"]["model_green_claim_count"] += 1
    identity_body = dict(identity_drift)
    identity_body.pop("payload_sha256")
    authority_body = dict(identity_body)
    authority_body.pop("authority_sha256")
    identity_body["authority_sha256"] = assurance._sha256_json(authority_body)
    identity_drift["authority_sha256"] = identity_body["authority_sha256"]
    identity_drift["payload_sha256"] = assurance._sha256_json(identity_body)
    with pytest.raises(ContractAssuranceError, match="successor parent authorities"):
        assurance._verified_terminal_state_child(
            terminal_payload=terminal,
            request_payload=request,
            identity_payload=identity_drift,
            provider_surface=surface,
        )


def test_atomic_generation_writes_manifest_last_and_revalidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_synthetic_contract_hooks(monkeypatch)
    writes: list[str] = []
    original = assurance._write_json_new

    def _record(path: Path, payload: dict[str, Any]) -> tuple[int, str]:
        writes.append(path.name)
        return original(path, payload)

    monkeypatch.setattr(assurance, "_write_json_new", _record)
    generation = assurance._write_generation(
        output_dir=tmp_path / "generation-one",
        generation_context=_context(),
        compiled_children=_compiled_children(),
        expected_semantic_sha256=None,
    )

    assert writes == [
        *CHILD_NAMES,
        assurance.MANIFEST_NAME,
        assurance.AUTHORITY_SEMANTIC_DIFF_NAME,
        assurance.ADMISSION_NAME,
        assurance.GENERATION_INDEX_NAME,
    ]
    assert generation.manifest["gate_results"] == {
        "structural_generation": "GREEN",
        "semantic_determinism": "NOT_CHECKED",
        "model_green": False,
        "model_status": "RED",
        "data_green": "UNPROVEN",
        "populated_data_correctness": "NOT_EVALUATED",
        "live_availability": "NOT_EVALUATED",
        "publication": "NOT_EVALUATED",
        "external_gates": {
            "exact_sha_ci": "OPEN_EXTERNAL",
            "vpn_and_nba_probing": "OPEN_EXTERNAL",
            "extraction": "OPEN_EXTERNAL",
            "kaggle_readback": "OPEN_EXTERNAL",
            "permission_review": "OPEN_EXTERNAL",
        },
    }
    assert generation.admission.to_dict() == {
        "schema_version": 2,
        "kind": "nbadb_assurance_admission",
        "source_sha": "b" * 40,
        "assurance_manifest_sha256": assurance._sha256_bytes(
            (generation.directory / assurance.MANIFEST_NAME).read_bytes()
        ),
        "generation_semantic_sha256": generation.semantic_sha256,
        "provider_evidence_sha256": "a" * 64,
        "provider_authority_sha256": "e" * 64,
        "authority_semantic_diff_sha256": assurance._sha256_bytes(
            (generation.directory / assurance.AUTHORITY_SEMANTIC_DIFF_NAME).read_bytes()
        ),
        "authority_update_mode": "full",
        "first_extraction": True,
        "model_status": "RED",
    }
    assert generation.admission.model_status == "RED"
    assert generation.admission.is_production_admissible is True
    assert generation.generation_index["required_members"] == list(assurance.REQUIRED_MEMBERS)
    assert [record["name"] for record in generation.generation_index["members"]] == [
        assurance.MANIFEST_NAME,
        assurance.AUTHORITY_SEMANTIC_DIFF_NAME,
        assurance.ADMISSION_NAME,
    ]
    from nbadb.contracts.authority_semantic_diff_verifier import (
        VerifiedAuthoritySemanticDiffV1,
    )

    semantic_diff = VerifiedAuthoritySemanticDiffV1.from_canonical_bytes(
        (generation.directory / assurance.AUTHORITY_SEMANTIC_DIFF_NAME).read_bytes()
    )
    assert semantic_diff.decision.first_extraction is True
    assert semantic_diff.decision.selected_mode == "full"
    assert semantic_diff.decision.decision_reason == "first_extraction_requires_full"
    assert semantic_diff.decision.current.mandatory_child_ids == tuple(sorted(CHILD_NAMES))
    assert semantic_diff.verification.verification_status == "verified"
    assert generation.admission_sha256 == assurance._sha256_bytes(
        (generation.directory / assurance.ADMISSION_NAME).read_bytes()
    )
    assert generation.generation_index_sha256 == assurance._sha256_bytes(
        (generation.directory / assurance.GENERATION_INDEX_NAME).read_bytes()
    )
    assert assurance.validate_assurance_generation(generation.directory) == generation


def test_assurance_artifacts_do_not_persist_machine_absolute_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_synthetic_contract_hooks(monkeypatch)
    generation = assurance._write_generation(
        output_dir=tmp_path / "generation",
        generation_context=_context(),
        compiled_children=_compiled_children(),
        expected_semantic_sha256=None,
    )

    artifact_text = "\n".join(
        path.read_text(encoding="utf-8") for path in generation.directory.iterdir()
    )
    assert str(tmp_path) not in artifact_text
    assert "/machine/local" not in artifact_text


def test_upstream_child_redacts_provider_locations_without_changing_semantics() -> None:
    raw = {
        "docs_root": "/private/provider/checkout",
        "metadata_ledger": {"docs_root": "/private/provider/checkout", "count": 1},
        "bundle_digest": "a" * 64,
    }

    redacted = assurance._redact_upstream_locations(raw)

    assert redacted["docs_root"] == "<local-exact-nba-api-checkout>"
    assert redacted["metadata_ledger"]["docs_root"] == ("<local-exact-nba-api-checkout>")
    assert "/private/provider/checkout" not in json.dumps(redacted)
    assert assurance._upstream_semantic_payload(redacted) == (
        assurance._upstream_semantic_payload(raw)
    )


def test_fresh_generation_rejects_existing_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_synthetic_contract_hooks(monkeypatch)
    destination = tmp_path / "already-exists"
    destination.mkdir()

    with pytest.raises(ContractAssuranceError, match="already exists"):
        assurance._write_generation(
            output_dir=destination,
            generation_context=_context(),
            compiled_children=_compiled_children(),
            expected_semantic_sha256=None,
        )


@pytest.mark.parametrize("mutation", ["extra", "missing"])
def test_generation_validation_rejects_extra_or_missing_members(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    _install_synthetic_contract_hooks(monkeypatch)
    generation = assurance._write_generation(
        output_dir=tmp_path / "generation",
        generation_context=_context(),
        compiled_children=_compiled_children(),
        expected_semantic_sha256=None,
    )
    if mutation == "extra":
        (generation.directory / "stale.json").write_text("{}", encoding="utf-8")
    else:
        (generation.directory / assurance.METRIC_NAME).unlink()

    with pytest.raises(ContractAssuranceError, match="extra, or missing"):
        assurance.validate_assurance_generation(generation.directory)


def test_generation_validation_rejects_missing_admission_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_synthetic_contract_hooks(monkeypatch)
    generation = assurance._write_generation(
        output_dir=tmp_path / "generation",
        generation_context=_context(),
        compiled_children=_compiled_children(),
        expected_semantic_sha256=None,
    )
    (generation.directory / assurance.ADMISSION_NAME).unlink()

    with pytest.raises(ContractAssuranceError, match="extra, or missing"):
        assurance.validate_assurance_generation(generation.directory)


def test_generation_validation_rejects_tampered_admission_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_synthetic_contract_hooks(monkeypatch)
    generation = assurance._write_generation(
        output_dir=tmp_path / "generation",
        generation_context=_context(),
        compiled_children=_compiled_children(),
        expected_semantic_sha256=None,
    )
    admission_path = generation.directory / assurance.ADMISSION_NAME
    admission = json.loads(admission_path.read_text(encoding="utf-8"))
    admission["provider_evidence_sha256"] = "9" * 64
    admission_path.write_bytes(assurance._canonical_bytes(admission))

    with pytest.raises(ContractAssuranceError, match="root member bytes differ"):
        assurance.validate_assurance_generation(generation.directory)


def test_generation_validation_rejects_reindexed_admission_evidence_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_synthetic_contract_hooks(monkeypatch)
    generation = assurance._write_generation(
        output_dir=tmp_path / "generation",
        generation_context=_context(),
        compiled_children=_compiled_children(),
        expected_semantic_sha256=None,
    )
    admission_path = generation.directory / assurance.ADMISSION_NAME
    admission = json.loads(admission_path.read_text(encoding="utf-8"))
    admission["provider_evidence_sha256"] = "9" * 64
    admission_path.write_bytes(assurance._canonical_bytes(admission))
    _refresh_root_index(generation.directory)

    with pytest.raises(ContractAssuranceError, match="does not match generation evidence"):
        assurance.validate_assurance_generation(generation.directory)


def test_generation_validation_rejects_unknown_admission_fields_even_if_reindexed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_synthetic_contract_hooks(monkeypatch)
    generation = assurance._write_generation(
        output_dir=tmp_path / "generation",
        generation_context=_context(),
        compiled_children=_compiled_children(),
        expected_semantic_sha256=None,
    )
    admission_path = generation.directory / assurance.ADMISSION_NAME
    admission = json.loads(admission_path.read_text(encoding="utf-8"))
    admission["message"] = "untrusted diagnostic"
    admission_path.write_bytes(assurance._canonical_bytes(admission))
    _refresh_root_index(generation.directory)

    with pytest.raises(ContractAssuranceError, match="admission member is invalid"):
        assurance.validate_assurance_generation(generation.directory)


def test_generation_validation_rejects_unknown_root_index_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_synthetic_contract_hooks(monkeypatch)
    generation = assurance._write_generation(
        output_dir=tmp_path / "generation",
        generation_context=_context(),
        compiled_children=_compiled_children(),
        expected_semantic_sha256=None,
    )
    index_path = generation.directory / assurance.GENERATION_INDEX_NAME
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["absolute_path"] = "/private/generation"
    index_path.write_bytes(assurance._canonical_bytes(index))

    with pytest.raises(ContractAssuranceError, match="index fields do not match"):
        assurance.validate_assurance_generation(generation.directory)


@pytest.mark.parametrize("member_kind", ["symlink", "fifo"])
def test_generation_validation_rejects_non_regular_members_before_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    member_kind: str,
) -> None:
    _install_synthetic_contract_hooks(monkeypatch)
    generation = assurance._write_generation(
        output_dir=tmp_path / "generation",
        generation_context=_context(),
        compiled_children=_compiled_children(),
        expected_semantic_sha256=None,
    )
    member = generation.directory / assurance.METRIC_NAME
    member.unlink()
    if member_kind == "symlink":
        target = tmp_path / "outside.json"
        target.write_text("{}", encoding="utf-8")
        member.symlink_to(target)
    else:
        if not hasattr(os, "mkfifo"):
            pytest.skip("FIFOs are unavailable on this platform")
        os.mkfifo(member)

    with pytest.raises(ContractAssuranceError, match="is not a regular file"):
        assurance.validate_assurance_generation(generation.directory)


def test_regular_member_read_rejects_path_swap_after_descriptor_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    member = tmp_path / "member.json"
    replacement = tmp_path / "replacement.json"
    member.write_text("{}", encoding="utf-8")
    replacement.write_text('{"replacement":true}', encoding="utf-8")
    original_lstat = assurance.os.lstat

    def _swap_then_lstat(path: Path) -> os.stat_result:
        member.unlink()
        replacement.rename(member)
        return original_lstat(path)

    monkeypatch.setattr(assurance.os, "lstat", _swap_then_lstat)

    with pytest.raises(ContractAssuranceError, match="changed during validation"):
        assurance._read_regular_member(member, context="assurance member")


def test_generation_validation_rejects_parent_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_synthetic_contract_hooks(monkeypatch)
    generation = assurance._write_generation(
        output_dir=tmp_path / "generation",
        generation_context=_context(),
        compiled_children=_compiled_children(),
        expected_semantic_sha256=None,
    )

    def _mutate(manifest: dict[str, Any]) -> None:
        manifest["children"][1]["parents"] = {"generation_context_sha256": "f" * 64}

    _rewrite_manifest(generation.directory / assurance.MANIFEST_NAME, _mutate)

    with pytest.raises(ContractAssuranceError, match="parent digests differ"):
        assurance.validate_assurance_generation(generation.directory)


@pytest.mark.parametrize(
    "name",
    [
        assurance.FIELD_FATE_STRUCTURE_NAME,
        assurance.FIELD_FATE_STRUCTURE_VERIFICATION_NAME,
        assurance.ANALYTICAL_NEEDS_NAME,
        assurance.MODEL_CANDIDATE_CENSUS_NAME,
        assurance.STABLE_MODEL_DISPOSITION_NAME,
        assurance.STAR_SEMANTIC_INVENTORY_NAME,
    ],
)
def test_persisted_validation_rejects_self_consistently_resealed_model_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    authority_validator = assurance._validate_persisted_model_authorities
    _install_synthetic_contract_hooks(monkeypatch)
    original_children = _compiled_children()
    generation = assurance._write_generation(
        output_dir=tmp_path / "generation",
        generation_context=_context(),
        compiled_children=original_children,
        expected_semantic_sha256=None,
    )
    _reseal_tampered_generation_child(
        generation.directory,
        name=name,
        mutate=lambda child: child["ordered_values"].append("self-consistent-forgery"),
    )

    expected = {
        child_name: original_children[child_name]
        for child_name in assurance._PERSISTED_MODEL_AUTHORITY_NAMES
    }
    monkeypatch.setattr(
        assurance,
        "_validate_persisted_model_authorities",
        authority_validator,
    )
    monkeypatch.setattr(
        assurance,
        "_freeze_generation_context",
        lambda **_kwargs: _context(),
    )
    monkeypatch.setattr(
        assurance,
        "_recompile_persisted_model_authorities",
        lambda **_kwargs: expected,
    )

    with pytest.raises(
        ContractAssuranceError,
        match=f"differs from current authority: {name}",
    ):
        assurance.validate_assurance_generation(
            generation.directory,
            project_root=tmp_path,
            endpoint_analysis_docs_root=tmp_path,
        )


def test_source_drift_fails_before_manifest_is_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_synthetic_contract_hooks(monkeypatch)
    first = _context()
    second = _context()
    second["semantic"]["project"]["source_sha256"] = "9" * 64
    observations = iter((first, second))
    monkeypatch.setattr(
        assurance,
        "_freeze_generation_context",
        lambda **_kwargs: next(observations),
    )
    monkeypatch.setattr(
        assurance,
        "_compile_profile_children",
        lambda **_kwargs: _compiled_children(),
    )
    destination = tmp_path / "generation"

    with pytest.raises(ContractAssuranceError, match="changed during generation"):
        assurance.generate_pre_extraction_assurance(
            endpoint_analysis_docs_root=tmp_path,
            output_dir=destination,
            project_root=tmp_path,
        )

    assert destination.is_dir()
    assert not (destination / assurance.MANIFEST_NAME).exists()


def test_timestamps_and_local_paths_are_nonsemantic_but_order_is_semantic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_synthetic_contract_hooks(monkeypatch)
    first = _context(observed_at="2026-08-12T00:00:00+00:00")
    second = _context(observed_at="2026-08-13T00:00:00+00:00")
    second["observation"]["project_location"] = "another_nonsemantic_label"

    assert assurance._child_semantic_sha256(GENERATION_CONTEXT_NAME, first) == (
        assurance._child_semantic_sha256(GENERATION_CONTEXT_NAME, second)
    )
    ordered = _compiled_children(ordered_values=("a", "b"))[assurance.METRIC_NAME]
    reordered = _compiled_children(ordered_values=("b", "a"))[assurance.METRIC_NAME]
    assert assurance._child_semantic_sha256(assurance.METRIC_NAME, ordered) != (
        assurance._child_semantic_sha256(assurance.METRIC_NAME, reordered)
    )


def test_second_generation_binds_identical_semantic_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_synthetic_contract_hooks(monkeypatch)
    first = assurance._write_generation(
        output_dir=tmp_path / "first",
        generation_context=_context(observed_at="2026-08-12T00:00:00+00:00"),
        compiled_children=_compiled_children(),
        expected_semantic_sha256=None,
    )
    second = assurance._write_generation(
        output_dir=tmp_path / "second",
        generation_context=_context(observed_at="2026-08-13T00:00:00+00:00"),
        compiled_children=_compiled_children(),
        expected_semantic_sha256=first.semantic_sha256,
    )

    assert second.semantic_sha256 == first.semantic_sha256
    assert (
        second.manifest["manifest_semantic_sha256"] == (first.manifest["manifest_semantic_sha256"])
    )
    assert second.manifest["gate_results"]["semantic_determinism"] == "GREEN"
    assert second.manifest["gate_results"]["model_status"] == "RED"


def test_check_receipt_exposes_second_admission_and_root_index_digests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_synthetic_contract_hooks(monkeypatch)
    observations = iter(
        _context(observed_at=f"2026-08-{day:02d}T00:00:00+00:00") for day in range(10, 14)
    )
    monkeypatch.setattr(
        assurance,
        "_freeze_generation_context",
        lambda **_kwargs: next(observations),
    )
    monkeypatch.setattr(
        assurance,
        "_compile_profile_children",
        lambda **_kwargs: _compiled_children(),
    )

    result = assurance.check_pre_extraction_assurance(
        endpoint_analysis_docs_root=tmp_path,
        output_root=tmp_path / "output",
        project_root=tmp_path,
    )
    generations = [
        assurance.validate_assurance_generation(path) for path in (tmp_path / "output").iterdir()
    ]
    second = next(
        generation
        for generation in generations
        if generation.manifest["gate_results"]["semantic_determinism"] == "GREEN"
    )

    assert result["assurance_admission_location"] == assurance.ADMISSION_NAME
    assert result["assurance_admission_sha256"] == second.admission_sha256
    assert result["assurance_admission_status"] == "RED"
    assert result["assurance_generation_index_location"] == assurance.GENERATION_INDEX_NAME
    assert result["assurance_generation_index_sha256"] == second.generation_index_sha256


def test_second_generation_rejects_order_drift_before_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_synthetic_contract_hooks(monkeypatch)
    first = assurance._write_generation(
        output_dir=tmp_path / "first",
        generation_context=_context(),
        compiled_children=_compiled_children(),
        expected_semantic_sha256=None,
    )
    second_path = tmp_path / "second"

    with pytest.raises(ContractAssuranceError, match="different semantic digest"):
        assurance._write_generation(
            output_dir=second_path,
            generation_context=_context(),
            compiled_children=_compiled_children(ordered_values=("b", "a")),
            expected_semantic_sha256=first.semantic_sha256,
        )

    assert second_path.is_dir()
    assert not (second_path / assurance.MANIFEST_NAME).exists()


def test_model_blockers_preserve_unresolved_implemented_and_receipt_gaps() -> None:
    children = {
        assurance.FIELD_FATE_STRUCTURE_VERIFICATION_NAME: {"summary": {"open_blocker_count": 0}},
        assurance.MODEL_CANDIDATE_CENSUS_NAME: {
            "summary": {"blocker_code_counts": {"candidate_structural_gap": 5}}
        },
        assurance.STABLE_MODEL_DISPOSITION_NAME: {
            "blockers": [
                {"candidate_id": "candidate:a", "code": "candidate_disposition_missing"},
                {"candidate_id": "candidate:b", "code": "candidate_disposition_missing"},
            ]
        },
        assurance.STAR_SEMANTIC_INVENTORY_NAME: {
            "blockers": [
                {"scope_id": "fact_a", "code": "semantic_contract_missing"},
                {"scope_id": "fact_b", "code": "semantic_contract_missing"},
            ]
        },
        assurance.FIELD_FATE_NAME: {
            "summary": {
                "blocker_summary": [
                    {"scope": "provider_field", "code": "unreviewed", "occurrence_count": 2}
                ]
            }
        },
        assurance.STAR_TABLE_NAME: {
            "summary": {
                "blocker_summary": [
                    {"code": "grain_unreviewed", "table_count": 1, "occurrence_count": 1}
                ]
            }
        },
        assurance.TEMPORAL_NAME: {"summary": {"unknown_availability_scope_count": 3}},
        assurance.METRIC_NAME: {"summary": {"blocker_counts": {"formula_unreviewed": 4}}},
        assurance.BRONZE_CONTRACT_NAME: {"summary": {"blocking_zero_column_table_count": 0}},
    }

    blockers = assurance._model_blockers(children)
    codes = {item["code"] for item in blockers}

    assert {
        "unreviewed",
        "grain_unreviewed",
        "availability_unknown_pending_reviewed_evidence",
        "formula_unreviewed",
        "candidate_structural_gap",
        "candidate_disposition_missing",
        "semantic_contract_missing",
        "independent_local_test_receipt_not_bound",
        "independent_review_receipt_not_bound",
    } <= codes


def test_raw_request_schema_is_a_mandatory_exact_child() -> None:
    from nbadb.contracts.raw_request_schema_contract import (
        compile_raw_request_schema_contract,
    )

    contract = compile_raw_request_schema_contract()
    payload = contract.to_dict()

    assert assurance.RAW_REQUEST_SCHEMA_NAME in CHILD_NAMES
    assert assurance.RAW_REQUEST_SCHEMA_NAME in assurance.CONTENT_REQUIRED_MEMBERS
    assert assurance._contract_digest(assurance.RAW_REQUEST_SCHEMA_NAME, payload) == (
        contract.contract_sha256
    )
    assert assurance._parent_digests(
        assurance.RAW_REQUEST_SCHEMA_NAME,
        payload,
        generation_context_sha256="f" * 64,
        children={},
    ) == {"generation_context_sha256": "f" * 64}
    assurance._validate_embedded_contract(assurance.RAW_REQUEST_SCHEMA_NAME, payload)

    forged = dict(payload)
    forged["contract_sha256"] = "0" * 64
    with pytest.raises(ContractAssuranceError, match="raw-request schema child is invalid"):
        assurance._validate_embedded_contract(assurance.RAW_REQUEST_SCHEMA_NAME, forged)


def test_current_source_authority_is_a_mandatory_authenticated_child() -> None:
    child, bindings = assurance._verified_implicit_competition_current_source_child()

    assert assurance.IMPLICIT_COMPETITION_CURRENT_SOURCE_NAME in CHILD_NAMES
    assert assurance.IMPLICIT_COMPETITION_CURRENT_SOURCE_NAME in (
        assurance.CONTENT_REQUIRED_MEMBERS
    )
    assert (
        assurance._contract_digest(
            assurance.IMPLICIT_COMPETITION_CURRENT_SOURCE_NAME,
            child,
        )
        == "cb16435d02467e2aae1888e665f806593a74736faaf9e6fcfbc83c133097acfc"
    )
    assert assurance._parent_digests(
        assurance.IMPLICIT_COMPETITION_CURRENT_SOURCE_NAME,
        child,
        generation_context_sha256="f" * 64,
        children={},
    ) == {"generation_context_sha256": "f" * 64, **bindings}
    assurance._validate_embedded_contract(
        assurance.IMPLICIT_COMPETITION_CURRENT_SOURCE_NAME,
        child,
    )

    forged = json.loads(json.dumps(child))
    forged["generation_proof"]["candidate"]["source_inventory_sha256"] = "0" * 64
    with pytest.raises(
        ContractAssuranceError,
        match="differs from the authenticated authority",
    ):
        assurance._validate_embedded_contract(
            assurance.IMPLICIT_COMPETITION_CURRENT_SOURCE_NAME,
            forged,
        )


@pytest.mark.parametrize(
    ("case", "error"),
    [
        ("rights_policy", "rights policy contract"),
        ("sanitization_policy", "sanitization policy contract"),
        ("entry_rights_reference", "entry policy reference"),
        ("entry_sanitization_reference", "entry policy reference"),
    ],
)
def test_fixture_manifest_rejects_policy_or_entry_reference_drift(
    tmp_path: Path,
    case: str,
    error: str,
) -> None:
    source_root = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / ("nba_api_contract")
    fixture_root = tmp_path / "tests" / "fixtures" / "nba_api_contract"
    fixture_root.parent.mkdir(parents=True)
    shutil.copytree(source_root, fixture_root)
    manifest_path = fixture_root / "manifest.json"

    def _mutate(manifest: dict[str, Any]) -> None:
        if case == "rights_policy":
            manifest["rights_policies"]["repo-synthetic-mit"]["license_identifier"] = "OTHER"
        elif case == "sanitization_policy":
            manifest["sanitization_policies"]["synthetic-none"] = "unreviewed"
        elif case == "entry_rights_reference":
            manifest["entries"][0]["rights_policy_id"] = "missing"
        elif case == "entry_sanitization_reference":
            manifest["entries"][0]["sanitization_policy_id"] = "missing"

    _rewrite_fixture_manifest(manifest_path, _mutate)

    with pytest.raises(ContractAssuranceError, match=error):
        assurance._fixture_manifest(tmp_path)


def test_cli_exact_check_reports_structural_green_model_red_and_data_unproven(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nbadb.cli.app import app
    from nbadb.cli.commands import contract_assurance as command_module

    monkeypatch.setattr(
        command_module,
        "check_pre_extraction_assurance",
        lambda **_kwargs: {
            "assurance_location": "second_fresh_generation_directory",
            "generation_semantic_sha256": "a" * 64,
            "semantic_determinism": "GREEN",
            "structural_generation": "GREEN",
            "model_green": False,
            "model_status": "RED",
            "assurance_admission_location": assurance.ADMISSION_NAME,
            "assurance_admission_sha256": "b" * 64,
            "assurance_admission_status": "RED",
            "assurance_generation_index_location": assurance.GENERATION_INDEX_NAME,
            "assurance_generation_index_sha256": "c" * 64,
            "data_green": "UNPROVEN",
            "model_blockers": [
                {
                    "child": "metric-use-case-contract.json",
                    "scope": "public_numeric_column",
                    "code": "formula_unreviewed",
                    "occurrence_count": 4,
                }
            ],
        },
    )

    result = CliRunner().invoke(
        app,
        [
            "contract-assurance",
            "--profile",
            "pre-extraction",
            "--endpoint-analysis-docs-root",
            str(tmp_path),
            "--check",
            "--output-root",
            str(tmp_path / "output"),
        ],
    )

    assert result.exit_code == 1
    assert "Structural generation: GREEN" in result.output
    assert "Semantic determinism: GREEN" in result.output
    assert "MODEL-GREEN: RED" in result.output
    assert "DATA-GREEN: UNPROVEN" in result.output
    assert f"Assurance admission: {assurance.ADMISSION_NAME}" in result.output
    assert f"Assurance admission SHA-256: {'b' * 64}" in result.output
    assert "Assurance admission status: RED" in result.output
    assert f"Assurance generation index: {assurance.GENERATION_INDEX_NAME}" in result.output
    assert f"Assurance generation index SHA-256: {'c' * 64}" in result.output
    assert str(tmp_path.resolve()) not in result.output


def test_cli_help_is_registered_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    from nbadb.cli.app import app

    monkeypatch.setenv("COLUMNS", "200")
    result = CliRunner().invoke(app, ["contract-assurance", "--help"])

    assert result.exit_code == 0
    assert "--endpoint-analysis-docs-root" in result.output
    assert "--check" in result.output


def test_cli_help_documents_diagnostic_exit_semantics() -> None:
    """The MODEL-oriented exit code must be labeled diagnostic, not DATA."""

    from nbadb.cli.app import app

    result = CliRunner().invoke(app, ["contract-assurance", "--help"])

    assert result.exit_code == 0
    assert "MODEL diagnostic, not a DATA gate" in result.output
    assert "exit 0 means MODEL-GREEN" in result.output
    assert "MODEL-RED" in result.output
    assert "UNPROVEN" in result.output
    assert "publication DATA authority" in result.output
