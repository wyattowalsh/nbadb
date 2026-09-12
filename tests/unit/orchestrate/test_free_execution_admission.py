from __future__ import annotations

import json
from dataclasses import replace

import pytest

from nbadb.orchestrate.free_execution_admission import (
    ARTIFACT_PACKAGES_FREE_FLOOR_BYTES,
    CostReadbackAuthorityBundleV1,
    ExactHttpResponseV1,
    ExecutionIntentV1,
    ExternalServiceKind,
    FreeExecutionAdmissionError,
    FreeExecutionAdmissionV1,
    FreeExecutionAuthorityBundleV1,
    FreeExecutionCostReadbackStatus,
    FreeExecutionCostReadbackV1,
    FreeExecutionMode,
    FreeExecutionPointOfUseV1,
    JobGraphEvidenceV1,
    PagedInventoryAuthorityV1,
    PointOfUseAuthorityBundleV1,
    ProviderOperationV1,
    canonical_json_bytes,
)

_REPOSITORY = "w4w/nbadb"
_SOURCE_SHA = "a" * 40
_WORKFLOW_PATH = ".github/workflows/full-extraction.yml"
_RUN_ID = 101
_RUN_ATTEMPT = 1
_OWNER = {"id": 7, "login": "w4w", "type": "User"}
_PRICING_URL = "https://docs.github.com/en/billing/concepts/product-billing/github-actions"


def _json_response(
    url: str,
    payload: object,
    *,
    at: str = "2026-08-26T12:00:00Z",
    api: bool = True,
    etag: str = '"etag"',
) -> ExactHttpResponseV1:
    return ExactHttpResponseV1(
        method="GET",
        url=url,
        api_version="2026-03-10" if api else None,
        status_code=200,
        response_date=at,
        etag=etag,
        body=canonical_json_bytes(payload),
    )


def _text_response(
    url: str,
    text: str,
    *,
    at: str = "2026-08-26T12:00:00Z",
) -> ExactHttpResponseV1:
    return ExactHttpResponseV1(
        method="GET",
        url=url,
        api_version=None,
        status_code=200,
        response_date=at,
        etag='"text-etag"',
        body=text.encode(),
    )


def _workflow_bytes() -> bytes:
    return b"""name: Full extraction
on: workflow_dispatch
jobs:
  plan:
    name: Plan
    runs-on: ubuntu-latest
    steps:
      - run: echo ok
  extract:
    name: Extract ${{ matrix.lane_id }}
    needs: plan
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix: ${{ fromJSON(needs.plan.outputs.github-matrix) }}
    steps:
      - run: echo extract
"""


def _lane_operation(index: int = 0, *, nonce: str | None = None) -> ProviderOperationV1:
    lane_id = f"lane-{index}"
    season = f"202{index}-2{index + 1}"
    return ProviderOperationV1(
        service_kind=ExternalServiceKind.NBA_API,
        lane_id=lane_id,
        operation_kind="extract",
        endpoint_id="league_game_log",
        method="GET",
        request_url="https://stats.nba.com/stats/leaguegamelog",
        safe_parameters_json=canonical_json_bytes({"Season": season}).decode(),
        request_body_sha256=None,
        operation_nonce=nonce or f"{lane_id}-call-1",
    )


def _manifest_bytes(*, publish: bool = False, lane_count: int = 2) -> bytes:
    workflow_sha = __import__("hashlib").sha256(_workflow_bytes()).hexdigest()
    lanes = [
        {
            "lane_id": f"lane-{index}",
            "lane_index": index,
            "endpoint": "league_game_log",
            "parameters": {"season": f"202{index}-2{index + 1}"},
            "operation_sha256s": [_lane_operation(index).operation_sha256],
        }
        for index in range(lane_count)
    ]
    return canonical_json_bytes(
        {
            "schema_version": 1,
            "repository": _REPOSITORY,
            "source_sha": _SOURCE_SHA,
            "workflow_path": _WORKFLOW_PATH,
            "workflow_sha256": workflow_sha,
            "publish": publish,
            "active_lane_count": lane_count,
            "matrix_lane_count": lane_count,
            "deferred_lane_count": 0,
            "lanes": lanes,
            "github_matrix": {"include": lanes},
            "resource_plan": {
                "planned_artifact_max_bytes": 0,
                "planned_artifact_retention_hours": 0,
                "planned_cache_max_bytes": 0,
            },
        }
    )


def _repository_response(*, at: str = "2026-08-26T12:00:00Z") -> ExactHttpResponseV1:
    return _json_response(
        f"https://api.github.com/repos/{_REPOSITORY}",
        {
            "id": 42,
            "full_name": _REPOSITORY,
            "owner": _OWNER,
            "private": False,
            "visibility": "public",
            "archived": False,
            "disabled": False,
        },
        at=at,
    )


