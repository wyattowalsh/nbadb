from __future__ import annotations

from nbadb.orchestrate.persistence import atomic_write_path, atomic_write_text


def _tmp_sidecars(path):
    return list(path.parent.glob(f".{path.name}.*.tmp"))


def test_atomic_write_text_allows_repeated_writes_without_tmp_collisions(tmp_path) -> None:
    path = tmp_path / "state.json"

    atomic_write_text(path, '{"status":"first"}\n')
    atomic_write_text(path, '{"status":"second"}\n')

    assert path.read_text(encoding="utf-8") == '{"status":"second"}\n'
    assert _tmp_sidecars(path) == []


def test_atomic_write_path_cleans_up_temp_file_when_writer_fails(tmp_path) -> None:
    path = tmp_path / "state.json"

    def _writer(temp_path) -> None:
        temp_path.write_text("partial", encoding="utf-8")
        raise RuntimeError("boom")

    try:
        atomic_write_path(path, _writer)
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("atomic_write_path should propagate writer failures")

    assert path.exists() is False
    assert _tmp_sidecars(path) == []
