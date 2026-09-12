from __future__ import annotations

import hashlib
import json
import socket
from collections import Counter
from copy import deepcopy
from typing import TYPE_CHECKING, cast

import pytest

from nbadb.core import nba_api_competition_occurrences_verifier as occurrence_verifier
from nbadb.core.nba_api_competition_occurrences import (
    build_pinned_competition_occurrence_payload,
)
from nbadb.core.nba_api_competition_occurrences_verifier import (
    NbaApiCompetitionOccurrenceVerificationError,
    verify_competition_occurrence_authority_file,
)

if TYPE_CHECKING:
    from pathlib import Path


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _planning_digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value) + b"\n").hexdigest()


def _recompute_package_summary(payload: dict[str, object]) -> None:
    rows = cast("list[dict[str, object]]", payload["package_occurrences"])
    payload["package_occurrence_count"] = len(rows)
    payload["package_endpoint_count"] = len({str(row["provider_endpoint_id"]) for row in rows})
    payload["package_constructor_name_counts"] = dict(
        sorted(Counter(str(row["constructor_name"]) for row in rows).items())
    )
    payload["package_wire_name_counts"] = dict(
        sorted(Counter(str(row["wire_name"]) for row in rows).items())
    )
    payload["package_occurrences_sha256"] = _digest(rows)


def _repo_planning_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "parameter_roles": [
                {
                    "default": role["default"],
                    "has_default": role["has_default"],
                    "name": role["constructor_name"],
                    "nullable": role["nullable"],
                    "query_name": role["wire_name"],
                    "semantic_role": role["semantic_role"],
                }
                for role in cast("list[dict[str, object]]", row["parameter_roles"])
            ],
            "provider_endpoint_ids": row["provider_endpoint_ids"],
            "provider_occurrence_ids": row["provider_occurrence_ids"],
            "repo_endpoint_name": row["repo_endpoint_name"],
        }
        for row in rows
    ]


def _recompute_repo_summary(payload: dict[str, object]) -> None:
    rows = cast("list[dict[str, object]]", payload["repo_aliases"])
    payload["repo_alias_count"] = len(rows)
    payload["projected_role_count"] = sum(
        len(cast("list[dict[str, object]]", row["parameter_roles"])) for row in rows
    )
    payload["projected_role_name_counts"] = dict(
        sorted(
            Counter(
                str(role["constructor_name"])
                for row in rows
                for role in cast("list[dict[str, object]]", row["parameter_roles"])
            ).items()
        )
    )
    payload["repo_aliases_sha256"] = _digest(rows)
    payload["repo_alias_planning_census_sha256"] = _planning_digest(_repo_planning_rows(rows))
    source_rows = cast("list[dict[str, object]]", payload["repo_source_inventory"])
    aliases_by_path: dict[str, list[str]] = {}
    for row in rows:
        aliases_by_path.setdefault(str(row["source_path"]), []).append(
            str(row["repo_endpoint_name"])
        )
    source_planning = [
        {
            "alias_count": len(aliases_by_path.get(str(source["path"]), [])),
            "aliases": sorted(aliases_by_path.get(str(source["path"]), [])),
            "path": source["path"],
            "sha256": source["sha256"],
        }
        for source in source_rows
        if aliases_by_path.get(str(source["path"]))
    ]
    payload["repo_source_file_count"] = len(source_planning)
    payload["repo_source_inventory_sha256"] = _planning_digest(source_planning)


def _reseal(payload: dict[str, object]) -> bytes:
    authority = {
        key: value
        for key, value in payload.items()
        if key not in {"authority_sha256", "independent_proof", "payload_sha256"}
    }
    payload["authority_sha256"] = _digest(authority)
    envelope = dict(payload)
    envelope.pop("payload_sha256", None)
    payload["payload_sha256"] = _digest(envelope)
    return _canonical_bytes(payload) + b"\n"


