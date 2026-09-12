## ADDED Requirements

### Requirement: Production execution is free-at-point-of-use by receipt

Before admitting any provider request, the system MUST validate a schema-
versioned `FreeExecutionAdmission` that binds the exact repository, source SHA,
workflow, run, attempt, job, runner/resource class, requested capacity,
authoritative eligibility source, observation time, expiry, and zero-cost-at-
point-of-use conclusion. Runner labels, plan names, device allowances,
historical charges, or assumed quotas MUST NOT establish eligibility.

#### Scenario: Trusted current evidence proves zero-cost capacity

- **WHEN** the exact requested jobs and resources are covered by an unexpired trusted eligibility receipt
- **THEN** admission may proceed only up to that receipt's exact capacity

#### Scenario: Cost evidence is missing or ambiguous

- **WHEN** cost semantics, resource identity, capacity, observation, expiry, or authoritative provenance cannot be proven
- **THEN** the workflow emits `capacity_blocked` and starts no provider request

#### Scenario: Evidence permits a nonzero charge

- **WHEN** the requested execution could consume a paid credit, paid minute, paid token, proxy, or VPN resource
- **THEN** production admission fails without falling back to that resource

#### Scenario: Public-repository compute is free but storage liability is unresolved

- **WHEN** standard GitHub-hosted compute is eligible for free public-repository use but artifact, cache, package, custom-image, retention, or other metered storage could exceed a current allowance or charge another billing period or account
- **THEN** admission remains `capacity_blocked` until an authoritative zero-liability resource plan and current billing readback cover every requested resource

#### Scenario: Pricing evidence is free-form or negated text

- **WHEN** eligibility is inferred from an unstructured description, a substring such as `free`, a negated statement, or caller-authored pricing text
- **THEN** it is not trusted cost evidence and cannot authorize provider work

### Requirement: Execution identity and resource plans come from authenticated authorities

Positive admission MUST derive repository visibility, exact workflow/run/attempt,
source and workflow SHA, actual job identity, GitHub-hosted runner environment,
standard runner class, requested capacity, execution mode, and nonce from
authenticated platform receipts whose issuer, signature, expiry, audience, and
direct API readbacks are independently validated. Caller-projected environment
values, mutable DTOs, workflow matrix labels, or self-resealed JSON MUST NOT
establish those facts. The admission MUST also bind an exhaustive recursive
resource plan covering jobs, `runs-on`, reusable workflows/actions, containers,
services, artifacts, caches, packages, custom images, retention, and every
other metered or externally billed dependency.

#### Scenario: Caller supplies matching run and runner values

- **WHEN** a caller passes repository, run, job, runner, capacity, mode, or nonce values that happen to match the expected text but lacks the authenticated execution-context authority
- **THEN** positive admission remains impossible

#### Scenario: A nested action or service adds a paid resource

- **WHEN** recursive workflow resolution finds a paid runner, service, proxy, package, storage action, container, custom image, or unreviewed external billing dependency in any key or value
- **THEN** the complete plan is not zero-cost and no provider operation is authorized

#### Scenario: Artifact evidence is bound only to a workflow run

- **WHEN** an artifact receipt proves its run but cannot prove the exact producing job required by the execution-context contract
- **THEN** it cannot serve as positive job authority without a separate authenticated job-to-artifact join

### Requirement: Provider authorization is exact and non-transferable

Immediately before each provider operation, the system MUST validate an
unexpired authorization bound to the authenticated execution context, admitted
slot, lane, endpoint, canonical path and URL, exact parameters/body identity,
operation ordinal, and one issued nonce. Authorizations MUST be derived from an
immutable admitted plan and MUST be single-use; a copied, reserialized,
re-sealed, reordered, widened, or replayed authorization MUST fail closed.

#### Scenario: A lane changes the endpoint or parameter tuple

- **WHEN** the actual provider operation differs from the admitted endpoint, path, parameter/body digest, lane, ordinal, or nonce
- **THEN** the boundary rejects it before network access

#### Scenario: A valid authorization is replayed

- **WHEN** an already consumed operation nonce is presented again or by another job or lane
- **THEN** it is rejected and the ledger does not advance a second time

#### Scenario: The ledger root is reconstructed from caller-authored state

- **WHEN** restoration lacks an exact receipt-bound checkpoint, safe artifact inventory, and authenticated creator/job provenance
- **THEN** no positive authorization, boundary summary, or zero-cost readback may be restored

### Requirement: Production has no Nord or paid-egress dependency

Initial extraction, terminal catch-up, daily, monthly, opportunistic, and
publication workflows MUST operate through admitted direct connectivity and
MUST NOT require Nord credentials, a paid VPN/proxy, a paid egress token, or a
paid relay. Legacy connector code or diagnostics MUST NOT be reachable as a
production admission or fallback path.

