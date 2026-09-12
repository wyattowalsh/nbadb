from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from nba_api.live.nba.library.http import NBALiveHTTP
from nba_api.stats.library import parameters as provider_parameters
from nba_api.stats.library.http import NBAStatsHTTP

from nbadb.core import nba_api_competition_verifier as verifier
from nbadb.core.nba_api_competition import (
    COMPETITION_RESOURCE,
    NbaApiCompetitionError,
    build_competition_authority,
    build_pinned_competition_payload,
    load_pinned_competition_payload,
    pinned_competition_authority,
    write_pinned_competition,
)
from nbadb.core.nba_api_competition_verifier import (
    NbaApiCompetitionVerificationError,
    verify_competition_authority_file,
    verify_pinned_competition_authority,
)
from nbadb.core.nba_api_surface_inventory import NBA_API_RECORD_AUTHORITY_SHA256


def _resource_path() -> Path:
    return Path(__file__).parents[3] / "src" / "nbadb" / "contracts" / COMPETITION_RESOURCE


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)[:-1]).hexdigest()


def _clear_caches() -> None:
    build_competition_authority.cache_clear()
    pinned_competition_authority.cache_clear()
    verify_pinned_competition_authority.cache_clear()


@pytest.fixture(autouse=True)
def _isolated_competition_caches() -> None:
    _clear_caches()
    yield
    _clear_caches()


def test_competition_authority_derives_exact_package_values() -> None:
    authority = pinned_competition_authority()
    payload = load_pinned_competition_payload()

    assert tuple((item.league_id, item.symbol) for item in authority.competitions) == (
        ("00", "nba"),
        ("01", "aba"),
        ("10", "wnba"),
        ("15", "summer_league"),
        ("20", "g_league"),
    )
    assert authority.league_ids == ("00", "01", "10", "15", "20")
    assert (authority.default_league_id, authority.default_symbol) == ("00", "nba")
    assert authority.distribution_record_authority_sha256 == NBA_API_RECORD_AUTHORITY_SHA256
    assert payload == build_pinned_competition_payload()
    assert payload["competition_count"] == 5
    assert payload["authority_sha256"] == authority.authority_sha256
    assert payload["competition_values_sha256"] == authority.competition_values_sha256


def test_independent_competition_authority_matches_primary() -> None:
    authority = pinned_competition_authority()
    proof = verify_pinned_competition_authority()
    payload = load_pinned_competition_payload()

    assert proof.competitions == tuple(
        (item.league_id, item.symbol) for item in authority.competitions
    )
    assert proof.default_symbol == authority.default_symbol
    assert proof.default_league_id == authority.default_league_id
    assert proof.provider_source_sha256 == authority.provider_source_sha256
    assert (
        proof.distribution_record_authority_sha256 == authority.distribution_record_authority_sha256
    )
    assert proof.checked_payload_sha256 == payload["payload_sha256"]
    assert len(proof.proof_sha256) == 64


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_competition_authority_rejects_missing_or_extra_package_values(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    if mutation == "missing":
        monkeypatch.delattr(provider_parameters.LeagueID, "aba")
    else:
        monkeypatch.setattr(provider_parameters.LeagueID, "future_league", "99", raising=False)
    _clear_caches()

    with pytest.raises(
        NbaApiCompetitionError,
        match="differs from the installed package authority",
    ):
        load_pinned_competition_payload()


def test_competition_authority_changes_when_package_value_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = build_pinned_competition_payload()
    monkeypatch.setattr(provider_parameters.LeagueID, "aba", "02")
    _clear_caches()
    changed = build_pinned_competition_payload()

    assert changed["payload_sha256"] != baseline["payload_sha256"]
    assert {row["league_id"] for row in changed["competitions"]} == {
        "00",
        "02",
        "10",
        "15",
        "20",
    }
    with pytest.raises(NbaApiCompetitionError, match="differs from the installed package"):
        load_pinned_competition_payload()


def test_independent_ast_rejects_missing_extra_and_invalid_values() -> None:
    installed_source = Path(provider_parameters.__file__).read_bytes()
    baseline, _, _ = verifier._derive_competitions_from_source(installed_source)
    assert len(baseline) == 5

    missing = installed_source.replace(b'    aba = "01"\n', b"")
    extra = installed_source.replace(
        b'    g_league = "20"\n',
        b'    g_league = "20"\n    future_league = "99"\n',
    )
    invalid = installed_source.replace(b'    aba = "01"\n', '    aba = "\u0660\u0661"\n'.encode())
    assert len(verifier._derive_competitions_from_source(missing)[0]) == 4
    assert len(verifier._derive_competitions_from_source(extra)[0]) == 6
    with pytest.raises(
        NbaApiCompetitionVerificationError,
        match="two ASCII digits",
    ):
        verifier._derive_competitions_from_source(invalid)


def test_checked_resource_rejects_self_consistent_foreign_value(tmp_path: Path) -> None:
    payload = deepcopy(build_pinned_competition_payload())
    rows = payload["competitions"]
    assert isinstance(rows, list)
    rows[-1] = {"league_id": "99", "symbol": "g_league"}
    payload["competition_values_sha256"] = _digest(
        [row["league_id"] for row in rows if isinstance(row, dict)]
    )
    authority = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "authority_sha256",
            "independent_proof",
            "payload_sha256",
        }
    }
    payload["authority_sha256"] = _digest(authority)
    body = dict(payload)
    body.pop("payload_sha256")
    payload["payload_sha256"] = _digest(body)
    path = tmp_path / "foreign.json"
    path.write_bytes(_canonical_bytes(payload))

    with pytest.raises(NbaApiCompetitionError, match="installed package authority"):
        load_pinned_competition_payload(path)
    with pytest.raises(
        NbaApiCompetitionVerificationError,
        match="independent source AST",
    ):
        verify_competition_authority_file(path)


@pytest.mark.parametrize(
    "raw, message",
    [
        (b'{"schema_version":1,"schema_version":1}\n', "duplicate object key"),
        (b'{"value":NaN}\n', "non-finite JSON constant"),
        (b"{}", "not canonical JSON"),
    ],
)
def test_competition_resource_rejects_noncanonical_json(
    tmp_path: Path,
    raw: bytes,
    message: str,
) -> None:
    path = tmp_path / "invalid.json"
    path.write_bytes(raw)
    with pytest.raises(NbaApiCompetitionError, match=message):
        load_pinned_competition_payload(path)


def test_competition_resource_is_generated_without_drift(tmp_path: Path) -> None:
    candidate = tmp_path / COMPETITION_RESOURCE
    assert write_pinned_competition(candidate) is False
    assert write_pinned_competition(candidate) is True
    assert write_pinned_competition(candidate, check=True) is True
    assert candidate.read_bytes() == _resource_path().read_bytes()


def test_competition_authority_never_sends_provider_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _network_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("competition authority attempted provider I/O")

    monkeypatch.setattr(NBAStatsHTTP, "send_api_request", _network_forbidden)
    monkeypatch.setattr(NBALiveHTTP, "send_api_request", _network_forbidden)
    _clear_caches()
    assert pinned_competition_authority().league_ids == ("00", "01", "10", "15", "20")
