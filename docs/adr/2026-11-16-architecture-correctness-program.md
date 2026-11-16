# Correctness and Architecture Program — November 16, 2026

**Identity:** `N16-20261116`
**Status:** Implementation in progress
**Normative scope:** Stable track identities, pointers, real dependencies, priority and binding rules
**Audit history:** [Source and slice audit](../audits/2026-11-16-architecture-handoff/README.md)

## What this is

This program captures the final grilled decisions from the November 16 architecture review. Four source-supported correctness findings receive narrow reproduction-and-correction slices. An independent STREAM inspection track first measures current cost, then conditionally implements the already bounded design. The plans own the contracts; parent issues, child issues and OmniFocus contain current state and pointers. The user invoked handoff, not implementation dispatch.

## Tracks, dependencies and frontier

| Track | Plan | Parent issue | Slices | Blocking slices | Initial state |
|---|---|---|---|---|---|
| N16-A: announcement carrier identity (D2) | [Announcement plan](2026-11-16-announcement-carrier-plan.md) | pending | A1 | None | FRONTIER; recommended first |
| N16-E: Reno testing reservation release (D3) | [ECN release plan](2026-11-16-ecn-testing-release-plan.md) | [#1431](https://github.com/the-sarge/quic-go-fast/issues/1431) | E1 | None | COMPLETE; no successors |
| N16-M: path-zero MTU growth (D1) | [MTU growth plan](2026-11-16-path-zero-mtu-growth-plan.md) | pending | M1 | None | FRONTIER; next priority |
| N16-L: size-recovery loss evidence (D4) | [Probe-loss plan](2026-11-16-recovery-probe-ecn-plan.md) | [#1435](https://github.com/the-sarge/quic-go-fast/issues/1435) | L1 | None | COMPLETE ([PR #1446](https://github.com/the-sarge/quic-go-fast/pull/1446)); no successors |
| N16-S: STREAM admission work | [STREAM inspection plan](2026-11-16-stream-admission-plan.md) | pending | S1, S2 | S2 requires S1's published SUPPORT decision | S1 FRONTIER; S2 BLOCKED/conditional |

The sole blocking edge is `S1 → S2`: the accepted decision requires sizing the optional optimization before committing to its implementation. Closing S1 is insufficient by itself; its published outcome must be SUPPORT. DEFER or INCONCLUSIVE completes S1 and closes S2 as not selected, without waiting for an unspecified future measurement. Source/representation invalidation is a stop, not automatic optimization authority.

A1, E1, M1, L1 and S1 have no technical dependencies on one another and are parallel-safe in separate worktrees. Prefer A1/E1, then M1/L1, then S1; this is priority, not a blocking graph. Coordinate an actual shared-host measurement with concurrent workloads and disclose relevant performance-core contention; ordinary background activity alone is not a dependency. Merge and certify each exact candidate independently. S2 can proceed independently of the correctness tracks once its own decision edge is satisfied.

All six slice contracts map to one child issue and one intended PR each. The four correction slices combine the failing regression and its bounded repair; they are not split into tests-only PRs that leave a known defect waiting. A disproved premise can terminate with a documented no-code disposition. No implementation agent is launched by this handoff.

## Outcomes requiring no implementation

The [decision register](2026-11-16-architecture-decisions.md) captures every rejected, deferred and narrowed direction, including D5's already-settled path-retirement policy, credit-only fixture retirement, native readiness, path-success publication, common turn ordering and broader recovery/parser designs. These are not additional dispatch tracks. No new domain term or numbered ADR is needed: existing glossary terms and ownership ADRs suffice.

## Rules binding every track

The current per-track plan and exact slice are normative. Preserve ADRs [0001](0001-upstream-compatibility.md), [0002](0002-adopt-through-module-replacement.md), [0004](0004-packet-emission-ownership.md), [0005](0005-incoming-packet-lifetime.md), and the [A20 dispositions](2026-10-20-architecture-decisions.md). No blanket performance exemption or tag wait is inferred from shared files. Release qualification remains with its existing owner.

Apply the shared [review-loop](https://github.com/the-sarge/skills/blob/main/_shared/REVIEW-LOOP.md), [contract-closure](https://github.com/the-sarge/skills/blob/main/_shared/CONTRACT-CLOSURE.md) and [design-cost](https://github.com/the-sarge/skills/blob/main/_shared/DESIGN-COST.md) policies plus [the repository execution overlay](../REVIEW-LOOP.md). Their representation and artifact gates, finite evidence/review budgets, precise-root family comparison, approach stops, exact-head certification, hosted checks, merge and journal rules govern. No repository baseline copy is created.

Keep a single mutation owner for each touched fact and transition. The plans add no persisted authority or temporary duplicate state; S2's shared decoder and its sole new consumer ship together. Do not absorb adjacent defects or resurrect rejected modules merely because a test is missing. File substantive surviving follow-ups only after revalidation at the merged head and mirror each issue change in OmniFocus.

The accepted contract must be on the current remote default branch before a child receives its exact plan commit or readiness label. A parent is a tracker, not an implementation task. Dispatch one verified frontier child to one fresh agent with `$implement-architecture-slice`; clear context between children. The execution ritual is review loop → merge → append-dev-journal → reconcile issue/blockers → complete the slice task. Plan/mirror state is not exact code-head certification.
