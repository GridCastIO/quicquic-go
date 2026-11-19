# Linux ARM64 multipath program

**Date:** 2026-11-19. **Identity:** MP-ARM-20261119. **Status:** Accepted handoff; no implementation dispatched. **Tracking issue:** pending. **Audit history:** [Source/slice audit](../audits/2026-11-19-linux-arm64-handoff/README.md).

## Purpose

Package the full-parity outcome from [planning issue #1395](https://github.com/GridCastIO/quicquic-go/issues/1395) and [PR #1481](https://github.com/GridCastIO/quicquic-go/pull/1481) into independently green child PRs. The [implementation plan](2026-11-19-linux-arm64-multipath-implementation-plan.md) owns substantive contracts; this index owns stable track identity and graph. The [target/evidence plan](2026-11-19-linux-arm64-multipath-plan.md) retains settled context. Issues and OmniFocus own live mappings/state, not copied contracts or audit history.

## Track and frontier

| Track | Normative plan | Parent issue | Size | Initial frontier | Status |
| --- | --- | --- | --- | --- | --- |
| MP-ARM — Linux ARM64 multipath parity | [Implementation plan](2026-11-19-linux-arm64-multipath-implementation-plan.md) | pending | 10 slices / intended PRs | A0, P1, P2, C3 | Not implemented |

| Slice | Blocked by | State |
| --- | --- | --- |
| A0 — Bind the native venue and prepared toolchains | None | FRONTIER |
| E1 — Adapt the native endpoint fixture and build attribution | A0 | BLOCKED |
| P1 — Build the pinned native ARM64 peer and ordinary controls | None | FRONTIER |
| P2 — Add a fresh both-active DATAGRAM ingress witness | None | FRONTIER |
| C1 — Adapt matched ordinary workloads and ARM64 metrics | A0 | BLOCKED |
| C2 — Observe negotiated lifecycle memory | C1 | BLOCKED |
| C3 — Build a scoped real-UDP topology relay | None | FRONTIER |
| C4 — Bind the matched topology comparison workload | C1, C3 | BLOCKED |
| Q1 — Approve the concrete native execution protocol | E1, P1, P2, C2, C4 | BLOCKED |
| Q2 — Qualify and activate the complete Linux ARM64 profile | Q1 | BLOCKED |

A0/P1/P2/C3 are parallel-safe in dedicated worktrees; prefer A0 and P1 to expose native venue/build feasibility early. E1/C1 can proceed independently after A0; C2 follows C1, while C4 requires both C1/C3. Q1 binds the five leaf outputs, then Q2 performs approved execution and activation. There are no cross-track edges or integration branch. Shared files with the separate macOS program require merge coordination and reuse of actual merged interfaces, not speculative dependencies.

Q1 cannot complete without the concrete owner-approved venue/privilege, operational inventory and selected continuing-aid decisions. Q2 cannot be ready merely because tools compile. This handoff allocates no native campaign, repeated-run allowance or doubled hosted peer matrix, and launches no implementation agent.

## Outcomes requiring no implementation

Two-path full Reno/BBR parity, default-off behavior, existing socket/grant/lifetime owners and experimental aggregate limitations are settled. Higher path counts, other architectures/kernels, physical-NIC claims, new backend/controller/scheduler designs and full BBR qualification remain outside this program. Completed [program #646](https://github.com/GridCastIO/quicquic-go/issues/646) and [continuation #1374](https://github.com/GridCastIO/quicquic-go/issues/1374) stay closed. [PR #1295](https://github.com/GridCastIO/quicquic-go/pull/1295) remains unselected historical work, excluded as a dependency; its refs, evidence and spent inventory are untouched. No unrelated legacy program is rebaselined and no new glossary term/numbered ADR is introduced.

## Binding rules

Use the shared review-loop/contract-closure baselines supplied by $implement-architecture-slice, shared design-cost policy and [repository execution overlay](../REVIEW-LOOP.md). Preserve existing behavior and frozen evidence, one mutation owner, authority completeness, explicit representation/artifact boundaries, terminating evidence and the zero temporary runtime seam budget in the plan. Public ARM64 support stays closed through readiness. No unapproved verification aid becomes a product blocker.

One slice maps to one child issue, intended PR and pointer-based task. Child issues carry the exact verified default-branch plan commit and heading; issue-link fields here remain pending because the live mapping belongs to the tracker. Parent issues are not dispatch requests. Implementing PRs own their contract/index completion and frontier updates before review. After exact-head review/certification/hosted success and merge: record the dev-journal completion account, reconcile issue/task blockers, then complete the slice task. Administrative pointers are separate from code-head certification.

The handoff report verifies current remote-default-branch reachability again before naming dispatchable frontier children. The operator may dispatch each verified frontier child to a fresh agent with $implement-architecture-slice and clear context between children. This run reports that frontier and does not dispatch it.
