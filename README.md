# quicquic-go

quicquic-go is an independently maintained QUIC and HTTP/3 implementation in Go, focused on transport performance and practical application integration.

It is built for sustained bulk DATAGRAM and stream transfers, with explicit application control over sockets, connection admission and traffic delivery. It combines efficient cross-platform packet I/O, lower allocation and copying costs, and extended congestion and loss recovery, while keeping standard QUIC and HTTP/3 interoperability. The module is `github.com/GridCastIO/quicquic-go`; the root package is `quic`. Requires **Go 1.26.0+**.

**Release status:** v0.63.0, the first independent release under this module path, is planned and **not yet published**. The latest published release is [v0.62.1-fast.10](https://github.com/the-sarge/quic-go-fast/releases/tag/v0.62.1-fast.10), from November 16, 2026. It is a prerelease of the earlier quic-go-fast fork, still declaring `github.com/quic-go/quic-go`. It carries experimental opt-in jumbo and multipath/BBR capabilities, DATAGRAM admission APIs, adaptive loss thresholds, and correctness and storage improvements. The planned v0.63.0 adds only the [identity transition](docs/releases/v0.63.0.md) to that source.

Fast.10 also increases the application DATAGRAM send queue from 32 to 128 entries, raises the reassembly gap limit to 4,096, tightens HTTP/3 metadata handling, and adds qlog path fields that require updating existing positional literals. The [release notes](https://github.com/the-sarge/quic-go-fast/releases/tag/v0.62.1-fast.10) and [release record](docs/releases/v0.62.1-fast.10.md) retain compatibility guidance, accepted costs and evidence limits. Historical measurements below do not measure the complete fast.10 source.

## Improvements over the v0.62.0 baseline

Shipped capabilities combine this project's own work and selected upstream fixes. See the [integration guide](docs/usage.md) for API ownership and platform requirements.

- **Application-owned transport integration.** External packet I/O, reusable managed socket leases, fixed-peer filtering, bounded connection setup, candidate selection and receive-phase control give applications explicit resource and traffic ownership.
- **Managed ECN and path-MTU discovery.** Qualified managed paths preserve ECN on Linux, macOS, FreeBSD and Windows, with path-MTU discovery on qualified Linux and macOS leases.
- **Burst capacity and ACK control.** Bounded 1,024-entry received-DATAGRAM queues expose drop counters. Opt-in local ACK thresholds of 2–32 packets support known compatible peer controllers; negotiated ACK Frequency remains unimplemented.
- **Native batching across platforms.** Linux GRO, Windows USO/URO and qualified macOS batch sends move more packets per socket call. Equal-size short DATAGRAM packets share segmented sends, with capability checks and ordinary socket fallbacks.
- **Lower allocation and linear stream copying.** Reject DATAGRAM overflow before allocation and remove an intermediate parser copy. Large `TryWriteAll` transfers replace quadratic tail copying with linear copying. HTTP/3 tracing and receive cleanup reduce allocation and retained memory.
- **Recovery from spurious loss.** Reno restores a cutback when all supporting losses are proved spurious.
- **Connection lifecycle and path reliability.** Correct handshake sizing, path validation, cancellation, socket cleanup and HTTP/3 reuse/shutdown. Fast.9 also keeps idle path-MTU discovery progressing.

**Experimental BBRv3 for lossy bulk transfers.** Opt in with `Config.SetCongestionControlV1("bbrv3")`. The measured benefit below is against fast.8 Reno. BBR remains **unqualified**: higher memory use, control-message latency and adverse Reno coexistence remain limitations. **Reno remains the default.** See the [release's BBR status](https://github.com/the-sarge/quic-go-fast/releases/tag/v0.62.1-fast.8#corrected-bbr-and-subsequent-recovery).

**Experimental multipath.** Opt in with `Config.ConfigureMultipathV1(true, 2, "primary-backup")` and an explicit native UDP socket grant. Draft-21 QUIC v1 on Linux amd64 supports default Reno or explicitly selected BBR. BBR also accepts `"aggregate"`, using uncoupled paced byte round-robin after its positive fixed comparison. BBR retains exact accepted ordinary-cost exceptions and its unqualified controller status. No universal performance, fairness or adoption claim follows. See the [tested profile, evidence and limitations](docs/audits/2026-11-15-bbr-b12-support.md).

## Performance evidence

Historical measurements of individual changes, using the explicit baselines below:

| Change | Recorded result | Comparison baseline and workload |
| --- | --- | --- |
| [Short DATAGRAM batching](https://github.com/the-sarge/quic-go-fast/issues/743#issuecomment-6331858628) | **2.48× throughput**, sender/receiver CPU per GiB **−57%/−53%** | On versus off at `642f014e`; downstream Linux network namespaces |
| [Linux GRO](https://github.com/the-sarge/quic-go-fast/blob/23c83b9896980511286ca8b81cd632f7ec56afed/docs/audits/2026-09-11-g2-gro-results.md) | **1.26× throughput**, receive syscalls/datagram **×0.263** | GRO on versus off in the adoption build, peer GSO on in both; paired Linux loopback transfers |
| [Windows USO](https://github.com/the-sarge/quic-go-fast/blob/23c83b9896980511286ca8b81cd632f7ec56afed/docs/audits/2026-09-11-w2-uso-results.md) | **3.01× throughput**, send submissions/packet **×0.0815** | USO on versus off in the same Windows message-I/O build; paired hosted Windows loopback transfers |
| [macOS batch send](https://github.com/the-sarge/quic-go-fast/blob/23c83b9896980511286ca8b81cd632f7ec56afed/docs/audits/2026-09-12-d1-sendmsgx-results.md) | **1.17× throughput**, send syscalls/packet **×0.126** | Batch versus per-packet sends in the adoption build; paired Darwin 25 arm64 loopback transfers |
| [Experimental BBRv3](https://github.com/the-sarge/quic-go-fast/blob/563785cf44a6be8b36f360bdf0e80acdf59df8ae/docs/audits/2026-10-22-bundle-990-readiness/result.md) | **14.06× STREAM / 14.27× DATAGRAM useful throughput** | Fast.8 BBR versus fast.8 Reno; Linux emulation, 100 Mbps each way, 100 ms base RTT, 0.1% random forward loss; median of five paired ratios per traffic type |

These are historical, workload-specific results; they do not establish an aggregate speedup of the current source over current upstream quic-go. The short-DATAGRAM result also raised mean RTT by 22.7 µs and lifetime minimum RTT by 9.8 µs, accepted under the [recorded decision (#743)](https://github.com/the-sarge/quic-go-fast/issues/743#issuecomment-6331925155). The [fast.1 measurements](CHANGELOG.md#recorded-measurements) and [fast.8 release notes](https://github.com/the-sarge/quic-go-fast/releases/tag/v0.62.1-fast.8) retain the baselines, accepted costs and limitations.

<a id="use-the-fork"></a>

## Adopt quicquic-go

Installation instructions will name the published tag once v0.63.0 is released; no version of `github.com/GridCastIO/quicquic-go` is available yet. To move an application from the fast series or from upstream quic-go, follow the [migration guide](docs/usage.md#migrate-to-quicquic-go). Until v0.63.0 is published, fast.10 remains available as its [release notes](https://github.com/the-sarge/quic-go-fast/releases/tag/v0.62.1-fast.10) describe.

Use keyed `Config` literals; positional literals no longer compile. Applications inspecting HTTP/3 errors should follow the [error-handling migration guide](http3/README.md#error-handling). [Integration instructions](docs/usage.md) cover this project's additional APIs and socket ownership. The [compatibility promise](docs/adr/0016-version-aware-compatibility.md) defines what patch and minor releases may change.

## Support and development

Unit and integration CI run on Linux, macOS and Windows, with additional Linux race coverage. Other cross-compiled targets are build-only; native offload support depends on the host and packet-I/O path. Review the [fast.10 changes and support boundaries](https://github.com/the-sarge/quic-go-fast/releases/tag/v0.62.1-fast.10) alongside the [historical fast.8 limitations](https://github.com/the-sarge/quic-go-fast/releases/tag/v0.62.1-fast.8), with current fast.10 guidance authoritative where it supersedes earlier statements, and evaluate the release you select against your workloads. Consumer certification and adoption remain separate decisions.

- [Changelog](CHANGELOG.md) · [Report an issue](https://github.com/GridCastIO/quicquic-go/issues) · [Security policy](SECURITY.md) · [Upstream quic-go usage documentation](https://quic-go.net/docs/)
- [Development toolchains](docs/usage.md#development-toolchains) · [Development journal](docs/DEV-JOURNAL.md) · [Evidence index](docs/audit-evidence.md) · [Release runbook](docs/runbooks/release.md)

## Origins and license

quicquic-go derives from [quic-go](https://github.com/quic-go/quic-go), and quic-go v0.62.0 is its historical baseline. It is maintained independently and adopts individual upstream changes only after validation here ([ADR 0015](docs/adr/0015-independent-maintenance.md)). The baseline records provenance; it does not promise upstream release tracking or API parity. The `v0.62.1-fast.N` prereleases were published as the quic-go-fast fork under the old module path, and they remain [recorded as published](CHANGELOG.md).

Built on the work of the quic-go authors and contributors. The [MIT license](LICENSE), with its copyright notice and author credits, is unchanged.

Upstream quic-go documentation describes upstream behavior, not this project's supported behavior. That includes [quic-go.net](https://quic-go.net/docs/) and the inherited [FIPS140.md](FIPS140.md), [FUZZING.md](FUZZING.md) and [http3/README.md](http3/README.md) apart from its error-handling section. This README, the [integration guide](docs/usage.md), the [changelog](CHANGELOG.md) and the [release records](docs/releases/) define what this project supports. The upstream logo and brand assets keep their [separate usage policy](assets/LICENSE.md).
