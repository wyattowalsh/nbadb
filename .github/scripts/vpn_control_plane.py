from __future__ import annotations

import argparse
import hashlib
import io
import ipaddress
import json
import os
import re
import stat
import sys
import tempfile
import time
import zipfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

GITHUB_API_VERSION = "2026-03-10"
GITHUB_API_ROOT = "https://api.github.com"
AUTH_CIRCUIT_KIND = "vpn_auth_circuit"
CAPACITY_MARKER_KIND = "vpn_capacity"
AUTH_CIRCUIT_OPEN_STATUS = "vpn_auth_circuit_open"
AUTH_CIRCUIT_CHECK_FAILED_STATUS = "vpn_auth_circuit_check_failed"
AUTH_CIRCUIT_CLOSED_STATUS = "closed"
DEFERRED_FAILURE_CLASS = "vpn_circuit_deferred"
DEFAULT_API_ATTEMPTS = 3
DEFAULT_REQUEST_TIMEOUT_SECONDS = 15.0
DEFAULT_RETRY_DELAY_SECONDS = 1.0
DEFAULT_WAIT_TIMEOUT_SECONDS = 120.0
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
MAX_ARTIFACT_PAGES = 100
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_MARKER_ARCHIVE_BYTES = 4 * 1024 * 1024
MAX_MARKER_JSON_BYTES = 64 * 1024
ARTIFACTS_PER_PAGE = 100
AUTH_MARKER_FILENAME = "auth-circuit-marker.json"

_ARTIFACT_COMPONENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_SHA_RE = re.compile(r"[0-9a-fA-F]{40}")
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")


class VpnControlPlaneError(RuntimeError):
    """Base class for expected, sanitized control-plane failures."""


class InputValidationError(VpnControlPlaneError):
    """Raised when required coordination input is invalid."""


class GitHubApiError(VpnControlPlaneError):
    """Raised when GitHub cannot provide a trustworthy artifact inventory."""


class ArtifactAmbiguityError(VpnControlPlaneError):
    """Raised when an exact artifact name has multiple live matches."""


class MarkerWaitTimeoutError(VpnControlPlaneError):
    """Raised when a bounded marker wait expires."""


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def _open_without_redirect(request: Request, *, timeout: float) -> Any:
    return build_opener(_NoRedirectHandler()).open(request, timeout=timeout)


def _required_text(value: object, field: str, *, maximum: int = 512) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise InputValidationError(f"{field} is required")
    normalized = str(value).strip()
    if not normalized:
        raise InputValidationError(f"{field} is required")
    if len(normalized) > maximum or any(ord(character) < 32 for character in normalized):
        raise InputValidationError(f"{field} is invalid")
    return normalized


def _artifact_component(value: object, field: str) -> str:
    normalized = _required_text(value, field, maximum=180)
    if _ARTIFACT_COMPONENT_RE.fullmatch(normalized) is None:
        raise InputValidationError(f"{field} is invalid")
    return normalized


def _repository(value: object) -> str:
    normalized = _required_text(value, "repository", maximum=200)
    if _REPOSITORY_RE.fullmatch(normalized) is None:
        raise InputValidationError("repository must use owner/name format")
    owner, name = normalized.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."}:
        raise InputValidationError("repository must use owner/name format")
    return normalized


def _integer(
    value: object,
    field: str,
    *,
    minimum: int,
    maximum: int = 2**63 - 1,
) -> int:
    if isinstance(value, bool):
        raise InputValidationError(f"{field} must be an integer")
    try:
        parsed = int(str(value).strip())
    except (AttributeError, TypeError, ValueError) as exc:
        raise InputValidationError(f"{field} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise InputValidationError(f"{field} is outside the allowed range")
    return parsed


def _number(
    value: object,
    field: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool):
        raise InputValidationError(f"{field} must be numeric")
    try:
        parsed = float(str(value).strip())
    except (AttributeError, TypeError, ValueError) as exc:
        raise InputValidationError(f"{field} must be numeric") from exc
    if not minimum <= parsed <= maximum:
        raise InputValidationError(f"{field} is outside the allowed range")
    return parsed


def _source_sha(value: object) -> str:
    normalized = _required_text(value, "source SHA").lower()
    if _SHA_RE.fullmatch(normalized) is None:
        raise InputValidationError("source SHA must contain 40 hexadecimal characters")
    return normalized


def _coverage_hash(value: object) -> str:
    normalized = _required_text(value, "coverage units hash").lower()
    if _SHA256_RE.fullmatch(normalized) is None:
        raise InputValidationError("coverage units hash must contain 64 hexadecimal characters")
    return normalized


def _env_value(
    env: Mapping[str, str],
    *names: str,
    default: str = "",
    required: bool = False,
) -> str:
    for name in names:
        value = env.get(name, "").strip()
        if value:
            return value
    if required:
        raise InputValidationError(f"{names[0]} is required")
    return default


def _argument_or_env(
    argument: object,
    env: Mapping[str, str],
    *names: str,
    default: str = "",
    required: bool = False,
) -> object:
    if argument not in (None, ""):
        return argument
    return _env_value(env, *names, default=default, required=required)


def _boolean_env(env: Mapping[str, str], name: str, *, default: bool = False) -> bool:
    raw = env.get(name, "").strip().lower()
    if not raw:
        return default
    if raw == "true":
        return True
    if raw == "false":
        return False
    raise InputValidationError(f"{name} must be true or false")


def _csv_env(env: Mapping[str, str], name: str) -> list[str]:
    return [item.strip() for item in env.get(name, "").split(",") if item.strip()]


def _json_list_env(env: Mapping[str, str], name: str) -> list[Any]:
    raw = env.get(name, "").strip() or "[]"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputValidationError(f"{name} must be a JSON array") from exc
    if not isinstance(payload, list):
        raise InputValidationError(f"{name} must be a JSON array")
    return payload


def _server_list(values: object, field: str) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise InputValidationError(f"{field} must be an array of server hostnames")
    servers: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise InputValidationError(f"{field} must contain only server hostnames")
        server = value.strip().lower()
        if not server or len(server) > 253 or any(ord(character) < 32 for character in server):
            raise InputValidationError(f"{field} contains an invalid server hostname")
        if server not in servers:
            servers.append(server)
    return servers


def _server_list_env(env: Mapping[str, str], name: str) -> list[str]:
    return _server_list(_json_list_env(env, name), name)


def auth_circuit_artifact_name(
    run_id: object,
    run_attempt: object,
) -> str:
    run = _integer(run_id, "run ID", minimum=1)
    attempt = _integer(run_attempt, "run attempt", minimum=1, maximum=1_000_000)
    return f"full-extraction-vpn-auth-circuit-run-{run}-attempt-{attempt}"


def capacity_marker_artifact_name(
    run_id: object,
    run_attempt: object,
    lane_index: object,
) -> str:
    run = _integer(run_id, "run ID", minimum=1)
    attempt = _integer(run_attempt, "run attempt", minimum=1, maximum=1_000_000)
    index = _integer(lane_index, "lane index", minimum=0, maximum=1_000_000)
    return f"vpn-capacity-connected-run-{run}-attempt-{attempt}-lane-{index}"


# Readable aliases for workflow callers and focused tests.
auth_circuit_marker_name = auth_circuit_artifact_name
capacity_marker_name = capacity_marker_artifact_name


def _github_token(token: str | None, env: Mapping[str, str]) -> str:
    candidate = token if token is not None else env.get("GH_TOKEN", "")
    normalized = candidate.strip()
    if not normalized or "\n" in normalized or "\r" in normalized:
        raise InputValidationError("GH_TOKEN is required")
    return normalized


def _artifact_api_url(
    repository: str,
    run_id: int,
    page: int,
    *,
    exact_name: str | None = None,
) -> str:
    owner, name = repository.split("/", 1)
    path = f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}/actions/runs/{run_id}/artifacts"
    query_values: dict[str, object] = {"per_page": ARTIFACTS_PER_PAGE, "page": page}
    if exact_name is not None:
        query_values["name"] = exact_name
    query = urlencode(query_values)
    return f"{GITHUB_API_ROOT}{path}?{query}"


