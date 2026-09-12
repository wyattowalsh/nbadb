from __future__ import annotations

import copy
import io
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email.message import Message
from email.utils import format_datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

import nbadb.kaggle.baseline_lease as baseline_lease_module
from nbadb.kaggle.baseline_lease import (
    _LEASE_HEAD_QUERY,
    BASELINE_LEASE_DEPLOYMENT_TASK,
    GITHUB_API_VERSION,
    BaselineConcurrencyPolicy,
    BaselineGitHubResponse,
    BaselineLeaseError,
    BaselineLeaseHeldError,
    BaselineLeaseOwner,
    BaselineLeasePendingError,
    BaselineLeaseReceipt,
    BaselineLeaseStaleError,
    GitHubDeploymentBaselineLease,
    LeaseOperation,
    LeaseState,
    ScheduledLeaseAction,
    baseline_concurrency_group,
)

_REPOSITORY = "wyattowalsh/nbadb"
_LEASE_KEY = "wyattowalsh/basketball"
_REPOSITORY_API = "https://api.github.com/repos/wyattowalsh/nbadb"
_SOURCE_SHA = "a" * 40
_WORKFLOW_SHA256 = "b" * 64


def _owner(
    run_id: int = 101,
    *,
    repository: str = _REPOSITORY,
    source_sha: str = _SOURCE_SHA,
    workflow_sha256: str = _WORKFLOW_SHA256,
) -> BaselineLeaseOwner:
    return BaselineLeaseOwner(
        repository=repository,
        run_id=run_id,
        run_attempt=1,
        source_sha=source_sha,
        workflow_sha256=workflow_sha256,
    )


class FakeBaselineGitHub:
    def __init__(self) -> None:
        self.clock = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
        self.deployments: dict[int, dict[str, Any]] = {}
        self.statuses: dict[int, dict[int, dict[str, Any]]] = {}
        self.next_deployment_id = 1
        self.next_status_id = 1
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.raise_deployment: str | None = None
        self.raise_status_operation: tuple[str, str] | None = None
        self.deployment_http_500: str | None = None
        self.status_http_500_operation: tuple[str, str] | None = None
        self.deployment_http_4xx_before: int | None = None
        self.status_http_4xx_operation: tuple[str, int] | None = None
        self.total_count_override: int | None = None
        self.duplicate_date_case = False
        self.date_override: datetime | None = None
        self.mutate_direct_status = False
        self.mutate_direct_status_id = False
        self.mutate_next_direct_status_id = False
        self.mutate_direct_deployment_id = False
        self.mutate_next_direct_deployment_ttl = False
        self.http_500_next_direct_status = False
        self.http_500_next_direct_deployment = False
        self.next_direct_status_response: tuple[int, Any] | None = None
        self.next_direct_deployment_response: tuple[int, Any] | None = None
        self.before_graphql: Any = None
        self.before_status_post: Any = None
        self.after_direct_deployment: Any = None
        self.deployment_tie_order = "descending"
        self.graphql_inventory_calls = 0
        self.status_tie_order = "descending"
        self.status_inventory_calls = 0

    def advance(self, seconds: int) -> None:
        self.clock += timedelta(seconds=seconds)

    def _timestamp(self) -> str:
        return self.clock.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _headers(self) -> tuple[tuple[str, str], ...]:
        value = format_datetime(self.date_override or self.clock, usegmt=True)
        if self.duplicate_date_case:
            return (("Date", value), ("date", value))
        return (("Date", value),)

    def _response(self, status: int, payload: Any) -> BaselineGitHubResponse:
        return BaselineGitHubResponse(status, payload, self._headers())

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

    def _graphql(self, body: dict[str, Any]) -> BaselineGitHubResponse:
        if self.before_graphql is not None:
            hook = self.before_graphql
            self.before_graphql = None
            hook()
        assert body["query"] == _LEASE_HEAD_QUERY
        variables = body["variables"]
        assert variables["owner"] == "wyattowalsh"
        assert variables["repository"] == "nbadb"
        environment = variables["environment"]
        assert variables["pageSize"] == baseline_lease_module._DEPLOYMENT_PAGE_SIZE
        cursor = variables["cursor"]
        records = [
            record for record in self.deployments.values() if record["environment"] == environment
        ]
        self.graphql_inventory_calls += 1
        lower_first = self.deployment_tie_order == "ascending" or (
            self.deployment_tie_order == "alternating" and self.graphql_inventory_calls % 2 == 1
        )
        records.sort(key=lambda record: record["id"], reverse=not lower_first)
        records.sort(key=lambda record: record["created_at"], reverse=True)
        count = self.total_count_override if self.total_count_override is not None else len(records)
        if cursor is None:
            start = 0
        else:
            match = re.fullmatch(r"cursor:(\d+)", cursor)
            assert match is not None
            start = int(match.group(1))
        end = min(start + variables["pageSize"], len(records))
        page_records = records[start:end]
        return self._response(
            200,
            {
                "data": {
                    "repository": {
                        "deployments": {
                            "totalCount": count,
                            "pageInfo": {
                                "hasNextPage": end < len(records),
                                "endCursor": f"cursor:{end}" if page_records else None,
                            },
                            "nodes": [
                                {
                                    "databaseId": record["id"],
                                    "createdAt": record["created_at"],
                                }
                                for record in page_records
                            ],
                        }
                    }
                }
            },
        )

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None = None,
        timeout_seconds: float,
    ) -> BaselineGitHubResponse:
        assert headers["Authorization"] == "Bearer token"
        assert headers["X-GitHub-Api-Version"] == GITHUB_API_VERSION
        assert timeout_seconds == 30.0
        self.calls.append((method, url, json_body))
        parsed = urlsplit(url)
        path = parsed.path
        query = parse_qs(parsed.query)
        deployments_path = "/repos/wyattowalsh/nbadb/deployments"
        if method == "POST" and path == "/graphql":
            assert json_body is not None
            return self._graphql(json_body)
        if method == "POST" and path == deployments_path:
            if self.raise_deployment == "before":
                self.raise_deployment = None
                raise TimeoutError
            if self.deployment_http_500 == "before":
                self.deployment_http_500 = None
                return self._response(500, {"message": "ambiguous deployment"})
            if self.deployment_http_4xx_before is not None:
                status = self.deployment_http_4xx_before
                self.deployment_http_4xx_before = None
                return self._response(status, "<html>rejected</html>")
            assert json_body is not None
            assert json_body["task"] == BASELINE_LEASE_DEPLOYMENT_TASK
            assert json_body["auto_merge"] is False
            assert json_body["required_contexts"] == []
            deployment_id = self.next_deployment_id
            self.next_deployment_id += 1
            deployment = self._deployment(deployment_id, json_body)
            self.deployments[deployment_id] = deployment
            self.statuses[deployment_id] = {}
            if self.raise_deployment == "after":
                self.raise_deployment = None
                raise TimeoutError
            if self.deployment_http_500 == "after":
                self.deployment_http_500 = None
                return self._response(500, {"message": "ambiguous deployment"})
            return self._response(201, deployment)
        relative = path.removeprefix(f"{deployments_path}/")
        parts = relative.split("/")
        if parts and parts[0].isdigit():
            deployment_id = int(parts[0])
            if method == "GET" and len(parts) == 1:
                if self.next_direct_deployment_response is not None:
                    status, payload = self.next_direct_deployment_response
                    self.next_direct_deployment_response = None
                    return self._response(status, payload)
                if self.http_500_next_direct_deployment:
                    self.http_500_next_direct_deployment = False
                    return self._response(500, {"message": "ambiguous deployment read"})
                record = self.deployments.get(deployment_id)
                if record is not None:
                    record = copy.deepcopy(record)
                if record is not None and self.mutate_direct_deployment_id:
                    returned_id = deployment_id + 1000
                    returned_url = f"{_REPOSITORY_API}/deployments/{returned_id}"
                    record["id"] = returned_id
                    record["url"] = returned_url
                    record["statuses_url"] = f"{returned_url}/statuses"
                if record is not None and self.mutate_next_direct_deployment_ttl:
                    self.mutate_next_direct_deployment_ttl = False
                    record["payload"]["requested_ttl_seconds"] += 1
                response = self._response(200 if record is not None else 404, record or {})
                if record is not None and self.after_direct_deployment is not None:
                    hook = self.after_direct_deployment
                    self.after_direct_deployment = None
                    hook()
                return response
            if len(parts) >= 2 and parts[1] == "statuses":
                if method == "POST" and len(parts) == 2:
                    assert json_body is not None
                    assert json_body["auto_inactive"] is False
                    if self.before_status_post is not None:
                        hook = self.before_status_post
                        self.before_status_post = None
                        hook()
                    match = re.match(r"nbadb-bl1\.([ahctr])\.", json_body["description"])
                    assert match is not None
                    operation = match.group(1)
                    mode = self.raise_status_operation
                    http_500_mode = self.status_http_500_operation
                    http_4xx_mode = self.status_http_4xx_operation
                    if mode == (operation, "before"):
                        self.raise_status_operation = None
                        raise TimeoutError
                    if http_500_mode == (operation, "before"):
                        self.status_http_500_operation = None
                        return self._response(500, {"message": "ambiguous status"})
                    if http_4xx_mode is not None and http_4xx_mode[0] == operation:
                        self.status_http_4xx_operation = None
                        return self._response(http_4xx_mode[1], "<html>rejected</html>")
                    status_id = self.next_status_id
                    self.next_status_id += 1
                    status = self._status(deployment_id, status_id, json_body)
                    self.statuses[deployment_id][status_id] = status
                    if mode == (operation, "after"):
                        self.raise_status_operation = None
                        raise TimeoutError
                    if http_500_mode == (operation, "after"):
                        self.status_http_500_operation = None
                        return self._response(500, {"message": "ambiguous status"})
                    return self._response(201, status)
                if method == "GET" and len(parts) == 2:
                    per_page = int(query["per_page"][0])
                    page = int(query["page"][0])
                    records = list(self.statuses[deployment_id].values())
                    self.status_inventory_calls += 1
                    lower_first = self.status_tie_order == "ascending" or (
                        self.status_tie_order == "alternating"
                        and self.status_inventory_calls % 2 == 1
                    )
                    records.sort(key=lambda record: record["id"], reverse=not lower_first)
                    records.sort(key=lambda record: record["created_at"], reverse=True)
                    start = (page - 1) * per_page
                    return self._response(200, records[start : start + per_page])
                if method == "GET" and len(parts) == 3 and parts[2].isdigit():
                    if self.next_direct_status_response is not None:
                        status, payload = self.next_direct_status_response
                        self.next_direct_status_response = None
                        return self._response(status, payload)
                    if self.http_500_next_direct_status:
                        self.http_500_next_direct_status = False
                        return self._response(500, {"message": "ambiguous status read"})
                    record = dict(self.statuses[deployment_id][int(parts[2])])
                    if self.mutate_direct_status_id or self.mutate_next_direct_status_id:
                        self.mutate_next_direct_status_id = False
                        returned_id = int(parts[2]) + 1000
                        record["id"] = returned_id
                        record["url"] = (
                            f"{_REPOSITORY_API}/deployments/{deployment_id}/statuses/{returned_id}"
                        )
                    if self.mutate_direct_status:
                        record["log_url"] = "https://github.com/foreign/run"
                    return self._response(200, record)
        raise AssertionError(f"Unexpected request: {method} {url}")


