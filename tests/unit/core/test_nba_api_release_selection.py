from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

import pytest

import nbadb.core.nba_api_release_selection as subject

SOURCE_SHA = "a" * 40
STARTED_AT = "2026-08-28T12:00:00Z"
RETRIEVED_AT = "2026-08-28T12:00:05Z"
COMPLETED_AT = "2026-08-28T12:04:00Z"
TRUSTED_NOW_AT = "2026-08-28T12:04:30Z"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
CLOCK_COLLECTOR_AUTHORITY_SHA256 = hashlib.sha256(b"trusted-clock-collector").hexdigest()


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _git_digest(label: str) -> str:
    return hashlib.sha1(label.encode(), usedforsecurity=False).hexdigest()


def _seal(payload: dict[str, Any], field: str) -> dict[str, Any]:
    body = dict(payload)
    body.pop(field, None)
    payload[field] = hashlib.sha256(subject.canonical_json_bytes(body)).hexdigest()
    return payload


def _archive_files(version: str, *, yanked: bool = False) -> list[dict[str, Any]]:
    requires_python = ">=3.12"
    return [
        {
            "digests": {"sha256": _digest(f"{version}-sdist")},
            "filename": f"nba_api-{version}.tar.gz",
            "packagetype": "sdist",
            "requires_python": requires_python,
            "size": 10_000,
            "yanked": yanked,
        },
        {
            "digests": {"sha256": _digest(f"{version}-wheel")},
            "filename": f"nba_api-{version}-py3-none-any.whl",
            "packagetype": "bdist_wheel",
            "requires_python": requires_python,
            "size": 20_000,
            "yanked": yanked,
        },
    ]


def _normalized_archives(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [
            {
                "filename": item["filename"],
                "package_type": item["packagetype"],
                "requires_python": item["requires_python"],
                "sha256": item["digests"]["sha256"],
                "size_bytes": item["size"],
                "yanked": item["yanked"],
            }
            for item in files
        ],
        key=lambda item: item["filename"],
    )


def _archive_set_sha256(files: list[dict[str, Any]]) -> str:
    return hashlib.sha256(subject.canonical_json_bytes(_normalized_archives(files))).hexdigest()


def _stack_identity() -> dict[str, Any]:
    return _seal(
        {
            "identity_sha256": "",
            "installed_distributions_sha256": _digest("installed-distributions"),
            "kind": "nbadb_repository_stack_identity",
            "platform_machine": "x86_64",
            "platform_system": "Linux",
            "pyproject_sha256": _digest("pyproject"),
            "python_implementation": "CPython",
            "python_version": "3.12.11",
            "repository_source_sha": SOURCE_SHA,
            "repository_tree_sha256": _digest("repository-tree"),
            "schema_version": 1,
            "uv_lock_sha256": _digest("uv-lock"),
        },
        "identity_sha256",
    )


def _compatibility_plan(stack_sha256: str) -> dict[str, Any]:
    return _seal(
        {
            "commands": [
                {
                    "argv": [
                        "uv",
                        "run",
                        "python",
                        "-m",
                        "nbadb.release_compatibility",
                        "--candidate={candidate_version}",
                        "--archive-set={candidate_archive_set_sha256}",
                    ],
                    "gate_id": "candidate_install",
                    "ordinal": 0,
                    "provider_incompatible_exit_codes": [1],
                    "timeout_seconds": 600,
                },
                {
                    "argv": ["uv", "run", "pytest", "tests/provider-compatibility"],
                    "gate_id": "repository_contracts",
                    "ordinal": 1,
                    "provider_incompatible_exit_codes": [1],
                    "timeout_seconds": 1800,
                },
            ],
            "kind": "nbadb_nba_api_compatibility_plan",
            "plan_sha256": "",
            "repository_source_sha": SOURCE_SHA,
            "schema_version": 1,
            "selection_nonce": _digest("selection-nonce"),
            "stack_identity_sha256": stack_sha256,
        },
        "plan_sha256",
    )


def _command_receipt(
    *,
    spec: dict[str, Any],
    version: str,
    archive_set_sha256: str,
    stack_sha256: str,
    plan_sha256: str,
    selection_nonce: str,
    started_at: str,
    completed_at: str,
    exit_code: int | None,
    result: str | None = None,
    collector_outcome: str = "complete",
    termination_kind: str = "exited",
    signal_number: int | None = None,
) -> dict[str, Any]:
    argv = [
        argument.replace("{candidate_version}", version).replace(
            "{candidate_archive_set_sha256}", archive_set_sha256
        )
        for argument in spec["argv"]
    ]
    if result is not None:
        command_result = result
    elif collector_outcome == "collector_failure":
        command_result = "collector_failure"
    elif termination_kind == "exited":
        if exit_code == 0:
            command_result = "passed"
        elif exit_code in spec["provider_incompatible_exit_codes"]:
            command_result = "provider_incompatible"
        else:
            command_result = "infrastructure_failure"
    elif termination_kind == "timed_out":
        command_result = "timed_out"
    else:
        command_result = "infrastructure_failure"
    return _seal(
        {
            "argv": argv,
            "candidate_archive_set_sha256": archive_set_sha256,
            "candidate_version": version,
            "compatibility_plan_sha256": plan_sha256,
            "completed_at_utc": completed_at,
            "collector_outcome": collector_outcome,
            "exit_code": exit_code,
            "gate_id": spec["gate_id"],
            "ordinal": spec["ordinal"],
            "provider_incompatible_exit_codes": spec["provider_incompatible_exit_codes"],
            "receipt_sha256": "",
            "repository_source_sha": SOURCE_SHA,
            "result": command_result,
            "selection_nonce": selection_nonce,
            "signal_number": signal_number,
            "stack_identity_sha256": stack_sha256,
            "started_at_utc": started_at,
            "stderr_sha256": EMPTY_SHA256,
            "stderr_size_bytes": 0,
            "stdout_sha256": _digest(f"stdout-{version}-{spec['ordinal']}"),
            "stdout_size_bytes": 32,
            "timeout_seconds": spec["timeout_seconds"],
            "termination_kind": termination_kind,
        },
        "receipt_sha256",
    )


