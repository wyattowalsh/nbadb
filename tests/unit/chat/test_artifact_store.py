from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from nbadb.chat.artifacts import ArtifactStore, ArtifactStoreError


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
        session_id="sess-1",
    )
    hits = store.search_findings("scorer", session_id="sess-1")
    assert len(hits) == 1
    assert hits[0]["metadata"]["sql_hash"] == "abc123"


def test_artifact_store_sanitizes_template_and_finding_paths(tmp_path) -> None:
    store = ArtifactStore(root=tmp_path / "artifacts")

    store.save_template("../leader board", {"sql": "SELECT 1"})
    stored = store.save_finding(
        "../Top/Scorer",
        "Player led scoring",
        session_id="sess-1",
    )

    assert (tmp_path / "artifacts" / "templates" / "leader-board.json").exists()
    finding_paths = list((tmp_path / "artifacts" / "findings").rglob("*.json"))
    assert len(finding_paths) == 1
    assert finding_paths[0].name == f"top-scorer-{stored['artifact_id']}.json"
    assert not (tmp_path / "leader board.json").exists()
    assert not (tmp_path / "Top" / "Scorer.json").exists()


def test_findings_are_session_scoped_and_equal_titles_never_overwrite(tmp_path) -> None:
    store = ArtifactStore(root=tmp_path / "artifacts")

    def save(index: int) -> dict[str, object]:
        return store.save_finding(
            "Scoring leader",
            f"result {index}",
            metadata={"index": index, "session_id": "sess-a"},
            session_id="sess-a",
        )

    with ThreadPoolExecutor(max_workers=6) as executor:
        saved = list(executor.map(save, range(12)))
    foreign = store.save_finding(
        "Scoring leader",
        "foreign result",
        metadata={"index": 99, "session_id": "sess-b"},
        session_id="sess-b",
    )

    own_hits = store.search_findings("result", session_id="sess-a")
    foreign_hits = store.search_findings("result", session_id="sess-b")
    assert len(own_hits) == 12
    assert len(foreign_hits) == 1
    assert foreign_hits[0]["metadata"]["index"] == 99
    assert len({item["artifact_id"] for item in (*saved, foreign)}) == 13
    assert all(hit["session_id"] == "sess-a" for hit in own_hits)
    assert all(hit["metadata"]["session_id"] == "sess-a" for hit in own_hits)


def test_finding_title_and_session_bounds_precede_filesystem_access(
    tmp_path,
    monkeypatch,
) -> None:
    store = ArtifactStore(root=tmp_path / "artifacts")
    monkeypatch.setattr(
        store,
        "_bucket",
        lambda _name: (_ for _ in ()).throw(AssertionError("filesystem accessed")),
    )

    with pytest.raises(ValueError, match="finding title exceeds 200"):
        store.save_finding("x" * 201, "summary", session_id="sess-a")
    with pytest.raises(ValueError, match="session_id exceeds 200"):
        store.save_finding("title", "summary", session_id="s" * 201)


def test_finding_filesystem_errors_are_bounded(tmp_path, monkeypatch) -> None:
    store = ArtifactStore(root=tmp_path / "artifacts")
    monkeypatch.setattr(
        store,
        "_bucket",
        lambda _name: (_ for _ in ()).throw(OSError("/private/secret/path")),
    )

    with pytest.raises(ArtifactStoreError) as exc_info:
        store.save_finding("title", "summary", session_id="sess-a")

    assert str(exc_info.value) == "finding could not be stored safely"
    assert "/private" not in str(exc_info.value)