def _pricing_response(*, at: str = "2026-08-26T12:00:00Z") -> ExactHttpResponseV1:
    return _json_response(
        _PRICING_URL,
        {
            "schema_version": 1,
            "authority_kind": "reviewed_zero_incremental_charge_v1",
            "service_kind": "github_actions_compute",
            "authority_url": _PRICING_URL,
            "authority_rule_id": "public_standard_github_hosted_compute_free",
            "maximum_incremental_charge_microusd": 0,
            "effective_at": "2026-08-01T00:00:00Z",
            "expires_at": "2026-09-01T00:00:00Z",
            "qualified_review_sha256": "9" * 64,
        },
        at=at,
        api=False,
    )


def _external_response(
    kind: ExternalServiceKind,
    *,
    at: str = "2026-08-26T12:00:00Z",
) -> ExactHttpResponseV1:
    authorities = {
        ExternalServiceKind.GITHUB_NETWORK_EGRESS: (
            _PRICING_URL,
            "github_public_network_egress_zero_incremental_charge_v1",
            "github_network_egress",
        ),
        ExternalServiceKind.NBA_API: (
            "https://www.nba.com/termsofuse",
            "nba_public_api_zero_incremental_charge_v1",
            "nba_api",
        ),
        ExternalServiceKind.KAGGLE: (
            "https://www.kaggle.com/docs/api",
            "kaggle_public_api_zero_incremental_charge_v1",
            "kaggle",
        ),
    }
    url, rule_id, service_kind = authorities[kind]
    return _json_response(
        url,
        {
            "schema_version": 1,
            "authority_kind": "reviewed_zero_incremental_charge_v1",
            "service_kind": service_kind,
            "authority_url": url,
            "authority_rule_id": rule_id,
            "maximum_incremental_charge_microusd": 0,
            "effective_at": "2026-08-01T00:00:00Z",
            "expires_at": "2026-09-01T00:00:00Z",
            "qualified_review_sha256": "8" * 64,
        },
        at=at,
        api=False,
    )


def _execution_context_response(*, publish: bool = False) -> ExactHttpResponseV1:
    workflow_sha = __import__("hashlib").sha256(_workflow_bytes()).hexdigest()
    manifest_sha = __import__("hashlib").sha256(_manifest_bytes(publish=publish)).hexdigest()
    url = (
        f"https://api.github.com/repos/{_REPOSITORY}/actions/runs/{_RUN_ID}/"
        f"attempts/{_RUN_ATTEMPT}/free-execution-context"
    )
    return _json_response(
        url,
        {
            "schema_version": 1,
            "repository": _REPOSITORY,
            "source_sha": _SOURCE_SHA,
            "workflow_path": _WORKFLOW_PATH,
            "workflow_sha256": workflow_sha,
            "run_id": _RUN_ID,
            "run_attempt": _RUN_ATTEMPT,
            "admission_job_id": "free-execution-admission",
            "mode": FreeExecutionMode.INITIAL.value,
            "requested_capacity": 2,
            "admission_nonce": "run-101-attempt-1-admission",
            "evaluated_at": "2026-08-26T12:01:00Z",
            "expires_at": "2026-08-26T12:05:00Z",
            "manifest_sha256": manifest_sha,
            "producer_job_receipt_sha256": "7" * 64,
        },
    )


def _account_usage(
    *,
    inventory: bool,
    at: str,
    charge: int = 0,
) -> ExactHttpResponseV1:
    url = "https://api.github.com/users/w4w/settings/billing/usage"
    if inventory:
        payload: object = {
            "account": _OWNER,
            "artifact_packages": {
                "accrued_byte_hours": 100,
                "items": [
                    {
                        "id": 1,
                        "kind": "artifact",
                        "size_bytes": 100,
                        "expires_at": "2026-08-27T12:00:00Z",
                    }
                ],
            },
        }
    else:
        payload = {
            "account": _OWNER,
            "incremental_charge_microusd": charge,
            "settled": True,
            "overlap_absent": True,
        }
    return _json_response(url, payload, at=at)


def _cache_usage(*, at: str, size: int = 4096) -> ExactHttpResponseV1:
    return _json_response(
        f"https://api.github.com/repos/{_REPOSITORY}/actions/cache/usage",
        {"active_caches_count": 1, "active_caches_size_in_bytes": size},
        at=at,
    )


def _authority(
    *,
    publish: bool = False,
    fresh: bool = False,
) -> FreeExecutionAuthorityBundleV1:
    if fresh:
        repo_at = "2026-08-26T12:08:00Z"
        cache_first_at = "2026-08-26T12:02:00Z"
        cache_stable_at = "2026-08-26T12:07:00Z"
    else:
        repo_at = "2026-08-26T12:00:00Z"
        cache_first_at = "2026-08-26T11:54:00Z"
        cache_stable_at = "2026-08-26T11:59:00Z"
    kinds = [ExternalServiceKind.GITHUB_NETWORK_EGRESS, ExternalServiceKind.NBA_API]
    if publish:
        kinds.append(ExternalServiceKind.KAGGLE)
    kinds.sort(key=lambda item: item.value)
    return FreeExecutionAuthorityBundleV1(
        workflow_bytes=_workflow_bytes(),
        manifest_bytes=_manifest_bytes(publish=publish),
        execution_context_response=_execution_context_response(publish=publish),
        repository_response=_repository_response(at=repo_at),
        pricing_response=_pricing_response(at=repo_at),
        storage_inventory_response=_account_usage(inventory=True, at=repo_at),
        cache_first_response=_cache_usage(at=cache_first_at),
        cache_stable_response=_cache_usage(at=cache_stable_at),
        billing_response=_account_usage(inventory=False, at=repo_at),
        external_responses=tuple((kind, _external_response(kind, at=repo_at)) for kind in kinds),
    )


