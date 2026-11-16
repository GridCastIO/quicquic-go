# Announcement Carrier Identity Implementation Plan

**Date:** 2026-11-16
**Status:** A1 complete; selected-carrier execution implemented
**Track:** `N16-A` in the [November 16 correctness and architecture program](2026-11-16-architecture-correctness-program.md)
**Depends on:** nothing — A1 is independently startable
**Related:** [ADR 0004](0004-packet-emission-ownership.md); [native endpoint plan](2026-10-24-multipath-endpoint-plan.md)
**Normative scope:** Current outcome, boundaries, invariants, acceptance evidence, blockers and stop conditions
**Audit history:** [Source and slice audit](../audits/2026-11-16-architecture-handoff/README.md)

## Goal

Keep an announcement's selected member, carrier, reserved local send bytes, pacing classification and packet construction associated through one synchronous attempt. Remove the repeated selection after BBR has reserved credit, without redesigning sending policy.

## Current shape (verified 2026-11-16)

[BBR path turns](../../packet_emission_bbr.go#L103) select a due member, derive its carrier MTU and reserve paced or exempt credit. [Announcement execution](../../packet_emission_path.go#L228) selects again. [Eligibility](../../multipath_admission.go#L375) consults [route usability](../../native_ordinary.go#L389) and [endpoint quarantine](../../native_ordinary.go#L685); [endpoint.do](../../native_endpoint.go#L479) advances independently owned endpoint state before and after a query. Registry confinement does not make the two selections equivalent.

[Handoff](../../packet_emission_bbr.go#L17) charges the reservation's grantor; [reservation resizing](../../local_send_credit.go#L126) rejects an actual length above reserved bytes. A second due carrier can therefore spend the first carrier's allowance. The resize panic is a latent guard consequence, not a reachable announcement reproduction at this source: [ordered selection](../../multipath_migration.go#L393) makes a replacement higher/nonzero, [cutover](../../multipath_migration.go#L364) resets its finder to 1,200 bytes before setting the obligation, and the current-tuple ACK that could grow it [clears announcing](../../multipath_policy.go#L124) before another send. The first reservation is at least 1,200 bytes. Returning no second member is already safe. This is a synchronized timing/selection defect hypothesis, not an unsynchronized Go data race or an executed reproduction.

## Decision

The private announcement execution operation accepts the already selected member. BBR passes its original selection; Reno's existing `announcePath` entry performs its one lookup and passes that result. Resolve the route from that member in the connection context, preserving the current credit-before-route-switch/native-preparation sequence. There is no second global selection under a retained reservation. Selection does not authorize bypassing later live construction/admission refusal.

Keep paced payload versus exempt PING/ACK choice, carrier size, retry/backoff, successful carrier selection, native-refusal restoration, packing-error behavior, immediate recovery registration, actual handoff and unused-credit release unchanged. ACK carriage and steering retain their different route endings. Existing registry, packer, recovery and native owners do their existing work.

**Owner's design:** adopted: a concrete operation in the existing packet-emission owner consumes its caller's selected member. No side channel or contained auxiliary state is added. A complete choose/reserve/execute command is an acceptable scoped re-audit only if it removes further obligations without changing chronology; it is not required by A1.

**Rejected alternatives (do not do this):** reselect another member after reservation, or preserve the first selection while bypassing live admission: both break the accepted invariant; revisit `none: rejected on merit`. A generic route transaction, caller-owned attempt ticket, lock around endpoint lifetime or new fault-injection runtime hook adds obligations; revisit only if a separately accepted real consumer requires such a contract. Common turn consolidation is excluded; revisit on a real shared ordering change.

**Non-goals:** throughput improvement, native-readiness redesign, ACK/steering unification, controller policy changes, completion fencing changes, new public API or production synchronization hook.

## Slice graph

| Slice | Disposition | Delivers | Blocked by | Temporary seam |
|---|---|---|---|---|
| A1 | complete | Legal endpoint-transition regression and original-carrier execution | None | None |

## Implementation slices

### A1 — Bind announcement execution to its original carrier

**What it delivers:** one independently green PR reproduces the legal endpoint-health transition on unchanged production source, then removes substituted-carrier accounting through the existing real emission entrypoint.

**Existing-work disposition:** new slice. No open implementation exists for D2. The unselected scalar-deadline [PR #1295](https://github.com/the-sarge/quic-go-fast/pull/1295) is retained outside this slice and is not a baseline.

**Single owner after merge:** packet emission owns selected-carrier/reservation association; the endpoint owns its live health and admission; registry owns announcement obligation/backoff; recovery owns registration. No cross-context policy handoff is added.

**Authority completeness / transitional seams:** no persisted fact or new long-lived representation. The member is already connection-owned and stable during this synchronous call. No duplicate representation, adapter or double-open lifetime is introduced; no removal successor is needed.

**Blast radius:** changes both private Reno and BBR announcement call sites but only BBR previously reserved before execution. Trace handoff credit, carrier MTU, native failure, route restoration, supply observation and registration timing. Preserve public/wire/security behavior and package dependencies. No measured speedup is claimed. No untraced effect is accepted.

**Artifact classification:** the binding change is shipped behavior and required accounting enforcement; focused tests are verification aids; receipts and issue/task pointers are process metadata. No blocking maintained verification aid is introduced.

**Representation contract:** current typed path members, route IDs, reservations and registered 1-RTT packets in one connection execution context, with endpoint health changing through its existing synchronized owner. These existing owners are authoritative. The scoped association invariant is enforced by construction; evidence is example-level, not a proof of every possible interleaving.

**Contract closure:** not triggered. Wrong-carrier accounting consequences are material, but the accepted invariant crosses one synchronous selection-to-execution seam whose distinct cases fit ordinary focused tests. No new closure or mutation harness is needed.

**TDD and evidence budget:** write a deterministic regression through real `triggerSending`, real packer/recovery and native sender. An existing `emissionPolicy.maxPacketSize` wrapper can fault the actual first endpoint after the initial choice and before reservation/execution; see [the existing wrapper pattern](../../native_software_natural_turn_test.go#L19). Do not mutate connection-owned registry entries concurrently. Two new cases: (1) a red/green regression with two due routes, where the first endpoint fails and the substitute packet fits the first reservation; the original exhibits wrong-carrier charging, while the correction retains the first attempt and later sends the second with its own credit; (2) a green/green characterization with no alternative due route, preserving no cross-member fallback or retained reservation and no false discharge of the announcement obligation. No oversize/panic fixture is required: it is unreachable under the current announcement/PMTU lifecycle. Do not force finder size to manufacture it; revisit only if a legal lifecycle change allows a larger substitute while still owing an announcement. Existing healthy-announcement tests preserve ordinary charging. Require the transition actually to fire; a misarranged fixture is not evidence against the source trace. Preserve existing pacing/control fallback, refusal and supply tests. Add only missing refusal/error-cleanup assertions exposed by the changed operation. One representative per listed behavior; zero guard mutations, timing repetitions, new platform inventory or operational campaign.

**Dispatch context budget:** at most 14k input tokens: A1, ADR 0004, `packet_emission_bbr.go` path-turn/handoff excerpts, `packet_emission_path.go` announcement/route methods, `local_send_credit.go`, the eligibility/endpoint query excerpts cited above, `multipath_bbr_test.go` announcement/ACK/supply tests, and the relevant native fixture wrapper. No complete endpoint history or old report versions.

**Slice decision audit:** splitting reproduction and fix creates no coherent green intermediate product; reject on merit. Merging with E1 or native readiness mixes different owners; reject on merit. A1 has no blocker because its inputs are already merged production owners. Full announcement restructuring may be evaluated only against this same outcome and one-PR boundary.

**Stop conditions:** failure requires unsupported registry mutation; the selected member/route can legally change within this synchronous call; a safe correction needs a new execution context, endpoint lifetime guarantee or different deadline policy; or supported reproduction does not establish the premise. Stop rather than manufacture a timing failure.

## Acceptance criteria

- The two-due-route wrong-carrier regression fails on unchanged base and passes after the binding correction; the no-alternative control passes before and after.
- Within the typed domain above, execution cannot substitute another carrier while retaining the original reservation; live refusal remains authoritative.
- Existing healthy/credit-refused/native-refused announcement behavior, registration timing and controller-specific continuation remain unchanged.

The second criterion is enforced by the single chosen-member execution seam; the finite cases above provide representative evidence, not exhaustive scheduling proof.

## Validation gates

Run the new focused regression red/green; then `go test . -run 'TestBBRPath|TestPathMigrationExhaustedCredit|TestPathReliableAdmissionProbeUnderSendAck' -count=1`, `go test .`, `go vet .`, `go mod tidy -diff`, and one focused race run of the new endpoint-transition test because it exercises a concurrent endpoint boundary. Use existing supported native fixtures; no extra platform matrix. Apply the repository's exact-head and hosted checks.

## Operating discipline

The shared [review-loop baseline](https://github.com/the-sarge/skills/blob/main/_shared/REVIEW-LOOP.md) and [contract-closure baseline](https://github.com/the-sarge/skills/blob/main/_shared/CONTRACT-CLOSURE.md) govern, composed with this repository's [execution overlay](../REVIEW-LOOP.md). There is no repository contract-closure overlay. Use the shared baselines directly; do not copy or strengthen them. The [design-cost reference](https://github.com/the-sarge/skills/blob/main/_shared/DESIGN-COST.md) governs alternative comparisons. Use the root [glossary](../../GLOSSARY.md), [maintained-code conventions](../agents/conventions.md), and existing ADRs.

For each intended PR, use the accepted focused evidence below, one fully briefed initial review and at most one fresh replacement after accepted fixes, exact-head local certification, applicable same-head hosted checks, squash merge, then the post-merge development journal and pointer-based GitHub/OmniFocus reconciliation. The shared finding dispositions and precise-invariant-and-owner approach stops apply to review and verification. Diagnose failures before rerunning. The repository has no `task preflight`, `ci.yml` or `ci-*` gate; do not invent one. Implementation PRs also owe the existing ready-only independent-peer check. Documentation-only evidence PRs use the documented docs path.

Tests are verification aids, not newly approved maintained verification products. Existing focused tests and normal CI retain their existing role; no new analyzer, harness service, platform campaign, mutation campaign or release qualification is approved. The finite inventory below applies to new targeted evidence; existing affected-package and hosted suites are unchanged. No evidence-budget exception is selected. Reproduction plus correction is one slice: a confirmed defect does not wait behind optional cleanup. If a supported regression cannot establish the suspected failure, preserve the negative result and stop for a scoped disposition instead of making a speculative fix. A disproved premise may close without production code after its explanation is published; inability to reproduce alone does not establish that the premise is false.

A dispatch receives only this current slice, its listed source excerpts and referenced invariants. Audit history is linked, not appended to the contract. Same-child re-audit is allowed only while the accepted outcome, representation owner and one-PR boundary remain intact; changes to those boundaries return to handoff. This program creates no new public API, wire format, persisted schema, worker, queue or capacity budget.
