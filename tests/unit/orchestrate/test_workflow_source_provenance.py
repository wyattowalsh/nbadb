from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import pathlib
import stat
import subprocess
import sys
import zipfile
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_SCRIPT_PATH = _REPO_ROOT / ".github" / "scripts" / "workflow_source_provenance.py"


def _load_module() -> object:
    spec = importlib.util.spec_from_file_location("workflow_source_provenance", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _content(path: str, body: bytes) -> dict[str, object]:
    blob_sha = hashlib.sha1(  # noqa: S324 - fixture models a Git blob ID.
        f"blob {len(body)}\0".encode() + body
    ).hexdigest()
    return {
        "content": base64.b64encode(body).decode(),
        "encoding": "base64",
        "path": path,
        "sha": blob_sha,
        "size": len(body),
        "type": "file",
    }


def _fixture(
    *,
    source_sha: str,
    owner_sha: str,
    workflow_body: bytes = b"name: Full Extraction\n",
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    repository = "acme/nbadb"
    run_id = 12345
    workflow_path = ".github/workflows/full-extraction.yml"
    run = {
        "conclusion": "success",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": owner_sha,
        "id": run_id,
        "path": workflow_path,
        "repository": {"full_name": repository},
        "run_attempt": 1,
        "status": "completed",
        "url": f"https://api.github.test/repos/{repository}/actions/runs/{run_id}",
        "workflow_id": 99,
    }
    workflow = {"id": 99, "path": workflow_path}
    comparison = {
        "ahead_by": 1,
        "base_commit": {"sha": source_sha},
        "behind_by": 0,
        "merge_base_commit": {"sha": source_sha},
        "status": "ahead",
    }
    return run, workflow, comparison, _content(workflow_path, workflow_body)


def _attest(
    monkeypatch: pytest.MonkeyPatch,
    *,
    source_sha: str,
    owner_sha: str,
    mutate: Callable[[dict[str, object], dict[str, object], dict[str, object]], None] | None = None,
    owner_content: dict[str, object] | None = None,
) -> dict[str, object]:
    module = _load_module()
    run, workflow, comparison, source_content = _fixture(
        source_sha=source_sha,
        owner_sha=owner_sha,
    )
    if mutate is not None:
        mutate(run, workflow, comparison)

    def gh_json(path: str, *, fields: dict[str, str] | None = None) -> object:
        if path.endswith("/actions/runs/12345"):
            return run
        if "/actions/workflows/" in path:
            return workflow
        if "/compare/" in path:
            return comparison
        assert fields is not None
        if fields["ref"] == source_sha:
            return source_content
        if fields["ref"] == owner_sha:
            return owner_content or source_content
        raise AssertionError((path, fields))

    monkeypatch.setattr(module, "_gh_json", gh_json)
    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_API_URL", "https://api.github.test")
    return module.attest_run(
        repository="acme/nbadb",
        run_id=12345,
        source_sha=source_sha,
        trusted_branch="main",
        workflow_path=".github/workflows/full-extraction.yml",
        required_state="completed",
    )


@pytest.mark.parametrize("same_commit", [True, False])
def test_attestor_accepts_identical_or_ancestor_owner_with_same_workflow(
    monkeypatch: pytest.MonkeyPatch,
    same_commit: bool,
) -> None:
    source_sha = "a" * 40
    owner_sha = source_sha if same_commit else "b" * 40

    result = _attest(
        monkeypatch,
        source_sha=source_sha,
        owner_sha=owner_sha,
    )

    assert result["semantic_source"] == {
        "relation": "identical" if same_commit else "ancestor",
        "sha": source_sha,
    }
    assert result["run"]["head_sha"] == owner_sha
    assert result["workflow"]["sha256"] == hashlib.sha256(b"name: Full Extraction\n").hexdigest()


@pytest.mark.parametrize(
    ("label", "mutation"),
    [
        ("run-id", lambda run, _workflow, _comparison: run.update(id=12346)),
        ("run-id-bool", lambda run, _workflow, _comparison: run.update(id=True)),
        ("run-id-float", lambda run, _workflow, _comparison: run.update(id=12345.0)),
        ("url", lambda run, _workflow, _comparison: run.update(url="https://bad.test")),
        (
            "repository",
            lambda run, _workflow, _comparison: run.update(repository={"full_name": "other/repo"}),
        ),
        ("event", lambda run, _workflow, _comparison: run.update(event="push")),
        ("path", lambda run, _workflow, _comparison: run.update(path="ci.yml")),
        ("branch", lambda run, _workflow, _comparison: run.update(head_branch="release")),
        ("attempt", lambda run, _workflow, _comparison: run.update(run_attempt=2)),
        ("workflow-id", lambda run, _workflow, _comparison: run.update(workflow_id=100)),
        ("status", lambda run, _workflow, _comparison: run.update(status="waiting")),
        (
            "conclusion",
            lambda run, _workflow, _comparison: run.update(conclusion="action_required"),
        ),
        (
            "workflow-path",
            lambda _run, workflow, _comparison: workflow.update(path="ci.yml"),
        ),
        (
            "workflow-definition-id-bool",
            lambda _run, workflow, _comparison: workflow.update(id=True),
        ),
        (
            "workflow-definition-id-float",
            lambda _run, workflow, _comparison: workflow.update(id=99.0),
        ),
        (
            "unrelated",
            lambda _run, _workflow, comparison: comparison.update(status="diverged"),
        ),
        (
            "wrong-base",
            lambda _run, _workflow, comparison: comparison.update(base_commit={"sha": "c" * 40}),
        ),
        (
            "wrong-merge-base",
            lambda _run, _workflow, comparison: comparison.update(
                merge_base_commit={"sha": "c" * 40}
            ),
        ),
        (
            "behind",
            lambda _run, _workflow, comparison: comparison.update(behind_by=1),
        ),
        (
            "bool-behind",
            lambda _run, _workflow, comparison: comparison.update(behind_by=False),
        ),
        (
            "bool-ahead",
            lambda _run, _workflow, comparison: comparison.update(ahead_by=True),
        ),
    ],
)
def test_attestor_rejects_each_identity_or_ancestry_mutation(
    monkeypatch: pytest.MonkeyPatch,
    label: str,
    mutation: Callable[[dict[str, object], dict[str, object], dict[str, object]], None],
) -> None:
    with pytest.raises(RuntimeError):
        _attest(
            monkeypatch,
            source_sha="a" * 40,
            owner_sha="b" * 40,
            mutate=mutation,
        )


def test_attestor_rejects_workflow_byte_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = ".github/workflows/full-extraction.yml"
    with pytest.raises(RuntimeError, match="definition differs"):
        _attest(
            monkeypatch,
            source_sha="a" * 40,
            owner_sha="b" * 40,
            owner_content=_content(path, b"name: Changed\n"),
        )


def test_cli_writes_nothing_when_attestation_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    module = _load_module()
    output = tmp_path / "attestation.json"
    monkeypatch.setattr(
        module,
        "attest_run",
        lambda **_kwargs: (_ for _ in ()).throw(module.ProvenanceError("rejected")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(_SCRIPT_PATH),
            "attest-run",
            "--repository",
            "acme/nbadb",
            "--run-id",
            "12345",
            "--source-sha",
            "a" * 40,
            "--trusted-branch",
            "main",
            "--workflow-path",
            ".github/workflows/full-extraction.yml",
            "--output",
            str(output),
        ],
    )

    with pytest.raises(SystemExit, match="rejected"):
        module.main()

    assert not output.exists()


def test_api_failures_do_not_expose_response_or_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout='{"token":"secret-token"}',
            stderr="secret-token",
        ),
    )

    with pytest.raises(RuntimeError) as raised:
        module._gh_json("/repos/acme/nbadb/actions/runs/12345")

    assert str(raised.value) == "GitHub API request failed"
    assert "secret-token" not in str(raised.value)


