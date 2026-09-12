## ADDED Requirements

### Requirement: Execution freezes the latest compatible stable provider release

At execution kickoff, the system MUST enumerate official non-yanked stable
`nba_api` releases newest-to-oldest, compatibility-test each candidate against
the exact repository stack, and freeze the first passing release. The freeze
receipt SHALL bind the selected distribution, archives and hashes, upstream
source/tag/commit/tree, docs/tools/runtime inventories, compatibility commands,
results, license, and observation time. A locally installed or locked version
is planning evidence only until this selection completes.

#### Scenario: A newer stable candidate is incompatible

- **WHEN** the newest non-yanked stable release fails a declared compatibility gate and the next candidate passes every gate
- **THEN** the passing candidate is frozen with both candidates' ordered evidence and the rejected candidate cannot silently re-enter extraction

#### Scenario: The release inventory cannot be proven

- **WHEN** official release enumeration is unavailable, incomplete, ambiguous, or contains an unclassified candidate
- **THEN** provider authority and extraction admission remain blocked rather than assuming the local `1.11.4` snapshot is latest

#### Scenario: Dependency surfaces name different releases

- **WHEN** the dependency pin, lock, installed distribution, standalone connector, headers, generated authority, fixtures, or parity tests do not all bind the selected release
- **THEN** the mixed-release tree fails before package discovery or extraction

### Requirement: Provider authority is observed rather than self-attested

The system MUST bind extraction authority to a verified receipt produced from
the installed distribution, lock archives, exact upstream tag/commit/tree,
clean source inventory, installed/source parity, and license. Repository
constants MAY define expected values but MUST NOT by themselves count as
observed evidence.

#### Scenario: A manifest repeats expected constants without a receipt

- **WHEN** planning, resume, lane restore, checkpoint restore, or terminal assurance receives expected provider values but no verified evidence receipt
- **THEN** admission fails before extraction or state reuse

#### Scenario: Exact installed and source evidence matches

- **WHEN** every observed provider field matches the exact pinned contract and the evidence receipt digest verifies
- **THEN** the receipt may be associated with plans and state without changing semantic lane identity

### Requirement: The adapter enforces an independent nbadb contract

The provider adapter SHALL compare runtime packets with the exact-tag nbadb
contract bundle rather than using the same installed endpoint declaration as
both implementation and oracle.

#### Scenario: Installed expected_data and parser drift together

- **WHEN** installed declarations and parser output agree with each other but differ from the verified nbadb bundle
- **THEN** the adapter raises the stable response-contract failure before schema validation

#### Scenario: A complex pinned parser remains conformant

- **WHEN** an immutable exact-release fixture passes through the retained V2/V3/live parser
- **THEN** nbadb emits ordered owned packets with exact name, ordinal, columns, row count, and normalized hash parity

### Requirement: The complete package and request surface is fail-closed

The frozen authority MUST account for every package-exposed stats, live,
static, helper, filter, and finder module and symbol; physical route;
constructor and wire parameter; constraint and dependency; result occurrence;
nested node; ordered duplicate-header occurrence; field; competition;
temporal applicability; repo extractor and alias; staging key; and public sink.
Runtime reflection and independent source/wheel/docs analysis SHALL reconcile
to an exact explained diff. Import suppression, warning-and-omit discovery,
`contract_not_modeled`, or an unclassified occurrence MUST remain blocking.

#### Scenario: One package module fails import

- **WHEN** discovery cannot import or inspect one exposed module or symbol
- **THEN** the authority receipt records the exact failure and MODEL-GREEN remains red; the module is not omitted from the denominator

#### Scenario: Two result sets reuse one header name

- **WHEN** a provider surface exposes duplicate names across result ordinals or duplicate headers within one result
- **THEN** each ordered occurrence receives a distinct identity and must reconcile independently through its request scope, temporal evidence, route, and public sink

### Requirement: Provider objects do not escape the boundary

Public and orchestration-facing extraction values MUST be nbadb-owned immutable
contracts or Polars frames. Upstream endpoint, response, dataset, pandas, and
parameter-class objects MUST remain internal to the provider boundary.

#### Scenario: Architecture validation scans production imports and types

- **WHEN** validation finds a raw transport/private parser/upstream object use outside the allowlisted boundary
- **THEN** the pre-extraction gate fails with the exact file and symbol

### Requirement: Failure semantics are stable and secret-safe

The adapter SHALL preserve status and root exception class while classifying
transport, parser, upstream-response-change, upstream-unavailable, adapter, and
orchestration outcomes. It MUST NOT persist response snippets, arbitrary URLs,
headers, credentials, proxy values, or exception messages.

#### Scenario: A non-2xx response contains a valid-looking result set

- **WHEN** the provider returns a non-2xx response whose JSON resembles a valid packet
- **THEN** nbadb records the HTTP failure and does not accept rows as coverage

#### Scenario: An exception message contains a credential

- **WHEN** a transport or parser exception includes sensitive text
- **THEN** only allowlisted class/status/digest metadata is retained
