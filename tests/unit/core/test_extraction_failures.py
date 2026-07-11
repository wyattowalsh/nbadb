from __future__ import annotations

import json

from nbadb.core.errors import ExtractionError, TransientError
from nbadb.core.extraction_failures import (
    classify_error_name,
    classify_exception,
    describe_exception,
    exception_chain,
    http_status_code,
    root_error_type,
)


class _Response:
    status_code = 503


class _HttpError(Exception):
    response = _Response()


def _wrapped(outer: type[Exception], inner: Exception) -> Exception:
    try:
        raise inner
    except Exception as exc:
        try:
            raise outer("redacted wrapper") from exc
        except Exception as wrapped:
            return wrapped


def test_exception_chain_and_root_type_follow_explicit_causes() -> None:
    exc = _wrapped(TransientError, KeyError("secret-field"))

    assert [type(item).__name__ for item in exception_chain(exc)] == [
        "TransientError",
        "KeyError",
    ]
    assert root_error_type(exc) == "KeyError"
    assert classify_exception(exc) == "response_contract"


def test_transport_wrapper_uses_root_transport_type() -> None:
    exc = _wrapped(ExtractionError, TimeoutError("secret-url"))

    assert classify_exception(exc) == "transport_transient"
    assert describe_exception(exc) == {
        "failure_class": "transport_transient",
        "root_error_type": "TimeoutError",
        "error_chain": ["ExtractionError", "TimeoutError"],
        "http_status": None,
    }


def test_http_429_and_5xx_are_transport_failures() -> None:
    assert classify_error_name("HTTPError", status_code=429) == "transport_transient"
    assert classify_exception(_HttpError("do not persist")) == "transport_transient"
    assert http_status_code(_HttpError()) == 503


def test_response_contract_names_cover_parser_arrow_and_result_shapes() -> None:
    for name in (
        "JSONDecodeError",
        "KeyError",
        "ArrowTypeError",
        "MissingRequiredResultSet:stg_box_score:4",
        "task_exception:UnexpectedNonListResult",
    ):
        assert classify_error_name(name) == "response_contract"


def test_unknown_and_non_retryable_http_errors_are_application_failures() -> None:
    assert classify_error_name("ValueError") == "application"
    assert classify_error_name("HTTPError", status_code=401) == "application"


def test_description_never_serializes_exception_messages() -> None:
    secret = "kaggle-key=super-secret"
    payload = describe_exception(ValueError(secret))

    assert secret not in json.dumps(payload)