#### Scenario: A workflow still references Nord production secrets

- **WHEN** static validation finds a production job, default, action call, or fallback that requires Nord or another paid egress service
- **THEN** the workflow contract fails before exact-SHA CI or provider work

#### Scenario: Direct reachability is unavailable

- **WHEN** strictly-free direct runners cannot pass admission and canaries
- **THEN** the run remains `capacity_blocked` or `not_fresh`; it does not switch to paid egress or reduce coverage

### Requirement: Every actual runner passes bounded direct canaries

Every admitted job that can call the provider MUST independently pass a bounded
GitHub control-plane probe, strict TeamYears response-shape probe, and installed-
stack `common_all_players` plus `league_game_log` canaries. The receipt MUST bind
the exact runner, job, run, attempt, source, canary contract version, result
shapes, sanitized failure classifications, observation time, and expiry and
MUST be rechecked immediately before the first provider call.

#### Scenario: A different runner passed preflight

- **WHEN** a matrix job has no unexpired canary receipt for its own runner identity
- **THEN** that job makes no provider call even if another job's canaries passed

#### Scenario: TeamYears or installed-stack shape is invalid

- **WHEN** a direct canary times out, returns malformed success, empty required membership, or inconsistent discovery evidence
- **THEN** the runner is ineligible and emits only allowlisted diagnostic metadata

#### Scenario: Direct smoke passes

- **WHEN** one exact-SHA attempt-one nonpublishing smoke has a valid free admission, all runner-local canaries, a complete lane, and a committed checkpoint receipt
- **THEN** it proves only that bounded direct transaction and MUST NOT claim full-dataset assurance

### Requirement: Execution slots remain complete and balanced

Before publishing a lane manifest, the planner MUST validate nonnegative lane
count `N`, positive admitted slot count `S`, unique lane IDs, complete rows, and
integer execution-slot assignments. For `N > 0`, used slots MUST be contiguous,
each count MUST be at most `ceil(N / S)`, and the largest and smallest used-slot
counts MUST differ by at most one. Per-slot jobs MUST use non-cancelling serial
queues, and live jobs MUST NOT exceed the free-capacity receipt.

#### Scenario: More lanes than admitted slots

- **WHEN** `N > S`
- **THEN** later lanes reuse their deterministic slots only through the slot's serial queue without changing request coverage

#### Scenario: Assignment is malformed or imbalanced

- **WHEN** a lane is missing or duplicated, a slot is invalid, used slots have a gap, or the balance bound is exceeded
- **THEN** planning fails before manifest publication or provider access

#### Scenario: Admitted capacity shrinks

- **WHEN** a required recheck proves fewer eligible slots than the active manifest requires
- **THEN** no new provider call begins, completed work may be checkpointed, and continuation waits for a fresh admission without rebasing coverage

### Requirement: Free capacity is re-read after execution

Every production generation MUST obtain a trusted post-run usage/cost receipt
for the exact admitted resources. Missing, drifted, ambiguous, or nonzero
readback MUST keep assurance and publication red even when extraction outputs
appear complete.

#### Scenario: Extraction completes but usage evidence is absent

- **WHEN** every lane completes but the exact post-run zero-cost receipt cannot be obtained
- **THEN** the generation cannot become assured or publishable

#### Scenario: Compute is zero but storage or cross-account usage changed

- **WHEN** the post-run readback shows unresolved artifact/cache retention, a storage allowance overrun, a different billing owner, a later-period liability, or any nonzero charge
- **THEN** the generation remains unverified or charged and publication stays blocked

#### Scenario: A successor readback precedes its predecessor

- **WHEN** a purported post-run receipt predates, reverses, or does not cryptographically descend from the admitted pre-run authority and operation ledger
- **THEN** it is rejected even when its reported amount is zero

### Requirement: Recurring free-capacity demand is coalesced

Daily and opportunistic triggers MUST share one non-cancelling generation
authority. Concurrent triggers MUST coalesce into one monotonically increasing
desired cutoff and MUST NOT create duplicate provider or publisher work. Every
trigger MUST receive a durable `fresh`, `not_fresh`, or `capacity_blocked`
receipt.

#### Scenario: Several triggers arrive while one tail is active

- **WHEN** daily and opportunistic requests overlap
- **THEN** one active generation owns provider work and its desired cutoff advances monotonically

#### Scenario: No free capacity is available

- **WHEN** a recurring trigger cannot obtain a valid free admission
- **THEN** it records `not_fresh` and `capacity_blocked` without mutating the last published authority