def _ledger(
    transport: FakeBaselineGitHub,
    *,
    nonces: list[str] | None = None,
) -> GitHubDeploymentBaselineLease:
    nonce_values = iter(nonces or [f"{value:032x}" for value in range(1, 100)])
    return GitHubDeploymentBaselineLease(
        token="token",
        repository=_REPOSITORY,
        transport=transport,
        sleep=lambda _seconds: None,
        nonce_factory=lambda: next(nonce_values),
        snapshot_delay_seconds=0,
    )


def _status_post_count(transport: FakeBaselineGitHub) -> int:
    return sum(
        method == "POST" and urlsplit(url).path.endswith("/statuses")
        for method, url, _body in transport.calls
    )


def _deployment_post_count(transport: FakeBaselineGitHub) -> int:
    return sum(
        method == "POST" and urlsplit(url).path.endswith("/deployments")
        for method, url, _body in transport.calls
    )


@pytest.mark.parametrize("body", [b"", b"<html>unavailable</html>"])
def test_urllib_transport_preserves_non_json_http_error_status(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
) -> None:
    headers = Message()
    headers["Date"] = "Fri, 21 Aug 2026 16:00:00 GMT"

    def raise_http_error(*_args: Any, **_kwargs: Any) -> None:
        raise baseline_lease_module.urllib.error.HTTPError(
            "https://api.github.com/example",
            500,
            "server error",
            headers,
            io.BytesIO(body),
        )

    monkeypatch.setattr(
        baseline_lease_module.urllib.request,
        "urlopen",
        raise_http_error,
    )
    result = baseline_lease_module.UrllibBaselineGitHubTransport().request(
        "GET",
        "https://api.github.com/example",
        headers={},
        timeout_seconds=1,
    )

    assert result.status_code == 500
    assert result.payload is None
    assert result.headers == (("Date", "Fri, 21 Aug 2026 16:00:00 GMT"),)