def _attestation_fixture(*, head_sha: str = "b" * 40) -> dict[str, object]:
    repository = "acme/nbadb"
    run_id = 12345
    workflow_path = ".github/workflows/full-extraction.yml"
    return {
        "repository": repository,
        "run": {
            "attempt": 1,
            "conclusion": "success",
            "event": "workflow_dispatch",
            "head_branch": "main",
            "head_sha": head_sha,
            "id": run_id,
            "path": workflow_path,
            "status": "completed",
            "url": f"https://api.github.com/repos/{repository}/actions/runs/{run_id}",
            "workflow_id": 99,
        },
        "schema_version": 1,
        "semantic_source": {"relation": "ancestor", "sha": "a" * 40},
        "workflow": {
            "blob_sha": "c" * 40,
            "path": workflow_path,
            "sha256": "d" * 64,
            "size_in_bytes": 10,
        },
    }


def _run_from_attestation(attestation: dict[str, object]) -> dict[str, object]:
    run = attestation["run"]
    assert isinstance(run, dict)
    return {
        "conclusion": run["conclusion"],
        "event": run["event"],
        "head_branch": run["head_branch"],
        "head_sha": run["head_sha"],
        "id": run["id"],
        "path": run["path"],
        "repository": {"full_name": attestation["repository"]},
        "run_attempt": run["attempt"],
        "status": run["status"],
        "url": run["url"],
        "workflow_id": run["workflow_id"],
    }