def _candidate_receipt(
    *,
    version: str,
    files: list[dict[str, Any]],
    stack: dict[str, Any],
    plan: dict[str, Any],
    times: tuple[tuple[str, str], tuple[str, str]],
    exits: tuple[int, int],
    results: tuple[str, str] | None = None,
) -> dict[str, Any]:
    archive_set_sha256 = _archive_set_sha256(files)
    commands = [
        _command_receipt(
            spec=spec,
            version=version,
            archive_set_sha256=archive_set_sha256,
            stack_sha256=stack["identity_sha256"],
            plan_sha256=plan["plan_sha256"],
            selection_nonce=plan["selection_nonce"],
            started_at=times[index][0],
            completed_at=times[index][1],
            exit_code=exits[index],
            result=None if results is None else results[index],
        )
        for index, spec in enumerate(plan["commands"])
    ]
    command_results = {command["result"] for command in commands}
    if command_results & {"timed_out", "infrastructure_failure", "collector_failure"}:
        outcome = "evidence_failure"
    elif command_results == {"passed"}:
        outcome = "compatible"
    else:
        outcome = "provider_incompatible"
    return _seal(
        {
            "candidate_archive_set_sha256": archive_set_sha256,
            "candidate_version": version,
            "commands": commands,
            "compatibility_plan_sha256": plan["plan_sha256"],
            "kind": "nbadb_nba_api_candidate_compatibility",
            "outcome": outcome,
            "receipt_sha256": "",
            "repository_source_sha": SOURCE_SHA,
            "schema_version": 1,
            "selection_nonce": plan["selection_nonce"],
            "stack_identity_sha256": stack["identity_sha256"],
        },
        "receipt_sha256",
    )


def _provider_authority(
    version: str,
    files: list[dict[str, Any]],
    *,
    stack: dict[str, Any],
    plan: dict[str, Any],
    selected_candidate_receipt_sha256: str,
    candidate_receipt_inventory_sha256: str,
) -> dict[str, Any]:
    inventory_digest = _digest(f"provider-inventory-{version}")
    versions = {
        "dependency_pin_version": version,
        "distribution_version": version,
        "fixture_version": version,
        "generated_authority_version": version,
        "installed_version": version,
        "live_headers_version": version,
        "lock_version": version,
        "parity_test_version": version,
        "standalone_connector_version": version,
        "stats_headers_version": version,
    }
    return _seal(
        {
            "authority_sha256": "",
            "bronze_contract_sha256": _digest("bronze-contract"),
            "candidate_receipt_inventory_sha256": candidate_receipt_inventory_sha256,
            "compatibility_plan_sha256": plan["plan_sha256"],
            **versions,
            "distribution_name": "nba-api",
            "docs_tools_bundle_sha256": _digest("docs-tools"),
            "installed_inventory_file_count": 200,
            "installed_inventory_sha256": inventory_digest,
            "kind": "nbadb_nba_api_observed_provider_authority",
            "license_identifier": "MIT",
            "license_sha256": _digest("license"),
            "live_contract_sha256": _digest("live-contract"),
            "locked_archive_sha256s": sorted(item["digests"]["sha256"] for item in files),
            "metadata_ledger_sha256": _digest("metadata-ledger"),
            "observed_at_utc": "2026-08-28T12:03:00Z",
            "provider_contract_sha256": _digest("provider-contract"),
            "provider_evidence_sha256": _digest("provider-evidence"),
            "repository_source_sha": SOURCE_SHA,
            "runtime_contract_payload_sha256": _digest("runtime-payload"),
            "runtime_endpoint_contract_count": 140,
            "runtime_endpoint_contract_sha256": _digest("runtime-endpoints"),
            "schema_version": 1,
            "selected_candidate_receipt_sha256": selected_candidate_receipt_sha256,
            "selection_nonce": plan["selection_nonce"],
            "source_checkout_clean": True,
            "source_installed_file_parity": True,
            "source_inventory_file_count": 200,
            "source_inventory_sha256": inventory_digest,
            "static_contract_sha256": _digest("static-contract"),
            "stack_identity_sha256": stack["identity_sha256"],
            "upstream_commit_sha": _git_digest(f"commit-{version}"),
            "upstream_repository": "https://github.com/swar/nba_api",
            "upstream_tag": f"v{version}",
            "upstream_tag_commit_sha": _git_digest(f"commit-{version}"),
            "upstream_tree_sha": _git_digest(f"tree-{version}"),
        },
        "authority_sha256",
    )


def _clock_receipt(
    *,
    phase: str,
    repository_source_sha: str,
    stack_identity_sha256: str,
    compatibility_plan_sha256: str,
    selection_nonce: str,
    execution_kickoff_at_utc: str,
    selection_completed_at_utc: str,
    observed_now_at_utc: str,
) -> dict[str, Any]:
    return _seal(
        {
            "collector_authority_sha256": CLOCK_COLLECTOR_AUTHORITY_SHA256,
            "compatibility_plan_sha256": compatibility_plan_sha256,
            "execution_kickoff_at_utc": execution_kickoff_at_utc,
            "kind": "nbadb_execution_clock_receipt",
            "observed_now_at_utc": observed_now_at_utc,
            "phase": phase,
            "receipt_sha256": "",
            "repository_source_sha": repository_source_sha,
            "schema_version": 1,
            "selection_completed_at_utc": selection_completed_at_utc,
            "selection_nonce": selection_nonce,
            "stack_identity_sha256": stack_identity_sha256,
        },
        "receipt_sha256",
    )


def _bundle() -> dict[str, Any]:
    releases = {
        "1.10.0": _archive_files("1.10.0", yanked=True),
        "1.11.4": _archive_files("1.11.4"),
        "1.12.0": _archive_files("1.12.0"),
        "1.13.0rc1": _archive_files("1.13.0rc1"),
    }
    inventory = {
        "info": {"name": "nba_api", "version": "1.12.0"},
        "last_serial": 987_654,
        "releases": releases,
        "urls": deepcopy(releases["1.12.0"]),
        "vulnerabilities": [],
    }
    stack = _stack_identity()
    plan = _compatibility_plan(stack["identity_sha256"])
    candidate_112 = _candidate_receipt(
        version="1.12.0",
        files=releases["1.12.0"],
        stack=stack,
        plan=plan,
        times=(
            ("2026-08-28T12:01:00Z", "2026-08-28T12:01:10Z"),
            ("2026-08-28T12:01:11Z", "2026-08-28T12:01:20Z"),
        ),
        exits=(0, 1),
    )
    candidate_1114 = _candidate_receipt(
        version="1.11.4",
        files=releases["1.11.4"],
        stack=stack,
        plan=plan,
        times=(
            ("2026-08-28T12:02:00Z", "2026-08-28T12:02:10Z"),
            ("2026-08-28T12:02:11Z", "2026-08-28T12:02:20Z"),
        ),
        exits=(0, 0),
    )
    candidate_payloads = [candidate_112, candidate_1114]
    candidate_receipt_sha256s = tuple(item["receipt_sha256"] for item in candidate_payloads)
    candidate_receipt_inventory_sha256 = hashlib.sha256(
        subject.canonical_json_bytes(list(candidate_receipt_sha256s))
    ).hexdigest()
    provider = _provider_authority(
        "1.11.4",
        releases["1.11.4"],
        stack=stack,
        plan=plan,
        selected_candidate_receipt_sha256=candidate_1114["receipt_sha256"],
        candidate_receipt_inventory_sha256=candidate_receipt_inventory_sha256,
    )
    bundle = {
        "inventory": inventory,
        "stack": stack,
        "plan": plan,
        "candidate_payloads": candidate_payloads,
        "provider": provider,
    }
    _refresh_bytes(bundle)
    return bundle


