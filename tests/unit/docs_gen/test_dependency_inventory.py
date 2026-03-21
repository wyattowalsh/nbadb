from __future__ import annotations

import json
from typing import TYPE_CHECKING

from nbadb.docs_gen.dependency_inventory import DependencyInventoryGenerator

if TYPE_CHECKING:
    from pathlib import Path
    pass


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


# ---------------------------------------------------------------------------
# _parse_requirement
# ---------------------------------------------------------------------------


class TestParseRequirement:
    def test_simple_with_version(self) -> None:
        name, constraint = DependencyInventoryGenerator._parse_requirement("polars>=1.0")
        assert name == "polars"
        assert constraint == ">=1.0"

    def test_with_extras(self) -> None:
        name, constraint = DependencyInventoryGenerator._parse_requirement("pandera[polars]>=0.29")
        assert name == "pandera"
        assert "0.29" in constraint

    def test_with_marker(self) -> None:
        name, constraint = DependencyInventoryGenerator._parse_requirement(
            'tomli>=1.0; python_version < "3.11"'
        )
        assert name == "tomli"
        assert constraint == ">=1.0"

    def test_bare_name(self) -> None:
        name, constraint = DependencyInventoryGenerator._parse_requirement("requests")
        assert name == "requests"
        assert constraint == ""

    def test_complex_version_spec(self) -> None:
        name, constraint = DependencyInventoryGenerator._parse_requirement("click>=8.1,<9.0")
        assert name == "click"
        assert "8.1" in constraint


# ---------------------------------------------------------------------------
# _normalize_name
# ---------------------------------------------------------------------------


class TestNormalizeName:
    def test_underscore_to_dash(self) -> None:
        assert DependencyInventoryGenerator._normalize_name("my_package") == "my-package"

    def test_uppercase_to_lower(self) -> None:
        assert DependencyInventoryGenerator._normalize_name("MyPackage") == "mypackage"

    def test_already_normalized(self) -> None:
        assert DependencyInventoryGenerator._normalize_name("requests") == "requests"

    def test_mixed(self) -> None:
        assert DependencyInventoryGenerator._normalize_name("My_Package") == "my-package"


# ---------------------------------------------------------------------------
# _parse_uv_lock
# ---------------------------------------------------------------------------


class TestParseUvLock:
    def test_basic_packages_and_edges(self, tmp_path: Path) -> None:
        gen = DependencyInventoryGenerator(project_root=tmp_path)
        payload = {
            "package": [
                {
                    "name": "foo",
                    "version": "1.0",
                    "dependencies": [{"name": "bar", "version": ">=2.0"}],
                },
                {"name": "bar", "version": "2.0"},
            ]
        }
        pkgs, edges = gen._parse_uv_lock(payload)
        assert len(pkgs) == 2
        assert any(e["from"] == "foo" and e["to"] == "bar" for e in edges)

    def test_empty_packages(self, tmp_path: Path) -> None:
        gen = DependencyInventoryGenerator(project_root=tmp_path)
        pkgs, edges = gen._parse_uv_lock({"package": []})
        assert pkgs == []
        assert edges == []

    def test_string_dependency(self, tmp_path: Path) -> None:
        gen = DependencyInventoryGenerator(project_root=tmp_path)
        payload = {
            "package": [
                {
                    "name": "foo",
                    "version": "1.0",
                    "dependencies": ["bar>=2.0"],
                },
            ]
        }
        pkgs, edges = gen._parse_uv_lock(payload)
        assert len(edges) == 1
        assert edges[0]["to"] == "bar"


# ---------------------------------------------------------------------------
# _parse_poetry_lock
# ---------------------------------------------------------------------------


class TestParsePoetryLock:
    def test_basic_packages_and_edges(self, tmp_path: Path) -> None:
        gen = DependencyInventoryGenerator(project_root=tmp_path)
        payload = {
            "package": [
                {
                    "name": "foo",
                    "version": "1.0",
                    "dependencies": {"bar": "^2.0"},
                },
                {"name": "bar", "version": "2.0"},
            ]
        }
        pkgs, edges = gen._parse_poetry_lock(payload)
        assert len(pkgs) == 2
        assert any(e["from"] == "foo" and e["to"] == "bar" for e in edges)

    def test_dict_dependency_spec(self, tmp_path: Path) -> None:
        gen = DependencyInventoryGenerator(project_root=tmp_path)
        payload = {
            "package": [
                {
                    "name": "foo",
                    "version": "1.0",
                    "dependencies": {"bar": {"version": ">=2.0", "optional": True}},
                },
            ]
        }
        pkgs, edges = gen._parse_poetry_lock(payload)
        assert len(edges) == 1
        assert edges[0]["constraint"] == ">=2.0"

    def test_empty_dependencies(self, tmp_path: Path) -> None:
        gen = DependencyInventoryGenerator(project_root=tmp_path)
        payload = {"package": [{"name": "foo", "version": "1.0"}]}
        pkgs, edges = gen._parse_poetry_lock(payload)
        assert len(pkgs) == 1
        assert edges == []


# ---------------------------------------------------------------------------
# build_inventory with minimal pyproject
# ---------------------------------------------------------------------------


class TestBuildInventoryMinimal:
    def test_with_minimal_pyproject(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "test-proj"\nversion = "0.1.0"\n'
            'dependencies = ["requests>=2.0"]\n',
            encoding="utf-8",
        )
        gen = DependencyInventoryGenerator(project_root=tmp_path)
        inv = gen.build_inventory()
        assert inv["project"]["name"] == "test-proj"
        assert inv["project"]["version"] == "0.1.0"
        # Should have at least the project itself + requests
        names = {p["name"] for p in inv["packages"]}
        assert "requests" in names

    def test_with_optional_dependencies(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "test"\nversion = "0.1"\n'
            'dependencies = []\n\n'
            '[project.optional-dependencies]\n'
            'dev = ["pytest>=7.0"]\n',
            encoding="utf-8",
        )
        gen = DependencyInventoryGenerator(project_root=tmp_path)
        inv = gen.build_inventory()
        names = {p["name"] for p in inv["packages"]}
        assert "pytest" in names

    def test_no_pyproject(self, tmp_path: Path) -> None:
        gen = DependencyInventoryGenerator(project_root=tmp_path)
        inv = gen.build_inventory()
        # Should still return a valid structure
        assert "packages" in inv
        assert "edges" in inv
