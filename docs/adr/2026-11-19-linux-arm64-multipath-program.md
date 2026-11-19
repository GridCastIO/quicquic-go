# Linux ARM64 multipath program

**Date:** 2026-11-19. **Identity:** MP-ARM-20261119. **Status:** Accepted handoff; no ARM implementation dispatched. **Tracking issue:** pending. **Audit history:** [Source/slice audit](../audits/2026-11-19-linux-arm64-handoff/README.md).

## Purpose

Package the full-parity outcome from [planning issue #1395](https://github.com/GridCastIO/quicquic-go/issues/1395) and [PR #1481](https://github.com/GridCastIO/quicquic-go/pull/1481) into six ARM-owned child PRs, consuming existing shared tooling owners. The [implementation plan](2026-11-19-linux-arm64-multipath-implementation-plan.md) owns substantive contracts; this index owns stable track identity and graph. The [target/evidence plan](2026-11-19-linux-arm64-multipath-plan.md) retains settled context. Issues and OmniFocus own live mappings/state, not copied contracts or audit history.

## Track and frontier

| Track | Normative plan | Parent issue | Size | Initial frontier | Status |
| --- | --- | --- | --- | --- | --- |
| MP-ARM — Linux ARM64 multipath parity | [Implementation plan](2026-11-19-linux-arm64-multipath-implementation-plan.md) | pending | 6 ARM-owned slices / intended PRs | A0 | Not implemented |

| ARM slice | Blocked by | State |
| --- | --- | --- |
| A0 — Bind the native venue and prepared toolchains | None | FRONTIER |
| E1 — Adapt the native endpoint fixture and build attribution | A0 | BLOCKED |
| P1 — Build the pinned native ARM64 peer and ordinary controls | [Shared peer P1 (#1488)](https://github.com/GridCastIO/quicquic-go/issues/1488) | BLOCKED |
| C1 — Adapt matched ordinary workloads and ARM64 metrics | A0, [shared metrics C1 (#1490)](https://github.com/GridCastIO/quicquic-go/issues/1490) | BLOCKED |
| Q1 — Approve the concrete native execution protocol | E1, P1, C1, [shared ingress P2 (#1489)](https://github.com/GridCastIO/quicquic-go/issues/1489), [shared lifecycle C2 (#1491)](https://github.com/GridCastIO/quicquic-go/issues/1491), [shared comparison C4 (#1493)](https://github.com/GridCastIO/quicquic-go/issues/1493) | BLOCKED |
| Q2 — Qualify and activate the complete Linux ARM64 profile | Q1 | BLOCKED |

The [shared relay C3 (#1492)](https://github.com/GridCastIO/quicquic-go/issues/1492) is a transitive prerequisite through shared C4 (#1493). The implementation plan links each existing shared contract at verified default-branch commit `24cd8a12dbf63bdd8bfbffdcfc07ca987739e465`. Its future implementation must still merge and meet that contract; no draft is grandfathered as a baseline. Keep shared issue/task ownership in the existing program and create no duplicate ARM P2/C2/C3/C4 or adoption-only PR.

A0 can proceed alongside the externally owned shared work. E1 follows A0 independently of peer/metric work. ARM P1 becomes parallel-safe with E1/C1 after shared P1 (#1488) completes; ARM C1 follows both A0 and shared C1 (#1490). These edges consume selected profile/identity or workload/metric interfaces. They are not convenience ordering and do not depend on macOS public activation. No integration branch is needed.

Q1 cannot complete without actual merged shared methods and the concrete owner-approved venue/privilege, operational inventory and selected continuing-aid decisions. Q2 cannot be ready merely because tools compile. This handoff allocates no native campaign, repeated-run allowance or doubled hosted peer matrix, and launches no implementation agent.

## Outcomes requiring no additional ARM implementation

Fresh ingress, lifecycle memory, the portable UDP relay and matched comparison already have sole shared child owners, listed above. Consume their actual merged outputs rather than rebuild them. Richer shared tool capabilities do not expand ARM's collection inventory. Preserve shared tools for the life of their owning support contract, even after that program completes. Only separately identified ARM-specific finite entrypoints are eligible for ARM retirement after a definitive support decision.

Two-path full Reno/BBR parity, default-off behavior, existing socket/grant/lifetime owners and experimental aggregate limitations are settled. Higher path counts, other architectures/kernels, physical-NIC claims, new backend/controller/scheduler designs and full BBR qualification remain outside this program. Completed [program #646](https://github.com/GridCastIO/quicquic-go/issues/646) and [continuation #1374](https://github.com/GridCastIO/quicquic-go/issues/1374) stay closed. [PR #1295](https://github.com/GridCastIO/quicquic-go/pull/1295) remains unselected historical work, excluded as a dependency; its refs, evidence and spent inventory are untouched. No unrelated legacy program is rebaselined and no new glossary term/numbered ADR is introduced.

## Binding rules

Use the shared review-loop/contract-closure baselines supplied by $implement-architecture-slice, shared design-cost policy and [repository execution overlay](../REVIEW-LOOP.md). Preserve existing behavior and frozen evidence, one mutation owner, authority completeness, explicit representation/artifact boundaries, terminating evidence and the zero temporary runtime seam budget in the plan. Public ARM64 support stays closed through readiness. No unapproved verification aid becomes a product blocker.

One ARM-owned slice maps to one new child issue, intended PR and pointer-based task. External shared children retain their existing mappings. ARM child issues carry the exact verified default-branch plan commit and heading; issue-link fields here remain pending because the live mapping belongs to the tracker. Parent issues are not dispatch requests. Implementing PRs own their contract/index completion and frontier updates before review. After exact-head review/certification/hosted success and merge: record the dev-journal completion account, reconcile issue/task blockers, then complete the slice task. Administrative pointers are separate from code-head certification.

Q2 keeps admission/tests/accepted evidence/selected CI/support together for activation. A definitive owner no-go instead produces the documented negative disposition and safe ARM-specific retirement while admission remains closed; shared maintenance obligations survive either outcome. The handoff report verifies current remote-default-branch reachability again before naming dispatchable frontier children. The operator may dispatch each verified frontier child to a fresh agent with $implement-architecture-slice and clear context between children. This run reports that frontier and does not dispatch it.