def _refresh_bytes(
    bundle: dict[str, Any],
    *,
    retrieved_at_utc: str = RETRIEVED_AT,
    execution_kickoff_at_utc: str = STARTED_AT,
    selection_completed_at_utc: str = COMPLETED_AT,
    trusted_now_utc: str = TRUSTED_NOW_AT,
) -> None:
    inventory_bytes = subject.canonical_json_bytes(bundle["inventory"])
    fetch = _seal(
        {
            "body_sha256": hashlib.sha256(inventory_bytes).hexdigest(),
            "body_size_bytes": len(inventory_bytes),
            "content_type": "application/json",
            "kind": "nbadb_pypi_inventory_fetch",
            "project_name": "nba_api",
            "receipt_sha256": "",
            "request_url": "https://pypi.org/pypi/nba_api/json",
            "response_url": "https://pypi.org/pypi/nba_api/json",
            "retrieved_at_utc": retrieved_at_utc,
            "schema_version": 1,
            "status_code": 200,
        },
        "receipt_sha256",
    )
    bundle["fetch"] = fetch
    candidate_receipt_sha256s = tuple(
        item["receipt_sha256"] for item in bundle["candidate_payloads"]
    )
    candidate_receipt_inventory_sha256 = hashlib.sha256(
        subject.canonical_json_bytes(list(candidate_receipt_sha256s))
    ).hexdigest()
    provider = bundle["provider"]
    provider["repository_source_sha"] = SOURCE_SHA
    provider["stack_identity_sha256"] = bundle["stack"]["identity_sha256"]
    provider["compatibility_plan_sha256"] = bundle["plan"]["plan_sha256"]
    provider["selection_nonce"] = bundle["plan"]["selection_nonce"]
    provider["selected_candidate_receipt_sha256"] = candidate_receipt_sha256s[-1]
    provider["candidate_receipt_inventory_sha256"] = candidate_receipt_inventory_sha256
    _seal(provider, "authority_sha256")
    selection_clock = _clock_receipt(
        phase="selection",
        repository_source_sha=SOURCE_SHA,
        stack_identity_sha256=bundle["stack"]["identity_sha256"],
        compatibility_plan_sha256=bundle["plan"]["plan_sha256"],
        selection_nonce=bundle["plan"]["selection_nonce"],
        execution_kickoff_at_utc=execution_kickoff_at_utc,
        selection_completed_at_utc=selection_completed_at_utc,
        observed_now_at_utc=trusted_now_utc,
    )
    bundle["selection_clock"] = selection_clock
    bundle["kwargs"] = {
        "candidate_compatibility_receipt_bytes": tuple(
            subject.canonical_json_bytes(item) for item in bundle["candidate_payloads"]
        ),
        "compatibility_plan_bytes": subject.canonical_json_bytes(bundle["plan"]),
        "execution_clock_receipt_bytes": subject.canonical_json_bytes(selection_clock),
        "expected_clock_collector_authority_sha256": CLOCK_COLLECTOR_AUTHORITY_SHA256,
        "expected_compatibility_plan_sha256": bundle["plan"]["plan_sha256"],
        "expected_candidate_receipt_inventory_sha256": (candidate_receipt_inventory_sha256),
        "expected_candidate_receipt_sha256s": candidate_receipt_sha256s,
        "expected_pypi_fetch_receipt_sha256": fetch["receipt_sha256"],
        "expected_execution_clock_receipt_sha256": selection_clock["receipt_sha256"],
        "expected_repository_source_sha": SOURCE_SHA,
        "expected_selected_provider_authority_sha256": bundle["provider"]["authority_sha256"],
        "expected_stack_identity_sha256": bundle["stack"]["identity_sha256"],
        "pypi_fetch_receipt_bytes": subject.canonical_json_bytes(fetch),
        "pypi_inventory_bytes": inventory_bytes,
        "repository_stack_identity_bytes": subject.canonical_json_bytes(bundle["stack"]),
        "selected_provider_authority_bytes": subject.canonical_json_bytes(bundle["provider"]),
    }


def _readback_kwargs(
    authority: subject.NbaApiReleaseSelectionAuthorityV1,
    *,
    trusted_now_utc: str = TRUSTED_NOW_AT,
) -> dict[str, Any]:
    readback_clock = _clock_receipt(
        phase="readback",
        repository_source_sha=authority.repository_source_sha,
        stack_identity_sha256=authority.stack_identity_sha256,
        compatibility_plan_sha256=authority.compatibility_plan_sha256,
        selection_nonce=authority.selection_nonce,
        execution_kickoff_at_utc=authority.execution_kickoff_at_utc,
        selection_completed_at_utc=authority.selection_completed_at_utc,
        observed_now_at_utc=trusted_now_utc,
    )
    return {
        "expected_authority_sha256": authority.authority_sha256,
        "expected_candidate_receipt_inventory_sha256": (
            authority.candidate_receipt_inventory_sha256
        ),
        "expected_candidate_receipt_sha256s": authority.candidate_receipt_sha256s,
        "expected_clock_collector_authority_sha256": CLOCK_COLLECTOR_AUTHORITY_SHA256,
        "expected_compatibility_plan_sha256": authority.compatibility_plan_sha256,
        "expected_execution_clock_receipt_sha256": (authority.execution_clock_receipt_sha256),
        "expected_pypi_fetch_receipt_sha256": authority.pypi_fetch_receipt_sha256,
        "expected_pypi_inventory_sha256": authority.pypi_inventory_sha256,
        "expected_repository_source_sha": authority.repository_source_sha,
        "expected_selected_provider_authority_sha256": (
            authority.selected_provider_authority_sha256
        ),
        "expected_stack_identity_sha256": authority.stack_identity_sha256,
        "expected_readback_clock_receipt_sha256": readback_clock["receipt_sha256"],
        "readback_clock_receipt_bytes": subject.canonical_json_bytes(readback_clock),
    }


def _select(bundle: dict[str, Any]) -> subject.NbaApiReleaseSelectionAuthorityV1:
    return subject.select_latest_compatible_release(**bundle["kwargs"])