def _admission(*, publish: bool = False) -> FreeExecutionAdmissionV1:
    workflow_sha = __import__("hashlib").sha256(_workflow_bytes()).hexdigest()
    return FreeExecutionAdmissionV1.admitted(
        authority=_authority(publish=publish),
        repository=_REPOSITORY,
        source_sha=_SOURCE_SHA,
        workflow_path=_WORKFLOW_PATH,
        workflow_sha256=workflow_sha,
        run_id=_RUN_ID,
        run_attempt=_RUN_ATTEMPT,
        admission_job_id="free-execution-admission",
        mode=FreeExecutionMode.INITIAL,
        requested_capacity=2,
        admission_nonce="run-101-attempt-1-admission",
        evaluated_at="2026-08-26T12:01:00Z",
        expires_at="2026-08-26T12:05:00Z",
    )


def _job_response(
    *,
    name: str = "Extract lane-0",
    job_id: int = 501,
    at: str = "2026-08-26T12:08:00Z",
) -> ExactHttpResponseV1:
    return _json_response(
        f"https://api.github.com/repos/{_REPOSITORY}/actions/jobs/{job_id}",
        {
            "id": job_id,
            "name": name,
            "run_id": _RUN_ID,
            "run_attempt": _RUN_ATTEMPT,
            "head_sha": _SOURCE_SHA,
            "status": "in_progress",
            "conclusion": None,
            "runner_id": 9001,
            "runner_name": "GitHub Actions 1",
            "runner_group_name": None,
            "labels": ["ubuntu-latest"],
            "environment": "github-hosted",
            "os": "Linux",
            "arch": "X64",
        },
        at=at,
    )


def _point_bundle() -> PointOfUseAuthorityBundleV1:
    return PointOfUseAuthorityBundleV1(
        refreshed_free_authority=_authority(fresh=True),
        actual_job_response=_job_response(),
    )


def test_exact_http_response_rejects_duplicate_keys_nonfinite_and_secrets() -> None:
    kwargs = {
        "method": "GET",
        "url": "https://api.github.com/example",
        "api_version": "2026-03-10",
        "status_code": 200,
        "response_date": "2026-08-26T12:00:00Z",
        "etag": '"x"',
    }
    duplicate = ExactHttpResponseV1(body=b'{"x":1,"x":2}', **kwargs)
    with pytest.raises(FreeExecutionAdmissionError, match="duplicate"):
        duplicate.json_value()
    nonfinite = ExactHttpResponseV1(body=b'{"x":NaN}', **kwargs)
    with pytest.raises(FreeExecutionAdmissionError, match="non-finite"):
        nonfinite.json_value()
    with pytest.raises(FreeExecutionAdmissionError, match="secret"):
        ExactHttpResponseV1(
            body=b'{"authorization":"Bearer github_pat_' + b"a" * 30 + b'"}', **kwargs
        )
    secret_key = ExactHttpResponseV1(body=b'{"api_token":"redacted"}', **kwargs)
    with pytest.raises(FreeExecutionAdmissionError, match="secret"):
        secret_key.json_value()
    sealed = ExactHttpResponseV1(body=b'{"x":1}', **kwargs)
    object.__setattr__(sealed, "body", b'{"x":2}')
    with pytest.raises(FreeExecutionAdmissionError, match="changed after sealing"):
        sealed.json_value()


def test_manifest_derives_kaggle_only_from_publish_intent_and_round_trips() -> None:
    ordinary = ExecutionIntentV1.from_manifest_bytes(_manifest_bytes())
    publish = ExecutionIntentV1.from_manifest_bytes(_manifest_bytes(publish=True))
    assert ordinary.required_external_services == (
        ExternalServiceKind.GITHUB_NETWORK_EGRESS,
        ExternalServiceKind.NBA_API,
    )
    assert publish.required_external_services == (
        ExternalServiceKind.GITHUB_NETWORK_EGRESS,
        ExternalServiceKind.KAGGLE,
        ExternalServiceKind.NBA_API,
    )
    assert ExecutionIntentV1.from_dict(publish.to_dict()) == publish


@pytest.mark.parametrize("forbidden", ["vpn", "proxy_url", "paid_credit", "api_token"])
def test_manifest_recursively_rejects_paid_secret_or_routing_fields(forbidden: str) -> None:
    payload = json.loads(_manifest_bytes())
    payload["lanes"][0]["parameters"][forbidden] = "x"
    with pytest.raises(FreeExecutionAdmissionError, match="forbidden|secret"):
        ExecutionIntentV1.from_manifest_bytes(canonical_json_bytes(payload))


