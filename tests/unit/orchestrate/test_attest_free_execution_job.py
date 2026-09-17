from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[3] / ".github" / "scripts" / "attest_free_execution_job.py"
)


def _load_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("attest_free_execution_job", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(value: str = "a") -> str:
    return (value * 40)[:40]


def _env(tmp_path: Path, *, job: str = "plan", lane_id: str = "") -> dict[str, str]:
    workflow = tmp_path / ".github" / "workflows" / "full-extraction.yml"
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text("name: Full Extraction\n", encoding="utf-8")
    output = tmp_path / "github-output"
    output.write_text("", encoding="utf-8")
    env = {
        "GH_TOKEN": "ghs_test",
        "GITHUB_REPOSITORY": "wyattowalsh/nbadb",
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_JOB": job,
        "GITHUB_SHA": _sha("b"),
        "WORKFLOW_SOURCE_SHA": _sha("b"),
        "GITHUB_API_URL": "https://api.github.com",
        "RUNNER_NAME": "runner-1",
        "FULL_EXTRACTION_OPERATION": "extract",
        "GITHUB_OUTPUT": str(output),
        "LANE_ID": lane_id,
    }
    return env


def _job_row(*, job: str = "plan", lane: str | None = None) -> dict[str, Any]:
    name = job if lane is None else f"{job} ({lane}, 1)"
    return {
        "id": 99,
        "name": name,
        "run_id": 123,
        "run_attempt": 1,
        "head_sha": _sha("b"),
        "runner_name": "runner-1",
        "status": "in_progress",
        "started_at": "2026-09-16T12:00:00Z",
        "url": "https://api.github.com/repos/wyattowalsh/nbadb/actions/jobs/99",
        "run_url": "https://api.github.com/repos/wyattowalsh/nbadb/actions/runs/123",
    }


@pytest.fixture
def module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    loaded = _load_module()
    monkeypatch.setattr(loaded.time, "sleep", lambda _seconds: None)
    return loaded


def _install_gh(module, monkeypatch: pytest.MonkeyPatch, *, job: str = "plan") -> None:
    row = _job_row(job=job)

    def fake_gh(path: str) -> object:
        if path.endswith("/actions/runs/123"):
            return {
                "id": 123,
                "run_attempt": 1,
                "event": "workflow_dispatch",
                "path": ".github/workflows/full-extraction.yml",
                "url": "https://api.github.com/repos/wyattowalsh/nbadb/actions/runs/123",
                "repository": {"full_name": "wyattowalsh/nbadb"},
            }
        if "/jobs?" in path:
            return {"total_count": 1, "jobs": [row]}
        if path.endswith("/actions/jobs/99"):
            return row
        raise AssertionError(path)

    monkeypatch.setattr(module, "_gh_json", fake_gh)


def test_collect_writes_admitted_outputs(
    tmp_path: Path, module, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _env(tmp_path)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    _install_gh(module, monkeypatch)
    assert module.main(["collect"]) == 0
    assert Path(env["GITHUB_OUTPUT"]).read_text(encoding="utf-8") == (
        "status=admitted\n"
        "authenticated=true\n"
        "runtime-context-status=authenticated\n"
        "storage-mutations-allowed=true\n"
        "provider-calls-allowed=true\n"
        "mutations-authorized=true\n"
    )


def test_collect_refuses_missing_token(
    tmp_path: Path, module, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key, value in _env(tmp_path).items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="1"):
        module.main(["collect"])
    assert Path(os.environ["GITHUB_OUTPUT"]).read_text(encoding="utf-8") == ""


def test_authorize_and_verify_round_trip(
    tmp_path: Path, module, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _env(tmp_path, job="extract", lane_id="lane-1")
    env.update(
        {
            "OPERATION_AUTHORITY_STATUS": "validated",
            "COLLECTOR_STATUS": "admitted",
            "COLLECTOR_AUTHENTICATED": "true",
            "RUNTIME_CONTEXT_STATUS": "authenticated",
            "STORAGE_MUTATIONS_ALLOWED": "true",
            "PROVIDER_CALLS_ALLOWED": "true",
            "MUTATIONS_AUTHORIZED": "true",
        }
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    _install_gh(module, monkeypatch, job="extract")
    path = "artifacts/extraction/free-execution-authorization.json"
    assert module.main(["authorize", "--output", path]) == 0
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload["collector_status"] == "admitted"
    assert payload["operation_authority_status"] == "validated"
    assert payload["lane_id"] == "lane-1"
    assert payload["provider_calls_allowed"] is True
    workflow_sha256 = hashlib.sha256(
        (tmp_path / ".github/workflows/full-extraction.yml").read_bytes()
    ).hexdigest()
    assert payload["workflow_sha256"] == workflow_sha256
    assert "authorization" not in payload
    assert module.main(["verify", "--input", path]) == 0


def test_authorize_refuses_unadmitted_collectors(
    tmp_path: Path, module, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _env(tmp_path, job="discovery_seed")
    env["OPERATION_AUTHORITY_STATUS"] = "validated"
    env["COLLECTOR_STATUS"] = "capacity_blocked"
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit, match="1"):
        module.main(
            [
                "authorize",
                "--output",
                "artifacts/discovery/free-execution-authorization.json",
            ]
        )


def test_collect_refuses_non_plan_job(
    tmp_path: Path, module, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key, value in _env(tmp_path, job="extract", lane_id="lane-1").items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit, match="1"):
        module.main(["collect"])


def test_authorize_refuses_wrong_output_path(
    tmp_path: Path, module, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _env(tmp_path, job="extract", lane_id="lane-1")
    env.update(
        {
            "OPERATION_AUTHORITY_STATUS": "validated",
            "COLLECTOR_STATUS": "admitted",
            "COLLECTOR_AUTHENTICATED": "true",
            "RUNTIME_CONTEXT_STATUS": "authenticated",
            "STORAGE_MUTATIONS_ALLOWED": "true",
            "PROVIDER_CALLS_ALLOWED": "true",
            "MUTATIONS_AUTHORIZED": "true",
        }
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit, match="1"):
        module.main(
            [
                "authorize",
                "--output",
                "artifacts/discovery/free-execution-authorization.json",
            ]
        )


def test_authorize_refuses_extract_without_lane_id(
    tmp_path: Path, module, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _env(tmp_path, job="extract")
    env.update(
        {
            "OPERATION_AUTHORITY_STATUS": "validated",
            "COLLECTOR_STATUS": "admitted",
            "COLLECTOR_AUTHENTICATED": "true",
            "RUNTIME_CONTEXT_STATUS": "authenticated",
            "STORAGE_MUTATIONS_ALLOWED": "true",
            "PROVIDER_CALLS_ALLOWED": "true",
            "MUTATIONS_AUTHORIZED": "true",
        }
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    _install_gh(module, monkeypatch, job="extract")
    with pytest.raises(SystemExit, match="1"):
        module.main(
            [
                "authorize",
                "--output",
                "artifacts/extraction/free-execution-authorization.json",
            ]
        )


def test_authorize_refuses_lane_id_outside_extract(
    tmp_path: Path, module, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _env(tmp_path, job="discovery_seed", lane_id="lane-1")
    env.update(
        {
            "OPERATION_AUTHORITY_STATUS": "validated",
            "COLLECTOR_STATUS": "admitted",
            "COLLECTOR_AUTHENTICATED": "true",
            "RUNTIME_CONTEXT_STATUS": "authenticated",
            "STORAGE_MUTATIONS_ALLOWED": "true",
            "PROVIDER_CALLS_ALLOWED": "true",
            "MUTATIONS_AUTHORIZED": "true",
        }
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    _install_gh(module, monkeypatch, job="discovery_seed")
    with pytest.raises(SystemExit, match="1"):
        module.main(
            [
                "authorize",
                "--output",
                "artifacts/discovery/free-execution-authorization.json",
            ]
        )


def test_verify_rejects_mutated_payload(
    tmp_path: Path, module, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _env(tmp_path, job="extract", lane_id="lane-1")
    env.update(
        {
            "OPERATION_AUTHORITY_STATUS": "validated",
            "COLLECTOR_STATUS": "admitted",
            "COLLECTOR_AUTHENTICATED": "true",
            "RUNTIME_CONTEXT_STATUS": "authenticated",
            "STORAGE_MUTATIONS_ALLOWED": "true",
            "PROVIDER_CALLS_ALLOWED": "true",
            "MUTATIONS_AUTHORIZED": "true",
        }
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    _install_gh(module, monkeypatch, job="extract")
    path = Path("artifacts/extraction/free-execution-authorization.json")
    assert module.main(["authorize", "--output", str(path)]) == 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["runner_name"] = "other-runner"
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="1"):
        module.main(["verify", "--input", str(path)])


def test_verify_rejects_symlink(tmp_path: Path, module, monkeypatch: pytest.MonkeyPatch) -> None:
    env = _env(tmp_path, job="merge")
    env.update(
        {
            "OPERATION_AUTHORITY_STATUS": "validated",
            "COLLECTOR_STATUS": "admitted",
            "COLLECTOR_AUTHENTICATED": "true",
            "RUNTIME_CONTEXT_STATUS": "authenticated",
            "STORAGE_MUTATIONS_ALLOWED": "true",
            "PROVIDER_CALLS_ALLOWED": "true",
            "MUTATIONS_AUTHORIZED": "true",
        }
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    target = tmp_path / "other.json"
    target.write_text("{}", encoding="utf-8")
    path = Path("artifacts/live-snapshot/free-execution-authorization.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)
    with pytest.raises(SystemExit, match="1"):
        module.main(["verify", "--input", str(path)])