def test_newer_incompatible_candidate_selects_next_all_green_release() -> None:
    bundle = _bundle()

    authority = _select(bundle)

    assert authority.stable_candidate_versions == ("1.12.0", "1.11.4")
    assert authority.rejected_newer_versions == ("1.12.0",)
    assert authority.selected_version == "1.11.4"
    assert tuple(item.requires_python for item in authority.selected_archives) == (
        ">=3.12",
        ">=3.12",
    )
    assert authority.selected_provider_authority.distribution_version == "1.11.4"
    assert authority.candidate_receipts[0].outcome == "provider_incompatible"
    assert authority.candidate_receipts[1].outcome == "compatible"


def test_selection_authority_has_exact_canonical_roundtrip() -> None:
    authority = _select(_bundle())
    encoded = authority.to_canonical_bytes()

    assert (
        subject.NbaApiReleaseSelectionAuthorityV1.from_canonical_bytes(
            encoded,
            **_readback_kwargs(authority),
        )
        == authority
    )
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="not exact canonical"):
        subject.NbaApiReleaseSelectionAuthorityV1.from_canonical_bytes(
            encoded + b"\n",
            **_readback_kwargs(authority),
        )
    forged = json.loads(encoded)
    forged["authority_sha256"] = "0" * 64
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="digest is invalid"):
        subject.NbaApiReleaseSelectionAuthorityV1.from_canonical_bytes(
            subject.canonical_json_bytes(forged),
            **_readback_kwargs(authority),
        )


@pytest.mark.parametrize("version", ["1.13", "v1.13.0", "1!1.13.0", "1.13.0+local"])
def test_unknown_future_version_syntax_blocks_complete_inventory(version: str) -> None:
    bundle = _bundle()
    bundle["inventory"]["releases"][version] = _archive_files(version)
    _refresh_bytes(bundle)

    with pytest.raises(subject.NbaApiReleaseSelectionError, match="unclassified version syntax"):
        _select(bundle)


@pytest.mark.parametrize("failure", ["partially_yanked", "missing_wheel", "missing_all"])
def test_partial_yank_or_missing_archive_inventory_fails_closed(failure: str) -> None:
    bundle = _bundle()
    files = bundle["inventory"]["releases"]["1.12.0"]
    if failure == "partially_yanked":
        files[0]["yanked"] = True
    elif failure == "missing_wheel":
        files.pop()
    else:
        files.clear()
    bundle["inventory"]["urls"] = deepcopy(files)
    _refresh_bytes(bundle)

    with pytest.raises(
        subject.NbaApiReleaseSelectionError,
        match="partially yanked|at least one wheel|no archive inventory",
    ):
        _select(bundle)


def test_prereleases_and_fully_yanked_stable_releases_are_classified_but_not_candidates() -> None:
    authority = _select(_bundle())
    release_by_version = {entry.version: entry for entry in authority.release_inventory}

    assert release_by_version["1.13.0rc1"].classification == "prerelease"
    assert release_by_version["1.10.0"].classification == "stable"
    assert release_by_version["1.10.0"].yanked is True
    assert "1.13.0rc1" not in authority.stable_candidate_versions
    assert "1.10.0" not in authority.stable_candidate_versions


def test_pypi_latest_projection_cannot_disagree_with_enumerated_stable_order() -> None:
    bundle = _bundle()
    bundle["inventory"]["info"]["version"] = "1.11.4"
    bundle["inventory"]["urls"] = deepcopy(bundle["inventory"]["releases"]["1.11.4"])
    _refresh_bytes(bundle)

    with pytest.raises(subject.NbaApiReleaseSelectionError, match="latest version disagrees"):
        _select(bundle)


def test_reordered_duplicate_extra_or_noncanonical_candidate_receipts_fail_closed() -> None:
    bundle = _bundle()
    original = bundle["kwargs"]["candidate_compatibility_receipt_bytes"]
    hostile_values = (
        tuple(reversed(original)),
        (original[0], original[0]),
        (*original, original[-1]),
        (original[0] + b"\n", original[1]),
    )

    for hostile in hostile_values:
        kwargs = {**bundle["kwargs"], "candidate_compatibility_receipt_bytes": hostile}
        with pytest.raises(subject.NbaApiReleaseSelectionError):
            subject.select_latest_compatible_release(**kwargs)


def test_candidate_receipt_list_cannot_replace_exact_tuple() -> None:
    bundle = _bundle()
    kwargs = dict(bundle["kwargs"])
    kwargs["candidate_compatibility_receipt_bytes"] = list(
        kwargs["candidate_compatibility_receipt_bytes"]
    )

    with pytest.raises(subject.NbaApiReleaseSelectionError, match="exact tuple"):
        subject.select_latest_compatible_release(**kwargs)  # type: ignore[arg-type]


def test_forged_fetch_candidate_and_external_trust_root_digests_fail_closed() -> None:
    bundle = _bundle()
    fetch = deepcopy(bundle["fetch"])
    fetch["body_sha256"] = "0" * 64
    _seal(fetch, "receipt_sha256")
    kwargs = {
        **bundle["kwargs"],
        "expected_pypi_fetch_receipt_sha256": fetch["receipt_sha256"],
        "pypi_fetch_receipt_bytes": subject.canonical_json_bytes(fetch),
    }
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="body digest differs"):
        subject.select_latest_compatible_release(**kwargs)

    candidate = deepcopy(bundle["candidate_payloads"][0])
    candidate["commands"][0]["exit_code"] = 9
    kwargs = {
        **bundle["kwargs"],
        "candidate_compatibility_receipt_bytes": (
            subject.canonical_json_bytes(candidate),
            bundle["kwargs"]["candidate_compatibility_receipt_bytes"][1],
        ),
    }
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="result does not match|digest"):
        subject.select_latest_compatible_release(**kwargs)

    with pytest.raises(subject.NbaApiReleaseSelectionError, match="independently expected plan"):
        subject.select_latest_compatible_release(
            **{
                **bundle["kwargs"],
                "expected_compatibility_plan_sha256": "0" * 64,
            }
        )


def test_command_timeout_empty_output_and_candidate_stack_rebinding_fail_closed() -> None:
    bundle = _bundle()
    candidate = deepcopy(bundle["candidate_payloads"][0])
    candidate["commands"][0]["completed_at_utc"] = "2026-08-28T12:20:00Z"
    _seal(candidate["commands"][0], "receipt_sha256")
    _seal(candidate, "receipt_sha256")
    bundle["candidate_payloads"][0] = candidate
    _refresh_bytes(bundle)
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="declared timeout"):
        _select(bundle)

    bundle = _bundle()
    candidate = deepcopy(bundle["candidate_payloads"][0])
    candidate["commands"][0]["stderr_sha256"] = _digest("forged-empty-stderr")
    _seal(candidate["commands"][0], "receipt_sha256")
    _seal(candidate, "receipt_sha256")
    bundle["candidate_payloads"][0] = candidate
    _refresh_bytes(bundle)
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="empty command stderr"):
        _select(bundle)

    bundle = _bundle()
    candidate = deepcopy(bundle["candidate_payloads"][0])
    candidate["stack_identity_sha256"] = "0" * 64
    for command in candidate["commands"]:
        command["stack_identity_sha256"] = "0" * 64
        _seal(command, "receipt_sha256")
    _seal(candidate, "receipt_sha256")
    bundle["candidate_payloads"][0] = candidate
    _refresh_bytes(bundle)
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="foreign authority"):
        _select(bundle)


