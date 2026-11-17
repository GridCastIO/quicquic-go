# Integration and platform guide

See the [README](../README.md#adopt-quicquic-go) for release status, the [migration guide](#migrate-to-quicquic-go) for moving to `github.com/GridCastIO/quicquic-go`, and the [published fast.10 release](https://github.com/the-sarge/quic-go-fast/releases/tag/v0.62.1-fast.10) for changes since fast.9, compatibility changes, accepted costs and limitations. The [changelog](../CHANGELOG.md) distinguishes released and unreleased changes. General QUIC and HTTP/3 usage is covered by the [upstream documentation](https://quic-go.net/docs/).

## Release and main selection

| Revision | Included behavior | Evidence and adoption boundary |
| --- | --- | --- |
| `v0.62.1-fast.8` (`8095c72244755f0c1e24f4158253bf09cfbe6e17`) | Eleven-slice bundle, corrected BBR sender and Reno undo; excludes adaptive application-loss thresholds | Published October 23, 2026, with candidate-specific memory, baseline and Linux readiness decisions |
| `v0.62.1-fast.9` (`0f717339f767df5d2e4091b2515266d61f66e2ac`) | Fast.8 plus the idle path-MTU timer fix only; excludes adaptive application-loss thresholds | Published October 25, 2026, from an approved maintenance branch; inherits fast.8 limitations and adds exact-source timer-fix validation |
| `v0.62.1-fast.10` (`24d75daf288469e454f55717ec20463eaf87675a`) | Full main rollup: experimental jumbo and multipath/BBR, DATAGRAM APIs and 128-entry send queue, adaptive loss thresholds, November correctness and storage improvements | Published November 16, 2026; exact-source release validation, no consumer performance qualification; [inventory and limits](releases/v0.62.1-fast.10.md) |
| `main` | Includes fast.10; subsequent development must be assessed at its exact revision | Development branch; release validation and historical measurements do not automatically transfer |

v0.63.0, planned as the first independent release under `github.com/GridCastIO/quicquic-go`, is not yet published; its [release record](releases/v0.63.0.md) describes fast.10's source with the identity transition. Until it is published, use the exact published fast.10 tag for the latest fork prerelease. Fast.9 remains the historical maintenance release. A higher fork prerelease suffix does not imply that all intervening `main` changes are included. Selecting `main` or a pseudo-version requires checking that exact revision's behavior and evidence; fast.8's measurements and advancement exceptions do not transfer automatically. The [#971 implementation closeout](https://github.com/the-sarge/quic-go-fast/issues/971) and [recovery assessment #962](https://github.com/the-sarge/quic-go-fast/issues/962) retain the unmeasured policy and deferred comparison context.

Reno remains default and BBRv3 remains experimental, opt-in and unqualified in the published releases and current `main`. Full [Q2 qualification #599](https://github.com/the-sarge/quic-go-fast/issues/599) awaits its execution preflight and separate operator dispatch. Publishing a fork version does not complete an application's certification or adoption; each consumer owns those decisions and its module replacement.

## Packet I/O and socket ownership

Receive coalescing is enabled on transport-created sockets and on supported external Linux and Windows sockets explicitly registered through `ConfigureExternalPacketIOV1`. External permission requires exclusive packet I/O and terminal socket disposal by the existing owner. Registration does not transfer close ownership, and `Transport.Close` does not restore ordinary raw reads; borrowed sockets intended for reuse must not grant receive-coalescing permission. The [registration API comments](../external_packet_io.go) define the exact contract.

For reusable sockets, `NewManagedPacketEndpointV1` creates an endpoint with exclusive leases. `ConfigureManagedPacketIOV1` binds a lease to the transport. Managed Linux and Windows endpoints retain a normalizing receiver across leases, so endpoint/lease `ReadFrom` continues returning one UDP datagram. Lease close interrupts and joins its I/O and permits reuse; `Transport.Close` alone does not release the lease. Lease return discards already consumed QUIC storage without draining kernel-queued traffic. Endpoint close is terminal. See the [managed endpoint contract](../managed_packet_endpoint.go).

`ConfigureFixedPeerV1` fixes a transport's permitted UDP peer before initialization, guarding receive, ordinary/batched/stateless output and alternate paths. It does not authenticate peer identity or enable migration. The [release notes](https://github.com/the-sarge/quic-go-fast/releases/tag/v0.62.1-fast.8#bundle-behavior-and-consumer-decisions) describe the opt-in network/setup admission, candidate selection and receive-phase extensions.

Multipath V1 is included in fast.10, absent from fast.9, experimental and opt-in; disabled is the default, and connections without it remain ordinary QUIC connections. Its one supported profile is draft-21 QUIC v1 with default Reno primary/backup or explicitly selected BBR primary/backup or aggregate and at most two paths, on Linux amd64. Reno was qualified with Go 1.26.11 and 1.27.4 on the recorded Ubuntu 26.04.1 image with kernel `7.0.0-30-generic`; another toolchain or kernel is outside the tested evidence. Enable it with `Config.ConfigureMultipathV1(true, 2, "primary-backup")`. A caller's socket needs an explicit `Transport` with the `Transport.ConfigureMultipathIOV1` grant, an exact unconnected `*net.UDPConn`; `Dial`, `Listen` and HTTP/3 `Server.Serve` refuse it, while the `Addr` helpers and HTTP/3's default client grant the sockets they own. Other platforms, a `Config.Versions` that lists QUIC v2 and excluded transport configurations (fixed-peer or network admission, candidate groups, send-thread QoS, packet ceilings, external or managed packet I/O) fail with `ErrMultipathUnsupportedV1` before anything is advertised; `ConfigureMultipathV1` accepts only `"primary-backup"` or `"aggregate"` and one or two paths, returning `ErrMultipathInvalidConfigV1` otherwise. Aggregate requires `SetCongestionControlV1("bbrv3")`; either setter order works, and every constructor rechecks the final pair so a later change to Reno is refused with `ErrMultipathUnsupportedV1`. A connection that negotiates QUIC v2, or whose peer doesn't negotiate multipath, stays ordinary; check `Conn.MultipathNegotiatedV1`. Before closing a `Transport` that surviving paths may still use, wait on `Conn.WaitTransportDetachedV1`; after `Transport.Close`, `Transport.WaitMultipathIOStoppedV1` returns the socket's write authority. The qualification evidence is the [native receipt](audits/2026-11-03-multipath-e6-receipt.md), carried to those Go patch releases by the [November compiler reassessment](adr/2026-10-24-multipath-endpoint-plan.md#november-go-patch-reassessment), with its [writer-yield supplement](audits/2026-11-12-native-writer-yield-r21/README.md), the [independent interoperability receipt](audits/2026-11-09-multipath-r17-receipt.md) and the [ordinary-peer cost receipt](audits/2026-11-12-multipath-r18-delivery-receipt.md), which keeps two owner-accepted CPU-per-useful-byte exceptions. BBR's public primary/backup evidence and exact accepted cost exceptions are recorded in the [B9 support receipt (#1382)](audits/2026-11-15-bbr-b9-support.md), including six native Go 1.27.4 interoperability cases through public admission. BBR aggregate is experimental after B11’s positive fixed comparison; the [B12 support record (#1385)](audits/2026-11-15-bbr-b12-support.md) owns its aggregate evidence. Reno aggregate remains refused; B5’s negative comparison concerns the retired arrival policy. Additional validated paths start as local backups: each sending endpoint must call `Path.SetLocalUseV1("active")` on the paths it intends to use concurrently. Selecting aggregate alone does not activate them; `Path.StateV1` reports their local use. Backups remain excluded from ordinary aggregate work while an active path is eligible, with existing PTO precedence unchanged. The underlying BBRv3 controller remains experimental and unqualified while full [Q2 (#599)](https://github.com/the-sarge/quic-go-fast/issues/599) is deferred. No consumer adoption recommendation follows. Isolate these calls in an integration adapter, like the other fork additions.

The [ordinary-flow cost comparison (#1368)](https://github.com/the-sarge/quic-go-fast/issues/1368) measured the native endpoint against an unregistered, controller-matched BBR baseline on the recorded Linux venue. Across three paired rounds per workload, ordinary goodput was 0.944295141271208 of baseline with mixed background traffic and 0.9590708299335772 under stateless-packet pressure; server CPU per useful byte was 1.2081314772756437 and 1.1593702973325581 times baseline, respectively. The CPU denominator includes useful background bytes in the mixed workload. The owner accepted these exact measured tradeoffs: mixed-bulk misses the original 0.95 goodput floor and 1.10 CPU ceiling, while stateless-pressure misses CPU; the raw verdicts remain failed. All other qualification checks and the six BBR interoperability cases pass. The [final receipt](audits/2026-11-14-bbr-ordinary-cost-1368/final-qualification/README.md) records the source, workload, measurement-only overlays and evidence limits. B9 (#1382) separately enables experimental public BBR primary/backup after checking source applicability and public peer evidence. The original measured exceptions do not become tolerances for future changed workloads. Aggregation, full Q2 (#599) and application qualification remain outside that decision.

A grant covers the whole transport, not only its multipath connections. Every connection dialed or accepted on a granted transport, including ordinary ones that never negotiate multipath, sends through the native endpoint, the socket writer the grant installs, and so does `Transport.WriteTo`. For connections, an expired local queue or write deadline there is backpressure, not a send failure: the connection stays open, bounded by its usual handshake, idle and path-validation timeouts. `WriteTo` instead returns `ErrMultipathBackpressureV1`, plus `ErrMultipathDeadlineV1` when its deadline expired; neither proves the packet was not sent. Each endpoint has a budget of 4,096 participants, shared by ordinary and multipath connections: a connection takes one on its own transport and one on each other granted transport it sends from through `Conn.OpenPathV1`, `Path.MigrateV1` or `Conn.AddPath`. When a transport's budget is full, a dial on it fails with `ErrMultipathResourceLimitV1`, and its server refuses a new connection with CONNECTION_REFUSED, or drops the first packet when it cannot send the refusal in time. A connection that needs a new participant there also gets that error from `OpenPathV1` from it or `MigrateV1` to it, and skips an `AddPath` probe from it until its probe timer retries. Closing a connection does not promise to free its participant at once.

## Platform controls

Offload availability depends on the host, packet-I/O path and explicit permissions. Generic platform CI does not prove native offload engagement. Qualified macOS batching uses the private `sendmsg_x` syscall with kernel qualification and a startup self-check. Build with `-tags quic_go_no_private_syscalls` to disable private-syscall paths.

On macOS, a participating wrapper implementing `ReadBatch` and `ReadBatchSlotsV1Conn` can opt into multiple datagrams per read; the default is one slot. Each buffer is one byte larger than the largest packet; a completely filled buffer is treated as truncated and dropped. The adapter owns its receive call; see the [read-slot API contract](../sys_conn.go) for bounds and platform exclusions. This is distinct from the fork's retired standalone `recvmsg_x` receive-batching experiment. Apple-silicon macOS also offers opt-in send-thread QoS through `ConfigureSendThreadQoSV1`; see its [contract and per-connection status](../send_thread_qos.go).

Set these environment variables to `true` to disable the named behavior:

| Variable | Effect |
| --- | --- |
| `QUIC_GO_DISABLE_GSO` | Disable segmented send, including Windows USO |
| `QUIC_GO_DISABLE_GRO` | Disable Linux GRO and Windows URO receive coalescing |
| `QUIC_GO_DISABLE_SHORT_GSO_SEGMENTS` | Disable equal-size short-DATAGRAM batching; full-size segmentation remains available |
| `QUIC_GO_DISABLE_SENDMSG_X` | Disable macOS batch send |
| `QUIC_GO_DISABLE_RECVMSG_X` | Keep one macOS adapter read slot |
| `QUIC_GO_DISABLE_SEND_QOS` | Disable send-thread QoS for new connections |

## Trace privacy

Qlog traces can contain sensitive HTTP headers and QUIC tokens. The QUIC and HTTP/3 default tracers create missing `QLOGDIR` directories with mode `0700` and new trace files with mode `0600`, subject to umask on Unix. Existing directory permissions are preserved; choose a trusted directory and parent path. An existing trace path, including a symlink, disables tracing for that connection instead of overwriting it. Restrict access to trace archives and review them before sharing.

## Migrate to quicquic-go

quicquic-go declares module `github.com/GridCastIO/quicquic-go` and keeps the root package name `quic` ([ADR 0014](adr/0014-independent-module-identity.md)). v0.63.0 is planned and not yet published. The commands below that name it work only after publication.

1. **Change imports.** Replace the `github.com/quic-go/quic-go` prefix with `github.com/GridCastIO/quicquic-go` in root and subpackage imports, for example `github.com/GridCastIO/quicquic-go/http3`. Use that exact case: `github.com/gridcastio/quicquic-go` is a different module path and fails with a path mismatch, and the module cache stores the path as `github.com/!grid!cast!i!o/quicquic-go`. Identifiers such as `quic.Config` and `http3.Server` do not change. For example, to rewrite quoted import paths in place:

   ```sh
   git grep -lz 'github.com/quic-go/quic-go' -- '*.go' |
     xargs -0 perl -pi -e 's{"github\.com/quic-go/quic-go((?:/[^"]*)?)"}{"github.com/GridCastIO/quicquic-go$1"}g'
   ```

   `goimports` and the `goimports` formatter in golangci-lint write the root import as `quic "github.com/GridCastIO/quicquic-go"`. The path's last element is not the package name, so they add the explicit name. Accept it; it changes nothing else.
2. **Require the release.** Once v0.63.0 is published, run `go get github.com/GridCastIO/quicquic-go@v0.63.0` and select later versions explicitly under the [compatibility promise](adr/0016-version-aware-compatibility.md). Inherited tags such as `v0.62.0` and the `v0.62.1-fast.N` prereleases declare the old path and cannot be selected for the new one.
3. **Drop the old replacement.** When nothing in your build still needs the old path, both `go mod why -m github.com/quic-go/quic-go` and `go mod graph | grep 'github.com/quic-go/quic-go@'` report no requirement. Then run `go mod edit -dropreplace=github.com/quic-go/quic-go` and `go mod tidy`, and commit `go.mod` and `go.sum`.
4. **Migrate dependencies that expose QUIC types first.** Defined types from the old and new paths are distinct, so a `*quic.Conn` from one cannot be passed where the other is expected. A dependency whose API exposes QUIC types must move to the new path before or together with your application. For GridCast and tapmux, that means wiremux's cutover in [GridSwarm/wiremux#2175](https://github.com/GridSwarm/wiremux/issues/2175) comes first. Until then, the old module stays in the graph alongside the new one.
5. **Keep existing adaptations.** Use keyed `Config` literals; positional literals do not compile. Inspect HTTP/3 errors as the [error-handling guide](../http3/README.md#error-handling) describes. Go 1.26.0 remains the minimum.

From fast.10, the module path is the only difference: no Go source changed except identity. From upstream v0.62.0, also expect the differences the [changelog](../CHANGELOG.md) records for the fast series, including:

- this project's additional `...V1` APIs, among them packet I/O, managed endpoints, fixed peers, admission, congestion-control selection, DATAGRAM admission, jumbo and multipath;
- the 128-entry DATAGRAM send queue and the 1,024-entry receive queue;
- the reassembly gap limit of 4,096;
- the qlog `Path` fields that break positional literals;
- HTTP/3 error conversion and stricter header validation.

The [fast.10 release record](releases/v0.62.1-fast.10.md#compatibility-and-support) lists the latest of these.

To roll back, return to the previous source and dependency state through ordinary version control. To return to upstream quic-go, first remove or adapt calls to this project's additional APIs, then restore the `github.com/quic-go/quic-go` imports and requirement. Verify the selected upstream version and your application's compatibility before deployment.

## Development toolchains

Use Go 1.27.4 for repository maintenance; [`.go-version`](../.go-version) records that choice for version managers that support it. The Go command itself does not read this file. Select the exact maintainer or compatibility toolchain explicitly:

```sh
GOTOOLCHAIN=go1.27.4 go test ./...
GOTOOLCHAIN=go1.26.11 go test ./...
```

These commands may download the named toolchain but do not permit automatic upgrades beyond it. CI installs the exact version for each lane, sets `GOTOOLCHAIN=local` to prevent automatic toolchain switching, and verifies the effective version. Integration CI also verifies the FIPS and vendor fixture modules. The root and nested integration modules retain their `go 1.26.0` language minimum. When reproducing a compatibility lane with a version manager, select Go 1.26.11 explicitly and use `GOTOOLCHAIN=local`.

The development journal records merged work and validation, and [DEV-JOURNAL.md](DEV-JOURNAL.md) holds its entries recorded in this repository; [GLOSSARY.md](../GLOSSARY.md) defines domain terminology; the [release runbook](runbooks/release.md) describes publication.