def _artifact_fixture(
    *,
    artifact_id: int = 701,
    head_sha: str = "b" * 40,
    size: int = 4096,
) -> dict[str, object]:
    repository = "acme/nbadb"
    return {
        "archive_download_url": (
            f"https://api.github.com/repos/{repository}/actions/artifacts/{artifact_id}/zip"
        ),
        "digest": "sha256:" + "e" * 64,
        "expired": False,
        "id": artifact_id,
        "name": "artifact-name",
        "size_in_bytes": size,
        "workflow_run": {"head_sha": head_sha, "id": 12345},
    }


@pytest.mark.parametrize("attempt", [2, True, 1.0])
def test_recheck_rejects_rerun_created_after_attestation(
    monkeypatch: pytest.MonkeyPatch,
    attempt: object,
) -> None:
    module = _load_module()
    attestation = _attestation_fixture()
    rerun = {**_run_from_attestation(attestation), "run_attempt": attempt}
    monkeypatch.setattr(module, "_gh_json", lambda *_args, **_kwargs: rerun)

    with pytest.raises(RuntimeError, match="changed after provenance attestation"):
        module.recheck_attested_run(attestation)


def test_recheck_rejects_boolean_schema_before_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    attestation = {**_attestation_fixture(), "schema_version": True}
    api_calls: list[str] = []
    monkeypatch.setattr(module, "_gh_json", lambda path, **_kwargs: api_calls.append(path))

    with pytest.raises(RuntimeError, match="attestation is malformed"):
        module.recheck_attested_run(attestation)

    assert api_calls == []


@pytest.mark.parametrize("run_id", [0, -1, True])
def test_attestor_rejects_invalid_run_id_before_api(
    monkeypatch: pytest.MonkeyPatch,
    run_id: int,
) -> None:
    module = _load_module()
    api_calls: list[str] = []
    monkeypatch.setattr(
        module,
        "_gh_json",
        lambda path, **_kwargs: api_calls.append(path),
    )
    monkeypatch.setenv("GH_TOKEN", "test-token")

    with pytest.raises(RuntimeError, match="run ID must be a positive integer"):
        module.attest_run(
            repository="acme/nbadb",
            run_id=run_id,
            source_sha="a" * 40,
            trusted_branch="main",
            workflow_path=".github/workflows/full-extraction.yml",
            required_state="completed",
        )

    assert api_calls == []


@pytest.mark.parametrize("run_id", [0, -1, True])
def test_current_artifact_rejects_invalid_run_id_before_api(
    monkeypatch: pytest.MonkeyPatch,
    run_id: int,
) -> None:
    module = _load_module()
    api_calls: list[str] = []
    monkeypatch.setattr(
        module,
        "_gh_json",
        lambda path, **_kwargs: api_calls.append(path),
    )

    with pytest.raises(RuntimeError, match="current run ID must be a positive integer"):
        module.verify_current_artifact(
            repository="acme/nbadb",
            run_id=run_id,
            run_attempt=1,
            head_sha="b" * 40,
            trusted_branch="main",
            workflow_path=".github/workflows/full-extraction.yml",
            artifact_id=701,
            artifact_name="artifact-name",
            artifact_digest="sha256:" + "e" * 64,
        )

    assert api_calls == []