def _base36(value: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    encoded = ""
    while value:
        value, remainder = divmod(value, 36)
        encoded = digits[remainder] + encoded
    return encoded or "0"


def _replace_status_ttl(
    transport: FakeBaselineGitHub,
    receipt: Any,
    ttl_token: str,
) -> None:
    status = transport.statuses[receipt.fence][receipt.revision]
    parts = status["description"].split(".")
    parts[4] = ttl_token
    status["description"] = ".".join(parts)


def _append_transition_mutation(
    transport: FakeBaselineGitHub,
    ledger: GitHubDeploymentBaselineLease,
    predecessor: BaselineLeaseReceipt,
    *,
    operation: LeaseOperation,
    owner: BaselineLeaseOwner,
    ttl_seconds: int,
    nonce: str,
) -> int:
    description = ledger._encode_transition(
        operation,
        owner,
        ttl_seconds=ttl_seconds,
        nonce=nonce,
        predecessor=predecessor,
    )
    body = {
        "state": "inactive" if operation is LeaseOperation.RELEASE else "in_progress",
        "description": description,
        "environment": predecessor.environment,
        "log_url": (
            f"https://github.com/{_REPOSITORY}/actions/runs/"
            f"{owner.run_id}/attempts/{owner.run_attempt}"
        ),
        "auto_inactive": False,
    }
    status_id = transport.next_status_id
    transport.next_status_id += 1
    transport.statuses[predecessor.fence][status_id] = transport._status(
        predecessor.fence,
        status_id,
        body,
    )
    return status_id


def _pending_lease(
    transport: FakeBaselineGitHub,
    ledger: GitHubDeploymentBaselineLease,
    *,
    ttl_seconds: int = 60,
    nonce: str = "9" * 32,
) -> BaselineLeaseReceipt:
    transport.raise_status_operation = ("a", "before")
    with pytest.raises(BaselineLeasePendingError):
        ledger.acquire(_LEASE_KEY, _owner(), ttl_seconds=ttl_seconds, nonce=nonce)
    pending = ledger.inspect(_LEASE_KEY).current
    assert pending is not None
    assert pending.state is LeaseState.PENDING
    return pending


def _age_deployment_past_status_retention(
    transport: FakeBaselineGitHub,
    fence: int,
) -> None:
    retained_since = transport.clock - timedelta(
        seconds=baseline_lease_module._STATUS_RETENTION_SECONDS
    )
    transport.deployments[fence]["created_at"] = retained_since.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_acquire_assigns_monotonic_deployment_fence_and_exact_owner() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    first_owner = _owner()

    first = ledger.acquire(_LEASE_KEY, first_owner, ttl_seconds=60)
    released = ledger.release(first)
    transport.advance(1)
    second_owner = _owner(202)
    second = ledger.acquire(_LEASE_KEY, second_owner, ttl_seconds=60)

    assert first.fence == 1
    assert released.fence == first.fence
    assert second.fence == 2
    assert second.fence > first.fence
    assert second.owner == second_owner
    assert second.state is LeaseState.ACTIVE
    assert second.operation is LeaseOperation.ACQUIRE
    assert ledger.assert_current(second).receipt_digest == second.receipt_digest


def test_acquire_recovers_ambiguous_crash_by_nonce() -> None:
    transport = FakeBaselineGitHub()
    transport.raise_deployment = "after"
    nonce = "1" * 32
    ledger = _ledger(transport)

    receipt = ledger.acquire(_LEASE_KEY, _owner(), ttl_seconds=60, nonce=nonce)

    assert receipt.transition_nonce == nonce
    assert receipt.operation is LeaseOperation.ACQUIRE
    assert len(transport.deployments) == 1

    transport_two = FakeBaselineGitHub()
    transport_two.raise_status_operation = ("a", "after")
    ledger_two = _ledger(transport_two)
    after_status = ledger_two.acquire(
        _LEASE_KEY,
        _owner(),
        ttl_seconds=60,
        nonce="2" * 32,
    )
    assert after_status.transition_nonce == "2" * 32
    assert len(transport_two.statuses[1]) == 1


def test_auto_generated_acquire_nonce_is_exposed_for_safe_pending_retry() -> None:
    transport = FakeBaselineGitHub()
    transport.deployment_http_500 = "before"
    generated_nonce = "a" * 32
    ledger = _ledger(transport, nonces=[generated_nonce])
    owner = _owner()

    with pytest.raises(BaselineLeasePendingError) as pending:
        ledger.acquire(_LEASE_KEY, owner, ttl_seconds=60)

    assert pending.value.nonce == generated_nonce
    assert _deployment_post_count(transport) == 1
    assert transport.deployments == {}
    receipt = ledger.acquire(
        _LEASE_KEY,
        owner,
        ttl_seconds=60,
        nonce=pending.value.nonce,
    )
    assert receipt.transition_nonce == generated_nonce
    assert _deployment_post_count(transport) == 2
    assert len(transport.deployments) == 1


def test_auto_generated_transition_nonce_is_exposed_for_zero_duplicate_reconcile() -> None:
    transport = FakeBaselineGitHub()
    generated_nonce = "b" * 32
    ledger = _ledger(transport, nonces=[generated_nonce])
    acquired = ledger.acquire(
        _LEASE_KEY,
        _owner(),
        ttl_seconds=60,
        nonce="1" * 32,
    )

    def fail_first_reconciliation_read() -> None:
        transport.next_direct_status_response = (500, "<html>unavailable</html>")

    transport.before_status_post = fail_first_reconciliation_read
    transport.status_http_500_operation = ("h", "after")
    before_posts = _status_post_count(transport)
    with pytest.raises(BaselineLeasePendingError) as pending:
        ledger.heartbeat(acquired, ttl_seconds=30)

    assert pending.value.nonce == generated_nonce
    assert _status_post_count(transport) == before_posts + 1
    reconciled = ledger.heartbeat(
        acquired,
        ttl_seconds=30,
        nonce=pending.value.nonce,
    )
    assert reconciled.transition_nonce == generated_nonce
    assert reconciled.operation is LeaseOperation.HEARTBEAT
    assert _status_post_count(transport) == before_posts + 1


def test_acquire_reconciles_persisted_http_500_mutations_by_exact_nonce() -> None:
    deployment_transport = FakeBaselineGitHub()
    deployment_transport.deployment_http_500 = "after"
    deployment_ledger = _ledger(deployment_transport)
    deployment_receipt = deployment_ledger.acquire(
        _LEASE_KEY,
        _owner(),
        ttl_seconds=60,
        nonce="3" * 32,
    )

    assert deployment_receipt.state is LeaseState.ACTIVE
    assert deployment_receipt.transition_nonce == "3" * 32
    assert len(deployment_transport.deployments) == 1

    status_transport = FakeBaselineGitHub()
    status_transport.status_http_500_operation = ("a", "after")
    status_ledger = _ledger(status_transport)
    status_receipt = status_ledger.acquire(
        _LEASE_KEY,
        _owner(),
        ttl_seconds=60,
        nonce="4" * 32,
    )

    assert status_receipt.state is LeaseState.ACTIVE
    assert status_receipt.transition_nonce == "4" * 32
    assert len(status_transport.deployments) == 1
    assert len(status_transport.statuses[1]) == 1


@pytest.mark.parametrize("direct_payload", [None, "<html>unavailable</html>"])
def test_acquire_deployment_post_500_then_reconciliation_500_is_pending(
    direct_payload: Any,
) -> None:
    transport = FakeBaselineGitHub()
    transport.deployment_http_500 = "after"
    transport.next_direct_deployment_response = (500, direct_payload)
    ledger = _ledger(transport)
    owner = _owner()
    nonce = "d" * 32

    with pytest.raises(BaselineLeasePendingError, match="exact nonce reconciliation"):
        ledger.acquire(
            _LEASE_KEY,
            owner,
            ttl_seconds=60,
            nonce=nonce,
        )

    assert _deployment_post_count(transport) == 1
    assert _status_post_count(transport) == 0
    assert len(transport.deployments) == 1
    reconciled = ledger.reconcile_acquire(
        _LEASE_KEY,
        owner,
        ttl_seconds=60,
        nonce=nonce,
    )
    assert reconciled.state is LeaseState.ACTIVE
    assert reconciled.transition_nonce == nonce
    assert _deployment_post_count(transport) == 1
    assert _status_post_count(transport) == 1


@pytest.mark.parametrize(
    ("direct_status", "direct_payload"),
    [
        (404, {}),
        (403, "<html>forbidden</html>"),
        (429, None),
        (500, "<html>unavailable</html>"),
    ],
)
def test_acquire_successful_post_then_direct_500_is_pending_without_duplicate(
    direct_status: int,
    direct_payload: Any,
) -> None:
    transport = FakeBaselineGitHub()
    transport.next_direct_deployment_response = (direct_status, direct_payload)
    ledger = _ledger(transport)
    owner = _owner()
    nonce = "e" * 32

    with pytest.raises(BaselineLeasePendingError, match="exact nonce reconciliation"):
        ledger.acquire(
            _LEASE_KEY,
            owner,
            ttl_seconds=60,
            nonce=nonce,
        )

    assert _deployment_post_count(transport) == 1
    assert _status_post_count(transport) == 0
    reconciled = ledger.reconcile_acquire(
        _LEASE_KEY,
        owner,
        ttl_seconds=60,
        nonce=nonce,
    )
    assert reconciled.state is LeaseState.ACTIVE
    assert reconciled.transition_nonce == nonce
    assert _deployment_post_count(transport) == 1


@pytest.mark.parametrize("direct_payload", [None, "<html>unavailable</html>"])
def test_acquire_status_post_500_then_reconciliation_500_is_pending(
    direct_payload: Any,
) -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    owner = _owner()
    nonce = "f" * 32

    def fail_first_reconciliation_read() -> None:
        transport.next_direct_status_response = (500, direct_payload)

    transport.before_status_post = fail_first_reconciliation_read
    transport.status_http_500_operation = ("a", "after")
    with pytest.raises(BaselineLeasePendingError, match="exact nonce reconciliation"):
        ledger.acquire(
            _LEASE_KEY,
            owner,
            ttl_seconds=60,
            nonce=nonce,
        )

    before_posts = _status_post_count(transport)
    assert before_posts == 1
    reconciled = ledger.reconcile_acquire(
        _LEASE_KEY,
        owner,
        ttl_seconds=60,
        nonce=nonce,
    )
    assert reconciled.state is LeaseState.ACTIVE
    assert reconciled.transition_nonce == nonce
    assert _deployment_post_count(transport) == 1
    assert _status_post_count(transport) == before_posts


@pytest.mark.parametrize(
    ("operation", "operation_code"),
    [
        (LeaseOperation.HEARTBEAT, "h"),
        (LeaseOperation.TRANSFER, "t"),
        (LeaseOperation.RECOVER, "c"),
        (LeaseOperation.RELEASE, "r"),
    ],
)
def test_non_acquire_persisted_http_500_and_exact_nonce_retry_reconcile(
    operation: LeaseOperation,
    operation_code: str,
) -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    ttl_seconds = 2 if operation is LeaseOperation.RECOVER else 60
    expected = ledger.acquire(
        _LEASE_KEY,
        _owner(101),
        ttl_seconds=ttl_seconds,
        nonce="5" * 32,
    )
    next_owner = _owner(202)
    transition_nonce = "6" * 32
    if operation is LeaseOperation.RECOVER:
        transport.advance(ttl_seconds)

    def invoke() -> BaselineLeaseReceipt:
        if operation is LeaseOperation.HEARTBEAT:
            return ledger.heartbeat(
                expected,
                ttl_seconds=30,
                nonce=transition_nonce,
            )
        if operation is LeaseOperation.TRANSFER:
            return ledger.transfer(
                expected,
                next_owner,
                ttl_seconds=30,
                nonce=transition_nonce,
            )
        if operation is LeaseOperation.RECOVER:
            return ledger.recover(
                expected,
                next_owner,
                ttl_seconds=30,
                nonce=transition_nonce,
            )
        return ledger.release(expected, nonce=transition_nonce)

    before_posts = _status_post_count(transport)
    transport.status_http_500_operation = (operation_code, "after")
    reconciled = invoke()

    assert reconciled.operation is operation
    assert reconciled.transition_nonce == transition_nonce
    assert reconciled.predecessor_revision == expected.revision
    assert _status_post_count(transport) == before_posts + 1
    assert ledger.inspect(_LEASE_KEY).current == reconciled

    retried = invoke()
    assert retried == reconciled
    assert _status_post_count(transport) == before_posts + 1


@pytest.mark.parametrize(
    ("operation", "operation_code"),
    [
        (LeaseOperation.HEARTBEAT, "h"),
        (LeaseOperation.TRANSFER, "t"),
        (LeaseOperation.RECOVER, "c"),
        (LeaseOperation.RELEASE, "r"),
    ],
)
def test_non_acquire_post_500_then_reconciliation_500_is_pending_and_retry_safe(
    operation: LeaseOperation,
    operation_code: str,
) -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    ttl_seconds = 2 if operation is LeaseOperation.RECOVER else 60
    expected = ledger.acquire(
        _LEASE_KEY,
        _owner(101),
        ttl_seconds=ttl_seconds,
        nonce="1" * 32,
    )
    next_owner = _owner(202)
    transition_nonce = "2" * 32
    if operation is LeaseOperation.RECOVER:
        transport.advance(ttl_seconds)

    def invoke() -> BaselineLeaseReceipt:
        if operation is LeaseOperation.HEARTBEAT:
            return ledger.heartbeat(
                expected,
                ttl_seconds=30,
                nonce=transition_nonce,
            )
        if operation is LeaseOperation.TRANSFER:
            return ledger.transfer(
                expected,
                next_owner,
                ttl_seconds=30,
                nonce=transition_nonce,
            )
        if operation is LeaseOperation.RECOVER:
            return ledger.recover(
                expected,
                next_owner,
                ttl_seconds=30,
                nonce=transition_nonce,
            )
        return ledger.release(expected, nonce=transition_nonce)

    def fail_first_reconciliation_read() -> None:
        transport.next_direct_status_response = (500, "<html>unavailable</html>")

    before_posts = _status_post_count(transport)
    transport.before_status_post = fail_first_reconciliation_read
    transport.status_http_500_operation = (operation_code, "after")
    with pytest.raises(BaselineLeasePendingError, match="exact nonce reconciliation"):
        invoke()

    assert _status_post_count(transport) == before_posts + 1
    reconciled = invoke()
    assert reconciled.operation is operation
    assert reconciled.transition_nonce == transition_nonce
    assert reconciled.predecessor_revision == expected.revision
    assert _status_post_count(transport) == before_posts + 1


def test_http_500_before_persistence_remains_pending_then_exact_retry_succeeds() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    expected = ledger.acquire(
        _LEASE_KEY,
        _owner(),
        ttl_seconds=60,
        nonce="7" * 32,
    )
    nonce = "8" * 32
    before_posts = _status_post_count(transport)
    transport.status_http_500_operation = ("h", "before")

    with pytest.raises(BaselineLeasePendingError, match="exact nonce reconciliation"):
        ledger.heartbeat(expected, ttl_seconds=30, nonce=nonce)

    assert ledger.inspect(_LEASE_KEY).current == expected
    assert _status_post_count(transport) == before_posts + 1
    retried = ledger.heartbeat(expected, ttl_seconds=30, nonce=nonce)
    assert retried.operation is LeaseOperation.HEARTBEAT
    assert retried.transition_nonce == nonce
    assert _status_post_count(transport) == before_posts + 2


@pytest.mark.parametrize("fault", ["status", "deployment"])
@pytest.mark.parametrize(
    ("direct_status", "direct_payload"),
    [
        (404, {}),
        (403, "<html>forbidden</html>"),
        (429, None),
        (500, "<html>unavailable</html>"),
    ],
)
def test_persisted_transition_direct_read_non_success_is_pending_then_reconciles(
    fault: str,
    direct_status: int,
    direct_payload: Any,
) -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    expected = ledger.acquire(
        _LEASE_KEY,
        _owner(),
        ttl_seconds=60,
        nonce="9" * 32,
    )

    def fail_one_direct_read() -> None:
        if fault == "status":
            transport.next_direct_status_response = (direct_status, direct_payload)
        else:
            transport.next_direct_deployment_response = (direct_status, direct_payload)

    transport.before_status_post = fail_one_direct_read
    before_posts = _status_post_count(transport)
    with pytest.raises(BaselineLeasePendingError, match="exact nonce reconciliation"):
        ledger.heartbeat(
            expected,
            ttl_seconds=30,
            nonce="a" * 32,
        )

    assert _status_post_count(transport) == before_posts + 1
    heartbeat = ledger.heartbeat(expected, ttl_seconds=30, nonce="a" * 32)
    assert heartbeat.operation is LeaseOperation.HEARTBEAT
    assert heartbeat.transition_nonce == "a" * 32
    assert _status_post_count(transport) == before_posts + 1
    assert ledger.inspect(_LEASE_KEY).current == heartbeat


def test_definitive_pre_persistence_mutation_4xx_remains_hard() -> None:
    deployment_transport = FakeBaselineGitHub()
    deployment_transport.deployment_http_4xx_before = 422
    deployment_ledger = _ledger(deployment_transport)

    with pytest.raises(BaselineLeaseError, match="creation failed with HTTP 422"):
        deployment_ledger.acquire(
            _LEASE_KEY,
            _owner(),
            ttl_seconds=60,
            nonce="b" * 32,
        )

    assert _deployment_post_count(deployment_transport) == 1
    assert deployment_transport.deployments == {}

    status_transport = FakeBaselineGitHub()
    status_ledger = _ledger(status_transport)
    expected = status_ledger.acquire(
        _LEASE_KEY,
        _owner(),
        ttl_seconds=60,
        nonce="c" * 32,
    )
    before_posts = _status_post_count(status_transport)
    status_transport.status_http_4xx_operation = ("h", 422)

    with pytest.raises(BaselineLeaseError, match="creation failed with HTTP 422"):
        status_ledger.heartbeat(expected, ttl_seconds=30, nonce="d" * 32)

    assert _status_post_count(status_transport) == before_posts + 1
    assert status_ledger.inspect(_LEASE_KEY).current == expected


def test_exact_nonce_retry_rejects_foreign_target_and_ttl_drift_without_post() -> None:
    foreign_transport = FakeBaselineGitHub()
    foreign_ledger = _ledger(foreign_transport)
    foreign_expected = foreign_ledger.acquire(
        _LEASE_KEY,
        _owner(101),
        ttl_seconds=60,
        nonce="9" * 32,
    )
    nonce = "a" * 32
    winner = foreign_ledger.transfer(
        foreign_expected,
        _owner(202),
        ttl_seconds=30,
        nonce=nonce,
    )
    before_foreign_posts = _status_post_count(foreign_transport)

    with pytest.raises(BaselineLeaseStaleError, match="no longer current"):
        foreign_ledger.transfer(
            foreign_expected,
            _owner(303),
            ttl_seconds=30,
            nonce=nonce,
        )

    assert _status_post_count(foreign_transport) == before_foreign_posts
    assert foreign_ledger.inspect(_LEASE_KEY).current == winner

    drift_transport = FakeBaselineGitHub()
    drift_ledger = _ledger(drift_transport)
    drift_expected = drift_ledger.acquire(
        _LEASE_KEY,
        _owner(),
        ttl_seconds=60,
        nonce="b" * 32,
    )
    _append_transition_mutation(
        drift_transport,
        drift_ledger,
        drift_expected,
        operation=LeaseOperation.HEARTBEAT,
        owner=drift_expected.owner,
        ttl_seconds=31,
        nonce=nonce,
    )
    drifted = drift_ledger.inspect(_LEASE_KEY).current
    before_drift_posts = _status_post_count(drift_transport)

    with pytest.raises(BaselineLeaseStaleError, match="no longer current"):
        drift_ledger.heartbeat(
            drift_expected,
            ttl_seconds=30,
            nonce=nonce,
        )

    assert _status_post_count(drift_transport) == before_drift_posts
    assert drift_ledger.inspect(_LEASE_KEY).current == drifted


def test_acquire_status_timeout_before_accept_is_reconciliation_only() -> None:
    transport = FakeBaselineGitHub()
    transport.raise_status_operation = ("a", "before")
    nonce = "3" * 32
    ledger = _ledger(transport)

    with pytest.raises(BaselineLeasePendingError, match="requires exact nonce reconciliation"):
        ledger.acquire(_LEASE_KEY, _owner(), ttl_seconds=60, nonce=nonce)

    pending = ledger.inspect(_LEASE_KEY).current
    assert pending is not None
    assert pending.state is LeaseState.PENDING
    assert pending.revision == 0
    assert pending.status_url is None
    assert transport.statuses[pending.fence] == {}


def test_reconcile_status_timeout_before_accept_never_returns_pending_receipt() -> None:
    transport = FakeBaselineGitHub()
    nonce = "4" * 32
    owner = _owner()
    ledger = _ledger(transport)
    transport.raise_status_operation = ("a", "before")
    with pytest.raises(BaselineLeasePendingError):
        ledger.acquire(_LEASE_KEY, owner, ttl_seconds=60, nonce=nonce)

    transport.raise_status_operation = ("a", "before")
    with pytest.raises(BaselineLeasePendingError, match="requires exact nonce reconciliation"):
        ledger.reconcile_acquire(
            _LEASE_KEY,
            owner,
            ttl_seconds=60,
            nonce=nonce,
        )

    current = ledger.inspect(_LEASE_KEY).current
    assert current is not None
    assert current.state is LeaseState.PENDING
    assert current.revision == 0
    assert current.status_url is None
    reconciled = ledger.reconcile_acquire(
        _LEASE_KEY,
        owner,
        ttl_seconds=60,
        nonce=nonce,
    )
    assert reconciled.state is LeaseState.ACTIVE
    assert reconciled.revision > 0
    assert reconciled.status_url == (f"{reconciled.deployment_url}/statuses/{reconciled.revision}")


def test_reconcile_active_acquisition_rejects_caller_ttl_mismatch() -> None:
    transport = FakeBaselineGitHub()
    nonce = "5" * 32
    owner = _owner()
    ledger = _ledger(transport)
    active = ledger.acquire(_LEASE_KEY, owner, ttl_seconds=60, nonce=nonce)
    before_posts = _status_post_count(transport)

    with pytest.raises(BaselineLeaseError, match="reconciliation TTL differs"):
        ledger.reconcile_acquire(
            _LEASE_KEY,
            owner,
            ttl_seconds=61,
            nonce=nonce,
        )

    assert _status_post_count(transport) == before_posts
    assert ledger.assert_current(active).receipt_digest == active.receipt_digest


def test_reconcile_pending_ttl_mismatch_performs_no_status_write() -> None:
    transport = FakeBaselineGitHub()
    nonce = "6" * 32
    owner = _owner()
    ledger = _ledger(transport)
    transport.raise_status_operation = ("a", "before")
    with pytest.raises(BaselineLeasePendingError):
        ledger.acquire(_LEASE_KEY, owner, ttl_seconds=60, nonce=nonce)
    before_posts = _status_post_count(transport)

    with pytest.raises(BaselineLeaseError, match="reconciliation TTL differs"):
        ledger.reconcile_acquire(
            _LEASE_KEY,
            owner,
            ttl_seconds=61,
            nonce=nonce,
        )

    assert _status_post_count(transport) == before_posts
    pending = ledger.inspect(_LEASE_KEY).current
    assert pending is not None
    assert pending.state is LeaseState.PENDING
    assert pending.revision == 0
    assert pending.status_url is None
    reconciled = ledger.reconcile_acquire(
        _LEASE_KEY,
        owner,
        ttl_seconds=60,
        nonce=nonce,
    )
    assert reconciled.state is LeaseState.ACTIVE


def test_expired_pending_root_can_recover_to_a_new_owner() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    pending = _pending_lease(transport, ledger, ttl_seconds=5)
    transport.advance(5)

    recovered = ledger.recover(
        pending,
        _owner(202),
        ttl_seconds=30,
        nonce="a" * 32,
    )

    assert recovered.state is LeaseState.ACTIVE
    assert recovered.operation is LeaseOperation.RECOVER
    assert recovered.predecessor_revision == 0
    assert ledger.assert_current(recovered).receipt_digest == recovered.receipt_digest


def test_first_persisted_status_rejects_heartbeat_from_revision_zero() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    pending = _pending_lease(transport, ledger)
    _append_transition_mutation(
        transport,
        ledger,
        pending,
        operation=LeaseOperation.HEARTBEAT,
        owner=pending.owner,
        ttl_seconds=60,
        nonce="a" * 32,
    )

    current = ledger.inspect(_LEASE_KEY).current
    assert current == pending


def test_first_persisted_status_rejects_transfer_from_revision_zero() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    pending = _pending_lease(transport, ledger)
    _append_transition_mutation(
        transport,
        ledger,
        pending,
        operation=LeaseOperation.TRANSFER,
        owner=_owner(202),
        ttl_seconds=60,
        nonce="b" * 32,
    )

    current = ledger.inspect(_LEASE_KEY).current
    assert current == pending


def test_first_persisted_status_rejects_release_from_revision_zero() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    pending = _pending_lease(transport, ledger)
    _append_transition_mutation(
        transport,
        ledger,
        pending,
        operation=LeaseOperation.RELEASE,
        owner=pending.owner,
        ttl_seconds=0,
        nonce="c" * 32,
    )

    current = ledger.inspect(_LEASE_KEY).current
    assert current == pending


def test_first_persisted_status_rejects_premature_recovery_from_revision_zero() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    pending = _pending_lease(transport, ledger)
    _append_transition_mutation(
        transport,
        ledger,
        pending,
        operation=LeaseOperation.RECOVER,
        owner=_owner(202),
        ttl_seconds=60,
        nonce="d" * 32,
    )

    current = ledger.inspect(_LEASE_KEY).current
    assert current == pending


def test_root_acquire_landing_at_exact_expiry_is_ignored_and_new_fence_succeeds() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)

    def reach_pending_expiry() -> None:
        transport.advance(2)

    transport.before_status_post = reach_pending_expiry
    with pytest.raises(BaselineLeaseStaleError, match="lost current authority"):
        ledger.acquire(
            _LEASE_KEY,
            _owner(101),
            ttl_seconds=2,
            nonce="a" * 32,
        )

    expired_pending = ledger.inspect(_LEASE_KEY).current
    assert expired_pending is not None
    assert expired_pending.state is LeaseState.PENDING
    assert expired_pending.is_expired_at(transport.clock)
    replacement = ledger.acquire(
        _LEASE_KEY,
        _owner(202),
        ttl_seconds=30,
        nonce="b" * 32,
    )
    assert replacement.fence > expired_pending.fence
    assert ledger.assert_current(replacement) == replacement


