"""Complete installed-package and reconciled source-surface authority.

The provider wheel is an input, not an oracle.  This module verifies every
entry in the installed distribution's ``RECORD`` (including dist-info files),
then binds the source-derived request/response atoms produced by the
independent verifier.  It performs no provider or network calls.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib.metadata
import io
import json
import stat
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from importlib.metadata import Distribution

NBA_API_DISTRIBUTION: Final = "nba-api"
NBA_API_VERSION: Final = "1.11.4"
NBA_API_RECORD_ENTRY_COUNT: Final = 195
NBA_API_RECORD_HASHED_ENTRY_COUNT: Final = 194
NBA_API_RECORD_SHA256: Final = "b75304af37c0d8a1bcc8f429bccb4a7d58e707586af6da9efa5cb0d730aa72f1"
NBA_API_RECORD_ENTRIES_SHA256: Final = (
    "a4ce72f52e3a54dd6a2425121c12a9208fca060830569e1fe2115daaa114c1aa"
)
NBA_API_RECORD_AUTHORITY_SHA256: Final = (
    "c644ee6a70347b2f49a0064d237aebaaf82f4522e2b78faf5347afe99c516aa8"
)


class NbaApiSurfaceInventoryError(ValueError):
    """The exact installed package or source-surface authority is invalid."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NbaApiSurfaceInventoryError("surface inventory is not canonical JSON") from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _safe_record_path(value: str) -> PurePosixPath:
    if not value or "\\" in value:
        raise NbaApiSurfaceInventoryError("distribution RECORD contains an unsafe path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.parts[0] not in {"nba_api", f"nba_api-{NBA_API_VERSION}.dist-info"}
    ):
        raise NbaApiSurfaceInventoryError("distribution RECORD contains an unsafe path")
    return path


def _read_regular_file(root: Path, path: PurePosixPath) -> bytes:
    candidate = root.joinpath(*path.parts)
    try:
        metadata = candidate.stat(follow_symlinks=False)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        if candidate.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise NbaApiSurfaceInventoryError("distribution RECORD member is not a regular file")
        return candidate.read_bytes()
    except NbaApiSurfaceInventoryError:
        raise
    except (OSError, ValueError) as exc:
        raise NbaApiSurfaceInventoryError(
            "distribution RECORD member cannot be read safely"
        ) from exc


@dataclass(frozen=True, slots=True)
class DistributionRecordEntry:
    """One exact installed ``RECORD`` row plus its observed file identity."""

    path: str
    record_hash: str | None
    record_size: int | None
    sha256: str
    size: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DistributionRecordAuthority:
    """Complete exact-pin authority for every installed distribution file."""

    entries: tuple[DistributionRecordEntry, ...]
    record_sha256: str
    entries_sha256: str
    authority_sha256: str

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    @property
    def hashed_entry_count(self) -> int:
        return sum(entry.record_hash is not None for entry in self.entries)

    @property
    def unhashed_paths(self) -> tuple[str, ...]:
        return tuple(entry.path for entry in self.entries if entry.record_hash is None)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "nbadb_nba_api_distribution_record_authority",
            "distribution_name": NBA_API_DISTRIBUTION,
            "distribution_version": NBA_API_VERSION,
            "entry_count": self.entry_count,
            "hashed_entry_count": self.hashed_entry_count,
            "unhashed_paths": list(self.unhashed_paths),
            "record_sha256": self.record_sha256,
            "entries": [entry.to_dict() for entry in self.entries],
            "entries_sha256": self.entries_sha256,
            "authority_sha256": self.authority_sha256,
        }


