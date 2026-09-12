"""Independent no-network verifier for competition applicability.

This verifier intentionally does not import the primary applicability module.
It authenticates the historical A1.2c packet and its three sealed evidence
inputs, separately binds the current checked predecessors, independently
expands all 1,750 typed cells, and requires exact equality with the candidate.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import TYPE_CHECKING, Final, cast

if TYPE_CHECKING:
    from pathlib import Path

_SCHEMA_VERSION: Final = 1
_RESOURCE: Final = "nba_api_competition_applicability_v1_11_4.json"
_PACKAGED_PROVENANCE_ROOT: Final = (
    "provenance",
    "nba_api_v1_11_4",
    "competition_applicability",
)
_EXISTENCE_SOURCE: Final = (
    "artifacts/assurance/complete-nba-api-sink/A1.2c/source-inputs/"
    "competition-existence-evidence.json"
)
_SUPPORT_SOURCE: Final = (
    "artifacts/assurance/complete-nba-api-sink/A1.2c/source-inputs/endpoint-support-evidence.json"
)
_SOURCE_REVIEW: Final = (
    "artifacts/assurance/complete-nba-api-sink/A1.2c/source-inputs/source-review.json"
)
_TASK_PACKET: Final = "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.2c.json"
_COMPETITION_RESOURCE: Final = "nba_api_competition_v1_11_4.json"
_OCCURRENCE_RESOURCE: Final = "nba_api_competition_occurrences_v1_11_4.json"
_REQUEST_RESOURCE: Final = "nba_api_request_surface_v1_11_4.json"
_TASK_PACKET_SHA256: Final = "d2f668cd0627562508849423c5df5d8e0e120a2fecc270a44699c9fe4458bf91"
_HISTORICAL_AUTHORITY_INPUTS_SHA256: Final = (
    "130c673ae6442f99cb5d94f243164b5a0b2d84211ea1c999423bbe6a51622d5f"
)
_HISTORICAL_CHECKED_AUTHORITIES_SHA256: Final = (
    "4fb2c5003de66ad0a2a94da7c043370a9f6fe2ad1e718df54ec7dacacb77b138"
)
_HISTORICAL_OPENING_ROWS_SHA256: Final = (
    "a94f22cba94539250b6a1e1c8be199dcf903b102f5290ee5ed4ece343bfcac90"
)
_HISTORICAL_SUCCESSOR_PATHS_SHA256: Final = (
    "99bd793926effc6edaa01c8796c3016410d45040a54e83ff881359f4055f782b"
)
_HISTORICAL_SUCCESSOR_PATHS: Final = (
    "src/nbadb/core/nba_api_request_surface.py",
    "src/nbadb/core/nba_api_request_surface_verifier.py",
    "src/nbadb/contracts/nba_api_request_surface_v1_11_4.json",
    "src/nbadb/contracts/nba_api_competition_occurrences_v1_11_4.json",
)
_HISTORICAL_OPENING_ROWS: Final = (
    {
        "path": "src/nbadb/core/nba_api_request_surface.py",
        "sha256": "ff5f5bc589876a5b624f93692f8a43021cf3a2465a9cdd18475c3497dab0fc96",
    },
    {
        "path": "src/nbadb/core/nba_api_request_surface_verifier.py",
        "sha256": "e85960d3577daf967136ef31f519ea03f27c849d58e1450ee86ab88cf5959308",
    },
    {
        "path": "src/nbadb/contracts/nba_api_request_surface_v1_11_4.json",
        "sha256": "c5b1de0b1e6e05541eec90df9c92ce3ca9e3c1cae490fe6723410137f947e608",
    },
    {
        "path": "src/nbadb/contracts/nba_api_competition_occurrences_v1_11_4.json",
        "sha256": "28f72468be47dce5b13429e43140f96277422892ee8dc21ab723ef1c606bc700",
    },
)
_EXPECTED_HASHES: Final = {
    _EXISTENCE_SOURCE: "876f79c748faa1f477dee8f15071d1799ad423d7e3b32e5b38e7c56cb34ccfa6",
    _SUPPORT_SOURCE: "6db164143c588092acbd2c8497b068a770ff5a39501d1c05e28ef638b6fb6cfb",
    _SOURCE_REVIEW: "accdd459d72d58be7c8b83f9c17e2e2086c058f3112b7714f4f0ea33e588f589",
    _COMPETITION_RESOURCE: ("cfb93458f5efb569995ddccaf33ae37c0c312e25e09d0649c307999ec0057c44"),
    _OCCURRENCE_RESOURCE: ("8bd3365806aa3118e3ec265a6e70647390b54aab203050805c59b6e6d9bce459"),
    _REQUEST_RESOURCE: ("3082def2aa92b35d55107f5ce8eaf2ffa0532a0e649899d0f1180979f6144981"),
}
_CURRENT_REQUEST_AUTHORITY: Final = {
    "payload_sha256": "b310313f41cf97cf1b8f55e01bbe95868532f3008527bf5265a985628eca9052",
    "resource": _REQUEST_RESOURCE,
    "resource_sha256": _EXPECTED_HASHES[_REQUEST_RESOURCE],
    "schema_version": 3,
    "surface_sha256": "ef6195829a9f1dad9f847094b79e88fae24dffc5c4df18e3d3e972f347f83733",
}
_CURRENT_OCCURRENCE_AUTHORITY: Final = {
    "authority_sha256": "4ef38c7ee185ff10fea4b4de611648af1b30be04f700399549233e809cd53935",
    "payload_sha256": "ed06098b67f31e19eca8d9d1e51b25d03681c3d7c0ecfae4b83e84dd7642f179",
    "schema_version": 1,
    "upstream_request_surface": {
        "payload_sha256": _CURRENT_REQUEST_AUTHORITY["payload_sha256"],
        "resource": _REQUEST_RESOURCE,
        "resource_sha256": _EXPECTED_HASHES[_REQUEST_RESOURCE],
        "surface_sha256": _CURRENT_REQUEST_AUTHORITY["surface_sha256"],
    },
}
_HISTORICAL_CHECKED_AUTHORITIES: Final = {
    "competition_existence_context": {
        "authority_sha256": "27f4a84f9ff26caaa8b07234975dc645c386742e6bfbb43522f743d3b31998ad",
        "payload_sha256": "ff113ddb858aa78ea23c3c63fe79dfdb67e548156d26c2db57cae01d7669bc5b",
        "resource_sha256": _EXPECTED_HASHES[_EXISTENCE_SOURCE],
        "schema": "CompetitionExistenceEvidenceV1",
    },
    "competition_occurrences": {
        "authority_sha256": "1b6c41f6a89ec9c74bc3ac1c4c0fff9aa517cd1842363055d7cc48e5854c4f64",
        "payload_sha256": "d459a37fd49ee86bcd68a81e7659c9e8eb5cd57e86b896c37370e61c7801b264",
        "resource_sha256": "28f72468be47dce5b13429e43140f96277422892ee8dc21ab723ef1c606bc700",
        "schema_version": 1,
    },
    "competition_values": {
        "authority_sha256": "61c9477221c08f4f36269c8c3050171e0ec472508a0a8ac72ddc6f42d865ef98",
        "payload_sha256": "1e79989c9d75d671520d868dfa4e63bc828ceb7844c64b28e7325dd11a6ce7e0",
        "resource_sha256": _EXPECTED_HASHES[_COMPETITION_RESOURCE],
        "schema_version": 1,
    },
    "request_surface": {
        "payload_sha256": "55fead813bab8a8f012f065d1d8ad41e0dfa88423b347215702c8e4a1410861b",
        "resource_sha256": "c5b1de0b1e6e05541eec90df9c92ce3ca9e3c1cae490fe6723410137f947e608",
        "schema_version": 2,
        "surface_sha256": "e240dc4c551f571aa46d8c7e6124c63c85e189d688c5bf3b78814b66c3cb9605",
    },
}
_EXPECTED_AUTHORITIES: Final = {
    _EXISTENCE_SOURCE: "27f4a84f9ff26caaa8b07234975dc645c386742e6bfbb43522f743d3b31998ad",
    _SUPPORT_SOURCE: "cfaf6b690e9d27c562813df964db05ed945f8430a8a395255643225247ddb7fd",
    _SOURCE_REVIEW: "d626977d4299847eabf5fe84b74551257fdb6552d64bf4fead93380b04749429",
}
_LEAGUE_IDS: Final = ("00", "01", "10", "15", "20")
_TEMPORAL_SHAPE_COUNTS: Final = {
    "date_or_date_range_only": 3,
    "explicit_season": 96,
    "no_temporal_parameter": 7,
    "participant_season_axis": 2,
    "season_type_only": 4,
}
_ALIAS_TEMPORAL_SHAPE_COUNTS: Final = {
    "date_or_date_range_only": 3,
    "explicit_season": 110,
    "no_temporal_parameter": 7,
    "participant_season_axis": 2,
    "season_type_only": 5,
}
_NON_TEMPORAL: Final = (
    "CommonPlayerInfo",
    "CommonTeamYears",
    "FranchiseHistory",
    "FranchiseLeaders",
    "GameRotation",
    "PlayerCareerStats",
    "PlayerProfileV2",
)
_SEASON_TYPE_ONLY: Final = (
    "AllTimeLeadersGrids",
    "FranchisePlayers",
    "PlayerNextNGames",
    "TeamYearByYearStats",
)
_DATE_ONLY: Final = ("ScoreboardV2", "ScoreboardV3", "VideoStatus")
_GL_BINDINGS: Final = {
    "parameter:stats:GLAlumBoxScoreSimilarityScore:0002:person1_league_id": (
        "parameter:stats:GLAlumBoxScoreSimilarityScore:0003:person1_season_year",
        "parameter:stats:GLAlumBoxScoreSimilarityScore:0004:person1_season_type",
    ),
    "parameter:stats:GLAlumBoxScoreSimilarityScore:0005:person2_league_id": (
        "parameter:stats:GLAlumBoxScoreSimilarityScore:0006:person2_season_year",
        "parameter:stats:GLAlumBoxScoreSimilarityScore:0007:person2_season_type",
    ),
}
_EVIDENCE_LAYERS: Final = {
    "competition_existence": (
        "official-source native-period existence gates probe eligibility only"
    ),
    "endpoint_request_contract_support": (
        "pinned declared axes are not endpoint-specific support evidence"
    ),
    "provider_availability": (
        "provider availability remains unknown until later receipt-bound probing"
    ),
}
_VERIFIER_ID: Final = "nbadb_independent_competition_applicability_sources_v1"
_SHA256_RE = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)
_SEASON_RE = re.compile(r"([0-9]{4})-([0-9]{2})", flags=re.ASCII)


class NbaApiCompetitionApplicabilityVerificationError(ValueError):
    """Independent applicability verification failed closed."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NbaApiCompetitionApplicabilityVerificationError(
            "applicability proof is not canonical JSON"
        ) from exc