def test_resolve_artifact_accepts_ancestor_source_and_exact_stable_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    attestation = _attestation_fixture()
    run = _run_from_attestation(attestation)
    artifact = _artifact_fixture()
    inventory = {"artifacts": [artifact], "total_count": 1}
    responses = iter([run, inventory, inventory, inventory, artifact, run])
    monkeypatch.setattr(module, "_gh_json", lambda *_args, **_kwargs: next(responses))

    receipt = module.resolve_attested_artifact(
        attestation=attestation,
        artifact_name="artifact-name",
        poll_interval_seconds=0,
    )

    assert receipt["id"] == 701
    assert receipt["workflow_run_sha"] == "b" * 40


def test_resolve_artifact_rejects_unstable_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    attestation = _attestation_fixture()
    run = _run_from_attestation(attestation)
    first = {"artifacts": [_artifact_fixture(size=4096)], "total_count": 1}
    second = {"artifacts": [_artifact_fixture(size=4097)], "total_count": 1}
    third = {"artifacts": [_artifact_fixture(size=4098)], "total_count": 1}
    responses = iter([run, first, second, third])
    monkeypatch.setattr(module, "_gh_json", lambda *_args, **_kwargs: next(responses))

    with pytest.raises(RuntimeError, match="did not stabilize"):
        module.resolve_attested_artifact(
            attestation=attestation,
            artifact_name="artifact-name",
            poll_interval_seconds=0,
        )


def test_resolve_artifact_rejects_direct_id_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    attestation = _attestation_fixture()
    run = _run_from_attestation(attestation)
    artifact = _artifact_fixture()
    inventory = {"artifacts": [artifact], "total_count": 1}
    responses = iter([run, inventory, inventory, inventory, _artifact_fixture(size=4097)])
    monkeypatch.setattr(module, "_gh_json", lambda *_args, **_kwargs: next(responses))

    with pytest.raises(RuntimeError, match="changed before exact-ID download"):
        module.resolve_attested_artifact(
            attestation=attestation,
            artifact_name="artifact-name",
            poll_interval_seconds=0,
        )


def test_resolve_artifact_rejects_owner_drift_after_direct_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    attestation = _attestation_fixture()
    run = _run_from_attestation(attestation)
    artifact = _artifact_fixture()
    inventory = {"artifacts": [artifact], "total_count": 1}
    responses = iter([run, inventory, inventory, inventory, artifact, {**run, "run_attempt": 2}])
    api_calls: list[str] = []

    def gh_json(path: str, **_kwargs: object) -> object:
        api_calls.append(path)
        return next(responses)

    monkeypatch.setattr(module, "_gh_json", gh_json)

    with pytest.raises(RuntimeError, match="changed after provenance attestation"):
        module.resolve_attested_artifact(
            attestation=attestation,
            artifact_name="artifact-name",
            poll_interval_seconds=0,
        )

    assert api_calls[-2:] == [
        "/repos/acme/nbadb/actions/artifacts/701",
        "/repos/acme/nbadb/actions/runs/12345",
    ]


def test_prefix_resolution_compares_complete_inventory_stability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    attestation = _attestation_fixture()
    run = _run_from_attestation(attestation)
    selected = {**_artifact_fixture(), "name": "lane-selected"}
    unrelated = {
        **_artifact_fixture(artifact_id=702),
        "name": "unrelated",
    }
    inventories = [
        {"artifacts": [selected, unrelated], "total_count": 2},
        {"artifacts": [selected, unrelated], "total_count": 2},
        {
            "artifacts": [selected, {**unrelated, "size_in_bytes": 4097}],
            "total_count": 2,
        },
    ]
    responses = iter([run, *inventories])
    api_calls: list[str] = []

    def gh_json(path: str, **_kwargs: object) -> object:
        api_calls.append(path)
        return next(responses)

    monkeypatch.setattr(module, "_gh_json", gh_json)

    with pytest.raises(RuntimeError, match="artifact inventory did not stabilize"):
        module.resolve_attested_artifacts_by_prefix(
            attestation=attestation,
            artifact_name_prefix="lane-",
            poll_interval_seconds=0,
        )

    assert not any("/actions/artifacts/701" in call for call in api_calls)


