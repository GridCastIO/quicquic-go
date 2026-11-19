# Experimental multipath on macOS 27 (MP-MAC Q2, #1495)

[Q2 (#1495)](https://github.com/GridCastIO/quicquic-go/issues/1495) activates the approved public multipath profile on Darwin 27 arm64 under the [accepted Q2 contract](../adr/2026-11-19-macos-multipath-implementation-plan.md#q2--qualify-and-activate-the-approved-public-profile) at plan commit `24cd8a12dbf63bdd8bfbffdcfc07ca987739e465`. It executed the owner-approved [execution protocol](../adr/2026-11-19-macos-multipath-execution-protocol.md) (Q1, [#1494](https://github.com/GridCastIO/quicquic-go/issues/1494)) on its exact candidate, under the owner's separate [activation decision](https://github.com/GridCastIO/quicquic-go/issues/1495#issuecomment-7022088124). Linux amd64 evidence and support records are unchanged and do not qualify Darwin.

## Public profile

The supported profile is unchanged except for its platform domain: experimental, opt-in draft-21 QUIC v1 with at most two active or validating paths including path zero, exact granted native UDP sockets, default Reno primary/backup, and explicitly selected BBR primary/backup or aggregate. Reno aggregate, an enabled Config that lists QUIC v2, and the excluded transport configurations stay refused with `ErrMultipathUnsupportedV1`. Disabled or unnegotiated connections, and granted connections that negotiate QUIC v2, stay ordinary.

The platform domain is now Linux amd64, and Darwin arm64 whose kernel major is 27 (macOS 27). The common capability helper `multipathPlatformAdmitted` owns this typed GOOS/GOARCH/kernel partition; the kernel major comes from the existing Darwin release reader and is read once, on first use by an enabled Config or explicit grant, so ordinary connections never read it. An unreadable release, Darwin amd64 (Intel), iOS, other Darwin majors and every other target are refused before any grant or advertisement. Explicit grants (`Transport.ConfigureMultipathIOV1`) and enabled admission (every constructor and server-selected Config) share the helper; the native grant validator, socket conflicts and the controller, policy and version checks keep their existing owners. Endpoint timing, buffering, scheduling, congestion control and the private-syscall allowlists are unchanged.

## Admitted releases

The predicate admits all of Darwin 27 on arm64 ([D5](../adr/2026-11-19-macos-multipath-execution-protocol.md#decision-table) A). The endpoint, its Go code and the selected toolchains are identical on every 27.x release; socket syscalls, the kqueue poller interaction, write timing, ECN and packet-info behavior belong to the kernel. Q2 observed those kernel-dependent facts on Darwin 27.2.0 (macOS 27.2.1, build 26B131) only. macOS 27.0 and 27.1 are assessed, not observed: the archived [Darwin 27.0 transient-error results](2026-09-22-darwin27-errors/results.md) cover a limited set of C sends and say nothing about the Go poller or the endpoint writer. The residual the owner accepted is an unobserved kernel change to those socket, poller, timing, ECN or packet-info behaviors on another 27.x minor. Later 27.x releases are unobserved by definition.

## Qualification results

Recorded after collection on the exact candidate.

## Continuing coverage

No new required check is selected ([D11](../adr/2026-11-19-macos-multipath-execution-protocol.md#decision-table) A). The hosted macOS unit and integration jobs run on Darwin 25, where Q2's independently stated expectations require refusal: `TestMultipathPublicRefusal`, `TestMultipathHTTP3PublicRefusal` and `TestMultipathPlatformMatchesExpectation` run there, and the public lifecycle tests skip by the independent expectation, never because the production gate refuses. If the hosted image moves to Darwin 27, the macOS unit entries begin exercising admission. The protocol's X2, X4, X5 and X7 rows are re-run by hand on the affected cell when a trigger in D11 changes: a CI Go pin, a Darwin 27 minor on the venue, or `native_endpoint.go`, `multipath_api.go` or `sys_conn_*_darwin.go`. That duty's payoff is detecting a Darwin 27 regression after a trigger; its domain is those rows on the affected cell; its owner is the transport integration and interop maintainer; it retires on equivalent replacement or removal of the profile. Its receipts go in comments on [#1495](https://github.com/GridCastIO/quicquic-go/issues/1495), and a failure opens a blocking regression issue against this profile. The capability helper's tests (`multipath_platform_test.go`) state the partition independently, and its Darwin kernel read uses `sysctl kern.osrelease`, not the production reader.

## Limitations

- All native results are example-level for one host, one kernel, two toolchains and one candidate. They are not a guarantee over every kernel interleaving, general performance, fairness or other Darwin majors or architectures.
- `ConnectionStats().PacketsLost` is not maintained by BBR. Darwin `ru_maxrss` is bytes. `go_heap_live` is live heap after a forced GC, not resident memory.
- The independent-peer rows use IPv4 loopback with distinct ports ([#1530](https://github.com/GridCastIO/quicquic-go/issues/1530)). The family, packet-info and ECN evidence reaches the granted endpoint through the private grant seam that the public grant uses.
- The topology relay forwards payloads only, so ECN and IP metadata are not carried on topology rows.
- UDP ENOBUFS has never been observed natively and stays a residual unless the pressure observation recorded it.
- BBR keeps its unqualified controller status and its historical Linux cost exceptions; no Linux exception transfers to Darwin.
