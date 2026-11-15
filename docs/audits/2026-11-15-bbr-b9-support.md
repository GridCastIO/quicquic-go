# Experimental BBR primary/backup support (#1382)

[B9 (#1382)](https://github.com/the-sarge/quic-go-fast/issues/1382) implements the [accepted B9 contract](../adr/2026-10-24-multipath-bbr-plan.md#b9) at plan revision `76954048981e4c0da3f1618ef3038fe1ca7d5576`, under [continuation #1374](https://github.com/the-sarge/quic-go-fast/issues/1374). Public Dial/DialEarly, Listen/ListenEarly and server-selected configurations now admit explicitly selected BBR primary/backup through the common capability gate. Reno remains default. This record supersedes B6's public BBR refusal statement; the [historical B6 record](2026-11-14-multipath-b6-support.md) and all frozen evidence retain their original meaning.

## Supported profile and exact exceptions

Support is experimental opt-in draft-21 QUIC v1, Linux amd64, one or two paths, exact granted native UDP sockets and primary/backup scheduling. QUIC v2 configuration, unsupported platforms, missing/conflicting grants and invalid path counts retain refusal; absent negotiation stays ordinary. Aggregation is still rejected for every controller. No application adoption recommendation follows. The underlying BBRv3 controller remains unqualified; full [Q2 (#599)](https://github.com/the-sarge/quic-go-fast/issues/599) is deferred and is not a prerequisite for this scoped support decision.

The [final cost receipt for #1368](2026-11-14-bbr-ordinary-cost-1368/final-qualification/README.md), its [raw summary](2026-11-14-bbr-ordinary-cost-1368/final-qualification/ordinary-results/summary.json) and [independent audit](2026-11-14-bbr-ordinary-cost-1368/final-qualification/ordinary-independent-audit.json) retain twelve clean ordinary observations and these median round-paired ratios:

| Workload | Goodput ratio | CPU/useful-byte ratio | Raw verdict |
| --- | ---: | ---: | --- |
| Mixed bulk | 0.944295141271208 | 1.2081314772756437 | Fails original 0.95 goodput floor and 1.10 CPU ceiling |
| Stateless pressure | 0.9590708299335772 | 1.1593702973325581 | Fails original 1.10 CPU ceiling |

The [owner's exact-result acceptance on #1368](https://github.com/the-sarge/quic-go-fast/issues/1368#issuecomment-6889212163) accepts these final mixed-bulk goodput/CPU and stateless CPU exceptions. Other latency, memory, progress, loss/drop/write/close checks passed, and granted endpoints joined. Original thresholds and raw failures remain unchanged. This is neither a new tolerance nor permission to inherit the exception for changed measured behavior. B9's acceptance decision is recorded in the [continuation contract](../adr/2026-10-24-multipath-bbr-plan.md#decision).

## Candidate-specific applicability

The measured source is `a1c9442f110cca36cb4752b39ce24ae998d76f05`. At B9's base `40642102a8d83660d16a86b61133e8ec92897415`, all production Go and module files match that measured source; subsequent differences are three behavior-preserving staticcheck test switches and the independently reviewed peer-fixture repair in [PR #1381](https://github.com/the-sarge/quic-go-fast/pull/1381). B9 changes only the controller predicate in `Transport.admitMultipath`: it accepts typed `reno` and `bbrv3` selections while keeping platform/version/grant checks. The historical measurement overlay admitted the same BBR controller; B9 makes that capability public, with no overlay or private bypass.

Controller algorithms, sampling, per-path state, registry/scheduler, opportunity planning, native construction/registration/completion, credit return and shutdown are unchanged. Ordinary connections return before the changed predicate. Thus B9 changes no measured ordinary/native execution path and carries the exact #1368 ordinary results without new cost observations. Source equality is not a new performance measurement or a claim about arbitrary workloads.

The [#1368 applicability assessment](2026-11-14-bbr-ordinary-cost-1368/candidate-applicability.md) continues to own the E6/R21/Reno carry and original limits: unprotected endpoint cases and the default-Reno shutdown case do not acquire new native geometry or authority. It does not establish protected-member service deadlines, kernel-pressure traversal or E09 member-branch coverage with rich paths attached. The [final review receipt](2026-11-14-bbr-ordinary-cost-1368/review/replacement-disposition.md) and merged [PR #1377](https://github.com/the-sarge/quic-go-fast/pull/1377), merge `fe5207c2532aed00bb7a9fe3da60746fd4582391`, supersede contemporaneous pending-review statements in the frozen records. B9 separately requires its six public BBR peer cases and the existing exact-head hosted Reno matrix.

## Finite validation and ownership

Typed Config and the common gate own admission; no new representation or mutable policy owner exists. Constructor tests cover both setter orders, cloning, regular/early Dial and Listen and GetConfigForClient. Public useful transfer switches from path zero to a newly opened primary path, then closes both connections and joins every granted endpoint. Existing negative-profile and ordinary-fallback tests preserve refusal and negotiation behavior; existing B1–B3 lifecycle/sampling suites retain per-path feedback coverage. The support regression pins the raw failed cost metrics and historical negative aggregation result.

The existing peer fixture uses the public BBR setter and public admission without an overlay. Its fixed inventory is useful-transfer, abandon-reopen-late-feedback and same-id-migration-rebinding, each client/server. Strict per-case controller, source/build/kernel and missing/duplicate accounting retain the default Reno inventory. These are example-level interoperability witnesses, not universal performance or arbitrary-peer guarantees. Native peer, local certification and review receipts will be linked here when complete; exact ready-head hosted evidence belongs to the product PR before merge.
