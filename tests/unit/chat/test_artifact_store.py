from __future__ import annotations

from nbadb.chat.artifacts import ArtifactStore


def test_artifact_store_round_trip_templates_and_findings(tmp_path) -> None:
    store = ArtifactStore(root=tmp_path / "artifacts")

    store.save_template("leaderboard", {"sql": "SELECT 1"}, summary="Top scorers")
    loaded = store.load_template("leaderboard")
    assert loaded is not None
    assert loaded["payload"]["sql"] == "SELECT 1"
    assert store.list_templates() == ["leaderboard"]

    store.save_finding(
        "Top scorer",
        "Player led scoring",
        metadata={"sql_hash": "abc123", "session_id": "sess-1"},
    )
    hits = store.search_findings("scorer")
    assert len(hits) == 1
    assert hits[0]["metadata"]["sql_hash"] == "abc123"


def test_artifact_store_sanitizes_template_and_finding_paths(tmp_path) -> None:
    store = ArtifactStore(root=tmp_path / "artifacts")

    store.save_template("../leader board", {"sql": "SELECT 1"})
    store.save_finding("../Top/Scorer", "Player led scoring")

    assert (tmp_path / "artifacts" / "templates" / "leader-board.json").exists()
    assert (tmp_path / "artifacts" / "findings" / "top-scorer.json").exists()
    assert not (tmp_path / "leader board.json").exists()
    assert not (tmp_path / "Top" / "Scorer.json").exists()
