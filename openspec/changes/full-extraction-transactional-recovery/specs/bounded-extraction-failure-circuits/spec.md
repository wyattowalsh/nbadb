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
The system MUST NOT count transport, timeout, HTTP transient, rate-limit, VPN,
authentication, runner, or control-plane failures toward a response-contract
circuit.

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
