## Why

The current public Kaggle dataset does not contain the complete frozen model
authority required by this program, so it is not an admissible recurring parent.
The first production parent must be a brand-new full-model baseline produced by
one fresh exact-SHA full extraction and accepted only after exact positive-version
remote readback. Recurring implementation can be tested locally before that
baseline exists, but it cannot publish or claim freshness against the current
public version.

The daily and monthly workflows also mutate a downloaded dataset in place, omit
the exact version required by verified-baseline download, reuse globally
completed extraction-journal rows, plan only narrow current/recent windows,
tolerate incomplete entity discovery, append changed discovery rows, skip failed
or empty transforms, and publish after only a generic scan. A successful full
extraction therefore does not prove that the next recurring update is fresh,
complete, atomic, uniquely versioned, or linked to the assured baseline it
replaced.

## Supersession Decision

The private planning-generation/GHCR/second-authority architecture described by
the earlier draft is superseded. Recurring updates use one repository and the
newest exact, fully verified Kaggle version that satisfies the active full-model
authority as their durable parent. "Latest" is never authority by itself. GitHub
artifacts and local checkpoints provide bounded same-transaction recovery only;
they are not a second dataset authority. Existing `successor_*` implementation
and tests remain preserved until each surface is classified and the replacement
transaction has equivalent focused coverage, then are reused, retired, or
archived under an explicit reference audit.

## What Changes

- Block production recurring admission until the fresh full-model initial
  publication has one exact positive Kaggle version, a complete streamed
  SHA-256 readback, and matching initial assurance. The current incomplete
  public dataset cannot satisfy this barrier.
- Reconcile any unresolved durable publication intent, then pass the resolved
  exact positive version explicitly to verified-baseline download, force-read
  every resource, and install a separate immutable parent plus disposable
  candidate.
- Compile daily, monthly, and opportunistic work as the deduplicated union of
  exact parent/request/field cutoff-to-as-of catch-up, conservative
  endpoint-specific correction overlap, and explicit older request/field
  identity-gap repair. Monthly additionally performs recent-season refresh plus
  a whole-history identity/field audit.
- Coordinate all recurring demand through one durable coalescing coordinator
  that retains the newest required cutoff, unions deeper scopes, permits one
  active candidate/writer, replaces redundant queued work, and proves monthly
  work cannot erase next-day daily freshness or create backlog.
- Append only declared immutable observations. Replace complete request-owned
  mutable source slices in transactions, including typed-zero deletion; rebuild
  every affected stable output; freeze all four export formats; and issue
  `UpdateAssuranceV1` only after complete scan and parity proof.
- Emit `RecurringRunStatusV1` from an always-run finalizer, including failures
  before extraction, so workflow success never substitutes for a receipt-bound
  `fresh` decision.
- Freeze one stable `update_transaction_id` for the original logical update and
  preserve it across attempts and recovery. A retry of that same immutable
  intent is reconciliation-only; every later distinct fully assured transaction
  creates exactly one new cumulative Kaggle version, including no-game or
  otherwise semantically unchanged table data.
- Keep full-extraction checkpoints for the expensive initial historical load;
  do not carry the private current/previous/candidate planning store into
  ordinary daily/monthly operation.
- Generate the resource denominator from the frozen manifest rather than a
  hard-coded table/resource count, and require exact four-format parity plus
  complete streamed remote readback.
- Force-download the newest immutable successor version into a new owner-only
  root, obtain a genuinely human four-format verification receipt without
  automation manufacturing the attestation, prove docs/metadata parity, and
  join every proof layer into `DataGreenReceiptV1`.

The previous private-generation implementation is not a production dependency.
Reusable validation, source-replacement, scan, and publication-ledger helpers may
remain while callers migrate, but public commands and hosted workflows MUST NOT
require a private repository, GHCR package, private generation pointer, or
encrypted planning store. Every successful body-bearing provider occurrence
MUST publish its exact parser-input body and body receipt beside the public
request/result/route/field authority; declared no-parser-input providers use an
explicit bodyless disposition. The one repository's GitHub Actions workflows
are the only production initial, catch-up, daily, monthly, opportunistic,
publication, and final-closeout control plane. Production provider work requires
current `FreeExecutionAdmissionV1` evidence and fails closed as
`capacity_blocked`/`not_fresh` when a genuinely free NBA-reachable path is not
proven. NordVPN, paid proxies/VPNs, subscriptions, trials, or inferred device
capacity are neither required nor permitted fallbacks.

The first baseline restarts as a fresh exact-SHA attempt-one chain. Stable
source/silver/gold outputs gate release; separately versioned fitted RAPM, xFG,
WPA, forecast, rating, and prospect-value outputs remain non-gating unless
individually admitted. DATA-GREEN also requires one exact-parent daily
successor publication, exact readback of both initial and successor versions,
immutable newest-version redownload, authenticated human DuckDB/SQLite/Parquet/
CSV inspection with unchanged hashes, docs/metadata parity, and an Actions-only
final receipt join.

## Capabilities

### New Capabilities

- `assured-recurring-successor-updates`: fresh full-model parent admission,
  complete three-part daily/monthly/opportunistic closure, durable demand
  coalescing, public-safe lossless provider evidence, deterministic source
  replacement, disposable candidate assurance, truthful freshness finalization,
  stable update identity, version-every-distinct-transaction publication,
  same-intent-only reconciliation, immutable readback, authenticated human
  verification, docs parity, and final DATA-GREEN joining.

### Modified Capabilities

None. Full baseline construction and initial publication mechanics remain owned
by the active `full-extraction-transactional-recovery` change; this change owns
the recurring admission barrier that consumes its exact readback. The public
parser-input body, explicit-bodyless, request/result/field, and reconstruction
authorities remain owned by `harden-nba-api-pre-extraction-contracts`.

## Impact

This change affects recurring workflow admission, Kaggle download/install,
extraction journals and planners, durable coordination, discovery, staging merge
semantics, transformation and loading, export, scanner/assurance contracts,
transaction/version identity, always-run freshness status, daily/monthly/
opportunistic workflows, immutable readback, human-verification tooling,
authored/generated docs, final receipt joining, and focused/full tests. Delivery
uses exclusive file ownership, dependency receipts, and resolved fan-out before
joins. It does not authorize live extraction, publication, human attestation,
commit, push, or changes to repository secrets.
