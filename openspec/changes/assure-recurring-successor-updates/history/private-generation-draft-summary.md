# Retired Private-Generation Draft (Non-Normative)

This note preserves the useful engineering evidence from the superseded
private-generation draft. It is history, not an active requirement, acceptance
criterion, production dependency, or migration promise.

The retired draft explored a separate owner-only planning DuckDB, wave-scoped
parser-input stores, content-addressed member objects, sealed wave manifests, a
current/previous/candidate generation pointer, installed-tree identity, and
schema-versioned successor receipts. Its strongest reusable findings were:

- distinguish missing evidence, partial evidence, and a complete typed-zero
  result;
- freeze a request universe before update execution and prohibit runtime fan-out
  outside it;
- bind one logical provider response to every ordered result route rather than
  pretending logical-call and route counts are one-to-one;
- replace request-owned source scopes transactionally so corrections,
  deletions, and valid-empty responses remove stale rows;
- make candidate construction, scan, export, and promotion fail closed;
- retain enough receipt-bound progress to reconcile a crash without treating a
  path-only checkpoint as evidence;
- treat cancellation or any incomplete phase as non-success; and
- publish through the existing GitHub Deployment ledger only after exact remote
  inventory and digest readback.

The rejected architecture also introduced private baseline receipts, private
capture generations, private planning manifests, a generation store, and
private-retention policy as mandatory authorities. Those parts are superseded.
Recurring operation now has one durable dataset authority: the exact fully
verified Kaggle version. Public-safe request/result/header/ordinal/value/
presence/provenance landings and committed receipts are the durable provider
evidence. The retired draft treated decoded-body capture as optional bounded
diagnostic material. That historical choice is not the active contract: the
approved one-repository design now requires every successful body-bearing
provider occurrence's exact parser-input body as public authority and permits
bodyless evidence only for declared no-parser-input providers.

Historical schema numbers, type names, and checked task boxes from the retired
draft prove only that the earlier library experiment existed. They do not prove
the active one-repository transaction, `MODEL-GREEN`, `DATA-GREEN`, a live
daily/monthly run, or a Kaggle publication.