def test_mixed_installed_pin_or_selected_archive_authority_fails_closed() -> None:
    bundle = _bundle()
    provider = deepcopy(bundle["provider"])
    provider["dependency_pin_version"] = "1.11.3"
    _seal(provider, "authority_sha256")
    kwargs = {
        **bundle["kwargs"],
        "expected_selected_provider_authority_sha256": provider["authority_sha256"],
        "selected_provider_authority_bytes": subject.canonical_json_bytes(provider),
    }

    with pytest.raises(subject.NbaApiReleaseSelectionError, match="mixed dependency"):
        subject.select_latest_compatible_release(**kwargs)

    provider = deepcopy(bundle["provider"])
    provider["locked_archive_sha256s"][0] = _digest("foreign-archive")
    provider["locked_archive_sha256s"].sort()
    _seal(provider, "authority_sha256")
    kwargs = {
        **bundle["kwargs"],
        "expected_selected_provider_authority_sha256": provider["authority_sha256"],
        "selected_provider_authority_bytes": subject.canonical_json_bytes(provider),
    }
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="other archives"):
        subject.select_latest_compatible_release(**kwargs)


def test_provider_observation_must_follow_selected_candidate_compatibility() -> None:
    bundle = _bundle()
    provider = deepcopy(bundle["provider"])
    provider["observed_at_utc"] = "2026-08-28T12:02:19Z"
    _seal(provider, "authority_sha256")
    bundle["provider"] = provider
    _refresh_bytes(bundle)

    with pytest.raises(subject.NbaApiReleaseSelectionError, match="observation is stale"):
        _select(bundle)


def test_stale_fetch_extra_fields_and_legacy_kind_fail_closed() -> None:
    bundle = _bundle()
    fetch = deepcopy(bundle["fetch"])
    fetch["retrieved_at_utc"] = "2026-08-28T11:59:59Z"
    _seal(fetch, "receipt_sha256")
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="stale|outside"):
        subject.select_latest_compatible_release(
            **{
                **bundle["kwargs"],
                "expected_pypi_fetch_receipt_sha256": fetch["receipt_sha256"],
                "pypi_fetch_receipt_bytes": subject.canonical_json_bytes(fetch),
            }
        )

    provider = deepcopy(bundle["provider"])
    provider["extra"] = True
    _seal(provider, "authority_sha256")
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="exact schema"):
        subject.select_latest_compatible_release(
            **{
                **bundle["kwargs"],
                "expected_selected_provider_authority_sha256": provider["authority_sha256"],
                "selected_provider_authority_bytes": subject.canonical_json_bytes(provider),
            }
        )

    provider = deepcopy(bundle["provider"])
    provider["kind"] = "nbadb_nba_api_provider_evidence_v1"
    _seal(provider, "authority_sha256")
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="schema, distribution"):
        subject.select_latest_compatible_release(
            **{
                **bundle["kwargs"],
                "expected_selected_provider_authority_sha256": provider["authority_sha256"],
                "selected_provider_authority_bytes": subject.canonical_json_bytes(provider),
            }
        )


def test_duplicate_json_keys_and_constants_only_do_not_authorize_selection() -> None:
    bundle = _bundle()
    canonical_fetch = bundle["kwargs"]["pypi_fetch_receipt_bytes"]
    duplicate = b'{"schema_version":1,' + canonical_fetch[1:]
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="duplicate JSON key"):
        subject.select_latest_compatible_release(
            **{**bundle["kwargs"], "pypi_fetch_receipt_bytes": duplicate}
        )

    with pytest.raises(TypeError):
        subject.select_latest_compatible_release(  # type: ignore[call-arg]
            expected_repository_source_sha=SOURCE_SHA,
            expected_stack_identity_sha256=bundle["stack"]["identity_sha256"],
            expected_compatibility_plan_sha256=bundle["plan"]["plan_sha256"],
        )


def test_candidate_receipts_require_an_independent_ordered_inventory_root() -> None:
    bundle = _bundle()
    candidate = deepcopy(bundle["candidate_payloads"][0])
    candidate["commands"][1]["stdout_sha256"] = _digest("foreign-candidate-output")
    _seal(candidate["commands"][1], "receipt_sha256")
    _seal(candidate, "receipt_sha256")
    hostile_bytes = (
        subject.canonical_json_bytes(candidate),
        bundle["kwargs"]["candidate_compatibility_receipt_bytes"][1],
    )

    with pytest.raises(subject.NbaApiReleaseSelectionError, match="independent trust root"):
        subject.select_latest_compatible_release(
            **{
                **bundle["kwargs"],
                "candidate_compatibility_receipt_bytes": hostile_bytes,
            }
        )

    hostile_sha256s = (
        candidate["receipt_sha256"],
        bundle["candidate_payloads"][1]["receipt_sha256"],
    )
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="internally inconsistent"):
        subject.select_latest_compatible_release(
            **{
                **bundle["kwargs"],
                "candidate_compatibility_receipt_bytes": hostile_bytes,
                "expected_candidate_receipt_sha256s": hostile_sha256s,
            }
        )


