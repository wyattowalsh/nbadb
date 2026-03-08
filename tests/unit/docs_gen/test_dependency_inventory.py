from __future__ import annotations

import json
from typing import TYPE_CHECKING

from nbadb.docs_gen.dependency_inventory import DependencyInventoryGenerator

if TYPE_CHECKING:
    from pathlib import Path


def _write_poetry_lock(path: Path) -> None:
    path.write_text(
        """
[[package]]
name = "rootpkg"
version = "1.0.0"
description = "root package"
optional = false
python-versions = ">=3.12"

[package.dependencies]
click = ">=8.1,<9.0"
rich = { version = ">=13.7", optional = true }

[[package]]
name = "click"
version = "8.1.7"
description = "Composable command line interface toolkit"
optional = false
python-versions = ">=3.8"
""".strip(),
        encoding="utf-8",
    )


def test_build_inventory_parses_lock_graph(tmp_path: Path) -> None:
    lock_path = tmp_path / "poetry.lock"
    _write_poetry_lock(lock_path)

    generator = DependencyInventoryGenerator(lock_path=lock_path)
    inventory = generator.build_inventory()

    assert inventory["lockfile"]["package_count"] == 2
    assert {pkg["name"] for pkg in inventory["packages"]} == {"click", "rootpkg"}
    assert {"from": "rootpkg", "to": "click", "constraint": ">=8.1,<9.0"} in inventory["edges"]
    assert any(edge["to"] == "rich" for edge in inventory["edges"])


def test_build_inventory_includes_installed_versions(tmp_path: Path, monkeypatch) -> None:
    lock_path = tmp_path / "poetry.lock"
    _write_poetry_lock(lock_path)

    monkeypatch.setattr(
        DependencyInventoryGenerator,
        "_get_installed_versions",
        lambda self: {"rootpkg": "1.0.1", "click": "8.1.7"},
    )

    generator = DependencyInventoryGenerator(lock_path=lock_path)
    inventory = generator.build_inventory()
    packages = {pkg["name"]: pkg for pkg in inventory["packages"]}

    assert packages["rootpkg"]["installed_version"] == "1.0.1"
    assert packages["click"]["installed_version"] == "8.1.7"


def test_write_creates_json_artifact(tmp_path: Path) -> None:
    lock_path = tmp_path / "poetry.lock"
    output_path = tmp_path / "dependency-inventory.json"
    _write_poetry_lock(lock_path)

    generator = DependencyInventoryGenerator(lock_path=lock_path, output_path=output_path)
    written = generator.write()

    assert written == output_path
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert "packages" in payload
    assert "edges" in payload