def test_heartbeat_landing_at_exact_expiry_is_ignored_and_recovery_succeeds() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    active = ledger.acquire(
        _LEASE_KEY,
        _owner(101),
        ttl_seconds=2,
        nonce="c" * 32,
    )

    def reach_active_expiry() -> None:
        transport.advance(2)

    transport.before_status_post = reach_active_expiry
    with pytest.raises(BaselineLeaseStaleError, match="lost current authority"):
        ledger.heartbeat(active, ttl_seconds=30, nonce="d" * 32)

    assert ledger.inspect(_LEASE_KEY).current == active
    recovered = ledger.recover(
        active,
        _owner(202),
        ttl_seconds=30,
        nonce="e" * 32,
    )
    assert recovered.operation is LeaseOperation.RECOVER
    assert ledger.assert_current(recovered) == recovered


def test_transfer_landing_at_exact_expiry_is_ignored_and_recovery_succeeds() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    active = ledger.acquire(
        _LEASE_KEY,
        _owner(101),
        ttl_seconds=2,
        nonce="1" * 32,
    )

    def reach_active_expiry() -> None:
        transport.advance(2)

    transport.before_status_post = reach_active_expiry
    with pytest.raises(BaselineLeaseStaleError, match="lost current authority"):
        ledger.transfer(
            active,
            _owner(202),
            ttl_seconds=30,
            nonce="2" * 32,
        )

    assert ledger.inspect(_LEASE_KEY).current == active
    recovered = ledger.recover(
        active,
        _owner(303),
        ttl_seconds=30,
        nonce="3" * 32,
    )
    assert recovered.operation is LeaseOperation.RECOVER
    assert ledger.assert_current(recovered) == recovered