def test_prefix_resolution_allows_stable_unusable_unrelated_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    attestation = _attestation_fixture()
    run = _run_from_attestation(attestation)
    selected = {**_artifact_fixture(), "name": "lane-selected"}
    unrelated = {
        **_artifact_fixture(artifact_id=702, size=0),
        "digest": None,
        "expired": True,
        "name": "unrelated-expired",
    }
    inventory = {"artifacts": [selected, unrelated], "total_count": 2}
    responses = iter([run, inventory, inventory, inventory, selected, run])
    monkeypatch.setattr(module, "_gh_json", lambda *_args, **_kwargs: next(responses))

    receipt = module.resolve_attested_artifacts_by_prefix(
        attestation=attestation,
        artifact_name_prefix="lane-",
        poll_interval_seconds=0,
    )

    assert receipt == {
        "artifacts": [
            module._normalize_artifact(
                selected,
                artifact_name="lane-selected",
                owner_head_sha="b" * 40,
                repository="acme/nbadb",
                run_id=12345,
            )
        ],
        "schema_version": 1,
    }


def test_artifact_inventory_rejects_duplicate_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    artifact = _artifact_fixture()
    monkeypatch.setattr(
        module,
        "_gh_json",
        lambda *_args, **_kwargs: {
            "artifacts": [artifact, artifact],
            "total_count": 2,
        },
    )

    with pytest.raises(RuntimeError, match="duplicate IDs"):
        module._artifact_inventory(
            artifact_name="artifact-name",
            owner_head_sha="b" * 40,
            repository="acme/nbadb",
            run_id=12345,
        )


@pytest.mark.parametrize(
    "missing_field",
    ["id", "digest", "size_in_bytes", "archive_download_url", "workflow_run"],
)
def test_artifact_identity_rejects_each_missing_receipt_field(
    missing_field: str,
) -> None:
    module = _load_module()
    artifact = _artifact_fixture()
    artifact.pop(missing_field)

    with pytest.raises(RuntimeError, match="artifact identity is malformed"):
        module._normalize_artifact(
            artifact,
            artifact_name="artifact-name",
            owner_head_sha="b" * 40,
            repository="acme/nbadb",
            run_id=12345,
        )


@pytest.mark.parametrize(
    ("attempt", "head_sha"),
    [(2, "b" * 40), (True, "b" * 40), (1, ""), (1, "c" * 40)],
)
def test_current_artifact_rejects_attempt_or_head_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    attempt: int,
    head_sha: str,
) -> None:
    module = _load_module()
    attestation = _attestation_fixture()
    run = _run_from_attestation(attestation)
    artifact = _artifact_fixture()
    monkeypatch.setattr(
        module,
        "_gh_json",
        lambda path, **_kwargs: run if "/actions/runs/" in path else artifact,
    )

    with pytest.raises(RuntimeError):
        module.verify_current_artifact(
            repository="acme/nbadb",
            run_id=12345,
            run_attempt=attempt,
            head_sha=head_sha,
            trusted_branch="main",
            workflow_path=".github/workflows/full-extraction.yml",
            artifact_id=701,
            artifact_name="artifact-name",
            artifact_digest="sha256:" + "e" * 64,
        )


@pytest.mark.parametrize("artifact_id", [0, -1, True])
def test_current_artifact_rejects_invalid_artifact_id_before_api(
    monkeypatch: pytest.MonkeyPatch,
    artifact_id: int,
) -> None:
    module = _load_module()
    api_calls: list[str] = []
    monkeypatch.setattr(
        module,
        "_gh_json",
        lambda path, **_kwargs: api_calls.append(path),
    )

    with pytest.raises(RuntimeError, match="current artifact ID must be a positive integer"):
        module.verify_current_artifact(
            repository="acme/nbadb",
            run_id=12345,
            run_attempt=1,
            head_sha="b" * 40,
            trusted_branch="main",
            workflow_path=".github/workflows/full-extraction.yml",
            artifact_id=artifact_id,
            artifact_name="artifact-name",
            artifact_digest="sha256:" + "e" * 64,
        )

    assert api_calls == []


def test_current_artifact_normalizes_raw_upload_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    attestation = _attestation_fixture()
    run = _run_from_attestation(attestation)
    artifact = _artifact_fixture()
    monkeypatch.setattr(
        module,
        "_gh_json",
        lambda path, **_kwargs: run if "/actions/runs/" in path else artifact,
    )

    receipt = module.verify_current_artifact(
        repository="acme/nbadb",
        run_id=12345,
        run_attempt=1,
        head_sha="b" * 40,
        trusted_branch="main",
        workflow_path=".github/workflows/full-extraction.yml",
        artifact_id=701,
        artifact_name="artifact-name",
        artifact_digest="e" * 64,
    )

    assert receipt["digest"] == "sha256:" + "e" * 64


