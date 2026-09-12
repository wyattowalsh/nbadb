from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path
from typing import Any

import pytest
from nba_api.library.http import NBAResponse
from nba_api.live.nba.endpoints import PlayByPlay
from nba_api.stats.endpoints import CommonPlayerInfo, LeagueGameLog, PlayByPlayV3
from nba_api.stats.library.http import NBAStatsResponse

from nbadb.core.errors import ResponseContractError
from nbadb.core.nba_api_provenance import (
    NBA_API_RUNTIME_CONTRACT_PAYLOAD_SHA256,
    NBA_API_UPSTREAM_TAG,
    NBA_API_VERSION,
    expected_nba_api_provider_authority,
)
from nbadb.core.nba_api_runtime_contract import (
    endpoint_contract_sha256,
    owned_contract_sha256,
    pinned_endpoint_contract,
    pinned_live_endpoint_contract,
    pinned_static_dataset_contract,
)
from nbadb.extract.bronze import (
    BronzeCaptureStore,
    BronzeLimits,
    ParserInputContext,
    ResultSetReceipt,
    parent_occurrence_states_digest,
)
from nbadb.extract.nba_api_adapter import (
    NbaDbLiveHTTP,
    NbaDbStatsHTTP,
    UpstreamApplicationError,
    fetch_live_payloads,
    fetch_stats_packets,
    validate_lossless_fallback_frame,
)

