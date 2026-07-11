"""Error taxonomy and exception hierarchy for nbadb.

Provides a structured error classification system enabling:
- Precise error categorization (config, transient, validation, extraction, transform)
- User-friendly error messages with context
- Retry logic for transient failures
- Clear error handling strategies at each layer

Error hierarchy:
    NbaDbError (base)
    ├── ConfigError (configuration or initialization problems)
    ├── TransientError (may be retryable: API timeouts, rate limits, network)
    └── IrrecoverableError (unrecoverable: data, schema, file issues)
        ├── ExtractionError (nba_api or endpoint-specific)
        ├── TransformError (SQL, schema composition, or computation)
        └── ValidationError (schema validation or data contract violation)
"""

from __future__ import annotations


class NbaDbError(Exception):
    """Base exception for all nbadb errors.

    All exceptions raised by nbadb inherit from this class, allowing
    users to catch and handle all library errors uniformly.
    """

    pass


class ConfigError(NbaDbError):
    """Configuration or initialization error.

    Raised when:
    - Database path is invalid or inaccessible
    - Required environment variables are missing
    - Settings validation fails
    - API credentials are missing or invalid
    """

    pass


class TransientError(NbaDbError):
    """Transient error that may be retryable.

    Raised for temporary failures such as:
    - API timeouts (ReadTimeout, ConnectTimeout)
    - Rate limiting (HTTP 429)
    - Temporary network issues (ConnectionError, RemoteDisconnected)

    Users can implement retry logic for these errors.
    """

    pass


class IrrecoverableError(NbaDbError):
    """Unrecoverable error that should not be retried.

    Raised when:
    - Data integrity problems are detected
    - Schema contracts are violated
    - Required files are missing
    - Operations cannot proceed due to data state

    Base class for domain-specific unrecoverable errors.
    """

    pass


class ExtractionError(IrrecoverableError):
    """Extraction-specific error.

    Raised during nba_api calls or data extraction when:
    - An endpoint returns invalid or unparseable data
    - Data shape/schema does not match expectations
    - Extraction strategy or parameters are invalid
    - Upstream API contract is violated (e.g., missing required columns)
    """

    pass


class TransformError(IrrecoverableError):
    """Transform-specific error.

    Raised during SQL execution or DataFrame transformation when:
    - SQL query fails or returns unexpected shape
    - Table join keys do not match upstream schemas
    - Transformer dependencies are unsatisfied
    - Column mutations violate downstream contracts
    - Data type coercion fails irrecoverably
    """

    pass


class ValidationError(IrrecoverableError):
    """Schema or data validation error.

    Raised when:
    - Pandera schema validation fails (missing required columns, type errors)
    - Data contract is violated (null constraints, range checks)
    - Staging or output table structure does not match expected schema
    """

    pass
