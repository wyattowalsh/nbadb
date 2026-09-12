from __future__ import annotations

import ast
import hashlib
import json
import pickle
from copy import copy, deepcopy
from dataclasses import fields, replace
from importlib import resources
from pathlib import Path
from typing import cast

import pytest

from nbadb.core import nba_api_implicit_competition_verifier as verifier_subject
from nbadb.core.nba_api_implicit_competition_verifier import (
    IndependentImplicitCompetitionProof,
    verify_pinned_implicit_competition_authority,
)

_RESOURCE = Path("src/nbadb/contracts/nba_api_implicit_competition_v1_11_4.json")
_VERIFIER_SOURCE = Path("src/nbadb/core/nba_api_implicit_competition_verifier.py")


class _BytesResource:
    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    def read_bytes(self) -> bytes:
        return self._raw


class _ResourceOverrideRoot:
    def __init__(self, base: object, parts: tuple[str, ...], raw: bytes) -> None:
        self._base = base
        self._parts = parts
        self._raw = raw

    def joinpath(self, *parts: str) -> object:
        if parts == self._parts:
            return _BytesResource(self._raw)
        return self._base.joinpath(*parts)  # type: ignore[attr-defined,no-any-return]


def _override_packaged_bytes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    package: str,
    parts: tuple[str, ...],
    raw: bytes,
) -> None:
    real_files = verifier_subject.resources.files

    def overridden_files(package_name: str) -> object:
        base = real_files(package_name)
        if package_name != package:
            return base
        return _ResourceOverrideRoot(base, parts, raw)

    monkeypatch.setattr(verifier_subject.resources, "files", overridden_files)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _pretty_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _payload() -> dict[str, object]:
    return cast("dict[str, object]", json.loads(_RESOURCE.read_text(encoding="utf-8")))


def _array(payload: dict[str, object], name: str) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", payload[name])


def _reseal(payload: dict[str, object]) -> bytes:
    for row in _array(payload, "endpoint_bindings"):
        body = dict(row)
        body.pop("binding_sha256", None)
        row["binding_sha256"] = _digest(body)
    for name in (
        "endpoint_bindings",
        "alias_bindings",
        "physical_competition_cells",
        "alias_competition_cells",
    ):
        payload[f"{name}_sha256"] = _digest(payload[name])
    authority = dict(payload)
    authority.pop("authority_sha256", None)
    authority.pop("payload_sha256", None)
    payload["authority_sha256"] = _digest(authority)
    envelope = dict(payload)
    envelope.pop("payload_sha256", None)
    payload["payload_sha256"] = _digest(envelope)
    return _pretty_bytes(payload)