def _artifact_archive_url(repository: str, artifact_id: int) -> str:
    owner, name = repository.split("/", 1)
    path = (
        f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}/actions/artifacts/{artifact_id}/zip"
    )
    return f"{GITHUB_API_ROOT}{path}"


def _response_status(response: Any) -> int | None:
    status = getattr(response, "status", None)
    if isinstance(status, int):
        return status
    getcode = getattr(response, "getcode", None)
    if callable(getcode):
        code = getcode()
        return code if isinstance(code, int) else None
    return None


def _decode_json_object(body: bytes) -> dict[str, Any]:
    if not isinstance(body, bytes):
        raise GitHubApiError("GitHub artifact API returned a non-byte response")
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GitHubApiError("GitHub artifact API returned invalid UTF-8") from exc
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise GitHubApiError("GitHub artifact API returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise GitHubApiError("GitHub artifact API response must be a JSON object")
    return payload


def _validate_artifact_page(payload: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    total_count = payload.get("total_count")
    if isinstance(total_count, bool) or not isinstance(total_count, int) or total_count < 0:
        raise GitHubApiError("GitHub artifact API total_count must be a non-negative integer")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        raise GitHubApiError("GitHub artifact API artifacts must be an array")

    validated: list[dict[str, Any]] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise GitHubApiError("GitHub artifact API artifact entries must be objects")
        name = artifact.get("name")
        expired = artifact.get("expired")
        if not isinstance(name, str) or not name:
            raise GitHubApiError("GitHub artifact API artifact names must be non-empty strings")
        if not isinstance(expired, bool):
            raise GitHubApiError("GitHub artifact API artifact expired flags must be booleans")
        artifact_id = artifact.get("id")
        if artifact_id is not None and (
            isinstance(artifact_id, bool) or not isinstance(artifact_id, int) or artifact_id < 1
        ):
            raise GitHubApiError("GitHub artifact API artifact ids must be positive integers")
        validated.append(dict(artifact))
    return total_count, validated


def _request_artifact_page(
    *,
    repository: str,
    run_id: int,
    page: int,
    exact_name: str | None,
    token: str,
    attempts: int,
    request_timeout_seconds: float,
    retry_delay_seconds: float,
    opener: Callable[..., Any],
    sleep: Callable[[float], None],
) -> dict[str, Any]:
    url = _artifact_api_url(repository, run_id, page, exact_name=exact_name)
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "nbadb-vpn-control-plane",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
        method="GET",
    )

    for attempt in range(1, attempts + 1):
        try:
            with closing(opener(request, timeout=request_timeout_seconds)) as response:
                status = _response_status(response)
                if status != 200:
                    if (
                        isinstance(status, int)
                        and (status == 429 or 500 <= status <= 599)
                        and attempt < attempts
                    ):
                        sleep(retry_delay_seconds * attempt)
                        continue
                    status_label = str(status) if isinstance(status, int) else "unknown"
                    raise GitHubApiError(
                        f"GitHub artifact API request failed with HTTP {status_label}"
                    )
                body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise GitHubApiError("GitHub artifact API response exceeded the size limit")
            return _decode_json_object(body)
        except HTTPError as exc:
            status = int(exc.code)
            exc.close()
            retryable = status == 429 or 500 <= status <= 599
            if retryable and attempt < attempts:
                sleep(retry_delay_seconds * attempt)
                continue
            raise GitHubApiError(f"GitHub artifact API request failed with HTTP {status}") from exc
        except (TimeoutError, URLError, OSError) as exc:
            if attempt < attempts:
                sleep(retry_delay_seconds * attempt)
                continue
            raise GitHubApiError(
                f"GitHub artifact API request failed after bounded retries ({type(exc).__name__})"
            ) from exc
    raise GitHubApiError("GitHub artifact API retry budget was exhausted")


def list_workflow_run_artifacts(
    *,
    repository: object,
    run_id: object,
    exact_name: object | None = None,
    token: str | None = None,
    env: Mapping[str, str] | None = None,
    attempts: object = DEFAULT_API_ATTEMPTS,
    request_timeout_seconds: object = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    retry_delay_seconds: object = DEFAULT_RETRY_DELAY_SECONDS,
    opener: Callable[..., Any] = _open_without_redirect,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    environment = os.environ if env is None else env
    normalized_repository = _repository(repository)
    normalized_run_id = _integer(run_id, "run ID", minimum=1)
    normalized_exact_name = (
        _required_text(exact_name, "artifact name") if exact_name is not None else None
    )
    normalized_token = _github_token(token, environment)
    normalized_attempts = _integer(attempts, "API attempts", minimum=1, maximum=10)
    normalized_request_timeout = _number(
        request_timeout_seconds,
        "request timeout seconds",
        minimum=0.1,
        maximum=120.0,
    )
    normalized_retry_delay = _number(
        retry_delay_seconds,
        "retry delay seconds",
        minimum=0.0,
        maximum=60.0,
    )

    inventory: list[dict[str, Any]] = []
    expected_total: int | None = None
    for page in range(1, MAX_ARTIFACT_PAGES + 1):
        payload = _request_artifact_page(
            repository=normalized_repository,
            run_id=normalized_run_id,
            page=page,
            exact_name=normalized_exact_name,
            token=normalized_token,
            attempts=normalized_attempts,
            request_timeout_seconds=normalized_request_timeout,
            retry_delay_seconds=normalized_retry_delay,
            opener=opener,
            sleep=sleep,
        )
        total_count, artifacts = _validate_artifact_page(payload)
        if expected_total is None:
            expected_total = total_count
        elif expected_total != total_count:
            raise GitHubApiError("GitHub artifact API total_count changed during pagination")
        inventory.extend(artifacts)
        if len(inventory) > total_count:
            raise GitHubApiError("GitHub artifact API returned more artifacts than total_count")
        if len(inventory) == total_count:
            return inventory
        if not artifacts:
            raise GitHubApiError("GitHub artifact API pagination ended before total_count")
    raise GitHubApiError("GitHub artifact API exceeded the pagination limit")


def exact_unexpired_artifact(
    artifacts: Sequence[Mapping[str, Any]],
    exact_name: object,
) -> dict[str, Any] | None:
    name = _required_text(exact_name, "artifact name")
    matches: list[dict[str, Any]] = []
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            raise GitHubApiError("artifact inventory entries must be objects")
        artifact_name = artifact.get("name")
        expired = artifact.get("expired")
        if not isinstance(artifact_name, str) or not isinstance(expired, bool):
            raise GitHubApiError("artifact inventory entries are invalid")
        if artifact_name == name and not expired:
            matches.append(dict(artifact))
    if len(matches) > 1:
        raise ArtifactAmbiguityError(
            "GitHub artifact inventory contains multiple unexpired exact-name matches"
        )
    return matches[0] if matches else None


def find_exact_workflow_run_artifact(
    *,
    exact_name: object,
    repository: object,
    run_id: object,
    **list_options: Any,
) -> dict[str, Any] | None:
    artifacts = list_workflow_run_artifacts(
        repository=repository,
        run_id=run_id,
        exact_name=exact_name,
        **list_options,
    )
    return exact_unexpired_artifact(artifacts, exact_name)


def _response_location(response: Any) -> str:
    headers = getattr(response, "headers", None)
    location = headers.get("Location") if headers is not None else None
    if not isinstance(location, str):
        raise GitHubApiError("GitHub artifact archive redirect did not include a location")
    normalized = location.strip()
    if len(normalized) > 8_192:
        raise GitHubApiError("GitHub artifact archive redirect location is invalid")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise GitHubApiError("GitHub artifact archive redirect location is invalid")
    return normalized


def _artifact_digest(value: object) -> str:
    if not isinstance(value, str):
        raise GitHubApiError("VPN authentication marker artifact digest is missing")
    normalized = value.strip().lower()
    if not normalized.startswith("sha256:") or _SHA256_RE.fullmatch(normalized[7:]) is None:
        raise GitHubApiError("VPN authentication marker artifact digest is invalid")
    return normalized


def _validated_auth_marker_artifact(
    artifact: Mapping[str, Any],
    *,
    repository: str,
    expected_name: str,
    run_id: int,
    workflow_head_sha: str,
) -> tuple[int, int, str]:
    if artifact.get("name") != expected_name or artifact.get("expired") is not False:
        raise GitHubApiError("VPN authentication marker artifact identity is invalid")
    artifact_id = artifact.get("id")
    if type(artifact_id) is not int or artifact_id < 1:
        raise GitHubApiError("VPN authentication marker artifact ID is invalid")
    size_in_bytes = artifact.get("size_in_bytes")
    if (
        isinstance(size_in_bytes, bool)
        or not isinstance(size_in_bytes, int)
        or not 0 < size_in_bytes <= MAX_MARKER_ARCHIVE_BYTES
    ):
        raise GitHubApiError("VPN authentication marker artifact size is invalid")
    if artifact.get("archive_download_url") != _artifact_archive_url(repository, artifact_id):
        raise GitHubApiError("VPN authentication marker artifact download URL is invalid")
    workflow_run = artifact.get("workflow_run")
    if not isinstance(workflow_run, Mapping):
        raise GitHubApiError("VPN authentication marker workflow provenance is missing")
    if type(workflow_run.get("id")) is not int or workflow_run["id"] != run_id:
        raise GitHubApiError("VPN authentication marker workflow run does not match")
    head_sha = workflow_run.get("head_sha")
    if not isinstance(head_sha, str) or head_sha.lower() != workflow_head_sha:
        raise GitHubApiError("VPN authentication marker workflow head SHA does not match")
    return artifact_id, size_in_bytes, _artifact_digest(artifact.get("digest"))


def _request_artifact_archive(
    *,
    repository: str,
    artifact_id: int,
    token: str,
    attempts: int,
    request_timeout_seconds: float,
    retry_delay_seconds: float,
    api_opener: Callable[..., Any],
    content_opener: Callable[..., Any],
    sleep: Callable[[float], None],
) -> bytes:
    request = Request(
        _artifact_archive_url(repository, artifact_id),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "nbadb-vpn-control-plane",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
        method="GET",
    )
    for attempt in range(1, attempts + 1):
        try:
            try:
                response_context = api_opener(request, timeout=request_timeout_seconds)
            except HTTPError as exc:
                if int(exc.code) != 302:
                    raise
                try:
                    signed_url = _response_location(exc)
                finally:
                    exc.close()
            else:
                with closing(response_context) as response:
                    status = _response_status(response)
                    if status == 302:
                        signed_url = _response_location(response)
                    else:
                        if (
                            isinstance(status, int)
                            and (status == 429 or 500 <= status <= 599)
                            and attempt < attempts
                        ):
                            sleep(retry_delay_seconds * attempt)
                            continue
                        status_label = str(status) if isinstance(status, int) else "unknown"
                        raise GitHubApiError(
                            "GitHub artifact archive redirect request failed with HTTP "
                            f"{status_label}"
                        )

            content_request = Request(
                signed_url,
                headers={
                    "Accept": "application/zip",
                    "User-Agent": "nbadb-vpn-control-plane",
                },
                method="GET",
            )
            with closing(
                content_opener(content_request, timeout=request_timeout_seconds)
            ) as response:
                status = _response_status(response)
                if status != 200:
                    if (
                        isinstance(status, int)
                        and (status == 429 or 500 <= status <= 599)
                        and attempt < attempts
                    ):
                        sleep(retry_delay_seconds * attempt)
                        continue
                    status_label = str(status) if isinstance(status, int) else "unknown"
                    raise GitHubApiError(
                        f"GitHub artifact content request failed with HTTP {status_label}"
                    )
                body = response.read(MAX_MARKER_ARCHIVE_BYTES + 1)
            if len(body) > MAX_MARKER_ARCHIVE_BYTES:
                raise GitHubApiError("GitHub artifact archive exceeded the size limit")
            return body
        except HTTPError as exc:
            status = int(exc.code)
            exc.close()
            retryable = status == 429 or 500 <= status <= 599
            if retryable and attempt < attempts:
                sleep(retry_delay_seconds * attempt)
                continue
            raise GitHubApiError(
                f"GitHub artifact archive request failed with HTTP {status}"
            ) from exc
        except (TimeoutError, URLError, OSError) as exc:
            if attempt < attempts:
                sleep(retry_delay_seconds * attempt)
                continue
            raise GitHubApiError(
                "GitHub artifact archive request failed after bounded retries "
                f"({type(exc).__name__})"
            ) from exc
    raise GitHubApiError("GitHub artifact archive retry budget was exhausted")


def _marker_payload_from_archive(body: bytes) -> dict[str, Any]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(body))
    except (OSError, zipfile.BadZipFile) as exc:
        raise GitHubApiError(
            "VPN authentication marker artifact is not a valid ZIP archive"
        ) from exc
    with archive:
        entries = archive.infolist()
        if len(entries) != 1:
            raise GitHubApiError(
                "VPN authentication marker artifact must contain exactly one regular file"
            )
        entry = entries[0]
        path = PurePosixPath(entry.filename)
        entry_mode = (entry.external_attr >> 16) & 0xFFFF
        entry_type = stat.S_IFMT(entry_mode)
        if (
            entry.is_dir()
            or bool(entry.flag_bits & 0x1)
            or path.is_absolute()
            or ".." in path.parts
            or entry.filename != AUTH_MARKER_FILENAME
            or entry_type not in {0, stat.S_IFREG}
            or entry.file_size > MAX_MARKER_JSON_BYTES
            or entry.compress_size > MAX_MARKER_ARCHIVE_BYTES
        ):
            raise GitHubApiError("VPN authentication marker artifact path or size is invalid")
        try:
            marker_body = archive.read(entry)
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise GitHubApiError("VPN authentication marker artifact could not be read") from exc
        if len(marker_body) > MAX_MARKER_JSON_BYTES:
            raise GitHubApiError("VPN authentication marker artifact path or size is invalid")
    return _decode_json_object(marker_body)


def load_auth_marker_artifact(
    artifact: Mapping[str, Any],
    *,
    repository: object,
    expected_name: object,
    run_id: object,
    workflow_head_sha: object,
    token: str | None = None,
    env: Mapping[str, str] | None = None,
    attempts: object = DEFAULT_API_ATTEMPTS,
    request_timeout_seconds: object = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    retry_delay_seconds: object = DEFAULT_RETRY_DELAY_SECONDS,
    api_opener: Callable[..., Any] = _open_without_redirect,
    content_opener: Callable[..., Any] = urlopen,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    environment = os.environ if env is None else env
    if not isinstance(artifact, Mapping):
        raise GitHubApiError("VPN authentication marker artifact metadata must be an object")
    normalized_repository = _repository(repository)
    normalized_name = _required_text(expected_name, "artifact name")
    normalized_run_id = _integer(run_id, "run ID", minimum=1)
    normalized_workflow_head_sha = _source_sha(workflow_head_sha)
    artifact_id, expected_size, expected_digest = _validated_auth_marker_artifact(
        artifact,
        repository=normalized_repository,
        expected_name=normalized_name,
        run_id=normalized_run_id,
        workflow_head_sha=normalized_workflow_head_sha,
    )
    body = _request_artifact_archive(
        repository=normalized_repository,
        artifact_id=artifact_id,
        token=_github_token(token, environment),
        attempts=_integer(attempts, "API attempts", minimum=1, maximum=10),
        request_timeout_seconds=_number(
            request_timeout_seconds,
            "request timeout seconds",
            minimum=0.1,
            maximum=120.0,
        ),
        retry_delay_seconds=_number(
            retry_delay_seconds,
            "retry delay seconds",
            minimum=0.0,
            maximum=60.0,
        ),
        api_opener=api_opener,
        content_opener=content_opener,
        sleep=sleep,
    )
    actual_digest = f"sha256:{hashlib.sha256(body).hexdigest()}"
    if len(body) != expected_size:
        raise GitHubApiError("VPN authentication marker artifact size does not match")
    if actual_digest != expected_digest:
        raise GitHubApiError("VPN authentication marker artifact digest does not match")
    return _marker_payload_from_archive(body)


def _wait_until(
    check: Callable[[], Any | None],
    *,
    description: str,
    timeout_seconds: object,
    poll_interval_seconds: object,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> Any:
    timeout = _number(
        timeout_seconds,
        "wait timeout seconds",
        minimum=0.0,
        maximum=3_600.0,
    )
    interval = _number(
        poll_interval_seconds,
        "poll interval seconds",
        minimum=0.01,
        maximum=300.0,
    )
    deadline = clock() + timeout
    while True:
        result = check()
        if result is not None:
            return result
        remaining = deadline - clock()
        if remaining <= 0:
            raise MarkerWaitTimeoutError(f"timed out waiting for {description}")
        sleep(min(interval, remaining))


def wait_for_auth_marker(
    *,
    run_id: object,
    run_attempt: object,
    artifact_lookup: Callable[[str], dict[str, Any] | None],
    artifact_validator: Callable[[dict[str, Any]], Any] | None = None,
    timeout_seconds: object = DEFAULT_WAIT_TIMEOUT_SECONDS,
    poll_interval_seconds: object = DEFAULT_POLL_INTERVAL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    name = auth_circuit_artifact_name(run_id, run_attempt)

    def check() -> dict[str, Any] | None:
        artifact = artifact_lookup(name)
        if artifact is not None and artifact_validator is not None:
            artifact_validator(artifact)
        return artifact

    return _wait_until(
        check,
        description="the VPN authentication circuit marker",
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        clock=clock,
        sleep=sleep,
    )


def wait_for_capacity_markers(
    *,
    run_id: object,
    run_attempt: object,
    expected: object,
    artifact_lister: Callable[[], Sequence[Mapping[str, Any]]],
    timeout_seconds: object = DEFAULT_WAIT_TIMEOUT_SECONDS,
    poll_interval_seconds: object = DEFAULT_POLL_INTERVAL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[int, dict[str, Any]]:
    count = _integer(expected, "expected capacity", minimum=0, maximum=256)
    expected_names = {
        index: capacity_marker_artifact_name(run_id, run_attempt, index) for index in range(count)
    }
    if not expected_names:
        return {}

    def check() -> dict[int, dict[str, Any]] | None:
        inventory = artifact_lister()
        found: dict[int, dict[str, Any]] = {}
        for index, name in expected_names.items():
            artifact = exact_unexpired_artifact(inventory, name)
            if artifact is None:
                return None
            found[index] = artifact
        return found

    return _wait_until(
        check,
        description=f"{count} VPN capacity markers",
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        clock=clock,
        sleep=sleep,
    )


def append_github_output(path: Path, key: str, value: str) -> None:
    if not key or "\n" in key or "\r" in key or "=" in key:
        raise InputValidationError("GitHub output key is invalid")
    if "\n" in value or "\r" in value:
        raise InputValidationError("GitHub output value is invalid")
    if not path.parent.is_dir():
        raise InputValidationError("GITHUB_OUTPUT parent directory does not exist")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{key}={value}\n")


def auth_guard(
    *,
    artifact_name: str,
    artifact_lookup: Callable[[str], dict[str, Any] | None],
    artifact_validator: Callable[[dict[str, Any]], Any] | None = None,
    output_path: Path,
    stderr: Any = sys.stderr,
) -> int:
    try:
        artifact = artifact_lookup(artifact_name)
    except Exception:  # The output must remain secret-free even for injected failures.
        append_github_output(output_path, "status", AUTH_CIRCUIT_CHECK_FAILED_STATUS)
        print("VPN authentication circuit check failed", file=stderr)
        return 1
    if artifact is not None:
        try:
            if artifact_validator is not None:
                artifact_validator(artifact)
        except Exception:
            append_github_output(output_path, "status", AUTH_CIRCUIT_CHECK_FAILED_STATUS)
            print("VPN authentication circuit marker validation failed", file=stderr)
            return 1
        append_github_output(output_path, "status", AUTH_CIRCUIT_OPEN_STATUS)
        print("VPN authentication circuit is open", file=stderr)
        return 1
    append_github_output(output_path, "status", AUTH_CIRCUIT_CLOSED_STATUS)
    return 0


def _normalize_marker_kind(value: object) -> str:
    normalized = _required_text(value, "marker kind").lower().replace("-", "_")
    aliases = {
        "auth": AUTH_CIRCUIT_KIND,
        "auth_circuit": AUTH_CIRCUIT_KIND,
        AUTH_CIRCUIT_KIND: AUTH_CIRCUIT_KIND,
        "capacity": CAPACITY_MARKER_KIND,
        "capacity_marker": CAPACITY_MARKER_KIND,
        CAPACITY_MARKER_KIND: CAPACITY_MARKER_KIND,
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise InputValidationError("marker kind must be auth-circuit or capacity") from exc


def _canonical_timestamp(value: str | None, now: Callable[[], datetime]) -> str:
    if value:
        candidate = value.strip()
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError as exc:
            raise InputValidationError("timestamp must be an RFC 3339 value") from exc
        if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
            raise InputValidationError("timestamp must use UTC")
    else:
        parsed = now()
        if parsed.tzinfo is None:
            raise InputValidationError("clock must return a timezone-aware datetime")
        parsed = parsed.astimezone(UTC)
    return parsed.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_marker_payload(
    *,
    kind: object,
    repository: object,
    chain_id: object,
    source_sha: object,
    run_id: object,
    run_attempt: object,
    lane_id: object,
    lane_index: object,
    auth_source: object,
    vpn_status: object,
    vpn_server: object,
    vpn_exit_ip: object = "",
    attempted_servers: object = (),
    failed_servers: object = (),
    timestamp: str | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    normalized_kind = _normalize_marker_kind(kind)
    normalized_server = str(vpn_server).strip()
    if normalized_kind == CAPACITY_MARKER_KIND and not normalized_server:
        raise InputValidationError("VPN server is required for a capacity marker")
    if len(normalized_server) > 253 or any(ord(character) < 32 for character in normalized_server):
        raise InputValidationError("VPN server is invalid")
    normalized_exit_ip = str(vpn_exit_ip).strip()
    if normalized_exit_ip:
        try:
            ipaddress.ip_address(normalized_exit_ip)
        except ValueError as exc:
            raise InputValidationError("VPN exit IP is invalid") from exc
    normalized_attempted_servers = _server_list(attempted_servers, "attempted servers")
    normalized_failed_servers = _server_list(failed_servers, "failed servers")
    if normalized_server:
        normalized_server = normalized_server.lower()
    if (
        normalized_kind == CAPACITY_MARKER_KIND
        and normalized_server not in normalized_attempted_servers
    ):
        raise InputValidationError("capacity marker server must be present in attempted servers")
    if not set(normalized_failed_servers).issubset(normalized_attempted_servers):
        raise InputValidationError("failed servers must be present in attempted servers")
    return {
        "schema_version": 1,
        "kind": normalized_kind,
        "repository": _repository(repository),
        "chain_id": _artifact_component(chain_id, "chain ID"),
        "source_sha": _source_sha(source_sha),
        "run_id": str(_integer(run_id, "run ID", minimum=1)),
        "run_attempt": _integer(run_attempt, "run attempt", minimum=1, maximum=1_000_000),
        "lane_id": _artifact_component(lane_id, "lane ID"),
        "lane_index": _integer(lane_index, "lane index", minimum=0, maximum=1_000_000),
        "auth_source": _required_text(auth_source, "auth source", maximum=100),
        "vpn_status": _required_text(vpn_status, "VPN status", maximum=100),
        "vpn_server": normalized_server,
        "vpn_exit_ip": normalized_exit_ip,
        "attempted_servers": normalized_attempted_servers,
        "failed_servers": normalized_failed_servers,
        "created_at": _canonical_timestamp(timestamp, now),
    }


def validate_auth_marker_payload(
    payload: Mapping[str, Any],
    *,
    repository: object,
    chain_id: object,
    source_sha: object,
    run_id: object,
    run_attempt: object,
    auth_source: object,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise InputValidationError("VPN authentication marker must be a JSON object")
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        raise InputValidationError("VPN authentication marker schema version is invalid")
    required_fields = {
        "schema_version",
        "kind",
        "repository",
        "chain_id",
        "source_sha",
        "run_id",
        "run_attempt",
        "lane_id",
        "lane_index",
        "auth_source",
        "vpn_status",
        "vpn_server",
        "vpn_exit_ip",
        "attempted_servers",
        "failed_servers",
        "created_at",
    }
    if set(payload) != required_fields:
        raise InputValidationError("VPN authentication marker fields are invalid")
    canonical = build_marker_payload(
        kind=payload.get("kind"),
        repository=payload.get("repository"),
        chain_id=payload.get("chain_id"),
        source_sha=payload.get("source_sha"),
        run_id=payload.get("run_id"),
        run_attempt=payload.get("run_attempt"),
        lane_id=payload.get("lane_id"),
        lane_index=payload.get("lane_index"),
        auth_source=payload.get("auth_source"),
        vpn_status=payload.get("vpn_status"),
        vpn_server=payload.get("vpn_server"),
        vpn_exit_ip=payload.get("vpn_exit_ip"),
        attempted_servers=payload.get("attempted_servers"),
        failed_servers=payload.get("failed_servers"),
        timestamp=str(payload.get("created_at") or ""),
    )
    if dict(payload) != canonical:
        raise InputValidationError("VPN authentication marker is not canonical")
    expected = {
        "kind": AUTH_CIRCUIT_KIND,
        "repository": _repository(repository),
        "chain_id": _artifact_component(chain_id, "chain ID"),
        "source_sha": _source_sha(source_sha),
        "run_id": str(_integer(run_id, "run ID", minimum=1)),
        "run_attempt": _integer(
            run_attempt,
            "run attempt",
            minimum=1,
            maximum=1_000_000,
        ),
        "auth_source": _required_text(auth_source, "auth source", maximum=100),
        "vpn_status": "vpn_auth_failure",
    }
    mismatches = [field for field, value in expected.items() if canonical.get(field) != value]
    if mismatches:
        raise InputValidationError(
            "VPN authentication marker provenance mismatch: " + ",".join(sorted(mismatches))
        )
    return canonical


def _load_marker(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise InputValidationError("capacity marker must be a regular file")
    if path.stat().st_size > MAX_RESPONSE_BYTES:
        raise InputValidationError("capacity marker exceeded the size limit")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputValidationError("capacity marker is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise InputValidationError("capacity marker must be a JSON object")
    return payload


def aggregate_vpn_quarantine(
    *,
    marker_directory: Path,
    expected_capacity: object,
    repository: object,
    chain_id: object,
    source_sha: object,
    run_id: object,
    run_attempt: object,
    baseline_servers: object,
    discovery_failed_servers: object,
) -> dict[str, Any]:
    expected = _integer(expected_capacity, "expected capacity", minimum=0, maximum=256)
    normalized_repository = _repository(repository)
    normalized_chain_id = _artifact_component(chain_id, "chain ID")
    normalized_source_sha = _source_sha(source_sha)
    normalized_run_id = _integer(run_id, "run ID", minimum=1)
    normalized_run_attempt = _integer(
        run_attempt,
        "run attempt",
        minimum=1,
        maximum=1_000_000,
    )
    baseline = _server_list(baseline_servers, "baseline quarantine")
    discovery = _server_list(discovery_failed_servers, "discovery failed servers")
    marker_paths = (
        sorted(marker_directory.rglob("capacity-marker.json")) if marker_directory.is_dir() else []
    )
    if len(marker_paths) != expected:
        raise InputValidationError(
            f"expected {expected} capacity marker files but found {len(marker_paths)}"
        )

    expected_keys = {
        "schema_version",
        "kind",
        "repository",
        "chain_id",
        "source_sha",
        "run_id",
        "run_attempt",
        "lane_id",
        "lane_index",
        "auth_source",
        "vpn_status",
        "vpn_server",
        "vpn_exit_ip",
        "attempted_servers",
        "failed_servers",
        "created_at",
    }
    markers: dict[int, dict[str, Any]] = {}
    successful_servers: dict[str, int] = {}
    for path in marker_paths:
        payload = _load_marker(path)
        if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
            raise InputValidationError("capacity marker schema version is invalid")
        if set(payload) != expected_keys:
            raise InputValidationError("capacity marker schema is invalid")
        canonical = build_marker_payload(
            kind=payload.get("kind"),
            repository=payload.get("repository"),
            chain_id=payload.get("chain_id"),
            source_sha=payload.get("source_sha"),
            run_id=payload.get("run_id"),
            run_attempt=payload.get("run_attempt"),
            lane_id=payload.get("lane_id"),
            lane_index=payload.get("lane_index"),
            auth_source=payload.get("auth_source"),
            vpn_status=payload.get("vpn_status"),
            vpn_server=payload.get("vpn_server"),
            vpn_exit_ip=payload.get("vpn_exit_ip"),
            attempted_servers=payload.get("attempted_servers"),
            failed_servers=payload.get("failed_servers"),
            timestamp=str(payload.get("created_at") or ""),
        )
        if dict(payload) != canonical:
            raise InputValidationError("capacity marker is not canonical")
        lane_index = _integer(
            canonical["lane_index"],
            "capacity marker lane index",
            minimum=0,
            maximum=255,
        )
        if lane_index in markers:
            raise InputValidationError("capacity marker lane indexes must be unique")
        attempted = canonical["attempted_servers"]
        failed = canonical["failed_servers"]
        server = _required_text(canonical["vpn_server"], "capacity VPN server", maximum=253)
        exit_ip = _required_text(canonical["vpn_exit_ip"], "capacity VPN exit IP", maximum=45)
        try:
            ipaddress.ip_address(exit_ip)
        except ValueError as exc:
            raise InputValidationError("capacity VPN exit IP is invalid") from exc
        if server not in attempted or not set(failed).issubset(attempted):
            raise InputValidationError("capacity marker server inventory is inconsistent")
        if server in failed:
            raise InputValidationError("capacity marker successful server is also marked failed")
        if server in successful_servers:
            raise InputValidationError(
                "capacity markers must attest distinct successful VPN servers: "
                f"lanes {successful_servers[server]} and {lane_index} both selected {server}"
            )
        expected_artifact_name = capacity_marker_artifact_name(
            normalized_run_id,
            normalized_run_attempt,
            lane_index,
        )
        expected_marker_path = marker_directory / expected_artifact_name / "capacity-marker.json"
        if path != expected_marker_path:
            raise InputValidationError("capacity marker artifact name does not match its lane")
        exact_values = {
            "schema_version": 1,
            "kind": CAPACITY_MARKER_KIND,
            "repository": normalized_repository,
            "chain_id": normalized_chain_id,
            "source_sha": normalized_source_sha,
            "run_id": str(normalized_run_id),
            "run_attempt": normalized_run_attempt,
            "lane_id": f"capacity-{lane_index}",
            "auth_source": "configured",
            "vpn_status": "connected",
        }
        for key, expected_value in exact_values.items():
            if canonical[key] != expected_value:
                raise InputValidationError(f"capacity marker {key} does not match this attempt")
        successful_servers[server] = lane_index
        markers[lane_index] = {"server": server, "failed_servers": failed}

    if set(markers) != set(range(expected)):
        raise InputValidationError("capacity markers do not cover every expected lane index")

    combined: list[str] = []
    for server in [*baseline, *discovery]:
        if server not in combined:
            combined.append(server)
    for lane_index in sorted(markers):
        for server in markers[lane_index]["failed_servers"]:
            if server not in combined:
                combined.append(server)
    return {
        "schema_version": 1,
        "repository": normalized_repository,
        "chain_id": normalized_chain_id,
        "source_sha": normalized_source_sha,
        "run_id": str(normalized_run_id),
        "run_attempt": normalized_run_attempt,
        "expected_capacity": expected,
        "capacity_marker_count": len(markers),
        "vpn_quarantined_servers": combined,
    }


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def write_json_atomically(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(_canonical_json(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    if path.is_symlink() or not path.is_file():
        raise VpnControlPlaneError("atomic JSON output is not a regular file")


def _zero_progress_fingerprint() -> str:
    body = json.dumps(
        {"completed_calls": 0, "rows_persisted": 0},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def build_deferred_metadata(
    env: Mapping[str, str],
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    chain_id = _artifact_component(
        _env_value(env, "CHAIN_ID", "ACTIVE_CHAIN_ID", required=True),
        "chain ID",
    )
    iteration = _integer(_env_value(env, "ITERATION", required=True), "iteration", minimum=1)
    lane_id = _artifact_component(_env_value(env, "LANE_ID", required=True), "lane ID")
    lane_index = _integer(
        _env_value(env, "LANE_INDEX", required=True),
        "lane index",
        minimum=0,
        maximum=1_000_000,
    )
    lane_name = _required_text(_env_value(env, "NAME", "LANE_NAME", required=True), "lane name")
    lane_kind = _required_text(_env_value(env, "KIND", "LANE_KIND", required=True), "lane kind")
    source_ref = _required_text(
        _env_value(env, "SOURCE_REF", "WORKFLOW_SOURCE_REF", required=True), "source ref"
    )
    source_sha = _source_sha(_env_value(env, "SOURCE_SHA", "WORKFLOW_SOURCE_SHA", required=True))
    coverage_units_hash = _coverage_hash(_env_value(env, "COVERAGE_UNITS_HASH", required=True))
    finished_at = _canonical_timestamp(env.get("FINISHED_AT") or None, now)
    timeout_seconds = _integer(
        _env_value(env, "TIMEOUT_SECONDS", default="0"),
        "timeout seconds",
        minimum=0,
    )
    effective_timeout_seconds = _integer(
        _env_value(
            env,
            "EFFECTIVE_TIMEOUT_SECONDS",
            default=str(timeout_seconds),
        ),
        "effective timeout seconds",
        minimum=0,
    )
    split_generation = _integer(
        _env_value(env, "SPLIT_GENERATION", default="0"),
        "split generation",
        minimum=0,
    )
    attempted_servers = _json_list_env(env, "VPN_ATTEMPTED_SERVERS_JSON")
    failed_servers = _json_list_env(env, "VPN_FAILED_SERVERS_JSON")
    auth_source = _env_value(env, "VPN_AUTH_SOURCE", "AUTH_SOURCE")
    network_mode = _env_value(env, "NETWORK_MODE", default="vpn")
    effective_network_mode = _env_value(env, "EFFECTIVE_NETWORK_MODE", default="vpn")
    circuit_status = _env_value(
        env,
        "VPN_AUTH_CIRCUIT_STATUS",
        default=AUTH_CIRCUIT_OPEN_STATUS,
    )
    if circuit_status not in {
        AUTH_CIRCUIT_OPEN_STATUS,
        AUTH_CIRCUIT_CHECK_FAILED_STATUS,
    }:
        raise InputValidationError("VPN_AUTH_CIRCUIT_STATUS is invalid")
    failure_class = (
        DEFERRED_FAILURE_CLASS
        if circuit_status == AUTH_CIRCUIT_OPEN_STATUS
        else "runner_infrastructure"
    )

    return {
        "metadata_schema_version": 3,
        "chain_id": chain_id,
        "iteration": str(iteration),
        "lane_id": lane_id,
        "lane_index": str(lane_index),
        "lane_name": lane_name,
        "lane_kind": lane_kind,
        "source_ref": source_ref,
        "source_sha": source_sha,
        "coverage_units_hash": coverage_units_hash,
        "database_sha256": "",
        "expected_empty": False,
        "workload_contract": None,
        "workload_contract_error": "",
        "status": "needs_resume",
        "raw_status": circuit_status,
        "cache_hit": _env_value(env, "CACHE_HIT", default="false"),
        "restore_source": _env_value(env, "RESTORE_SOURCE", default="none"),
        "restore_usable": _boolean_env(env, "RESTORE_USABLE", default=False),
        "restart_mode": _env_value(env, "RESTART_MODE", default="clean-restart"),
        "restore_error": _env_value(env, "RESTORE_ERROR"),
        "resume_only": _boolean_env(env, "RESUME_ONLY", default=False),
        "timeout_seconds": timeout_seconds,
        "effective_timeout_seconds": effective_timeout_seconds,
        "started_at": _env_value(env, "STARTED_AT"),
        "finished_at": finished_at,
        "extract_status": "not-run",
        "extract_exit_code": "",
        "network_mode": network_mode,
        "effective_network_mode": effective_network_mode,
        "direct_egress_reason": _env_value(env, "DIRECT_EGRESS_REASON"),
        "vpn_status": circuit_status,
        "patterns": _csv_env(env, "PATTERNS"),
        "season_types": _csv_env(env, "SEASON_TYPES"),
        "endpoints": _csv_env(env, "ENDPOINTS"),
        "context_measures": _csv_env(env, "CONTEXT_MEASURES"),
        "season_start": env.get("SEASON_START", "").strip(),
        "season_end": env.get("SEASON_END", "").strip(),
        "parent_lane_id": env.get("PARENT_LANE_ID", "").strip(),
        "split_generation": split_generation,
        "support_rules": [],
        "failure_class": failure_class,
        "failure_class_counts": {failure_class: 1},
        "root_error_type": "",
        "root_error_type_counts": {},
        "progress": {
            "completed_calls": 0,
            "rows_persisted": 0,
            "fingerprint": _zero_progress_fingerprint(),
        },
        "state_artifact": {
            "run_id": "",
            "name": "",
            "sha256": "",
            "artifact_id": "",
            "artifact_digest": "",
            "required": False,
            "attested": False,
            "uploaded": False,
        },
        "artifact_requirements": {
            "lane_metadata": True,
            "vpn_diagnostics": False,
        },
        "telemetry": {
            "planned_calls": 0,
            "journal_skips": 0,
            "failed_calls": 0,
            "completed_calls": 0,
            "tables_persisted": 0,
            "rows_persisted": 0,
            "zero_row_reason": circuit_status,
            "circuit_breaker_endpoints": [],
            "rate_degradation_events": [],
            "extract_summary_parse_error": "",
            "completion_evidence_errors": [],
            "workload_contract_error": "",
            "db_telemetry": {
                "planned_calls": 0,
                "journal_skips": 0,
                "failed_calls": 0,
                "running_calls": 0,
                "completed_calls": 0,
                "tables_persisted": 0,
                "rows_persisted": 0,
            },
        },
        "extract_summary": {},
        "vpn": {
            "status": circuit_status,
            "auth_source": auth_source,
            "server": _env_value(env, "VPN_SERVER"),
            "interface": _env_value(env, "VPN_INTERFACE"),
            "exit_ip": _env_value(env, "VPN_EXIT_IP"),
            "attempted_servers": attempted_servers,
            "failed_servers": failed_servers,
        },
    }


def _common_coordination_values(
    args: argparse.Namespace,
    env: Mapping[str, str],
) -> tuple[str, int, int]:
    repository = _repository(
        _argument_or_env(args.repository, env, "GITHUB_REPOSITORY", required=True)
    )
    run_id = _integer(
        _argument_or_env(args.run_id, env, "GITHUB_RUN_ID", required=True),
        "run ID",
        minimum=1,
    )
    run_attempt = _integer(
        _argument_or_env(args.run_attempt, env, "GITHUB_RUN_ATTEMPT", required=True),
        "run attempt",
        minimum=1,
        maximum=1_000_000,
    )
    return repository, run_id, run_attempt


def _api_options(args: argparse.Namespace, env: Mapping[str, str]) -> dict[str, Any]:
    return {
        "env": env,
        "attempts": _argument_or_env(
            args.api_attempts,
            env,
            "VPN_CONTROL_API_ATTEMPTS",
            default=str(DEFAULT_API_ATTEMPTS),
        ),
        "request_timeout_seconds": _argument_or_env(
            args.request_timeout_seconds,
            env,
            "VPN_CONTROL_REQUEST_TIMEOUT_SECONDS",
            default=str(DEFAULT_REQUEST_TIMEOUT_SECONDS),
        ),
        "retry_delay_seconds": _argument_or_env(
            args.retry_delay_seconds,
            env,
            "VPN_CONTROL_RETRY_DELAY_SECONDS",
            default=str(DEFAULT_RETRY_DELAY_SECONDS),
        ),
    }


def _wait_options(
    args: argparse.Namespace,
    env: Mapping[str, str],
    *,
    timeout_names: Sequence[str],
) -> dict[str, object]:
    return {
        "timeout_seconds": _argument_or_env(
            args.timeout_seconds,
            env,
            *timeout_names,
            default=str(DEFAULT_WAIT_TIMEOUT_SECONDS),
        ),
        "poll_interval_seconds": _argument_or_env(
            args.poll_interval_seconds,
            env,
            "VPN_CONTROL_POLL_INTERVAL_SECONDS",
            "POLL_INTERVAL_SECONDS",
            default=str(DEFAULT_POLL_INTERVAL_SECONDS),
        ),
    }


def _auth_marker_validator(
    args: argparse.Namespace,
    env: Mapping[str, str],
    *,
    repository: str,
    run_id: int,
    run_attempt: int,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    chain_id = _argument_or_env(
        getattr(args, "chain_id", None),
        env,
        "CHAIN_ID",
        "ACTIVE_CHAIN_ID",
        required=True,
    )
    source_sha = _argument_or_env(
        getattr(args, "source_sha", None),
        env,
        "SOURCE_SHA",
        "WORKFLOW_SOURCE_SHA",
        required=True,
    )
    workflow_head_sha = _argument_or_env(
        getattr(args, "workflow_head_sha", None),
        env,
        "GITHUB_SHA",
        required=True,
    )
    auth_source = _argument_or_env(
        getattr(args, "auth_source", None),
        env,
        "VPN_AUTH_SOURCE",
        "AUTH_SOURCE",
        required=True,
    )
    api_options = _api_options(args, env)

    def validate(artifact: dict[str, Any]) -> dict[str, Any]:
        payload = load_auth_marker_artifact(
            artifact,
            repository=repository,
            expected_name=auth_circuit_artifact_name(run_id, run_attempt),
            run_id=run_id,
            workflow_head_sha=workflow_head_sha,
            **api_options,
        )
        return validate_auth_marker_payload(
            payload,
            repository=repository,
            chain_id=chain_id,
            source_sha=source_sha,
            run_id=run_id,
            run_attempt=run_attempt,
            auth_source=auth_source,
        )

    return validate


def _command_auth_guard(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    repository, run_id, run_attempt = _common_coordination_values(args, env)
    name = auth_circuit_artifact_name(run_id, run_attempt)
    output_path = Path(
        _required_text(
            _argument_or_env(args.output, env, "GITHUB_OUTPUT", required=True),
            "GITHUB_OUTPUT",
            maximum=4_096,
        )
    )

    def lookup(exact_name: str) -> dict[str, Any] | None:
        return find_exact_workflow_run_artifact(
            exact_name=exact_name,
            repository=repository,
            run_id=run_id,
            **_api_options(args, env),
        )

    return auth_guard(
        artifact_name=name,
        artifact_lookup=lookup,
        artifact_validator=_auth_marker_validator(
            args,
            env,
            repository=repository,
            run_id=run_id,
            run_attempt=run_attempt,
        ),
        output_path=output_path,
    )


def _command_verify_auth(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    repository, run_id, run_attempt = _common_coordination_values(args, env)

    def lookup(exact_name: str) -> dict[str, Any] | None:
        return find_exact_workflow_run_artifact(
            exact_name=exact_name,
            repository=repository,
            run_id=run_id,
            **_api_options(args, env),
        )

    wait_options = _wait_options(
        args,
        env,
        timeout_names=(
            "AUTH_MARKER_TIMEOUT_SECONDS",
            "VERIFY_TIMEOUT_SECONDS",
            "MARKER_TIMEOUT_SECONDS",
        ),
    )
    wait_for_auth_marker(
        run_id=run_id,
        run_attempt=run_attempt,
        artifact_lookup=lookup,
        artifact_validator=_auth_marker_validator(
            args,
            env,
            repository=repository,
            run_id=run_id,
            run_attempt=run_attempt,
        ),
        timeout_seconds=wait_options["timeout_seconds"],
        poll_interval_seconds=wait_options["poll_interval_seconds"],
    )
    return 0


def _command_capacity_wait(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    repository, run_id, run_attempt = _common_coordination_values(args, env)
    expected = _argument_or_env(
        args.expected,
        env,
        "VPN_CAPACITY_EXPECTED",
        "EXPECTED_CAPACITY",
        required=True,
    )

    def artifact_lister() -> list[dict[str, Any]]:
        return list_workflow_run_artifacts(
            repository=repository,
            run_id=run_id,
            **_api_options(args, env),
        )

    wait_options = _wait_options(
        args,
        env,
        timeout_names=("BARRIER_TIMEOUT_SECONDS", "MARKER_TIMEOUT_SECONDS"),
    )
    wait_for_capacity_markers(
        run_id=run_id,
        run_attempt=run_attempt,
        expected=expected,
        artifact_lister=artifact_lister,
        timeout_seconds=wait_options["timeout_seconds"],
        poll_interval_seconds=wait_options["poll_interval_seconds"],
    )
    return 0


def _command_write_marker(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    repository, run_id, run_attempt = _common_coordination_values(args, env)
    chain_id = _artifact_component(
        _argument_or_env(args.chain_id, env, "CHAIN_ID", "ACTIVE_CHAIN_ID", required=True),
        "chain ID",
    )
    kind = _normalize_marker_kind(_argument_or_env(args.kind, env, "MARKER_KIND", required=True))
    lane_index = _argument_or_env(args.lane_index, env, "LANE_INDEX", required=True)
    lane_id = _argument_or_env(args.lane_id, env, "LANE_ID")
    if not lane_id and kind == CAPACITY_MARKER_KIND:
        lane_id = f"capacity-{_integer(lane_index, 'lane index', minimum=0)}"
    raw_timestamp = _argument_or_env(args.timestamp, env, "MARKER_TIMESTAMP")
    payload = build_marker_payload(
        kind=kind,
        repository=repository,
        chain_id=chain_id,
        source_sha=_argument_or_env(
            args.source_sha,
            env,
            "SOURCE_SHA",
            "WORKFLOW_SOURCE_SHA",
            required=True,
        ),
        run_id=run_id,
        run_attempt=run_attempt,
        lane_id=lane_id,
        lane_index=lane_index,
        auth_source=_argument_or_env(
            args.auth_source, env, "VPN_AUTH_SOURCE", "AUTH_SOURCE", required=True
        ),
        vpn_status=_argument_or_env(
            args.vpn_status, env, "VPN_STATUS", "AUTH_STATUS", required=True
        ),
        vpn_server=_argument_or_env(
            args.vpn_server,
            env,
            "VPN_SERVER",
            "SERVER",
            required=kind == CAPACITY_MARKER_KIND,
        ),
        vpn_exit_ip=_argument_or_env(args.vpn_exit_ip, env, "VPN_EXIT_IP", "EXIT_IP"),
        attempted_servers=_server_list_env(env, "VPN_ATTEMPTED_SERVERS_JSON"),
        failed_servers=_server_list_env(env, "VPN_FAILED_SERVERS_JSON"),
        timestamp=str(raw_timestamp) if raw_timestamp else None,
    )
    artifact_name = (
        auth_circuit_artifact_name(run_id, run_attempt)
        if kind == AUTH_CIRCUIT_KIND
        else capacity_marker_artifact_name(run_id, run_attempt, lane_index)
    )
    output_value = _argument_or_env(args.output, env, "MARKER_PATH")
    output_path = (
        Path(str(output_value))
        if output_value
        else Path("artifacts/vpn-control") / f"{artifact_name}.json"
    )
    write_json_atomically(output_path, payload)
    github_output = env.get("GITHUB_OUTPUT", "").strip()
    if github_output:
        append_github_output(Path(github_output), "artifact-name", artifact_name)
        append_github_output(Path(github_output), "marker-path", str(output_path))
    return 0


def _command_aggregate_quarantine(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    repository, run_id, run_attempt = _common_coordination_values(args, env)
    marker_directory = Path(
        str(
            _argument_or_env(
                args.marker_directory,
                env,
                "VPN_CAPACITY_MARKER_DIRECTORY",
                default="capacity-markers",
            )
        )
    )
    report = aggregate_vpn_quarantine(
        marker_directory=marker_directory,
        expected_capacity=_argument_or_env(
            args.expected,
            env,
            "VPN_CAPACITY_EXPECTED",
            "EXPECTED_CAPACITY",
            required=True,
        ),
        repository=repository,
        chain_id=_argument_or_env(
            args.chain_id,
            env,
            "CHAIN_ID",
            "ACTIVE_CHAIN_ID",
            required=True,
        ),
        source_sha=_argument_or_env(
            args.source_sha,
            env,
            "SOURCE_SHA",
            "WORKFLOW_SOURCE_SHA",
            required=True,
        ),
        run_id=run_id,
        run_attempt=run_attempt,
        baseline_servers=_server_list_env(env, "BASELINE_QUARANTINE_JSON"),
        discovery_failed_servers=_server_list_env(env, "DISCOVERY_FAILED_SERVERS_JSON"),
    )
    output_value = _argument_or_env(
        args.output,
        env,
        "VPN_QUARANTINE_REPORT_PATH",
        default="artifacts/vpn-control/effective-quarantine.json",
    )
    output_path = Path(str(output_value))
    write_json_atomically(output_path, report)
    github_output = env.get("GITHUB_OUTPUT", "").strip()
    if github_output:
        append_github_output(
            Path(github_output),
            "vpn-quarantined-servers-json",
            json.dumps(report["vpn_quarantined_servers"], separators=(",", ":")),
        )
    return 0


def _command_write_deferred_metadata(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    output_value = _argument_or_env(
        args.output,
        env,
        "LANE_METADATA_PATH",
        default="artifacts/extraction/lane-metadata.json",
    )
    output_path = Path(str(output_value))
    payload = build_deferred_metadata(env)
    write_json_atomically(output_path, payload)
    github_output = env.get("GITHUB_OUTPUT", "").strip()
    if github_output:
        append_github_output(Path(github_output), "final-outcome", "needs_resume")
        append_github_output(Path(github_output), "snapshot-attested", "false")
    return 0


def _add_coordination_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repository")
    parser.add_argument("--run-id")
    parser.add_argument("--run-attempt")
    parser.add_argument("--chain-id")


def _add_api_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--api-attempts")
    parser.add_argument("--request-timeout-seconds")
    parser.add_argument("--retry-delay-seconds")


def _add_wait_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--timeout-seconds")
    parser.add_argument("--poll-interval-seconds")


def _add_auth_marker_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source-sha")
    parser.add_argument("--workflow-head-sha")
    parser.add_argument("--auth-source")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Coordinate VPN state through GitHub artifacts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    auth_guard_parser = subparsers.add_parser("auth-guard")
    _add_coordination_arguments(auth_guard_parser)
    _add_api_arguments(auth_guard_parser)
    _add_auth_marker_arguments(auth_guard_parser)
    auth_guard_parser.add_argument("--output")
    auth_guard_parser.set_defaults(handler=_command_auth_guard)

    verify_auth_parser = subparsers.add_parser("verify-auth")
    _add_coordination_arguments(verify_auth_parser)
    _add_api_arguments(verify_auth_parser)
    _add_wait_arguments(verify_auth_parser)
    _add_auth_marker_arguments(verify_auth_parser)
    verify_auth_parser.set_defaults(handler=_command_verify_auth)

    capacity_wait_parser = subparsers.add_parser("capacity-wait")
    _add_coordination_arguments(capacity_wait_parser)
    _add_api_arguments(capacity_wait_parser)
    _add_wait_arguments(capacity_wait_parser)
    capacity_wait_parser.add_argument("--expected")
    capacity_wait_parser.set_defaults(handler=_command_capacity_wait)

    marker_parser = subparsers.add_parser("write-marker")
    _add_coordination_arguments(marker_parser)
    marker_parser.add_argument("--kind")
    marker_parser.add_argument("--source-sha")
    marker_parser.add_argument("--lane-id")
    marker_parser.add_argument("--lane-index")
    marker_parser.add_argument("--auth-source")
    marker_parser.add_argument("--vpn-status", "--status", dest="vpn_status")
    marker_parser.add_argument("--vpn-server", "--server", dest="vpn_server")
    marker_parser.add_argument("--vpn-exit-ip", "--exit-ip", dest="vpn_exit_ip")
    marker_parser.add_argument("--timestamp")
    marker_parser.add_argument("--output")
    marker_parser.set_defaults(handler=_command_write_marker)

    aggregate_parser = subparsers.add_parser("aggregate-quarantine")
    _add_coordination_arguments(aggregate_parser)
    aggregate_parser.add_argument("--source-sha")
    aggregate_parser.add_argument("--marker-directory")
    aggregate_parser.add_argument("--expected")
    aggregate_parser.add_argument("--output")
    aggregate_parser.set_defaults(handler=_command_aggregate_quarantine)

    deferred_parser = subparsers.add_parser("write-deferred-metadata")
    deferred_parser.add_argument("--output")
    deferred_parser.set_defaults(handler=_command_write_deferred_metadata)
    return parser


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    environment = os.environ if env is None else env
    try:
        return int(args.handler(args, environment))
    except VpnControlPlaneError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError:
        print("error: VPN control-plane file operation failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
