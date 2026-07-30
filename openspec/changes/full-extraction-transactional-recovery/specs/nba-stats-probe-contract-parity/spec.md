## ADDED Requirements

### Requirement: The VPN NBA canary matches the pinned runtime HTTP contract

The system SHALL send the TeamYears VPN canary with the exact `STATS_HEADERS`
mapping declared by the repository's pinned `nba_api` runtime.

#### Scenario: Connector and runtime headers match

- **WHEN** deterministic validation compares the connector header sequence with the pinned runtime mapping
- **THEN** every header name and value matches and the connector sends the headers in runtime declaration order

#### Scenario: The pinned runtime changes its headers

- **WHEN** a dependency update changes a `STATS_HEADERS` name or value without updating the connector
- **THEN** deterministic validation fails before a VPN extraction run

### Requirement: The public NBA header export matches the pinned runtime

The system SHALL expose `nbadb.core.NBA_HEADERS` as an independent mapping with
the exact names and values declared by pinned `STATS_HEADERS`.

#### Scenario: A consumer reads the public mapping

- **WHEN** a consumer imports `NBA_HEADERS` from `nbadb.core`
- **THEN** it receives values equal to the pinned runtime contract without sharing the runtime mapping object

### Requirement: The TeamYears canary remains fail-closed and shape-validating

The system MUST accept a VPN tunnel only when the bounded TeamYears request
returns a successful HTTP response with the expected non-empty result-set
shape, after the route, changed-exit-IP, and GitHub control-plane gates pass.

#### Scenario: NBA.com silently times out

- **WHEN** the header-complete TeamYears request reaches its bounded timeout with no valid response
- **THEN** the server is rejected as an NBA reachability failure and extraction does not start

#### Scenario: NBA.com returns malformed success content

- **WHEN** the request returns 2xx content without the required TeamYears headers and at least one width-matching row
- **THEN** the server is rejected as an NBA response-contract failure

#### Scenario: The canary passes

- **WHEN** the header-complete request returns the required non-empty TeamYears shape
- **THEN** the connector proceeds to the installed-stack discovery canaries without weakening any later gate

### Requirement: Installed-stack failures retain a secret-safe root cause

The installed-stack discovery probe MUST preserve its existing status,
endpoint, failure-kind, and outer error-type fields. An exception failure MUST
also report the explicit exception chain's root type as a bounded token without
including exception messages, response content, request parameters, or
credentials. The connector MUST surface a recognized root type in its bounded
diagnostic and log output. When the recognized root identifies a transport or
response-contract class, the connector MUST use it for that classification and
MUST fall back to the validated outer type when the root is absent or invalid.
This optional field MUST NOT change failure-attestation admission or any
preceding connector gate.

#### Scenario: The extraction boundary wraps a transport exception

- **WHEN** an installed-stack canary raises a transport wrapper from a lower-level timeout
- **THEN** the failure attestation retains the wrapper in `error_type`, reports the timeout class in `root_error_type`, and the connector surfaces both types

#### Scenario: Exception messages contain sensitive content

- **WHEN** either the wrapper or root exception message contains request or credential material
- **THEN** the attestation contains only sanitized exception class names and none of the message content

#### Scenario: Root type is absent or malformed

- **WHEN** an otherwise valid child failure omits `root_error_type` or supplies a value outside the bounded error-type allowlist
- **THEN** the connector retains its existing outer-only diagnostic and outer-type classification and does not surface the supplied value

#### Scenario: A transport wrapper contains a response-contract root

- **WHEN** a recognized contract-error root is wrapped by a recognized transport-error outer type
- **THEN** the connector surfaces both types and treats the failure as a fatal response-contract error without rotating or quarantining the server

#### Scenario: A transport wrapper contains a timeout root

- **WHEN** a recognized timeout root is wrapped by a recognized transport-error outer type
- **THEN** the connector surfaces both types and preserves the server-specific transport failure decision

### Requirement: Installed-stack endpoint timeouts match discovery's fast path

The connector MUST give each installed-stack discovery endpoint the same
10-second request timeout as the discovery fast path when sufficient attempt
budget remains. The default child cap MUST cover both sequential endpoint
timeouts plus bounded process overhead. The server attempt, overall connector,
and finalization-reserve deadlines MUST remain independently bounded.

#### Scenario: The connector has its ordinary probe budget

- **WHEN** the installed-stack discovery child starts with the default total probe budget
- **THEN** each of its two sequential endpoints receives a 10-second timeout while the configured child budget is 22 seconds and the process remains capped at 22.25 seconds
- **AND** the process cap covers the 20-second combined request budget plus 2.25 seconds of bounded child overhead

#### Scenario: Little server-attempt budget remains

- **WHEN** the remaining server-attempt budget cannot support the normal endpoint timeout
- **THEN** the endpoint and process timeouts are reduced to fit without consuming connector finalization headroom
