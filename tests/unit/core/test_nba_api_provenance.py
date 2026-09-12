from __future__ import annotations

import json
from pathlib import Path

import pytest

import nbadb.core.nba_api_provenance as provenance


def _install_valid_provider_fakes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source" / "src" / "nba_api"
    installed = tmp_path / "installed" / "nba_api"
    source.mkdir(parents=True)
    installed.mkdir(parents=True)
    installed_init = installed / "__init__.py"
    installed_init.write_text("", encoding="utf-8")
    monkeypatch.setattr(provenance.nba_api, "__file__", str(installed_init))
    monkeypatch.setattr(
        provenance.importlib.metadata,
        "version",
        lambda _name: provenance.NBA_API_VERSION,
    )
    monkeypatch.setattr(
        provenance,
        "_locked_archive_hashes",
        lambda _path: (
            provenance.NBA_API_VERSION,
            provenance.NBA_API_SDIST_SHA256,
            provenance.NBA_API_WHEEL_SHA256,
        ),
    )
    monkeypatch.setattr(provenance, "_package_root", lambda _root: source)
    inventory = (
        provenance.NBA_API_INVENTORY_FILE_COUNT,
        provenance.NBA_API_TREE_INVENTORY_SHA256,
        {"nba_api/example.py": "a" * 64},
    )
    monkeypatch.setattr(provenance, "_inventory", lambda _root: inventory)
    monkeypatch.setattr(
        provenance,
        "_sha256",
        lambda _path: provenance.NBA_API_LICENSE_SHA256,
    )

    def _git(_root: Path, *args: str) -> str | None:
        if args == ("rev-parse", "HEAD"):
            return provenance.NBA_API_UPSTREAM_COMMIT
        if args == ("rev-parse", "HEAD^{tree}"):
            return provenance.NBA_API_UPSTREAM_TREE
        if args == (
            "rev-parse",
            f"refs/tags/{provenance.NBA_API_UPSTREAM_TAG}^{{commit}}",
        ):
            return provenance.NBA_API_UPSTREAM_COMMIT
        if args == ("status", "--porcelain", "--untracked-files=all"):
            return ""
        return None

    monkeypatch.setattr(provenance, "_git", _git)


def test_verify_provider_emits_path_free_canonical_attestation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_valid_provider_fakes(monkeypatch, tmp_path)

    result = provenance.verify_nba_api_provider(tmp_path / "source", project_root=tmp_path)

    assert result["enabled"] is True
    assert result["verified"] is True
    assert result["errors"] == []
    assert result["contract"]["upstream_commit_sha"] == provenance.NBA_API_UPSTREAM_COMMIT
    assert result["distribution_record_authority"]["entry_count"] == 195
    assert result["distribution_record_authority"]["hashed_entry_count"] == 194
    assert len(result["contract"]["attestation_sha256"]) == 64
    assert (
        provenance.normalize_nba_api_provider_evidence_receipt(result["evidence_receipt"])
        == result["evidence_receipt"]
    )
    assert str(tmp_path) not in json.dumps(result, sort_keys=True)


def test_verify_provider_fails_closed_on_distribution_record_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_valid_provider_fakes(monkeypatch, tmp_path)

    def _record_drift() -> None:
        raise ValueError("synthetic RECORD drift")

    monkeypatch.setattr(provenance, "build_distribution_record_authority", _record_drift)

    result = provenance.verify_nba_api_provider(tmp_path / "source", project_root=tmp_path)

    assert result["verified"] is False
    assert result["distribution_record_authority"] is None
    assert "installed_distribution_record_authority_mismatch" in result["errors"]


@pytest.mark.parametrize(
    ("git_args", "wrong_value", "expected_error"),
    [
        (("rev-parse", "HEAD"), "0" * 40, "upstream_commit_mismatch"),
        (("rev-parse", "HEAD^{tree}"), "1" * 40, "upstream_tree_mismatch"),
        (
            ("rev-parse", f"refs/tags/{provenance.NBA_API_UPSTREAM_TAG}^{{commit}}"),
            "2" * 40,
            "upstream_tag_target_mismatch",
        ),
        (
            ("status", "--porcelain", "--untracked-files=all"),
            " M src/nba_api/__init__.py",
            "upstream_checkout_tracked_dirty",
        ),
    ],
)
def test_verify_provider_fails_closed_on_checkout_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    git_args: tuple[str, ...],
    wrong_value: str,
    expected_error: str,
) -> None:
    _install_valid_provider_fakes(monkeypatch, tmp_path)
    original_git = provenance._git

    def _drifted_git(root: Path, *args: str) -> str | None:
        return wrong_value if args == git_args else original_git(root, *args)

    monkeypatch.setattr(provenance, "_git", _drifted_git)

    result = provenance.verify_nba_api_provider(tmp_path / "source", project_root=tmp_path)

    assert result["verified"] is False
    assert expected_error in result["errors"]


