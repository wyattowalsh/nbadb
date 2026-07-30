from __future__ import annotations

import base64
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from nbadb.kaggle.publication_ledger import (
    _DEPLOYMENT_HEAD_QUERY,
    GITHUB_API_VERSION,
    PUBLICATION_DEPLOYMENT_TASK,
    GitHubDeploymentPublicationLedger,
    GitHubResponse,
    PublicationAttempt,
    PublicationIntent,
    PublicationLedgerError,
    PublicationLedgerPendingError,
)

_SOURCE_SHA = "a" * 40
_REPOSITORY_API = "https://api.github.com/repos/wyattowalsh/nbadb"
_DATASET = "wyattowalsh/basketball"


def _attempt(
    *,
    run_id: int = 123,
    run_attempt: int = 1,
    require_default_branch_head: bool = False,
    expected_default_branch_sha: str | None = None,
) -> PublicationAttempt:
    return PublicationAttempt(
        repository="wyattowalsh/nbadb",
        run_id=run_id,
        run_attempt=run_attempt,
        workflow="Daily Update",
        workflow_ref=("wyattowalsh/nbadb/.github/workflows/daily-update.yml@refs/heads/main"),
        job="daily",
        workflow_sha="b" * 40,
        source_sha=_SOURCE_SHA,
        actor="wyattowalsh",
        server_url="https://github.com",
        api_url="https://api.github.com",
        require_default_branch_head=require_default_branch_head,
        expected_default_branch_sha=expected_default_branch_sha,
    )


def _intent(**updates: object) -> PublicationIntent:
    values: dict[str, object] = {
        "dataset": _DATASET,
        "source_sha": _SOURCE_SHA,
        "publish_key": "1" * 20,
        "bundle_fingerprint": "2" * 64,
        "data_tree_fingerprint": "a" * 64,
        "staged_tree_fingerprint": "3" * 64,
        "publication_marker_sha256": "4" * 64,
        "metadata_sha256": "5" * 64,
        "resource_count": 2,
        "resource_bytes": 42,
        "verify_remote": True,
        "full_publication": False,
    }
    values.update(updates)
    return PublicationIntent(**values)  # type: ignore[arg-type]


