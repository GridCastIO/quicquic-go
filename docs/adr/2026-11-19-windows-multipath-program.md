# Windows multipath program

**Date:** 2026-11-19. **Identity:** MP-WIN-20261119. **Status:** Accepted handoff; no implementation dispatched. **Tracking issue:** pending. **Audit history:** [Source and slice audit](../audits/2026-11-19-windows-multipath-handoff/README.md).

## Purpose and source of truth

Package the Windows profile from [planning issue #1397](https://github.com/GridCastIO/quicquic-go/issues/1397) and [PR #1483](https://github.com/GridCastIO/quicquic-go/pull/1483) into one track of fifteen child PRs. The [implementation plan](2026-11-19-windows-multipath-implementation-plan.md) is normative for slice contracts. This index owns stable identities and dependency pointers; issues and OmniFocus own current administrative state. The [target/evidence plan](2026-11-19-windows-multipath-plan.md) supplies settled background, while its broad W1–W6 units are replaced by the audited slices.

## Track, dependencies and frontier

| Track | Plan | Parent issue | Size | Frontier | Status |
| --- | --- | --- | --- | --- | --- |
| MP-WIN — Native Windows multipath | [Implementation plan](2026-11-19-windows-multipath-implementation-plan.md) | pending | 15 slices / intended PRs | R1, R3, R4 | Implementation pending |

| Slice | Blocked by | State |
| --- | --- | --- |
| R1 — Extract native platform operations without changing behavior | None | FRONTIER |
| R2 — Implement the Windows scalar endpoint and datagram results | R1 | BLOCKED |
| R3 — Add the checked Windows granted-reader interface | None | FRONTIER |
| R4 — Publish target ECN capability at path transitions | None | FRONTIER |
| R5 — Integrate private Windows transports and paths | R2, R3, R4 | BLOCKED |
| E1 — Supply native socket, family and PMTU case receipts | R5 | BLOCKED |
| E2 — Establish the pending-IOCP deadline and borrow method | E1 | BLOCKED |
| E3 — Add contention and pressure observations | E1 | BLOCKED |
| P1 — Connect a Windows subject to the pinned Linux peer | MP-MAC-P1 (#1488) | BLOCKED |
| P2 — Attribute fresh STREAM content to both ingress paths | MP-MAC-P2 (#1489) | BLOCKED |
| C1 — Add Windows ordinary workloads and native metrics | R5, MP-MAC-C1 (#1490) | BLOCKED |
| C2 — Adapt lifecycle-memory observations for Windows | C1, MP-MAC-C2 (#1491) | BLOCKED |
| C3 — Adapt topology comparisons to native Windows subjects | C1, MP-MAC-C4 (#1493) | BLOCKED |
| Q1 — Bind the executable protocol and operating authority | E2, E3, P1, P2, C2, C3 | BLOCKED |
| Q2 — Qualify and activate Windows multipath | Q1 | BLOCKED |

Cross-program children retain their existing mappings: [MP-MAC-P1 (#1488)](https://github.com/GridCastIO/quicquic-go/issues/1488), [P2 (#1489)](https://github.com/GridCastIO/quicquic-go/issues/1489), [C1 (#1490)](https://github.com/GridCastIO/quicquic-go/issues/1490), [C2 (#1491)](https://github.com/GridCastIO/quicquic-go/issues/1491), [C4 (#1493)](https://github.com/GridCastIO/quicquic-go/issues/1493), transitively [relay C3 (#1492)](https://github.com/GridCastIO/quicquic-go/issues/1492). These are genuine consumed-interface blockers; open PRs are not established baselines. Verify accepted merged interfaces before dependent dispatch. This program does not dispatch, duplicate or rebaseline those tracks.

R1/R3/R4 may run independently in dedicated worktrees. Prefer R1 first to expose the platform-operation interface and unblock R2, alongside R3/R4 when capacity allows; priority does not add edges. P1 consumes its shared launch/tuple predecessor and requires independently supplied operator development access for its native controls; Q1 cannot supply that prerequisite. P2 consumes the shared DATAGRAM phase/receipt interface and validates STREAM attribution independently of P1 on supported Linux; its live aggregate control retains the shared requirement for operator approval of the bounded inventory before execution. P1 returns the finalized peer artifact before remote cleanup; P2 uses the same local artifact contract in either merge order. Missing external access keeps affected validation and the child open. E2/E3 can overlap after E1, and C2/C3 after their actual inputs merge. Shared files and shared hosts require coordination, not invented serial ordering. Q1 binds concrete operating decisions; Q2 cannot become ready from compilation or a missing-evidence receipt.

## Outcomes closed without additional implementation

P0 and [issue #1397](https://github.com/GridCastIO/quicquic-go/issues/1397) remain complete. The two-path cap, three controller/policy combinations, scalar-first granted Windows egress, existing Go runtime ownership and arm64/386 deferrals are settled. The completed [multipath program (#646)](https://github.com/GridCastIO/quicquic-go/issues/646) and [BBR continuation (#1374)](https://github.com/GridCastIO/quicquic-go/issues/1374) are not reopened. [PR #1295](https://github.com/GridCastIO/quicquic-go/pull/1295) remains unselected historical Linux evidence and outside this graph. No new numbered ADR or domain term is required, and no unrelated legacy program is rebaselined.

## Binding rules

Use the shared review-loop and contract-closure baselines from `$implement-architecture-slice`, the shared design-cost reference and [repository overlay](../REVIEW-LOOP.md). Preserve the approved profile, public refusal through readiness, single mutation owners and bounded transitional seams. The implementation plan owns artifact/representation contracts, finite evidence and context budgets, TDD seams, preservation and stop conditions. This program creates no policy copy, new blanket campaign allocation or automatic recurring CI gate.

One Windows slice maps to one marked child, one intended PR and one OmniFocus task; the parent track is never an implementation request. Child PRs include their required plan/index completion and affected frontier transitions. After merge: dev-journal completion account, child/parent/tracker blocker and readiness reconciliation, then complete the task. Mirrors contain current pointers and state, not copied contracts or exact code-head certification. Do not create a routine status-only third PR.

Publish and verify the plan/index on remote main before creating child issues and task mirrors. Child issues record the verified default-branch plan commit; issue-link fields stay pending here because the tracker owns live mappings. Before reporting a frontier, re-fetch main and verify each recorded plan commit remains reachable and contains its exact slice. Dispatch is the operator's decision: a fresh agent using `$implement-architecture-slice` for each verified frontier child, with context cleared between children.
