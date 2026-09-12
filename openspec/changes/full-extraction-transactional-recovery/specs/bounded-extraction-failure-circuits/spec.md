## ADDED Requirements

### Requirement: Response-contract circuits are explicitly endpoint-scoped
The system SHALL enable repeated response-contract suppression only for
endpoints with an explicit positive threshold and SHALL scope circuit state to
one pattern-result execution.

#### Scenario: Endpoint has a positive threshold
- **WHEN** the endpoint begins a pattern-result execution
- **THEN** the system creates isolated consecutive-failure state for that endpoint and execution

#### Scenario: Endpoint is not configured
- **WHEN** no positive threshold exists for an endpoint
- **THEN** every eligible call follows the ordinary extraction and retry path

### Requirement: Only consecutive identical permanent failures open the circuit
The system MUST count only permanent `response_contract` failures with the same
normalized root-error signature and MUST open after the configured consecutive
threshold.

#### Scenario: Threshold is reached
- **WHEN** an endpoint produces the configured number of consecutive response-contract failures with the same signature
- **THEN** later queued calls in that pattern execution are suppressed before entering the upstream rate limiter

#### Scenario: Failure signature changes
- **WHEN** a different response-contract signature occurs before the threshold
- **THEN** the consecutive count restarts for the new signature

#### Scenario: Valid response occurs
- **WHEN** the endpoint returns a contract-valid response
- **THEN** the endpoint's response-contract circuit state resets

### Requirement: Transient and infrastructure failures never open this circuit
The system MUST NOT count transport, timeout, HTTP transient, rate-limit,
network-egress, authentication, runner, or control-plane failures toward a
response-contract circuit.

#### Scenario: Calls fail with a transport error
- **WHEN** configured endpoint calls raise retryable connection or transport failures
- **THEN** the response-contract circuit remains closed and ordinary retry and failure policies apply

### Requirement: Suppressed calls remain failed and resumable
For every suppressed eligible call, the system MUST increment failed-call
accounting, write a failure journal record with a distinct circuit-open marker,
return response-contract failure evidence, and MUST NOT write a success journal
record or completed coverage.

#### Scenario: Queued calls are suppressed
- **WHEN** the circuit is open and an eligible call reaches execution
- **THEN** that call is counted and journaled as failed without an upstream request

#### Scenario: Extraction resumes later
- **WHEN** a later run evaluates journal and coverage state
- **THEN** suppressed calls remain outstanding and are eligible for retry

### Requirement: Suppression does not reduce required coverage
The system SHALL preserve the original eligible-call denominator, required
semantic coverage, and terminal assurance obligations when a circuit opens.

#### Scenario: Homogeneous malformed chunk reaches threshold
- **WHEN** only a bounded prefix is sent upstream and the remaining chunk calls are suppressed
- **THEN** success count remains limited to genuine valid responses, failure count includes every failed or suppressed call, and the result is incomplete

#### Scenario: Zero-progress abort follows suppression
- **WHEN** the endpoint is configured for zero-progress abort and the chunk makes no completed progress
- **THEN** the normal abort policy stops further chunks while preserving all unattempted and suppressed coverage for resume

### Requirement: Suppression is observable and distinguishable
The system SHALL emit an endpoint, failure-signature, and circuit-open marker
that distinguishes suppression from an actual upstream request failure.

#### Scenario: Operators inspect a failed lane
- **WHEN** response-contract suppression occurred
- **THEN** logs, returned failure evidence, and journal errors identify the response-contract circuit and triggering signature

### Requirement: Repeated box-score-hustle failure requires bounded classification
Before launching another full extraction from a new source, the system MUST
classify the repeated `box_score_hustle` failure for target game `0024800300`
against controls `0024800299` and `0024800301`. The diagnostic MUST use exactly
two independently admitted egress paths, zero in-call retries, and at most six
upstream calls total.

#### Scenario: Bounded diagnostic runs
- **WHEN** release has explicit diagnostic authority and both egress paths pass admission
- **THEN** each path probes the target and both controls once without mutating extraction journals or durable coverage

#### Scenario: Required admission or evidence is unavailable
- **WHEN** either egress cannot be admitted or the six-call evidence is incomplete or ambiguous
- **THEN** release stops and does not reset the chain safety cap or launch an unchanged third production attempt

### Requirement: Incident evidence is secret-safe and decision-bound
The diagnostic MUST retain only HTTP status class, content type, response byte
length and SHA-256, outer and root exception class names, and valid result-set
names and row counts. It MUST NOT persist response bodies, request parameters,
credentials, or non-allowlisted exception messages. The outcome MUST select one
predefined handling branch.

#### Scenario: Valid JSON exposes a local parser defect
- **WHEN** target and controls return contract-valid JSON but local result-set handling fails for the target
- **THEN** the implementation may add one sanitized fixture and a narrow parser correction

#### Scenario: Evidence is transport-transient
- **WHEN** either egress observes HTTP 429/5xx, HTML or WAF content, a transport envelope, or egress-dependent behavior
- **THEN** the implementation may correct transport classification or bounded retry behavior and MUST NOT classify the target as contract-blocked

#### Scenario: Target is valid empty data
- **WHEN** the target consistently returns a contract-valid empty result
- **THEN** extraction records a successful zero-row call with ordinary request and result-set provenance

#### Scenario: Target is repeatably unsupported
- **WHEN** both controls succeed and both egress paths return the same target-specific unsupported contract evidence
- **THEN** only an independently validated parameter-scoped `upstream_unavailable` support rule may be added

#### Scenario: Classification remains ambiguous
- **WHEN** evidence does not satisfy exactly one handling branch
- **THEN** implementation and release stop without fabricating success or broadening support exclusions

### Requirement: Incident handling cannot weaken historical coverage
Old-chain artifacts from run `30511585896` MUST remain diagnostic only for a
fresh-source cutover. Any support rule derived from the diagnostic MUST be
limited to the proven endpoint and parameter identity and MUST NOT exclude the
entire lane, 1946-49 season range, or unrelated games.

#### Scenario: Fresh source chain is prepared
- **WHEN** incident classification and exact-source validation are complete
- **THEN** the new chain supplies no old-chain lane manifest, resume source, checkpoint, or recovery pointer

#### Scenario: Evidence proves only one game unsupported
- **WHEN** the target-specific unsupported branch is satisfied
- **THEN** terminal support evidence names only the proven endpoint/parameter contract and preserves every other required coverage unit