def test_publication_reconciliation_accepts_later_owner_with_attempt_one_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    run = {
        **_run_from_attestation(_attestation_fixture()),
        "conclusion": None,
        "run_attempt": 2,
        "status": "in_progress",
    }
    artifact_name = "nbadb-full-extraction-assured-fixture-12345-1"
    artifact = {**_artifact_fixture(), "name": artifact_name}
    responses = iter([run, artifact, run])
    api_calls: list[str] = []

    def gh_json(path: str, **_kwargs: object) -> object:
        api_calls.append(path)
        return next(responses)

    monkeypatch.setattr(module, "_gh_json", gh_json)

    receipt = module.verify_current_artifact(
        repository="acme/nbadb",
        run_id=12345,
        run_attempt=2,
        head_sha="b" * 40,
        trusted_branch="main",
        workflow_path=".github/workflows/full-extraction.yml",
        artifact_id=701,
        artifact_name=artifact_name,
        artifact_digest="sha256:" + "e" * 64,
        producer_run_attempt=1,
        producer_artifact_name=artifact_name,
        reconciliation_role="publication_reconcile",
    )

    assert receipt["producer_run_attempt"] == 1
    assert receipt["verified_owner_run_attempt"] == 2
    assert receipt["reconciliation_role"] == "publication_reconcile"
    assert api_calls == [
        "/repos/acme/nbadb/actions/runs/12345",
        "/repos/acme/nbadb/actions/artifacts/701",
        "/repos/acme/nbadb/actions/runs/12345",
    ]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "current workflow run attempt must be one"),
        (
            {
                "producer_run_attempt": 1,
                "producer_artifact_name": "nbadb-full-extraction-assured-fixture-12345-1",
                "reconciliation_role": "dispatch_reconcile",
            },
            "artifact reconciliation role is invalid",
        ),
        (
            {
                "producer_run_attempt": 2,
                "producer_artifact_name": "nbadb-full-extraction-assured-fixture-12345-1",
                "reconciliation_role": "publication_reconcile",
            },
            "producer run attempt must be one",
        ),
        (
            {
                "producer_run_attempt": 1,
                "producer_artifact_name": "nbadb-full-extraction-assured-fixture-12345-1",
                "reconciliation_role": "publication_reconcile",
                "artifact_name": "nbadb-full-extraction-assured-fixture-12345-2",
            },
            "not bound to its attempt-one producer",
        ),
    ],
)
def test_publication_reconciliation_rejects_invalid_role_or_producer_before_api(
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, object],
    message: str,
) -> None:
    module = _load_module()
    artifact_name = str(
        kwargs.pop(
            "artifact_name",
            "nbadb-full-extraction-assured-fixture-12345-1",
        )
    )
    api_calls: list[str] = []
    monkeypatch.setattr(module, "_gh_json", lambda path, **_kwargs: api_calls.append(path))

    with pytest.raises(RuntimeError, match=message):
        module.verify_current_artifact(
            repository="acme/nbadb",
            run_id=12345,
            run_attempt=2,
            head_sha="b" * 40,
            trusted_branch="main",
            workflow_path=".github/workflows/full-extraction.yml",
            artifact_id=701,
            artifact_name=artifact_name,
            artifact_digest="sha256:" + "e" * 64,
            **kwargs,
        )

    assert api_calls == []


def test_publication_reconciliation_rejects_final_owner_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    run = {
        **_run_from_attestation(_attestation_fixture()),
        "conclusion": None,
        "run_attempt": 2,
        "status": "in_progress",
    }
    artifact_name = "nbadb-full-extraction-assured-fixture-12345-1"
    artifact = {**_artifact_fixture(), "name": artifact_name}
    responses = iter([run, artifact, {**run, "status": "completed", "conclusion": "success"}])
    api_calls: list[str] = []

    def gh_json(path: str, **_kwargs: object) -> object:
        api_calls.append(path)
        return next(responses)

    monkeypatch.setattr(module, "_gh_json", gh_json)

    with pytest.raises(RuntimeError, match="changed after artifact receipt"):
        module.verify_current_artifact(
            repository="acme/nbadb",
            run_id=12345,
            run_attempt=2,
            head_sha="b" * 40,
            trusted_branch="main",
            workflow_path=".github/workflows/full-extraction.yml",
            artifact_id=701,
            artifact_name=artifact_name,
            artifact_digest="sha256:" + "e" * 64,
            producer_run_attempt=1,
            producer_artifact_name=artifact_name,
            reconciliation_role="publication_reconcile",
        )

    assert api_calls[-2:] == [
        "/repos/acme/nbadb/actions/artifacts/701",
        "/repos/acme/nbadb/actions/runs/12345",
    ]


