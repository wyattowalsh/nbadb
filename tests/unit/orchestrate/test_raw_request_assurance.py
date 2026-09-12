"""Focused tests for assurance-derived raw-request field/model authority."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from nbadb.contracts.assurance import AssuranceGeneration
from nbadb.contracts.assurance_admission import AssuranceAdmission
from nbadb.orchestrate import raw_request_assurance as authority_module
from nbadb.orchestrate.raw_request_assurance import (
    RawRequestAssuranceAuthorityV2,
    RawRequestAssuranceError,
    load_raw_request_assurance_authority,
    validate_raw_request_assurance_authority,
)

if TYPE_CHECKING:
    from pathlib import Path


def _admission(*, model_status: str = "GREEN") -> AssuranceAdmission:
    return AssuranceAdmission(
        source_sha="a" * 40,
        assurance_manifest_sha256="1" * 64,
        generation_semantic_sha256="2" * 64,
        provider_evidence_sha256="3" * 64,
        provider_authority_sha256="4" * 64,
        authority_semantic_diff_sha256="5" * 64,
        authority_update_mode="full",
        first_extraction=True,
        model_status=model_status,  # type: ignore[arg-type]
    )


def _generation(
    tmp_path: Path,
    *,
    admission: AssuranceAdmission | None = None,
    duplicate_name: str | None = None,
    omit_name: str | None = None,
) -> AssuranceGeneration:
    selected = (
        *authority_module._FIELD_AUTHORITY_CHILD_NAMES,  # noqa: SLF001
        *authority_module._MODEL_AUTHORITY_CHILD_NAMES,  # noqa: SLF001
    )
    records = [
        {
            "name": name,
            "contract_sha256": f"{index + 6:064x}",
        }
        for index, name in enumerate(selected)
        if name != omit_name
    ]
    if duplicate_name is not None:
        records.append(
            {
                "name": duplicate_name,
                "contract_sha256": "f" * 64,
            }
        )
    resolved = admission or _admission()
    return AssuranceGeneration(
        directory=tmp_path,
        manifest={
            "children": records,
            "generation_semantic_sha256": resolved.generation_semantic_sha256,
            "gate_results": {"model_green": resolved.model_status == "GREEN"},
        },
        admission=resolved,
        generation_index={},
        generation_index_sha256="6" * 64,
    )


def _load_generation(
    generation: AssuranceGeneration,
    monkeypatch: pytest.MonkeyPatch,
) -> RawRequestAssuranceAuthorityV2:
    monkeypatch.setattr(
        authority_module,
        "validate_assurance_generation",
        lambda *_args, **_kwargs: generation,
    )
    return load_raw_request_assurance_authority(
        generation.directory,
        project_root=generation.directory / "project",
        endpoint_analysis_docs_root=generation.directory / "nba-api",
    )


def test_compile_derives_both_digests_from_exact_green_child_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _load_generation(_generation(tmp_path), monkeypatch)

    assert type(authority) is RawRequestAssuranceAuthorityV2
    assert authority.source_sha == "a" * 40
    assert authority.assurance_admission_sha256 == _admission().sha256
    assert authority.assurance_manifest_sha256 == "1" * 64
    assert authority.generation_semantic_sha256 == "2" * 64
    assert authority.provider_evidence_sha256 == "3" * 64
    assert authority.provider_authority_sha256 == "4" * 64
    assert len(authority.field_children) == len(
        authority_module._FIELD_AUTHORITY_CHILD_NAMES  # noqa: SLF001
    )
    assert len(authority.model_children) == len(
        authority_module._MODEL_AUTHORITY_CHILD_NAMES  # noqa: SLF001
    )
    assert authority.field_authority_sha256 != authority.model_authority_sha256


def test_authority_rejects_direct_self_consistent_reseal_without_loader_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _load_generation(_generation(tmp_path), monkeypatch)
    forged_children = (
        (authority.field_children[0][0], "e" * 64),
        *authority.field_children[1:],
    )
    forged_field = authority_module._authority_digest(  # noqa: SLF001
        kind="nbadb_raw_request_field_authority",
        source_sha=authority.source_sha,
        assurance_admission_sha256=authority.assurance_admission_sha256,
        assurance_manifest_sha256=authority.assurance_manifest_sha256,
        generation_semantic_sha256=authority.generation_semantic_sha256,
        generation_index_sha256=authority.generation_index_sha256,
        provider_evidence_sha256=authority.provider_evidence_sha256,
        provider_authority_sha256=authority.provider_authority_sha256,
        children=forged_children,
    )
    forged = replace(
        authority,
        field_children=forged_children,
        field_authority_sha256=forged_field,
    )

    with pytest.raises(
        RawRequestAssuranceError,
        match="lacks current-process independent generation provenance",
    ):
        validate_raw_request_assurance_authority(forged)

    with pytest.raises(RawRequestAssuranceError, match="generation provenance"):
        validate_raw_request_assurance_authority(
            replace(authority, validation_provenance_sha256="0" * 64)
        )
    assert not hasattr(authority_module, "_VALIDATED_GENERATION_TOKEN")


def test_compile_rejects_red_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    red = _admission(model_status="RED")

    # Under the locked advisory semantics a RED model status stays admissible
    # as an admission, but raw-request assurance authority still fails closed
    # through the exact MODEL-GREEN evidence gate.
    with pytest.raises(
        RawRequestAssuranceError,
        match="not exact MODEL-GREEN evidence",
    ):
        _load_generation(_generation(tmp_path, admission=red), monkeypatch)


def test_compile_rejects_duplicate_or_missing_authority_children(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = authority_module._FIELD_AUTHORITY_CHILD_NAMES[0]  # noqa: SLF001
    with pytest.raises(
        RawRequestAssuranceError,
        match="lacks required authority children",
    ):
        _load_generation(_generation(tmp_path, omit_name=missing), monkeypatch)

    duplicate = authority_module._MODEL_AUTHORITY_CHILD_NAMES[0]  # noqa: SLF001
    with pytest.raises(
        RawRequestAssuranceError,
        match="duplicated",
    ):
        _load_generation(
            _generation(tmp_path, duplicate_name=duplicate),
            monkeypatch,
        )


def test_load_revalidates_generation_against_explicit_source_and_upstream_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation = _generation(tmp_path / "generation")
    observed: dict[str, object] = {}

    def _validate(
        directory: Path | str,
        *,
        project_root: Path | str | None = None,
        endpoint_analysis_docs_root: Path | str | None = None,
    ) -> AssuranceGeneration:
        observed.update(
            directory=directory,
            project_root=project_root,
            endpoint_analysis_docs_root=endpoint_analysis_docs_root,
        )
        return generation

    monkeypatch.setattr(authority_module, "validate_assurance_generation", _validate)

    authority = load_raw_request_assurance_authority(
        generation.directory,
        project_root=tmp_path / "project",
        endpoint_analysis_docs_root=tmp_path / "nba-api",
    )

    assert type(authority) is RawRequestAssuranceAuthorityV2
    assert observed == {
        "directory": generation.directory,
        "project_root": tmp_path / "project",
        "endpoint_analysis_docs_root": tmp_path / "nba-api",
    }
