# FreeBSD multipath implementation program

**Identity:** MP-FBSD-20261119. **Status:** Accepted handoff; not yet implemented; no implementation dispatched. **Tracking issue:** pending. **Program parent:** the user-selected FreeBSD multipath OmniFocus task. **Audit history:** [Handoff audit](../audits/2026-11-19-freebsd-multipath-handoff/README.md).

## Purpose and normative owner

Package the accepted [FreeBSD planning outcome (#1398)](https://github.com/GridCastIO/quicquic-go/issues/1398), merged in [PR #1482](https://github.com/GridCastIO/quicquic-go/pull/1482), into one independently reviewed child per intended PR. The [implementation plan](2026-11-19-freebsd-multipath-implementation-plan.md) owns current contracts. This index and the future tracker own pointers and frontier state only. No implementation or native campaign is dispatched by this handoff.

## Track and dependencies

| Track | Plan | Parent issue | Size | State |
| --- | --- | --- | --- | --- |
| MP-FBSD — FreeBSD amd64/arm64 multipath | [Current fourteen-slice plan](2026-11-19-freebsd-multipath-implementation-plan.md) | pending | 14 intended PRs, one bounded fresh context per child | V1 frontier; remaining children blocked |

The internal graph is `V1 → S1 → S2`, `V1 → S3`, `V1 → E1 → E2/E3`, `V1 → P1`, `V1 → C1 → C2/C3`; P2 consumes its shared external predecessor. Q1 requires S2, S3, E2, E3, P1, P2, C2 and C3; Q2 requires Q1. The exact contracts, edge reasoning and all stop conditions live in the plan.

External consumed interfaces are [native peer P1 (#1488)](https://github.com/GridCastIO/quicquic-go/issues/1488) → FreeBSD P1; [fresh DATAGRAM P2 (#1489)](https://github.com/GridCastIO/quicquic-go/issues/1489) → FreeBSD P2; [ordinary metrics C1 (#1490)](https://github.com/GridCastIO/quicquic-go/issues/1490) → FreeBSD C1; [lifecycle C2 (#1491)](https://github.com/GridCastIO/quicquic-go/issues/1491) → FreeBSD C2; and [topology comparison C4 (#1493)](https://github.com/GridCastIO/quicquic-go/issues/1493) → FreeBSD C3, with its transitive [relay dependency (#1492)](https://github.com/GridCastIO/quicquic-go/issues/1492). No macOS qualification or activation is a dependency. Unmerged work is not a baseline; consumers wait for merge and interface verification. Existing external issues/tasks remain with their current owners and are not duplicated here.

V1 is the initial FreeBSD frontier. After V1, S1, S3 and E1 are parallel-safe in separate worktrees; P1 and C1 additionally require their external blockers. E2/E3 follow E1 independently; P2 may proceed when its external phase/witness dependency completes, without waiting for V1. C2/C3 each need C1 and their own external consumer interface. Shared file proximity creates merge coordination, not an extra dependency. Infrastructure already serializes access to a target; coordinated native use is an execution condition, not a new graph edge.

Required external readiness also blocks its affected consumers. Infra-owned Go 1.26.11 delivery must be resolved before Q1 is ready or complete; V1 records the responsible infra maintainer and concrete delivery issue/runbook/receipt pointer (pending until its inventory), including required selected tools. Merging Q1's eight code leaves alone does not clear this block. Optional diagnostics and unavailable counters are not gates. Q1 selects the concrete continuing-CI route/trust/credentials/status/failure owner; Q2 integrates the established execution interface. A selected route needing new infrastructure or authority becomes a separately owned prerequisite and triggers the affected re-audit, rather than expanding Q2.

## Settled outcomes and boundaries

Both architectures and all three controller/policy combinations remain initial targets. FreeBSD 386/arm, higher path counts, another backend, GSO/GRO/grouping optimization, full BBR qualification and historical Linux cost exceptions are outside the program. The completed [multipath program (#646)](https://github.com/GridCastIO/quicquic-go/issues/646) and [BBR continuation (#1374)](https://github.com/GridCastIO/quicquic-go/issues/1374) remain complete. [PR #1295](https://github.com/GridCastIO/quicquic-go/pull/1295) is excluded historical evidence, not a dependency or a target for incidental mutation.

The existing endpoint/connection/socket and infra lifecycle owners are retained. Source-confirmed FreeBSD size feedback, DF/PMTU and reply-source gaps get separate contracts. The dual-stack DF limitation is an explicit applicability/repair decision in Q1; no narrowed family domain or false capability is preapproved. Native evidence, truthful measurement and public activation stay distinct.

No new glossary term or numbered ADR is needed. Preserve the glossary's distinctions among application DATAGRAM admission, transport delivery, application goodput, endpoint grant, protocol path, detachment and grant return. The program creates implementation plans in the established date-named layout, not a new irreversible architecture decision.

## Binding rules

Use the shared review-loop, contract-closure and design-cost baselines supplied by $implement-architecture-slice, composed with [the repository execution overlay](../REVIEW-LOOP.md). Their representation/artifact gates, finite evidence/review scope, owner-based semantic closure, precise-root comparison, diagnosis before reruns, clean exact-head certification, same-head hosted checks, merge and dev-journal ritual govern. This index installs no policy copy, automatic CI gate, statistical repetition or campaign allowance.

A current plan slice maps exactly once to one marked child issue, one intended PR and one pointer-based OmniFocus task. The parent track is not an implementation request. A child product PR owns its plan/index completion and affected successor-frontier transition before review. After merge, record the hosted dev-journal completion account, reconcile issue dependencies and frontier labels, then complete the matching task. Exact code-head evidence is separate from administrative mirrors; OmniFocus contains no plan SHA and no mirrored contract. No routine third PR is needed solely for status.

Merge the audited docs before publishing dispatch pointers. Child issues carry the exact verified default-branch plan commit and heading; pending issue fields here stay pending because the tracker owns the live mapping. Before reporting a frontier, verify the commit remains reachable and its exact slice exists on remote main. Dispatch is the operator's choice: use a fresh agent with $implement-architecture-slice for each verified frontier child and clear context between children.
