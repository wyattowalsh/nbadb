"""Deterministically generate the repository-authored NBA API fixture manifest.

The generator replays every synthetic fixture through the current pinned parser
contract without network access.  It binds the resulting oracle, the exact
endpoint contract, the fixture bytes, and the verified local ``nba_api`` source
checkout into one canonical manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal
from unittest.mock import patch

import nba_api.live.nba.endpoints as live_endpoints
import nba_api.stats.endpoints as stats_endpoints
from nba_api.library.http import NBAResponse
from nba_api.stats.library.http import NBAStatsResponse

from nbadb.core.errors import ResponseContractError
from nbadb.core.nba_api_provenance import (
    NBA_API_RUNTIME_CONTRACT_PAYLOAD_SHA256,
    NBA_API_UPSTREAM_TAG,
    NBA_API_VERSION,
    verify_nba_api_provider,
)
from nbadb.core.nba_api_runtime_contract import (
    endpoint_contract_sha256,
    owned_contract_sha256,
    pinned_endpoint_contract,
    pinned_live_endpoint_contract,
    pinned_static_dataset_contract,
)
from nbadb.extract.nba_api_adapter import (
    NbaDbLiveHTTP,
    NbaDbStatsHTTP,
    UpstreamApplicationError,
    fetch_live_payloads,
    fetch_stats_packets,
    validate_lossless_fallback_frame,
)

FIXTURE_MANIFEST_NAME: Final = "manifest.json"
FIXTURE_MANIFEST_KIND: Final = "nbadb_nba_api_exact_release_fixture_manifest"
FIXTURE_MANIFEST_SCHEMA_VERSION: Final = 1


class NbaApiFixtureManifestError(ValueError):
    """The exact synthetic-fixture manifest cannot be generated or checked."""


FixtureFamily = Literal["stats", "live", "static"]
FixtureMode = Literal["packets", "lossless", "negative", "live_packets", "static_packet"]


@dataclass(frozen=True, slots=True)
class _FixtureSpec:
    fixture_id: str
    filename: str
    endpoint_id: str
    fixture_kind: str
    family: FixtureFamily
    mode: FixtureMode
    kwargs: tuple[tuple[str, object], ...] = ()
    negative_outcome: str | None = None


_FIXTURES: Final = (
    _FixtureSpec(
        "custom_play_by_play_v3",
        "custom_play_by_play_v3.json",
        "PlayByPlayV3",
        "positive_stats",
        "stats",
        "packets",
        (("game_id", "0000000001"),),
    ),
    _FixtureSpec(
        "duplicate_headers",
        "duplicate_headers.json",
        "LeagueGameLog",
        "positive_stats_lossless",
        "stats",
        "lossless",
    ),
    _FixtureSpec(
        "empty_result_set",
        "empty_result_set.json",
        "LeagueGameLog",
        "positive_stats",
        "stats",
        "packets",
    ),
    _FixtureSpec(
        "error_envelope",
        "error_envelope.json",
        "LeagueGameLog",
        "negative",
        "stats",
        "negative",
        negative_outcome="application_error_envelope",
    ),
    _FixtureSpec(
        "legacy_multi",
        "legacy_multi.json",
        "CommonPlayerInfo",
        "positive_stats",
        "stats",
        "packets",
        (("player_id", 1000001),),
    ),
    _FixtureSpec(
        "legacy_multi_reordered",
        "legacy_multi_reordered.json",
        "CommonPlayerInfo",
        "positive_stats",
        "stats",
        "packets",
        (("player_id", 1000001),),
    ),
    _FixtureSpec(
        "legacy_single",
        "legacy_single.json",
        "LeagueGameLog",
        "positive_stats",
        "stats",
        "packets",
    ),
    _FixtureSpec(
        "live_play_by_play_empty",
        "live_play_by_play_empty.json",
        "PlayByPlay",
        "positive_live",
        "live",
        "live_packets",
        (("game_id", "0000000001"),),
    ),
    _FixtureSpec(
        "malformed_json",
        "malformed_json.txt",
        "LeagueGameLog",
        "negative",
        "stats",
        "negative",
        negative_outcome="malformed_json",
    ),
    _FixtureSpec(
        "mixed_type_rows",
        "mixed_type_rows.json",
        "LeagueGameLog",
        "positive_stats_lossless",
        "stats",
        "lossless",
    ),
    _FixtureSpec(
        "optional_missing_live",
        "optional_missing_live.json",
        "PlayByPlay",
        "negative",
        "live",
        "negative",
        (("game_id", "0000000001"),),
        negative_outcome="optional_result_set_absent",
    ),
    _FixtureSpec(
        "ragged_rows",
        "ragged_rows.json",
        "LeagueGameLog",
        "positive_stats_lossless",
        "stats",
        "lossless",
    ),
    _FixtureSpec(
        "static_teams_synthetic",
        "static_teams_synthetic.json",
        "static_teams",
        "positive_static_canonical_representation",
        "static",
        "static_packet",
    ),
)


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _headers_sha256(headers: tuple[str, ...]) -> str:
    return _canonical_sha256(list(headers))


def _packet_oracle(packet: Any) -> dict[str, object]:
    headers = tuple(packet.headers)
    rows = [list(row) for row in packet.frame.rows()]
    return {
        "canonical_index": packet.canonical_index,
        "headers_sha256": _headers_sha256(headers),
        "name": packet.name,
        "normalized_output_sha256": _canonical_sha256({"headers": list(headers), "rows": rows}),
        "provider_index": packet.provider_index,
        "row_count": packet.frame.height,
    }


def _stats_contract(spec: _FixtureSpec) -> tuple[type, str]:
    runtime_cls = getattr(stats_endpoints, spec.endpoint_id, None)
    if not isinstance(runtime_cls, type):
        raise NbaApiFixtureManifestError(
            f"stats fixture endpoint is unavailable: {spec.endpoint_id}"
        )
    return runtime_cls, endpoint_contract_sha256(pinned_endpoint_contract(runtime_cls))


def _live_contract(spec: _FixtureSpec) -> tuple[type, str]:
    runtime_cls = getattr(live_endpoints, spec.endpoint_id, None)
    if not isinstance(runtime_cls, type):
        raise NbaApiFixtureManifestError(
            f"live fixture endpoint is unavailable: {spec.endpoint_id}"
        )
    return runtime_cls, owned_contract_sha256(pinned_live_endpoint_contract(runtime_cls))


def _stats_oracle(spec: _FixtureSpec, raw: str) -> tuple[str, dict[str, object]]:
    runtime_cls, contract_sha256 = _stats_contract(spec)
    kwargs: dict[str, Any] = dict(spec.kwargs)
    with patch.object(
        NbaDbStatsHTTP,
        "send_api_request",
        lambda _self, **_kwargs: NBAStatsResponse(raw, 200, "fixture://offline-generation"),
    ):
        if spec.mode == "negative":
            try:
                fetch_stats_packets(runtime_cls, **kwargs)
            except (ResponseContractError, UpstreamApplicationError) as exc:
                return contract_sha256, {
                    "error_class": type(exc).__name__,
                    "outcome": spec.negative_outcome,
                }
            raise NbaApiFixtureManifestError(
                f"negative stats fixture unexpectedly succeeded: {spec.fixture_id}"
            )

        packets = fetch_stats_packets(runtime_cls, **kwargs)
    if spec.mode == "packets":
        if packets.lossless_fallback is not None:
            raise NbaApiFixtureManifestError(
                f"packet fixture unexpectedly used lossless fallback: {spec.fixture_id}"
            )
        return contract_sha256, {
            "outcome": "success",
            "packets": [_packet_oracle(packet) for packet in packets],
        }
    if spec.mode != "lossless" or packets.lossless_fallback is None:
        raise NbaApiFixtureManifestError(
            f"lossless fixture did not produce its fallback: {spec.fixture_id}"
        )
    fallback = packets.lossless_fallback
    validate_lossless_fallback_frame(fallback.frame)
    return contract_sha256, {
        "fallback_frame_sha256": _canonical_sha256(
            {"columns": fallback.frame.columns, "rows": fallback.frame.to_dicts()}
        ),
        "fallback_record_count": fallback.frame.height,
        "outcome": "success_lossless_fallback",
        "reason_codes": list(fallback.reason_codes),
        "wide_packet_count": len(packets),
    }


def _live_oracle(spec: _FixtureSpec, raw: str) -> tuple[str, dict[str, object]]:
    runtime_cls, contract_sha256 = _live_contract(spec)
    kwargs: dict[str, Any] = dict(spec.kwargs)
    outputs = {"actions": "game_actions"}
    with patch.object(
        NbaDbLiveHTTP,
        "send_api_request",
        lambda _self, **_kwargs: NBAResponse(raw, 200, "fixture://offline-generation"),
    ):
        if spec.mode == "negative":
            try:
                fetch_live_payloads(runtime_cls, outputs, **kwargs)
            except ResponseContractError as exc:
                return contract_sha256, {
                    "error_class": type(exc).__name__,
                    "outcome": spec.negative_outcome,
                }
            raise NbaApiFixtureManifestError(
                f"negative live fixture unexpectedly succeeded: {spec.fixture_id}"
            )
        payload = fetch_live_payloads(runtime_cls, outputs, **kwargs)

    contract = pinned_live_endpoint_contract(runtime_cls)
    result_set = next(item for item in contract.result_sets if item.name == "game_actions")
    headers = tuple(field.name for field in result_set.fields)
    rows = payload.get("actions")
    if not isinstance(rows, list):
        raise NbaApiFixtureManifestError("live fixture actions are not a list")
    return contract_sha256, {
        "outcome": "success",
        "packets": [
            {
                "canonical_index": result_set.ordinal,
                "headers_sha256": _headers_sha256(headers),
                "name": result_set.name,
                "normalized_output_sha256": _canonical_sha256(
                    {"headers": list(headers), "rows": rows}
                ),
                "provider_index": None,
                "row_count": len(rows),
            }
        ],
    }


def _static_oracle(spec: _FixtureSpec, raw: str) -> tuple[str, dict[str, object]]:
    contract = pinned_static_dataset_contract(spec.endpoint_id)
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NbaApiFixtureManifestError("static fixture is not JSON") from exc
    headers = tuple(field.name for field in contract.raw_fields)
    if (
        not isinstance(rows, list)
        or any(not isinstance(row, list) for row in rows)
        or any(len(row) != len(headers) for row in rows)
    ):
        raise NbaApiFixtureManifestError("static fixture rows do not match the raw contract")
    return owned_contract_sha256(contract), {
        "outcome": "success",
        "packets": [
            {
                "canonical_index": 0,
                "headers_sha256": _headers_sha256(headers),
                "name": f"{contract.source_symbol}_shape_1",
                "normalized_output_sha256": _canonical_sha256(
                    {"headers": list(headers), "rows": rows}
                ),
                "provider_index": 0,
                "row_count": len(rows),
            }
        ],
    }


def build_fixture_manifest(
    *,
    project_root: Path,
    upstream_root: Path,
) -> dict[str, object]:
    """Build the exact checked manifest without performing provider I/O."""

    root = project_root.resolve()
    fixture_root = root / "tests" / "fixtures" / "nba_api_contract"
    verification = verify_nba_api_provider(upstream_root.resolve(), project_root=root)
    if verification.get("verified") is not True or verification.get("errors") != []:
        raise NbaApiFixtureManifestError("exact nba_api provider verification failed")

    expected_files = {spec.filename for spec in _FIXTURES}
    observed_files = {
        path.name for path in fixture_root.iterdir() if path.name != FIXTURE_MANIFEST_NAME
    }
    if observed_files != expected_files:
        raise NbaApiFixtureManifestError(
            "fixture directory membership differs from the generator inventory"
        )

    entries: list[dict[str, object]] = []
    for spec in _FIXTURES:
        path = fixture_root / spec.filename
        if path.is_symlink() or not path.is_file():
            raise NbaApiFixtureManifestError(f"fixture path is invalid: {spec.filename}")
        raw_bytes = path.read_bytes()
        try:
            raw_text = raw_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise NbaApiFixtureManifestError(
                f"fixture is not valid UTF-8: {spec.filename}"
            ) from exc
        if spec.family == "stats":
            contract_sha256, oracle = _stats_oracle(spec, raw_text)
        elif spec.family == "live":
            contract_sha256, oracle = _live_oracle(spec, raw_text)
        else:
            contract_sha256, oracle = _static_oracle(spec, raw_text)
        relative = path.relative_to(root).as_posix()
        payload_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        entries.append(
            {
                "endpoint_contract_sha256": contract_sha256,
                "endpoint_id": spec.endpoint_id,
                "fixture_kind": spec.fixture_kind,
                "id": spec.fixture_id,
                "oracle": oracle,
                "payload_sha256": payload_sha256,
                "relative_path": relative,
                "rights_policy_id": "repo-synthetic-mit",
                "sanitization_policy_id": "synthetic-none",
                "source_path": f"repo-authored:{relative}",
                "source_sha256": payload_sha256,
            }
        )

    entries.sort(key=lambda item: str(item["id"]))
    body: dict[str, object] = {
        "entries": entries,
        "entries_sha256": _canonical_sha256(entries),
        "kind": FIXTURE_MANIFEST_KIND,
        "provider": {
            "distribution_version": NBA_API_VERSION,
            "runtime_contract_payload_sha256": NBA_API_RUNTIME_CONTRACT_PAYLOAD_SHA256,
            "upstream_tag": NBA_API_UPSTREAM_TAG,
        },
        "rights_policies": {
            "repo-synthetic-mit": {
                "copied_nba_response_data": False,
                "copied_upstream_code": False,
                "copied_upstream_docs": False,
                "data_class": "repository_authored_synthetic_non_nba",
                "license_identifier": "MIT",
            }
        },
        "sanitization_policies": {"synthetic-none": "not_applicable_repo_authored_synthetic"},
        "schema_version": FIXTURE_MANIFEST_SCHEMA_VERSION,
    }
    return {**body, "manifest_sha256": _canonical_sha256(body)}


def fixture_manifest_bytes(*, project_root: Path, upstream_root: Path) -> bytes:
    """Return stable, human-readable bytes for the checked manifest."""

    payload = build_fixture_manifest(
        project_root=project_root,
        upstream_root=upstream_root,
    )
    return (
        json.dumps(
            payload,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def write_fixture_manifest(
    path: Path,
    *,
    project_root: Path,
    upstream_root: Path,
    check: bool = False,
) -> bool:
    """Write or verify the canonical synthetic-fixture manifest."""

    encoded = fixture_manifest_bytes(
        project_root=project_root,
        upstream_root=upstream_root,
    )
    if path.is_file() and path.read_bytes() == encoded:
        return True
    if check:
        raise NbaApiFixtureManifestError("NBA API fixture manifest has generated drift")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return False


def main(argv: list[str] | None = None) -> int:
    """Generate or check the manifest from an exact local provider checkout."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--upstream-root", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tests/fixtures/nba_api_contract/manifest.json"),
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        already_current = write_fixture_manifest(
            args.output,
            project_root=args.project_root,
            upstream_root=args.upstream_root,
            check=args.check,
        )
    except (NbaApiFixtureManifestError, OSError) as exc:
        parser.error(str(exc))
    print("unchanged" if already_current else "updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "FIXTURE_MANIFEST_KIND",
    "FIXTURE_MANIFEST_NAME",
    "FIXTURE_MANIFEST_SCHEMA_VERSION",
    "NbaApiFixtureManifestError",
    "build_fixture_manifest",
    "fixture_manifest_bytes",
    "main",
    "write_fixture_manifest",
]
