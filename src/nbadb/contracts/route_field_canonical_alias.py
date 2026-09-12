"""Value-free proof that one route landing is a canonical view of another.

The receipt deliberately projects only public landing and field identities.  It
never serializes or inspects the value-bearing inventories carried by
``RouteFieldLandingReceiptV2``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import ClassVar, Final, Never, Self, cast

from nbadb.contracts.raw_request_authority import ObservationRouteLandingV2
from nbadb.contracts.typed_field_value_receipt import (
    MAX_ROUTE_CANONICAL_BYTES,
    MAX_ROUTE_FIELDS,
    MAX_ROUTE_ROWS,
    LandingFieldAuthorityV2,
    RouteFieldLandingReceiptV2,
)

__all__ = [
    "MAX_ROUTE_FIELD_CANONICAL_ALIAS_CANDIDATES",
    "ROUTE_FIELD_CANONICAL_ALIAS_FIELD_COLUMNS",
    "ROUTE_FIELD_CANONICAL_ALIAS_RECEIPT_COLUMNS",
    "ROUTE_FIELD_CANONICAL_ALIAS_SCHEMA_VERSION",
    "RouteFieldCanonicalAliasError",
    "RouteFieldCanonicalAliasFieldV1",
    "RouteFieldCanonicalAliasReceiptV1",
]


ROUTE_FIELD_CANONICAL_ALIAS_SCHEMA_VERSION: Final = 1
MAX_ROUTE_FIELD_CANONICAL_ALIAS_CANDIDATES: Final = 1_000_000

_MAX_FIELD_CANONICAL_BYTES: Final = 32 * 1024
_MAX_FIELDS_JSON_BYTES: Final = (MAX_ROUTE_FIELDS * 16 * 1024) + 4_096
_MAX_RECEIPT_CANONICAL_BYTES: Final = _MAX_FIELDS_JSON_BYTES + (64 * 1024)

_FIELD_KIND: Final = "route_field_canonical_alias_field_v1"
_RECEIPT_KIND: Final = "route_field_canonical_alias_receipt_v1"
_FIELD_ROOT_KIND: Final = "route_field_canonical_alias_fields_v1"

_TARGET_SOURCE_SHAPES: Final = frozenset(
    {
        "selected_result_bound",
        "body_node_bound",
        "hybrid_result_body_bound",
        "live_lossless_bound",
    }
)
_FIELD_ORIGINS: Final = frozenset(
    {"provider_bound", "provider_multi_bound", "lossless_bound", "storage_only"}
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,511}\Z", flags=re.ASCII)
_CAMEL_ACRONYM_BOUNDARY_RE = re.compile(r"([A-Z]+)([A-Z][a-z])", flags=re.ASCII)
_CAMEL_WORD_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])", flags=re.ASCII)
_KEY_SEPARATOR_RE = re.compile(r"[^A-Za-z0-9]+", flags=re.ASCII)
_SENSITIVE_KEY_RE = re.compile(
    r"(?:authorization|proxy_authorization|authentication|cookie|set_cookie|credential|"
    r"secret|token|client_secret|client_key|access_token|refresh_token|id_token|api_key|"
    r"apikey|password|passwd|proxy_url|proxy_host|vpn_server|vpn_ip|vpn_password|"
    r"request_headers|response_headers|runner_path|workspace_path|local_path|file_path|"
    r"github_token|gh_token|pat|private_key|secret_key|personal_access_token|"
    r"ssh_private_key)\Z",
    flags=re.ASCII,
)
_GENERIC_SENSITIVE_COMPONENTS: Final = frozenset({"auth", "session", "secret", "token"})
_AUTHORIZATION_SECRET_RE = re.compile(
    r"authorization\s*:\s*(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}",
    flags=re.ASCII | re.IGNORECASE,
)
_BEARER_SECRET_RE = re.compile(
    r"bearer\s+[A-Za-z0-9._~+/=-]{20,}(?![A-Za-z0-9._~+/=-])",
    flags=re.ASCII | re.IGNORECASE,
)
_BASIC_SECRET_RE = re.compile(
    r"basic\s+[A-Za-z0-9+/=]{12,}(?![A-Za-z0-9+/=])",
    flags=re.ASCII | re.IGNORECASE,
)
_LOCAL_PATH_RE = re.compile(
    r"(?:/Users/[^/\x00\s]+(?=/|\s|\Z)|/home/[^/\x00\s]+(?=/|\s|\Z)|"
    r"/private/var(?![A-Za-z0-9_])|[A-Za-z]:\\Users\\)"
)
_EMBEDDED_SECRET_RES: Final = (
    re.compile(r"\bgh[opurs]_[A-Za-z0-9]{20,}\b", flags=re.ASCII),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b", flags=re.ASCII),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b", flags=re.ASCII),
    re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
        flags=re.ASCII,
    ),
)

ROUTE_FIELD_CANONICAL_ALIAS_FIELD_COLUMNS: Final = (
    "schema_version",
    "field_sha256",
    "field_ordinal",
    "field_name",
    "alias_raw_route_landing_sha256",
    "alias_route_id",
    "alias_staging_key",
    "target_raw_route_landing_sha256",
    "target_route_id",
    "target_staging_key",
    "target_route_landing_receipt_sha256",
    "target_field_authority_sha256",
    "field_origin",
    "logical_type_sha256",
)

ROUTE_FIELD_CANONICAL_ALIAS_RECEIPT_COLUMNS: Final = (
    "schema_version",
    "receipt_sha256",
    "raw_authority_bundle_sha256",
    "alias_raw_route_landing_sha256",
    "alias_observation_sha256",
    "alias_route_ordinal",
    "alias_route_id",
    "alias_staging_key",
    "alias_receipt_root_sha256",
    "alias_content_hash",
    "alias_persisted_row_count",
    "alias_persisted_content_sha256",
    "alias_persisted_schema_sha256",
    "target_raw_route_landing_sha256",
    "target_observation_sha256",
    "target_route_ordinal",
    "target_route_id",
    "target_staging_key",
    "target_receipt_root_sha256",
    "target_route_landing_receipt_sha256",
    "target_source_shape",
    "target_content_hash",
    "target_persisted_row_count",
    "target_persisted_content_sha256",
    "target_persisted_schema_sha256",
    "target_fields_sha256",
    "field_count",
    "field_root_sha256",
    "fields_json",
)


class RouteFieldCanonicalAliasError(ValueError):
    """A canonical-alias receipt is unsafe, ambiguous, or inconsistently bound."""


def _fail(message: str) -> Never:
    raise RouteFieldCanonicalAliasError(message)


def _sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact lowercase SHA-256")
    return value


def _bounded_integer(value: object, *, label: str, maximum: int) -> int:
    if type(value) is not int or value < 0 or value > maximum:
        _fail(f"{label} must be one bounded nonnegative exact integer")
    return value


def _normalized_key(value: str) -> str:
    separated = _CAMEL_ACRONYM_BOUNDARY_RE.sub(r"\1_\2", value)
    separated = _CAMEL_WORD_BOUNDARY_RE.sub(r"\1_\2", separated)
    return _KEY_SEPARATOR_RE.sub("_", separated).strip("_").lower()


def _reject_secret_or_local(value: str, *, label: str) -> None:
    normalized = _normalized_key(value)
    if (
        _AUTHORIZATION_SECRET_RE.search(value) is not None
        or _BEARER_SECRET_RE.search(value) is not None
        or _BASIC_SECRET_RE.search(value) is not None
        or _LOCAL_PATH_RE.search(value) is not None
        or _SENSITIVE_KEY_RE.fullmatch(normalized) is not None
        or any(component in _GENERIC_SENSITIVE_COMPONENTS for component in normalized.split("_"))
        or any(pattern.search(value) is not None for pattern in _EMBEDDED_SECRET_RES)
    ):
        _fail(f"{label} is not public-safe")


def _safe_id(value: object, *, label: str) -> str:
    if type(value) is not str or _SAFE_ID_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact public-safe identifier")
    _reject_secret_or_local(value, label=label)
    return value


def _safe_field_name(value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        _fail("canonical-alias field name must be nonempty exact text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _fail("canonical-alias field name contains invalid Unicode")
    if len(encoded) > 8_192 or any(ord(character) < 0x20 for character in value):
        _fail("canonical-alias field name exceeds its public text bound")
    _reject_secret_or_local(value, label="canonical-alias field name")
    return value


def _canonical_json_bytes(value: object, *, maximum_bytes: int, label: str) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError) as exc:
        raise RouteFieldCanonicalAliasError(f"{label} is not canonical JSON") from exc
    if not encoded or len(encoded) > maximum_bytes:
        _fail(f"{label} exceeds its canonical byte bound")
    return encoded


def _canonical_sha256(value: object, *, maximum_bytes: int, label: str) -> str:
    return hashlib.sha256(
        _canonical_json_bytes(value, maximum_bytes=maximum_bytes, label=label)
    ).hexdigest()


def _reject_json_constant(value: str) -> Never:
    _fail(f"canonical-alias JSON contains unsupported constant {value!r}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if type(key) is not str or key in result:
            _fail("canonical-alias JSON contains a duplicate or non-text key")
        result[key] = value
    return result


def _decode_canonical_json(
    encoded: object,
    *,
    maximum_bytes: int,
    label: str,
) -> object:
    if type(encoded) is not bytes or not encoded or len(encoded) > maximum_bytes:
        _fail(f"{label} is absent, mutable, or over bound")
    try:
        decoded_text = encoded.decode("utf-8", errors="strict")
        value = json.loads(
            decoded_text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RouteFieldCanonicalAliasError(f"{label} is not exact UTF-8 JSON") from exc
    if _canonical_json_bytes(value, maximum_bytes=maximum_bytes, label=label) != encoded:
        _fail(f"{label} is not in canonical byte form")
    return value


def _strict_row(
    value: object,
    *,
    columns: tuple[str, ...],
    label: str,
) -> dict[str, object]:
    if type(value) is not dict:
        _fail(f"{label} lacks its exact ordered columns")
    mapping = cast("dict[object, object]", value)
    if any(type(key) is not str for key in mapping) or tuple(mapping) != columns:
        _fail(f"{label} lacks its exact ordered columns")
    return cast("dict[str, object]", value)


def _field_root(fields: tuple[RouteFieldCanonicalAliasFieldV1, ...]) -> str:
    return _canonical_sha256(
        {
            "schema_version": ROUTE_FIELD_CANONICAL_ALIAS_SCHEMA_VERSION,
            "kind": _FIELD_ROOT_KIND,
            "count": len(fields),
            "items": [field.field_sha256 for field in fields],
        },
        maximum_bytes=_MAX_FIELDS_JSON_BYTES,
        label="canonical-alias ordered field root",
    )


@dataclass(frozen=True, slots=True)
class RouteFieldCanonicalAliasFieldV1:
    """One alias-specific field binding to an unchanged target authority."""

    field_sha256: str
    field_ordinal: int
    field_name: str
    alias_raw_route_landing_sha256: str
    alias_route_id: str
    alias_staging_key: str
    target_raw_route_landing_sha256: str
    target_route_id: str
    target_staging_key: str
    target_route_landing_receipt_sha256: str
    target_field_authority_sha256: str
    field_origin: str
    logical_type_sha256: str

    schema_version: ClassVar[int] = ROUTE_FIELD_CANONICAL_ALIAS_SCHEMA_VERSION
    kind: ClassVar[str] = _FIELD_KIND

    def __post_init__(self) -> None:
        for label, value in (
            ("canonical-alias field identity", self.field_sha256),
            ("alias raw route landing", self.alias_raw_route_landing_sha256),
            ("target raw route landing", self.target_raw_route_landing_sha256),
            ("target route landing receipt", self.target_route_landing_receipt_sha256),
            ("target field authority", self.target_field_authority_sha256),
            ("canonical-alias logical type", self.logical_type_sha256),
        ):
            _sha256(value, label=label)
        _bounded_integer(
            self.field_ordinal,
            label="canonical-alias field ordinal",
            maximum=MAX_ROUTE_FIELDS - 1,
        )
        _safe_field_name(self.field_name)
        _safe_id(self.alias_route_id, label="canonical-alias route ID")
        _safe_id(self.alias_staging_key, label="canonical-alias staging key")
        _safe_id(self.target_route_id, label="canonical target route ID")
        _safe_id(self.target_staging_key, label="canonical target staging key")
        if self.alias_route_id == self.target_route_id:
            _fail("canonical alias cannot relabel its target as the alias route")
        if type(self.field_origin) is not str or self.field_origin not in _FIELD_ORIGINS:
            _fail("canonical-alias field origin is outside the closed domain")
        if self.field_sha256 != _canonical_sha256(
            self.identity_payload(),
            maximum_bytes=_MAX_FIELD_CANONICAL_BYTES,
            label="canonical-alias field identity",
        ):
            _fail("canonical-alias field digest differs from its exact identity")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "field_ordinal": self.field_ordinal,
            "field_name": self.field_name,
            "alias_raw_route_landing_sha256": self.alias_raw_route_landing_sha256,
            "alias_route_id": self.alias_route_id,
            "alias_staging_key": self.alias_staging_key,
            "target_raw_route_landing_sha256": self.target_raw_route_landing_sha256,
            "target_route_id": self.target_route_id,
            "target_staging_key": self.target_staging_key,
            "target_route_landing_receipt_sha256": (self.target_route_landing_receipt_sha256),
            "target_field_authority_sha256": self.target_field_authority_sha256,
            "field_origin": self.field_origin,
            "logical_type_sha256": self.logical_type_sha256,
        }

    @classmethod
    def build(
        cls,
        *,
        alias_landing: ObservationRouteLandingV2,
        target_landing: ObservationRouteLandingV2,
        target_receipt: RouteFieldLandingReceiptV2,
        target_field: LandingFieldAuthorityV2,
    ) -> Self:
        if type(alias_landing) is not ObservationRouteLandingV2:
            _fail("canonical-alias field builder received a foreign alias landing")
        if type(target_landing) is not ObservationRouteLandingV2:
            _fail("canonical-alias field builder received a foreign target landing")
        if type(target_receipt) is not RouteFieldLandingReceiptV2:
            _fail("canonical-alias field builder received a foreign target receipt")
        if type(target_field) is not LandingFieldAuthorityV2:
            _fail("canonical-alias field builder received a foreign target field")
        payload = {
            "schema_version": cls.schema_version,
            "kind": cls.kind,
            "field_ordinal": target_field.storage_ordinal,
            "field_name": target_field.storage_column,
            "alias_raw_route_landing_sha256": alias_landing.landing_sha256,
            "alias_route_id": alias_landing.route_id,
            "alias_staging_key": alias_landing.staging_key,
            "target_raw_route_landing_sha256": target_landing.landing_sha256,
            "target_route_id": target_landing.route_id,
            "target_staging_key": target_landing.staging_key,
            "target_route_landing_receipt_sha256": target_receipt.landing_receipt_sha256,
            "target_field_authority_sha256": target_field.authority_sha256,
            "field_origin": target_field.origin,
            "logical_type_sha256": target_field.logical_type_sha256,
        }
        return cls(
            field_sha256=_canonical_sha256(
                payload,
                maximum_bytes=_MAX_FIELD_CANONICAL_BYTES,
                label="canonical-alias field identity",
            ),
            field_ordinal=target_field.storage_ordinal,
            field_name=target_field.storage_column,
            alias_raw_route_landing_sha256=alias_landing.landing_sha256,
            alias_route_id=alias_landing.route_id,
            alias_staging_key=alias_landing.staging_key,
            target_raw_route_landing_sha256=target_landing.landing_sha256,
            target_route_id=target_landing.route_id,
            target_staging_key=target_landing.staging_key,
            target_route_landing_receipt_sha256=target_receipt.landing_receipt_sha256,
            target_field_authority_sha256=target_field.authority_sha256,
            field_origin=target_field.origin,
            logical_type_sha256=target_field.logical_type_sha256,
        )

    def to_row(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "field_sha256": self.field_sha256,
            "field_ordinal": self.field_ordinal,
            "field_name": self.field_name,
            "alias_raw_route_landing_sha256": self.alias_raw_route_landing_sha256,
            "alias_route_id": self.alias_route_id,
            "alias_staging_key": self.alias_staging_key,
            "target_raw_route_landing_sha256": self.target_raw_route_landing_sha256,
            "target_route_id": self.target_route_id,
            "target_staging_key": self.target_staging_key,
            "target_route_landing_receipt_sha256": (self.target_route_landing_receipt_sha256),
            "target_field_authority_sha256": self.target_field_authority_sha256,
            "field_origin": self.field_origin,
            "logical_type_sha256": self.logical_type_sha256,
        }

    @classmethod
    def from_row(cls, value: object) -> Self:
        row = _strict_row(
            value,
            columns=ROUTE_FIELD_CANONICAL_ALIAS_FIELD_COLUMNS,
            label="canonical-alias field row",
        )
        if row["schema_version"] != cls.schema_version or type(row["schema_version"]) is not int:
            _fail("canonical-alias field row has a foreign schema version")
        try:
            return cls(
                field_sha256=cast("str", row["field_sha256"]),
                field_ordinal=cast("int", row["field_ordinal"]),
                field_name=cast("str", row["field_name"]),
                alias_raw_route_landing_sha256=cast("str", row["alias_raw_route_landing_sha256"]),
                alias_route_id=cast("str", row["alias_route_id"]),
                alias_staging_key=cast("str", row["alias_staging_key"]),
                target_raw_route_landing_sha256=cast("str", row["target_raw_route_landing_sha256"]),
                target_route_id=cast("str", row["target_route_id"]),
                target_staging_key=cast("str", row["target_staging_key"]),
                target_route_landing_receipt_sha256=cast(
                    "str", row["target_route_landing_receipt_sha256"]
                ),
                target_field_authority_sha256=cast("str", row["target_field_authority_sha256"]),
                field_origin=cast("str", row["field_origin"]),
                logical_type_sha256=cast("str", row["logical_type_sha256"]),
            )
        except RouteFieldCanonicalAliasError:
            raise
        except (TypeError, ValueError) as exc:
            raise RouteFieldCanonicalAliasError(
                "canonical-alias field row failed exact reconstruction"
            ) from exc

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(
            self.to_row(),
            maximum_bytes=_MAX_FIELD_CANONICAL_BYTES,
            label="canonical-alias field row",
        )

    @classmethod
    def from_canonical_bytes(cls, encoded: object) -> Self:
        decoded = _decode_canonical_json(
            encoded,
            maximum_bytes=_MAX_FIELD_CANONICAL_BYTES,
            label="canonical-alias field row",
        )
        if type(decoded) is not dict:
            _fail("canonical-alias field bytes do not contain one exact row")
        mapping = cast("dict[object, object]", decoded)
        if any(type(key) is not str for key in mapping) or set(mapping) != set(
            ROUTE_FIELD_CANONICAL_ALIAS_FIELD_COLUMNS
        ):
            _fail("canonical-alias field bytes contain foreign columns")
        return cls.from_row(
            {column: mapping[column] for column in ROUTE_FIELD_CANONICAL_ALIAS_FIELD_COLUMNS}
        )


def _validate_target_field(
    field: LandingFieldAuthorityV2,
    *,
    ordinal: int,
    target_receipt: RouteFieldLandingReceiptV2,
) -> None:
    if type(field) is not LandingFieldAuthorityV2:
        _fail("canonical target receipt contains a foreign field authority")
    if (
        field.storage_ordinal != ordinal
        or field.route_id != target_receipt.route_id
        or field.staging_key != target_receipt.staging_key
    ):
        _fail("canonical target field inventory is reordered or relabeled")
    if field.authority_sha256 != _canonical_sha256(
        field.identity_payload(),
        maximum_bytes=_MAX_FIELDS_JSON_BYTES,
        label="canonical target field authority",
    ):
        _fail("canonical target field authority was independently resealed")


def _replay_raw_landing(landing: ObservationRouteLandingV2, *, label: str) -> None:
    try:
        replayed = ObservationRouteLandingV2.model_validate(
            landing.model_dump(mode="python", round_trip=True),
            strict=True,
        )
    except (TypeError, ValueError) as exc:
        raise RouteFieldCanonicalAliasError(f"{label} fails exact Raw V2 replay") from exc
    if type(replayed) is not ObservationRouteLandingV2 or replayed != landing:
        _fail(f"{label} differs from exact Raw V2 replay")


def _resolve_authorities(
    *,
    raw_authority_bundle_sha256: object,
    alias_landing: object,
    target_landings: object,
    target_route_receipts: object,
) -> tuple[ObservationRouteLandingV2, RouteFieldLandingReceiptV2]:
    bundle_sha256 = _sha256(
        raw_authority_bundle_sha256,
        label="canonical-alias raw authority bundle",
    )
    if type(alias_landing) is not ObservationRouteLandingV2:
        _fail("canonical-alias resolver received a foreign alias landing")
    if type(target_landings) is not tuple:
        _fail("canonical-alias target landings must be one exact tuple")
    if type(target_route_receipts) is not tuple:
        _fail("canonical-alias target receipts must be one exact tuple")
    landing_candidates = target_landings
    receipt_candidates = target_route_receipts
    if (
        len(landing_candidates) > MAX_ROUTE_FIELD_CANONICAL_ALIAS_CANDIDATES
        or len(receipt_candidates) > MAX_ROUTE_FIELD_CANONICAL_ALIAS_CANDIDATES
    ):
        _fail("canonical-alias candidate inventory exceeds its bound")
    if any(type(item) is not ObservationRouteLandingV2 for item in landing_candidates):
        _fail("canonical-alias target landing inventory contains a foreign DTO")
    if any(type(item) is not RouteFieldLandingReceiptV2 for item in receipt_candidates):
        _fail("canonical-alias target receipt inventory contains a foreign DTO")

    alias = alias_landing
    _replay_raw_landing(alias, label="canonical-alias raw landing")
    if (
        alias.landing_semantic != "response_canonical_alias"
        or type(alias.conditional_lossless) is not bool
        or alias.conditional_lossless
        or type(alias.alias_target_route_id) is not str
        or alias.alias_target_route_id == alias.route_id
    ):
        _fail("canonical-alias landing lacks exact alias semantics")

    same_route = tuple(
        cast("ObservationRouteLandingV2", item)
        for item in landing_candidates
        if cast("ObservationRouteLandingV2", item).route_id == alias.alias_target_route_id
    )
    same_observation = tuple(
        item for item in same_route if item.observation_sha256 == alias.observation_sha256
    )
    if not same_observation and same_route:
        _fail("canonical alias and target span different observations")
    if len(same_observation) != 1:
        _fail("canonical alias target landing is absent or ambiguous")
    target = same_observation[0]
    _replay_raw_landing(target, label="canonical target raw landing")
    if (
        target.landing_semantic != "conditional_lossless"
        or type(target.conditional_lossless) is not bool
        or not target.conditional_lossless
        or target.alias_target_route_id is not None
        or target.route_id == alias.route_id
    ):
        _fail("canonical alias target is not the exact conditional landing")

    if (
        alias.content_hash != target.content_hash
        or alias.persisted_row_count != target.persisted_row_count
        or alias.persisted_content_sha256 != target.persisted_content_sha256
        or alias.persisted_schema_sha256 != target.persisted_schema_sha256
    ):
        _fail("canonical alias and target differ in persisted content, schema, or row count")

    matches = tuple(
        cast("RouteFieldLandingReceiptV2", item)
        for item in receipt_candidates
        if cast("RouteFieldLandingReceiptV2", item).raw_bundle_sha256 == bundle_sha256
        and cast("RouteFieldLandingReceiptV2", item).route_id == target.route_id
        and cast("RouteFieldLandingReceiptV2", item).staging_key == target.staging_key
        and cast("RouteFieldLandingReceiptV2", item).receipt_root_sha256
        == target.receipt_root_sha256
        and cast("RouteFieldLandingReceiptV2", item).row_count == target.persisted_row_count
    )
    if len(matches) != 1:
        _fail("canonical alias target route receipt is absent or ambiguous")
    target_receipt = matches[0]
    if (
        type(target_receipt.source_shape) is not str
        or target_receipt.source_shape not in _TARGET_SOURCE_SHAPES
    ):
        _fail("canonical alias target receipt has an incompatible source shape")
    if target_receipt.landing_receipt_sha256 != _canonical_sha256(
        target_receipt.identity_payload(),
        maximum_bytes=_MAX_RECEIPT_CANONICAL_BYTES,
        label="canonical target route receipt identity",
    ):
        _fail("canonical target route receipt identity is invalid")
    if (
        type(target_receipt.field_authorities) is not tuple
        or type(target_receipt.field_count) is not int
        or target_receipt.field_count < 0
        or target_receipt.field_count > MAX_ROUTE_FIELDS
        or len(target_receipt.field_authorities) != target_receipt.field_count
    ):
        _fail("canonical target route field denominator is invalid")
    for ordinal, field in enumerate(target_receipt.field_authorities):
        _validate_target_field(field, ordinal=ordinal, target_receipt=target_receipt)
    expected_target_fields_sha256 = _canonical_sha256(
        [field.to_dict() for field in target_receipt.field_authorities],
        maximum_bytes=MAX_ROUTE_CANONICAL_BYTES,
        label="canonical target route fields",
    )
    if target_receipt.fields_sha256 != expected_target_fields_sha256:
        _fail("canonical target route field root is invalid")
    return target, target_receipt


@dataclass(frozen=True, slots=True)
class RouteFieldCanonicalAliasReceiptV1:
    """One exact, value-free alias-to-canonical route landing proof."""

    receipt_sha256: str
    raw_authority_bundle_sha256: str
    alias_raw_route_landing_sha256: str
    alias_observation_sha256: str
    alias_route_ordinal: int
    alias_route_id: str
    alias_staging_key: str
    alias_receipt_root_sha256: str
    alias_content_hash: str
    alias_persisted_row_count: int
    alias_persisted_content_sha256: str
    alias_persisted_schema_sha256: str
    target_raw_route_landing_sha256: str
    target_observation_sha256: str
    target_route_ordinal: int
    target_route_id: str
    target_staging_key: str
    target_receipt_root_sha256: str
    target_route_landing_receipt_sha256: str
    target_source_shape: str
    target_content_hash: str
    target_persisted_row_count: int
    target_persisted_content_sha256: str
    target_persisted_schema_sha256: str
    target_fields_sha256: str
    field_count: int
    field_root_sha256: str
    fields: tuple[RouteFieldCanonicalAliasFieldV1, ...]

    schema_version: ClassVar[int] = ROUTE_FIELD_CANONICAL_ALIAS_SCHEMA_VERSION
    kind: ClassVar[str] = _RECEIPT_KIND

    def __post_init__(self) -> None:
        for label, value in (
            ("canonical-alias receipt identity", self.receipt_sha256),
            ("canonical-alias raw authority bundle", self.raw_authority_bundle_sha256),
            ("alias raw route landing", self.alias_raw_route_landing_sha256),
            ("alias observation", self.alias_observation_sha256),
            ("alias receipt root", self.alias_receipt_root_sha256),
            ("alias content hash", self.alias_content_hash),
            ("alias persisted content", self.alias_persisted_content_sha256),
            ("alias persisted schema", self.alias_persisted_schema_sha256),
            ("target raw route landing", self.target_raw_route_landing_sha256),
            ("target observation", self.target_observation_sha256),
            ("target receipt root", self.target_receipt_root_sha256),
            ("target route landing receipt", self.target_route_landing_receipt_sha256),
            ("target content hash", self.target_content_hash),
            ("target persisted content", self.target_persisted_content_sha256),
            ("target persisted schema", self.target_persisted_schema_sha256),
            ("target fields", self.target_fields_sha256),
            ("canonical-alias field root", self.field_root_sha256),
        ):
            _sha256(value, label=label)
        _bounded_integer(
            self.alias_route_ordinal,
            label="canonical-alias route ordinal",
            maximum=MAX_ROUTE_ROWS - 1,
        )
        _bounded_integer(
            self.target_route_ordinal,
            label="canonical target route ordinal",
            maximum=MAX_ROUTE_ROWS - 1,
        )
        _bounded_integer(
            self.alias_persisted_row_count,
            label="canonical-alias persisted row count",
            maximum=MAX_ROUTE_ROWS,
        )
        _bounded_integer(
            self.target_persisted_row_count,
            label="canonical target persisted row count",
            maximum=MAX_ROUTE_ROWS,
        )
        _bounded_integer(
            self.field_count,
            label="canonical-alias field count",
            maximum=MAX_ROUTE_FIELDS,
        )
        _safe_id(self.alias_route_id, label="canonical-alias route ID")
        _safe_id(self.alias_staging_key, label="canonical-alias staging key")
        _safe_id(self.target_route_id, label="canonical target route ID")
        _safe_id(self.target_staging_key, label="canonical target staging key")
        if type(self.target_source_shape) is not str or self.target_source_shape not in (
            _TARGET_SOURCE_SHAPES
        ):
            _fail("canonical alias target source shape is outside the closed domain")
        if (
            self.alias_observation_sha256 != self.target_observation_sha256
            or self.alias_route_id == self.target_route_id
        ):
            _fail("canonical alias relabels a route or crosses observations")
        if (
            self.alias_content_hash != self.target_content_hash
            or self.alias_persisted_row_count != self.target_persisted_row_count
            or self.alias_persisted_content_sha256 != self.target_persisted_content_sha256
            or self.alias_persisted_schema_sha256 != self.target_persisted_schema_sha256
        ):
            _fail("canonical alias differs from its target frame proof")
        if type(self.fields) is not tuple or len(self.fields) != self.field_count:
            _fail("canonical-alias field denominator differs from its exact tuple")

        seen_fields: set[str] = set()
        seen_target_fields: set[str] = set()
        for ordinal, field in enumerate(self.fields):
            if type(field) is not RouteFieldCanonicalAliasFieldV1:
                _fail("canonical-alias field inventory contains a foreign DTO")
            if RouteFieldCanonicalAliasFieldV1.from_row(field.to_row()) != field:
                _fail("canonical-alias field fails exact row replay")
            if (
                field.field_ordinal != ordinal
                or field.alias_raw_route_landing_sha256 != self.alias_raw_route_landing_sha256
                or field.alias_route_id != self.alias_route_id
                or field.alias_staging_key != self.alias_staging_key
                or field.target_raw_route_landing_sha256 != self.target_raw_route_landing_sha256
                or field.target_route_id != self.target_route_id
                or field.target_staging_key != self.target_staging_key
                or field.target_route_landing_receipt_sha256
                != self.target_route_landing_receipt_sha256
            ):
                _fail("canonical-alias field inventory is reordered, foreign, or relabeled")
            if field.field_sha256 in seen_fields:
                _fail("canonical-alias field inventory contains a duplicate alias field")
            if field.target_field_authority_sha256 in seen_target_fields:
                _fail("canonical-alias field inventory duplicates a target field")
            seen_fields.add(field.field_sha256)
            seen_target_fields.add(field.target_field_authority_sha256)
        if self.field_root_sha256 != _field_root(self.fields):
            _fail("canonical-alias field root differs from its ordered inventory")
        if self.receipt_sha256 != _canonical_sha256(
            self.identity_payload(),
            maximum_bytes=_MAX_RECEIPT_CANONICAL_BYTES,
            label="canonical-alias receipt identity",
        ):
            _fail("canonical-alias receipt digest differs from its exact identity")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "raw_authority_bundle_sha256": self.raw_authority_bundle_sha256,
            "alias_raw_route_landing_sha256": self.alias_raw_route_landing_sha256,
            "alias_observation_sha256": self.alias_observation_sha256,
            "alias_route_ordinal": self.alias_route_ordinal,
            "alias_route_id": self.alias_route_id,
            "alias_staging_key": self.alias_staging_key,
            "alias_receipt_root_sha256": self.alias_receipt_root_sha256,
            "alias_content_hash": self.alias_content_hash,
            "alias_persisted_row_count": self.alias_persisted_row_count,
            "alias_persisted_content_sha256": self.alias_persisted_content_sha256,
            "alias_persisted_schema_sha256": self.alias_persisted_schema_sha256,
            "target_raw_route_landing_sha256": self.target_raw_route_landing_sha256,
            "target_observation_sha256": self.target_observation_sha256,
            "target_route_ordinal": self.target_route_ordinal,
            "target_route_id": self.target_route_id,
            "target_staging_key": self.target_staging_key,
            "target_receipt_root_sha256": self.target_receipt_root_sha256,
            "target_route_landing_receipt_sha256": (self.target_route_landing_receipt_sha256),
            "target_source_shape": self.target_source_shape,
            "target_content_hash": self.target_content_hash,
            "target_persisted_row_count": self.target_persisted_row_count,
            "target_persisted_content_sha256": self.target_persisted_content_sha256,
            "target_persisted_schema_sha256": self.target_persisted_schema_sha256,
            "target_fields_sha256": self.target_fields_sha256,
            "field_count": self.field_count,
            "field_root_sha256": self.field_root_sha256,
        }

    @classmethod
    def build(
        cls,
        *,
        raw_authority_bundle_sha256: str,
        alias_landing: ObservationRouteLandingV2,
        target_landings: tuple[ObservationRouteLandingV2, ...],
        target_route_receipts: tuple[RouteFieldLandingReceiptV2, ...],
    ) -> Self:
        target, target_receipt = _resolve_authorities(
            raw_authority_bundle_sha256=raw_authority_bundle_sha256,
            alias_landing=alias_landing,
            target_landings=target_landings,
            target_route_receipts=target_route_receipts,
        )
        fields = tuple(
            RouteFieldCanonicalAliasFieldV1.build(
                alias_landing=alias_landing,
                target_landing=target,
                target_receipt=target_receipt,
                target_field=field,
            )
            for field in target_receipt.field_authorities
        )
        root = _field_root(fields)
        identity = {
            "schema_version": cls.schema_version,
            "kind": cls.kind,
            "raw_authority_bundle_sha256": raw_authority_bundle_sha256,
            "alias_raw_route_landing_sha256": alias_landing.landing_sha256,
            "alias_observation_sha256": alias_landing.observation_sha256,
            "alias_route_ordinal": alias_landing.route_ordinal,
            "alias_route_id": alias_landing.route_id,
            "alias_staging_key": alias_landing.staging_key,
            "alias_receipt_root_sha256": alias_landing.receipt_root_sha256,
            "alias_content_hash": alias_landing.content_hash,
            "alias_persisted_row_count": alias_landing.persisted_row_count,
            "alias_persisted_content_sha256": alias_landing.persisted_content_sha256,
            "alias_persisted_schema_sha256": alias_landing.persisted_schema_sha256,
            "target_raw_route_landing_sha256": target.landing_sha256,
            "target_observation_sha256": target.observation_sha256,
            "target_route_ordinal": target.route_ordinal,
            "target_route_id": target.route_id,
            "target_staging_key": target.staging_key,
            "target_receipt_root_sha256": target.receipt_root_sha256,
            "target_route_landing_receipt_sha256": target_receipt.landing_receipt_sha256,
            "target_source_shape": target_receipt.source_shape,
            "target_content_hash": target.content_hash,
            "target_persisted_row_count": target.persisted_row_count,
            "target_persisted_content_sha256": target.persisted_content_sha256,
            "target_persisted_schema_sha256": target.persisted_schema_sha256,
            "target_fields_sha256": target_receipt.fields_sha256,
            "field_count": len(fields),
            "field_root_sha256": root,
        }
        return cls(
            receipt_sha256=_canonical_sha256(
                identity,
                maximum_bytes=_MAX_RECEIPT_CANONICAL_BYTES,
                label="canonical-alias receipt identity",
            ),
            raw_authority_bundle_sha256=raw_authority_bundle_sha256,
            alias_raw_route_landing_sha256=alias_landing.landing_sha256,
            alias_observation_sha256=alias_landing.observation_sha256,
            alias_route_ordinal=alias_landing.route_ordinal,
            alias_route_id=alias_landing.route_id,
            alias_staging_key=alias_landing.staging_key,
            alias_receipt_root_sha256=alias_landing.receipt_root_sha256,
            alias_content_hash=alias_landing.content_hash,
            alias_persisted_row_count=alias_landing.persisted_row_count,
            alias_persisted_content_sha256=alias_landing.persisted_content_sha256,
            alias_persisted_schema_sha256=alias_landing.persisted_schema_sha256,
            target_raw_route_landing_sha256=target.landing_sha256,
            target_observation_sha256=target.observation_sha256,
            target_route_ordinal=target.route_ordinal,
            target_route_id=target.route_id,
            target_staging_key=target.staging_key,
            target_receipt_root_sha256=target.receipt_root_sha256,
            target_route_landing_receipt_sha256=target_receipt.landing_receipt_sha256,
            target_source_shape=target_receipt.source_shape,
            target_content_hash=target.content_hash,
            target_persisted_row_count=target.persisted_row_count,
            target_persisted_content_sha256=target.persisted_content_sha256,
            target_persisted_schema_sha256=target.persisted_schema_sha256,
            target_fields_sha256=target_receipt.fields_sha256,
            field_count=len(fields),
            field_root_sha256=root,
            fields=fields,
        )

    def validate_against(
        self,
        *,
        alias_landing: ObservationRouteLandingV2,
        target_landings: tuple[ObservationRouteLandingV2, ...],
        target_route_receipts: tuple[RouteFieldLandingReceiptV2, ...],
    ) -> Self:
        if type(self) is not RouteFieldCanonicalAliasReceiptV1:
            _fail("canonical-alias validation requires the exact V1 receipt type")
        expected = RouteFieldCanonicalAliasReceiptV1.build(
            raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
            alias_landing=alias_landing,
            target_landings=target_landings,
            target_route_receipts=target_route_receipts,
        )
        if self != expected:
            _fail("canonical-alias receipt differs from independent authority replay")
        return self

    def to_row(self) -> dict[str, object]:
        fields_json = _canonical_json_bytes(
            [field.to_row() for field in self.fields],
            maximum_bytes=_MAX_FIELDS_JSON_BYTES,
            label="canonical-alias field inventory",
        ).decode("utf-8")
        return {
            "schema_version": self.schema_version,
            "receipt_sha256": self.receipt_sha256,
            "raw_authority_bundle_sha256": self.raw_authority_bundle_sha256,
            "alias_raw_route_landing_sha256": self.alias_raw_route_landing_sha256,
            "alias_observation_sha256": self.alias_observation_sha256,
            "alias_route_ordinal": self.alias_route_ordinal,
            "alias_route_id": self.alias_route_id,
            "alias_staging_key": self.alias_staging_key,
            "alias_receipt_root_sha256": self.alias_receipt_root_sha256,
            "alias_content_hash": self.alias_content_hash,
            "alias_persisted_row_count": self.alias_persisted_row_count,
            "alias_persisted_content_sha256": self.alias_persisted_content_sha256,
            "alias_persisted_schema_sha256": self.alias_persisted_schema_sha256,
            "target_raw_route_landing_sha256": self.target_raw_route_landing_sha256,
            "target_observation_sha256": self.target_observation_sha256,
            "target_route_ordinal": self.target_route_ordinal,
            "target_route_id": self.target_route_id,
            "target_staging_key": self.target_staging_key,
            "target_receipt_root_sha256": self.target_receipt_root_sha256,
            "target_route_landing_receipt_sha256": (self.target_route_landing_receipt_sha256),
            "target_source_shape": self.target_source_shape,
            "target_content_hash": self.target_content_hash,
            "target_persisted_row_count": self.target_persisted_row_count,
            "target_persisted_content_sha256": self.target_persisted_content_sha256,
            "target_persisted_schema_sha256": self.target_persisted_schema_sha256,
            "target_fields_sha256": self.target_fields_sha256,
            "field_count": self.field_count,
            "field_root_sha256": self.field_root_sha256,
            "fields_json": fields_json,
        }

    @classmethod
    def from_row(cls, value: object) -> Self:
        row = _strict_row(
            value,
            columns=ROUTE_FIELD_CANONICAL_ALIAS_RECEIPT_COLUMNS,
            label="canonical-alias receipt row",
        )
        if row["schema_version"] != cls.schema_version or type(row["schema_version"]) is not int:
            _fail("canonical-alias receipt row has a foreign schema version")
        fields_json = row["fields_json"]
        if type(fields_json) is not str:
            _fail("canonical-alias field inventory is not exact JSON text")
        try:
            encoded_fields = fields_json.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            _fail("canonical-alias field inventory contains invalid Unicode")
        decoded_fields = _decode_canonical_json(
            encoded_fields,
            maximum_bytes=_MAX_FIELDS_JSON_BYTES,
            label="canonical-alias field inventory",
        )
        if type(decoded_fields) is not list or len(decoded_fields) > MAX_ROUTE_FIELDS:
            _fail("canonical-alias field inventory is not one bounded exact list")
        fields_list: list[RouteFieldCanonicalAliasFieldV1] = []
        for item in cast("list[object]", decoded_fields):
            if type(item) is not dict:
                _fail("canonical-alias field inventory contains a non-row member")
            mapping = cast("dict[object, object]", item)
            if any(type(key) is not str for key in mapping) or set(mapping) != set(
                ROUTE_FIELD_CANONICAL_ALIAS_FIELD_COLUMNS
            ):
                _fail("canonical-alias field inventory contains a noncanonical row")
            ordered = {
                column: mapping[column] for column in ROUTE_FIELD_CANONICAL_ALIAS_FIELD_COLUMNS
            }
            fields_list.append(RouteFieldCanonicalAliasFieldV1.from_row(ordered))
        fields = tuple(fields_list)
        try:
            return cls(
                receipt_sha256=cast("str", row["receipt_sha256"]),
                raw_authority_bundle_sha256=cast("str", row["raw_authority_bundle_sha256"]),
                alias_raw_route_landing_sha256=cast("str", row["alias_raw_route_landing_sha256"]),
                alias_observation_sha256=cast("str", row["alias_observation_sha256"]),
                alias_route_ordinal=cast("int", row["alias_route_ordinal"]),
                alias_route_id=cast("str", row["alias_route_id"]),
                alias_staging_key=cast("str", row["alias_staging_key"]),
                alias_receipt_root_sha256=cast("str", row["alias_receipt_root_sha256"]),
                alias_content_hash=cast("str", row["alias_content_hash"]),
                alias_persisted_row_count=cast("int", row["alias_persisted_row_count"]),
                alias_persisted_content_sha256=cast("str", row["alias_persisted_content_sha256"]),
                alias_persisted_schema_sha256=cast("str", row["alias_persisted_schema_sha256"]),
                target_raw_route_landing_sha256=cast("str", row["target_raw_route_landing_sha256"]),
                target_observation_sha256=cast("str", row["target_observation_sha256"]),
                target_route_ordinal=cast("int", row["target_route_ordinal"]),
                target_route_id=cast("str", row["target_route_id"]),
                target_staging_key=cast("str", row["target_staging_key"]),
                target_receipt_root_sha256=cast("str", row["target_receipt_root_sha256"]),
                target_route_landing_receipt_sha256=cast(
                    "str", row["target_route_landing_receipt_sha256"]
                ),
                target_source_shape=cast("str", row["target_source_shape"]),
                target_content_hash=cast("str", row["target_content_hash"]),
                target_persisted_row_count=cast("int", row["target_persisted_row_count"]),
                target_persisted_content_sha256=cast("str", row["target_persisted_content_sha256"]),
                target_persisted_schema_sha256=cast("str", row["target_persisted_schema_sha256"]),
                target_fields_sha256=cast("str", row["target_fields_sha256"]),
                field_count=cast("int", row["field_count"]),
                field_root_sha256=cast("str", row["field_root_sha256"]),
                fields=fields,
            )
        except RouteFieldCanonicalAliasError:
            raise
        except (TypeError, ValueError) as exc:
            raise RouteFieldCanonicalAliasError(
                "canonical-alias receipt row failed exact reconstruction"
            ) from exc

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(
            self.to_row(),
            maximum_bytes=_MAX_RECEIPT_CANONICAL_BYTES,
            label="canonical-alias receipt row",
        )

    @classmethod
    def from_canonical_bytes(cls, encoded: object) -> Self:
        decoded = _decode_canonical_json(
            encoded,
            maximum_bytes=_MAX_RECEIPT_CANONICAL_BYTES,
            label="canonical-alias receipt row",
        )
        if type(decoded) is not dict:
            _fail("canonical-alias receipt bytes do not contain one exact row")
        mapping = cast("dict[object, object]", decoded)
        if any(type(key) is not str for key in mapping) or set(mapping) != set(
            ROUTE_FIELD_CANONICAL_ALIAS_RECEIPT_COLUMNS
        ):
            _fail("canonical-alias receipt bytes contain foreign columns")
        return cls.from_row(
            {column: mapping[column] for column in ROUTE_FIELD_CANONICAL_ALIAS_RECEIPT_COLUMNS}
        )