@pytest.mark.parametrize("forbidden", ["vpn", "paid", "proxy", "secret", "token"])
def test_manifest_recursively_rejects_forbidden_string_values(forbidden: str) -> None:
    payload = json.loads(_manifest_bytes())
    payload["lanes"][0]["parameters"]["transport"] = {"mode": forbidden}
    with pytest.raises(FreeExecutionAdmissionError, match="forbidden"):
        ExecutionIntentV1.from_manifest_bytes(canonical_json_bytes(payload))


def test_workflow_parser_preserves_on_and_rejects_duplicates_aliases_and_reuse() -> None:
    intent = ExecutionIntentV1.from_manifest_bytes(_manifest_bytes())
    graph = JobGraphEvidenceV1.from_workflow_bytes(_workflow_bytes(), intent=intent)
    assert graph.maximum_total_jobs == 3
    assert graph.job("extract").maximum_instances == 2
    for hostile in (
        b"on: workflow_dispatch\non: push\njobs: {}\n",
        b"on: workflow_dispatch\nx: &a 1\ny: *a\njobs: {}\n",
        b"on: workflow_dispatch\njobs:\n  x:\n    uses: ./x.yml\n",
    ):
        hostile_intent = replace(
            intent,
            workflow_sha256=__import__("hashlib").sha256(hostile).hexdigest(),
            intent_sha256="",
        )
        with pytest.raises(FreeExecutionAdmissionError):
            JobGraphEvidenceV1.from_workflow_bytes(hostile, intent=hostile_intent)


def test_workflow_parser_rejects_unsupported_triggers_expressions_and_cycles() -> None:
    base_intent = ExecutionIntentV1.from_manifest_bytes(_manifest_bytes())
    hostiles = (
        b"on: push\njobs:\n  x:\n    runs-on: ubuntu-latest\n",
        (
            b"on: workflow_dispatch\njobs:\n  x:\n    runs-on: ubuntu-latest\n"
            b"    name: ${{ secrets.X }}\n"
        ),
        (
            b"on: workflow_dispatch\njobs:\n  x:\n    needs: y\n"
            b"    runs-on: ubuntu-latest\n  y:\n    needs: x\n"
            b"    runs-on: ubuntu-latest\n"
        ),
    )
    for hostile in hostiles:
        intent = replace(
            base_intent,
            workflow_sha256=__import__("hashlib").sha256(hostile).hexdigest(),
            intent_sha256="",
        )
        with pytest.raises(FreeExecutionAdmissionError):
            JobGraphEvidenceV1.from_workflow_bytes(hostile, intent=intent)


@pytest.mark.parametrize(
    "hostile",
    [
        (
            b"on: workflow_dispatch\njobs:\n  x:\n    runs-on: ubuntu-latest\n"
            b"    env:\n      MODE: vpn\n    steps:\n      - run: echo ok\n"
        ),
        (
            b"on: workflow_dispatch\njobs:\n  x:\n    runs-on: ubuntu-latest\n"
            b"    steps:\n      - run: curl https://example.com\n"
        ),
        (
            b"on: workflow_dispatch\njobs:\n  x:\n    runs-on: ubuntu-latest\n"
            b"    steps:\n      - uses: actions/upload-artifact@"
            b"0123456789012345678901234567890123456789\n"
        ),
        (
            b"on: workflow_dispatch\njobs:\n  x:\n    runs-on: ubuntu-latest\n"
            b"    container: python:3\n    steps:\n      - run: echo ok\n"
        ),
        (
            b"on: workflow_dispatch\njobs:\n  x:\n    runs-on: ubuntu-latest\n"
            b"    steps:\n      - run: echo ok\n        shell: python\n"
        ),
        (
            b"on: workflow_dispatch\nenv:\n  BASH_ENV: bootstrap.sh\njobs:\n"
            b"  x:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo ok\n"
        ),
    ],
)
def test_workflow_recursively_rejects_unpriced_effects(hostile: bytes) -> None:
    intent = replace(
        ExecutionIntentV1.from_manifest_bytes(_manifest_bytes()),
        workflow_sha256=__import__("hashlib").sha256(hostile).hexdigest(),
        intent_sha256="",
    )
    with pytest.raises(FreeExecutionAdmissionError):
        JobGraphEvidenceV1.from_workflow_bytes(hostile, intent=intent)


def test_pricing_free_text_and_negation_cannot_create_zero_cost_authority() -> None:
    hostile = replace(
        _authority(),
        pricing_response=_text_response(
            _PRICING_URL,
            "Standard GitHub-hosted runners are not free and no zero-cost claim is made.",
        ),
    )
    with pytest.raises(FreeExecutionAdmissionError, match="JSON|policy"):
        hostile.derive(
            repository=_REPOSITORY,
            expires_at="2026-08-26T12:05:00Z",
        )


