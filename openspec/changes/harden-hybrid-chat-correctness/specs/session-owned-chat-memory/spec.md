## ADDED Requirements

### Requirement: Preference mutation distinguishes administrator and scoped sessions
At the preference-store boundary, `session_id=None` MUST mean unscoped
administrator access. Any supplied empty or whitespace-only session ID MUST be
rejected with `ValueError("session_id must be non-empty")` before a database
mutation.

#### Scenario: Scoped caller supplies whitespace
- **WHEN** a preference create, update, or delete receives a supplied session ID that normalizes to empty
- **THEN** the mutation fails before opening an ownership transaction

#### Scenario: Administrator omits session
- **WHEN** an unscoped caller supplies `None`
- **THEN** administrator semantics apply without converting it to an empty scoped identity

### Requirement: Scoped preference create and update are atomic and ownership-preserving
A scoped preference mutation MUST begin an immediate SQLite transaction, read
and validate any existing `ProfileRecord`, authorize ownership, and write within
that transaction. An absent key MUST be created with the caller as owner. An
existing key MUST be updated only by its exact owner.

#### Scenario: Scoped caller creates an absent key
- **WHEN** no record exists at transaction admission
- **THEN** the caller creates it with its own session ID and one preserved creation timestamp

#### Scenario: Exact owner updates a key
- **WHEN** the stored validated session ID equals the caller
- **THEN** the value is updated, `created_at` is preserved, omitted notes remain unchanged, and `updated_at` advances

#### Scenario: Foreign, null, or malformed ownership is encountered
- **WHEN** the record belongs to another session, has a null owner, or fails `ProfileRecord` validation
- **THEN** the transaction rolls back and raises `PermissionError("preference is not owned by this session")`

### Requirement: Administrator updates preserve omitted record provenance
An unscoped administrator MAY create or update any preference. When updating an
existing valid record, omitted owner and notes MUST remain unchanged,
`created_at` MUST be preserved, and `updated_at` MUST advance.

#### Scenario: Administrator changes only a value
- **WHEN** an administrator updates an owned record without supplying owner or notes
- **THEN** the existing owner, notes, and creation timestamp remain unchanged

#### Scenario: Administrator creates a new record
- **WHEN** no key exists and the administrator supplies no owner
- **THEN** the new record is null-owned and remains inaccessible to scoped mutation

### Requirement: Preference update timestamps are synchronized and monotonic
After beginning the immediate transaction, the store MUST validate and
authorize an existing record before sampling the preference wall clock. It MUST
parse every present JSON `updated_at` and SQL `updated_at` value as an aware ISO
timestamp, normalize it to UTC, and use the later valid copy as the prior
timestamp. One missing legacy copy MAY be healed from the other valid copy; a
malformed or naive copy, two missing copies, or an unadvanceable maximum
timestamp MUST use the existing fixed invalid-record error mapping. The next
timestamp MUST be the later of the UTC wall clock and one microsecond after the
prior maximum, formatted with UTC microseconds, and written identically to the
JSON record and SQL column. This preference-only behavior MUST NOT change
trajectory timestamp precision.

#### Scenario: Wall clock stalls or moves backward
- **WHEN** an authorized owner or administrator repeatedly updates one key while the wall clock is equal to or earlier than its prior timestamp
- **THEN** each committed `updated_at` advances by one microsecond and both stored copies are identical

#### Scenario: Legacy timestamp copies differ
- **WHEN** both copies are valid but differ, or exactly one copy is absent
- **THEN** the next update advances from the later available value and heals both copies to one identical UTC timestamp

#### Scenario: Stored timestamp is invalid
- **WHEN** a present copy is malformed or naive, both copies are absent, or the prior maximum cannot advance
- **THEN** a scoped mutation raises the fixed ownership `PermissionError` and an administrator mutation raises the fixed invalid-record `ValueError`

#### Scenario: Foreign caller reaches an owned record
- **WHEN** a foreign scoped caller attempts an update
- **THEN** ownership fails before the preference wall clock is sampled

### Requirement: Preference deletion uses the same ownership transaction
Delete MUST use the same session normalization, immediate transaction, record
validation, and ownership rules as update. An absent key MUST return `False`.
An exact owner or unscoped administrator MAY delete. Foreign, null-owned, or
malformed records MUST raise the fixed ownership `PermissionError`.

#### Scenario: Exact owner deletes
- **WHEN** the caller's session exactly matches the stored owner
- **THEN** the row is deleted and the operation returns `True`

#### Scenario: Foreign caller deletes
- **WHEN** a scoped caller does not own the existing record
- **THEN** deletion rolls back and raises the fixed ownership error without revealing the owner

#### Scenario: Key is absent
- **WHEN** no record exists at transaction admission
- **THEN** deletion returns `False` without creating a row

### Requirement: Concurrent sessions cannot transfer ownership
Separate SQLite connections contending for the same absent key MUST serialize
at the immediate transaction boundary. Exactly one scoped session MUST create
the key; every competing foreign mutation MUST fail with the fixed ownership
error and MUST NOT corrupt or replace the winning record.

#### Scenario: Two sessions create the same absent key
- **WHEN** two connections race to create one key with different session IDs
- **THEN** exactly one becomes owner and the other receives the ownership error after observing the committed record

#### Scenario: Owner update contends with foreign update or delete
- **WHEN** an owner and foreign session mutate the same existing key concurrently
- **THEN** every committed state is valid, retains the owner, and contains no partial or malformed JSON

### Requirement: MCP memory mutations preserve store authorization
MCP preference writes and deletes MUST require a nonempty scoped session, retain
existing payload and confirmation bounds, and propagate only the sanitized fixed
ownership failure. They MUST NOT bypass the store transaction or expose stored
record contents.

#### Scenario: MCP delete lacks confirmation
- **WHEN** a caller requests preference deletion without `confirm=True`
- **THEN** the wrapper rejects the request before store mutation

#### Scenario: MCP caller does not own the preference
- **WHEN** the store rejects the scoped mutation for ownership
- **THEN** the caller receives the fixed ownership error and no owner or value detail

### Requirement: Scoped reads expose only exact-owner memory
Preference listing and trajectory search MUST require a normalized nonempty
session ID, validate stored records, and return only records whose stored session
exactly matches the caller. Foreign, null-owned, or malformed rows MUST NOT be
returned. Any administrator-wide inspection MUST use a separately named store
API that is not exposed as a general MCP tool.

#### Scenario: Two sessions list preferences
- **WHEN** two sessions own different preference keys
- **THEN** each scoped listing returns only its exact-owner record

#### Scenario: Trajectory search has foreign and null-owned hits
- **WHEN** a scoped search matches own, foreign, and null-owned trajectories
- **THEN** only the exact-owner valid trajectory is returned

#### Scenario: Scoped read encounters malformed ownership
- **WHEN** a candidate row cannot validate or contains an empty stored session
- **THEN** the read fails closed with a bounded invalid-record error and exposes no record contents
