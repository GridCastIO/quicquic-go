# November 16 Architecture Handoff Audit

This file records source assessment and slice-design evidence, not runtime validation or a second normative contract. The [program index](../../adr/2026-11-16-architecture-correctness-program.md) and current plans own accepted work.

## Source and authority

Source assessment is pinned to `ad76ab772160a9eabf88d06c508213b94ce37bd8`, fetched from remote main on November 16, 2026. The user delegated technical grilling decisions, then explicitly invoked `$architecture-handoff` for OmniFocus parent `eLqOZpf2G8F`. The parent had no children or note. The handoff does not authorize implementation dispatch.

The review progressed from candidate ranking to concrete designs, then compared Fable's source hypotheses. The final decision replaces the original “deterministic announcement lookup” claim, prioritizes specific correctness outcomes, and measures the optional STREAM optimization before implementation. These facts and exclusions are now in the current plans and [decision register](../../adr/2026-11-16-architecture-decisions.md); temporary HTML reports are not needed as dispatch context.

Independent source/planning auditors covered announcement selection, Reno release, path-zero growth, dedicated loss retirement and STREAM sizing. They made no code edits and executed no tests or benchmarks. Handoff drafting likewise changes documentation only. Existing tests named in plans were inspected, not claimed to pass.

## Existing-work disposition

The open-issue and open-PR inventory was fetched before drafting. No open implementation was found for A1, E1, M1, L1 or S1/S2. Bodies/comments were read for the relevant nearby issues and PRs.

