## ADDED Requirements

### Requirement: Direct NBA canaries match the pinned runtime HTTP contract

The system SHALL send every strict TeamYears direct canary with the exact
ordered `STATS_HEADERS` mapping declared by the pinned `nba_api` runtime. The
canary implementation, standalone request copy, and runtime dependency MUST be
updated atomically when that contract changes.

#### Scenario: Canary and runtime headers match

- **WHEN** deterministic validation compares the canary sequence with the pinned runtime mapping
- **THEN** every header name, value, and order matches

#### Scenario: The pinned runtime changes its headers

- **WHEN** a dependency update changes `STATS_HEADERS` without updating every canary surface
- **THEN** validation fails before direct extraction admission

### Requirement: The public NBA header export matches the pinned runtime

The system SHALL expose `nbadb.core.NBA_HEADERS` as an independent mapping with
the exact names, values, and order declared by pinned `STATS_HEADERS`.

#### Scenario: A consumer reads the public mapping

- **WHEN** a consumer imports `NBA_HEADERS` from `nbadb.core`
- **THEN** it receives values equal to the pinned runtime contract without sharing the runtime mapping object

### Requirement: TeamYears remains fail-closed and shape-validating

An actual production runner MUST pass a bounded direct TeamYears request with a
successful HTTP status, the expected non-empty result-set headers, and at least
one width-matching row before provider work. A GitHub control-plane reachability
probe MUST also pass on that same runner.

#### Scenario: NBA.com silently times out

- **WHEN** the header-complete TeamYears request reaches its bounded timeout without a valid response
- **THEN** that runner is rejected and extraction does not start

#### Scenario: NBA.com returns malformed success content

- **WHEN** 2xx content lacks the required TeamYears headers or a width-matching row
- **THEN** the runner is rejected as a response-contract failure

#### Scenario: TeamYears passes

- **WHEN** the exact request returns the required non-empty shape on the actual runner
- **THEN** admission may proceed to installed-stack canaries on that runner

### Requirement: Installed-stack canaries match extraction discovery

Every provider-capable runner MUST execute installed-runtime
`common_all_players` and `league_game_log` canaries under bounded deadlines.
Player discovery MUST show positive player/team membership consistent with the
workload seed, and game discovery MUST return a contract-valid typed result,
including a typed evidence-backed empty result when that exact scope permits it.

#### Scenario: Player membership is empty or inconsistent

- **WHEN** `common_all_players` cannot prove positive player/team membership used by workload discovery
- **THEN** the runner cannot receive extraction work

#### Scenario: Game discovery is malformed

- **WHEN** `league_game_log` returns malformed content or a result inconsistent with its exact scope
- **THEN** the runner cannot receive extraction work

#### Scenario: All installed-stack canaries pass

- **WHEN** both installed endpoints and TeamYears pass on the same runner
- **THEN** one expiring runner/job/source/attempt-bound canary receipt may be issued

### Requirement: Installed-stack failures retain a secret-safe root cause

Failure attestations MUST preserve status, endpoint, failure kind, outer
exception type, and the explicit exception chain's root type as bounded
allowlisted ASCII tokens. They MUST NOT include exception messages, response
content, request parameters, credentials, cookies, authorization data, or
unrestricted bodies. A recognized root governs transport-versus-response-
contract classification; absent, malformed, or unrecognized roots fall back to
the validated outer type.

#### Scenario: A wrapper contains a timeout root

- **WHEN** an installed-stack canary raises a transport wrapper from a recognized lower-level timeout
- **THEN** the attestation retains both class names and classifies the failure as transport

#### Scenario: A wrapper contains a response-contract root

- **WHEN** a recognized contract root is wrapped by a transport-shaped outer type
- **THEN** the attestation retains both class names and treats the failure as runner-independent contract failure

#### Scenario: Exception messages contain sensitive content

- **WHEN** a wrapper or root message contains request or credential material
- **THEN** none of that message content enters the attestation or logs

#### Scenario: Root type is absent or malformed

- **WHEN** `root_error_type` is missing or outside the allowlist
- **THEN** classification uses only the validated outer type and does not surface the supplied value

### Requirement: Canary deadlines preserve finalization headroom

Every request and child process MUST have a positive bounded deadline nested
inside the workflow job's checkpoint, receipt, artifact-upload, diagnostics, and
finalization reserves. A smaller remaining budget MUST reduce or reject canary
work rather than extending the enclosing job deadline.

#### Scenario: Ordinary budget remains

- **WHEN** the runner-local canary process starts with its declared full budget
- **THEN** all endpoint and process deadlines fit inside the independent finalization reserve

#### Scenario: Too little budget remains

- **WHEN** the remaining job budget cannot complete every required canary and preserve finalization
- **THEN** admission fails before provider access rather than weakening a canary or reserve

### Requirement: Canary receipts are runner-local and expiring

A canary receipt MUST bind schema version, exact source SHA, workflow, run,
attempt, job, runner identity, canary contract digest, sanitized results,
observation time, and expiry. The job MUST revalidate it immediately before its
first provider call. Another job's receipt or an expired receipt is invalid.

#### Scenario: The job moves to another runner

- **WHEN** the execution identity differs from the receipt owner
- **THEN** every required canary is rerun and the old receipt is rejected

#### Scenario: Admission expires while queued

- **WHEN** the canary receipt is stale before the first provider call
- **THEN** the job stops or obtains a fresh complete receipt without making an unverified call
