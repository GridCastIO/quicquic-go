# QUIC multipath #646 program

**Identity:** `QGF-MP646-20261024`. **Status:** 48 original slices complete; B9–B12 complete; accepted B continuation complete. **Tracking issue:** [#646](https://github.com/the-sarge/quic-go-fast/issues/646). Track plans own contracts; issues and OmniFocus own live mappings/state. Historical receipts stay behind links. This package reports work and dispatches no implementation.

## Tracks and frontier

| Track | Normative plan | Parent | Slices | Current state |
| --- | --- | --- | ---: | --- |
| E — native endpoint | [Endpoint plan](2026-10-24-multipath-endpoint-plan.md) | [#1012](https://github.com/the-sarge/quic-go-fast/issues/1012) | 9 | Complete; unchanged |
| R — Reno primary/backup | [Reno plan](2026-10-24-multipath-reno-plan.md) | [#1013](https://github.com/the-sarge/quic-go-fast/issues/1013) | 21 | Complete; experimental Linux amd64 Reno primary/backup enabled by R19 #1039 |
| B — BBR/aggregation | [BBR plan](2026-10-24-multipath-bbr-plan.md) | [#1014](https://github.com/the-sarge/quic-go-fast/issues/1014) | 11 complete | Continuation B9–B12 under follow-up #1374 complete; no frontier |
| N — endpoint efficiency/admission | [Efficiency plan](2026-11-04-native-endpoint-efficiency-plan.md) | [#1193](https://github.com/the-sarge/quic-go-fast/issues/1193) | 11 | Complete; unchanged |

The current public profile admits experimental Reno or BBR primary/backup and BBR aggregate through completed B12 (#1385); Reno stays default and Reno aggregate remains rejected. See the [B12 support record](../audits/2026-11-15-bbr-b12-support.md) for the positive fixed comparison, exact accepted ordinary-cost exceptions and public peer evidence. Full BBR Q2 [#599](https://github.com/the-sarge/quic-go-fast/issues/599) remains deferred and outside this work; application adoption and universal network-performance claims remain excluded.

**Current continuation frontier:** none. [B9 (#1382)](https://github.com/the-sarge/quic-go-fast/issues/1382), [B10 (#1383)](https://github.com/the-sarge/quic-go-fast/issues/1383), [B11 (#1384)](https://github.com/the-sarge/quic-go-fast/issues/1384) and [B12 (#1385)](https://github.com/the-sarge/quic-go-fast/issues/1385) are complete. The private selector and finite comparison apparatus are retired; frozen comparison evidence remains. Completed cross-track edges remain R9←E5, R16←E6 and B1←R19; no new E/R/N work is introduced.

## Evidence and no-code outcomes

The original 48 intended slice PRs remain complete. B8 [#1356](https://github.com/the-sarge/quic-go-fast/issues/1356) was dropped without code and is excluded from that count. The [scoped B handoff audit](../audits/2026-11-15-bbr-1374-handoff.md) records the legacy-contract rebaseline, owner decision, existing-work disposition and current slice audit. [The previous program index](https://github.com/the-sarge/quic-go-fast/blob/b4e3a4474f51a7b1fa60a0febbc79b04da4c4e72/docs/adr/2026-10-24-multipath-program.md) links historical coordination and evidence without making it the new dispatch context.

Native and Reno outcomes retain [native parent closure](../audits/2026-11-12-native-parent-closure.md), [R18 delivery](../audits/2026-11-12-multipath-r18-delivery-receipt.md), [R21 writer-yield evidence](../audits/2026-11-12-native-writer-yield-r21/README.md) and their original limitations/exact deviations. B5's [negative comparison](../audits/2026-11-14-multipath-b5-receipt.md) and B6's [published support record](../audits/2026-11-14-multipath-b6-support.md) remain frozen. [Cost follow-up #1368](https://github.com/the-sarge/quic-go-fast/issues/1368) is complete in [PR #1377](https://github.com/the-sarge/quic-go-fast/pull/1377), with exact exceptions and [candidate applicability](../audits/2026-11-14-bbr-ordinary-cost-1368/candidate-applicability.md); its delivery did not itself enable BBR. No old raw failure becomes a pass.

The existing [qualification ledger](2026-10-24-multipath-reno-plan.md#candidate-and-run-ledger) and live tracker own cumulative accounting. B continuation uses their remaining capacity under its exact plan inventory, without a new global cap. No operational attempt occurs in this handoff. Unsupported custom I/O/platform/v2/jumbo combinations, native authority, local-backpressure semantics, default Reno and the lack of a consumer adoption claim remain unchanged.

## Binding rules

Every audited slice maps once to its current plan contract, child issue, intended product PR and OmniFocus task. Parent issues are trackers. Dispatch each verified frontier child to a fresh agent with `$implement-architecture-slice`; clear context between children and use a dedicated worktree/feature branch. Same-child scoped re-audit is allowed only while representation, outcome and one-PR boundary remain intact; changes of product intent, representation, topology, adjacent scope or irreversible authority require an operator decision/handoff.

The shared review-loop and contract-closure baselines compose with [the repository execution overlay](../REVIEW-LOOP.md). Preserve single mutation ownership, authority-complete facts, bounded transitional seams, finite evidence, precise-root approach stops and diagnosis before reruns. Product PRs own their completion and successor frontier changes before review. Review and exact-head local/applicable hosted certification precede squash merge, journal and pointer reconciliation; no routine extra frontier PR follows.

Docs merge before issues/task publication. Each child records the reachable 40-character default-branch plan commit and exact heading. Mirrors carry only pointers and current state; plan revision is separate from exact code-head certification. Immediately before reporting dispatchability, verify each frontier child's accepted slice remains on current remote main. No implementation agent is launched by this package.
