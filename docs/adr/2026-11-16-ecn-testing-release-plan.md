# Reno Testing Reservation Release Implementation Plan

**Date:** 2026-11-16
**Status:** Accepted design; not yet implemented
**Track:** `N16-E` in the [November 16 correctness and architecture program](2026-11-16-architecture-correctness-program.md)
**Depends on:** nothing — E1 is independently startable
**Related:** [private BBR integration](0009-opt-in-bbrv3.md); [multipath endpoint plan](2026-10-24-multipath-endpoint-plan.md)
**Normative scope:** Current outcome, boundaries, invariants, acceptance evidence, blockers and stop conditions
**Audit history:** [Source and slice audit](../audits/2026-11-16-architecture-handoff/README.md)

## Goal

Let the existing path-local Reno validator decide whether an unsubmitted local testing registration belongs to its current testing interval before releasing that interval's reservation. Preserve historical local ECN evidence and BBR's distinct policy.

## Current shape (verified 2026-11-16)

The [Reno testing count](../../internal/ackhandler/ecn.go#L57) is unsigned. [Tuple restart](../../internal/ackhandler/ecn.go#L128) resets its count and packet bounds, while [late local unsubmitted completion](../../internal/ackhandler/local_ecn.go#L264) can still call [releaseTest](../../internal/ackhandler/local_ecn.go#L322). Its Reno branch decrements without checking current membership.

The connection [consumes completion before registry service](../../connection.go#L796), but endpoint terminal publication can occur between those operations. The [native fence](../../native_ordinary.go#L647) can be satisfied by a terminal endpoint record before recovery consumes it; [cutover restarts ECN](../../multipath_migration.go#L371). [Completion](../../internal/ackhandler/local_completion.go#L293) still handles ECN before returning for a retired packet. Two old unsubmitted test records can wrap the replacement interval's count and prematurely end testing. No runtime reproduction has yet been executed.

## Decision

Introduce a private current-test release operation on `ecnTracker`. The caller supplies the testing packet number. A missing current first-testing boundary, or a packet number below that boundary, rejects the release. A valid current testing record performs the existing decrement and Unknown-to-Testing reopening. Preserve the existing last-bound behavior and invalidation when reopening. Existing monotonic 1-RTT packet numbers survive tuple cutover; constructor and restart invalidate the first bound, and the first current test registration sets it.

`localECNEvidence.releaseTest` delegates its Reno branch to the validator. Its existing caller proves that the record was historically testing and releases before clearing its mark/bit. Preserve this ordering, token validation, cumulative counters, BBR's branch, and failed-state persistence. Do not reuse `isTestingPacket` unchanged as the guard: its local-evidence branch trusts historical testing metadata rather than current bounds.

**Owner's design:** adopted: the counter owner decides whether its current interval may be changed. It uses existing identity rather than a caller guard, side channel or new tuple-generation copy.

**Rejected alternatives (do not do this):** caller-side arithmetic guard leaves release policy outside the state owner; `none: rejected on merit`. A new generation field duplicates reset/monotonic-PN identity; revisit only if supported tuple restart reuses packet numbers. Clearing/retagging historical evidence or changing historical ACK/loss/pending-receipt semantics is a different invariant; revisit only under a separate accepted defect contract. A generic ECN facade or forty-line relocation alone does not repair ownership; revisit only when a real wider operation requires it.

**Non-goals:** ECN marking/validation redesign, universal current-tuple interpretation of historical evidence, new counters/generations, BBR policy changes, endpoint publication or fence timing changes, D5 or general packet retirement.

## Slice graph

| Slice | Disposition | Delivers | Blocked by | Temporary seam |
|---|---|---|---|---|
| E1 | new | Late-unsubmitted regression and validator-owned current release | None | None |

## Implementation slices

### E1 — Reject old testing releases after tuple restart

**What it delivers:** one independently green regression-and-fix PR through real recovery registration, migration/restart and completion APIs. An unsubmitted local testing registration may decrement current Reno testing allowance and reopen Unknown only when it belongs to the current interval.

**Existing-work disposition:** new slice; no open implementation found. Preserve the completed ECN/PTO correction in [PR #1418](https://github.com/the-sarge/quic-go-fast/pull/1418). Its marking-endpoint and PTO-loss owners are distinct from E1's current reservation-release owner; no repeated-root claim is made.

**Single owner after merge:** `ecnTracker` mutates its interval count/state. Local evidence owns registration facts and invokes release; existing completion validation owns token identity and exactly-once acceptance. Those preconditions remain authoritative rather than duplicated.

**Authority completeness:** no persisted authority. Existing construction/restart initialize invalid bounds; registration supplies the first current boundary; release uses it; failed state does not reopen; duplicate/foreign tokens remain rejected upstream. No new constructor or reset field is needed.

**Transitional-seam budget:** none. The new owner method and its sole Reno delegation ship together.

**Blast radius:** local Reno unsubmitted completion only; it can arrive after migration retired the packet. Preserve BBR, nonlocal Reno, historical ACK/loss interpretation, local pending counts and cumulative peer-counter continuity. No public/wire/security/dependency or execution-context change. No untraced effect is accepted; an independently found historical receipt/loss issue is not automatically this release invariant.

**Artifact classification:** counter-release correction is shipped behavior and required restart/accounting enforcement. Focused tests are verification aids; receipts, plans and mirrors are process metadata. No maintained verification service.

**Representation contract:** valid local tokens from `RegisterLocalPacket`, completed once as Unsubmitted, with monotonic 1-RTT packet numbers in the same path recovery context. Existing token validation, path routing and `ecnTracker` bounds own this typed domain. Current-interval release is enforced at one owner; finite evidence is example-level, not a universal ECN protocol proof.

**Contract closure:** not triggered. Restart corruption is material, but one synchronous release operation and its bounded interval states can be covered with ordinary focused tests. Do not broaden to a generic cohort matrix.

**TDD and evidence budget:** use `newLocalECNTestHandler(t, false)` and `localECNPacket` from [local ECN tests](../../internal/ackhandler/local_ecn_test.go#L15). The proposed `TestLocalECNTupleUnsubmitted` has three new cases: two old releases before the first current test; an old release after some current tests; and an old release after current Unknown. Register real old tokens, call MigratedPath then RestartTupleECN in production order, then complete old tokens. Observe the current ten-packet test budget and marking/state transition, not only wrapped arithmetic. Existing current-Unsubmitted replacement/reopening, BBR, nonlocal, token-rejection and non-1-RTT tests supply preservation evidence. No new native timing harness, guard mutation, repetition or platform campaign; the source trace and existing migration-fence tests connect legal local APIs to production.

**Dispatch context budget:** at most 14k input tokens: E1; `ecn.go`, `local_ecn.go`, `local_completion.go`, `sent_path.go`; relevant local ECN, tuple-ECN and token-lifetime tests; the short connection/fence/cutover excerpts cited above. Root migration fixtures are optional unless touched. Exclude complete prior reports and unrelated controller internals.

**Slice decision audit:** split reproduction and fix: no useful independently green intermediate outcome; reject on merit. Merge with L1: different invariant and enforcement owner despite shared ECN vocabulary; reject on merit. No blocker: existing typed boundaries and completion APIs already ship.

**Stop conditions:** supported local APIs cannot reproduce the release error after fixture preconditions are confirmed; a real restart reuses packet numbers; the correction requires changing historical ACK/loss/pending-receipt or cumulative-counter policy; or native demonstration requires a production synchronization mechanism. Record adjacent findings without expanding E1.

## Acceptance criteria

- The new before/partial/Unknown release regressions fail on unchanged source and pass with validator-owned release.
- In the declared typed domain, stale unsubmitted testing records cannot alter the replacement interval's allowance or reopen Unknown.
- Current unsubmitted testing still returns its reservation; BBR, nonlocal, failed-state and upstream token-ownership semantics remain unchanged.

The second criterion is enforced at the current-boundary owner. The listed cases and existing token tests terminate its representative evidence; no scheduling or grammar completeness claim is made.

## Validation gates

Run `go test ./internal/ackhandler -run '^TestLocalECNTupleUnsubmitted$' -count=1` red/green, then `go test ./internal/ackhandler -run '^Test(LocalECNOutcomes|SentPathTupleECN|LocalCompletion(Unsubmitted|TerminalLifetime)|ECNPTOTestingLoss)$' -count=1`, `go test ./internal/ackhandler -count=1`, `go test . -run '^TestPathMigration(FenceBeforeCommit|LateOldGenerationAck)$' -count=1`, `go vet ./internal/ackhandler`, and `go mod tidy -diff`. The new test name is proposed; existing names must be rechecked at the implementation head. Existing hosted checks remain required; add no new timing repetition or platform matrix.

## Operating discipline

The shared [review-loop baseline](https://github.com/the-sarge/skills/blob/main/_shared/REVIEW-LOOP.md) and [contract-closure baseline](https://github.com/the-sarge/skills/blob/main/_shared/CONTRACT-CLOSURE.md) govern, composed with this repository's [execution overlay](../REVIEW-LOOP.md). There is no repository contract-closure overlay. Use the shared baselines directly; do not copy or strengthen them. The [design-cost reference](https://github.com/the-sarge/skills/blob/main/_shared/DESIGN-COST.md) governs alternative comparisons. Use the root [glossary](../../GLOSSARY.md), [maintained-code conventions](../agents/conventions.md), and existing ADRs.

For each intended PR, use the accepted focused evidence below, one fully briefed initial review and at most one fresh replacement after accepted fixes, exact-head local certification, applicable same-head hosted checks, squash merge, then the post-merge development journal and pointer-based GitHub/OmniFocus reconciliation. The shared finding dispositions and precise-invariant-and-owner approach stops apply to review and verification. Diagnose failures before rerunning. The repository has no `task preflight`, `ci.yml` or `ci-*` gate; do not invent one. Implementation PRs also owe the existing ready-only independent-peer check. Documentation-only evidence PRs use the documented docs path.

Tests are verification aids, not newly approved maintained verification products. Existing focused tests and normal CI retain their existing role; no new analyzer, harness service, platform campaign, mutation campaign or release qualification is approved. The finite inventory below applies to new targeted evidence; existing affected-package and hosted suites are unchanged. No evidence-budget exception is selected. Reproduction plus correction is one slice: a confirmed defect does not wait behind optional cleanup. If a supported regression cannot establish the suspected failure, preserve the negative result and stop for a scoped disposition instead of making a speculative fix. A disproved premise may close without production code after its explanation is published; inability to reproduce alone does not establish that the premise is false.

A dispatch receives only this current slice, its listed source excerpts and referenced invariants. Audit history is linked, not appended to the contract. Same-child re-audit is allowed only while the accepted outcome, representation owner and one-PR boundary remain intact; changes to those boundaries return to handoff. This program creates no new public API, wire format, persisted schema, worker, queue or capacity budget.