def _pretty_bytes(value: object) -> bytes:
    try:
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
    except (TypeError, ValueError) as exc:
        raise NbaApiCompetitionApplicabilityVerificationError(
            "applicability source is not canonical JSON"
        ) from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise NbaApiCompetitionApplicabilityVerificationError(
            f"{field} must be a canonical SHA-256"
        )
    return value


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise NbaApiCompetitionApplicabilityVerificationError(
                f"applicability input contains duplicate object key: {key}"
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise NbaApiCompetitionApplicabilityVerificationError(
        f"applicability input contains non-finite JSON constant: {value}"
    )


def _parse(raw: bytes, *, label: str, pretty: bool) -> dict[str, object]:
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except NbaApiCompetitionApplicabilityVerificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NbaApiCompetitionApplicabilityVerificationError(f"{label} cannot be decoded") from exc
    expected = _pretty_bytes(payload) if pretty else _canonical_bytes(payload) + b"\n"
    if not isinstance(payload, dict) or raw != expected:
        raise NbaApiCompetitionApplicabilityVerificationError(
            f"{label} bytes are not canonical JSON"
        )
    return cast("dict[str, object]", payload)


def _read_path(path: Path, *, label: str, pretty: bool) -> tuple[bytes, dict[str, object]]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise NbaApiCompetitionApplicabilityVerificationError(f"{label} cannot be read") from exc
    return raw, _parse(raw, label=label, pretty=pretty)


def _read_packaged_provenance(
    relative: str, *, label: str, pretty: bool
) -> tuple[bytes, dict[str, object]]:
    if relative not in {
        _EXISTENCE_SOURCE,
        _SUPPORT_SOURCE,
        _SOURCE_REVIEW,
        _TASK_PACKET,
    }:
        raise NbaApiCompetitionApplicabilityVerificationError(f"{label} has no packaged authority")
    try:
        raw = (
            resources.files("nbadb.contracts")
            .joinpath(*_PACKAGED_PROVENANCE_ROOT, relative.rsplit("/", 1)[-1])
            .read_bytes()
        )
    except (AttributeError, OSError) as exc:
        raise NbaApiCompetitionApplicabilityVerificationError(f"{label} cannot be read") from exc
    return raw, _parse(raw, label=label, pretty=pretty)


def _read_contract(resource: str) -> tuple[bytes, dict[str, object]]:
    try:
        raw = resources.files("nbadb.contracts").joinpath(resource).read_bytes()
    except (AttributeError, OSError) as exc:
        raise NbaApiCompetitionApplicabilityVerificationError(
            f"checked predecessor resource cannot be read: {resource}"
        ) from exc
    if hashlib.sha256(raw).hexdigest() != _EXPECTED_HASHES[resource]:
        raise NbaApiCompetitionApplicabilityVerificationError(
            f"checked predecessor resource hash drifted: {resource}"
        )
    return raw, _parse(raw, label=resource, pretty=False)


def _verify_envelope(payload: dict[str, object], *, label: str) -> None:
    body = dict(payload)
    payload_sha256 = body.pop("payload_sha256", None)
    if _require_digest(payload_sha256, f"{label} payload_sha256") != _digest(body):
        raise NbaApiCompetitionApplicabilityVerificationError(f"{label} payload digest is invalid")


def _period_index(value: object, native_type: str) -> int:
    if native_type == "season_label":
        if not isinstance(value, str):
            raise NbaApiCompetitionApplicabilityVerificationError(
                "season-label interval contains a non-string native period"
            )
        match = _SEASON_RE.fullmatch(value)
        if match is None or int(match.group(2)) != (int(match.group(1)) + 1) % 100:
            raise NbaApiCompetitionApplicabilityVerificationError(
                "season-label interval is not exact consecutive ASCII YYYY-YY"
            )
        return int(match.group(1))
    if native_type in {"calendar_year", "event_year"}:
        if isinstance(value, bool) or not isinstance(value, int):
            raise NbaApiCompetitionApplicabilityVerificationError(
                "calendar/event interval contains an NBA-style season substitution"
            )
        return value
    raise NbaApiCompetitionApplicabilityVerificationError(
        "competition interval native period type is unknown"
    )


def _verify_source_payload(
    raw: bytes,
    payload: dict[str, object],
    *,
    relative: str,
    exact_path: bool,
) -> None:
    _verify_envelope(payload, label=relative)
    if exact_path and hashlib.sha256(raw).hexdigest() != _EXPECTED_HASHES[relative]:
        raise NbaApiCompetitionApplicabilityVerificationError(
            f"sealed source input hash drifted: {relative}"
        )
    if payload.get("authority_sha256") != _EXPECTED_AUTHORITIES[relative]:
        raise NbaApiCompetitionApplicabilityVerificationError(
            f"sealed source authority drifted: {relative}"
        )
    canonicalization = payload.get("canonicalization")
    if not isinstance(canonicalization, dict):
        raise NbaApiCompetitionApplicabilityVerificationError(
            f"sealed source canonicalization is missing: {relative}"
        )
    if relative == _EXISTENCE_SOURCE:
        fields = (
            "authority_exclusions",
            "competition_count",
            "competitions_sha256",
            "evidence_scope",
            "provider_availability_claim_count",
            "revalidation_sha256",
            "retrieval_date",
            "source_count",
            "source_url_inventory_sha256",
            "sources_sha256",
            "typed_endpoint_support_claim_count",
        )
    else:
        field_rows = canonicalization.get("authority_sha256_fields")
        if not isinstance(field_rows, list) or not all(
            isinstance(item, str) for item in field_rows
        ):
            raise NbaApiCompetitionApplicabilityVerificationError(
                f"sealed source authority field list is invalid: {relative}"
            )
        fields = tuple(cast("list[str]", field_rows))
    if payload.get("authority_sha256") != _digest({field: payload.get(field) for field in fields}):
        raise NbaApiCompetitionApplicabilityVerificationError(
            f"sealed source authority digest is invalid: {relative}"
        )


def _validate_historical_task_packet(
    raw: bytes,
    packet: dict[str, object],
    support: dict[str, object],
) -> None:
    if hashlib.sha256(raw).hexdigest() != _TASK_PACKET_SHA256:
        raise NbaApiCompetitionApplicabilityVerificationError(
            "historical A1.2c task packet drifted"
        )
    if packet.get("schema") != "TaskPacketV1" or packet.get("task_id") != "A1.2c":
        raise NbaApiCompetitionApplicabilityVerificationError(
            "historical A1.2c task packet identity is invalid"
        )
    immutable_rows = packet.get("immutable_inputs")
    if (
        not isinstance(immutable_rows, list)
        or len(immutable_rows) != 27
        or not all(
            isinstance(item, dict)
            and set(item) == {"path", "sha256"}
            and isinstance(item.get("path"), str)
            and bool(item.get("path"))
            and isinstance(item.get("sha256"), str)
            and _SHA256_RE.fullmatch(cast("str", item.get("sha256"))) is not None
            for item in immutable_rows
        )
    ):
        raise NbaApiCompetitionApplicabilityVerificationError(
            "historical A1.2c immutable-input inventory is malformed"
        )
    immutable = cast("list[dict[str, object]]", immutable_rows)
    immutable_identities = [
        (cast("str", item["path"]), cast("str", item["sha256"])) for item in immutable
    ]
    if (
        len({path for path, _ in immutable_identities}) != 27
        or len(set(immutable_identities)) != 27
    ):
        raise NbaApiCompetitionApplicabilityVerificationError(
            "historical A1.2c immutable-input inventory is not unique"
        )

    authority_rows = support.get("authority_inputs")
    if (
        not isinstance(authority_rows, list)
        or len(authority_rows) != 16
        or not all(
            isinstance(item, dict)
            and set(item) == {"path", "role", "sha256"}
            and isinstance(item.get("path"), str)
            and bool(item.get("path"))
            and isinstance(item.get("role"), str)
            and bool(item.get("role"))
            and isinstance(item.get("sha256"), str)
            and _SHA256_RE.fullmatch(cast("str", item.get("sha256"))) is not None
            for item in authority_rows
        )
        or support.get("authority_inputs_sha256") != _HISTORICAL_AUTHORITY_INPUTS_SHA256
        or _digest(authority_rows) != _HISTORICAL_AUTHORITY_INPUTS_SHA256
    ):
        raise NbaApiCompetitionApplicabilityVerificationError(
            "historical A1.2c authority-input inventory is malformed"
        )
    authorities = cast("list[dict[str, object]]", authority_rows)
    authority_identities = [
        (cast("str", item["path"]), cast("str", item["sha256"])) for item in authorities
    ]
    if (
        len(set(authority_identities)) != 16
        or len({cast("str", item["path"]) for item in authorities}) != 16
        or len({cast("str", item["role"]) for item in authorities}) != 16
        or any(immutable_identities.count(identity) != 1 for identity in authority_identities)
    ):
        raise NbaApiCompetitionApplicabilityVerificationError(
            "historical authority inputs do not map uniquely into A1.2c immutable inputs"
        )

    immutable_by_path = {cast("str", row["path"]): row for row in immutable}
    opening_rows = [immutable_by_path[path] for path in _HISTORICAL_SUCCESSOR_PATHS]
    if (
        opening_rows != list(_HISTORICAL_OPENING_ROWS)
        or _digest(opening_rows) != _HISTORICAL_OPENING_ROWS_SHA256
        or _digest(list(_HISTORICAL_SUCCESSOR_PATHS)) != _HISTORICAL_SUCCESSOR_PATHS_SHA256
    ):
        raise NbaApiCompetitionApplicabilityVerificationError(
            "historical A1.2c successor projection is invalid"
        )


def _validate_existence(payload: dict[str, object]) -> list[dict[str, object]]:
    rows = payload.get("competitions")
    sources = payload.get("sources")
    inventory = payload.get("source_url_inventory")
    revalidation = payload.get("revalidation")
    if (
        payload.get("schema") != "CompetitionExistenceEvidenceV1"
        or not isinstance(rows, list)
        or len(rows) != 5
        or not isinstance(sources, list)
        or len(sources) != 12
        or not isinstance(inventory, list)
        or not isinstance(revalidation, dict)
        or payload.get("competition_count") != 5
        or payload.get("source_count") != 12
        or payload.get("provider_availability_claim_count") != 0
        or payload.get("typed_endpoint_support_claim_count") != 0
        or payload.get("competitions_sha256") != _digest(rows)
        or payload.get("sources_sha256") != _digest(sources)
        or payload.get("source_url_inventory_sha256") != _digest(inventory)
        or payload.get("revalidation_sha256") != _digest(revalidation)
        or revalidation.get("network_required") is not True
        or not revalidation.get("policy_id")
        or not revalidation.get("last_revalidated_date")
        or not revalidation.get("trigger")
    ):
        raise NbaApiCompetitionApplicabilityVerificationError(
            "competition existence source is incomplete or promotes forbidden claims"
        )
    for source in sources:
        if not isinstance(source, dict):
            raise NbaApiCompetitionApplicabilityVerificationError(
                "competition existence source row is malformed"
            )
        body = dict(source)
        claim_sha256 = body.pop("claim_sha256", None)
        if _require_digest(claim_sha256, "claim_sha256") != _digest(body):
            raise NbaApiCompetitionApplicabilityVerificationError(
                "competition existence claim digest is invalid"
            )
    output: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise NbaApiCompetitionApplicabilityVerificationError(
                "competition existence row is malformed"
            )
        intervals = row.get("confirmed_intervals")
        gaps = row.get("explicit_gaps")
        planned = row.get("planned_future_periods")
        source_ids = row.get("source_ids")
        native_type = row.get("native_period_type")
        if (
            row.get("evidence_scope") != "competition_existence_only"
            or row.get("endpoint_support_claim_count") != 0
            or row.get("provider_availability_claim_count") != 0
            or not isinstance(intervals, list)
            or len(intervals) != 1
            or not isinstance(intervals[0], dict)
            or not isinstance(gaps, list)
            or not isinstance(planned, list)
            or not isinstance(source_ids, list)
            or not all(isinstance(item, str) for item in source_ids)
            or not isinstance(native_type, str)
        ):
            raise NbaApiCompetitionApplicabilityVerificationError(
                "competition existence row promoted support/availability or is malformed"
            )
        interval = intervals[0]
        start = interval.get("start")
        end = interval.get("end")
        start_index = _period_index(start, native_type)
        end_index = _period_index(end, native_type)
        if start_index > end_index or interval.get("status") not in {
            "confirmed_eligibility",
            "confirmed_eligibility_with_explicit_gaps",
        }:
            raise NbaApiCompetitionApplicabilityVerificationError(
                "competition existence interval is reversed or unconfirmed"
            )
        gap_periods: list[object] = []
        for gap in gaps:
            if not isinstance(gap, dict) or gap.get("status") != "confirmed_gap":
                raise NbaApiCompetitionApplicabilityVerificationError(
                    "competition existence gap is malformed"
                )
            period = gap.get("period")
            index = _period_index(period, native_type)
            if index < start_index or index > end_index:
                raise NbaApiCompetitionApplicabilityVerificationError(
                    "competition existence gap is outside its interval"
                )
            gap_periods.append(period)
        if len({_canonical_bytes(item) for item in gap_periods}) != len(gap_periods):
            raise NbaApiCompetitionApplicabilityVerificationError(
                "competition existence gaps are duplicate"
            )
        future_periods: list[object] = []
        for future in planned:
            if (
                not isinstance(future, dict)
                or future.get("status") != "planned_future_not_confirmed_eligibility"
            ):
                raise NbaApiCompetitionApplicabilityVerificationError(
                    "planned future was promoted into confirmed eligibility"
                )
            period = future.get("period")
            if _period_index(period, native_type) <= end_index:
                raise NbaApiCompetitionApplicabilityVerificationError(
                    "planned future overlaps confirmed eligibility"
                )
            future_periods.append(period)
        output.append(
            {
                "end": end,
                "evidence_scope": "competition_existence_only",
                "explicit_gaps": gap_periods,
                "league_id": row.get("league_id"),
                "native_period_type": native_type,
                "planned_future_periods": future_periods,
                "source_ids": sorted(cast("list[str]", source_ids)),
                "start": start,
                "status": interval.get("status"),
                "symbol": row.get("symbol"),
            }
        )
    output.sort(key=lambda item: str(item["league_id"]))
    if [item["league_id"] for item in output] != list(_LEAGUE_IDS):
        raise NbaApiCompetitionApplicabilityVerificationError(
            "competition existence finite values are not exact"
        )
    return output


def _support_arrays(
    payload: dict[str, object],
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    endpoint = payload.get("endpoint_competition_cells")
    axes = payload.get("parameter_axis_competition_cells")
    aliases = payload.get("alias_role_competition_cells")
    if (
        not isinstance(endpoint, list)
        or not all(isinstance(item, dict) for item in endpoint)
        or not isinstance(axes, list)
        or not all(isinstance(item, dict) for item in axes)
        or not isinstance(aliases, list)
        or not all(isinstance(item, dict) for item in aliases)
    ):
        raise NbaApiCompetitionApplicabilityVerificationError(
            "endpoint support compact arrays are malformed"
        )
    return (
        cast("list[dict[str, object]]", endpoint),
        cast("list[dict[str, object]]", axes),
        cast("list[dict[str, object]]", aliases),
    )


def _validate_support(payload: dict[str, object]) -> None:
    endpoint, axes, aliases = _support_arrays(payload)
    if (
        payload.get("schema") != "EndpointCompetitionSupportEvidenceV1"
        or payload.get("package_endpoint_count") != len(endpoint)
        or len(endpoint) != 111
        or payload.get("package_occurrence_count") != len(axes)
        or len(axes) != 112
        or payload.get("projected_role_count") != len(aliases)
        or len(aliases) != 127
        or payload.get("repo_alias_count") != 126
        or payload.get("endpoint_competition_cell_count") != 555
        or payload.get("parameter_axis_competition_cell_count") != 560
        or payload.get("alias_role_competition_cell_count") != 635
        or payload.get("typed_declared_axis_cell_count") != 1750
        or payload.get("endpoint_competition_cells_sha256") != _digest(endpoint)
        or payload.get("parameter_axis_competition_cells_sha256") != _digest(axes)
        or payload.get("alias_role_competition_cells_sha256") != _digest(aliases)
        or payload.get("temporal_shape_counts") != _TEMPORAL_SHAPE_COUNTS
        or payload.get("alias_role_temporal_shape_counts") != _ALIAS_TEMPORAL_SHAPE_COUNTS
        or payload.get("endpoint_specific_supported_claim_count") != 0
        or payload.get("endpoint_specific_unsupported_claim_count") != 0
        or payload.get("provider_availability_claim_count") != 0
        or payload.get("provider_availability_observation_count") != 0
        or payload.get("endpoint_specific_supported_rows") != []
        or payload.get("endpoint_specific_unsupported_rows") != []
        or payload.get("provider_availability_observations") != []
    ):
        raise NbaApiCompetitionApplicabilityVerificationError(
            "endpoint support source denominator or false-green counters are invalid"
        )
    for field in (
        "authority_inputs",
        "cell_semantics",
        "checked_authorities",
        "competition_values",
        "temporal_shape_policy",
        "unsupported_evidence_policy",
    ):
        value = payload.get(field)
        if value is None or payload.get(f"{field}_sha256") != _digest(value):
            raise NbaApiCompetitionApplicabilityVerificationError(
                f"endpoint support {field} digest is invalid"
            )
    if (
        payload.get("authority_inputs_sha256") != _HISTORICAL_AUTHORITY_INPUTS_SHA256
        or payload.get("checked_authorities_sha256") != _HISTORICAL_CHECKED_AUTHORITIES_SHA256
    ):
        raise NbaApiCompetitionApplicabilityVerificationError(
            "endpoint support historical authority bindings drifted"
        )
    semantics = payload.get("cell_semantics")
    if not isinstance(semantics, dict) or (
        semantics.get("declared_axis_status") != "declared_by_pinned_package_request_contract"
        or semantics.get("endpoint_support_status")
        != "unknown_no_independent_endpoint_specific_source"
        or semantics.get("provider_availability_status") != "unknown"
        or semantics.get("league_default_as_cross_competition_support") != "forbidden"
    ):
        raise NbaApiCompetitionApplicabilityVerificationError(
            "endpoint support source promotes history/default/availability"
        )


def _validate_review(payload: dict[str, object], existence_raw: bytes, support_raw: bytes) -> None:
    if (
        payload.get("schema") != "IndependentSourceReviewV1"
        or payload.get("disposition") != "pass"
        or payload.get("findings") != []
        or payload.get("model_green_asserted") is not False
        or payload.get("data_green_asserted") is not False
        or payload.get("live_operations_admissible") is not False
        or payload.get("publication_admissible") is not False
    ):
        raise NbaApiCompetitionApplicabilityVerificationError(
            "source review is not a finding-free source-only admission"
        )
    reviewed = payload.get("reviewed_inputs")
    if not isinstance(reviewed, list):
        raise NbaApiCompetitionApplicabilityVerificationError(
            "source review input inventory is malformed"
        )
    observed = {
        str(row.get("path")): str(row.get("sha256")) for row in reviewed if isinstance(row, dict)
    }
    if observed != {
        _EXISTENCE_SOURCE: hashlib.sha256(existence_raw).hexdigest(),
        _SUPPORT_SOURCE: hashlib.sha256(support_raw).hexdigest(),
    }:
        raise NbaApiCompetitionApplicabilityVerificationError(
            "source review does not bind the exact source inputs"
        )


def _validate_predecessors(
    support: dict[str, object],
    competition: dict[str, object],
    occurrence: dict[str, object],
    request: dict[str, object],
) -> None:
    for label, payload in (
        (_COMPETITION_RESOURCE, competition),
        (_OCCURRENCE_RESOURCE, occurrence),
        (_REQUEST_RESOURCE, request),
    ):
        _verify_envelope(payload, label=label)
    current_request = {
        "payload_sha256": request.get("payload_sha256"),
        "resource": _REQUEST_RESOURCE,
        "resource_sha256": _EXPECTED_HASHES[_REQUEST_RESOURCE],
        "schema_version": request.get("schema_version"),
        "surface_sha256": request.get("surface_sha256"),
    }
    if current_request != _CURRENT_REQUEST_AUTHORITY:
        raise NbaApiCompetitionApplicabilityVerificationError(
            "current request-surface authority differs from the pinned successor"
        )
    current_occurrence = {
        "authority_sha256": occurrence.get("authority_sha256"),
        "payload_sha256": occurrence.get("payload_sha256"),
        "schema_version": occurrence.get("schema_version"),
        "upstream_request_surface": occurrence.get("upstream_request_surface"),
    }
    if current_occurrence != _CURRENT_OCCURRENCE_AUTHORITY:
        raise NbaApiCompetitionApplicabilityVerificationError(
            "current occurrence authority differs from the request-v3-bound successor"
        )
    competition_rows = competition.get("competitions")
    support_values = support.get("competition_values")
    if competition_rows != support_values:
        raise NbaApiCompetitionApplicabilityVerificationError(
            "support values differ from the checked competition resource"
        )
    endpoint_rows, axis_rows, alias_rows = _support_arrays(support)
    package_rows = occurrence.get("package_occurrences")
    repo_rows = occurrence.get("repo_aliases")
    if (
        not isinstance(package_rows, list)
        or not all(isinstance(item, dict) for item in package_rows)
        or not isinstance(repo_rows, list)
        or not all(isinstance(item, dict) for item in repo_rows)
    ):
        raise NbaApiCompetitionApplicabilityVerificationError(
            "checked occurrence resource inventories are malformed"
        )
    package = cast("list[dict[str, object]]", package_rows)
    by_occurrence = {str(row["occurrence_id"]): row for row in package}
    if set(by_occurrence) != {str(row["provider_occurrence_id"]) for row in axis_rows}:
        raise NbaApiCompetitionApplicabilityVerificationError(
            "support axes differ from checked occurrence rows"
        )
    for row in axis_rows:
        source = by_occurrence[str(row["provider_occurrence_id"])]
        if any(
            row.get(field) != value
            for field, value in {
                "constructor_name": source.get("constructor_name"),
                "default": source.get("default"),
                "has_default": source.get("has_default"),
                "league_ids": list(_LEAGUE_IDS),
                "nullable": source.get("nullable"),
                "provider_endpoint_id": source.get("provider_endpoint_id"),
                "request_surface_source_signature_sha256": source.get(
                    "request_surface_source_signature_sha256"
                ),
                "request_surface_typed_domain_sha256": source.get(
                    "request_surface_typed_domain_sha256"
                ),
                "wire_name": source.get("wire_name"),
            }.items()
        ):
            raise NbaApiCompetitionApplicabilityVerificationError(
                "support axis differs from the checked occurrence resource"
            )
    by_endpoint: dict[str, list[str]] = {}
    for row in package:
        by_endpoint.setdefault(str(row["provider_endpoint_id"]), []).append(
            str(row["occurrence_id"])
        )
    expected_endpoints = [
        {
            "league_ids": list(_LEAGUE_IDS),
            "provider_endpoint_id": endpoint,
            "provider_occurrence_ids": sorted(occurrence_ids),
        }
        for endpoint, occurrence_ids in sorted(by_endpoint.items())
    ]
    if endpoint_rows != expected_endpoints:
        raise NbaApiCompetitionApplicabilityVerificationError(
            "support endpoint summaries differ from checked occurrence rows"
        )
    shape_by_occurrence = {
        str(row["provider_occurrence_id"]): str(row["temporal_shape"]) for row in axis_rows
    }
    expected_aliases: list[dict[str, object]] = []
    for repo in cast("list[dict[str, object]]", repo_rows):
        roles = repo.get("parameter_roles")
        if not isinstance(roles, list) or not all(isinstance(item, dict) for item in roles):
            raise NbaApiCompetitionApplicabilityVerificationError(
                "checked occurrence alias roles are malformed"
            )
        for role in cast("list[dict[str, object]]", roles):
            occurrence_id = str(role["provider_occurrence_id"])
            expected_aliases.append(
                {
                    "constructor_name": role.get("constructor_name"),
                    "league_ids": list(_LEAGUE_IDS),
                    "provider_endpoint_id": role.get("provider_endpoint_id"),
                    "provider_occurrence_id": occurrence_id,
                    "repo_endpoint_name": repo.get("repo_endpoint_name"),
                    "temporal_shape": shape_by_occurrence[occurrence_id],
                    "wire_name": role.get("wire_name"),
                }
            )
    expected_aliases.sort(
        key=lambda row: (str(row["repo_endpoint_name"]), str(row["provider_occurrence_id"]))
    )
    if alias_rows != expected_aliases:
        raise NbaApiCompetitionApplicabilityVerificationError(
            "support alias roles differ from checked occurrence rows"
        )
    checked = support.get("checked_authorities")
    if (
        not isinstance(checked, dict)
        or checked != _HISTORICAL_CHECKED_AUTHORITIES
        or _digest(checked) != _HISTORICAL_CHECKED_AUTHORITIES_SHA256
    ):
        raise NbaApiCompetitionApplicabilityVerificationError(
            "support historical checked-authority bindings are invalid"
        )


def _cell_semantics() -> dict[str, object]:
    return {
        "declared_axis_evidence_kind": "pinned_package_request_contract",
        "declared_axis_status": "declared_by_pinned_package_request_contract",
        "endpoint_support_evidence_kind": "none",
        "endpoint_support_status": "unknown_no_independent_endpoint_specific_source",
        "probe_disposition": "probe_required",
        "provider_availability_status": "unknown",
    }


def _expand_cells(
    support: dict[str, object], existence: list[dict[str, object]]
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    endpoint_rows, axis_rows, alias_rows = _support_arrays(support)
    competitions = {str(row["league_id"]): row for row in existence}
    axis_by_occurrence = {str(row["provider_occurrence_id"]): row for row in axis_rows}
    endpoint_cells: list[dict[str, object]] = []
    for row in endpoint_rows:
        occurrence_ids = row.get("provider_occurrence_ids")
        if not isinstance(occurrence_ids, list) or not all(
            isinstance(item, str) for item in occurrence_ids
        ):
            raise NbaApiCompetitionApplicabilityVerificationError(
                "support endpoint occurrence IDs are malformed"
            )
        occurrence_id_rows = cast("list[str]", occurrence_ids)
        shapes = {str(axis_by_occurrence[item]["temporal_shape"]) for item in occurrence_id_rows}
        if len(shapes) != 1:
            raise NbaApiCompetitionApplicabilityVerificationError(
                "endpoint summary combines incompatible temporal shapes"
            )
        for league_id in _LEAGUE_IDS:
            competition = competitions[league_id]
            endpoint_cells.append(
                {
                    **_cell_semantics(),
                    "league_id": league_id,
                    "native_period_type": competition["native_period_type"],
                    "provider_endpoint_id": row["provider_endpoint_id"],
                    "provider_occurrence_ids": sorted(occurrence_id_rows),
                    "symbol": competition["symbol"],
                    "temporal_shape": next(iter(shapes)),
                }
            )
    axis_cells: list[dict[str, object]] = []
    for row in axis_rows:
        companions = row.get("temporal_companion_occurrence_ids")
        if not isinstance(companions, list) or not all(
            isinstance(item, str) for item in companions
        ):
            raise NbaApiCompetitionApplicabilityVerificationError(
                "support temporal companion IDs are malformed"
            )
        constructor = str(row["constructor_name"])
        occurrence_id = str(row["provider_occurrence_id"])
        participant = constructor in {"person1_league_id", "person2_league_id"}
        if participant and tuple(companions) != _GL_BINDINGS.get(occurrence_id):
            raise NbaApiCompetitionApplicabilityVerificationError(
                "GLAlum same-person temporal binding is invalid"
            )
        for league_id in _LEAGUE_IDS:
            competition = competitions[league_id]
            axis_cells.append(
                {
                    "cell_kind": "parameter_axis",
                    "constructor_name": constructor,
                    **_cell_semantics(),
                    "joint_cartesian_authority": False,
                    "league_id": league_id,
                    "native_period_type": competition["native_period_type"],
                    "participant_axis_binding": (
                        "same_person_temporal_companions" if participant else "not_applicable"
                    ),
                    "provider_endpoint_id": row["provider_endpoint_id"],
                    "provider_occurrence_id": occurrence_id,
                    "repo_endpoint_name": None,
                    "symbol": competition["symbol"],
                    "temporal_companion_occurrence_ids": companions,
                    "temporal_shape": row["temporal_shape"],
                    "wire_name": row["wire_name"],
                }
            )
    alias_cells: list[dict[str, object]] = []
    for row in alias_rows:
        occurrence_id = str(row["provider_occurrence_id"])
        axis = axis_by_occurrence[occurrence_id]
        companions = axis["temporal_companion_occurrence_ids"]
        constructor = str(row["constructor_name"])
        participant = constructor in {"person1_league_id", "person2_league_id"}
        for league_id in _LEAGUE_IDS:
            competition = competitions[league_id]
            alias_cells.append(
                {
                    "cell_kind": "alias_role",
                    "constructor_name": constructor,
                    **_cell_semantics(),
                    "joint_cartesian_authority": False,
                    "league_id": league_id,
                    "native_period_type": competition["native_period_type"],
                    "participant_axis_binding": (
                        "same_person_temporal_companions" if participant else "not_applicable"
                    ),
                    "provider_endpoint_id": row["provider_endpoint_id"],
                    "provider_occurrence_id": occurrence_id,
                    "repo_endpoint_name": row["repo_endpoint_name"],
                    "symbol": competition["symbol"],
                    "temporal_companion_occurrence_ids": companions,
                    "temporal_shape": row["temporal_shape"],
                    "wire_name": row["wire_name"],
                }
            )
    endpoint_cells.sort(key=lambda row: (str(row["provider_endpoint_id"]), str(row["league_id"])))
    axis_cells.sort(key=lambda row: (str(row["provider_occurrence_id"]), str(row["league_id"])))
    alias_cells.sort(
        key=lambda row: (
            str(row["repo_endpoint_name"]),
            str(row["provider_occurrence_id"]),
            str(row["league_id"]),
        )
    )
    if (
        len(endpoint_cells) != 555
        or len(axis_cells) != 560
        or len(alias_cells) != 635
        or len({(row["provider_endpoint_id"], row["league_id"]) for row in endpoint_cells}) != 555
        or len({(row["provider_occurrence_id"], row["league_id"]) for row in axis_cells}) != 560
        or len(
            {
                (
                    row["repo_endpoint_name"],
                    row["provider_occurrence_id"],
                    row["league_id"],
                )
                for row in alias_cells
            }
        )
        != 635
    ):
        raise NbaApiCompetitionApplicabilityVerificationError(
            "expanded endpoint/axis/alias-role cell denominator is invalid"
        )
    axis_shapes = {
        str(row["provider_occurrence_id"]): str(row["temporal_shape"]) for row in axis_cells
    }
    alias_shapes = {
        (str(row["repo_endpoint_name"]), str(row["provider_occurrence_id"])): str(
            row["temporal_shape"]
        )
        for row in alias_cells
    }
    if (
        dict(sorted(Counter(axis_shapes.values()).items())) != _TEMPORAL_SHAPE_COUNTS
        or dict(sorted(Counter(alias_shapes.values()).items())) != _ALIAS_TEMPORAL_SHAPE_COUNTS
    ):
        raise NbaApiCompetitionApplicabilityVerificationError(
            "expanded temporal-shape partitions are invalid"
        )
    return endpoint_cells, axis_cells, alias_cells


def _expected_payload(
    existence_raw: bytes,
    existence_source: dict[str, object],
    support_raw: bytes,
    support: dict[str, object],
    review_raw: bytes,
    review: dict[str, object],
    competition: dict[str, object],
    occurrence: dict[str, object],
    request: dict[str, object],
) -> dict[str, object]:
    existence = _validate_existence(existence_source)
    endpoint_cells, axis_cells, alias_cells = _expand_cells(support, existence)
    revalidation = cast("dict[str, object]", existence_source["revalidation"])
    body: dict[str, object] = {
        "alias_role_competition_cell_count": len(alias_cells),
        "alias_role_competition_cells": alias_cells,
        "alias_role_competition_cells_sha256": _digest(alias_cells),
        "alias_role_temporal_shape_counts": _ALIAS_TEMPORAL_SHAPE_COUNTS,
        "competition_count": len(existence),
        "competition_existence": existence,
        "competition_existence_sha256": _digest(existence),
        "endpoint_competition_cell_count": len(endpoint_cells),
        "endpoint_competition_cells": endpoint_cells,
        "endpoint_competition_cells_sha256": _digest(endpoint_cells),
        "evidence_layers": _EVIDENCE_LAYERS,
        "false_green_counters": {
            "history_promoted_to_endpoint_support_count": 0,
            "provider_available_claim_count": 0,
            "unclassified_request_contract_cell_count": 0,
            "upstream_unavailable_claim_count": 0,
        },
        "gl_alum_participant_axis_contract": {
            "independent_axis_cell_count": 10,
            "joint_cartesian_cell_count_authorized": False,
            "same_person_temporal_bindings": [
                {
                    "provider_occurrence_id": occurrence_id,
                    "temporal_companion_occurrence_ids": list(companions),
                }
                for occurrence_id, companions in sorted(_GL_BINDINGS.items())
            ],
        },
        "kind": "nbadb_nba_api_competition_applicability_authority",
        "parameter_axis_competition_cell_count": len(axis_cells),
        "parameter_axis_competition_cells": axis_cells,
        "parameter_axis_competition_cells_sha256": _digest(axis_cells),
        "provider_availability_values": ["unknown"],
        "revalidation": {
            "last_revalidated_date": revalidation["last_revalidated_date"],
            "network_required": revalidation["network_required"],
            "policy_id": revalidation["policy_id"],
            "source_body_bytes_or_digests_retained": False,
            "trigger": revalidation["trigger"],
        },
        "schema_version": _SCHEMA_VERSION,
        "source_authorities": {
            "competition_existence": {
                "authority_sha256": existence_source["authority_sha256"],
                "path": _EXISTENCE_SOURCE,
                "payload_sha256": existence_source["payload_sha256"],
                "resource_sha256": hashlib.sha256(existence_raw).hexdigest(),
            },
            "competition_occurrences": {"authority_sha256": occurrence["authority_sha256"]},
            "competition_values": {"authority_sha256": competition["authority_sha256"]},
            "endpoint_support": {
                "authority_sha256": support["authority_sha256"],
                "path": _SUPPORT_SOURCE,
                "payload_sha256": support["payload_sha256"],
                "resource_sha256": hashlib.sha256(support_raw).hexdigest(),
            },
            "independent_source_review": {
                "authority_sha256": review["authority_sha256"],
                "path": _SOURCE_REVIEW,
                "payload_sha256": review["payload_sha256"],
                "resource_sha256": hashlib.sha256(review_raw).hexdigest(),
            },
            "request_surface": {"surface_sha256": request["surface_sha256"]},
        },
        "special_temporal_sets": {
            "date_or_date_range_only_endpoint_ids": list(_DATE_ONLY),
            "no_temporal_parameter_endpoint_ids": list(_NON_TEMPORAL),
            "season_type_only_endpoint_ids": list(_SEASON_TYPE_ONLY),
        },
        "temporal_shape_counts": _TEMPORAL_SHAPE_COUNTS,
        "typed_declared_axis_cell_count": 1750,
    }
    payload: dict[str, object] = {
        **body,
        "authority_sha256": _digest(body),
        "independent_proof": {
            "claim_status": "not_supplied_by_this_artifact",
            "kind": "independent_competition_applicability_source_receipt",
            "required": True,
            "schema_version": 1,
        },
    }
    payload["payload_sha256"] = _digest(payload)
    return payload


@dataclass(frozen=True, slots=True)
class IndependentCompetitionApplicabilityProof:
    """Independent exact-equality proof for the checked applicability resource."""

    verifier_id: str
    authority_sha256: str
    checked_payload_sha256: str
    competition_existence_sha256: str
    endpoint_competition_cells_sha256: str
    parameter_axis_competition_cells_sha256: str
    alias_role_competition_cells_sha256: str
    endpoint_competition_cell_count: int
    parameter_axis_competition_cell_count: int
    alias_role_competition_cell_count: int
    proof_sha256: str


def _verify(
    candidate_path: Path | None,
    *,
    existence_source_path: Path | None = None,
    endpoint_support_source_path: Path | None = None,
    source_review_path: Path | None = None,
) -> IndependentCompetitionApplicabilityProof:
    task_packet_raw, task_packet = _read_packaged_provenance(
        _TASK_PACKET,
        label="historical A1.2c task packet",
        pretty=True,
    )
    existence_raw, existence = (
        _read_path(existence_source_path, label=_EXISTENCE_SOURCE, pretty=True)
        if existence_source_path is not None
        else _read_packaged_provenance(_EXISTENCE_SOURCE, label=_EXISTENCE_SOURCE, pretty=True)
    )
    support_raw, support = (
        _read_path(endpoint_support_source_path, label=_SUPPORT_SOURCE, pretty=True)
        if endpoint_support_source_path is not None
        else _read_packaged_provenance(_SUPPORT_SOURCE, label=_SUPPORT_SOURCE, pretty=True)
    )
    review_raw, review = (
        _read_path(source_review_path, label=_SOURCE_REVIEW, pretty=True)
        if source_review_path is not None
        else _read_packaged_provenance(_SOURCE_REVIEW, label=_SOURCE_REVIEW, pretty=True)
    )
    _verify_source_payload(
        existence_raw,
        existence,
        relative=_EXISTENCE_SOURCE,
        exact_path=existence_source_path is None,
    )
    _verify_source_payload(
        support_raw,
        support,
        relative=_SUPPORT_SOURCE,
        exact_path=endpoint_support_source_path is None,
    )
    _verify_source_payload(
        review_raw,
        review,
        relative=_SOURCE_REVIEW,
        exact_path=source_review_path is None,
    )
    _validate_support(support)
    _validate_historical_task_packet(task_packet_raw, task_packet, support)
    _validate_review(review, existence_raw, support_raw)
    _, competition = _read_contract(_COMPETITION_RESOURCE)
    _, occurrence = _read_contract(_OCCURRENCE_RESOURCE)
    _, request = _read_contract(_REQUEST_RESOURCE)
    _validate_predecessors(support, competition, occurrence, request)
    expected = _expected_payload(
        existence_raw,
        existence,
        support_raw,
        support,
        review_raw,
        review,
        competition,
        occurrence,
        request,
    )
    if candidate_path is None:
        try:
            candidate_raw = resources.files("nbadb.contracts").joinpath(_RESOURCE).read_bytes()
        except (AttributeError, OSError) as exc:
            raise NbaApiCompetitionApplicabilityVerificationError(
                "checked applicability resource cannot be read"
            ) from exc
        candidate = _parse(
            candidate_raw,
            label="checked applicability resource",
            pretty=False,
        )
    else:
        candidate_raw, candidate = _read_path(
            candidate_path,
            label="candidate applicability resource",
            pretty=False,
        )
    _verify_envelope(candidate, label="candidate applicability resource")
    if candidate != expected or candidate_raw != _canonical_bytes(expected) + b"\n":
        raise NbaApiCompetitionApplicabilityVerificationError(
            "checked applicability authority differs from independent sealed sources"
        )
    proof_body = {
        "alias_role_competition_cell_count": 635,
        "alias_role_competition_cells_sha256": expected["alias_role_competition_cells_sha256"],
        "authority_sha256": expected["authority_sha256"],
        "checked_payload_sha256": expected["payload_sha256"],
        "competition_existence_sha256": expected["competition_existence_sha256"],
        "endpoint_competition_cell_count": 555,
        "endpoint_competition_cells_sha256": expected["endpoint_competition_cells_sha256"],
        "kind": "nbadb_independent_competition_applicability_proof",
        "parameter_axis_competition_cell_count": 560,
        "parameter_axis_competition_cells_sha256": expected[
            "parameter_axis_competition_cells_sha256"
        ],
        "schema_version": 1,
        "verifier_id": _VERIFIER_ID,
    }
    return IndependentCompetitionApplicabilityProof(
        verifier_id=_VERIFIER_ID,
        authority_sha256=str(expected["authority_sha256"]),
        checked_payload_sha256=str(expected["payload_sha256"]),
        competition_existence_sha256=str(expected["competition_existence_sha256"]),
        endpoint_competition_cells_sha256=str(expected["endpoint_competition_cells_sha256"]),
        parameter_axis_competition_cells_sha256=str(
            expected["parameter_axis_competition_cells_sha256"]
        ),
        alias_role_competition_cells_sha256=str(expected["alias_role_competition_cells_sha256"]),
        endpoint_competition_cell_count=555,
        parameter_axis_competition_cell_count=560,
        alias_role_competition_cell_count=635,
        proof_sha256=_digest(proof_body),
    )


@lru_cache(maxsize=1)
def verify_pinned_competition_applicability_authority() -> IndependentCompetitionApplicabilityProof:
    """Independently verify the installed checked applicability resource."""

    return _verify(None)


def verify_competition_applicability_authority_file(
    path: Path,
    *,
    existence_source_path: Path | None = None,
    endpoint_support_source_path: Path | None = None,
    source_review_path: Path | None = None,
) -> IndependentCompetitionApplicabilityProof:
    """Verify an explicit candidate resource and optional explicit source inputs."""

    return _verify(
        path,
        existence_source_path=existence_source_path,
        endpoint_support_source_path=endpoint_support_source_path,
        source_review_path=source_review_path,
    )


__all__ = [
    "IndependentCompetitionApplicabilityProof",
    "NbaApiCompetitionApplicabilityVerificationError",
    "verify_competition_applicability_authority_file",
    "verify_pinned_competition_applicability_authority",
]