| Existing work | Disposition and evidence |
|---|---|
| [PR #1295 — scalar deadline arming](https://github.com/the-sarge/quic-go-fast/pull/1295) | Retain unselected outside N16. Its body records terminal INCONCLUSIVE comparison and no integration authorization. The inspected diff changes request-I/O preparation and its own endpoint-plan contract; N16 depends only on merged endpoint health/completion behavior. Its source is not an established N16 baseline. |
| [Issue #1285 — ordinary STREAM latency](https://github.com/the-sarge/quic-go-fast/issues/1285) | Closed after owner acceptance of the measured tradeoff; no claim the draft PR shipped. Preserve its frozen evidence and spent inventory. |
| [Issue #1412 — DATAGRAM admission limits](https://github.com/the-sarge/quic-go-fast/issues/1412) | Retain separate. It investigates conservative admission versus packing; M1 repairs own-growth accounting/settlement without relaxing admission. |
| [Jumbo parent #1215](https://github.com/the-sarge/quic-go-fast/issues/1215) and [F12 #1226](https://github.com/the-sarge/quic-go-fast/issues/1226) | Retain existing program. F1–F11 shipped; F12 awaits its own exact-candidate qualification/release conditions. No N16 dependency or rebaseline is inferred. |
| [PR #1418 — ECN boundary and PTO accounting](https://github.com/the-sarge/quic-go-fast/pull/1418) | Retain merged behavior at `d5f55d73eca45c9391272173dc567d93f994a6b6`. Its body, approved contract and disposition establish the bounded owners below. D5 was already rejected; no new D5 project is warranted. |

## Precise owner comparison

The comparison below prevents treating a shared “ECN” or “retirement” topic as a repeated approach failure.

| Finding/work | Exact invariant | Central enforcement seam | Semantic class | Why it does or does not belong to the earlier accepted family |
|---|---|---|---|---|
| PR #1418 final test boundary | The final registered testing packet is included in its marking range. | `ecnMarking` range end | Last testing-packet classification | Range classification; does not own local current-reservation release or dedicated MTU retirement. |
| PR #1418 PTO loss | PTO-retired eligible 1-RTT packets forward their loss fact to the proper ECN authority. | `QueueProbePacketAt → reportECNLoss` | Ordinary/local PTO retirement | Existing dispatch owns validator selection, but the accepted PTO caller family did not own the separate connection deadline/later-ACK verdict. |
| E1 / D3 | Only a current testing registration can release the current Reno testing allowance. | Validator-owned release called by `localECNEvidence.releaseTest` | Late Unsubmitted before/within/after the new interval | Different invariant and mutation owner from marking-range and loss dispatch. Historical ACK/loss semantics are not silently absorbed. |
| L1 / D4 | Dedicated size-recovery loss-qualified retirement reports ECN loss; cancellation does not. | Named recovery retirement operation selected by connection verdict | Fallback/recheck loss versus cancellation/success | New integration at a different verdict/retirement owner. A common downstream dispatcher is insufficient to call it a repeated root. |
| D5 | Unusable-path rescheduling intentionally follows existing PTO extraction policy, including ECN loss. | `rescheduleUnusable → QueueProbePacketAt` | Failure/suspicion rescheduling | Already considered and rejected in [PR #1418's C-001 disposition](https://github.com/the-sarge/quic-go-fast/pull/1418#issuecomment-6904313749). Preserve that closed decision. |

## Slice decision audit

Draft graph: A1, E1, M1, L1 and S1 have no blockers; S2 is conditional on S1's SUPPORT decision. Priority is A1/E1, then M1/L1, then S1. No convenience-only cross-track edge is accepted.

| Slice | Single owner and bounded outcome | Split/merge judgment | Context and evidence boundary |
|---|---|---|---|
| A1 | Existing emission executor binds the selected member to its reservation. | Regression plus fix is one coherent green PR; merging native readiness or turn ordering adds a different contract. | Two production call sites; three meaningful endpoint-transition scenarios plus existing preservation coverage. |
| E1 | Reno tracker owns current testing-slot release using existing PN bounds. | Release-only guard is the bounded accepted invariant; receipt/loss semantics are separate. No new cohort field or tests-only predecessor. | Three stale-release boundary cases, current-release preservation and existing token/BBR tests. |
| M1 | Connection ACK operation observes a same-finder local size transition. | Local pointer/size snapshot avoids durable mirror obligations. Detection, accounting and settlement belong together. | Real aborted-fence regression; preserved floor, no-growth, constructor/replacement classification and existing DATAGRAM ownership. |
| L1 | Connection owns verdict; recovery's two named operations own its consequences. | Two meanings must not be smuggled into keepForACK; general retirement stays out. | Real testing overlap plus two loss entrypoints and materially different no-verdict cases, without cross products. |
| S1 | A finite receipt owns selection, runtime parser/admission remain unchanged. | Combining optimization with sizing defeats the decision; splitting observations from receipt leaves no coherent result. | Two commands, four declared fixtures, one observation per case; SUPPORT or terminal defer/inconclusive. |
| S2 | Existing wire parser owns shared scalar validation and the real skip consumer. | Shared decoder without consumer is unused exposure; consumer and validator ship together. | Named semantic preservation cases and one comparable baseline/candidate observation, without external grammar enumeration. |

All proposed contracts use existing representation owners. The source/planning audit found no accepted invariant needing a new persisted fact, cross-context signal, temporary runtime representation or broader module. Contract closure is not triggered for these bounded seams because ordinary focused tests cover the admitted semantic distinctions; no proof, mutation campaign or unapproved maintained verification product is claimed.

## Publication audit receipt

**PASS — independent source/architecture audit and independent contract/slice audit**, November 16, 2026. Both auditors read the immutable `draft-v1` snapshot against source commit `ad76ab772160a9eabf88d06c508213b94ce37bd8` and verified all eight SHA-256 identities below. The source audit also used two narrow read-only reviewers for ECN and STREAM. Neither audit edited files or ran tests, benchmarks or implementation agents. No material correction, unresolved finding, new gate or expanded evidence obligation was returned.

| Slice | Source/architecture | Contract/slice | Disposition |
|---|---|---|---|
| A1 | PASS | PASS | Retain selected-member execution and three endpoint-transition cases. |
| E1 | PASS | PASS | Retain current-reservation release ownership; exclude historical ACK/loss policy. |
| M1 | PASS | PASS | Retain same-finder ACK snapshot and causal fixture repair. |
| L1 | PASS | PASS | Retain two semantic retirement operations and production-reachable testing overlap. |
| S1 | PASS | PASS | Retain finite observations and a terminal selection receipt. |
| S2 | PASS, conditional | PASS, conditional | Retain the requirement for S1's merged SUPPORT decision, not merely S1 closure. |

The drafting owner independently accepts both audit conclusions. The four correction premises remain source-supported hypotheses until their declared regressions execute. S1 SUPPORT authorizes an attempt at the bounded S2 design; it is not performance qualification or a speedup claim.

### Reviewed snapshot identities

These are the identities the auditors reviewed before commit. The seven normative/index documents remain byte-identical to that snapshot. This audit artifact's snapshot hash identifies its pre-receipt version; the only subsequent change is replacing the pending receipt with this completed record. There is no recursive self-hash obligation.

| Reviewed document | SHA-256 |
|---|---|
| `docs/adr/2026-11-16-announcement-carrier-plan.md` | `e036f06d11df6a6615cb1637fc04792fd4522be1526f5dc7a697ab0052099565` |
| `docs/adr/2026-11-16-architecture-correctness-program.md` | `fbfd4218d24e29b932409367ec43ede8d634dc0317510503202437c76b146ce7` |
| `docs/adr/2026-11-16-architecture-decisions.md` | `3cd8e00e04cc65b1b3bfc81d677da079f9f28aa01348115c12ecffe0d42bb899` |
| `docs/adr/2026-11-16-ecn-testing-release-plan.md` | `6ed67f1204761d007d0ec9d860b5c826a2e519b800eeefe71d05465d7ae39bd1` |
| `docs/adr/2026-11-16-path-zero-mtu-growth-plan.md` | `f07bcb1c5b48d1d627f755d6c14c1011f4f51f2b69412914e132e45a0b23cc3d` |
| `docs/adr/2026-11-16-recovery-probe-ecn-plan.md` | `708d00aad127009883173a1774eeee76611ad1800aa29171bfc36b415b033f15` |
| `docs/adr/2026-11-16-stream-admission-plan.md` | `9fd9a3f977950c469223790fa76cfadd8298f956f64ad72fe1f9a987619c5490` |
| `docs/audits/2026-11-16-architecture-handoff/README.md` | `a4195c8fadfe6f81b058a087c2ab13817f3ac616ea9bda4fa705ac4831421103` |

Later PR review, exact-head certification and merge receipts belong in the PR discussion. This section is audit history, not a second source of substantive acceptance criteria.