def test_canonical_readback_rejects_coordinated_foreign_roots_and_resealed_candidates() -> None:
    authority = _select(_bundle())
    canonical = json.loads(authority.to_canonical_bytes())

    foreign_roots = deepcopy(canonical)
    foreign_roots["pypi_fetch_receipt_sha256"] = "f" * 64
    foreign_roots["pypi_inventory_sha256"] = "e" * 64
    _seal(foreign_roots, "authority_sha256")
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="independent trust roots"):
        subject.NbaApiReleaseSelectionAuthorityV1.from_canonical_bytes(
            subject.canonical_json_bytes(foreign_roots),
            **{
                **_readback_kwargs(authority),
                "expected_authority_sha256": foreign_roots["authority_sha256"],
            },
        )

    resealed = deepcopy(canonical)
    command = resealed["candidate_receipts"][0]["commands"][1]
    command["stdout_sha256"] = _digest("resealed-candidate-output")
    _seal(command, "receipt_sha256")
    _seal(resealed["candidate_receipts"][0], "receipt_sha256")
    resealed["candidate_receipt_sha256s"][0] = resealed["candidate_receipts"][0]["receipt_sha256"]
    resealed["candidate_receipt_inventory_sha256"] = hashlib.sha256(
        subject.canonical_json_bytes(resealed["candidate_receipt_sha256s"])
    ).hexdigest()
    resealed_provider = resealed["selected_provider_authority"]
    resealed_provider["candidate_receipt_inventory_sha256"] = resealed[
        "candidate_receipt_inventory_sha256"
    ]
    _seal(resealed_provider, "authority_sha256")
    resealed["selected_provider_authority_sha256"] = resealed_provider["authority_sha256"]
    _seal(resealed, "authority_sha256")
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="independent trust roots"):
        subject.NbaApiReleaseSelectionAuthorityV1.from_canonical_bytes(
            subject.canonical_json_bytes(resealed),
            **{
                **_readback_kwargs(authority),
                "expected_authority_sha256": resealed["authority_sha256"],
            },
        )

    with pytest.raises(TypeError):
        subject.NbaApiReleaseSelectionAuthorityV1.from_canonical_bytes(  # type: ignore[call-arg]
            authority.to_canonical_bytes()
        )


@pytest.mark.parametrize("requires_python", [">=999", "not a specifier"])
def test_selected_archives_must_support_exact_stack_python(requires_python: str) -> None:
    bundle = _bundle()
    selected_files = bundle["inventory"]["releases"]["1.11.4"]
    for archive in selected_files:
        archive["requires_python"] = requires_python
    bundle["candidate_payloads"][1] = _candidate_receipt(
        version="1.11.4",
        files=selected_files,
        stack=bundle["stack"],
        plan=bundle["plan"],
        times=(
            ("2026-08-28T12:02:00Z", "2026-08-28T12:02:10Z"),
            ("2026-08-28T12:02:11Z", "2026-08-28T12:02:20Z"),
        ),
        exits=(0, 0),
    )
    _refresh_bytes(bundle)

    with pytest.raises(
        subject.NbaApiReleaseSelectionError,
        match="excludes the exact|valid PEP 440 Requires-Python",
    ):
        _select(bundle)


def test_rejected_stable_candidate_requires_python_must_still_be_classified() -> None:
    bundle = _bundle()
    newer_files = bundle["inventory"]["releases"]["1.12.0"]
    for archive in newer_files:
        archive["requires_python"] = "not a specifier"
    bundle["inventory"]["urls"] = deepcopy(newer_files)
    bundle["candidate_payloads"][0] = _candidate_receipt(
        version="1.12.0",
        files=newer_files,
        stack=bundle["stack"],
        plan=bundle["plan"],
        times=(
            ("2026-08-28T12:01:00Z", "2026-08-28T12:01:10Z"),
            ("2026-08-28T12:01:11Z", "2026-08-28T12:01:20Z"),
        ),
        exits=(0, 1),
    )
    _refresh_bytes(bundle)

    with pytest.raises(subject.NbaApiReleaseSelectionError, match="valid PEP 440 Requires-Python"):
        _select(bundle)


@pytest.mark.parametrize("python_version", ["3.12", "3.12.13rc1", "3.12.13+local"])
def test_stack_python_version_must_be_exact_runtime_triplet(python_version: str) -> None:
    bundle = _bundle()
    bundle["stack"]["python_version"] = python_version
    _seal(bundle["stack"], "identity_sha256")
    bundle["plan"] = _compatibility_plan(bundle["stack"]["identity_sha256"])
    bundle["candidate_payloads"] = [
        _candidate_receipt(
            version="1.12.0",
            files=bundle["inventory"]["releases"]["1.12.0"],
            stack=bundle["stack"],
            plan=bundle["plan"],
            times=(
                ("2026-08-28T12:01:00Z", "2026-08-28T12:01:10Z"),
                ("2026-08-28T12:01:11Z", "2026-08-28T12:01:20Z"),
            ),
            exits=(0, 1),
        ),
        _candidate_receipt(
            version="1.11.4",
            files=bundle["inventory"]["releases"]["1.11.4"],
            stack=bundle["stack"],
            plan=bundle["plan"],
            times=(
                ("2026-08-28T12:02:00Z", "2026-08-28T12:02:10Z"),
                ("2026-08-28T12:02:11Z", "2026-08-28T12:02:20Z"),
            ),
            exits=(0, 0),
        ),
    ]
    _refresh_bytes(bundle)

    with pytest.raises(subject.NbaApiReleaseSelectionError, match="major.minor.micro"):
        _select(bundle)


def test_nonempty_command_output_cannot_claim_the_empty_content_digest() -> None:
    bundle = _bundle()
    command = bundle["candidate_payloads"][1]["commands"][1]
    command["stdout_size_bytes"] = 32
    command["stdout_sha256"] = EMPTY_SHA256
    _seal(command, "receipt_sha256")
    _seal(bundle["candidate_payloads"][1], "receipt_sha256")
    _refresh_bytes(bundle)

    with pytest.raises(subject.NbaApiReleaseSelectionError, match="nonempty command stdout"):
        _select(bundle)


@pytest.mark.parametrize(
    ("field", "foreign_value"),
    [
        ("repository_source_sha", "b" * 40),
        ("stack_identity_sha256", "b" * 64),
        ("compatibility_plan_sha256", "c" * 64),
        ("selection_nonce", "d" * 64),
        ("selected_candidate_receipt_sha256", "e" * 64),
        ("candidate_receipt_inventory_sha256", "f" * 64),
    ],
)
def test_provider_authority_must_join_the_current_selection_context(
    field: str,
    foreign_value: str,
) -> None:
    bundle = _bundle()
    provider = deepcopy(bundle["provider"])
    provider[field] = foreign_value
    _seal(provider, "authority_sha256")

    with pytest.raises(subject.NbaApiReleaseSelectionError, match="mixed or rebound"):
        subject.select_latest_compatible_release(
            **{
                **bundle["kwargs"],
                "expected_selected_provider_authority_sha256": provider["authority_sha256"],
                "selected_provider_authority_bytes": subject.canonical_json_bytes(provider),
            }
        )


