from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import cast

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = _PROJECT_ROOT / "scripts/assurance/generate_implicit_competition_author_proof.py"
_SPEC = importlib.util.spec_from_file_location(
    "generate_implicit_competition_author_proof",
    _SCRIPT_PATH,
)
assert _SPEC is not None and _SPEC.loader is not None
subject = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = subject
_SPEC.loader.exec_module(subject)


def _copy_project_inputs(destination: Path) -> None:
    for relative in subject._OBSERVED_PROJECT_PATHS:
        source = _PROJECT_ROOT / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def _decode(raw: bytes) -> dict[str, object]:
    value = json.loads(raw)
    assert isinstance(value, dict)
    return value


def test_author_bundle_is_provider_free_and_byte_deterministic(tmp_path: Path) -> None:
    source = _SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "nba_api" not in imports
    assert not imports.intersection({"httpx", "requests", "socket", "urllib"})

    first = subject.author_bundle_bytes(_PROJECT_ROOT)
    second = subject.author_bundle_bytes(_PROJECT_ROOT)
    assert first == second
    assert set(first) == {subject.PROOF_FILENAME, subject.RECEIPT_FILENAME}
    assert str(tmp_path) not in first[subject.RECEIPT_FILENAME].decode("utf-8")

    proof = _decode(first[subject.PROOF_FILENAME])
    receipt = _decode(first[subject.RECEIPT_FILENAME])
    assert proof["proof_sha256"] == receipt["proof_sha256"]
    assert receipt["proof_raw_sha256"] == hashlib.sha256(first[subject.PROOF_FILENAME]).hexdigest()
    assert receipt["provider_authority_sha256"] == subject.PROVIDER_AUTHORITY_SHA256
    provider_validation = cast("dict[str, object]", receipt["provider_validation"])
    assert isinstance(provider_validation, dict)
    execution_surface = cast(
        "dict[str, object]", provider_validation["generator_execution_surface"]
    )
    assert isinstance(execution_surface, dict)
    assert execution_surface == {
        "direct_nba_api_imports": [],
        "direct_network_imports": [],
        "direct_network_operation_calls": [],
        "direct_provider_endpoint_calls": [],
        "generator_path": subject.GENERATOR_PATH,
        "generator_sha256": hashlib.sha256(_SCRIPT_PATH.read_bytes()).hexdigest(),
        "package_import_side_effects_attested_absent": False,
        "scope": "direct_generator_ast_only",
    }
    assert receipt["author_task_id"] == "A1.3a-repair-12"
    assert receipt["author_role"] == "current-source-author"
    independence = cast("dict[str, object]", receipt["root_independence"])
    assert isinstance(independence, dict)
    assert independence["root_count"] == 3
    assert independence["member_count"] == len(subject.AUTHORITY_INPUT_PATHS)
    assert independence["transient_paths_recorded"] is False
    inventory = cast("list[dict[str, object]]", receipt["output_inventory"])
    assert isinstance(inventory, list)
    assert [item["path"] for item in inventory] == sorted(item["path"] for item in inventory)


def test_create_then_check_never_overwrites_existing_outputs(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _copy_project_inputs(project)
    output = tmp_path / "author"
    first = subject.generate_author_bundle(project_root=project, output_dir=output)
    proof_before = (output / subject.PROOF_FILENAME).read_bytes()
    receipt_before = (output / subject.RECEIPT_FILENAME).read_bytes()

    checked = subject.generate_author_bundle(
        project_root=project,
        output_dir=output,
        check=True,
    )
    repeated = subject.generate_author_bundle(project_root=project, output_dir=output)
    assert checked == repeated == first
    assert (output / subject.PROOF_FILENAME).read_bytes() == proof_before
    assert (output / subject.RECEIPT_FILENAME).read_bytes() == receipt_before

    (output / subject.PROOF_FILENAME).write_bytes(b"{}")
    with pytest.raises(subject.AuthorProofError, match="existing author output differs"):
        subject.generate_author_bundle(project_root=project, output_dir=output)
    assert (output / subject.PROOF_FILENAME).read_bytes() == b"{}"


def test_provider_pin_is_rederived_without_importing_upstream(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _copy_project_inputs(project)
    provenance = project / subject.PROVIDER_PROVENANCE_PATH
    original = provenance.read_text(encoding="utf-8")
    provenance.write_text(original.replace('NBA_API_VERSION = "1.11.4"', 'NBA_API_VERSION = "0"'))

    with pytest.raises(subject.AuthorProofError, match="differs from the frozen pin"):
        subject.author_bundle_bytes(project)


def test_generation_fails_closed_if_project_source_drifts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    _copy_project_inputs(project)
    original_generate = subject.generate_implicit_competition_generation_proof
    changed = project / subject.SOURCE_PATHS[0]

    def mutate_after_generation(*args: object, **kwargs: object) -> object:
        proof = original_generate(*args, **kwargs)
        changed.write_bytes(changed.read_bytes() + b"\n# concurrent drift\n")
        return proof

    monkeypatch.setattr(
        subject,
        "generate_implicit_competition_generation_proof",
        mutate_after_generation,
    )
    with pytest.raises(subject.AuthorProofError, match="drifted during generation"):
        subject.author_bundle_bytes(project)