def build_distribution_record_authority(
    distribution: Distribution | None = None,
) -> DistributionRecordAuthority:
    """Verify and return all installed ``nba-api`` ``RECORD`` members.

    The sole unhashed member must be ``RECORD`` itself.  Every other row must
    carry a size and URL-safe base64 SHA-256 that matches a regular file under
    the distribution root.  Exact-pin counts and canonical digests prevent a
    count-preserving replacement from becoming a new authority.
    """

    try:
        installed = distribution or importlib.metadata.distribution(NBA_API_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError as exc:
        raise NbaApiSurfaceInventoryError("pinned nba_api distribution is not installed") from exc
    if installed.version != NBA_API_VERSION:
        raise NbaApiSurfaceInventoryError("installed nba_api version differs from the exact pin")
    files = installed.files
    if files is None:
        raise NbaApiSurfaceInventoryError("installed nba_api distribution has no RECORD")
    record_paths = tuple(str(path) for path in files if str(path).endswith(".dist-info/RECORD"))
    if len(record_paths) != 1:
        raise NbaApiSurfaceInventoryError("installed nba_api distribution has ambiguous RECORD")
    root = Path(str(installed.locate_file(""))).resolve(strict=True)
    record_path = _safe_record_path(record_paths[0])
    record_bytes = _read_regular_file(root, record_path)
    try:
        text = record_bytes.decode("utf-8", errors="strict")
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise NbaApiSurfaceInventoryError("distribution RECORD cannot be decoded") from exc
    if not rows or any(len(row) != 3 for row in rows):
        raise NbaApiSurfaceInventoryError("distribution RECORD rows are malformed")
    paths = [row[0] for row in rows]
    if paths != sorted(set(paths)) or paths != sorted(str(path) for path in files):
        raise NbaApiSurfaceInventoryError(
            "distribution RECORD inventory is noncanonical or incomplete"
        )

    entries: list[DistributionRecordEntry] = []
    for raw_path, record_hash, record_size in rows:
        path = _safe_record_path(raw_path)
        raw = _read_regular_file(root, path)
        observed_digest = hashlib.sha256(raw).digest()
        observed_hex = observed_digest.hex()
        if record_hash:
            if not record_hash.startswith("sha256="):
                raise NbaApiSurfaceInventoryError("distribution RECORD hash is not SHA-256")
            encoded = record_hash.removeprefix("sha256=")
            try:
                decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            except (ValueError, TypeError) as exc:
                raise NbaApiSurfaceInventoryError(
                    "distribution RECORD hash is not canonical base64url"
                ) from exc
            if (
                decoded != observed_digest
                or base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != encoded
            ):
                raise NbaApiSurfaceInventoryError(
                    "distribution RECORD file or hash differs from the exact install"
                )
            if record_size != str(len(raw)):
                raise NbaApiSurfaceInventoryError("distribution RECORD file size differs")
            size: int | None = len(raw)
        else:
            if path != record_path or record_size:
                raise NbaApiSurfaceInventoryError(
                    "only distribution RECORD may omit its own hash and size"
                )
            size = None
        entries.append(
            DistributionRecordEntry(
                path=raw_path,
                record_hash=record_hash or None,
                record_size=size,
                sha256=observed_hex,
                size=len(raw),
            )
        )

    canonical_entries = tuple(entries)
    entries_payload = [entry.to_dict() for entry in canonical_entries]
    entries_sha256 = _digest(entries_payload)
    body: dict[str, Any] = {
        "schema_version": 1,
        "kind": "nbadb_nba_api_distribution_record_authority",
        "distribution_name": NBA_API_DISTRIBUTION,
        "distribution_version": NBA_API_VERSION,
        "entry_count": len(canonical_entries),
        "hashed_entry_count": sum(entry.record_hash is not None for entry in canonical_entries),
        "unhashed_paths": [entry.path for entry in canonical_entries if entry.record_hash is None],
        "record_sha256": hashlib.sha256(record_bytes).hexdigest(),
        "entries": entries_payload,
        "entries_sha256": entries_sha256,
    }
    authority = DistributionRecordAuthority(
        entries=canonical_entries,
        record_sha256=str(body["record_sha256"]),
        entries_sha256=entries_sha256,
        authority_sha256=_digest(body),
    )
    expected = (
        authority.entry_count == NBA_API_RECORD_ENTRY_COUNT,
        authority.hashed_entry_count == NBA_API_RECORD_HASHED_ENTRY_COUNT,
        authority.unhashed_paths == (record_path.as_posix(),),
        authority.record_sha256 == NBA_API_RECORD_SHA256,
        authority.entries_sha256 == NBA_API_RECORD_ENTRIES_SHA256,
        authority.authority_sha256 == NBA_API_RECORD_AUTHORITY_SHA256,
    )
    if not all(expected):
        raise NbaApiSurfaceInventoryError(
            "installed nba_api RECORD differs from the exact pinned authority"
        )
    return authority


def build_nba_api_surface_inventory() -> dict[str, object]:
    """Return the production-bindable all-file and source-atom authority."""

    # Local imports keep the independent verifier free of an import cycle.
    from nbadb.core.nba_api_request_surface import pinned_request_surface_authority
    from nbadb.core.nba_api_request_surface_verifier import (
        build_independent_package_inventory,
        build_independent_surface_atoms,
        build_primary_surface_atoms,
    )

    record = build_distribution_record_authority()
    primary_atoms = build_primary_surface_atoms()
    independent_atoms = build_independent_surface_atoms()
    if primary_atoms != independent_atoms:
        raise NbaApiSurfaceInventoryError("primary and independently derived source atoms differ")
    package_inventory = build_independent_package_inventory()
    request_authority = pinned_request_surface_authority()
    payload: dict[str, object] = {
        "schema_version": 1,
        "kind": "nbadb_nba_api_surface_inventory",
        "distribution_record": record.to_dict(),
        "request_surface_sha256": request_authority.surface_sha256,
        "runtime_contract_payload_sha256": (request_authority.runtime_contract_payload_sha256),
        "source_atom_count": len(independent_atoms),
        "source_atoms_sha256": _digest(list(independent_atoms)),
        "source_atoms": list(independent_atoms),
        "independent_package_inventory": asdict(package_inventory),
        "reserved_authorities": {
            "league_finite_values": "pending_A1.2a",
            "release_terminal_state": "pending_A1.3a",
        },
    }
    payload["inventory_sha256"] = _digest(payload)
    return payload


__all__ = [
    "DistributionRecordAuthority",
    "DistributionRecordEntry",
    "NBA_API_RECORD_AUTHORITY_SHA256",
    "NBA_API_RECORD_ENTRIES_SHA256",
    "NBA_API_RECORD_ENTRY_COUNT",
    "NBA_API_RECORD_HASHED_ENTRY_COUNT",
    "NBA_API_RECORD_SHA256",
    "NbaApiSurfaceInventoryError",
    "build_distribution_record_authority",
    "build_nba_api_surface_inventory",
]
