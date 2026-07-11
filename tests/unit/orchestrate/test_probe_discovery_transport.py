from __future__ import annotations

import importlib.util
from pathlib import Path

import polars as pl

MODULE_PATH = (
    Path(__file__).resolve().parents[3] / ".github" / "scripts" / "probe_discovery_transport.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("probe_discovery_transport", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_probe_uses_nbadb_extractors_for_player_and_game_discovery(monkeypatch) -> None:
    module = _load_module()
    calls: list[tuple[str, dict[str, object]]] = []

    def _fake_sync_extract(extractor: object, **params: object) -> pl.DataFrame:
        endpoint = extractor.endpoint_name
        calls.append((endpoint, params))
        if endpoint == "common_all_players":
            return pl.DataFrame(
                {
                    "person_id": [2544, 201939],
                    "team_id": [1610612747, 1610612744],
                }
            )
        return pl.DataFrame(
            {
                "game_id": ["0022400001"],
                "game_date": ["2024-10-22"],
                "team_id": [1610612738],
            }
        )

    monkeypatch.setattr(module, "_sync_extract", _fake_sync_extract)

    result = module.run_probe(request_timeout_seconds=7, season="2024-25")

    assert result == {
        "status": "passed",
        "endpoints": {
            "common_all_players": {"rows": 2},
            "league_game_log": {"rows": 1},
        },
    }
    assert calls == [
        (
            "common_all_players",
            {
                "season": "2024-25",
                "is_only_current_season": 0,
                "allow_static_fallback": False,
                "timeout": 7,
            },
        ),
        (
            "league_game_log",
            {
                "season": "2024-25",
                "season_type": "Regular Season",
                "timeout": 7,
            },
        ),
    ]


def test_probe_failure_attestation_excludes_exception_messages(monkeypatch) -> None:
    module = _load_module()
    secret_marker = "credential-secret-marker"

    def _raise_transport_failure(extractor: object, **params: object) -> pl.DataFrame:
        raise TimeoutError(secret_marker)

    monkeypatch.setattr(module, "_sync_extract", _raise_transport_failure)

    result = module.run_probe(request_timeout_seconds=3, season="2024-25")

    assert result == {
        "status": "failed",
        "endpoint": "common_all_players",
        "failure_kind": "exception",
        "error_type": "TimeoutError",
    }
    assert secret_marker not in str(result)


def test_probe_rejects_empty_or_wrong_schema_frames(monkeypatch) -> None:
    module = _load_module()

    monkeypatch.setattr(module, "_sync_extract", lambda extractor, **params: pl.DataFrame())
    empty = module.run_probe(request_timeout_seconds=3, season="2024-25")
    assert empty["failure_kind"] == "empty"

    monkeypatch.setattr(
        module,
        "_sync_extract",
        lambda extractor, **params: pl.DataFrame({"unexpected": [1]}),
    )
    wrong_schema = module.run_probe(request_timeout_seconds=3, season="2024-25")
    assert wrong_schema["failure_kind"] == "missing_columns"


def test_probe_rejects_player_rows_without_positive_team_membership(monkeypatch) -> None:
    module = _load_module()

    monkeypatch.setattr(
        module,
        "_sync_extract",
        lambda extractor, **params: pl.DataFrame(
            {"person_id": [2544, None, 201939], "team_id": [0, -1, None]}
        ),
    )

    result = module.run_probe(request_timeout_seconds=3, season="2024-25")

    assert result == {
        "status": "failed",
        "endpoint": "common_all_players",
        "failure_kind": "invalid_values",
        "error_type": "ProbeContractError",
    }