def test_heartbeat_transfer_recover_release_preserve_fence() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    first = ledger.acquire(_LEASE_KEY, _owner(101), ttl_seconds=30)
    transport.advance(1)
    heartbeat = ledger.heartbeat(first, ttl_seconds=30)
    transport.advance(1)
    transferred = ledger.transfer(heartbeat, _owner(202), ttl_seconds=5)
    transport.advance(5)
    recovered = ledger.recover(transferred, _owner(303), ttl_seconds=30)
    transport.advance(1)
    released = ledger.release(recovered)

    assert {
        first.fence,
        heartbeat.fence,
        transferred.fence,
        recovered.fence,
        released.fence,
    } == {first.fence}
    assert [
        first.operation,
        heartbeat.operation,
        transferred.operation,
        recovered.operation,
        released.operation,
    ] == [
        LeaseOperation.ACQUIRE,
        LeaseOperation.HEARTBEAT,
        LeaseOperation.TRANSFER,
        LeaseOperation.RECOVER,
        LeaseOperation.RELEASE,
    ]
    assert released.state is LeaseState.RELEASED


def test_concurrency_configuration_is_case_normalized_queue_max_and_non_cancelling() -> None:
    lower = baseline_concurrency_group(_LEASE_KEY)
    mixed = baseline_concurrency_group("WyattOwalsh/BasketBall")

    assert lower == mixed
    assert lower == lower.casefold()
    policy = BaselineConcurrencyPolicy.validate(
        _LEASE_KEY,
        group=lower,
        queue="max",
        cancel_in_progress=False,
    )
    assert policy.fencing_authority is False
    assert policy.queue == "max"
    assert policy.cancel_in_progress is False

    with pytest.raises(BaselineLeaseError, match="normalized"):
        BaselineConcurrencyPolicy.validate(
            _LEASE_KEY,
            group=lower.upper(),
            queue="max",
            cancel_in_progress=False,
        )
    with pytest.raises(BaselineLeaseError, match="queue"):
        BaselineConcurrencyPolicy.validate(
            _LEASE_KEY,
            group=lower,
            queue="6",
            cancel_in_progress=False,
        )
    with pytest.raises(BaselineLeaseError, match="non-cancelling"):
        BaselineConcurrencyPolicy.validate(
            _LEASE_KEY,
            group=lower,
            queue="max",
            cancel_in_progress=True,
        )


def test_aba_status_revision_and_stale_owner_fail_closed() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    owner_a = _owner(101)
    owner_b = _owner(202)
    original_a = ledger.acquire(_LEASE_KEY, owner_a, ttl_seconds=30)
    transport.advance(1)
    owner_b_receipt = ledger.transfer(original_a, owner_b, ttl_seconds=5)
    transport.advance(5)
    restored_a = ledger.recover(owner_b_receipt, owner_a, ttl_seconds=30)

    assert restored_a.owner == original_a.owner
    assert restored_a.fence == original_a.fence
    assert restored_a.revision > original_a.revision
    assert restored_a.receipt_digest != original_a.receipt_digest
    before_posts = _status_post_count(transport)
    with pytest.raises(BaselineLeaseStaleError, match="no longer current"):
        ledger.heartbeat(original_a, ttl_seconds=30)
    with pytest.raises(BaselineLeaseStaleError, match="no longer current"):
        ledger.release(original_a)
    assert _status_post_count(transport) == before_posts


