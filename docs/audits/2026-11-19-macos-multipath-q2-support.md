# Experimental multipath on macOS 27 (MP-MAC Q2, #1495)

[Q2 (#1495)](https://github.com/GridCastIO/quicquic-go/issues/1495) activates the approved public multipath profile on Darwin 27 arm64 under the [accepted Q2 contract](../adr/2026-11-19-macos-multipath-implementation-plan.md#q2--qualify-and-activate-the-approved-public-profile) at plan commit `24cd8a12dbf63bdd8bfbffdcfc07ca987739e465`. It executed the owner-approved [execution protocol](../adr/2026-11-19-macos-multipath-execution-protocol.md) (Q1, [#1494](https://github.com/GridCastIO/quicquic-go/issues/1494)) on its exact candidate, under the owner's separate [activation decision](https://github.com/GridCastIO/quicquic-go/issues/1495#issuecomment-7022088124). Linux amd64 evidence and support records are unchanged and do not qualify Darwin.

## Public profile

The supported profile is unchanged except for its platform domain: experimental, opt-in draft-21 QUIC v1 with at most two active or validating paths including path zero, exact granted native UDP sockets, default Reno primary/backup, and explicitly selected BBR primary/backup or aggregate. Reno aggregate, an enabled Config that lists QUIC v2, and the excluded transport configurations stay refused with `ErrMultipathUnsupportedV1`. Disabled or unnegotiated connections, and granted connections that negotiate QUIC v2, stay ordinary.

The platform domain is now Linux amd64, and Darwin arm64 whose kernel major is 27 (macOS 27). The common capability helper `multipathPlatformAdmitted` owns this typed GOOS/GOARCH/kernel partition; the kernel major comes from the existing Darwin release reader and is read once, on first use by an enabled Config or explicit grant, so ordinary connections never read it. An unreadable release, Darwin amd64 (Intel), iOS, other Darwin majors and every other target are refused before any grant or advertisement. Explicit grants (`Transport.ConfigureMultipathIOV1`) and enabled admission (every constructor and server-selected Config) share the helper; the native grant validator, socket conflicts and the controller, policy and version checks keep their existing owners. Endpoint timing, buffering, scheduling, congestion control and the private-syscall allowlists are unchanged.

## Admitted releases

The predicate admits all of Darwin 27 on arm64 ([D5](../adr/2026-11-19-macos-multipath-execution-protocol.md#decision-table) A). The endpoint, its Go code and the selected toolchains are identical on every 27.x release; socket syscalls, the kqueue poller interaction, write timing, ECN and packet-info behavior belong to the kernel. Q2 observed those kernel-dependent facts on Darwin 27.2.0 (macOS 27.2.1, build 26B131) only. macOS 27.0 and 27.1 are assessed, not observed: the archived [Darwin 27.0 transient-error results](2026-09-22-darwin27-errors/results.md) cover a limited set of C sends and say nothing about the Go poller or the endpoint writer. The residual the owner accepted is an unobserved kernel change to those socket, poller, timing, ECN or packet-info behaviors on another 27.x minor. Later 27.x releases are unobserved by definition.

## Qualification results

The accepted candidate is `463568a9ae324c9d61c638bb7ac72beeb430eab2` (tree `9983bfa8630c4055ef8420b76add713edc425c4b`). It was collected clean, X1 through X13, on `mbp128` (Mac16,5, M4 Max with 12 performance and 4 efficiency cores, macOS 27.2.1 build 26B131, Darwin 27.2.0) with go1.27.4 and go1.26.11. The protocol host gate was clear before and after all 124 observation invocations. None was contaminated, held or failed, and no replacement attempt was used. The receipts on [PR #1585](https://github.com/GridCastIO/quicquic-go/pull/1585) are the evidence of record:
- [certification](https://github.com/GridCastIO/quicquic-go/pull/1585#issuecomment-7037930356);
- [X1–X10](https://github.com/GridCastIO/quicquic-go/pull/1585#issuecomment-7038066523);
- [X11](https://github.com/GridCastIO/quicquic-go/pull/1585#issuecomment-7039421580);
- [X12 and X13](https://github.com/GridCastIO/quicquic-go/pull/1585#issuecomment-7040944588).

The raw results root for each candidate, including its failed attempts, is retained on the venue under rule 5.

### Results by step

- **X2 (T27, T26):** all eight blocked-writer cases passed once each on both toolchains. The four native-traversal cases (`eagain-to-deadline`, `queued-expiry`, `active-close-join` and `bbr-protected-close-join`) had a poller witness, `injected: 0` and `traced: false`, with native return 0.03–2.08 ms after the deadline. `bbr-protected-close-join` recorded `borrowed-through-fence`. The other four keep their own classes: `expired-before-dispatch-successor` is `expired-claim-unsubmitted` (`injected: 0`, `traced: false`), `first-send-eperm` is `simulated` (two injected errors), `constructed-segmentation-prefix` is `constructed`, and `scalar-emsgsize` is `native-size-feedback`.
- **X3:** the `powermetrics` capture passed contiguity in one attempt (60 records).
- **X4 (T27, T26):** every family case (IPv4-only, IPv6-only, dual-stack mapped and native) received CE and sent ECT(0), with the packet-info destination and interface. Refusals and post-join authority held, and contention was complete with `fault: none`.
- **X5 (T27, T26 race):** 8 of 8 passed with no race reports.
- **X6:** complete at the D7 load of 98,304 writes, `fault: none`, `pressure_wait: not-observed`, and zero errors in every class. ENOBUFS was not observed.
- **X7 (T27, T26, O27):** every required name ran with one terminal action against the inventory at `9dee3cf56` plus Q2's acceptance tests. The only skips are the two expected refusal tests.
- **X8:** the ECN-disabled ordinary control passed 3 of 3.
- **X9:** the pinned independent peer built against SDK 27.2 on arm64. Its ordinary control and discovery passed.
- **X10:** Reno 16 of 16 plus negotiated-zero, BBR primary/backup 6 of 6, and BBR aggregate 6 of 6. Each scenario and role ran once.
- **X11:** the four judged Reno cells missed narrowly, and the owner accepted them as measured (below). Medians, as goodput / CPU per useful byte / control p99 margin:
  - stream: 0.956 / 1.110 / +442 µs;
  - datagram: 1.038 / 1.010 / +1,097 µs;
  - mixed-bulk: 0.952 / 1.089 / −4,932 µs, with one round's opted-in server peak RSS ×1.178;
  - stateless-pressure: 0.897 / 1.152 / +2,015 µs, with one round's peak RSS ×1.154.

  Stateless-pressure is the expected R0 result: there is no reset batching, and the opted-in arm answered about 15 times as many stateless resets. BBR is reported. Its goodput / CPU medians are stream 0.968 / 1.040, datagram 0.951 / 1.027, mixed-bulk 1.136 / 1.223 and stateless-pressure 0.916 / 1.116. Both O27 smoke pairs delivered useful bytes.
- **X12:** both lifecycle attempts succeeded at `closed`, with the backup detached and the grant joins complete. Retired-phase `go_heap_live` / `peak_rss` was 1,800,480 / 20,316,160 B for Reno and 3,624,328 / 21,200,896 B for BBR.
- **X13:** all 37 runs completed: 35 BBR runs and two reported Reno primary/backup controls. The BBR aggregate verdict passed, with these medians:
  - disjoint aggregate ÷ better single arm: 2.004 (≥ 1.20);
  - disjoint aggregate ÷ pair: 1.005 (≥ 0.95);
  - shared competitor beside the aggregate ÷ beside the pair: 1.092 (≥ 0.90).

### Combination verdicts

- **Reno primary/backup (default):** qualified. Correctness rows X2–X10 passed, ordinary cost was accepted as measured by the owner, and lifecycle memory is as reported.
- **BBR primary/backup:** qualified. Correctness rows passed, and the reported ordinary cost was accepted as measured by the owner.
- **BBR aggregate:** qualified. Correctness rows passed, the X13 topology gates passed, and the reported ordinary cost was accepted as measured.

### Owner dispositions and earlier candidates

- **X11 on `463568a9a`.** The owner accepted all four Reno results and BBR's numbers exactly as measured ([#1495 comment 7039863535](https://github.com/GridCastIO/quicquic-go/issues/1495#issuecomment-7039863535)). Host load was heavy during collection: a 1-minute load average of 14–77, with runner VMs, Spotlight and foreign builds. This was supplementary and not a pass/fail input; D10 A reports performance-cluster activity without judging it. Whether `sendmsg_x` batching raises the peak RSS is followed up in [#1599](https://github.com/GridCastIO/quicquic-go/issues/1599).
- **`016bc60c7`.** X1 and X2 passed, then X3 failed. The capture reader dated each record by the next record's NUL ([#1586](https://github.com/GridCastIO/quicquic-go/issues/1586), fixed by [PR #1587](https://github.com/GridCastIO/quicquic-go/pull/1587)). The owner approved the fix and a restart ([#1495 comment 7025205252](https://github.com/GridCastIO/quicquic-go/issues/1495#issuecomment-7025205252)).
- **`a8193c627`.** X1–X10 passed. X11 failed for Reno: goodput 0.77–0.81, and CPU per useful byte 1.24–1.42. BBR's reported goodput was 0.41–0.63. The owner chose to fix first ([#1495 comment 7028382059](https://github.com/GridCastIO/quicquic-go/issues/1495#issuecomment-7028382059)). That candidate's X12 and X13 ran for information only.
  - The send-path fixes were [#1589](https://github.com/GridCastIO/quicquic-go/issues/1589), [#1590](https://github.com/GridCastIO/quicquic-go/issues/1590) and [#1592](https://github.com/GridCastIO/quicquic-go/issues/1592).
  - Collection then restarted from X1 on `463568a9a`.

Neither earlier candidate's results can activate anything.

### Post-collection change (rule 3)

After collection, one prose-only commit filled in this section and corrected the #1590 entry in `CHANGELOG.md`, which still said Darwin grants were publicly refused. The CHANGELOG correction came from a low concern raised by the `ras verify` of review run `20261119T220039-73fede99ed3971220f0048df`, pinned to `463568a9a`. No selected build, fixture, test or receipt check reads either file.

## Continuing coverage

No new required check is selected ([D11](../adr/2026-11-19-macos-multipath-execution-protocol.md#decision-table) A). The hosted macOS unit jobs (Go 1.26.11 and 1.27.4) run the root and `http3` packages on Darwin 25, where Q2's independently stated expectations require refusal: `TestMultipathPublicRefusal`, `TestMultipathHTTP3PublicRefusal` and `TestMultipathPlatformMatchesExpectation` run there, and the public lifecycle tests skip by the independent expectation, never because the production gate refuses. If the hosted image moves to Darwin 27, those unit entries begin exercising admission. The hosted macOS integration job runs only the `integrationtests` packages and is credited only with ordinary regressions, on either image. The capability helper's tests (`multipath_platform_test.go`) state the partition independently, and their Darwin kernel read uses `sysctl kern.osrelease`, not the production reader.

D11 A also selects a manual re-run duty for the protocol's X2, X4, X5 and X7 rows on the affected cell when one of its triggers changes. D11's row in the protocol is the single definition of that duty: its triggers, the affected cell per trigger, the owner's approval of the substituted identity, where receipts go, the regression route and its payoff, domain, owner and retirement. This record does not restate it.

## Limitations

- The `ordinarycost` Go fixtures now grant through the public `Transport.ConfigureMultipathIOV1` on Darwin, as on Linux, so every Darwin opted-in cost arm records `grant_seam` "public Transport.ConfigureMultipathIOV1" and advertises multipath; before Q2 the Darwin arms granted through the private seam and never advertised. Only the opted-in `mixed-bulk` arm negotiates a second path. This follows from the D14 lift of Darwin's `negotiated_multipath`.
- All native results are example-level for one host, one kernel, two toolchains and one candidate. They are not a guarantee over every kernel interleaving, general performance, fairness or other Darwin majors or architectures.
- `ConnectionStats().PacketsLost` is not maintained by BBR. Darwin `ru_maxrss` is bytes. `go_heap_live` is live heap after a forced GC, not resident memory.
- The independent-peer rows use IPv4 loopback with distinct ports ([#1530](https://github.com/GridCastIO/quicquic-go/issues/1530)). The family, packet-info and ECN evidence reaches the granted endpoint through the private grant seam that the public grant uses.
- The topology relay forwards payloads only, so ECN and IP metadata are not carried on topology rows.
- UDP ENOBUFS has never been observed natively and stays a residual unless the pressure observation recorded it.
- BBR keeps its unqualified controller status and its historical Linux cost exceptions; no Linux exception transfers to Darwin.