def test_current_artifact_rejects_owner_drift_after_artifact_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    attestation = _attestation_fixture()
    run = _run_from_attestation(attestation)
    artifact = _artifact_fixture()
    responses = iter([run, artifact, {**run, "run_attempt": 2}])
    api_calls: list[str] = []

    def gh_json(path: str, **_kwargs: object) -> object:
        api_calls.append(path)
        return next(responses)

    monkeypatch.setattr(module, "_gh_json", gh_json)

    with pytest.raises(RuntimeError, match="current workflow run identity is invalid"):
        module.verify_current_artifact(
            repository="acme/nbadb",
            run_id=12345,
            run_attempt=1,
            head_sha="b" * 40,
            trusted_branch="main",
            workflow_path=".github/workflows/full-extraction.yml",
            artifact_id=701,
            artifact_name="artifact-name",
            artifact_digest="sha256:" + "e" * 64,
        )

    assert api_calls == [
        "/repos/acme/nbadb/actions/runs/12345",
        "/repos/acme/nbadb/actions/artifacts/701",
        "/repos/acme/nbadb/actions/runs/12345",
    ]


def test_download_rechecks_direct_id_before_fetching_archive(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    module = _load_module()
    attestation = _attestation_fixture()
    run = _run_from_attestation(attestation)
    artifact = _artifact_fixture()
    receipt = module._normalize_artifact(
        artifact,
        artifact_name="artifact-name",
        owner_head_sha="b" * 40,
        repository="acme/nbadb",
        run_id=12345,
    )
    monkeypatch.setattr(
        module,
        "_gh_json",
        lambda path, **_kwargs: run if "/actions/runs/" in path else _artifact_fixture(size=4097),
    )
    download_called = False

    def stream_gh_archive(_path: str, _destination: pathlib.Path) -> None:
        nonlocal download_called
        download_called = True

    monkeypatch.setattr(module, "_stream_gh_archive", stream_gh_archive)

    with pytest.raises(RuntimeError, match="changed before exact-ID download"):
        module.download_attested_artifact(
            attestation=attestation,
            receipt=receipt,
            output_dir=tmp_path / "output",
        )
    assert download_called is False


def test_download_streams_and_hashes_exact_receipt_before_safe_extraction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    module = _load_module()
    attestation = _attestation_fixture()
    run = _run_from_attestation(attestation)
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("payload/data.json", json.dumps({"ok": True}))
    archive_bytes = archive_buffer.getvalue()
    artifact = {
        **_artifact_fixture(size=len(archive_bytes)),
        "digest": "sha256:" + hashlib.sha256(archive_bytes).hexdigest(),
    }
    receipt = module._normalize_artifact(
        artifact,
        artifact_name="artifact-name",
        owner_head_sha="b" * 40,
        repository="acme/nbadb",
        run_id=12345,
    )
    monkeypatch.setattr(
        module,
        "_gh_json",
        lambda path, **_kwargs: run if "/actions/runs/" in path else artifact,
    )
    monkeypatch.setattr(
        module,
        "_stream_gh_archive",
        lambda _path, destination: destination.write_bytes(archive_bytes),
    )
    output_dir = tmp_path / "output"

    module.download_attested_artifact(
        attestation=attestation,
        receipt=receipt,
        output_dir=output_dir,
    )

    assert json.loads((output_dir / "payload" / "data.json").read_text(encoding="utf-8")) == {
        "ok": True
    }
    assert not list(tmp_path.glob(".artifact-*.zip"))


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("traversal", "unsafe member"),
        ("absolute", "unsafe member"),
        ("backslash", "unsafe member"),
        ("normalized-duplicate", "unsafe member"),
        ("symlink", "unsafe member"),
        ("special-file", "unsafe member"),
        ("special-directory", "unsafe member"),
        ("file-parent", "file-parent collision"),
        ("empty", "archive is empty"),
    ],
)
def test_download_rejects_every_unsafe_archive_layout_before_extracting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    case: str,
    message: str,
) -> None:
    module = _load_module()
    attestation = _attestation_fixture()
    run = _run_from_attestation(attestation)
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        if case != "empty":
            archive.writestr("safe.json", "must-not-be-written")
        if case == "traversal":
            archive.writestr("../escape", "unsafe")
        elif case == "absolute":
            archive.writestr("/absolute/path", "unsafe")
        elif case == "backslash":
            archive.writestr("nested\\member", "unsafe")
        elif case == "normalized-duplicate":
            archive.writestr("duplicate/member", "first")
            archive.writestr("duplicate//member", "second")
        elif case == "symlink":
            member = zipfile.ZipInfo("nested/link")
            member.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(member, "target")
        elif case == "special-file":
            member = zipfile.ZipInfo("nested/fifo")
            member.external_attr = (stat.S_IFIFO | 0o644) << 16
            archive.writestr(member, b"")
        elif case == "special-directory":
            member = zipfile.ZipInfo("nested/fifo/")
            member.external_attr = (stat.S_IFIFO | 0o755) << 16
            archive.writestr(member, b"")
        elif case == "file-parent":
            archive.writestr("nested", "file")
            archive.writestr("nested/member", "child")
        elif case != "empty":
            raise AssertionError(case)
    archive_bytes = archive_buffer.getvalue()
    artifact = {
        **_artifact_fixture(size=len(archive_bytes)),
        "digest": "sha256:" + hashlib.sha256(archive_bytes).hexdigest(),
    }
    receipt = module._normalize_artifact(
        artifact,
        artifact_name="artifact-name",
        owner_head_sha="b" * 40,
        repository="acme/nbadb",
        run_id=12345,
    )
    monkeypatch.setattr(
        module,
        "_gh_json",
        lambda path, **_kwargs: run if "/actions/runs/" in path else artifact,
    )
    monkeypatch.setattr(
        module,
        "_stream_gh_archive",
        lambda _path, destination: destination.write_bytes(archive_bytes),
    )
    output_dir = tmp_path / "output"

    with pytest.raises(RuntimeError, match=message):
        module.download_attested_artifact(
            attestation=attestation,
            receipt=receipt,
            output_dir=output_dir,
        )

    assert not (output_dir / "safe.json").exists()
    assert not list(tmp_path.glob(".artifact-*.zip"))


