"""Fail closed when packaged or canonical chat bytecode lacks matching source."""

from __future__ import annotations

import importlib.util
import stat
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _source_from_bytecode(pyc: Path) -> Path | None:
    if pyc.parent.name == "__pycache__":
        try:
            return Path(importlib.util.source_from_cache(str(pyc)))
        except ValueError:
            return None
    return pyc.with_suffix(".py")


def _is_regular_source_within(source: Path, scan_root: Path) -> bool:
    try:
        scan_resolved = scan_root.resolve(strict=True)
        source_resolved = source.resolve(strict=True)
        source_mode = source.lstat().st_mode
    except (OSError, RuntimeError):
        return False
    try:
        source_resolved.relative_to(scan_resolved)
    except ValueError:
        return False
    return not source.is_symlink() and stat.S_ISREG(source_mode)


def orphan_pyc_files(repo_root: Path | None = None) -> list[Path]:
    """Return bytecode whose mapped Python source is absent or unsafe.

    This is a source-presence gate. It deliberately does not claim that a
    bytecode file is fresh or content-equivalent to its corresponding source.
    """
    root = repo_root or _REPO_ROOT
    scan_roots = (
        root / "src" / "nbadb" / "chat",
        root / "chat",
    )
    orphans: list[Path] = []
    for scan in scan_roots:
        if not scan.exists():
            continue
        for pyc in scan.rglob("*.pyc"):
            source = _source_from_bytecode(pyc)
            if source is None or not _is_regular_source_within(source, scan):
                orphans.append(pyc)
    return sorted(orphans)


def retired_chat_paths(repo_root: Path | None = None) -> list[Path]:
    """Return files under the retired ``apps/chat`` surface, if it reappears."""
    root = repo_root or _REPO_ROOT
    retired_root = root / "apps" / "chat"
    if not retired_root.exists():
        return []
    return sorted(path for path in retired_root.rglob("*") if path.is_file())


def main() -> int:
    orphans = orphan_pyc_files()
    retired = retired_chat_paths()
    if not orphans and not retired:
        print("chat source inventory: ok (no orphan bytecode or retired apps/chat content)")
        return 0
    if orphans:
        print("chat source inventory: orphan bytecode without .py source:", file=sys.stderr)
        for path in orphans:
            try:
                print(f"  {path.relative_to(_REPO_ROOT)}", file=sys.stderr)
            except ValueError:
                print(f"  {path}", file=sys.stderr)
    if retired:
        print("chat source inventory: retired apps/chat content:", file=sys.stderr)
        for path in retired:
            try:
                print(f"  {path.relative_to(_REPO_ROOT)}", file=sys.stderr)
            except ValueError:
                print(f"  {path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