def test_manifest_requires_exact_lane_rows_and_matrix_join() -> None:
    payload = json.loads(_manifest_bytes())
    del payload["lanes"][0]["endpoint"]
    with pytest.raises(FreeExecutionAdmissionError, match="lane fields"):
        ExecutionIntentV1.from_manifest_bytes(canonical_json_bytes(payload))
    payload = json.loads(_manifest_bytes())
    payload["github_matrix"]["include"][0]["endpoint"] = "team_years"
    with pytest.raises(FreeExecutionAdmissionError, match="differs"):
        ExecutionIntentV1.from_manifest_bytes(canonical_json_bytes(payload))


def test_candidate_authority_derives_exact_context_but_public_admission_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    intent, graph, pricing, storage, external = authority.derive(
        repository=_REPOSITORY,
        expires_at="2026-08-26T12:05:00Z",
    )
    context = authority.derive_execution_context(intent=intent)
    assert graph.intent_sha256 == intent.intent_sha256
    assert pricing.maximum_compute_charge_microusd == 0
    assert storage.maximum_incremental_charge_microusd == 0
    assert tuple(item.service_kind for item in external) == intent.required_external_services
    assert context == {
        "repository": _REPOSITORY,
        "source_sha": _SOURCE_SHA,
        "workflow_path": _WORKFLOW_PATH,
        "workflow_sha256": __import__("hashlib").sha256(_workflow_bytes()).hexdigest(),
        "run_id": _RUN_ID,
        "run_attempt": _RUN_ATTEMPT,
        "admission_job_id": "free-execution-admission",
        "mode": FreeExecutionMode.INITIAL,
        "requested_capacity": 2,
        "admission_nonce": "run-101-attempt-1-admission",
        "evaluated_at": "2026-08-26T12:01:00Z",
        "expires_at": "2026-08-26T12:05:00Z",
    }
    expected_codes = tuple(sorted(FreeExecutionAuthorityBundleV1.integration_blocker_codes))
    with pytest.raises(FreeExecutionAdmissionError) as caught:
        _admission()
    assert all(code in str(caught.value) for code in expected_codes)
    monkeypatch.setattr(FreeExecutionAuthorityBundleV1, "integration_blocker_codes", ())
    with pytest.raises(FreeExecutionAdmissionError) as still_blocked:
        _admission()
    assert all(code in str(still_blocked.value) for code in expected_codes)


def test_execution_context_rebinding_fails_before_integration_blocker() -> None:
    authority = _authority()
    kwargs = {
        "authority": authority,
        "repository": _REPOSITORY,
        "source_sha": _SOURCE_SHA,
        "workflow_path": _WORKFLOW_PATH,
        "workflow_sha256": __import__("hashlib").sha256(_workflow_bytes()).hexdigest(),
        "run_id": _RUN_ID,
        "run_attempt": _RUN_ATTEMPT,
        "admission_job_id": "free-execution-admission",
        "mode": FreeExecutionMode.INITIAL,
        "requested_capacity": 2,
        "admission_nonce": "run-101-attempt-1-admission",
        "evaluated_at": "2026-08-26T12:01:00Z",
        "expires_at": "2026-08-26T12:05:00Z",
    }
    for field_name, hostile in (
        ("run_id", 999),
        ("run_attempt", 2),
        ("admission_job_id", "other"),
        ("mode", FreeExecutionMode.DAILY),
        ("requested_capacity", 1),
        ("admission_nonce", "other"),
    ):
        rebound = dict(kwargs)
        rebound[field_name] = hostile
        with pytest.raises(FreeExecutionAdmissionError, match="context differs"):
            FreeExecutionAdmissionV1.admitted(**rebound)  # type: ignore[arg-type]


def test_direct_resealed_admitted_dto_cannot_bypass_collectors() -> None:
    blocked = FreeExecutionAdmissionV1.capacity_blocked(
        manifest_bytes=_manifest_bytes(),
        repository=_REPOSITORY,
        source_sha=_SOURCE_SHA,
        workflow_path=_WORKFLOW_PATH,
        workflow_sha256=__import__("hashlib").sha256(_workflow_bytes()).hexdigest(),
        run_id=_RUN_ID,
        run_attempt=_RUN_ATTEMPT,
        admission_job_id="free-execution-admission",
        mode=FreeExecutionMode.INITIAL,
        requested_capacity=2,
        admission_nonce="blocked",
        evaluated_at="2026-08-26T12:01:00Z",
        expires_at="2026-08-26T12:05:00Z",
        blocker_codes=("capacity_unavailable",),
    )
    intent, graph, pricing, storage, external = _authority().derive(
        repository=_REPOSITORY,
        expires_at="2026-08-26T12:05:00Z",
    )
    payload = blocked.to_dict()
    payload.update(
        {
            "status": "admitted",
            "blocker_codes": [],
            "admitted_capacity": 2,
            "intent": intent.to_dict(),
            "job_graph": graph.to_dict(),
            "repository_pricing": pricing.to_dict(),
            "storage_cost": storage.to_dict(),
            "external_services": [item.to_dict() for item in external],
            "authority_sha256": _authority().authority_sha256(),
            "admission_sha256": "",
        }
    )
    with pytest.raises(FreeExecutionAdmissionError, match="integration-blocked"):
        FreeExecutionAdmissionV1.from_dict(payload)