class FakeGitHubTransport:
    def __init__(self) -> None:
        self.deployments: dict[int, dict[str, Any]] = {}
        self.statuses: dict[int, dict[int, dict[str, Any]]] = {}
        self.runs: dict[tuple[int, int], dict[str, Any]] = {}
        self.jobs: dict[tuple[int, int], list[dict[str, Any]]] = {}
        self.next_deployment_id = 1
        self.next_status_id = 1
        self.next_job_id = 1_000
        self.calls: list[tuple[str, str, dict[str, Any] | None, dict[str, str]]] = []
        self.raise_deployment: str | None = None
        self.raise_status_state: str | None = None
        self.ascending_status_inventory = False
        self.default_branch_sha = _SOURCE_SHA
        self.default_branch_sha_sequence: list[str] = []
        self._clock = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
        self.workflow_content = """\
name: Daily Update

on:
  workflow_dispatch:

jobs:
  daily:
    runs-on: ubuntu-latest
    concurrency:
      group: nbadb-kaggle-publish
      queue: max
      cancel-in-progress: false
    steps:
      - run: uv run nbadb upload
"""
        self.add_run(_attempt())

    def add_run(
        self,
        attempt: PublicationAttempt,
        *,
        run_name: str | None = None,
        status: str = "in_progress",
        conclusion: str | None = None,
    ) -> None:
        resolved_run_name = run_name or attempt.workflow
        self.runs[(attempt.run_id, attempt.run_attempt)] = {
            "id": attempt.run_id,
            "run_attempt": attempt.run_attempt,
            "workflow_id": 77,
            "name": resolved_run_name,
            "path": attempt.workflow_path,
            "head_sha": attempt.workflow_sha,
            "actor": {"login": attempt.actor, "id": 1},
            "repository": {"full_name": attempt.repository},
            "head_repository": {"full_name": attempt.repository},
            "event": "schedule",
            "status": status,
            "conclusion": conclusion,
        }
        job_id = self.next_job_id
        self.next_job_id += 1
        job_status = "completed" if status == "completed" else "in_progress"
        job_url = f"{_REPOSITORY_API}/actions/jobs/{job_id}"
        self.jobs[(attempt.run_id, attempt.run_attempt)] = [
            {
                "id": job_id,
                "run_id": attempt.run_id,
                "run_attempt": attempt.run_attempt,
                "run_url": f"{_REPOSITORY_API}/actions/runs/{attempt.run_id}",
                "head_sha": attempt.workflow_sha,
                "workflow_name": resolved_run_name,
                "name": attempt.job,
                "status": job_status,
                "conclusion": conclusion if job_status == "completed" else None,
                "url": job_url,
            }
        ]

    def _timestamp(self) -> str:
        value = self._clock.strftime("%Y-%m-%dT%H:%M:%SZ")
        self._clock += timedelta(seconds=1)
        return value

    @staticmethod
    def _creator() -> dict[str, Any]:
        return {"login": "github-actions[bot]", "id": 41898282}

    def _deployment(self, deployment_id: int, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{_REPOSITORY_API}/deployments/{deployment_id}"
        return {
            "id": deployment_id,
            "url": url,
            "statuses_url": f"{url}/statuses",
            "repository_url": _REPOSITORY_API,
            "sha": body["ref"],
            "ref": body["ref"],
            "task": body["task"],
            "payload": body["payload"],
            "environment": body["environment"],
            "description": body["description"],
            "creator": self._creator(),
            "transient_environment": body["transient_environment"],
            "production_environment": body["production_environment"],
            "created_at": self._timestamp(),
        }

    def _status(
        self,
        deployment_id: int,
        status_id: int,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        deployment_url = f"{_REPOSITORY_API}/deployments/{deployment_id}"
        return {
            "id": status_id,
            "url": f"{deployment_url}/statuses/{status_id}",
            "deployment_url": deployment_url,
            "repository_url": _REPOSITORY_API,
            "state": body["state"],
            "description": body["description"],
            "environment": body["environment"],
            "log_url": body["log_url"],
            "creator": self._creator(),
            "created_at": self._timestamp(),
        }

    @staticmethod
    def _page(items: list[Any], query: dict[str, list[str]]) -> list[Any]:
        per_page = int(query.get("per_page", ["30"])[0])
        page = int(query.get("page", ["1"])[0])
        start = (page - 1) * per_page
        return items[start : start + per_page]

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None = None,
        timeout_seconds: float,
    ) -> GitHubResponse:
        assert timeout_seconds == 30.0
        assert headers["X-GitHub-Api-Version"] == GITHUB_API_VERSION
        assert headers["Authorization"] == "Bearer token"
        self.calls.append((method, url, json_body, headers))
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        path = parsed.path
        deployments_path = "/repos/wyattowalsh/nbadb/deployments"
        repository_path = "/repos/wyattowalsh/nbadb"

        if method == "GET" and path == repository_path:
            return GitHubResponse(
                200,
                {
                    "full_name": "wyattowalsh/nbadb",
                    "default_branch": "main",
                },
            )

        if method == "GET" and path == f"{repository_path}/git/ref/heads/main":
            branch_sha = (
                self.default_branch_sha_sequence.pop(0)
                if self.default_branch_sha_sequence
                else self.default_branch_sha
            )
            return GitHubResponse(
                200,
                {
                    "ref": "refs/heads/main",
                    "url": f"{_REPOSITORY_API}/git/refs/heads/main",
                    "object": {
                        "type": "commit",
                        "sha": branch_sha,
                    },
                },
            )

        jobs_match = re.fullmatch(
            rf"{repository_path}/actions/runs/([1-9][0-9]*)"
            r"/attempts/([1-9][0-9]*)/jobs",
            path,
        )
        if method == "GET" and jobs_match is not None:
            key = (int(jobs_match.group(1)), int(jobs_match.group(2)))
            jobs = self.jobs.get(key, [])
            return GitHubResponse(
                200,
                {
                    "total_count": len(jobs),
                    "jobs": self._page(jobs, query),
                },
            )

        direct_job_match = re.fullmatch(
            rf"{repository_path}/actions/jobs/([1-9][0-9]*)",
            path,
        )
        if method == "GET" and direct_job_match is not None:
            job_id = int(direct_job_match.group(1))
            job = next(
                (
                    candidate
                    for jobs in self.jobs.values()
                    for candidate in jobs
                    if candidate["id"] == job_id
                ),
                None,
            )
            return GitHubResponse(200 if job is not None else 404, job or {})

        run_match = re.fullmatch(
            rf"{repository_path}/actions/runs/([1-9][0-9]*)/attempts/([1-9][0-9]*)",
            path,
        )
        if method == "GET" and run_match is not None:
            key = (int(run_match.group(1)), int(run_match.group(2)))
            run = self.runs.get(key)
            return GitHubResponse(200 if run is not None else 404, run or {})

        workflow_match = re.fullmatch(
            rf"{repository_path}/actions/workflows/([1-9][0-9]*)",
            path,
        )
        if method == "GET" and workflow_match is not None:
            workflow_id = int(workflow_match.group(1))
            return GitHubResponse(
                200,
                {
                    "id": workflow_id,
                    "name": "Daily Update",
                    "path": ".github/workflows/daily-update.yml",
                    "state": "active",
                    "url": f"{_REPOSITORY_API}/actions/workflows/{workflow_id}",
                },
            )

        contents_prefix = f"{repository_path}/contents/"
        if method == "GET" and path.startswith(contents_prefix):
            workflow_path = unquote(path.removeprefix(contents_prefix))
            encoded = self.workflow_content.encode()
            assert query == {"ref": ["b" * 40]}
            return GitHubResponse(
                200,
                {
                    "type": "file",
                    "path": workflow_path,
                    "name": workflow_path.rsplit("/", 1)[-1],
                    "encoding": "base64",
                    "content": base64.b64encode(encoded).decode(),
                    "size": len(encoded),
                    "sha": "c" * 40,
                },
            )

        if method == "POST" and path == deployments_path:
            if self.raise_deployment == "before":
                raise TimeoutError("before deployment accept")
            assert json_body is not None
            deployment_id = self.next_deployment_id
            self.next_deployment_id += 1
            deployment = self._deployment(deployment_id, json_body)
            self.deployments[deployment_id] = deployment
            self.statuses[deployment_id] = {}
            if self.raise_deployment == "after":
                raise TimeoutError("after deployment accept")
            return GitHubResponse(201, deployment)

        if method == "POST" and path == "/graphql":
            assert json_body is not None
            assert json_body == {
                "query": _DEPLOYMENT_HEAD_QUERY,
                "variables": {
                    "owner": "wyattowalsh",
                    "repository": "nbadb",
                    "environment": GitHubDeploymentPublicationLedger.environment_for_dataset(
                        _DATASET
                    ),
                },
            }
            environment = str(json_body["variables"]["environment"])
            records = [
                record
                for record in self.deployments.values()
                if record["environment"] == environment
            ]
            records.sort(key=lambda record: str(record["created_at"]), reverse=True)
            return GitHubResponse(
                200,
                {
                    "data": {
                        "repository": {
                            "deployments": {
                                "nodes": [
                                    {
                                        "databaseId": record["id"],
                                        "createdAt": record["created_at"],
                                    }
                                    for record in records[:2]
                                ]
                            }
                        }
                    }
                },
            )

        if method == "GET" and path == deployments_path:
            records = list(self.deployments.values())
            task = query.get("task", [None])[0]
            environment = query.get("environment", [None])[0]
            if task is not None:
                records = [record for record in records if record["task"] == task]
            if environment is not None:
                records = [record for record in records if record["environment"] == environment]
            records.sort(key=lambda record: str(record["created_at"]), reverse=True)
            return GitHubResponse(200, self._page(records, query))

        relative = path.removeprefix(f"{deployments_path}/")
        parts = relative.split("/")
        if parts and parts[0].isdigit():
            deployment_id = int(parts[0])
            if method == "GET" and len(parts) == 1:
                return GitHubResponse(200, self.deployments[deployment_id])
            if len(parts) >= 2 and parts[1] == "statuses":
                if method == "POST" and len(parts) == 2:
                    assert json_body is not None
                    state = str(json_body["state"])
                    mode = self.raise_status_state
                    if mode == f"{state}:before":
                        raise TimeoutError(f"before {state} accept")
                    status_id = self.next_status_id
                    self.next_status_id += 1
                    status = self._status(
                        deployment_id,
                        status_id,
                        json_body,
                    )
                    self.statuses[deployment_id][status_id] = status
                    if mode == f"{state}:after":
                        raise TimeoutError(f"after {state} accept")
                    return GitHubResponse(201, status)
                if method == "GET" and len(parts) == 2:
                    records = list(self.statuses[deployment_id].values())
                    records.sort(
                        key=lambda record: str(record["created_at"]),
                        reverse=not self.ascending_status_inventory,
                    )
                    return GitHubResponse(200, self._page(records, query))
                if method == "GET" and len(parts) == 3 and parts[2].isdigit():
                    return GitHubResponse(
                        200,
                        self.statuses[deployment_id][int(parts[2])],
                    )
        raise AssertionError(f"Unexpected request: {method} {url}")


def _ledger(
    transport: FakeGitHubTransport,
    *,
    attempt: PublicationAttempt | None = None,
) -> GitHubDeploymentPublicationLedger:
    return GitHubDeploymentPublicationLedger(
        token="token",
        attempt=attempt or _attempt(),
        transport=transport,
        sleep=lambda _seconds: None,
        nonce_factory=lambda: "6" * 32,
        snapshot_delay_seconds=0,
        recovery_delay_seconds=0,
        recovery_attempts=1,
    )


def _post_count(transport: FakeGitHubTransport, suffix: str) -> int:
    return sum(
        method == "POST" and urlsplit(url).path.endswith(suffix)
        for method, url, _body, _headers in transport.calls
    )


def _resolve(
    ledger: GitHubDeploymentPublicationLedger,
    intent: PublicationIntent,
    *,
    version: int,
) -> None:
    execution = ledger.claim_pending(ledger.prepare(intent))
    ledger.mark_resolved(
        execution,
        resolved_version=version,
        publication_marker_sha256=intent.publication_marker_sha256,
        readback_fingerprint=intent.staged_tree_fingerprint,
    )


def test_intent_id_is_canonical_and_excludes_attempt_provenance() -> None:
    intent = _intent()
    transport = FakeGitHubTransport()
    first = _ledger(transport, attempt=_attempt(run_attempt=1))
    second = _ledger(transport, attempt=_attempt(run_attempt=2))

    assert intent.intent_id == _intent().intent_id
    assert first.source_sha == second.source_sha == _SOURCE_SHA
    assert intent.intent_id != _intent(resource_bytes=43).intent_id


def test_actions_env_requires_explicit_trusted_publication_source() -> None:
    env = {
        "GH_TOKEN": "token",
        "GITHUB_REPOSITORY": "wyattowalsh/nbadb",
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKFLOW": "Daily Update",
        "GITHUB_WORKFLOW_REF": (
            "wyattowalsh/nbadb/.github/workflows/daily-update.yml@refs/heads/main"
        ),
        "GITHUB_JOB": "daily",
        "GITHUB_SHA": "b" * 40,
        "GITHUB_ACTOR": "wyattowalsh",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_API_URL": "https://api.github.com",
    }

    with pytest.raises(
        PublicationLedgerError,
        match="NBADB_KAGGLE_PUBLICATION_SOURCE_SHA",
    ):
        GitHubDeploymentPublicationLedger.from_actions_env(env)

    env["NBADB_KAGGLE_PUBLICATION_SOURCE_SHA"] = "not-a-sha"
    with pytest.raises(PublicationLedgerError, match="source_sha"):
        GitHubDeploymentPublicationLedger.from_actions_env(env)

    env["NBADB_KAGGLE_PUBLICATION_SOURCE_SHA"] = _SOURCE_SHA
    env["NBADB_KAGGLE_REQUIRE_DEFAULT_HEAD"] = "true"
    attempt = PublicationAttempt.from_actions_env(env)
    assert attempt.expected_default_branch_sha == _SOURCE_SHA

    env["NBADB_KAGGLE_EXPECTED_DEFAULT_HEAD_SHA"] = "f" * 40
    attempt = PublicationAttempt.from_actions_env(env)
    assert attempt.expected_default_branch_sha == "f" * 40
    assert PublicationAttempt.from_payload(attempt.payload()) == attempt


def test_expected_default_head_requires_enforcement() -> None:
    with pytest.raises(ValueError, match="requires default-branch enforcement"):
        _attempt(expected_default_branch_sha="f" * 40)


def test_prepare_creates_direct_gets_and_stably_verifies_pending() -> None:
    transport = FakeGitHubTransport()
    ledger = _ledger(transport)

    receipt = ledger.prepare(_intent())

    assert receipt.state == "pending"
    assert receipt.created_by_current is True
    assert receipt.intent_id == _intent().intent_id
    assert _post_count(transport, "/deployments") == 1
    assert any(
        method == "GET" and urlsplit(url).path.endswith("/deployments/1")
        for method, url, _body, _headers in transport.calls
    )


def test_prepare_accepts_dynamic_run_name_separate_from_workflow_name() -> None:
    transport = FakeGitHubTransport()
    transport.add_run(
        _attempt(),
        run_name="Daily Update source=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )

    receipt = _ledger(transport).prepare(_intent())

    assert receipt.attempt.workflow == "Daily Update"


def test_prepare_accepts_pending_parent_only_with_active_exact_job() -> None:
    transport = FakeGitHubTransport()
    transport.runs[(123, 1)]["status"] = "pending"

    ledger = _ledger(transport)
    receipt = ledger.prepare(_intent())
    execution = ledger.claim_pending(receipt)

    assert execution.job == "daily"


def test_prepare_rejects_inactive_exact_job_before_deployment_write() -> None:
    transport = FakeGitHubTransport()
    transport.jobs[(123, 1)][0]["status"] = "pending"
    ledger = _ledger(transport)

    with pytest.raises(PublicationLedgerPendingError, match="executor job"):
        ledger.prepare(_intent())

    assert _post_count(transport, "/deployments") == 0


def test_shared_ledger_accepts_historical_status_from_another_workflow() -> None:
    transport = FakeGitHubTransport()
    daily = _ledger(transport)
    _resolve(daily, _intent(), version=42)
    transport.runs[(123, 1)]["status"] = "pending"
    transport.jobs[(123, 1)][0]["status"] = "completed"
    transport.jobs[(123, 1)][0]["conclusion"] = "success"
    monthly_attempt = replace(
        _attempt(),
        workflow="Monthly Update",
        workflow_ref=("wyattowalsh/nbadb/.github/workflows/monthly-update.yml@refs/heads/main"),
        job="monthly",
    )

    inventory = _ledger(transport, attempt=monthly_attempt).scan_dataset(_DATASET)

    assert inventory.current is not None
    assert inventory.current.latest_status is not None
    assert inventory.current.latest_status.executor.workflow == "Daily Update"


def test_prepare_recovers_accepted_ambiguous_create_without_post_retry() -> None:
    transport = FakeGitHubTransport()
    transport.raise_deployment = "after"
    ledger = _ledger(transport)

    receipt = ledger.prepare(_intent())

    assert receipt.state == "pending"
    assert receipt.deployment_id == 1
    assert _post_count(transport, "/deployments") == 1


def test_prepare_fails_closed_when_ambiguous_create_is_absent() -> None:
    transport = FakeGitHubTransport()
    transport.raise_deployment = "before"
    ledger = _ledger(transport)

    with pytest.raises(PublicationLedgerPendingError, match="outcome is unresolved"):
        ledger.prepare(_intent())

    assert _post_count(transport, "/deployments") == 1


def test_claim_writes_and_directly_verifies_in_progress() -> None:
    transport = FakeGitHubTransport()
    ledger = _ledger(transport)
    pending = ledger.prepare(_intent())

    execution = ledger.claim_pending(pending)

    assert execution.deployment_id == pending.deployment_id
    assert execution.dataset == _DATASET
    assert execution.nonce == "6" * 32
    states = [
        body["state"]
        for method, url, body, _headers in transport.calls
        if method == "POST" and urlsplit(url).path.endswith("/statuses") and body
    ]
    assert states == ["in_progress"]
    inventory = ledger.scan_dataset(_DATASET)
    assert inventory.unresolved[0].state == "in_progress"
    assert inventory.unresolved[0].latest_status is not None
    assert inventory.unresolved[0].latest_status.status_id == execution.status_id


def test_claim_recovers_accepted_ambiguous_in_progress_without_post_retry() -> None:
    transport = FakeGitHubTransport()
    ledger = _ledger(transport)
    pending = ledger.prepare(_intent())
    transport.raise_status_state = "in_progress:after"

    execution = ledger.claim_pending(pending)

    assert execution.status_id == 1
    in_progress_posts = [
        body
        for method, url, body, _headers in transport.calls
        if method == "POST"
        and urlsplit(url).path.endswith("/statuses")
        and body
        and body["state"] == "in_progress"
    ]
    assert len(in_progress_posts) == 1


def test_claim_leaves_pending_when_in_progress_is_ambiguous_absent() -> None:
    transport = FakeGitHubTransport()
    ledger = _ledger(transport)
    pending = ledger.prepare(_intent())
    transport.raise_status_state = "in_progress:before"

    with pytest.raises(PublicationLedgerPendingError, match="outcome is unresolved"):
        ledger.claim_pending(pending)

    inventory = ledger.scan_dataset(_DATASET)
    assert inventory.unresolved[0].state == "pending"
    assert _post_count(transport, "/statuses") == 1


def test_preexisting_in_progress_is_reconciliation_only() -> None:
    transport = FakeGitHubTransport()
    ledger = _ledger(transport)
    pending = ledger.prepare(_intent())
    ledger.claim_pending(pending)
    mutation_count = _post_count(transport, "/deployments") + _post_count(
        transport,
        "/statuses",
    )

    with pytest.raises(PublicationLedgerPendingError, match="reconciliation-only"):
        ledger.prepare(_intent())

    assert (
        _post_count(transport, "/deployments") + _post_count(transport, "/statuses")
        == mutation_count
    )


def test_mark_resolved_requires_current_execution_and_direct_gets_success() -> None:
    transport = FakeGitHubTransport()
    ledger = _ledger(transport)
    execution = ledger.claim_pending(ledger.prepare(_intent()))

    resolution = ledger.mark_resolved(
        execution,
        resolved_version=42,
        publication_marker_sha256="4" * 64,
        readback_fingerprint="3" * 64,
    )

    assert resolution.resolved_version == 42
    assert resolution.publication_marker_sha256 == "4" * 64
    assert len(resolution.resolution_digest) == 64
    success_status = transport.statuses[1][2]
    resolution_token = (
        base64.urlsafe_b64encode(bytes.fromhex(resolution.resolution_digest)).decode().rstrip("=")
    )
    assert f"r={resolution_token}" in success_status["description"]
    assert len(success_status["description"]) <= 140
    assert ledger.scan_dataset(_DATASET).records[0].state == "success"


def test_remote_match_rejects_pending_but_reconciles_in_progress() -> None:
    transport = FakeGitHubTransport()
    ledger = _ledger(transport)
    pending = ledger.prepare(_intent())
    marker = {
        "dataset": _DATASET,
        "publish_key": "1" * 20,
        "bundle_fingerprint": "2" * 64,
        "data_tree_fingerprint": "a" * 64,
        "metadata_sha256": "5" * 64,
    }

    with pytest.raises(PublicationLedgerError, match="without a verified in-progress"):
        ledger.find_remote_match(marker, marker_sha256="4" * 64)

    ledger.claim_pending(pending)
    match = ledger.find_remote_match(marker, marker_sha256="4" * 64)
    assert match is not None
    resolution = ledger.mark_reconciled(
        match,
        resolved_version=42,
        publication_marker_sha256="4" * 64,
        readback_fingerprint="3" * 64,
    )
    assert resolution.resolved_version == 42


def test_resolution_rejects_readback_identity_outside_durable_intent() -> None:
    transport = FakeGitHubTransport()
    ledger = _ledger(transport)
    execution = ledger.claim_pending(ledger.prepare(_intent()))

    with pytest.raises(PublicationLedgerError, match="marker digest"):
        ledger.mark_resolved(
            execution,
            resolved_version=42,
            publication_marker_sha256="7" * 64,
            readback_fingerprint="3" * 64,
        )
    with pytest.raises(PublicationLedgerError, match="readback fingerprint"):
        ledger.mark_resolved(
            execution,
            resolved_version=42,
            publication_marker_sha256="4" * 64,
            readback_fingerprint="7" * 64,
        )

    assert ledger.scan_dataset(_DATASET).records[0].state == "in_progress"


def test_pending_takeover_binds_and_verifies_current_executor_attempt() -> None:
    transport = FakeGitHubTransport()
    first_attempt = _attempt(run_attempt=1)
    first = _ledger(transport, attempt=first_attempt)
    pending = first.prepare(_intent())
    transport.runs[(123, 1)]["status"] = "completed"
    transport.runs[(123, 1)]["conclusion"] = "failure"
    transport.jobs[(123, 1)][0]["status"] = "completed"
    transport.jobs[(123, 1)][0]["conclusion"] = "failure"
    takeover_attempt = _attempt(run_attempt=2)
    transport.add_run(takeover_attempt)
    takeover = _ledger(transport, attempt=takeover_attempt)

    execution = takeover.claim_pending(takeover.prepare(_intent()))

    assert pending.attempt.run_attempt == 1
    assert execution.run_attempt == 2
    assert execution.job == "daily"
    assert transport.statuses[1][1]["log_url"].endswith("/runs/123/attempts/2")
    assert takeover.scan_dataset(_DATASET).current.latest_status.executor.run_attempt == 2


def test_existing_success_requires_exact_resolution_digest() -> None:
    transport = FakeGitHubTransport()
    ledger = _ledger(transport)
    execution = ledger.claim_pending(ledger.prepare(_intent()))
    ledger.mark_resolved(
        execution,
        resolved_version=42,
        publication_marker_sha256="4" * 64,
        readback_fingerprint="3" * 64,
    )
    transport.statuses[1][2]["description"] = re.sub(
        r"r=[A-Za-z0-9_-]{43}",
        "r=" + base64.urlsafe_b64encode(bytes.fromhex("8" * 64)).decode().rstrip("="),
        transport.statuses[1][2]["description"],
    )

    with pytest.raises(PublicationLedgerError, match="receipt digest is invalid"):
        ledger.scan_dataset(_DATASET)


def test_dataset_wide_scan_rejects_multiple_unresolved_deployments() -> None:
    transport = FakeGitHubTransport()
    first = _ledger(transport)
    first.prepare(_intent())
    second_intent = _intent(
        publish_key="8" * 20,
        bundle_fingerprint="9" * 64,
    )
    body = {
        "ref": second_intent.source_sha,
        "task": PUBLICATION_DEPLOYMENT_TASK,
        "auto_merge": False,
        "required_contexts": [],
        "payload": first._deployment_payload(second_intent),
        "environment": first.environment_for_dataset(_DATASET),
        "description": f"nbadb pending intent={second_intent.intent_id}",
        "transient_environment": False,
        "production_environment": True,
    }
    transport.request(
        "POST",
        f"{_REPOSITORY_API}/deployments",
        headers={
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "Authorization": "Bearer token",
        },
        json_body=body,
        timeout_seconds=30.0,
    )

    with pytest.raises(PublicationLedgerError, match="multiple unresolved"):
        first.scan_dataset(_DATASET)


def test_prepare_rejects_source_sha_not_bound_to_trusted_attempt() -> None:
    ledger = _ledger(FakeGitHubTransport())

    with pytest.raises(PublicationLedgerError, match="trusted workflow source"):
        ledger.prepare(_intent(source_sha="f" * 40))


def test_attempt_variants_do_not_change_semantic_intent() -> None:
    assert replace(_attempt(), run_attempt=2).source_sha == _intent().source_sha


def test_scan_request_budget_is_constant_with_more_than_100_historical_versions() -> None:
    transport = FakeGitHubTransport()
    ledger = _ledger(transport)
    intents: list[PublicationIntent] = []
    for version in range(1, 104):
        intent = _intent(
            publish_key=f"{version:020x}",
            bundle_fingerprint=f"{version:064x}",
        )
        _resolve(ledger, intent, version=version)
        intents.append(intent)

    cold_scanner = _ledger(transport)
    transport.calls.clear()
    inventory = cold_scanner.scan_dataset(_DATASET)

    assert [record.intent_id for record in inventory.records] == [
        intents[-2].intent_id,
        intents[-1].intent_id,
    ]
    assert len(transport.calls) == 32
    directly_read_deployment_ids = {
        int(match.group(1))
        for method, url, _body, _headers in transport.calls
        if method == "GET"
        and (
            match := re.fullmatch(
                r"/repos/wyattowalsh/nbadb/deployments/([1-9][0-9]*)",
                urlsplit(url).path,
            )
        )
        is not None
    }
    assert directly_read_deployment_ids == {102, 103}
    list_queries = [
        parse_qs(urlsplit(url).query)
        for method, url, _body, _headers in transport.calls
        if method == "GET" and "per_page" in parse_qs(urlsplit(url).query)
    ]
    assert list_queries
    assert all(query["page"] == ["1"] for query in list_queries)
    assert {query["per_page"][0] for query in list_queries} == {"3", "100"}
    graph_queries = [
        body
        for method, url, body, _headers in transport.calls
        if method == "POST" and urlsplit(url).path == "/graphql"
    ]
    assert len(graph_queries) == 3
    assert all(
        body is not None and "orderBy: {field: CREATED_AT, direction: DESC}" in str(body["query"])
        for body in graph_queries
    )


def test_executor_job_inventory_is_fully_paginated_before_admission() -> None:
    transport = FakeGitHubTransport()
    jobs = transport.jobs[(123, 1)]
    for index in range(204):
        job_id = transport.next_job_id
        transport.next_job_id += 1
        jobs.append(
            {
                "id": job_id,
                "run_id": 123,
                "run_attempt": 1,
                "run_url": f"{_REPOSITORY_API}/actions/runs/123",
                "head_sha": "b" * 40,
                "workflow_name": "Daily Update",
                "name": f"extract-{index:03d}",
                "status": "completed",
                "conclusion": "success",
                "url": f"{_REPOSITORY_API}/actions/jobs/{job_id}",
            }
        )

    receipt = _ledger(transport).prepare(_intent())

    assert receipt.state == "pending"
    job_pages = [
        parse_qs(urlsplit(url).query)["page"][0]
        for method, url, _body, _headers in transport.calls
        if method == "GET" and urlsplit(url).path.endswith("/actions/runs/123/attempts/1/jobs")
    ]
    assert job_pages == ["1", "2", "3"]


def test_created_at_not_numeric_id_defines_deployment_and_status_order() -> None:
    transport = FakeGitHubTransport()
    ledger = _ledger(transport)
    transport.next_deployment_id = 100
    first_intent = _intent()
    pending = ledger.prepare(first_intent)
    transport.next_status_id = 100
    execution = ledger.claim_pending(pending)
    transport.next_status_id = 1
    ledger.mark_resolved(
        execution,
        resolved_version=41,
        publication_marker_sha256=first_intent.publication_marker_sha256,
        readback_fingerprint=first_intent.staged_tree_fingerprint,
    )
    transport.next_deployment_id = 1
    second_intent = _intent(
        publish_key="8" * 20,
        bundle_fingerprint="9" * 64,
    )

    second = ledger.prepare(second_intent)
    inventory = ledger.scan_dataset(_DATASET)

    assert second.deployment_id == 1
    assert inventory.current is not None
    assert inventory.current.deployment_id == 1
    assert inventory.records[0].deployment_id == 100
    assert [status.status_id for status in inventory.records[0].statuses] == [100, 1]


def test_status_inventory_transport_order_is_not_trusted() -> None:
    transport = FakeGitHubTransport()
    ledger = _ledger(transport)
    _resolve(ledger, _intent(), version=42)
    transport.ascending_status_inventory = True

    inventory = ledger.scan_dataset(_DATASET)

    assert inventory.current is not None
    assert [status.state for status in inventory.current.statuses] == [
        "in_progress",
        "success",
    ]


def test_status_inventory_rejects_equal_created_at_receipts() -> None:
    transport = FakeGitHubTransport()
    ledger = _ledger(transport)
    _resolve(ledger, _intent(), version=42)
    transport.statuses[1][2]["created_at"] = transport.statuses[1][1]["created_at"]

    with pytest.raises(PublicationLedgerError, match="status inventory chronology"):
        ledger.scan_dataset(_DATASET)


def test_scan_rejects_ambiguous_created_at_chronology() -> None:
    transport = FakeGitHubTransport()
    ledger = _ledger(transport)
    _resolve(ledger, _intent(), version=41)
    second_intent = _intent(
        publish_key="8" * 20,
        bundle_fingerprint="9" * 64,
    )
    ledger.prepare(second_intent)
    transport.deployments[2]["created_at"] = transport.deployments[1]["created_at"]

    with pytest.raises(PublicationLedgerError, match="chronology is invalid"):
        ledger.scan_dataset(_DATASET)


@pytest.mark.parametrize(
    "workflow_content",
    [
        """\
name: Daily Update
jobs:
  daily:
    runs-on: ubuntu-latest
    steps:
      - run: uv run nbadb upload
""",
        """\
name: Daily Update
jobs:
  daily:
    concurrency:
      group: a-different-group
      queue: max
      cancel-in-progress: false
    steps:
      - run: uv run nbadb upload
""",
    ],
)
def test_prepare_requires_exact_structural_publication_mutex(
    workflow_content: str,
) -> None:
    transport = FakeGitHubTransport()
    transport.workflow_content = workflow_content
    ledger = _ledger(transport)

    with pytest.raises(PublicationLedgerError, match="publisher mutex"):
        ledger.prepare(_intent())

    assert _post_count(transport, "/deployments") == 0


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"status": "completed", "conclusion": "success"}, "not currently active"),
        (
            {"head_repository": {"full_name": "someone/else"}},
            "run-attempt provenance is invalid",
        ),
    ],
)
def test_prepare_rejects_noncurrent_or_untrusted_executor_before_write(
    mutation: dict[str, Any],
    message: str,
) -> None:
    transport = FakeGitHubTransport()
    transport.runs[(123, 1)].update(mutation)
    ledger = _ledger(transport)

    with pytest.raises(PublicationLedgerError, match=message):
        ledger.prepare(_intent())

    assert _post_count(transport, "/deployments") == 0