_STATS_ENDPOINTS = {
    "CommonPlayerInfo": (CommonPlayerInfo, {"player_id": 1000001}),
    "LeagueGameLog": (LeagueGameLog, {}),
    "PlayByPlayV3": (PlayByPlayV3, {"game_id": "0000000001"}),
}


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


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
    return hashlib.sha256(
        json.dumps(list(headers), separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _manifest(project_root: Path) -> dict[str, Any]:
    path = project_root / "tests" / "fixtures" / "nba_api_contract" / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _entry(project_root: Path, fixture_id: str) -> dict[str, Any]:
    return next(item for item in _manifest(project_root)["entries"] if item["id"] == fixture_id)


@pytest.fixture(autouse=True)
def _deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access is forbidden in fixture replay tests")

    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket.socket, "connect", _blocked)


def test_exact_release_fixture_manifest_is_complete_digest_bound_and_synthetic(
    project_root: Path,
) -> None:
    manifest = _manifest(project_root)
    body = dict(manifest)
    manifest_digest = body.pop("manifest_sha256")
    entries = manifest["entries"]
    fixture_root = project_root / "tests" / "fixtures" / "nba_api_contract"

    assert manifest["schema_version"] == 1
    assert manifest["kind"] == "nbadb_nba_api_exact_release_fixture_manifest"
    assert manifest["provider"] == {
        "distribution_version": NBA_API_VERSION,
        "runtime_contract_payload_sha256": NBA_API_RUNTIME_CONTRACT_PAYLOAD_SHA256,
        "upstream_tag": NBA_API_UPSTREAM_TAG,
    }
    assert manifest_digest == _canonical_sha256(body)
    assert manifest["entries_sha256"] == _canonical_sha256(entries)
    assert [item["id"] for item in entries] == sorted(item["id"] for item in entries)
    assert manifest["rights_policies"] == {
        "repo-synthetic-mit": {
            "copied_nba_response_data": False,
            "copied_upstream_code": False,
            "copied_upstream_docs": False,
            "data_class": "repository_authored_synthetic_non_nba",
            "license_identifier": "MIT",
        }
    }
    assert manifest["sanitization_policies"] == {
        "synthetic-none": "not_applicable_repo_authored_synthetic"
    }

    declared_paths: set[str] = set()
    for item in entries:
        relative = item["relative_path"]
        path = project_root / relative
        assert path.resolve().is_relative_to(fixture_root.resolve())
        assert path.is_file() and not path.is_symlink()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert item["source_path"] == f"repo-authored:{relative}"
        assert item["source_sha256"] == digest
        assert item["payload_sha256"] == digest
        assert item["rights_policy_id"] == "repo-synthetic-mit"
        assert item["sanitization_policy_id"] == "synthetic-none"
        declared_paths.add(relative)

    observed_paths = {
        path.relative_to(project_root).as_posix()
        for path in fixture_root.iterdir()
        if path.name != "manifest.json"
    }
    assert declared_paths == observed_paths


@pytest.mark.parametrize(
    "fixture_id",
    [
        "custom_play_by_play_v3",
        "empty_result_set",
        "legacy_multi",
        "legacy_multi_reordered",
        "legacy_single",
    ],
)
def test_stats_fixture_replay_matches_normalized_oracle_without_network(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture_id: str,
) -> None:
    item = _entry(project_root, fixture_id)
    endpoint_cls, kwargs = _STATS_ENDPOINTS[item["endpoint_id"]]
    raw = (project_root / item["relative_path"]).read_text(encoding="utf-8")

    monkeypatch.setattr(
        NbaDbStatsHTTP,
        "send_api_request",
        lambda _self, **_kwargs: NBAStatsResponse(raw, 200, "fixture://offline-replay"),
    )

    packets = fetch_stats_packets(endpoint_cls, **kwargs)
    observed = [
        {
            "canonical_index": packet.canonical_index,
            "headers_sha256": _headers_sha256(packet.headers),
            "name": packet.name,
            "normalized_output_sha256": _canonical_sha256(
                {
                    "headers": list(packet.headers),
                    "rows": [list(row) for row in packet.frame.rows()],
                }
            ),
            "provider_index": packet.provider_index,
            "row_count": packet.frame.height,
        }
        for packet in packets
    ]

    assert observed == item["oracle"]["packets"]
    assert item["endpoint_contract_sha256"] == endpoint_contract_sha256(
        pinned_endpoint_contract(endpoint_cls)
    )


@pytest.mark.parametrize(
    "fixture_id",
    ["error_envelope", "malformed_json"],
)
def test_negative_stats_fixtures_fail_with_declared_owned_class(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture_id: str,
) -> None:
    item = _entry(project_root, fixture_id)
    raw = (project_root / item["relative_path"]).read_text(encoding="utf-8")
    monkeypatch.setattr(
        NbaDbStatsHTTP,
        "send_api_request",
        lambda _self, **_kwargs: NBAStatsResponse(raw, 200, "fixture://offline-replay"),
    )

    with pytest.raises((ResponseContractError, UpstreamApplicationError)) as exc_info:
        fetch_stats_packets(LeagueGameLog)

    assert type(exc_info.value).__name__ == item["oracle"]["error_class"]


@pytest.mark.parametrize(
    "fixture_id",
    ["duplicate_headers", "mixed_type_rows", "ragged_rows"],
)
def test_stats_shape_drift_fixtures_are_retained_losslessly(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture_id: str,
) -> None:
    item = _entry(project_root, fixture_id)
    raw = (project_root / item["relative_path"]).read_text(encoding="utf-8")
    monkeypatch.setattr(
        NbaDbStatsHTTP,
        "send_api_request",
        lambda _self, **_kwargs: NBAStatsResponse(raw, 200, "fixture://offline-replay"),
    )

    packets = fetch_stats_packets(LeagueGameLog)
    fallback = packets.lossless_fallback

    assert fallback is not None
    validate_lossless_fallback_frame(fallback.frame)
    oracle = item["oracle"]
    assert len(packets) == oracle["wide_packet_count"]
    assert fallback.frame.height == oracle["fallback_record_count"]
    assert list(fallback.reason_codes) == oracle["reason_codes"]
    assert (
        _canonical_sha256({"columns": fallback.frame.columns, "rows": fallback.frame.to_dicts()})
        == oracle["fallback_frame_sha256"]
    )


def test_live_empty_and_missing_fixtures_remain_distinct(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    success = _entry(project_root, "live_play_by_play_empty")
    raw = (project_root / success["relative_path"]).read_text(encoding="utf-8")
    monkeypatch.setattr(
        NbaDbLiveHTTP,
        "send_api_request",
        lambda _self, **_kwargs: NBAResponse(raw, 200, "fixture://offline-replay"),
    )

    result = fetch_live_payloads(
        PlayByPlay,
        {"actions": "game_actions"},
        game_id="0000000001",
    )

    assert result == {"actions": []}
    contract = pinned_live_endpoint_contract(PlayByPlay)
    result_set = next(item for item in contract.result_sets if item.name == "game_actions")
    headers = tuple(field.name for field in result_set.fields)
    assert success["oracle"]["packets"] == [
        {
            "canonical_index": result_set.ordinal,
            "headers_sha256": _headers_sha256(headers),
            "name": "game_actions",
            "normalized_output_sha256": _canonical_sha256({"headers": list(headers), "rows": []}),
            "provider_index": None,
            "row_count": 0,
        }
    ]

    missing = _entry(project_root, "optional_missing_live")
    missing_raw = (project_root / missing["relative_path"]).read_text(encoding="utf-8")
    monkeypatch.setattr(
        NbaDbLiveHTTP,
        "send_api_request",
        lambda _self, **_kwargs: NBAResponse(
            missing_raw,
            200,
            "fixture://offline-replay",
        ),
    )
    with pytest.raises(ResponseContractError) as exc_info:
        fetch_live_payloads(
            PlayByPlay,
            {"actions": "game_actions"},
            game_id="0000000001",
        )
    assert type(exc_info.value).__name__ == missing["oracle"]["error_class"]


def test_static_synthetic_fixture_has_canonical_private_replay(
    project_root: Path,
    tmp_path: Path,
) -> None:
    item = _entry(project_root, "static_teams_synthetic")
    records = json.loads((project_root / item["relative_path"]).read_text(encoding="utf-8"))
    contract = pinned_static_dataset_contract("static_teams")
    headers = tuple(field.name for field in contract.raw_fields)
    packet = item["oracle"]["packets"][0]
    store = BronzeCaptureStore(
        tmp_path / "private" / "bronze",
        public_roots=(tmp_path / "data",),
        limits=BronzeLimits(100_000, 1_000_000, 1),
    )
    captured = store.store_static_records(records)
    receipt = store.record_static_snapshot_attempt(
        context=ParserInputContext(attempt_id="fixture-static"),
        endpoint_id="static_teams",
        endpoint_slug="teams",
        provider_authority_sha256=expected_nba_api_provider_authority()["authority_sha256"],
        contract_sha256=owned_contract_sha256(contract),
        captured=captured,
        result_set=ResultSetReceipt(
            name="teams_shape_1",
            provider_index=0,
            canonical_index=0,
            headers_sha256=_headers_sha256(headers),
            row_count=len(records),
            json_path=None,
            container_kind="nba_api_static_records",
            container_count=1,
            missing_count=0,
            null_count=0,
            parent_observation_count=1,
            parent_occurrence_states_sha256=parent_occurrence_states_digest(("present",)),
            observed_field_orders_sha256=_headers_sha256(headers),
            normalized_output_sha256=_canonical_sha256({"headers": list(headers), "rows": records}),
        ),
    )

    assert json.loads(store.replay_parser_input(receipt)) == records
    assert packet["headers_sha256"] == _headers_sha256(headers)
    assert packet["normalized_output_sha256"] == _canonical_sha256(
        {"headers": list(headers), "rows": records}
    )
    assert item["endpoint_contract_sha256"] == owned_contract_sha256(contract)