def test_concurrent_stale_transfer_cannot_replace_or_poison_winning_chain() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    original = ledger.acquire(
        _LEASE_KEY,
        _owner(101),
        ttl_seconds=2,
        nonce="1" * 32,
    )
    transport.advance(1)
    winner: BaselineLeaseReceipt | None = None

    def inject_winning_transfer() -> None:
        nonlocal winner
        winner = ledger.transfer(
            original,
            _owner(202),
            ttl_seconds=60,
            nonce="2" * 32,
        )
        transport.advance(1)

    transport.before_status_post = inject_winning_transfer
    with pytest.raises(BaselineLeaseStaleError, match="lost current authority"):
        ledger.transfer(
            original,
            _owner(303),
            ttl_seconds=60,
            nonce="3" * 32,
        )

    assert winner is not None
    current = ledger.inspect(_LEASE_KEY).current
    assert current is not None
    assert current.receipt_digest == winner.receipt_digest
    assert current.owner == _owner(202)
    assert len(transport.statuses[original.fence]) == 3

    renewed = ledger.heartbeat(winner, ttl_seconds=60, nonce="5" * 32)
    released = ledger.release(renewed, nonce="6" * 32)
    assert released.state is LeaseState.RELEASED
    assert ledger.inspect(_LEASE_KEY).current == released

    before_posts = _status_post_count(transport)
    with pytest.raises(BaselineLeaseStaleError, match="no longer current"):
        ledger.transfer(
            original,
            _owner(404),
            ttl_seconds=60,
            nonce="4" * 32,
        )
    assert _status_post_count(transport) == before_posts


def test_concurrent_claim_lower_fence_and_foreign_authority_fail_closed() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    current = ledger.acquire(_LEASE_KEY, _owner(101), ttl_seconds=60)

    with pytest.raises(BaselineLeaseHeldError, match="already held"):
        ledger.acquire(_LEASE_KEY, _owner(202), ttl_seconds=60)

    foreign_source = _owner(202, source_sha="c" * 40)
    foreign_workflow = _owner(202, workflow_sha256="d" * 64)
    before_posts = _status_post_count(transport)
    with pytest.raises(BaselineLeaseError, match="foreign"):
        ledger.transfer(current, foreign_source, ttl_seconds=60)
    with pytest.raises(BaselineLeaseError, match="foreign"):
        ledger.transfer(current, foreign_workflow, ttl_seconds=60)
    assert _status_post_count(transport) == before_posts

    ledger.release(current)
    transport.advance(1)
    transport.next_deployment_id = current.fence
    with pytest.raises(BaselineLeaseError, match="fence is not monotonic"):
        ledger.acquire(_LEASE_KEY, _owner(303), ttl_seconds=60)

    racing_transport = FakeBaselineGitHub()
    racing_ledger = _ledger(racing_transport)

    def inject_newer_pending_fence() -> None:
        prior = racing_transport.deployments[1]
        racing_transport.advance(1)
        body = {
            "ref": prior["ref"],
            "task": prior["task"],
            "payload": {
                **prior["payload"],
                "initial_owner": _owner(404).to_payload(),
                "acquire_nonce": "f" * 32,
            },
            "environment": prior["environment"],
            "description": prior["description"],
            "transient_environment": False,
            "production_environment": False,
        }
        newer = racing_transport._deployment(2, body)
        racing_transport.deployments[2] = newer
        racing_transport.statuses[2] = {}
        racing_transport.next_deployment_id = 3

    racing_transport.before_status_post = inject_newer_pending_fence
    with pytest.raises(BaselineLeaseStaleError, match="lost current authority"):
        racing_ledger.acquire(_LEASE_KEY, _owner(101), ttl_seconds=60)
    assert max(racing_transport.deployments) == 2


def test_case_collision_and_queue_overflow_fail_closed() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    receipt = ledger.acquire("WyattOwalsh/BasketBall", _owner(), ttl_seconds=60)

    assert receipt.lease_key == _LEASE_KEY
    assert ledger.inspect(_LEASE_KEY).current == receipt
    transport.total_count_override = 10_001
    with pytest.raises(BaselineLeaseError, match="inventory exceeds"):
        ledger.inspect(_LEASE_KEY)


def test_complete_deployment_inventory_selects_max_same_second_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(baseline_lease_module, "_DEPLOYMENT_PAGE_SIZE", 2)
    transport = FakeBaselineGitHub()
    transport.deployment_tie_order = "ascending"
    ledger = _ledger(transport)
    first = ledger.acquire(_LEASE_KEY, _owner(101), ttl_seconds=30)
    ledger.release(first)
    second = ledger.acquire(_LEASE_KEY, _owner(202), ttl_seconds=30)
    ledger.release(second)
    third = ledger.acquire(_LEASE_KEY, _owner(303), ttl_seconds=30)

    inspection = ledger.inspect(_LEASE_KEY)
    assert inspection.head_fence == 3
    assert inspection.current == third
    assert inspection.inventory_count == 3