def test_claim_rechecks_default_branch_after_prepare_before_status_write() -> None:
    transport = FakeGitHubTransport()
    ledger = _ledger(
        transport,
        attempt=_attempt(require_default_branch_head=True),
    )
    pending = ledger.prepare(_intent())
    transport.default_branch_sha = "f" * 40

    with pytest.raises(PublicationLedgerPendingError, match="default branch"):
        ledger.claim_pending(pending)

    assert _post_count(transport, "/statuses") == 0


def test_exact_approved_default_head_can_differ_from_frozen_publication_source() -> None:
    transport = FakeGitHubTransport()
    transport.default_branch_sha = "f" * 40
    attempt = _attempt(
        require_default_branch_head=True,
        expected_default_branch_sha="f" * 40,
    )
    ledger = _ledger(transport, attempt=attempt)

    pending = ledger.prepare(_intent())

    assert pending.attempt.source_sha == _SOURCE_SHA
    assert pending.attempt.expected_default_branch_sha == "f" * 40


def test_claim_rechecks_default_branch_after_claim_before_upload_admission() -> None:
    transport = FakeGitHubTransport()
    ledger = _ledger(
        transport,
        attempt=_attempt(require_default_branch_head=True),
    )
    pending = ledger.prepare(_intent())
    transport.default_branch_sha_sequence = [_SOURCE_SHA, "f" * 40]

    with pytest.raises(PublicationLedgerPendingError, match="default branch"):
        ledger.claim_pending(pending)

    assert _post_count(transport, "/statuses") == 1
    assert ledger.scan_dataset(_DATASET).current.state == "in_progress"


def test_scan_rejects_more_than_two_status_receipts() -> None:
    transport = FakeGitHubTransport()
    ledger = _ledger(transport)
    _resolve(ledger, _intent(), version=42)
    deployment = transport.deployments[1]
    transport.statuses[1][3] = transport._status(
        1,
        3,
        {
            "state": "success",
            "description": transport.statuses[1][2]["description"],
            "environment": deployment["environment"],
            "log_url": transport.statuses[1][2]["log_url"],
        },
    )

    with pytest.raises(PublicationLedgerError, match="more statuses"):
        ledger.scan_dataset(_DATASET)


def test_terminal_success_remains_verifiable_after_claim_status_retention() -> None:
    transport = FakeGitHubTransport()
    ledger = _ledger(transport)
    intent = _intent()
    _resolve(ledger, intent, version=42)
    del transport.statuses[1][1]

    inventory = ledger.scan_dataset(_DATASET)

    assert inventory.current is not None
    assert inventory.current.state == "success"
    assert len(inventory.current.statuses) == 1
    assert inventory.current.latest_status is not None
    assert inventory.current.latest_status.claim_digest
