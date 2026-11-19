# macOS multipath program

**Date:** 2026-11-19. **Identity:** MP-MAC-20261119. **Status:** Accepted handoff; implementation in progress. **Tracking issue:** pending. **Audit history:** [Source and slice audit](../audits/2026-11-19-macos-multipath-handoff/README.md).

## Purpose and source of truth

Package the owner-approved macOS profile from [planning issue #1396](https://github.com/GridCastIO/quicquic-go/issues/1396) and [PR #1479](https://github.com/GridCastIO/quicquic-go/pull/1479) into one track of eleven independently green child PRs. The [implementation plan](2026-11-19-macos-multipath-implementation-plan.md) owns substantive contracts; this index owns stable program/track pointers and the graph. Issues and OmniFocus hold current state and pointers, not duplicate contracts. The original [target and evidence plan](2026-11-18-macos-multipath-plan.md) retains settled profile context; its broad proposed work units are replaced by the audited child contracts.

## Track and frontier

| Track | Plan | Parent issue | Size | Current frontier | State |
| --- | --- | --- | --- | --- | --- |
| MP-MAC — Native macOS multipath | [Implementation plan](2026-11-19-macos-multipath-implementation-plan.md) | pending | 11 slices / intended PRs | E1, P1, P2, C1 | Readiness in progress |

| Slice | Blocked by | State |
| --- | --- | --- |
| E1 — Granted scalar fixture | None | FRONTIER |
| E2 — Blocked-writer lifecycle fixture | E1 | BLOCKED |
| E3 — Contention/pressure fixture | E1 | BLOCKED |
| P1 — Native pinned peer and ordinary control | None | FRONTIER |
| P2 — Fresh aggregate ingress witness | None | FRONTIER |
| C1 — Native ordinary workloads/metrics | None | FRONTIER |
| C2 — Negotiated lifecycle memory | C1 | BLOCKED |
| C3 — UDP topology relay | None | COMPLETE |
| C4 — Topology comparison workload | C1, C3 | BLOCKED |
| Q1 — Concrete execution/venue protocol | E2, E3, P1, P2, C2, C4 | BLOCKED |
| Q2 — Qualification and public activation | Q1 | BLOCKED |

There are no cross-track edges. E1, P1, P2, C1 and C3 can be dispatched independently in separate worktrees; P1/P2 share some files but have no behavioral dependency. E2/E3 become parallel-safe after E1; C2 can proceed after C1 while C4 additionally needs C3. Prefer E1 and P1 first to expose native socket/build feasibility early; priority does not create a blocking edge. Shared-host qualification coordination belongs to Q1, not to arbitrary serial task order.

Q1 cannot complete without the concrete owner-approved execution, venue, toolchain, admitted-release and selected maintained-aid decisions. It collects no native qualification campaign. Q2 cannot be ready merely because tooling compiles; its blocker binds the actual methods and authority. The implementation skill verifies those conditions again before dispatch. No implementation agent is launched by this handoff.

## Outcomes requiring no implementation

The two-path cap and all three controller/policy combinations are settled. Intel, other Darwin majors, higher path counts, full BBR qualification and private-batch optimization remain outside this program. The completed [multipath program (#646)](https://github.com/GridCastIO/quicquic-go/issues/646) and [BBR continuation (#1374)](https://github.com/GridCastIO/quicquic-go/issues/1374) stay complete. [PR #1295](https://github.com/GridCastIO/quicquic-go/pull/1295) remains Draft/unselected historical evidence, with no graph edge or fresh inventory; the plan/audit record the exclusion. No unrelated legacy program is rebaselined.

No new domain term or numbered ADR is required. Preserve the glossary's distinctions among application delivery, local admission, endpoint grant, protocol path and transport detachment, and the settled packet-emission/endpoint ownership decisions.

## Binding rules

Use the shared review-loop and contract-closure baselines supplied by `$implement-architecture-slice`, the shared design-cost reference and [repository execution overlay](../REVIEW-LOOP.md). Their artifact/representation gates, finite evidence and review limits, semantic-family closure, precise-root stop comparison, diagnosis before reruns, exact-head local certification, same-head hosted checks, merge and journal rules govern. This program adds no copy of those policies, blanket campaign budget, statistical repetition or automatic required CI gate.

One current plan slice maps to one marked child issue, one intended PR and one pointer-based OmniFocus task. A parent is not an implementation request. Keep public Darwin admission closed through readiness; preserve default-off and Linux behavior and frozen evidence. New artifacts have the owners/classes and finite evidence in the plan. No undocumented temporary runtime seam, second mutation owner or untraced production effect may be carried into a successor.

The implementing child's PR must own its plan/index completion and affected successor-frontier update before review. After exact-head merge: record the dev-journal completion account, reconcile child/parent/tracker blockers and readiness labels, and complete the matching OmniFocus task. Do not open a routine status-only third PR. Administrative state is separate from code-head certification; mirrors do not carry the plan SHA.

Publish this index and the audited contracts before issue/task synchronization. Child issues carry the verified default-branch plan commit and exact heading; issue-link fields stay pending here because live mappings belong to the tracker. Immediately before reporting a frontier, verify its plan commits remain reachable from the current remote default branch. Dispatch is the operator's decision: one fresh agent per verified frontier child using `$implement-architecture-slice`, with context cleared between children.