def test_locked_archive_hashes_match_exact_project_lock() -> None:
    lock_version, sdist, wheel = provenance._locked_archive_hashes(Path("uv.lock"))

    assert lock_version == provenance.NBA_API_VERSION
    assert sdist == provenance.NBA_API_SDIST_SHA256
    assert wheel == provenance.NBA_API_WHEEL_SHA256


def test_provider_authority_is_canonical_and_rejects_drift() -> None:
    authority = provenance.expected_nba_api_provider_authority()

    assert provenance.normalize_nba_api_provider_authority(authority) == authority
    assert len(authority["authority_sha256"]) == 64
    drifted = json.loads(json.dumps(authority))
    drifted["bronze_contract_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="exact pinned contract"):
        provenance.normalize_nba_api_provider_authority(drifted)


def test_provider_evidence_validates_every_generated_digest() -> None:
    authority = provenance.expected_nba_api_provider_authority()
    provider_evidence = provenance.expected_nba_api_provider_evidence_receipt()
    evidence = provenance.validate_nba_api_provider_evidence(
        provider_provenance={
            "verified": True,
            "contract": authority["provider_contract"],
            "evidence_receipt": provider_evidence,
        },
        runtime_endpoint_contract_count=authority["runtime_endpoint_contract_count"],
        runtime_endpoint_contract_sha256=authority["runtime_endpoint_contract_sha256"],
        live_endpoint_contract_count=authority["live_endpoint_contract_count"],
        live_result_set_contract_count=authority["live_result_set_contract_count"],
        live_column_contract_count=authority["live_column_contract_count"],
        live_parsed_column_contract_count=authority["live_parsed_column_contract_count"],
        live_contract_sha256=authority["live_contract_sha256"],
        static_dataset_contract_count=authority["static_dataset_contract_count"],
        static_modeled_field_contract_count=authority["static_modeled_field_contract_count"],
        static_contract_sha256=authority["static_contract_sha256"],
        runtime_contract_payload_sha256=authority["runtime_contract_payload_sha256"],
        docs_tools_bundle_sha256=authority["docs_tools_bundle_sha256"],
        bronze_contract_sha256=authority["bronze_contract_sha256"],
        metadata_ledger_sha256=authority["metadata_ledger_sha256"],
    )

    assert evidence["verified"] is True
    assert evidence["errors"] == []
    drifted = provenance.validate_nba_api_provider_evidence(
        provider_provenance={
            "verified": True,
            "contract": authority["provider_contract"],
            "evidence_receipt": provider_evidence,
        },
        runtime_endpoint_contract_count=authority["runtime_endpoint_contract_count"],
        runtime_endpoint_contract_sha256=authority["runtime_endpoint_contract_sha256"],
        live_endpoint_contract_count=authority["live_endpoint_contract_count"],
        live_result_set_contract_count=authority["live_result_set_contract_count"],
        live_column_contract_count=authority["live_column_contract_count"],
        live_parsed_column_contract_count=authority["live_parsed_column_contract_count"],
        live_contract_sha256=authority["live_contract_sha256"],
        static_dataset_contract_count=authority["static_dataset_contract_count"],
        static_modeled_field_contract_count=authority["static_modeled_field_contract_count"],
        static_contract_sha256=authority["static_contract_sha256"],
        runtime_contract_payload_sha256=authority["runtime_contract_payload_sha256"],
        docs_tools_bundle_sha256="0" * 64,
        bronze_contract_sha256=authority["bronze_contract_sha256"],
        metadata_ledger_sha256=authority["metadata_ledger_sha256"],
    )
    assert drifted["verified"] is False
    assert drifted["errors"] == ["docs_tools_bundle_digest_mismatch"]


def test_provider_evidence_rejects_boolean_self_attestation() -> None:
    authority = provenance.expected_nba_api_provider_authority()
    evidence = provenance.validate_nba_api_provider_evidence(
        provider_provenance={"verified": True, "contract": authority["provider_contract"]},
        runtime_endpoint_contract_count=authority["runtime_endpoint_contract_count"],
        runtime_endpoint_contract_sha256=authority["runtime_endpoint_contract_sha256"],
        live_endpoint_contract_count=authority["live_endpoint_contract_count"],
        live_result_set_contract_count=authority["live_result_set_contract_count"],
        live_column_contract_count=authority["live_column_contract_count"],
        live_parsed_column_contract_count=authority["live_parsed_column_contract_count"],
        live_contract_sha256=authority["live_contract_sha256"],
        static_dataset_contract_count=authority["static_dataset_contract_count"],
        static_modeled_field_contract_count=authority["static_modeled_field_contract_count"],
        static_contract_sha256=authority["static_contract_sha256"],
        runtime_contract_payload_sha256=authority["runtime_contract_payload_sha256"],
        docs_tools_bundle_sha256=authority["docs_tools_bundle_sha256"],
        bronze_contract_sha256=authority["bronze_contract_sha256"],
        metadata_ledger_sha256=authority["metadata_ledger_sha256"],
    )

    assert evidence["verified"] is False
    assert evidence["errors"] == [
        "provider_evidence_receipt_invalid",
        "provider_evidence_digest_mismatch",
    ]