def _write_candidate(tmp_path: Path, payload: dict[str, object], name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(_reseal(payload))
    return path


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("default", "10"),
        ("nullable", True),
        ("semantic_role", "neutral_filter"),
    ],
)
def test_independent_verifier_rejects_default_nullable_or_role_mutation(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    payload = deepcopy(build_pinned_competition_occurrence_payload())
    rows = cast("list[dict[str, object]]", payload["package_occurrences"])
    rows[0][field] = value
    _recompute_package_summary(payload)
    path = _write_candidate(tmp_path, payload, f"mutated-{field}.json")

    with pytest.raises(
        NbaApiCompetitionOccurrenceVerificationError,
        match="independent source AST",
    ):
        verify_competition_occurrence_authority_file(path)


def test_independent_verifier_rejects_output_behavior_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_order: list[str] = []
    original_derive = occurrence_verifier._independent_authority_body
    original_load = occurrence_verifier._load_checked_resource

    def derive_with_order_proof() -> tuple[dict[str, object], tuple[int, int, int]]:
        result = original_derive()
        call_order.append("derive")
        return result

    def load_with_order_proof(path: Path | None) -> dict[str, object]:
        call_order.append("load")
        return original_load(path)

    def reject_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("independent verification attempted a network operation")

    monkeypatch.setattr(socket, "socket", reject_network)
    monkeypatch.setattr(socket, "create_connection", reject_network)
    monkeypatch.setattr(
        occurrence_verifier,
        "_independent_authority_body",
        derive_with_order_proof,
    )
    monkeypatch.setattr(
        occurrence_verifier,
        "_load_checked_resource",
        load_with_order_proof,
    )

    payload = deepcopy(build_pinned_competition_occurrence_payload())
    aliases = cast("list[dict[str, object]]", payload["repo_aliases"])
    roles = cast("list[dict[str, object]]", aliases[0]["parameter_roles"])
    roles[0]["output_behavior"] = "drop_competition_identity"
    _recompute_repo_summary(payload)
    path = _write_candidate(tmp_path, payload, "mutated-output.json")

    with pytest.raises(
        NbaApiCompetitionOccurrenceVerificationError,
        match="independent source AST",
    ):
        verify_competition_occurrence_authority_file(path)

    assert call_order == ["derive", "load"]


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_independent_verifier_rejects_missing_or_extra_package_occurrence(
    tmp_path: Path,
    mutation: str,
) -> None:
    payload = deepcopy(build_pinned_competition_occurrence_payload())
    rows = cast("list[dict[str, object]]", payload["package_occurrences"])
    if mutation == "missing":
        rows.pop()
    else:
        foreign = deepcopy(rows[-1])
        foreign["occurrence_id"] = "parameter:stats:ForeignLeagueFeed:0000:league_id"
        foreign["provider_endpoint_id"] = "ForeignLeagueFeed"
        foreign["provider_module"] = "nba_api.stats.endpoints.foreignleaguefeed"
        foreign["provider_source_path"] = "nba_api/stats/endpoints/foreignleaguefeed.py"
        rows.append(foreign)
        rows.sort(key=lambda row: str(row["occurrence_id"]))
    _recompute_package_summary(payload)
    path = _write_candidate(tmp_path, payload, f"package-{mutation}.json")

    with pytest.raises(
        NbaApiCompetitionOccurrenceVerificationError,
        match="independent source AST",
    ):
        verify_competition_occurrence_authority_file(path)


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_independent_verifier_rejects_missing_or_extra_repo_alias(
    tmp_path: Path,
    mutation: str,
) -> None:
    payload = deepcopy(build_pinned_competition_occurrence_payload())
    aliases = cast("list[dict[str, object]]", payload["repo_aliases"])
    if mutation == "missing":
        aliases.pop()
    else:
        foreign = deepcopy(aliases[0])
        foreign["repo_endpoint_name"] = "foreign_competition_alias"
        foreign["extractor_qualname"] = "ForeignCompetitionAliasExtractor"
        aliases.append(foreign)
        aliases.sort(key=lambda row: str(row["repo_endpoint_name"]))
    _recompute_repo_summary(payload)
    path = _write_candidate(tmp_path, payload, f"repo-{mutation}.json")

    with pytest.raises(
        NbaApiCompetitionOccurrenceVerificationError,
        match="independent source AST",
    ):
        verify_competition_occurrence_authority_file(path)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema_version":1,"schema_version":1}\n',
        b'{"value":NaN}\n',
        b"{}",
    ],
)
def test_independent_verifier_rejects_noncanonical_resources(
    tmp_path: Path,
    raw: bytes,
) -> None:
    path = tmp_path / "invalid.json"
    path.write_bytes(raw)
    with pytest.raises(NbaApiCompetitionOccurrenceVerificationError):
        verify_competition_occurrence_authority_file(path)
