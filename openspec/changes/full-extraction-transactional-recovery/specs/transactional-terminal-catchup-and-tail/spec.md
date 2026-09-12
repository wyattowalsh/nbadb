## ADDED Requirements

### Requirement: Terminal catch-up has one frozen event-time cutoff

After historical fixed-point extraction, the system MUST create a schema-
versioned `TerminalCatchupGeneration` with an immutable event-time cutoff. The
generation MUST account separately for baseline-to-cutoff completion, a
declared recent overlap refresh, whole-history request and field hole repair,
and one frozen live snapshot. None of the four components may be omitted or
silently replaced by a generic latest-data refresh.

#### Scenario: Historical lanes complete before the cutoff

- **WHEN** provider data becomes available between their last extraction and the frozen cutoff
- **THEN** baseline-to-cutoff completion requests and receipts cover that interval

#### Scenario: Recent data can be corrected upstream

- **WHEN** the declared overlap interval intersects already completed periods
- **THEN** those exact identities are refreshed with provenance-preserving replacement/merge rules

#### Scenario: A historical request or field hole exists

- **WHEN** independent verification finds a missing invocation, body/bodyless receipt, result set, field, or temporal evidence anywhere in history
- **THEN** the exact hole remains scheduled until repaired or narrowly evidenced unavailable

#### Scenario: Live state is captured

- **WHEN** the historical, overlap, and hole components are accounted for
- **THEN** one live snapshot bound to the same cutoff and authority generation is frozen without overwriting historical facts

### Requirement: Observation windows are explicit and sealed

Every terminal-catch-up provider call MUST record observation start and end
times. The generation MUST bind its minimum start, maximum accepted end, final
seal time, clock/ordering contract, and exact call inventory. A call ending
after the seal MUST NOT enter the sealed generation, even when its event time is
at or before the cutoff.

#### Scenario: A call completes before the seal

- **WHEN** its event identity is in scope and its observation end is at or before the final seal
- **THEN** its receipt may enter the generation after all other authority checks pass

#### Scenario: A call completes after the seal

- **WHEN** its observation end is later than the committed seal
- **THEN** it is excluded from that generation and may enter only a later parent-bound tail

#### Scenario: Observation timing is missing

- **WHEN** a successful occurrence lacks exact start/end evidence or ordering is contradictory
- **THEN** terminal catch-up remains unsealed and cannot become assured

### Requirement: Terminal catch-up is a four-state transaction

The system MUST apply `candidate`, `built`, `uploaded_verified`, and `committed`
states to every terminal-catch-up generation. Its built identity MUST bind the
parent committed checkpoint, RequestUniverse generation, public observation and
body/bodyless inventory, field-temporal authority, model contract, cutoff,
overlap scope, hole-repair inventory, live snapshot, observation window and
seal, database/report digests, and canonical component inventory. Commit MUST
occur only after exact artifact-ID receipt verification.

#### Scenario: Terminal catch-up commits

- **WHEN** all four components, content digests, authority digests, and the exact artifact receipt verify
- **THEN** the committed catch-up generation becomes terminal assurance's sole data authority

#### Scenario: A crash occurs before commit

- **WHEN** candidate construction, build, upload, receipt verification, or commit is interrupted
- **THEN** the previous committed checkpoint/catch-up remains authoritative and retry may resume only from its exact receipt

#### Scenario: A retry attempts an unreceipted live snapshot

- **WHEN** prior work has no committed transaction binding its live and seal identity
- **THEN** it is diagnostic only and cannot be merged as recovered terminal authority

### Requirement: TailGeneration is immutable and parent-bound

Provider observations after a committed terminal seal MUST enter a new schema-
versioned `TailGeneration`. Its identity MUST bind the exact committed parent,
source SHA, semantic diff, request-universe generation, event cutoff,
observation window, overlap scope, body/bodyless and field-temporal authority,
and canonical request inventory. It MUST use the same four-state transaction and
MUST NOT mutate or relabel its parent.

#### Scenario: New next-day data appears

- **WHEN** provider data after the parent cutoff becomes available under unchanged authority
- **THEN** a tail covers the exact new interval plus its declared overlap and commits as a child generation

#### Scenario: Provider authority changes

- **WHEN** semantic diff changes request identity, field meaning/type/key, route, model lineage, or temporal authority
- **THEN** tail admission fails and a new fresh baseline is required

#### Scenario: A tail fails before commit

- **WHEN** any tail transaction stage fails
- **THEN** the parent remains publishable authority and the failed tail is diagnostic/recoverable only by exact committed receipts

### Requirement: Daily freshness is evidenced, not implied

Daily scheduling SHOULD target next-day provider availability whenever strictly-
free capacity exists. Every scheduled or coalesced attempt MUST emit a durable
receipt identifying its desired cutoff, parent, admission, provider observation,
and final state of `fresh`, `not_fresh`, or `capacity_blocked`. Workflow success
without a committed tail MUST NOT be reported as fresh.

#### Scenario: No new provider data is present

- **WHEN** a valid admitted observation proves no events are available beyond the parent cutoff
- **THEN** the receipt records evidence-backed `not_fresh` without fabricating a tail

#### Scenario: Capacity is unavailable

- **WHEN** no current strictly-free admission exists
- **THEN** the receipt records `capacity_blocked` and `not_fresh` without provider calls

#### Scenario: A committed tail reaches the desired cutoff

- **WHEN** all exact requests through the cutoff are terminal and the tail receipt commits
- **THEN** the attempt may report `fresh` for that cutoff

### Requirement: Opportunistic triggers coalesce without duplicate work

Daily, event-driven, manual, and opportunistic tail triggers MUST serialize on
one non-cancelling generation authority. While work is active, new demand MUST
advance one desired cutoff monotonically and MUST NOT launch a competing
provider matrix or publisher. Coalescing MUST preserve each trigger's receipt.

#### Scenario: A later trigger requests a newer cutoff

- **WHEN** an admitted tail is already active
- **THEN** the shared desired cutoff advances and one successor generation may cover the added interval

#### Scenario: Two triggers request the same cutoff

- **WHEN** their parent and authority identities match
- **THEN** one generation performs provider work and both trigger receipts point to its outcome
