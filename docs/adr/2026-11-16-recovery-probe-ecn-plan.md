# Size-Recovery ECN Loss Evidence Implementation Plan

**Date:** 2026-11-16
**Status:** Accepted design; not yet implemented
**Track:** `N16-L` in the [November 16 correctness and architecture program](2026-11-16-architecture-correctness-program.md)
**Depends on:** nothing — L1 is independently startable
**Related:** [jumbo plan](2026-11-05-jumbo-packets-plan.md); [PR #1418](https://github.com/the-sarge/quic-go-fast/pull/1418)
**Normative scope:** Current outcome, boundaries, invariants, acceptance evidence, blockers and stop conditions
**Audit history:** [Source and slice audit](../audits/2026-11-16-architecture-handoff/README.md)

## Goal

Deliver the existing size-recovery loss verdict to the correct ECN authority while keeping cancellation and successful cleanup free of an invented loss verdict.

## Current shape (verified 2026-11-16)

[Fallback expiry](../../packet_size_recovery.go#L53) and [recheck expiry](../../packet_size_watch.go#L138) require both the owned deadline and a later small-packet ACK before declaring the padded probe lost. [Dedicated retirement](../../internal/ackhandler/mtu_reduction.go#L43) removes those packets without calling `reportECNLoss`; [ordinary loss detection](../../internal/ackhandler/sent_packet_handler.go#L1139) deliberately skips them. [Emission](../../packet_size_recovery.go#L129) can mark those probes with ECN.

Other calls to the same retirement function represent successful confirmation, phase cleanup or expiry without later small delivery. Existing [ECN fallback coverage](../../jumbo_ecn_fallback_test.go#L16) first establishes capability, missing Testing/Unknown loss evidence. A CE-only discovery receipt can leave testing active while jumbo progression continues; this source-supported overlap still requires an executed regression.

## Decision

Replace the caller-facing retention boolean with two named semantic operations in `internal/ackhandler`: cancellation/terminal retirement drops retained size-confirmation receipts without an ECN-loss verdict; loss-qualified retirement retains bounded late-ACK receipts and calls existing `reportECNLoss`. Both use one recovery-owned traversal. Names are illustrative: `RetireMTURecoveryProbes` and `DeclareMTURecoveryProbesLost`.

The two deadline-plus-later-ACK callers choose the loss-qualified operation. Successful confirmation, successful-delivery phase cleanup, no-verdict expiry and final cleanup use cancellation/terminal retirement. Keep relative flight subtraction, retained ACK carrier handling, congestion-evidence disposal, local retirement, history removal and timer updates unless the regression demonstrates a required ordering adjustment. The connection owns the verdict; recovery owns its application; existing local-first/BBR/Reno dispatch owns ECN authority.

**Owner's design:** adopted: recovery exposes the complete semantic operation instead of requiring callers to correlate receipt retention with a separate ECN call. No durable state, worker, queue or new policy is added.

**Rejected alternatives (do not do this):** treat `keepForACK` as an implicit second meaning “loss,” or add independent retention/loss booleans; both leave a correlation obligation with callers, `none: rejected on merit`. A typed two-value disposition is viable but adds a type/value contract with no present need; revisit if another real semantic disposition is accepted. Direct validator calls in connection code duplicate existing dispatch; `none: rejected on merit`. A general packet-exit module exceeds this verdict seam; revisit only under a separately accepted retirement contract.

**Non-goals:** ECN policy changes, D5 reconsideration, congestion-loss credit, new frame-loss callbacks, general PTO/disposal unification, recovery scheduling, native performance or release qualification.

## Slice graph

| Slice | Disposition | Delivers | Blocked by | Temporary seam |
|---|---|---|---|---|
| L1 | new | Reachable ECN-testing loss regression and verdict-specific retirement | None | None |

## Implementation slices

### L1 — Report ECN loss only for a qualified recovery-probe loss

**What it delivers:** one independently green reproduction-and-correction PR demonstrates a marked padded probe reaching the existing dedicated loss verdict while ECN is Testing/Unknown, then supplies the omitted loss evidence through the existing dispatcher.

**Existing-work disposition:** new slice. Preserve merged PR #1418 and its explicit D5 rejection; the [audit comparison](../audits/2026-11-16-architecture-handoff/README.md#precise-owner-comparison) distinguishes the old PTO owner from this dedicated verdict owner. No unmerged work is a baseline.

**Single owner after merge:** connection phase logic decides deadline/later-ACK loss; recovery owns probe retirement; `reportECNLoss` selects local/BBR/Reno authority. Cancellation never manufactures a connection verdict.

**Authority completeness / transitional seams:** no new persisted fact or duplicated representation. Both named operations and the two changed loss callers ship together. No temporary adapter or successor removal slice.

**Blast radius:** current path-zero jumbo fallback/recheck, retained late ACK confirmation, bytes in flight, local transmission evidence and ECN state. Unknown versus Failed is a validation-state distinction; both send Not-ECT, so no unsafe continued marking is asserted. Preserve public/wire formats, congestion policy, local outcome authority and dependencies. No untraced effect is accepted.

**Artifact classification:** verdict integration is shipped behavior/required accounting enforcement; focused tests are verification aids; current plans and evidence receipts are metadata. No maintained harness approval is requested.

**Representation contract:** admitted ACK facts, current-generation 1-RTT dedicated size probes and existing ordinary/local registration evidence. Connection probe/phase types own the verdict; recovery owns packet classification; existing ECN validators own evidence interpretation. Guarantee is example-level regression plus enumerated preservation, not exhaustive protocol/timing proof.

**Contract closure:** not triggered. Two explicit synchronous verdict entrypoints and distinct cancellation states fit ordinary focused tests. The accepted contract does not require a universal protocol or concurrency census.

**TDD and evidence budget:** first establish the production-trigger overlap without forcing tracker state. Reuse real emission/registration and ECN feedback; standard-ceiling explicit InitialPacketSize plus early jumbo CE-only discovery and refusal is a source-supported starting trace, not already-run evidence. Then cover one fallback loss verdict, one recheck loss verdict, no-later-small-ACK cancellation, successful confirmation/cleanup, duplicate retirement with late ACK, and a compact Reno/BBR validator outcome table. Reuse existing local pending/unsubmitted/uncertain dispatcher coverage rather than cross-product every phase/controller/outcome. Preserve no immediate congestion-loss credit and existing bounded ACK receipts. No guard mutation, new native harness, timing repetition or platform campaign.

**Test seams:** [deadline versus later ACK](../../jumbo_fallback_test.go#L520), [late probe ACK](../../jumbo_fallback_test.go#L583), [BBR retirement](../../jumbo_fallback_test.go#L693), `jumbo_ecn_fallback_test.go`, `internal/ackhandler/mtu_reduction_test.go` and `ecn_pto_test.go`. The full-pair refusal fixture lacks ECN capability and waits for complete discovery, so it cannot establish the overlap unchanged. A recovery test can prove missing notification, but the root production-transition case must establish reachability.

**Dispatch context budget:** at most 16k input tokens: L1; `mtu_reduction.go`; the three `packet_size_{recovery,watch,fallback}.go` callers; `reportECNLoss`, ordinary exclusion and PTO excerpts; ECN testing/loss methods; named tests; and the narrow prior PR #1418 disposition/diff. Do not load the complete jumbo campaign or sampler history.

**Slice decision audit:** reproduction and repair belong in one green PR; splitting leaves an incomplete outcome, reject on merit. Merging with E1 or general retirement mixes distinct invariants/owners, reject on merit. No blocking edge is needed: current loss verdict, dispatcher and registration APIs already ship.

**Stop conditions:** legal production transitions cannot reproduce the Testing/Unknown overlap after verifying fixture assumptions; required correction changes reset policy, native authority or a wider retirement family; or cancellation cannot be distinguished at the current owner. Do not fix a forced impossible ECN state or report loss unconditionally.

## Acceptance criteria

- An actual production-transition regression demonstrates missing testing-loss evidence on unchanged source and passes after correction.
- The existing fallback and recheck loss verdicts deliver one ECN-loss fact per retired eligible probe through the existing authority dispatcher.
- Successful/no-verdict cancellation does not acquire loss semantics; retained ACK confirmation, flight, local outcome and congestion accounting remain consistent.

“One” is scoped to the selected registered-probe identities and history-removal owner. Duplicate/late-ACK and cancellation controls terminate representative evidence; no universal loss-detection claim is made.

## Validation gates

Run the new overlap regression red/green; `go test ./internal/ackhandler -run 'Test(MTU|ECNPTO|ECNOrdinaryLoss|LocalECNPTO)'`; `go test . -run '^TestJumbo'`; `go test ./internal/ackhandler .`; `go vet ./internal/ackhandler .`; and `go mod tidy -diff`. Existing hosted checks remain applicable. No native qualification or performance inventory is added.

## Operating discipline

The shared [review-loop baseline](https://github.com/the-sarge/skills/blob/main/_shared/REVIEW-LOOP.md) and [contract-closure baseline](https://github.com/the-sarge/skills/blob/main/_shared/CONTRACT-CLOSURE.md) govern, composed with this repository's [execution overlay](../REVIEW-LOOP.md). There is no repository contract-closure overlay. Use the shared baselines directly; do not copy or strengthen them. The [design-cost reference](https://github.com/the-sarge/skills/blob/main/_shared/DESIGN-COST.md) governs alternative comparisons. Use the root [glossary](../../GLOSSARY.md), [maintained-code conventions](../agents/conventions.md), and existing ADRs.

For each intended PR, use the accepted focused evidence below, one fully briefed initial review and at most one fresh replacement after accepted fixes, exact-head local certification, applicable same-head hosted checks, squash merge, then the post-merge development journal and pointer-based GitHub/OmniFocus reconciliation. The shared finding dispositions and precise-invariant-and-owner approach stops apply to review and verification. Diagnose failures before rerunning. The repository has no `task preflight`, `ci.yml` or `ci-*` gate; do not invent one. Implementation PRs also owe the existing ready-only independent-peer check. Documentation-only evidence PRs use the documented docs path.

Tests are verification aids, not newly approved maintained verification products. Existing focused tests and normal CI retain their existing role; no new analyzer, harness service, platform campaign, mutation campaign or release qualification is approved. The finite inventory below applies to new targeted evidence; existing affected-package and hosted suites are unchanged. No evidence-budget exception is selected. Reproduction plus correction is one slice: a confirmed defect does not wait behind optional cleanup. If a supported regression cannot establish the suspected failure, preserve the negative result and stop for a scoped disposition instead of making a speculative fix. A disproved premise may close without production code after its explanation is published; inability to reproduce alone does not establish that the premise is false.

A dispatch receives only this current slice, its listed source excerpts and referenced invariants. Audit history is linked, not appended to the contract. Same-child re-audit is allowed only while the accepted outcome, representation owner and one-PR boundary remain intact; changes to those boundaries return to handoff. This program creates no new public API, wire format, persisted schema, worker, queue or capacity budget.
