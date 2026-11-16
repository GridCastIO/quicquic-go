# Path-Zero ACK Growth Implementation Plan

**Date:** 2026-11-16
**Status:** Accepted design; not yet implemented
**Track:** `N16-M` in the [November 16 correctness and architecture program](2026-11-16-architecture-correctness-program.md)
**Depends on:** nothing — M1 is independently startable
**Related:** [packet-size plan](2026-11-05-jumbo-packets-plan.md); [A20 packet-size disposition](2026-10-20-architecture-decisions.md)
**Normative scope:** Current outcome, boundaries, invariants, acceptance evidence, blockers and stop conditions
**Audit history:** [Source and slice audit](../audits/2026-11-16-architecture-handoff/README.md)

## Goal

Apply path zero's ACK-driven MTU growth to its congestion accounting and first-path settled signal independently of an aggregate DATAGRAM admission estimate. Keep packet construction and aggregate admission ownership unchanged.

## Current shape (verified 2026-11-16)

[Route selection](../../multipath_admission.go#L237) can publish a surviving path's larger payload limit to `maxPayloadSizeEstimate` while zero is both suspect and [fencing](../../multipath_migration.go#L43). An aborted migration can preserve zero's original finder without restoring that shared value. [ACK handling](../../connection.go#L2587) currently gates zero's congestion update and settlement on growth above the shared estimate.

The finder itself grows in [its synchronous ACK callback](../../mtu_discoverer.go#L272). [Packet construction](../../connection.go#L3158) reads its current size directly. [BBR](../../packet_emission_bbr.go#L201) also refreshes its controller size during an ordinary opportunity. The bounded suspected defect is stale Reno accounting and missed ACK-completion settlement, not frozen actual packet size. [DATAGRAM admission](../../connection.go#L3393) also uses the eligible-path limit.

## Decision

Capture the existing finder pointer and its size immediately before the existing ReceivedAck/ReceivedPathAck call. At the existing final publication point, classify ACK growth only when the prior finder was nonnil, its identity is unchanged, and its current size strictly exceeds the captured size. On that own-finder growth, apply `max(mtu, config.initialPacketSize())` to recovery congestion accounting and settle when the finder is done.

Keep the existing max-only shared-estimate publication as a separate operation, regardless of whether own-finder growth occurred. Preserve the admitted-ACK/error handling, path bookkeeping, valid-1-RTT gate, handshake confirmation and final crypto receipt call in their existing order. Do not bypass the receipt call with a new early return.

[Handshake confirmation](../../connection.go#L1230) only starts an existing finder; parameter application initializes it earlier. [Constructors](../../connection.go#L364) already initialize accounting. [Handshake fallback replacement](../../connection.go#L3038) is outside this ACK seam. A same-pointer ACK-triggered [fallback confirmation](../../packet_size_fallback.go#L125) resets to the same current size and is not growth. Old-generation finder callbacks already decline. No durable “last applied MTU” field is necessary.

**Owner's design:** adopted: the connection's existing ACK operation observes its synchronous state transition. This removes the borrowed aggregate-cache invariant without adding a mirrored size or callback. The finder remains the MTU state owner; recovery remains the congestion accounting owner.

**Rejected alternatives (do not do this):** a new persistent applied-size mirror adds constructor/reset consistency obligations; revisit only if a supported asynchronous growth path makes a local snapshot insufficient. Comparing current finder size with itself after the ACK cannot detect growth; `none: rejected on merit`. Retaining the old cache gate with an OR condition preserves the incorrect dependency for fixture convenience; `none: rejected on merit`. A universal packet-size coordinator is outside scope; revisit only under a new accepted owner problem.

**Non-goals:** relaxing DATAGRAM admission, making aggregate limit publication synchronous with settlement, changing selected-path probing or recovery, changing BBR policy, and [issue #1412's broader admission investigation](https://github.com/the-sarge/quic-go-fast/issues/1412).

## Slice graph

| Slice | Disposition | Delivers | Blocked by | Temporary seam |
|---|---|---|---|---|
| M1 | new | Aborted-migration regression and own-finder ACK growth publication | None | None |

## Implementation slices

### M1 — Separate ACK growth from aggregate admission state

**What it delivers:** one independently green PR reproduces the suspect-zero, held migration fence, larger survivor, cancellation, recovery/reselection and MTU ACK sequence; then fixes accounting and settlement at the existing ACK owner.

**Existing-work disposition:** new slice; retain issue #1412 independently. No open M1 implementation exists. Existing constructors/fallback helpers and the completed jumbo work are the baseline; no unmerged candidate is assumed.

**Single owner after merge:** finder owns discovered size; connection ACK handling owns observed-growth publication/settlement; recovery owns congestion size; route selection owns aggregate path admission. No new owner is introduced.

**Authority completeness / transitional seams:** a stack-local pointer/size observation has no restart round trip or persistent authority. Initialization, replacement and same-size reset are explicitly not ACK growth. No mirrored state, adapter or removal successor.

**Blast radius:** root ACK handling across client/server, ordinary/multipath, Reno/BBR, handshake fallback and path-zero settlement. Preserve the initial-size congestion floor, generation rejection and independent aggregate cache. Public signal semantics are repaired within their existing first-path contract; wire/API/schema/security/dependencies remain unchanged. The pre-existing interval before normal route selection refreshes `pathPayloadLimit` is not expanded into a stronger immediate-publication guarantee. No untraced effect is accepted.

**Artifact classification:** ACK publication correction is shipped behavior and required lifecycle/accounting enforcement; regression and corrected causal fixtures are verification aids; plans and receipts are metadata.

**Representation contract:** an existing connection-owned path-zero finder whose identity remains unchanged across successful admitted ACK processing. Existing ACK admission and finder generation handlers own the representation. New/nil/replaced finder is excluded from inferred growth. The owner enforces this scoped predicate; representative tests do not prove all ACK encodings or callback schedules.

**Contract closure:** not triggered. The public lifecycle consequence is material, but one synchronous ACK transition and its identified initialization/reset boundaries fit focused tests; no general packet-size matrix is needed.

**TDD and evidence budget:** first reproduce the legal path sequence through existing migration/native fixtures with unequal MTUs and a held old submission. After zero recovers and is selected, ACK a real probe that concludes below the survivor's cached limit. Independently observe finder size, emitted packet length, Reno congestion size, DATAGRAM bound after normal selection and settled signal. Include a BBR preservation observation using its existing refresh, not another campaign. Preserve no-growth and nil/replaced-finder classification plus handshake initial-size floor. Existing [handshake growth coverage](../../connection_handshake_mtu_test.go#L167) simulates growth before handleAckFrame; move that mutation into ReceivedAck.DoAndReturn or a real handler so it reflects production causality. Likewise adjust only the zero-conclusion part of [legacy observation coverage](../../multipath_datagram_test.go#L243). One representative per distinct boundary; no guard mutations, timing-frequency tests or extra platform inventory.

**Dispatch context budget:** at most 16k input tokens: M1; handleAckFrame, constructor/parameter/fallback/confirmation excerpts in `connection.go`; finder ACK/Reset/done code; `selectRoute`, `zeroCarries`, cancellation/retirement/cutover and liveness excerpts; named migration, DATAGRAM and handshake-MTU tests; glossary settled-signal definition. Do not include complete historical packet-size plans.

**Slice decision audit:** separate detection/accounting/settlement PRs would leave one accepted ACK behavior incomplete; reject on merit. Merge with broader DATAGRAM admission or L1 changes different owners; reject on merit. No blocker is required because real finder, migration and ACK fixtures already ship.

**Stop conditions:** a supported finder replacement or upward reset occurs within the synchronous ACK/path-bookkeeping/confirmation seam; the reproduction requires impossible state edits; a safe correction needs durable mirrored state or stronger aggregate publication; or the supposed failure is not reproduced after verifying the fixture. Stop for a precise disposition, not a speculative helper.

## Acceptance criteria

- A supported aborted-migration sequence reproduces skipped own-growth accounting or settlement on unchanged source and passes after the correction.
- Current own-finder ACK growth applies the existing congestion floor and completion signal independently of the shared cache.
- No-growth/initialization/replacement cases do not become false growth; aggregate admission and packet construction retain their existing owners and bounds.
- Existing floor and legacy-observation tests model growth inside the ACK operation rather than preapplying the result.

The declared same-finder domain and owner enforce the growth predicate; the finite cases above terminate evidence. No stronger immediate aggregate-publication or universal callback guarantee is claimed.

## Validation gates

Run the proposed focused `TestPathZeroMTUGrowthAfterAbortedMigration` red/green, then the existing tests matching `TestHandshakeMTUFallback|TestPathDatagram|TestPathMTUDiscovery|TestPathMigrationCancelBeforeCommit|TestPathMigrationFenceBeforeCommit`, `go test .`, `go vet .` and `go mod tidy -diff`. Use synctest/owned fences rather than repeated wall-clock timing. Existing hosted checks govern platform boundaries.

## Operating discipline

The shared [review-loop baseline](https://github.com/the-sarge/skills/blob/main/_shared/REVIEW-LOOP.md) and [contract-closure baseline](https://github.com/the-sarge/skills/blob/main/_shared/CONTRACT-CLOSURE.md) govern, composed with this repository's [execution overlay](../REVIEW-LOOP.md). There is no repository contract-closure overlay. Use the shared baselines directly; do not copy or strengthen them. The [design-cost reference](https://github.com/the-sarge/skills/blob/main/_shared/DESIGN-COST.md) governs alternative comparisons. Use the root [glossary](../../GLOSSARY.md), [maintained-code conventions](../agents/conventions.md), and existing ADRs.

For each intended PR, use the accepted focused evidence below, one fully briefed initial review and at most one fresh replacement after accepted fixes, exact-head local certification, applicable same-head hosted checks, squash merge, then the post-merge development journal and pointer-based GitHub/OmniFocus reconciliation. The shared finding dispositions and precise-invariant-and-owner approach stops apply to review and verification. Diagnose failures before rerunning. The repository has no `task preflight`, `ci.yml` or `ci-*` gate; do not invent one. Implementation PRs also owe the existing ready-only independent-peer check. Documentation-only evidence PRs use the documented docs path.

Tests are verification aids, not newly approved maintained verification products. Existing focused tests and normal CI retain their existing role; no new analyzer, harness service, platform campaign, mutation campaign or release qualification is approved. The finite inventory below applies to new targeted evidence; existing affected-package and hosted suites are unchanged. No evidence-budget exception is selected. Reproduction plus correction is one slice: a confirmed defect does not wait behind optional cleanup. If a supported regression cannot establish the suspected failure, preserve the negative result and stop for a scoped disposition instead of making a speculative fix. A disproved premise may close without production code after its explanation is published; inability to reproduce alone does not establish that the premise is false.

A dispatch receives only this current slice, its listed source excerpts and referenced invariants. Audit history is linked, not appended to the contract. Same-child re-audit is allowed only while the accepted outcome, representation owner and one-PR boundary remain intact; changes to those boundaries return to handoff. This program creates no new public API, wire format, persisted schema, worker, queue or capacity budget.