def test_capacity_blocked_has_manifest_identity_but_no_positive_evidence() -> None:
    blocked = FreeExecutionAdmissionV1.capacity_blocked(
        manifest_bytes=_manifest_bytes(),
        repository=_REPOSITORY,
        source_sha=_SOURCE_SHA,
        workflow_path=_WORKFLOW_PATH,
        workflow_sha256=__import__("hashlib").sha256(_workflow_bytes()).hexdigest(),
        run_id=_RUN_ID,
        run_attempt=_RUN_ATTEMPT,
        admission_job_id="free-execution-admission",
        mode=FreeExecutionMode.INITIAL,
        requested_capacity=2,
        admission_nonce="blocked-101-1",
        evaluated_at="2026-08-26T12:01:00Z",
        expires_at="2026-08-26T12:05:00Z",
        blocker_codes=("capacity_unavailable",),
    )
    assert blocked.admitted_capacity == 0
    assert blocked.authority_sha256 is None
    assert blocked.job_graph is None
    with pytest.raises(FreeExecutionAdmissionError, match="no positive authority"):
        blocked.validate_authority(_authority())


def test_storage_authority_counts_existing_future_liability_and_calendar() -> None:
    _, _, _, storage, _ = _authority().derive(
        repository=_REPOSITORY,
        expires_at="2026-08-26T12:05:00Z",
    )
    assert storage.artifact_packages_existing_future_byte_hours == 100 * 24
    assert storage.billing_period_hours == 31 * 24
    assert storage.artifact_packages_free_byte_hours == ARTIFACT_PACKAGES_FREE_FLOOR_BYTES * 31 * 24
    hostile_inventory = _account_usage(inventory=True, at="2026-08-26T12:00:00Z")
    payload = hostile_inventory.json_object()
    payload["artifact_packages"]["items"][0]["size_bytes"] = ARTIFACT_PACKAGES_FREE_FLOOR_BYTES + 1
    hostile = replace(
        _authority(),
        storage_inventory_response=_json_response(
            hostile_inventory.url,
            payload,
            at=hostile_inventory.response_date,
        ),
    )
    with pytest.raises(FreeExecutionAdmissionError, match="headroom|liability"):
        hostile.derive(
            repository=_REPOSITORY,
            expires_at="2026-08-26T12:05:00Z",
        )


@pytest.mark.parametrize("expiry", [None, "2026-09-02T00:00:00Z"])
def test_storage_candidate_rejects_unbounded_or_future_period_liability(
    expiry: str | None,
) -> None:
    response = _account_usage(inventory=True, at="2026-08-26T12:00:00Z")
    payload = response.json_object()
    payload["artifact_packages"]["items"][0]["expires_at"] = expiry
    authority = replace(
        _authority(),
        storage_inventory_response=_json_response(response.url, payload),
    )
    with pytest.raises(FreeExecutionAdmissionError, match="future"):
        authority.derive(
            repository=_REPOSITORY,
            expires_at="2026-08-26T12:05:00Z",
        )


def test_point_of_use_is_unconstructible_until_refresh_and_chain_collectors_exist() -> None:
    with pytest.raises(FreeExecutionAdmissionError) as caught:
        FreeExecutionPointOfUseV1.from_authority(
            admission=object(),  # type: ignore[arg-type]
            authority=_point_bundle(),
            logical_job_id="extract",
            lane_id="lane-0",
            predecessor=object(),  # type: ignore[arg-type]
            checked_at="2026-08-26T12:09:00Z",
            expires_at="2026-08-26T12:10:00Z",
        )
    assert all(
        code in str(caught.value) for code in PointOfUseAuthorityBundleV1.integration_blocker_codes
    )


def test_provider_operation_binds_exact_endpoint_parameters_and_body_semantics() -> None:
    operation = _lane_operation()
    assert ProviderOperationV1.from_dict(operation.to_dict()) == operation
    with pytest.raises(FreeExecutionAdmissionError, match="canonical"):
        replace(operation, safe_parameters_json='{ "Season":"2020-21" }', operation_sha256="")
    with pytest.raises(FreeExecutionAdmissionError, match="foreign"):
        replace(operation, request_url="https://evil.example/stats/x", operation_sha256="")
    with pytest.raises(FreeExecutionAdmissionError, match="body"):
        replace(operation, request_body_sha256="b" * 64, operation_sha256="")
    for hostile_url in (
        "https://stats.nba.com:443/stats/leaguegamelog",
        "https://stats.nba.com/stats/%2fleaguegamelog",
        "https://stats.nba.com/stats//leaguegamelog",
        "https://stats.nba.com/stats/leaguegamelog?Season=2020-21",
        "https://user@stats.nba.com/stats/leaguegamelog",
    ):
        with pytest.raises(FreeExecutionAdmissionError, match="foreign|ambiguous"):
            replace(operation, request_url=hostile_url, operation_sha256="")
    intent = ExecutionIntentV1.from_manifest_bytes(_manifest_bytes())
    assert operation.operation_sha256 in intent.operation_sha256s_for_lane("lane-0")
    assert _lane_operation(nonce="lane-0-call-2").operation_sha256 not in (
        intent.operation_sha256s_for_lane("lane-0")
    )


