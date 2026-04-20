from __future__ import annotations

import argparse
import json
import re
import tomllib
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

_REQUIREMENT_PATTERN = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]+\])?\s*(?P<constraint>.*)$"
)
_LOCKFILE_CANDIDATES = (
    "poetry.lock",
    "uv.lock",
    "Pipfile.lock",
    "pdm.lock",
    "requirements.lock",
    "requirements.txt",
)
_DOCS_LOCKFILE_CANDIDATES = (
    "docs/pnpm-lock.yaml",
    "docs/package-lock.json",
    "docs/yarn.lock",
)


class DependencyInventoryGenerator:
    def __init__(
        self,
        project_root: Path | None = None,
        pyproject_path: Path | None = None,
        docs_package_path: Path | None = None,
        lock_path: Path | None = None,
        output_path: Path | None = None,
    ) -> None:
        self.project_root = self._resolve_project_root(
            project_root=project_root,
            pyproject_path=pyproject_path,
            lock_path=lock_path,
        )
        self.pyproject_path = pyproject_path or self.project_root / "pyproject.toml"
        self.docs_package_path = docs_package_path or self.project_root / "docs" / "package.json"
        self.lock_path = lock_path or self._detect_primary_lockfile()
        self.output_path = output_path or self.project_root / "dependency-inventory.json"

    def _resolve_project_root(
        self,
        project_root: Path | None,
        pyproject_path: Path | None,
        lock_path: Path | None,
    ) -> Path:
        if project_root is not None:
            return Path(project_root)
        if pyproject_path is not None:
            return Path(pyproject_path).parent
        if lock_path is not None:
            return Path(lock_path).parent
        return Path.cwd()

    def _detect_primary_lockfile(self) -> Path | None:
        for relative in _LOCKFILE_CANDIDATES:
            candidate = self.project_root / relative
            if candidate.exists():
                return candidate
        return None

    @staticmethod
    def _parse_requirement(requirement: str) -> tuple[str, str]:
        marker_free = requirement.split(";", maxsplit=1)[0].strip()
        match = _REQUIREMENT_PATTERN.match(marker_free)
        if match is None:
            return marker_free, ""
        return match.group("name"), match.group("constraint").strip()

    @staticmethod
    def _normalize_name(name: str) -> str:
        return name.lower().replace("_", "-")

    def _get_installed_versions(self) -> dict[str, str]:
        versions: dict[str, str] = {}
        for distribution in metadata.distributions():
            name = distribution.metadata.get("Name")
            if name:
                versions[self._normalize_name(name)] = distribution.version
        return versions

    def _read_toml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return {}

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _parse_poetry_lock(
        self, payload: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        packages: list[dict[str, Any]] = []
        edges: list[dict[str, str]] = []

        for package in payload.get("package", []):
            name = str(package.get("name", "")).strip()
            if not name:
                continue
            packages.append(
                {
                    "name": name,
                    "version": str(package.get("version", "")),
                    "source": "lockfile",
                }
            )
            dependencies = package.get("dependencies", {}) or {}
            if isinstance(dependencies, dict):
                for dep_name, dep_spec in dependencies.items():
                    if isinstance(dep_spec, str):
                        constraint = dep_spec
                    elif isinstance(dep_spec, dict):
                        constraint = str(dep_spec.get("version", ""))
                    else:
                        constraint = ""
                    edges.append(
                        {
                            "from": name,
                            "to": str(dep_name),
                            "constraint": constraint,
                        }
                    )

        return packages, edges

    def _parse_uv_lock(
        self, payload: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        packages: list[dict[str, Any]] = []
        edges: list[dict[str, str]] = []

        for package in payload.get("package", []):
            name = str(package.get("name", "")).strip()
            if not name:
                continue
            packages.append(
                {
                    "name": name,
                    "version": str(package.get("version", "")),
                    "source": "lockfile",
                }
            )

            dependencies = package.get("dependencies", []) or []
            if not isinstance(dependencies, list):
                continue
            for dep in dependencies:
                if isinstance(dep, str):
                    dep_name, constraint = self._parse_requirement(dep)
                elif isinstance(dep, dict):
                    dep_name = str(dep.get("name", "")).strip()
                    constraint = str(dep.get("version", dep.get("specifier", "")))
                else:
                    dep_name = ""
                    constraint = ""

                if dep_name:
                    edges.append(
                        {
                            "from": name,
                            "to": dep_name,
                            "constraint": constraint,
                        }
                    )

        return packages, edges

    def _parse_lockfile(self) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        if self.lock_path is None or not self.lock_path.exists():
            return [], []

        payload = self._read_toml(self.lock_path)
        if not payload:
            return [], []

        if self.lock_path.name == "poetry.lock":
            return self._parse_poetry_lock(payload)
        if self.lock_path.name == "uv.lock":
            return self._parse_uv_lock(payload)
        return [], []

    def _lockfile_presence(self) -> dict[str, dict[str, Any]]:
        entries: dict[str, dict[str, Any]] = {}
        candidates = list(_LOCKFILE_CANDIDATES) + list(_DOCS_LOCKFILE_CANDIDATES)
        for relative in candidates:
            path = self.project_root / relative
            entries[relative] = {"present": path.exists(), "path": str(path)}

        if self.lock_path is not None:
            key = self.lock_path.name
            entries[key] = {
                "present": self.lock_path.exists(),
                "path": str(self.lock_path),
            }

        return entries

    def build_inventory(self) -> dict[str, Any]:
        pyproject = self._read_toml(self.pyproject_path)
        docs_package = self._read_json(self.docs_package_path)
        installed_versions = self._get_installed_versions()
        lock_packages, lock_edges = self._parse_lockfile()

        package_index: dict[str, dict[str, Any]] = {}

        def upsert_package(package: dict[str, Any]) -> None:
            name = str(package.get("name", "")).strip()
            if not name:
                return
            key = self._normalize_name(name)
            installed = installed_versions.get(key)
            if installed:
                package["installed_version"] = installed

            if key in package_index:
                existing = package_index[key]
                existing.update({k: v for k, v in package.items() if v not in ("", None, [], {})})
            else:
                package_index[key] = package

        for package in lock_packages:
            upsert_package(package)

        edges: list[dict[str, str]] = []
        edge_index: set[tuple[str, str, str]] = set()

        def add_edge(source: str, target: str, constraint: str) -> None:
            edge_key = (source, target, constraint)
            if edge_key in edge_index:
                return
            edge_index.add(edge_key)
            edges.append({"from": source, "to": target, "constraint": constraint})

        for edge in lock_edges:
            add_edge(edge["from"], edge["to"], edge.get("constraint", ""))

        project_meta = pyproject.get("project", {}) if isinstance(pyproject, dict) else {}
        project_name = str(project_meta.get("name", self.project_root.name))
        project_version = str(project_meta.get("version", ""))
        requires_python = str(project_meta.get("requires-python", ""))

        if project_meta:
            upsert_package(
                {
                    "name": project_name,
                    "version": project_version,
                    "requires_python": requires_python,
                    "source": "pyproject",
                    "kind": "project",
                }
            )

        dependencies = (
            project_meta.get("dependencies", []) if isinstance(project_meta, dict) else []
        )
        for requirement in dependencies:
            if not isinstance(requirement, str):
                continue
            dep_name, constraint = self._parse_requirement(requirement)
            upsert_package({"name": dep_name, "source": "pyproject", "kind": "python"})
            add_edge(project_name, dep_name, constraint)

        optional_groups = (
            project_meta.get("optional-dependencies", {}) if isinstance(project_meta, dict) else {}
        )
        if isinstance(optional_groups, dict):
            for group, requirements in optional_groups.items():
                for requirement in requirements or []:
                    if not isinstance(requirement, str):
                        continue
                    dep_name, constraint = self._parse_requirement(requirement)
                    upsert_package(
                        {
                            "name": dep_name,
                            "source": f"pyproject[{group}]",
                            "kind": "python",
                        }
                    )
                    add_edge(project_name, dep_name, constraint)

        docs_name = str(docs_package.get("name", "")).strip()
        if docs_name:
            upsert_package(
                {
                    "name": docs_name,
                    "source": "docs/package.json",
                    "kind": "docs-project",
                }
            )
            for section in ("dependencies", "devDependencies"):
                section_payload = docs_package.get(section, {})
                if not isinstance(section_payload, dict):
                    continue
                for dep_name, dep_version in section_payload.items():
                    upsert_package(
                        {
                            "name": dep_name,
                            "source": f"docs/package.json#{section}",
                            "kind": "node",
                        }
                    )
                    add_edge(docs_name, dep_name, str(dep_version))

        packages = sorted(
            package_index.values(),
            key=lambda item: self._normalize_name(item["name"]),
        )
        lockfile_format = self.lock_path.suffix.lstrip(".") if self.lock_path is not None else ""

        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "project": {
                "root": str(self.project_root),
                "name": project_name,
                "version": project_version,
                "requires_python": requires_python,
            },
            "pyproject": {
                "path": str(self.pyproject_path),
                "present": self.pyproject_path.exists(),
            },
            "docs_package": {
                "path": str(self.docs_package_path),
                "present": self.docs_package_path.exists(),
                "name": docs_name or None,
            },
            "lockfile": {
                "path": str(self.lock_path) if self.lock_path is not None else None,
                "present": (self.lock_path.exists() if self.lock_path is not None else False),
                "format": lockfile_format,
                "package_count": len(lock_packages),
            },
            "lockfiles": self._lockfile_presence(),
            "packages": packages,
            "edges": edges,
            "summary": {
                "package_count": len(packages),
                "edge_count": len(edges),
            },
        }

    def generate_json(self) -> str:
        return json.dumps(self.build_inventory(), indent=2)

    def write(self, output_path: Path | None = None) -> Path:
        destination = output_path or self.output_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(self.generate_json() + "\n", encoding="utf-8")
        return destination


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate dependency inventory artifact JSON.")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root directory (defaults to cwd).",
    )
    parser.add_argument(
        "--pyproject-path",
        type=Path,
        default=None,
        help="Path to pyproject.toml (defaults to <project-root>/pyproject.toml).",
    )
    parser.add_argument(
        "--docs-package-path",
        type=Path,
        default=None,
        help=("Path to docs package.json (defaults to <project-root>/docs/package.json)."),
    )
    parser.add_argument(
        "--lock-path",
        type=Path,
        default=None,
        help="Path to lockfile to parse (defaults to detected poetry.lock/uv.lock).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON path (defaults to <project-root>/dependency-inventory.json).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    generator = DependencyInventoryGenerator(
        project_root=args.project_root,
        pyproject_path=args.pyproject_path,
        docs_package_path=args.docs_package_path,
        lock_path=args.lock_path,
        output_path=args.output,
    )
    written = generator.write()
    print(written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
