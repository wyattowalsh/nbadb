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