def test_deployment_head_must_be_global_maximum_fence_across_full_inventory() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    first = ledger.acquire(
        _LEASE_KEY,
        _owner(101),
        ttl_seconds=30,
        nonce="1" * 32,
    )
    template = transport.deployments[first.fence]
    now = transport.clock
    template["created_at"] = (now - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    for deployment_id, owner, nonce, age_seconds in (
        (2, _owner(202), "2" * 32, 0),
        (100, _owner(303), "3" * 32, 2),
    ):
        transport.clock = now - timedelta(seconds=age_seconds)
        body = {
            "ref": owner.source_sha,
            "task": BASELINE_LEASE_DEPLOYMENT_TASK,
            "payload": ledger._deployment_payload(
                lease_key=_LEASE_KEY,
                owner=owner,
                ttl_seconds=30,
                nonce=nonce,
            ),
            "environment": template["environment"],
            "description": template["description"],
            "transient_environment": False,
            "production_environment": False,
        }
        transport.deployments[deployment_id] = transport._deployment(deployment_id, body)
        transport.statuses[deployment_id] = {}
    transport.clock = now
    transport.next_deployment_id = 101

    with pytest.raises(BaselineLeaseError, match="not the global maximum fence"):
        ledger.inspect(_LEASE_KEY)


def test_alternating_same_second_deployment_and_status_order_is_not_authority() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    first = ledger.acquire(_LEASE_KEY, _owner(101), ttl_seconds=30)
    ledger.release(first)
    second = ledger.acquire(_LEASE_KEY, _owner(202), ttl_seconds=30)
    ledger.release(second)
    third = ledger.acquire(_LEASE_KEY, _owner(303), ttl_seconds=30)
    heartbeat = ledger.heartbeat(third, ttl_seconds=30)

    transport.deployment_tie_order = "alternating"
    transport.status_tie_order = "alternating"
    inspection = ledger.inspect(_LEASE_KEY)
    assert inspection.head_fence == third.fence
    assert inspection.current == heartbeat


def test_acquire_reserves_capacity_at_exact_deployment_inventory_maximum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(baseline_lease_module, "_MAX_DEPLOYMENT_INVENTORY", 2)
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    first = ledger.acquire(_LEASE_KEY, _owner(101), ttl_seconds=30)
    ledger.release(first)
    transport.advance(1)
    second = ledger.acquire(_LEASE_KEY, _owner(202), ttl_seconds=30)
    released = ledger.release(second)
    before_posts = _deployment_post_count(transport)

    with pytest.raises(BaselineLeaseError, match="no reserved mutation capacity"):
        ledger.acquire(_LEASE_KEY, _owner(303), ttl_seconds=30)

    assert _deployment_post_count(transport) == before_posts
    assert ledger.inspect(_LEASE_KEY).current == released


def test_active_operations_reserve_capacity_at_exact_status_inventory_maximum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(baseline_lease_module, "_MAX_STATUS_INVENTORY", 2)
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    acquired = ledger.acquire(_LEASE_KEY, _owner(101), ttl_seconds=5)
    current = ledger.heartbeat(acquired, ttl_seconds=5)
    assert ledger.inspect(_LEASE_KEY).status_inventory_count == 2
    before_posts = _status_post_count(transport)

    with pytest.raises(BaselineLeaseError, match="no reserved mutation capacity"):
        ledger.heartbeat(current, ttl_seconds=5)
    with pytest.raises(BaselineLeaseError, match="no reserved mutation capacity"):
        ledger.transfer(current, _owner(202), ttl_seconds=5)
    with pytest.raises(BaselineLeaseError, match="no reserved mutation capacity"):
        ledger.release(current)
    transport.advance(5)
    with pytest.raises(BaselineLeaseError, match="no reserved mutation capacity"):
        ledger.recover(current, _owner(303), ttl_seconds=5)

    assert _status_post_count(transport) == before_posts
    assert ledger.inspect(_LEASE_KEY).current == current


def test_acquire_status_reserves_capacity_at_exact_status_inventory_maximum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(baseline_lease_module, "_MAX_STATUS_INVENTORY", 2)
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    nonce = "7" * 32
    pending = _pending_lease(transport, ledger, nonce=nonce)
    _append_transition_mutation(
        transport,
        ledger,
        pending,
        operation=LeaseOperation.HEARTBEAT,
        owner=pending.owner,
        ttl_seconds=60,
        nonce="8" * 32,
    )
    _append_transition_mutation(
        transport,
        ledger,
        pending,
        operation=LeaseOperation.RELEASE,
        owner=pending.owner,
        ttl_seconds=0,
        nonce="9" * 32,
    )
    inspection = ledger.inspect(_LEASE_KEY)
    assert inspection.current == pending
    assert inspection.status_inventory_count == 2
    before_posts = _status_post_count(transport)

    with pytest.raises(BaselineLeaseError, match="no reserved mutation capacity"):
        ledger.reconcile_acquire(
            _LEASE_KEY,
            pending.owner,
            ttl_seconds=60,
            nonce=nonce,
        )

    assert _status_post_count(transport) == before_posts
    assert ledger.inspect(_LEASE_KEY).current == pending


def test_expiry_uses_github_server_time_and_rejects_date_rollback() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    receipt = ledger.acquire(_LEASE_KEY, _owner(), ttl_seconds=10)
    transport.advance(9)
    assert ledger.scheduled_admission(_LEASE_KEY).action is ScheduledLeaseAction.NOOP_HELD
    transport.advance(1)
    assert ledger.scheduled_admission(_LEASE_KEY).action is ScheduledLeaseAction.ACQUIRE_REQUIRED
    with pytest.raises(BaselineLeaseStaleError, match="expired"):
        ledger.heartbeat(receipt, ttl_seconds=10)

    transport.date_override = transport.clock - timedelta(seconds=1)
    with pytest.raises(BaselineLeaseError, match="time moved backwards"):
        ledger.inspect(_LEASE_KEY)


def test_live_retention_truncated_head_noops_and_rejects_reusable_receipts() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    acquired = ledger.acquire(_LEASE_KEY, _owner(101), ttl_seconds=60)
    heartbeat = ledger.heartbeat(acquired, ttl_seconds=60)
    del transport.statuses[heartbeat.fence][acquired.revision]
    _age_deployment_past_status_retention(transport, heartbeat.fence)

    inspection = ledger.inspect(_LEASE_KEY)
    assert inspection.current is None
    assert inspection.head_fence == heartbeat.fence
    assert inspection.retention_truncated is True
    assert inspection.retained_head_revision == heartbeat.revision
    assert inspection.retained_head_state is LeaseState.ACTIVE
    assert inspection.held is True
    admission = ledger.scheduled_admission(_LEASE_KEY)
    assert admission.action is ScheduledLeaseAction.NOOP_HELD
    assert admission.fence == heartbeat.fence
    assert admission.receipt_digest is None
    before_posts = _status_post_count(transport)

    with pytest.raises(BaselineLeaseStaleError, match="no longer current"):
        ledger.heartbeat(heartbeat, ttl_seconds=60)
    with pytest.raises(BaselineLeaseStaleError, match="no longer current"):
        ledger.transfer(heartbeat, _owner(202), ttl_seconds=60)
    with pytest.raises(BaselineLeaseStaleError, match="no longer current"):
        ledger.release(heartbeat)
    with pytest.raises(BaselineLeaseStaleError, match="no longer current"):
        ledger.recover(heartbeat, _owner(303), ttl_seconds=60)
    with pytest.raises(BaselineLeaseHeldError, match="already held"):
        ledger.acquire(_LEASE_KEY, _owner(404), ttl_seconds=60)
    assert _status_post_count(transport) == before_posts


def test_expired_retention_truncated_head_allows_only_higher_deployment_fence() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    acquired = ledger.acquire(_LEASE_KEY, _owner(101), ttl_seconds=5)
    heartbeat = ledger.heartbeat(acquired, ttl_seconds=5)
    del transport.statuses[heartbeat.fence][acquired.revision]
    _age_deployment_past_status_retention(transport, heartbeat.fence)
    transport.advance(5)

    inspection = ledger.inspect(_LEASE_KEY)
    assert inspection.current is None
    assert inspection.retention_truncated is True
    assert inspection.held is False
    replacement = ledger.acquire(_LEASE_KEY, _owner(202), ttl_seconds=30)
    assert replacement.fence > heartbeat.fence
    assert ledger.assert_current(replacement) == replacement


def test_released_retention_truncated_head_allows_higher_deployment_fence() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    acquired = ledger.acquire(_LEASE_KEY, _owner(101), ttl_seconds=60)
    released = ledger.release(acquired)
    del transport.statuses[released.fence][acquired.revision]
    _age_deployment_past_status_retention(transport, released.fence)

    inspection = ledger.inspect(_LEASE_KEY)
    assert inspection.current is None
    assert inspection.retention_truncated is True
    assert inspection.retained_head_state is LeaseState.RELEASED
    assert inspection.held is False
    replacement = ledger.acquire(_LEASE_KEY, _owner(202), ttl_seconds=30)
    assert replacement.fence > released.fence
    transport.statuses[released.fence][released.revision]["description"] = "malformed"
    assert ledger.assert_current(replacement) == replacement


def test_retention_truncated_siblings_conservatively_preserve_live_branch() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    acquired = ledger.acquire(
        _LEASE_KEY,
        _owner(101),
        ttl_seconds=60,
        nonce="1" * 32,
    )
    active_sibling = ledger.heartbeat(
        acquired,
        ttl_seconds=60,
        nonce="2" * 32,
    )
    released_sibling_revision = _append_transition_mutation(
        transport,
        ledger,
        acquired,
        operation=LeaseOperation.RELEASE,
        owner=acquired.owner,
        ttl_seconds=0,
        nonce="3" * 32,
    )
    assert released_sibling_revision > active_sibling.revision
    del transport.statuses[acquired.fence][acquired.revision]
    _age_deployment_past_status_retention(transport, acquired.fence)
    transport.status_tie_order = "alternating"

    inspection = ledger.inspect(_LEASE_KEY)
    assert inspection.current is None
    assert inspection.retention_truncated is True
    assert inspection.retained_head_revision == active_sibling.revision
    assert inspection.retained_head_state is LeaseState.ACTIVE
    assert inspection.held is True
    before_deployment_posts = _deployment_post_count(transport)
    before_status_posts = _status_post_count(transport)

    with pytest.raises(BaselineLeaseHeldError, match="already held"):
        ledger.acquire(
            _LEASE_KEY,
            _owner(202),
            ttl_seconds=30,
            nonce="4" * 32,
        )
    with pytest.raises(BaselineLeaseStaleError, match="no longer current"):
        ledger.heartbeat(active_sibling, ttl_seconds=30, nonce="5" * 32)

    assert _deployment_post_count(transport) == before_deployment_posts
    assert _status_post_count(transport) == before_status_posts

    transport.advance(60)
    expired = ledger.inspect(_LEASE_KEY)
    assert expired.current is None
    assert expired.retention_truncated is True
    assert expired.held is False
    replacement = ledger.acquire(
        _LEASE_KEY,
        _owner(202),
        ttl_seconds=30,
        nonce="6" * 32,
    )
    assert replacement.fence > acquired.fence
    assert ledger.assert_current(replacement) == replacement


def test_recent_missing_status_predecessor_fails_closed() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    acquired = ledger.acquire(_LEASE_KEY, _owner(101), ttl_seconds=60)
    heartbeat = ledger.heartbeat(acquired, ttl_seconds=60)
    del transport.statuses[heartbeat.fence][acquired.revision]

    with pytest.raises(BaselineLeaseError, match="recent status predecessor"):
        ledger.inspect(_LEASE_KEY)


def test_scheduled_admission_noops_before_secret_or_tunnel_access() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    receipt = ledger.acquire(_LEASE_KEY, _owner(), ttl_seconds=60)
    accessed: list[str] = []

    admission = ledger.scheduled_admission(_LEASE_KEY)
    if admission.action is ScheduledLeaseAction.ACQUIRE_REQUIRED:
        accessed.extend(("publisher-secret", "vpn-tunnel"))

    assert admission.action is ScheduledLeaseAction.NOOP_HELD
    assert admission.fence == receipt.fence
    assert admission.receipt_digest == receipt.receipt_digest
    assert accessed == []


def test_missing_ambiguous_or_noncanonical_server_date_fails_closed() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    transport.duplicate_date_case = True

    with pytest.raises(BaselineLeaseError, match="missing or ambiguous"):
        ledger.inspect(_LEASE_KEY)


def test_direct_status_drift_and_tampered_transition_authority_fail_closed() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    receipt = ledger.acquire(_LEASE_KEY, _owner(), ttl_seconds=60)
    transport.mutate_direct_status = True
    with pytest.raises(BaselineLeaseError, match="status identity"):
        ledger.inspect(_LEASE_KEY)
    transport.mutate_direct_status = False
    status = transport.statuses[receipt.fence][receipt.revision]
    parts = status["description"].split(".")
    parts[-2] = "A" * 43
    status["description"] = ".".join(parts)
    with pytest.raises(BaselineLeaseError, match="receipt/owner authority"):
        ledger.inspect(_LEASE_KEY)


def test_persisted_transition_rejects_tampered_predecessor_revision() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    acquired = ledger.acquire(_LEASE_KEY, _owner(), ttl_seconds=60)
    heartbeat = ledger.heartbeat(acquired, ttl_seconds=60)
    status = transport.statuses[heartbeat.fence][heartbeat.revision]
    parts = status["description"].split(".")
    parts[5] = "0"
    status["description"] = ".".join(parts)

    with pytest.raises(BaselineLeaseError, match="receipt/owner authority"):
        ledger.inspect(_LEASE_KEY)


def test_direct_status_get_rejects_payload_id_different_from_requested_id() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    ledger.acquire(_LEASE_KEY, _owner(), ttl_seconds=60)
    transport.mutate_direct_status_id = True

    with pytest.raises(BaselineLeaseError, match="status receipt changed from inventory"):
        ledger.inspect(_LEASE_KEY)


def test_direct_transition_get_rejects_one_shot_coherent_status_id_substitution() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    acquired = ledger.acquire(_LEASE_KEY, _owner(), ttl_seconds=60)

    def substitute_next_direct_status() -> None:
        transport.mutate_next_direct_status_id = True

    transport.before_status_post = substitute_next_direct_status
    with pytest.raises(BaselineLeaseError, match="transition receipt changed after creation"):
        ledger.heartbeat(
            acquired,
            ttl_seconds=60,
            nonce="f" * 32,
        )

    current = ledger.inspect(_LEASE_KEY).current
    assert current is not None
    assert current.operation is LeaseOperation.HEARTBEAT
    assert current.transition_nonce == "f" * 32


def test_direct_deployment_get_rejects_payload_id_different_from_requested_id() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    ledger.acquire(_LEASE_KEY, _owner(), ttl_seconds=60)
    transport.mutate_direct_deployment_id = True

    with pytest.raises(BaselineLeaseError, match="deployment receipt changed from requested ID"):
        ledger.inspect(_LEASE_KEY)


def test_acquire_rejects_direct_deployment_requested_ttl_substitution_before_status() -> None:
    transport = FakeBaselineGitHub()
    transport.mutate_next_direct_deployment_ttl = True
    ledger = _ledger(transport)

    with pytest.raises(BaselineLeaseError, match="creation receipt is inconsistent"):
        ledger.acquire(
            _LEASE_KEY,
            _owner(),
            ttl_seconds=60,
            nonce="7" * 32,
        )

    assert _status_post_count(transport) == 0
    assert transport.statuses[1] == {}


@pytest.mark.parametrize(
    "persisted_ttl",
    [True, "60", 0, baseline_lease_module._MAX_TTL_SECONDS + 1],
)
def test_persisted_deployment_ttl_failures_are_baseline_lease_errors(
    persisted_ttl: Any,
) -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    receipt = ledger.acquire(
        _LEASE_KEY,
        _owner(),
        ttl_seconds=60,
        nonce="7" * 32,
    )
    transport.deployments[receipt.fence]["payload"]["requested_ttl_seconds"] = persisted_ttl

    with pytest.raises(BaselineLeaseError, match="deployment requested TTL is invalid"):
        ledger.inspect(_LEASE_KEY)


@pytest.mark.parametrize(
    ("description_index", "replacement", "message"),
    [
        (2, "0", "persisted transition owner is invalid"),
        (3, "2", "persisted transition owner is invalid"),
        (5, "status_id", "persisted status receipt is invalid"),
    ],
)
def test_persisted_status_dataclass_failures_are_baseline_lease_errors(
    description_index: int,
    replacement: str,
    message: str,
) -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    receipt = ledger.acquire(
        _LEASE_KEY,
        _owner(),
        ttl_seconds=60,
        nonce="8" * 32,
    )
    status = transport.statuses[receipt.fence][receipt.revision]
    description = status["description"].split(".")
    description[description_index] = (
        _base36(receipt.revision) if replacement == "status_id" else replacement
    )
    status["description"] = ".".join(description)

    with pytest.raises(BaselineLeaseError, match=message):
        ledger.inspect(_LEASE_KEY)


def test_acquire_rejects_raced_active_root_with_changed_requested_ttl() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    owner = _owner()
    nonce = "8" * 32

    def mutate_ttl_and_install_matching_active_root() -> None:
        stored = transport.deployments[1]
        stored["payload"]["requested_ttl_seconds"] = 61
        deployment = ledger._parse_deployment(
            stored,
            lease_key=_LEASE_KEY,
            observed_at=transport.clock,
        )
        pending = ledger._pending_receipt(deployment)
        _append_transition_mutation(
            transport,
            ledger,
            pending,
            operation=LeaseOperation.ACQUIRE,
            owner=owner,
            ttl_seconds=61,
            nonce=nonce,
        )

    transport.after_direct_deployment = mutate_ttl_and_install_matching_active_root
    with pytest.raises(BaselineLeaseError, match="request TTL changed"):
        ledger.acquire(
            _LEASE_KEY,
            owner,
            ttl_seconds=60,
            nonce=nonce,
        )

    assert _status_post_count(transport) == 0
    current = ledger.inspect(_LEASE_KEY).current
    assert current is not None
    assert current.state is LeaseState.ACTIVE
    assert current.operation is LeaseOperation.ACQUIRE
    assert current.expires_at == "2026-08-21T12:01:01Z"


def test_deployment_schema_version_rejects_json_boolean() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    receipt = ledger.acquire(_LEASE_KEY, _owner(), ttl_seconds=60)
    transport.deployments[receipt.fence]["payload"]["schema_version"] = True

    with pytest.raises(BaselineLeaseError, match="payload identity"):
        ledger.inspect(_LEASE_KEY)


@pytest.mark.parametrize("max_ttl_seconds", [86_401, True])
def test_constructor_rejects_noncanonical_or_oversize_ttl_ceiling(
    max_ttl_seconds: Any,
) -> None:
    transport = FakeBaselineGitHub()

    with pytest.raises(ValueError, match="fixed bounded contract"):
        GitHubDeploymentBaselineLease(
            token="token",
            repository=_REPOSITORY,
            transport=transport,
            max_ttl_seconds=max_ttl_seconds,
        )
    assert transport.calls == []


def test_explicit_falsey_nonces_are_rejected_without_status_writes() -> None:
    empty_transport = FakeBaselineGitHub()
    empty_ledger = _ledger(empty_transport)
    with pytest.raises(ValueError, match="nonce"):
        empty_ledger.acquire(_LEASE_KEY, _owner(), ttl_seconds=60, nonce="")
    assert empty_transport.calls == []

    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    active = ledger.acquire(_LEASE_KEY, _owner(), ttl_seconds=5, nonce="1" * 32)
    before_posts = _status_post_count(transport)
    with pytest.raises(ValueError, match="parameters"):
        ledger.heartbeat(active, ttl_seconds=5, nonce="")
    with pytest.raises(ValueError, match="parameters"):
        ledger.transfer(active, _owner(202), ttl_seconds=5, nonce="")
    with pytest.raises(ValueError, match="parameters"):
        ledger.release(active, nonce="")
    transport.advance(5)
    with pytest.raises(ValueError, match="parameters"):
        ledger.recover(active, _owner(303), ttl_seconds=5, nonce="")
    assert _status_post_count(transport) == before_posts


@pytest.mark.parametrize(
    ("ttl_token", "message"),
    [
        ("z" * 141, "description is too large"),
        (_base36(86_401), "active transition TTL is outside its bounded contract"),
    ],
)
def test_persisted_active_transition_rejects_oversize_or_overflow_ttl(
    ttl_token: str,
    message: str,
) -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    acquired = ledger.acquire(_LEASE_KEY, _owner(), ttl_seconds=60)
    heartbeat = ledger.heartbeat(acquired, ttl_seconds=60)
    _replace_status_ttl(transport, heartbeat, ttl_token)

    with pytest.raises(BaselineLeaseError, match=message):
        ledger.inspect(_LEASE_KEY)


def test_acquire_status_ttl_must_equal_deployment_request() -> None:
    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    acquired = ledger.acquire(_LEASE_KEY, _owner(), ttl_seconds=60)
    _replace_status_ttl(transport, acquired, _base36(61))

    with pytest.raises(BaselineLeaseError, match="differs from its deployment request"):
        ledger.inspect(_LEASE_KEY)


def test_acquire_timeout_before_accept_is_reconciliation_only() -> None:
    transport = FakeBaselineGitHub()
    transport.raise_deployment = "before"
    ledger = _ledger(transport)

    with pytest.raises(BaselineLeasePendingError, match="nonce"):
        ledger.acquire(
            _LEASE_KEY,
            _owner(),
            ttl_seconds=60,
            nonce="e" * 32,
        )
    assert transport.deployments == {}


def test_receipt_value_validation_rejects_rerun_and_tampering() -> None:
    with pytest.raises(ValueError, match="attempt one"):
        BaselineLeaseOwner(
            repository=_REPOSITORY,
            run_id=101,
            run_attempt=2,
            source_sha=_SOURCE_SHA,
            workflow_sha256=_WORKFLOW_SHA256,
        )

    transport = FakeBaselineGitHub()
    ledger = _ledger(transport)
    receipt = ledger.acquire(_LEASE_KEY, _owner(), ttl_seconds=60)
    with pytest.raises(ValueError, match="environment"):
        replace(receipt, environment="foreign")