@pytest.mark.parametrize("collision_kind", ["file", "broken-symlink"])
def test_download_preflights_all_destination_parents_before_extracting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    collision_kind: str,
) -> None:
    module = _load_module()
    attestation = _attestation_fixture()
    run = _run_from_attestation(attestation)
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("safe.json", "must-not-be-written")
        archive.writestr("nested/data.json", "blocked")
    archive_bytes = archive_buffer.getvalue()
    artifact = {
        **_artifact_fixture(size=len(archive_bytes)),
        "digest": "sha256:" + hashlib.sha256(archive_bytes).hexdigest(),
    }
    receipt = module._normalize_artifact(
        artifact,
        artifact_name="artifact-name",
        owner_head_sha="b" * 40,
        repository="acme/nbadb",
        run_id=12345,
    )
    monkeypatch.setattr(
        module,
        "_gh_json",
        lambda path, **_kwargs: run if "/actions/runs/" in path else artifact,
    )
    monkeypatch.setattr(
        module,
        "_stream_gh_archive",
        lambda _path, destination: destination.write_bytes(archive_bytes),
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    nested = output_dir / "nested"
    if collision_kind == "file":
        nested.write_text("existing", encoding="utf-8")
    else:
        nested.symlink_to(output_dir / "missing-target", target_is_directory=True)

    with pytest.raises(RuntimeError, match="destination"):
        module.download_attested_artifact(
            attestation=attestation,
            receipt=receipt,
            output_dir=output_dir,
        )

    assert not (output_dir / "safe.json").exists()
    assert not list(tmp_path.glob(".artifact-*.zip"))
