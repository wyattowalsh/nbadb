from __future__ import annotations

import pytest

from nbadb.chat.artifacts import ArtifactStore
from nbadb.chat.memory import MemoryStore
from nbadb.chat.runtime import ChatRuntime
from nbadb.chat.sql import QueryResponse


def test_runtime_promotes_query_response_to_finding(tmp_path) -> None:
    runtime = ChatRuntime(
        duckdb_path=tmp_path / "warehouse.duckdb",
        memory_store=MemoryStore(root=tmp_path / "memory"),
        artifact_store=ArtifactStore(root=tmp_path / "artifacts"),
    )
    response = QueryResponse(
        question="Who led scoring?",
        route="player_season_scoring",
        sql="SELECT 1",
        metadata={"sql_hash": "abc123", "catalog_entry": "player season scoring"},
        tables=("agg_player_season", "dim_player"),
        columns=("full_name", "total_pts"),
        rows=(("Test Player", 2500),),
    )

    record = runtime.promote_to_finding(response, title="Scoring leader", session_id="sess-1")

    assert record.source_sql_hash == "abc123"
    hits = runtime.artifact_store.search_findings("Scoring", session_id="sess-1")
    assert hits
    assert hits[0]["metadata"]["catalog_entry"] == "player season scoring"


def test_runtime_rejects_unsuccessful_finding_promotion(tmp_path) -> None:
    runtime = ChatRuntime(
        duckdb_path=tmp_path / "warehouse.duckdb",
        memory_store=MemoryStore(root=tmp_path / "memory"),
        artifact_store=ArtifactStore(root=tmp_path / "artifacts"),
    )
    response = QueryResponse(question="unknown", route="unsupported")

    with pytest.raises(ValueError, match="only successful query results"):
        runtime.promote_to_finding(response, title="Should not save", session_id="sess-1")

    assert runtime.artifact_store.search_findings("Should not save", session_id="sess-1") == []
