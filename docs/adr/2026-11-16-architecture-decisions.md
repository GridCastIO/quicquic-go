# Architecture Decisions Requiring No Separate Work — November 16, 2026

**Status:** Accepted after source-based grilling and handoff audit
**Normative scope:** Current exclusions, preservation rules and revisit triggers; not a dispatch backlog
**Program:** [N16-20261116](2026-11-16-architecture-correctness-program.md)
**Audit history:** [Source and slice audit](../audits/2026-11-16-architecture-handoff/README.md)

## Selected outcomes and corrections

A1 binds an announcement's execution to its original carrier and reservation. The earlier deterministic-lookup premise is rejected: endpoint eligibility is externally mutable. E1 owns current Reno testing-reservation release without rewriting historical receipt/loss semantics. M1 detects path zero's own synchronous ACK growth independently of a shared DATAGRAM estimate. L1 supplies ECN evidence only for the existing dedicated size-recovery loss verdict. S1 measures the STREAM opportunity; S2 remains conditional. Confirmed fixes do not wait behind optional cleanup.

D1 does not prevent the finder or actual packet construction from growing. Its bounded consequence is skipped congestion-size accounting and ACK-completion settlement; BBR also refreshes its controller size during an ordinary opportunity. D2's missing-second-target case releases credit safely; a substituted carrier can charge the wrong route. Although reservation resizing guards against an oversized packet, the current announcement/PMTU lifecycle prevents a legally reselected carrier from exceeding the first reservation, so A1 does not require a panic reproduction. D3 is an old unsubmitted test-release defect; a single wrapped decrement alone does not establish permanent ECN failure. D4's missing evidence can leave validation Unknown instead of Failed; both states send Not-ECT. These source traces are not executed reproductions.

## Rejected and deferred directions

| Direction: do not do this | Reason and retained boundary | Revisit trigger |
|---|---|---|
| Standalone path-operation success module | Existing activation, cutover and failure owners hold the hard transitions. A CAS-plus-send wrapper is too thin; callbacks or a union of unlike completions add protocol. Public successful open/migrate wrappers also synchronize before returning. Preserve the existing private ordering. | A real new transition or repeated obligation beyond publication; a migration publication assertion may accompany related maintenance. |
| Global side-effect-free native-readiness rewrite | Preparation intentionally captures a deadline and reserves construction capacity. Pure hypothetical route checks and actual buffer reservation already exist separately. | A concrete caller protocol can disappear while preserving original capture, finish/reentry and grouping. |
| Shared controller turn-order extraction | Reno continuation and BBR handoff/credit/supply rules differ; the remaining common list is short. | A real shared ordering change, not resemblance alone. |
| Mandatory full announcement refactor | A1's correctness outcome is carrier/reservation association. A chosen-member execution operation can satisfy it without another framework. | Remaining caller obligations demonstrably justify deeper ownership after A1 is concrete. |
| Generic packet-exit or recovery-probe module | Disposal, PTO, dedicated size loss and cancellation have different policy owners. L1 changes one explicit verdict seam. | A separately accepted common retirement contract. |
| D5 path-failure/PTO policy reopening | Already settled in [PR #1418's disposition](https://github.com/the-sarge/quic-go-fast/pull/1418#issuecomment-6904313749): rescheduling intentionally uses the PTO loss path; no ECN-blind exemption was accepted. No immediate congestion-loss callback is added, while retained PTO evidence can affect later persistent loss. | A demonstrated new behavior violating that accepted policy; no new D5 test project is selected. |
| Automatic credit-only fixture retirement | Production activation requires native admission, but old fixtures still test live CID/reset/receipt/activation obligations. Preserving those obligations limits the runtime simplification available from fixture retirement alone. | An actual activation/test-owner change or an explicit later decision to undertake fixture retirement. Preserve historical receipts; map retained assertions before deletion. |
| Broad recovery setup profile | Would move many test sites for modest production simplification without a concrete defect. | A real setup-policy change. |
| Retained receipt-list / full retained-evidence rewrite | Current owners and A20 dispositions remain; optional locality is not sufficient standalone value. | A real local-feedback or ACK-operation change with demonstrated duplicated obligation. |
| Generic ECN facade or historical testing-record rewrite | E1 only owns current testing-slot release. BBR, Reno, cumulative evidence and historical ACK/loss consumers retain their distinct contracts. | A separate accepted defect requiring a coherent wider owner. |
| Borrowed frame view or generic packet walker | Admission needs validated STREAM length, not a payload lifetime. A broad walker exposes ordinary dispatch and grammar beyond S2. | A separately accepted consumer actually needs that representation. |
| Early return after DATAGRAM queue overcount | Would suppress a later malformed-frame error and change packet admission semantics. | none: rejected on merit |
| New benchmark campaign, arbitrary threshold or qualification dependency | S1/S2 use a finite local sizing/comparison decision. F12 retains exact-candidate consumer/release qualification; it is not a benchmark harness or prerequisite to architecture design. | A separately approved operational question. |
| Blanket tests-only coverage program based on counts | The reported seven recovery and three refusal gaps were not enumerated; real existing tests cover related behavior. Test counts do not establish missing obligations or justify an abstraction. | A named observable gap required by an accepted change. |
| Claiming tests establish universal safety | Representative tests do not prove all states; single-owner enforcement and the declared representation/evidence domain still matter. | none: rejected on merit |
| ECN platform qualification, DATAGRAM publication, native settlement, fixture replacement and jumbo re-climb as prerequisites | These have separate owners and accepted dispositions; no genuine blocking edge to N16 was established. | A concrete interaction changes an accepted N16 invariant; otherwise keep separate. |

## Preserved decisions and existing work

[PR #1295 — scalar deadline arming](https://github.com/the-sarge/quic-go-fast/pull/1295) remains draft, unselected and outside this program. Its parent [issue #1285](https://github.com/the-sarge/quic-go-fast/issues/1285) closed after the owner accepted the measured tradeoff, not after shipping that candidate. The diff changes request I/O preparation; none of N16's contracts relies on it. Retain the branch and evidence; do not merge, replace or close it here.

[Issue #1412 — DATAGRAM admission limits](https://github.com/the-sarge/quic-go-fast/issues/1412) remains independent. M1 preserves aggregate DATAGRAM admission rather than relaxing it. [F12 release qualification (#1226)](https://github.com/the-sarge/quic-go-fast/issues/1226) remains in [the jumbo plan](2026-11-05-jumbo-packets-plan.md); S1 is not its completion, dependency replacement or performance approval. No existing program is rebaselined by this new scoped parent.

Keep the [A20 decisions](2026-10-20-architecture-decisions.md), existing native/MTU deadlines, storage limits, physical buffer ownership, packet registration before handoff, controller-specific policy, ordinary-parser allocation properties and frozen evidence. No glossary change or new numbered ADR is warranted.