def _candidate(tmp_path: Path, payload: dict[str, object], name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(_reseal(payload))
    return path


def _assert_rejected(path: Path) -> None:
    with pytest.raises(ValueError, match="differs from independent sources"):
        verify_pinned_implicit_competition_authority(path)


def _binding(payload: dict[str, object], alias: str) -> dict[str, object]:
    return next(
        row for row in _array(payload, "endpoint_bindings") if row["repo_endpoint_name"] == alias
    )


def _refresh_cell_binding(
    payload: dict[str, object],
    *,
    old_digest: str,
    binding: dict[str, object],
) -> None:
    body = dict(binding)
    body.pop("binding_sha256", None)
    new_digest = _digest(body)
    binding["binding_sha256"] = new_digest
    for array_name in ("physical_competition_cells", "alias_competition_cells"):
        for cell in _array(payload, array_name):
            if cell["root_binding_sha256"] == old_digest:
                cell["root_binding_sha256"] = new_digest
                cell["root_kind"] = binding["root_kind"]
                cell["physical_endpoint_key"] = binding["physical_endpoint_key"]
                cell["provider_endpoint_id"] = binding["provider_endpoint_id"]
                cell["source_family"] = binding["source_family"]
                prefix = "physical" if array_name == "physical_competition_cells" else "alias"
                identity = (
                    binding["physical_endpoint_key"]
                    if prefix == "physical"
                    else binding["repo_endpoint_name"]
                )
                cell["cell_id"] = f"{prefix}:{identity}:{cell['league_id']}"


def _assert_import_independence() -> None:
    source = _VERIFIER_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_VERIFIER_SOURCE))
    forbidden = {
        "nbadb.contracts.implicit_competition_source_authority",
        "nbadb.contracts.implicit_competition_source_authority_loader",
        "nbadb.contracts.implicit_competition_source_authority_pin",
        "nbadb.core.nba_api_implicit_competition",
    }
    forbidden_leaves = {module.rsplit(".", 1)[-1] for module in forbidden}

    def is_forbidden_module(name: str) -> bool:
        normalized = name.lstrip(".")
        return (
            normalized in forbidden
            or normalized.rsplit(".", 1)[-1] in forbidden_leaves
            or any(normalized.startswith(f"{module}.") for module in forbidden)
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(not is_forbidden_module(alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert not is_forbidden_module(module)
            assert all(
                not is_forbidden_module(f"{module}.{alias.name}" if module else alias.name)
                for alias in node.names
            )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not is_forbidden_module(node.value)
    assert all(module not in source for module in forbidden)


def test_independent_implicit_competition_authority_matches_primary() -> None:
    _assert_import_independence()
    proof = verify_pinned_implicit_competition_authority()
    payload = _payload()

    assert isinstance(proof, IndependentImplicitCompetitionProof)
    assert proof.verifier_id == "nbadb_independent_implicit_competition_v1"
    assert proof.candidate_authority_sha256 == payload["authority_sha256"]
    assert proof.candidate_payload_sha256 == payload["payload_sha256"]
    assert proof.endpoint_binding_count == proof.alias_binding_count == 36
    assert proof.physical_cell_count == proof.alias_cell_count == 180
    assert proof.cumulative_physical_competition_cell_count == 735
    assert proof.cumulative_parameter_axis_count == 148
    assert proof.cumulative_parameter_axis_cell_count == 740
    assert proof.cumulative_projected_alias_role_count == 163
    assert proof.cumulative_alias_role_cell_count == 815
    assert proof.missing_ids == proof.foreign_ids == proof.mismatched_ids == ()
    with pytest.raises(ValueError, match="proof digest"):
        replace(proof, proof_sha256="0" * 64)
    with pytest.raises(ValueError, match="exact empty concrete tuple"):
        replace(proof, missing_ids=("foreign",))
    with pytest.raises(ValueError, match="is not exact"):
        replace(proof, endpoint_binding_count=True)  # type: ignore[arg-type]

    class PathSubclass(type(Path())):
        pass

    with pytest.raises(ValueError, match="candidate path must be an exact Path"):
        verify_pinned_implicit_competition_authority(PathSubclass(_RESOURCE))

    class StringSubclass(str):
        pass

    class IntSubclass(int):
        pass

    class TupleSubclass(tuple):
        pass

    string_fields = (
        "verifier_id",
        "task_packet_sha256",
        "evidence_sha256",
        "evidence_authority_sha256",
        "source_review_sha256",
        "source_review_authority_sha256",
        "candidate_authority_sha256",
        "candidate_payload_sha256",
        "endpoint_bindings_sha256",
        "alias_bindings_sha256",
        "physical_competition_cells_sha256",
        "alias_competition_cells_sha256",
        "proof_sha256",
    )
    count_fields = (
        "endpoint_binding_count",
        "alias_binding_count",
        "physical_cell_count",
        "alias_cell_count",
        "cumulative_physical_competition_cell_count",
        "cumulative_parameter_axis_count",
        "cumulative_parameter_axis_cell_count",
        "cumulative_projected_alias_role_count",
        "cumulative_alias_role_cell_count",
    )
    result_fields = ("missing_ids", "foreign_ids", "mismatched_ids")
    foreign_identity_fields = (
        "task_packet_sha256",
        "evidence_sha256",
        "evidence_authority_sha256",
        "source_review_sha256",
        "source_review_authority_sha256",
        "candidate_authority_sha256",
        "candidate_payload_sha256",
        "endpoint_bindings_sha256",
        "alias_bindings_sha256",
        "physical_competition_cells_sha256",
        "alias_competition_cells_sha256",
    )
    proof_constructor = {field.name: getattr(proof, field.name) for field in fields(proof)}
    exact_body = {
        field.name: getattr(proof, field.name)
        for field in fields(proof)
        if field.name != "proof_sha256"
    }

    def resealed_updates(changes: dict[str, object]) -> dict[str, object]:
        body = {**exact_body, **changes}
        return {**changes, "proof_sha256": _digest(body)}

    for name in string_fields:
        with pytest.raises(ValueError, match="must be an exact str"):
            replace(proof, **{name: StringSubclass(cast("str", getattr(proof, name)))})

    for name in count_fields:
        for value in (IntSubclass(cast("int", getattr(proof, name))), True):
            with pytest.raises(ValueError, match="is not exact"):
                replace(proof, **{name: value})

    for name in result_fields:
        with pytest.raises(ValueError, match="exact empty concrete tuple"):
            replace(proof, **{name: TupleSubclass(cast("tuple[str, ...]", getattr(proof, name)))})
        with pytest.raises(ValueError, match="exact empty concrete tuple"):
            replace(proof, **{name: []})
        subclass_item_update = resealed_updates({name: (StringSubclass(f"foreign-{name}"),)})
        with pytest.raises(ValueError, match="exact empty concrete tuple"):
            replace(proof, **subclass_item_update)

    for name in exact_body:
        if name == "verifier_id":
            changes: dict[str, object] = {name: "foreign-verifier"}
            expected_error = "verifier ID"
        elif name in foreign_identity_fields:
            changes = {name: _digest({"one_at_a_time_foreign_identity": name})}
            expected_error = "binding differs from the independently derived"
        elif name in count_fields:
            changes = {name: cast("int", getattr(proof, name)) + 1}
            expected_error = "is not exact"
        elif name in result_fields:
            changes = {name: (f"foreign-{name}",)}
            expected_error = "exact empty concrete tuple"
        else:
            raise AssertionError(f"unclassified proof body field: {name}")
        with pytest.raises(ValueError, match=expected_error):
            replace(proof, **resealed_updates(changes))

    foreign_identity_changes: dict[str, object] = {
        name: _digest({"foreign_proof_identity": name}) for name in foreign_identity_fields
    }
    foreign_updates = resealed_updates(foreign_identity_changes)
    foreign_body = {
        **exact_body,
        **foreign_identity_changes,
    }
    with pytest.raises(ValueError, match="binding differs from the independently derived"):
        replace(proof, **foreign_updates)

    fake_context: dict[str, object] = {
        "binding": exact_body,
        "provenance_sha256": _digest(exact_body),
        "token": "external-fake-token",
    }
    copied_context = deepcopy(fake_context)
    mutated_context = deepcopy(fake_context)
    mutated_context["binding"] = foreign_body
    mutated_context["provenance_sha256"] = _digest(foreign_body)
    resealed_context = {
        **mutated_context,
        "context_sha256": _digest(mutated_context),
    }
    for external_context in (
        fake_context,
        copied_context,
        mutated_context,
        resealed_context,
    ):
        with pytest.raises(TypeError, match="_validation_context"):
            IndependentImplicitCompetitionProof(
                **proof_constructor,
                _validation_context=external_context,
            )

    assert proof.validated_payload() == proof_constructor
    assert copy(proof) is proof
    assert deepcopy(proof) is proof
    restored = pickle.loads(pickle.dumps(proof))
    assert type(restored) is IndependentImplicitCompetitionProof
    assert restored.validated_payload() == proof_constructor

    tampered = IndependentImplicitCompetitionProof(**proof_constructor)
    for name, value in foreign_updates.items():
        object.__setattr__(tampered, name, value)
    with pytest.raises(ValueError, match="binding differs from the independently derived"):
        tampered.validated_payload()
    with pytest.raises(ValueError, match="binding differs from the independently derived"):
        copy(tampered)
    with pytest.raises(ValueError, match="binding differs from the independently derived"):
        deepcopy(tampered)
    with pytest.raises(ValueError, match="binding differs from the independently derived"):
        pickle.dumps(tampered)


def test_independent_verifier_rejects_current_source_sidecar_tamper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = verifier_subject._CURRENT_SOURCE_RESOURCE
    raw = resources.files("nbadb.contracts").joinpath(resource).read_bytes()
    _override_packaged_bytes(
        monkeypatch,
        package="nbadb.contracts",
        parts=(resource,),
        raw=raw + b"\n",
    )

    with pytest.raises(
        ValueError,
        match="current implicit-competition source authority raw identity drifted",
    ):
        verify_pinned_implicit_competition_authority()


def test_independent_verifier_rejects_current_source_binding_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relative = "src/nbadb/extract/live/endpoints.py"
    parts = tuple(relative.removeprefix("src/nbadb/").split("/"))
    raw = resources.files("nbadb").joinpath(*parts).read_bytes()
    _override_packaged_bytes(
        monkeypatch,
        package="nbadb",
        parts=parts,
        raw=raw + b"\n# hostile current-source drift\n",
    )

    with pytest.raises(
        ValueError,
        match="current source binding differs from packaged source",
    ):
        verify_pinned_implicit_competition_authority()


def test_independent_verifier_rejects_count_preserving_explicit_implicit_endpoint_swap(
    tmp_path: Path,
) -> None:
    payload = deepcopy(_payload())
    row = _array(payload, "endpoint_bindings")[0]
    old_digest = str(row["binding_sha256"])
    row["provider_endpoint_id"] = "AllTimeLeadersGrids"
    row["physical_endpoint_key"] = "stats:AllTimeLeadersGrids"
    _refresh_cell_binding(payload, old_digest=old_digest, binding=row)
    alias = next(
        item
        for item in _array(payload, "alias_bindings")
        if item["repo_endpoint_name"] == row["repo_endpoint_name"]
    )
    alias["provider_endpoint_id"] = row["provider_endpoint_id"]

    _assert_rejected(_candidate(tmp_path, payload, "explicit-implicit-swap.json"))


def test_independent_verifier_rejects_count_preserving_alias_binding_swap(
    tmp_path: Path,
) -> None:
    payload = deepcopy(_payload())
    rows = _array(payload, "alias_bindings")
    rows[0]["repo_endpoint_name"], rows[1]["repo_endpoint_name"] = (
        rows[1]["repo_endpoint_name"],
        rows[0]["repo_endpoint_name"],
    )

    _assert_rejected(_candidate(tmp_path, payload, "alias-swap.json"))


def test_independent_verifier_rejects_game_team_or_player_root_kind_swap(
    tmp_path: Path,
) -> None:
    payload = deepcopy(_payload())
    player = _binding(payload, "player_awards")
    team = _binding(payload, "team_details")
    player_old = str(player["binding_sha256"])
    team_old = str(team["binding_sha256"])
    player["root_kind"], team["root_kind"] = team["root_kind"], player["root_kind"]
    _refresh_cell_binding(payload, old_digest=player_old, binding=player)
    _refresh_cell_binding(payload, old_digest=team_old, binding=team)

    _assert_rejected(_candidate(tmp_path, payload, "root-kind-swap.json"))


def test_independent_verifier_rejects_request_root_occurrence_digest_swap(
    tmp_path: Path,
) -> None:
    payload = deepcopy(_payload())
    first = _binding(payload, "box_score_advanced")
    second = _binding(payload, "play_by_play")
    first_old = str(first["binding_sha256"])
    second_old = str(second["binding_sha256"])
    first_root = cast("dict[str, object]", first["root_evidence"])
    first_parameter = cast("dict[str, object]", first_root["parameter"])
    second_parameter = cast(
        "dict[str, object]", cast("dict[str, object]", second["root_evidence"])["parameter"]
    )
    first_parameter["source_signature_sha256"], second_parameter["source_signature_sha256"] = (
        second_parameter["source_signature_sha256"],
        first_parameter["source_signature_sha256"],
    )
    first_parameter["typed_domain_sha256"], second_parameter["typed_domain_sha256"] = (
        second_parameter["typed_domain_sha256"],
        first_parameter["typed_domain_sha256"],
    )
    _refresh_cell_binding(payload, old_digest=first_old, binding=first)
    _refresh_cell_binding(payload, old_digest=second_old, binding=second)

    _assert_rejected(_candidate(tmp_path, payload, "request-digest-swap.json"))


def test_independent_verifier_rejects_odds_game_id_path_swap(tmp_path: Path) -> None:
    payload = deepcopy(_payload())
    odds = _binding(payload, "live_odds")
    old_digest = str(odds["binding_sha256"])
    root = cast("dict[str, object]", odds["root_evidence"])
    root["live_raw_root_evidence_sha256"] = _digest(
        {
            "game_id_json_path": "$.games.gameID",
            "provider_endpoint_id": "Odds",
        }
    )
    _refresh_cell_binding(payload, old_digest=old_digest, binding=odds)

    _assert_rejected(_candidate(tmp_path, payload, "odds-path-swap.json"))


def test_independent_verifier_rejects_scoreboard_league_or_game_path_swap(
    tmp_path: Path,
) -> None:
    payload = deepcopy(_payload())
    scoreboard = _binding(payload, "live_score_board")
    old_digest = str(scoreboard["binding_sha256"])
    root = cast("dict[str, object]", scoreboard["root_evidence"])
    root["live_raw_root_evidence_sha256"] = _digest(
        {
            "game_id_json_path": "$.scoreboard.game.gameId",
            "league_id_json_path": "$.scoreboard.leagueID",
            "provider_endpoint_id": "ScoreBoard",
        }
    )
    _refresh_cell_binding(payload, old_digest=old_digest, binding=scoreboard)

    _assert_rejected(_candidate(tmp_path, payload, "scoreboard-path-swap.json"))


def test_independent_verifier_rejects_static_nba_wnba_mapping_swap(tmp_path: Path) -> None:
    payload = deepcopy(_payload())
    nba = _binding(payload, "static_players")
    wnba = _binding(payload, "static_wnba_players")
    nba_old = str(nba["binding_sha256"])
    wnba_old = str(wnba["binding_sha256"])
    nba["root_evidence"], wnba["root_evidence"] = wnba["root_evidence"], nba["root_evidence"]
    _refresh_cell_binding(payload, old_digest=nba_old, binding=nba)
    _refresh_cell_binding(payload, old_digest=wnba_old, binding=wnba)

    _assert_rejected(_candidate(tmp_path, payload, "static-mapping-swap.json"))


def test_independent_verifier_rejects_static_source_symbol_or_rows_digest_swap(
    tmp_path: Path,
) -> None:
    payload = deepcopy(_payload())
    static = _binding(payload, "static_teams")
    old_digest = str(static["binding_sha256"])
    root = cast("dict[str, object]", static["root_evidence"])
    root["static_chain_sha256"] = _digest(
        {
            "dataset_id": "static_teams",
            "source_rows_sha256": "0" * 64,
            "source_symbol": "wnba_teams",
        }
    )
    _refresh_cell_binding(payload, old_digest=old_digest, binding=static)

    _assert_rejected(_candidate(tmp_path, payload, "static-source-swap.json"))


def test_independent_verifier_rejects_same_identifier_competition_mutation(
    tmp_path: Path,
) -> None:
    payload = deepcopy(_payload())
    rows = _array(payload, "physical_competition_cells")
    nba = next(
        row
        for row in rows
        if row["physical_endpoint_key"] == "stats:BoxScoreAdvancedV3" and row["league_id"] == "00"
    )
    wnba = next(
        row
        for row in rows
        if row["physical_endpoint_key"] == "stats:BoxScoreAdvancedV3" and row["league_id"] == "10"
    )
    wnba["league_id"] = nba["league_id"]
    wnba["symbol"] = nba["symbol"]
    wnba["cell_id"] = nba["cell_id"]

    _assert_rejected(_candidate(tmp_path, payload, "same-id-competition.json"))


def test_independent_verifier_rejects_unknown_to_available_mutation(tmp_path: Path) -> None:
    payload = deepcopy(_payload())
    _array(payload, "physical_competition_cells")[0]["provider_availability_status"] = "available"

    _assert_rejected(_candidate(tmp_path, payload, "available.json"))


def test_independent_verifier_rejects_nba_url_or_default_promotion(tmp_path: Path) -> None:
    payload = deepcopy(_payload())
    row = _array(payload, "endpoint_bindings")[0]
    old_digest = str(row["binding_sha256"])
    row["competition_inference"] = {
        "default": "LeagueID.default",
        "url_suffix": "_00",
    }
    _refresh_cell_binding(payload, old_digest=old_digest, binding=row)

    _assert_rejected(_candidate(tmp_path, payload, "nba-default.json"))


def test_independent_verifier_rejects_predecessor_or_source_review_digest_drift(
    tmp_path: Path,
) -> None:
    payload = deepcopy(_payload())
    authorities = cast("dict[str, object]", payload["source_authorities"])
    review = cast("dict[str, object]", authorities["independent_source_review"])
    receipts = cast("dict[str, object]", authorities["predecessor_receipts"])
    review["sha256"] = "0" * 64
    receipts["A1.2c_review"] = "1" * 64

    _assert_rejected(_candidate(tmp_path, payload, "authority-drift.json"))