def _list_page(
    base_url: str,
    key: str,
    items: list[dict[str, object]],
    *,
    at: str,
    total: int | None = None,
) -> ExactHttpResponseV1:
    return _json_response(
        f"{base_url}?per_page=100&page=1",
        {"total_count": len(items) if total is None else total, key: items},
        at=at,
    )


def _job_list_item() -> dict[str, object]:
    return {
        "id": 501,
        "name": "Extract lane-0",
        "run_id": _RUN_ID,
        "run_attempt": _RUN_ATTEMPT,
        "head_sha": _SOURCE_SHA,
        "status": "completed",
        "conclusion": "success",
    }


def _artifact_list_item() -> dict[str, object]:
    return {
        "id": 601,
        "name": "lane-0-state",
        "size_in_bytes": 100,
        "expired": False,
        "created_at": "2026-08-26T12:00:00Z",
        "expires_at": "2026-08-26T13:00:00Z",
        "workflow_run_id": _RUN_ID,
        "head_sha": _SOURCE_SHA,
    }


def _external_usage(kind: ExternalServiceKind, *, charge: int = 0) -> ExactHttpResponseV1:
    operations = (
        [_lane_operation(index).operation_sha256 for index in range(2)]
        if kind is ExternalServiceKind.NBA_API
        else []
    )
    return _json_response(
        (
            f"https://api.github.com/repos/{_REPOSITORY}/actions/runs/{_RUN_ID}/"
            f"attempts/{_RUN_ATTEMPT}/free-execution-usage/{kind.value}"
        ),
        {
            "repository": _REPOSITORY,
            "source_sha": _SOURCE_SHA,
            "run_id": _RUN_ID,
            "run_attempt": _RUN_ATTEMPT,
            "service_kind": kind.value,
            "operation_sha256s": operations,
            "incremental_charge_microusd": charge,
            "settled": True,
        },
        at="2026-08-26T12:15:00Z",
    )


def _cost_storage_inventory(*, size: int = 100) -> ExactHttpResponseV1:
    return _json_response(
        "https://api.github.com/users/w4w/settings/billing/usage",
        {
            "account": _OWNER,
            "artifact_packages": {
                "accrued_byte_hours": 100,
                "items": [
                    {
                        "id": 601,
                        "kind": "artifact",
                        "size_bytes": size,
                        "expires_at": "2026-08-26T13:00:00Z",
                    }
                ],
            },
        },
        at="2026-08-26T12:15:00Z",
    )


def _cost_authority(*, charge: int = 0) -> CostReadbackAuthorityBundleV1:
    jobs_url = (
        f"https://api.github.com/repos/{_REPOSITORY}/actions/runs/{_RUN_ID}/"
        f"attempts/{_RUN_ATTEMPT}/jobs"
    )
    artifacts_url = f"https://api.github.com/repos/{_REPOSITORY}/actions/runs/{_RUN_ID}/artifacts"
    job_item = _job_list_item()
    artifact_item = _artifact_list_item()
    job_direct = _json_response(
        f"https://api.github.com/repos/{_REPOSITORY}/actions/jobs/501",
        {**job_item, "billable_milliseconds": 1000, "incremental_charge_microusd": charge},
        at="2026-08-26T12:15:00Z",
    )
    artifact_direct = _json_response(
        f"https://api.github.com/repos/{_REPOSITORY}/actions/artifacts/601",
        {**artifact_item, "incremental_charge_microusd": charge},
        at="2026-08-26T12:15:00Z",
    )
    kinds = ExecutionIntentV1.from_manifest_bytes(_manifest_bytes()).required_external_services
    return CostReadbackAuthorityBundleV1(
        jobs_inventory=PagedInventoryAuthorityV1(
            inventory_kind="jobs",
            base_url=jobs_url,
            items_key="jobs",
            first_pages=(_list_page(jobs_url, "jobs", [job_item], at="2026-08-26T12:09:00Z"),),
            stable_pages=(_list_page(jobs_url, "jobs", [job_item], at="2026-08-26T12:14:00Z"),),
        ),
        artifacts_inventory=PagedInventoryAuthorityV1(
            inventory_kind="artifacts",
            base_url=artifacts_url,
            items_key="artifacts",
            first_pages=(
                _list_page(artifacts_url, "artifacts", [artifact_item], at="2026-08-26T12:09:00Z"),
            ),
            stable_pages=(
                _list_page(artifacts_url, "artifacts", [artifact_item], at="2026-08-26T12:14:00Z"),
            ),
        ),
        direct_job_responses=(job_direct,),
        direct_artifact_responses=(artifact_direct,),
        storage_inventory_response=_cost_storage_inventory(),
        billing_baseline_response=_account_usage(
            inventory=False, at="2026-08-26T12:09:00Z", charge=0
        ),
        billing_post_response=_account_usage(
            inventory=False, at="2026-08-26T12:10:00Z", charge=charge
        ),
        billing_stable_response=_account_usage(
            inventory=False, at="2026-08-26T12:15:00Z", charge=charge
        ),
        cache_first_response=_cache_usage(at="2026-08-26T12:10:00Z"),
        cache_stable_response=_cache_usage(at="2026-08-26T12:15:00Z"),
        external_usage_responses=tuple(
            (kind, _external_usage(kind, charge=charge)) for kind in kinds
        ),
    )


