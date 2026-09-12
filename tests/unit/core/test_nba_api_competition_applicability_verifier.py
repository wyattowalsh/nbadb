from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest

from nbadb.core.nba_api_competition_applicability import (
    build_pinned_competition_applicability_payload,
    pinned_competition_applicability_authority,
)
from nbadb.core.nba_api_competition_applicability_verifier import (
    NbaApiCompetitionApplicabilityVerificationError,
    verify_competition_applicability_authority_file,
    verify_pinned_competition_applicability_authority,
)


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


def _reseal(payload: dict[str, object], array: str | None = None) -> bytes:
    if array is not None:
        rows = payload[array]
        payload[f"{array}_sha256"] = _digest(rows)
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


def _candidate(tmp_path: Path, payload: dict[str, object], array: str, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(_reseal(payload, array))
    return path


def _rows(payload: dict[str, object], key: str) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", payload[key])


def _assert_independent_rejection(path: Path) -> None:
    with pytest.raises(
        NbaApiCompetitionApplicabilityVerificationError,
        match="independent sealed sources",
    ):
        verify_competition_applicability_authority_file(path)


def test_independent_applicability_authority_matches_primary() -> None:
    authority = pinned_competition_applicability_authority()
    proof = verify_pinned_competition_applicability_authority()
    payload = build_pinned_competition_applicability_payload()

    assert proof.authority_sha256 == authority.authority_sha256
    assert proof.checked_payload_sha256 == payload["payload_sha256"]
    assert proof.endpoint_competition_cell_count == 555
    assert proof.parameter_axis_competition_cell_count == 560
    assert proof.alias_role_competition_cell_count == 635
    assert proof.endpoint_competition_cells_sha256 == payload["endpoint_competition_cells_sha256"]
    assert (
        proof.parameter_axis_competition_cells_sha256
        == payload["parameter_axis_competition_cells_sha256"]
    )
    assert (
        proof.alias_role_competition_cells_sha256 == payload["alias_role_competition_cells_sha256"]
    )
    verifier_source = Path(
        "src/nbadb/core/nba_api_competition_applicability_verifier.py"
    ).read_text()
    assert "from nbadb.core.nba_api_competition_applicability import" not in verifier_source


def test_independent_verifier_rejects_count_preserving_endpoint_cell_swap(
    tmp_path: Path,
) -> None:
    payload = deepcopy(build_pinned_competition_applicability_payload())
    rows = _rows(payload, "endpoint_competition_cells")
    rows[0]["provider_endpoint_id"], rows[5]["provider_endpoint_id"] = (
        rows[5]["provider_endpoint_id"],
        rows[0]["provider_endpoint_id"],
    )
    path = _candidate(
        tmp_path,
        payload,
        "endpoint_competition_cells",
        "endpoint-swap.json",
    )

    _assert_independent_rejection(path)


def test_independent_verifier_rejects_count_preserving_occurrence_axis_swap(
    tmp_path: Path,
) -> None:
    payload = deepcopy(build_pinned_competition_applicability_payload())
    rows = _rows(payload, "parameter_axis_competition_cells")
    rows[0]["provider_occurrence_id"], rows[5]["provider_occurrence_id"] = (
        rows[5]["provider_occurrence_id"],
        rows[0]["provider_occurrence_id"],
    )
    path = _candidate(
        tmp_path,
        payload,
        "parameter_axis_competition_cells",
        "axis-swap.json",
    )

    _assert_independent_rejection(path)


def test_independent_verifier_rejects_count_preserving_alias_role_swap(
    tmp_path: Path,
) -> None:
    payload = deepcopy(build_pinned_competition_applicability_payload())
    rows = _rows(payload, "alias_role_competition_cells")
    rows[0]["repo_endpoint_name"], rows[5]["repo_endpoint_name"] = (
        rows[5]["repo_endpoint_name"],
        rows[0]["repo_endpoint_name"],
    )
    path = _candidate(
        tmp_path,
        payload,
        "alias_role_competition_cells",
        "alias-swap.json",
    )

    _assert_independent_rejection(path)


def test_independent_verifier_rejects_support_evidence_kind_promotion(
    tmp_path: Path,
) -> None:
    payload = deepcopy(build_pinned_competition_applicability_payload())
    rows = _rows(payload, "endpoint_competition_cells")
    rows[0]["endpoint_support_status"] = "supported"
    rows[0]["endpoint_support_evidence_kind"] = "competition_existence_history"
    path = _candidate(
        tmp_path,
        payload,
        "endpoint_competition_cells",
        "history-promotion.json",
    )

    _assert_independent_rejection(path)


def test_independent_verifier_rejects_probe_required_to_available_mutation(
    tmp_path: Path,
) -> None:
    payload = deepcopy(build_pinned_competition_applicability_payload())
    rows = _rows(payload, "parameter_axis_competition_cells")
    rows[0]["probe_disposition"] = "available"
    rows[0]["provider_availability_status"] = "available"
    path = _candidate(
        tmp_path,
        payload,
        "parameter_axis_competition_cells",
        "available.json",
    )

    _assert_independent_rejection(path)


def test_independent_verifier_rejects_gl_alum_participant_temporal_binding_swap(
    tmp_path: Path,
) -> None:
    payload = deepcopy(build_pinned_competition_applicability_payload())
    rows = _rows(payload, "parameter_axis_competition_cells")
    person1 = next(
        row
        for row in rows
        if row["provider_occurrence_id"]
        == "parameter:stats:GLAlumBoxScoreSimilarityScore:0002:person1_league_id"
        and row["league_id"] == "00"
    )
    person2 = next(
        row
        for row in rows
        if row["provider_occurrence_id"]
        == "parameter:stats:GLAlumBoxScoreSimilarityScore:0005:person2_league_id"
        and row["league_id"] == "00"
    )
    person1["temporal_companion_occurrence_ids"], person2["temporal_companion_occurrence_ids"] = (
        person2["temporal_companion_occurrence_ids"],
        person1["temporal_companion_occurrence_ids"],
    )
    path = _candidate(
        tmp_path,
        payload,
        "parameter_axis_competition_cells",
        "gl-binding.json",
    )

    _assert_independent_rejection(path)


def test_independent_verifier_rejects_nba_default_substitution_for_other_competition(
    tmp_path: Path,
) -> None:
    payload = deepcopy(build_pinned_competition_applicability_payload())
    rows = _rows(payload, "parameter_axis_competition_cells")
    wnba = next(row for row in rows if row["league_id"] == "10")
    wnba["native_period_type"] = "season_label"
    path = _candidate(
        tmp_path,
        payload,
        "parameter_axis_competition_cells",
        "nba-season-substitution.json",
    )

    _assert_independent_rejection(path)


def test_independent_verifier_rejects_non_temporal_to_season_scoped_mutation(
    tmp_path: Path,
) -> None:
    payload = deepcopy(build_pinned_competition_applicability_payload())
    rows = _rows(payload, "parameter_axis_competition_cells")
    non_temporal = next(
        row
        for row in rows
        if row["provider_endpoint_id"] == "CommonPlayerInfo" and row["league_id"] == "00"
    )
    non_temporal["temporal_shape"] = "explicit_season"
    non_temporal["temporal_companion_occurrence_ids"] = [
        "parameter:stats:CommonPlayerInfo:9999:synthesized_season"
    ]
    path = _candidate(
        tmp_path,
        payload,
        "parameter_axis_competition_cells",
        "non-temporal-season.json",
    )

    _assert_independent_rejection(path)


@pytest.mark.parametrize("target", ["checked", "existence_source"])
def test_independent_verifier_rejects_noncanonical_source_or_checked_resource(
    tmp_path: Path,
    target: str,
) -> None:
    candidate = tmp_path / "candidate.json"
    candidate.write_bytes(
        _canonical_bytes(build_pinned_competition_applicability_payload()) + b"\n"
    )
    if target == "checked":
        candidate.write_bytes(b'{"schema_version":1,"schema_version":1}\n')
        with pytest.raises(NbaApiCompetitionApplicabilityVerificationError):
            verify_competition_applicability_authority_file(candidate)
    else:
        source = tmp_path / "existence.json"
        source.write_bytes(b"{}\n")
        with pytest.raises(NbaApiCompetitionApplicabilityVerificationError):
            verify_competition_applicability_authority_file(
                candidate,
                existence_source_path=source,
            )
