from __future__ import annotations

import importlib.machinery
import py_compile
from pathlib import Path

from nbadb.chat.source_inventory import orphan_pyc_files, retired_chat_paths


def test_live_chat_source_inventory_is_clean() -> None:
    orphans = orphan_pyc_files()
    assert orphans == [], f"orphan pyc present: {orphans[:10]}"
    retired = retired_chat_paths()
    assert retired == [], f"retired apps/chat files present: {retired[:10]}"


def _write_source(path: Path, body: str = "VALUE = 1\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _compile(source: Path, *, optimize: int = -1, cfile: Path | None = None) -> Path:
    compiled = py_compile.compile(
        str(source),
        cfile=str(cfile) if cfile is not None else None,
        doraise=True,
        optimize=optimize,
    )
    assert compiled is not None
    return Path(compiled)


def test_cache_inventory_uses_real_source_from_cache_mappings(tmp_path: Path) -> None:
    sources = (
        tmp_path / "src" / "nbadb" / "chat" / "runtime.py",
        tmp_path / "src" / "nbadb" / "chat" / "package" / "__init__.py",
        tmp_path / "chat" / "mcp_servers" / "catalog.py",
        tmp_path / "chat" / "nested" / "tool.py",
    )
    for source in sources:
        _write_source(source)

    compiled = (
        _compile(sources[0]),
        _compile(sources[1], optimize=1),
        _compile(sources[2], optimize=2),
        _compile(sources[3]),
    )

    assert orphan_pyc_files(tmp_path) == []

    sources[1].unlink()
    assert orphan_pyc_files(tmp_path) == [compiled[1]]


def test_malformed_cache_name_is_reported_even_when_guessed_source_exists(
    tmp_path: Path,
) -> None:
    malformed = tmp_path / "chat" / "__pycache__" / "catalog.pyc"
    guessed_source = tmp_path / "chat" / "catalog.py"
    malformed.parent.mkdir(parents=True, exist_ok=True)
    malformed.write_bytes(b"not cache-tagged")
    _write_source(guessed_source)

    assert orphan_pyc_files(tmp_path) == [malformed]


def test_adjacent_sourceless_bytecode_is_scanned_and_loadable(tmp_path: Path) -> None:
    source = tmp_path / "chat" / "legacy.py"
    bytecode = source.with_suffix(".pyc")
    _write_source(source, "VALUE = 42\n")
    _compile(source, cfile=bytecode)
    source.unlink()

    loader = importlib.machinery.SourcelessFileLoader("legacy_fixture", str(bytecode))
    assert loader.get_code("legacy_fixture") is not None
    assert orphan_pyc_files(tmp_path) == [bytecode]

    _write_source(source, "VALUE = 43\n")
    assert orphan_pyc_files(tmp_path) == []


def test_inventory_rejects_symlinked_and_broken_mapped_sources(tmp_path: Path) -> None:
    external_source = tmp_path / "external.py"
    _write_source(external_source)

    linked_bytecode = tmp_path / "chat" / "linked.pyc"
    linked_source = linked_bytecode.with_suffix(".py")
    linked_bytecode.parent.mkdir(parents=True, exist_ok=True)
    _compile(external_source, cfile=linked_bytecode)
    linked_source.symlink_to(external_source)

    broken_bytecode = tmp_path / "src" / "nbadb" / "chat" / "broken.pyc"
    broken_source = broken_bytecode.with_suffix(".py")
    broken_bytecode.parent.mkdir(parents=True, exist_ok=True)
    _compile(external_source, cfile=broken_bytecode)
    broken_source.symlink_to(tmp_path / "missing.py")

    assert orphan_pyc_files(tmp_path) == sorted([linked_bytecode, broken_bytecode])


def test_inventory_reports_source_symlink_loop_instead_of_crashing(tmp_path: Path) -> None:
    external_source = tmp_path / "external.py"
    _write_source(external_source)
    looped_bytecode = tmp_path / "chat" / "looped.pyc"
    looped_source = looped_bytecode.with_suffix(".py")
    looped_bytecode.parent.mkdir(parents=True, exist_ok=True)
    _compile(external_source, cfile=looped_bytecode)
    looped_source.symlink_to(looped_source.name)

    assert orphan_pyc_files(tmp_path) == [looped_bytecode]


def test_orphan_inventory_scans_both_roots_and_sorts_deterministically(tmp_path: Path) -> None:
    root_orphan = tmp_path / "chat" / "zeta.pyc"
    nested_orphan = tmp_path / "chat" / "mcp_servers" / "alpha.pyc"
    shared_orphan = tmp_path / "src" / "nbadb" / "chat" / "middle.pyc"
    for path in (root_orphan, nested_orphan, shared_orphan):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")

    assert orphan_pyc_files(tmp_path) == sorted([root_orphan, nested_orphan, shared_orphan])


def test_source_inventory_rejects_retired_apps_chat(tmp_path: Path) -> None:
    retired = tmp_path / "apps" / "chat" / "legacy.py"
    retired.parent.mkdir(parents=True)
    retired.write_text("# retired\n", encoding="utf-8")

    assert retired_chat_paths(tmp_path) == [retired]