def test_raw_authority_bundles_publish_explicit_integration_blockers() -> None:
    expected = {
        "admission": (
            "free_execution_billing_authority_unavailable",
            "free_execution_http_collector_not_integrated",
            "free_execution_manifest_artifact_collector_not_integrated",
            "free_execution_nonce_issuer_not_integrated",
            "free_execution_operation_registry_not_integrated",
            "free_execution_plan_artifact_job_provenance_not_integrated",
            "free_execution_run_job_context_collector_not_integrated",
            "free_execution_storage_inventory_collector_not_integrated",
            "free_execution_workflow_content_collector_not_integrated",
        ),
        "point": (
            "free_execution_point_predecessor_chain_collector_not_integrated",
            "free_execution_point_refresh_collector_not_integrated",
        ),
        "cost": (
            "free_execution_artifact_cache_size_collector_not_integrated",
            "free_execution_billing_authority_unavailable",
            "free_execution_cost_collector_not_integrated",
            "free_execution_external_operation_inventory_not_integrated",
            "free_execution_future_billing_liability_collector_not_integrated",
        ),
    }
    assert FreeExecutionAuthorityBundleV1.integration_blocker_codes == expected["admission"]
    assert PointOfUseAuthorityBundleV1.integration_blocker_codes == expected["point"]
    assert CostReadbackAuthorityBundleV1.integration_blocker_codes == expected["cost"]


def _charged_cost_readback() -> FreeExecutionCostReadbackV1:
    period_hours = 31 * 24
    return FreeExecutionCostReadbackV1(
        admission_sha256="a" * 64,
        authority_sha256="b" * 64,
        jobs_inventory_sha256="c" * 64,
        artifacts_inventory_sha256="d" * 64,
        jobs_total_count=0,
        artifacts_total_count=0,
        jobs=(),
        artifacts=(),
        external_services=(),
        billing_period_start="2026-08-01T00:00:00Z",
        billing_period_end="2026-09-01T00:00:00Z",
        billing_period_hours=period_hours,
        storage_existing_item_count=0,
        storage_current_bytes=0,
        storage_accrued_byte_hours=0,
        storage_existing_future_byte_hours=0,
        storage_free_byte_hours=ARTIFACT_PACKAGES_FREE_FLOOR_BYTES * period_hours,
        cache_current_bytes=0,
        billing_baseline_incremental_charge_microusd=0,
        billing_incremental_charge_microusd=7,
        maximum_incremental_charge_microusd=7,
        readback_at="2026-08-26T12:15:00Z",
        status=FreeExecutionCostReadbackStatus.CHARGED,
    )


def test_charged_readback_remains_representable_but_zero_green_is_blocked() -> None:
    charged = _charged_cost_readback()
    assert FreeExecutionCostReadbackV1.from_bytes(charged.to_bytes()) == charged
    with pytest.raises(FreeExecutionAdmissionError) as caught:
        replace(
            charged,
            billing_incremental_charge_microusd=0,
            maximum_incremental_charge_microusd=0,
            status=FreeExecutionCostReadbackStatus.VERIFIED_ZERO,
            readback_sha256="",
        )
    assert all(
        code in str(caught.value)
        for code in CostReadbackAuthorityBundleV1.integration_blocker_codes
    )


def test_paged_inventory_rejects_hidden_pages_unstable_repeats_and_missing_direct_receipts() -> (
    None
):
    authority = _cost_authority()
    jobs = authority.jobs_inventory
    hidden = replace(
        jobs,
        first_pages=(
            _list_page(
                jobs.base_url, "jobs", [_job_list_item()], at="2026-08-26T12:09:00Z", total=101
            ),
        ),
        stable_pages=(
            _list_page(
                jobs.base_url, "jobs", [_job_list_item()], at="2026-08-26T12:14:00Z", total=101
            ),
        ),
    )
    with pytest.raises(FreeExecutionAdmissionError, match="denominator"):
        hidden.derive()
    changed_item = {**_job_list_item(), "name": "Extract lane-1"}
    unstable = replace(
        jobs,
        stable_pages=(
            _list_page(jobs.base_url, "jobs", [changed_item], at="2026-08-26T12:14:00Z"),
        ),
    )
    with pytest.raises(FreeExecutionAdmissionError, match="stabilize"):
        unstable.derive()
    items, total, *_ = authority.artifacts_inventory.derive()
    assert len(items) == total == 1