@pytest.mark.parametrize(
    ("failure_result", "collector_outcome", "termination_kind", "signal_number"),
    [
        ("timed_out", "complete", "timed_out", None),
        ("infrastructure_failure", "complete", "infrastructure_failure", None),
        ("infrastructure_failure", "complete", "spawn_failure", None),
        ("infrastructure_failure", "complete", "signaled", 9),
        ("collector_failure", "collector_failure", "unobserved", None),
    ],
)
def test_non_provider_command_failures_block_selection(
    failure_result: str,
    collector_outcome: str,
    termination_kind: str,
    signal_number: int | None,
) -> None:
    bundle = _bundle()
    candidate = bundle["candidate_payloads"][0]
    command = candidate["commands"][1]
    command["collector_outcome"] = collector_outcome
    command["termination_kind"] = termination_kind
    command["exit_code"] = None
    command["signal_number"] = signal_number
    command["result"] = failure_result
    _seal(command, "receipt_sha256")
    candidate["outcome"] = "evidence_failure"
    _seal(candidate, "receipt_sha256")
    _refresh_bytes(bundle)

    with pytest.raises(subject.NbaApiReleaseSelectionError, match="non-provider failure"):
        _select(bundle)


@pytest.mark.parametrize("exit_code", [2, 3, 4, 5, 127, 255])
def test_undeclared_positive_exits_cannot_eliminate_a_newer_candidate(exit_code: int) -> None:
    bundle = _bundle()
    candidate = bundle["candidate_payloads"][0]
    command = candidate["commands"][1]
    command["exit_code"] = exit_code
    command["result"] = "infrastructure_failure"
    _seal(command, "receipt_sha256")
    candidate["outcome"] = "evidence_failure"
    _seal(candidate, "receipt_sha256")
    _refresh_bytes(bundle)

    with pytest.raises(subject.NbaApiReleaseSelectionError, match="non-provider failure"):
        _select(bundle)

    relabelled = _bundle()
    candidate = relabelled["candidate_payloads"][0]
    command = candidate["commands"][1]
    command["exit_code"] = exit_code
    command["result"] = "provider_incompatible"
    _seal(command, "receipt_sha256")
    _seal(candidate, "receipt_sha256")
    _refresh_bytes(relabelled)

    with pytest.raises(subject.NbaApiReleaseSelectionError, match="validator-derived"):
        _select(relabelled)


def test_declared_gate_exit_semantics_are_part_of_the_independent_plan() -> None:
    bundle = _bundle()
    bundle["plan"]["commands"][1]["provider_incompatible_exit_codes"] = [1, 2]
    _seal(bundle["plan"], "plan_sha256")
    releases = bundle["inventory"]["releases"]
    bundle["candidate_payloads"] = [
        _candidate_receipt(
            version="1.12.0",
            files=releases["1.12.0"],
            stack=bundle["stack"],
            plan=bundle["plan"],
            times=(
                ("2026-08-28T12:01:00Z", "2026-08-28T12:01:10Z"),
                ("2026-08-28T12:01:11Z", "2026-08-28T12:01:20Z"),
            ),
            exits=(0, 2),
        ),
        _candidate_receipt(
            version="1.11.4",
            files=releases["1.11.4"],
            stack=bundle["stack"],
            plan=bundle["plan"],
            times=(
                ("2026-08-28T12:02:00Z", "2026-08-28T12:02:10Z"),
                ("2026-08-28T12:02:11Z", "2026-08-28T12:02:20Z"),
            ),
            exits=(0, 0),
        ),
    ]
    _refresh_bytes(bundle)

    authority = _select(bundle)

    assert authority.selected_version == "1.11.4"
    assert authority.compatibility_commands[1].provider_incompatible_exit_codes == (1, 2)
    assert authority.candidate_receipts[0].commands[1].provider_incompatible_exit_codes == (1, 2)


@pytest.mark.parametrize(
    "exit_codes",
    [
        [True],
        [0],
        [1, 1],
        [2, 1],
        [256],
        [*range(1, 256), 1],
    ],
    ids=["bool", "zero", "duplicate", "reordered", "out-of-range", "unbounded"],
)
def test_gate_exit_semantics_reject_invalid_exact_inventories(exit_codes: list[object]) -> None:
    bundle = _bundle()
    plan = bundle["plan"]
    plan["commands"][1]["provider_incompatible_exit_codes"] = exit_codes
    _seal(plan, "plan_sha256")

    with pytest.raises(subject.NbaApiReleaseSelectionError):
        subject.select_latest_compatible_release(
            **{
                **bundle["kwargs"],
                "compatibility_plan_bytes": subject.canonical_json_bytes(plan),
                "expected_compatibility_plan_sha256": plan["plan_sha256"],
            }
        )


def test_gate_exit_semantics_cannot_rebind_plan_receipts_or_canonical_readback() -> None:
    bundle = _bundle()
    plan = deepcopy(bundle["plan"])
    plan["commands"][1]["provider_incompatible_exit_codes"] = [1, 2]
    _seal(plan, "plan_sha256")
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="independently expected plan"):
        subject.select_latest_compatible_release(
            **{
                **bundle["kwargs"],
                "compatibility_plan_bytes": subject.canonical_json_bytes(plan),
            }
        )

    rebound_receipt = _bundle()
    candidate = rebound_receipt["candidate_payloads"][0]
    candidate["commands"][1]["provider_incompatible_exit_codes"] = [1, 2]
    _seal(candidate["commands"][1], "receipt_sha256")
    _seal(candidate, "receipt_sha256")
    _refresh_bytes(rebound_receipt)
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="exact compatibility plan"):
        _select(rebound_receipt)

    authority = _select(_bundle())
    canonical = json.loads(authority.to_canonical_bytes())
    canonical["compatibility_commands"][1]["provider_incompatible_exit_codes"] = [1, 2]
    for candidate in canonical["candidate_receipts"]:
        candidate["commands"][1]["provider_incompatible_exit_codes"] = [1, 2]
        _seal(candidate["commands"][1], "receipt_sha256")
        _seal(candidate, "receipt_sha256")
    canonical["candidate_receipt_sha256s"] = [
        candidate["receipt_sha256"] for candidate in canonical["candidate_receipts"]
    ]
    canonical["candidate_receipt_inventory_sha256"] = hashlib.sha256(
        subject.canonical_json_bytes(canonical["candidate_receipt_sha256s"])
    ).hexdigest()
    provider = canonical["selected_provider_authority"]
    provider["selected_candidate_receipt_sha256"] = canonical["candidate_receipt_sha256s"][-1]
    provider["candidate_receipt_inventory_sha256"] = canonical["candidate_receipt_inventory_sha256"]
    _seal(provider, "authority_sha256")
    canonical["selected_provider_authority_sha256"] = provider["authority_sha256"]
    _seal(canonical, "authority_sha256")

    with pytest.raises(subject.NbaApiReleaseSelectionError, match="sealed compatibility plan"):
        subject.NbaApiReleaseSelectionAuthorityV1.from_canonical_bytes(
            subject.canonical_json_bytes(canonical),
            **{
                **_readback_kwargs(authority),
                "expected_authority_sha256": canonical["authority_sha256"],
                "expected_candidate_receipt_sha256s": tuple(canonical["candidate_receipt_sha256s"]),
                "expected_candidate_receipt_inventory_sha256": canonical[
                    "candidate_receipt_inventory_sha256"
                ],
                "expected_selected_provider_authority_sha256": provider["authority_sha256"],
            },
        )


