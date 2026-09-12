from __future__ import annotations

from typing import Any, Literal

from nbadb.core.errors import ParserInputCaptureIntegrityError

type ExtractionFailureClass = Literal[
    "transport_transient",
    "response_contract",
    "application",
    "vpn_egress",
    "runner_infrastructure",
    "timeout_progress",
    "timeout_stalled",
    "contract_blocked",
]

TRANSPORT_ERROR_NAMES = frozenset(
    {
        "ChunkedEncodingError",
        "ConnectError",
        "ConnectTimeout",
        "ConnectionError",
        "ConnectionResetError",
        "NetworkError",
        "NameResolutionError",
        "NewConnectionError",
        "MaxRetryError",
        "ProtocolError",
        "ProxyError",
        "ReadError",
        "ReadTimeout",
        "RemoteDisconnected",
        "SSLError",
        "Timeout",
        "TimeoutError",
        "TransientError",
        "gaierror",
    }
)
RESPONSE_CONTRACT_ERROR_NAMES = frozenset(
    {
        "ArrowInvalid",
        "ArrowTypeError",
        "JSONDecodeError",
        "KeyError",
        "MissingRequiredResultSet",
        "ResponseContractError",
        "UnexpectedElementType",
        "UnexpectedListResult",
        "UnexpectedNonListResult",
        "UnexpectedResultShape",
    }
)
SAFE_ROOT_ERROR_NAMES = frozenset(
    set(TRANSPORT_ERROR_NAMES)
    | set(RESPONSE_CONTRACT_ERROR_NAMES)
    | {
        "AttributeError",
        "CancelledError",
        "ExtractionError",
        "HTTPError",
        "IndexError",
        "ParserInputCapacityError",
        "ParserInputCaptureIntegrityError",
        "TypeError",
        "UnicodeDecodeError",
        "UnicodeEncodeError",
        "UnclassifiedError",
        "UpstreamApplicationError",
        "UpstreamHttpError",
        "UpstreamTransientHttpError",
        "ValueError",
        "WebException",
    }
)


def exception_chain(exc: BaseException) -> tuple[BaseException, ...]:
    """Return the explicit exception chain, outermost to root, without cycles."""
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return tuple(chain)


def root_exception(exc: BaseException) -> BaseException:
    chain = exception_chain(exc)
    return chain[-1]


def root_error_type(exc: BaseException) -> str:
    return type(root_exception(exc)).__name__


def safe_root_error_type(exc: BaseException) -> str:
    """Return a fixed, secret-safe root class for durable receipts.

    Operational diagnostics may retain :func:`root_error_type`, but durable
    provider receipts admit only this repository-owned vocabulary. Unknown
    third-party or dynamically named exception classes collapse to a stable
    sentinel rather than leaking an attacker-controlled class name.
    """

    chain = exception_chain(exc)
    for candidate in (chain[-1], chain[0]):
        name = type(candidate).__name__
        if name in SAFE_ROOT_ERROR_NAMES:
            return name
    return "UnclassifiedError"


def safe_error_type(exc: BaseException) -> str:
    """Return a fixed, secret-safe class name for one exception object."""

    name = type(exc).__name__
    return name if name in SAFE_ROOT_ERROR_NAMES else "UnclassifiedError"


def http_status_code(exc: BaseException) -> int | None:
    """Extract an HTTP status from common requests/httpx exception shapes."""
    for candidate in exception_chain(exc):
        response = getattr(candidate, "response", None)
        values = (
            getattr(response, "status_code", None),
            getattr(response, "status", None),
            getattr(candidate, "status_code", None),
        )
        for value in values:
            if value is None:
                continue
            try:
                status = int(value)
            except (TypeError, ValueError):
                continue
            if 100 <= status <= 599:
                return status
    return None


def classify_error_name(
    error_name: str,
    *,
    status_code: int | None = None,
) -> ExtractionFailureClass:
    if status_code == 429 or (status_code is not None and status_code >= 500):
        return "transport_transient"

    normalized = error_name.strip()
    tokens = {normalized, normalized.split(":", 1)[0]}
    if any(name in normalized for name in RESPONSE_CONTRACT_ERROR_NAMES) or (
        tokens & RESPONSE_CONTRACT_ERROR_NAMES
    ):
        return "response_contract"
    if any(name in normalized for name in TRANSPORT_ERROR_NAMES) or (
        tokens & TRANSPORT_ERROR_NAMES
    ):
        return "transport_transient"
    return "application"


def classify_exception(exc: BaseException) -> ExtractionFailureClass:
    if any(isinstance(item, ParserInputCaptureIntegrityError) for item in exception_chain(exc)):
        return "runner_infrastructure"
    status = http_status_code(exc)
    root_name = root_error_type(exc)
    root_class = classify_error_name(root_name, status_code=status)
    if root_class != "application":
        return root_class
    return classify_error_name(type(exc).__name__, status_code=status)


def is_transport_error(exc: BaseException) -> bool:
    return classify_exception(exc) == "transport_transient"


def describe_exception(exc: BaseException) -> dict[str, Any]:
    """Return secret-safe diagnostic fields without exception messages or payloads."""
    chain = exception_chain(exc)
    return {
        "failure_class": classify_exception(exc),
        "root_error_type": safe_root_error_type(exc),
        "error_chain": [safe_error_type(item) for item in chain],
        "http_status": http_status_code(exc),
    }
