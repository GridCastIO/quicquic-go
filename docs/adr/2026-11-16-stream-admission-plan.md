# STREAM Admission Inspection Implementation Plan

**Date:** 2026-11-16
**Status:** S1 complete with SUPPORT; S2 ready for its bounded implementation
**Track:** `N16-S` in the [November 16 program](2026-11-16-architecture-correctness-program.md)
**Depends on:** S1 has no blocker; S2 requires S1's published SUPPORT decision
**Related:** [ADR 0005](0005-incoming-packet-lifetime.md); [jumbo F11/F12](2026-11-05-jumbo-packets-plan.md); [A20](2026-10-20-architecture-decisions.md)
**Normative scope:** Current outcome, boundaries, invariants, acceptance evidence, blockers and stop conditions
**Audit history:** [Source and slice audit](../audits/2026-11-16-architecture-handoff/README.md)

## Goal

Determine whether the measured cost of temporary STREAM materialization during packet admission justifies the bounded change below. If it does, let the existing wire parser validate and skip a STREAM frame without acquiring payload ownership. Ordinary parsing remains owning and shares authoritative validation.

## Current shape (verified 2026-11-16)

[Admission](../../datagram_packet_admission.go#L14) requires DATAGRAMs enabled, a configured ceiling above 1,452 bytes, 0/1-RTT and plaintext frame bytes greater than remaining DATAGRAM queue slots (`1024 - receiveQueueLen`). Ordinary-sized and STREAM-only packets can scan; payloads below 1,024 also can when the queue is occupied. The gate is not UDP length or negotiated jumbo-active status.

[The STREAM arm](../../datagram_packet_admission.go#L39) calls the owning parser and immediately PutBack. [STREAM parsing](../../internal/wire/stream_frame.go#L26) validates, acquires storage and copies data. This establishes removable work but no measured throughput benefit. The full admission scan must finish before its capacity verdict, including malformed tails after overcount.

[Existing BenchmarkParseStreamFrame](../../internal/wire/frame_parser_test.go#L782) uses the free parser through its helper, not a configured jumbo `FrameParser`. It is ordinary-parser preservation context, not admission cost evidence. [F11](2026-11-05-jumbo-packets-plan.md#f11--pack-several-short-datagrams-into-a-jumbo-packet-conditional) already records STREAM-only cost; F12 governs exact-candidate consumer/release qualification and is not this measurement's harness or blocker.

## Decision

S1 is a finite local sizing decision before committing to optional runtime work. It produces SUPPORT, DEFER/INCONCLUSIVE, or a scoped stop. SUPPORT permits S2's already bounded design; it does not claim a candidate speedup. DEFER/INCONCLUSIVE completes S1 and closes S2 as not selected. No repeated search for a favorable number is implied.

S2 adds a narrow `FrameParser.SkipStreamFrame(typ, body, version) (consumed, error)`. The existing STREAM parser privately owns one scalar layout/validation decoder. Owning parse uses its scalar result to acquire/copy storage; skip returns only consumed body length or the same typed error. No frame, payload slice, callback, mode object or packet-wide view escapes. The caller replaces only admission's STREAM parse/PutBack arm. Type/encryption checks and ordinary inline dispatch remain unchanged.

Preserve truncation normalization, zero consumed bytes on failure, explicit/implicit length, configured maximum, the effective 8,972-byte pool-capacity rejection, offset overflow, and error code/frame type/message. Preserve rejection order: truncation/available payload and configured/storage limits precede offset overflow. A configured limit above the pool tier does not authorize acceptance the materializer rejects. Share the existing supported-capacity rule without acquiring storage merely to validate it. Removing preflight copy does not remove the second traversal or all allocation.

**Owner's design:** adopted conditionally: the existing wire representation owner provides the length-only operation. Private scalar validation is shared; callers receive no payload-lifetime obligation. Sharing affects ordinary parser code generation, so that exposure is part of S2.

**Rejected alternatives (do not do this):** duplicate hand-written STREAM grammar, packet-wide walker or a borrowed-frame view adds validation/lifetime obligations; revisit only for a separately accepted real consumer needing that representation. Early return after queue overcount changes malformed-tail error precedence; `none: rejected on merit`. A validation-only precursor PR exposes ordinary parsing without its consumer; `none: rejected on merit`. Combining S1/S2 before the decision defeats accepted measurement-first selection; `none: rejected on merit`. A new performance threshold, operational campaign or F12 dependency is not selected; revisit only under an approved operational question.

**Non-goals:** removing the complete scan, optimizing DATAGRAM/ACK/control parsing, changing storage ownership, normal dispatch, public API, wire grammar, queue bounds, native output, F12 release, or proving end-to-end speedup from a microbenchmark.

## Slice graph

| Slice | Disposition | Delivers | Blocked by | Temporary seam |
|---|---|---|---|---|
| S1 | complete (#1438), SUPPORT | [Baseline observations and terminal selection receipt](../audits/2026-11-16-stream-admission-cost/README.md) | None | Disposable measurement source removed |
| S2 | ready (#1439) | Shared validation plus real admission skip consumer | S1 SUPPORT published in this revision | None; decoder and consumer ship together |

## Implementation slices

### S1 — Measure current admission cost and settle selection

**Current state:** complete with [SUPPORT receipt](../audits/2026-11-16-stream-admission-cost/README.md); S2 #1439 is ready when this revision reaches the default branch.

**What it delivers:** one independently green documentation/evidence PR publishes exact source/toolchain/host/settings, raw local observations, archived disposable harness text, interpretation and a terminal decision. No runtime code or maintained benchmark is delivered.

**Existing-work disposition:** new slice. Keep [F12 (#1226)](https://github.com/the-sarge/quic-go-fast/issues/1226), its qualification and existing frozen evidence separate. Do not reopen [PR #1295](https://github.com/the-sarge/quic-go-fast/pull/1295) or reset any spent comparison inventory.

**Single owner / authority completeness:** existing admission and parser own runtime behavior; the S1 receipt owns this scoped work-selection decision. No persisted runtime authority is introduced. The temporary benchmark calls real operations and does not contain a candidate parser.

**Transitional-seam budget:** one disposable root-package benchmark exists only during the experiment, then is removed from compiled source before commit. Its source may be archived as text under the S1 receipt directory for interpretation, with no ongoing execution or maintenance obligation. S1 itself removes the seam; no successor is needed.

**Blast radius:** measurement and process metadata only. No behavior, schema, security, public interface or dependency change. Host load, CPU/core placement, toolchain and fixture representativeness limit interpretation; disclose them rather than inferring performance-core contention from efficiency-core activity.

**Artifact classification:** benchmark code is a disposable verification aid, archived source/raw output are frozen experiment evidence, decision receipt and plan/task state are process metadata. No blocking maintained verification aid is approved. The S1→S2 edge depends on the accepted decision receipt, not on turning the harness into a product or recursively certifying it.

**Representation contract:** legal locally constructed STREAM/DATAGRAM fixtures passed through real FrameParser/Conn admission, with parser cap explicitly 8,972 and queue populated through existing operations. Wire parser and queue remain authoritative. Guarantee is example-level local cost observations only.

**Contract closure:** not triggered; this is a bounded sizing decision without runtime mutation or a universal representation claim.

**Finite evidence budget:** one invocation of each command below, one host/toolchain, `-count=1 -cpu=1 -benchtime=1s`; Go's adaptive benchmark iterations are the measurement mechanism, not repeated operational trials. Four fixtures: (a) 1,200-byte STREAM, empty queue; (b) 8,900-byte STREAM, empty queue; (c) 64-byte STREAM below the pool threshold, full queue; (d) eight 1,099-byte DATAGRAMs, four queue slots free. All use 1-RTT, enabled DATAGRAMs and the configured ceiling. For the three STREAM cases, separately measure actual admission and current owning parse/PutBack. Record ns/op, B/op and allocs/op; do not subtract different paths and label the remainder validation cost. Construct fixtures before timing, consume results, and verify declared payload length, queue room, cap and admission verdict outside the timed loop.

**Commands (proposed temporary symbol):**

```sh
go test . -run '^$' -bench '^BenchmarkS1DatagramAdmissionCost$' -benchmem -benchtime=1s -count=1 -cpu=1
go test ./internal/wire -run '^$' -bench '^BenchmarkParseStreamFrame$' -benchmem -benchtime=1s -count=1 -cpu=1
```

**TDD / termination:** characterize the four fixture outcomes before timing; no failing production test is expected. SUPPORT requires usable observations, attributable current materialization cost at the intended seam and an explicit argument why its measured scale/exposure justifies this particular small change. It authorizes implementation, not a speedup claim. Immaterial cost, dominant work outside STREAM, or inconclusive/unusable timing ends DEFER/INCONCLUSIVE and closes S2 as not selected. Source drift, inability to exercise real admission without a broader harness, or an unexpected behavior/authority requirement is a stop for scoped re-audit. Diagnose tool failures; do not silently add repetitions, platforms or workloads. No confidence interval, fixed elapsed-hour budget or end-to-end assertion is made.

**Dispatch context budget:** at most 10k input tokens: S1, admission loop, queue setup/room methods, parser/pool selectors, benchmark helper and F11/F12/A20 excerpts. No complete connection/campaign history.

**Slice decision audit:** merge with S2 would bypass the chosen decision; reject on merit. Split the two observations/receipt would leave an unfinished decision with no useful separate outcome; reject on merit. No technical dependency on A1/E1/M1/L1 exists.

**Stop conditions:** the stated representation or fixture scope cannot be honored; evidence requires an unapproved maintained harness or operational campaign; or source change invalidates the selected seam. An inconclusive cost observation is a normal terminal outcome, not a reason to keep running.

### S2 — Skip STREAM materialization through shared validation

**What it delivers:** one independently green runtime-and-tests PR adds the shared private validator and length/error-only skip operation, then replaces admission's single owning STREAM call. It may start only after S1 is merged with SUPPORT and the receipt is included in dispatch context.

**Existing-work disposition:** new conditional slice; no implementation exists. Do not mark ready from S1 issue closure alone. A published DEFER/INCONCLUSIVE disposition closes S2 without code.

**Single owner / authority completeness:** existing wire parser owns STREAM representation and storage-capacity validity; admission owns full-packet count/refusal; normal dispatch and stream/queue owners retain data. No new persisted authority, payload lifetime or duplicate grammar. Private decoder and consumer ship together.

**Transitional-seam budget:** none. No unused public view, compatibility adapter or future storage migration.

**Blast radius:** qualifying admission plus ordinary STREAM parsing through shared validation; function boundaries, inlining and allocations can change. Preserve all existing error ordering, configured/default caps, effective storage tier, caller ownership and default admission bypass. Public/wire/security/dependencies stay unchanged; no untraced ordinary-path exemption is accepted.

**Artifact classification / representation:** parser/consumer changes are shipped behavior; authoritative shared validation is required enforcement; focused tests and the reused disposable measurement are verification aids; receipt and raw comparison are metadata/frozen evidence. Supported domain is the current parser's accepted STREAM grammar and existing encryption/type checks, not a new hand-written external scanner. The existing parser owns representation; the broad acceptance-preservation intent is backed by named representative cases, not exhaustive grammar proof.

**Contract closure:** not triggered. The narrow synchronous parser/admission operation is reasonably covered by focused semantic cases and existing authoritative parser tests; no protocol-wide census or mutation campaign is warranted.

**TDD and evidence budget:** proposed `TestFrameParserSkipStreamFrame` and `TestDatagramPacketAdmissionStreamPreservation` compare owning/skip consumed length and typed errors, with explicit expected outcomes so agreement cannot conceal a shared bug. One representative for: LEN with following frame; implicit LEN consuming rest; valid OFF/FIN/empty forms; truncated header/payload; default versus configured cap and cap above the 8,972 storage tier; offset overflow; combined truncation/cap/overflow precedence; STREAM-only with full DATAGRAM queue; overcount followed by malformed/forbidden tail; valid mixed frames. Reuse existing grammar/zero-allocation and pre-ACK whole-packet refusal tests. Preserve no STREAM delivery and no ACK on refused mixed input. Do not cross every varint spelling or add fuzz/mutation/platform campaigns.

**Performance evidence:** compare the same bounded S1 workloads and ordinary parser benchmark on baseline and candidate under comparable host/toolchain/settings, one invocation per command per source revision. A fresh matched baseline is justified here because S1's earlier environment may differ; it is not a repeat-until-pass inventory. Reuse S1's baseline if identities/conditions are actually comparable. Preserve the existing pooled STREAM allocation test without weakening its inputs. Report local ns/op/allocation differences and limits; do not infer end-to-end throughput. A demonstrated default allocation regression is fix-or-stop. If measured benefit is immaterial or outweighed by a common-path cost, do not merge the optimization; publish the disposition and close it as not selected. Inconclusive comparison is a terminal defer, not permission for more trials.

**Dispatch context budget:** at most 16k input tokens: S2, S1's compact receipt and archived harness, STREAM parser methods/storage selectors, admission loop, exact receive call sites and named tests. No full older plan versions or native pipeline context.

**Slice decision audit:** splitting validator from consumer creates an unused seam and exposes ordinary parsing before delivering the benefit; reject on merit. Merge with S1 defeats its decision edge; reject on merit. The sole blocker is genuine: the user-selected sizing decision must precede this optional implementation.

**Stop conditions:** shared authoritative validation cannot preserve the present verdict/error order/caps; a new borrowed lifetime or packet-wide walker is required; performance needs a different design or expanded campaign; or relevant source drift invalidates S1's decision.

## Acceptance criteria

- S1 publishes the declared finite observations and one terminal decision with honest limitations; no temporary benchmark remains compiled or becomes a maintained CI tool.
- S2 starts only from a published SUPPORT decision; otherwise it is closed/deferred without runtime changes.
- If implemented, admission receives validated consumed length/error without acquiring STREAM payload ownership, and normal parsing retains owning behavior through the same authoritative validation.
- The named error, size, full-scan/refusal and ordinary-parser allocation cases retain their specified outcomes; comparative performance evidence justifies retaining the optional change.

Universal words in these criteria apply only to the declared typed/parser domain and named owner operations. Finite representative cases and the explicit observation inventory terminate evidence; no universal scheduling, external-grammar or end-to-end performance proof is claimed.

## Validation gates

S1: fixture characterization, the two bounded benchmark commands, removal of compiled disposable source, raw receipt/source identity checks and the repository docs certification path.

S2: new focused tests red/green; existing STREAM grammar/error/allocation tests in `internal/wire`; `go test . -run 'TestDatagramPacketAdmissionStreamPreservation|TestJumboDatagramAdmissionBeforeAck'`; `go test . ./internal/wire`; `go vet . ./internal/wire`; `go mod tidy -diff`; the bounded matched measurement above; and existing exact-head hosted checks. Recheck actual existing test symbols rather than treating a nonmatching test regex as evidence.

## Operating discipline

The shared [review-loop baseline](https://github.com/the-sarge/skills/blob/main/_shared/REVIEW-LOOP.md) and [contract-closure baseline](https://github.com/the-sarge/skills/blob/main/_shared/CONTRACT-CLOSURE.md) govern, composed with this repository's [execution overlay](../REVIEW-LOOP.md). There is no repository contract-closure overlay. Use the shared baselines directly; do not copy or strengthen them. The [design-cost reference](https://github.com/the-sarge/skills/blob/main/_shared/DESIGN-COST.md) governs alternative comparisons. Use the root [glossary](../../GLOSSARY.md), [maintained-code conventions](../agents/conventions.md), and existing ADRs.

For each intended PR, use the accepted focused evidence below, one fully briefed initial review and at most one fresh replacement after accepted fixes, exact-head local certification, applicable same-head hosted checks, squash merge, then the post-merge development journal and pointer-based GitHub/OmniFocus reconciliation. The shared finding dispositions and precise-invariant-and-owner approach stops apply to review and verification. Diagnose failures before rerunning. The repository has no `task preflight`, `ci.yml` or `ci-*` gate; do not invent one. Implementation PRs also owe the existing ready-only independent-peer check. Documentation-only evidence PRs use the documented docs path.

Tests are verification aids, not newly approved maintained verification products. Existing focused tests and normal CI retain their existing role; no new analyzer, harness service, platform campaign, mutation campaign or release qualification is approved. The finite inventory below applies to new targeted evidence; existing affected-package and hosted suites are unchanged. No evidence-budget exception is selected. Reproduction plus correction is one slice: a confirmed defect does not wait behind optional cleanup. If a supported regression cannot establish the suspected failure, preserve the negative result and stop for a scoped disposition instead of making a speculative fix. A disproved premise may close without production code after its explanation is published; inability to reproduce alone does not establish that the premise is false.

A dispatch receives only this current slice, its listed source excerpts and referenced invariants. Audit history is linked, not appended to the contract. Same-child re-audit is allowed only while the accepted outcome, representation owner and one-PR boundary remain intact; changes to those boundaries return to handoff. This program creates no new public API, wire format, persisted schema, worker, queue or capacity budget.