def test_signals_and_collector_failures_cannot_be_relabelled_as_provider_failures() -> None:
    bundle = _bundle()
    command = bundle["candidate_payloads"][0]["commands"][1]
    command["termination_kind"] = "signaled"
    command["exit_code"] = None
    command["signal_number"] = 9
    command["result"] = "provider_incompatible"
    _seal(command, "receipt_sha256")
    _seal(bundle["candidate_payloads"][0], "receipt_sha256")
    _refresh_bytes(bundle)
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="validator-derived"):
        _select(bundle)

    bundle = _bundle()
    command = bundle["candidate_payloads"][0]["commands"][1]
    command["collector_outcome"] = "collector_failure"
    command["termination_kind"] = "unobserved"
    command["exit_code"] = 0
    command["signal_number"] = None
    command["result"] = "provider_incompatible"
    _seal(command, "receipt_sha256")
    _seal(bundle["candidate_payloads"][0], "receipt_sha256")
    _refresh_bytes(bundle)
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="cannot project"):
        _select(bundle)

    bundle = _bundle()
    command = bundle["candidate_payloads"][0]["commands"][1]
    command["termination_kind"] = "exited"
    command["exit_code"] = -9
    command["signal_number"] = None
    command["result"] = "provider_incompatible"
    _seal(command, "receipt_sha256")
    _seal(bundle["candidate_payloads"][0], "receipt_sha256")
    _refresh_bytes(bundle)
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="exit code"):
        _select(bundle)


def test_legacy_untyped_command_failure_is_rejected() -> None:
    bundle = _bundle()
    candidate = bundle["candidate_payloads"][0]
    candidate["commands"][1]["result"] = "failed"
    _seal(candidate["commands"][1], "receipt_sha256")
    _seal(candidate, "receipt_sha256")
    _refresh_bytes(bundle)

    with pytest.raises(subject.NbaApiReleaseSelectionError, match="result is invalid"):
        _select(bundle)


def test_authenticated_clock_receipts_reject_foreign_or_stale_point_of_use() -> None:
    bundle = _bundle()
    foreign_clock = deepcopy(bundle["selection_clock"])
    foreign_clock["observed_now_at_utc"] = "2026-08-28T12:04:31Z"
    _seal(foreign_clock, "receipt_sha256")
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="authenticated execution"):
        subject.select_latest_compatible_release(
            **{
                **bundle["kwargs"],
                "execution_clock_receipt_bytes": subject.canonical_json_bytes(foreign_clock),
            }
        )

    authority = _select(bundle)
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="stale|chronology"):
        subject.NbaApiReleaseSelectionAuthorityV1.from_canonical_bytes(
            authority.to_canonical_bytes(),
            **_readback_kwargs(authority, trusted_now_utc="2026-08-28T12:09:01Z"),
        )
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="stale|chronology"):
        subject.NbaApiReleaseSelectionAuthorityV1.from_canonical_bytes(
            authority.to_canonical_bytes(),
            **_readback_kwargs(authority, trusted_now_utc="2026-08-28T12:03:59Z"),
        )


def test_authenticated_clock_receipts_cannot_rebind_phase_or_selection_context() -> None:
    bundle = _bundle()
    foreign_clock = deepcopy(bundle["selection_clock"])
    foreign_clock["phase"] = "readback"
    _seal(foreign_clock, "receipt_sha256")
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="authenticated execution"):
        subject.select_latest_compatible_release(
            **{
                **bundle["kwargs"],
                "execution_clock_receipt_bytes": subject.canonical_json_bytes(foreign_clock),
                "expected_execution_clock_receipt_sha256": foreign_clock["receipt_sha256"],
            }
        )

    authority = _select(bundle)
    readback_kwargs = _readback_kwargs(authority)
    foreign_readback = json.loads(readback_kwargs["readback_clock_receipt_bytes"])
    foreign_readback["stack_identity_sha256"] = "f" * 64
    _seal(foreign_readback, "receipt_sha256")
    with pytest.raises(subject.NbaApiReleaseSelectionError, match="authenticated execution"):
        subject.NbaApiReleaseSelectionAuthorityV1.from_canonical_bytes(
            authority.to_canonical_bytes(),
            **{
                **readback_kwargs,
                "expected_readback_clock_receipt_sha256": foreign_readback["receipt_sha256"],
                "readback_clock_receipt_bytes": subject.canonical_json_bytes(foreign_readback),
            },
        )


def test_first_version_dto_names_have_no_compatibility_aliases() -> None:
    for forbidden_alias in (
        "CandidateCompatibilityReceipt",
        "CompatibilityCommandReceipt",
        "ExecutionClockReceipt",
        "NbaApiReleaseSelectionAuthority",
        "ObservedProviderAuthority",
        "ReleaseArchive",
        "ReleaseInventoryEntry",
    ):
        assert not hasattr(subject, forbidden_alias)


def test_coordinated_old_internal_chronology_cannot_override_trusted_now() -> None:
    bundle = _bundle()
    candidate_times = (
        (
            ("2000-01-01T00:01:00Z", "2000-01-01T00:01:10Z"),
            ("2000-01-01T00:01:11Z", "2000-01-01T00:01:20Z"),
        ),
        (
            ("2000-01-01T00:02:00Z", "2000-01-01T00:02:10Z"),
            ("2000-01-01T00:02:11Z", "2000-01-01T00:02:20Z"),
        ),
    )
    for candidate, times in zip(bundle["candidate_payloads"], candidate_times, strict=True):
        for command, (started, completed) in zip(candidate["commands"], times, strict=True):
            command["started_at_utc"] = started
            command["completed_at_utc"] = completed
            _seal(command, "receipt_sha256")
        _seal(candidate, "receipt_sha256")
    bundle["provider"]["observed_at_utc"] = "2000-01-01T00:03:00Z"
    _seal(bundle["provider"], "authority_sha256")
    _refresh_bytes(
        bundle,
        retrieved_at_utc="2000-01-01T00:00:05Z",
        execution_kickoff_at_utc="2000-01-01T00:00:00Z",
        selection_completed_at_utc="2000-01-01T00:04:00Z",
        trusted_now_utc=TRUSTED_NOW_AT,
    )

    with pytest.raises(subject.NbaApiReleaseSelectionError, match="stale|chronology"):
        _select(bundle)
