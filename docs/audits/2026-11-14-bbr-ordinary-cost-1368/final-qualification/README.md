# Final native qualification receipt (#1368)

**Native inventory complete; ordinary raw verdict FAILED with exact owner-accepted exceptions; six-case BBR interoperability PASS. Full-panel review and final local certification are COMPLETE; exact ready-head required checks remain PENDING. See the [review receipt](../review/replacement-disposition.md).** This receipt covers [BBR ordinary-flow cost (#1368)](https://github.com/the-sarge/quic-go-fast/issues/1368), not public BBR multipath enablement, aggregation, full Q2 qualification or application adoption. The [candidate applicability record](../candidate-applicability.md) preserves the scoped Reno/native-owner evidence carry and remaining review obligations.

## Source, venue and commands

Both campaigns used product `a1c9442f110cca36cb4752b39ce24ae998d76f05`, tree `aa697c0ef117bdf4dc74e712cbf30182b4c8cb97`, Go/module-identical to retained E09 plus its deterministic fixture correction at `59ca2a3a3d6dc9419f9bd09ae4b1e6197153e103`. The source archive SHA-256 is `3a4c5b1013f2d3739965c939d6a03a83b7b830bac1040749133f49b3fd7f991a`. The [launch identity](launch.json), [ordinary manifest](ordinary/manifest.json) and [interop manifest](interop/manifest.json) bind the source, exact measurement-only overlays and historical B5 drivers. E11 and observer runtime are absent.

Execution was native Linux amd64 on Minimax, kernel `7.0.0-30-generic`, Go 1.27.4, `GOAMD64=v1`, `CGO_ENABLED=0`, empty `GOFLAGS`/`GOEXPERIMENT`, with the interop image run through rootless Podman. The [ordinary identity](ordinary-results/identity.json) records server cores 8–11, client cores 12–15 and sibling-aware contamination accounting. The [interop aggregate identity](interop-results/matrix-result.json) also pins picoquic, picotls, kernel and peer driver.

| Artifact | SHA-256 / image identity |
| --- | --- |
| [Ordinary binary build](ordinary/build-receipt.json) | `b11e8b59b4782679617fec6eff4768e8db2a08b0298af63b5cb7b54e3cd83a3a` |
| [Interop test binary build](interop/build-receipt.json) | `666a1b3d9a4e2b6a068cffb14fb2d3462c4f2f1eaa64568b311c5426ca3418df` |
| Peer binary | `52e8e7cfb6f098370b84494c7b466f8628d027d769df235e22e0c3b18f04960c` |
| [Interop image](interop/image-inspect.json) | `sha256:4f07478e800375ddcbf617c9a86d1f101cd140c56903e28a0c2d6d0d4c226411` |

The [ordinary launch command](launch.json), [phase launcher](commands.sh), [sequential interop helper](interop-sequence.py), [case launcher](interop-case.sh) and [nine interop command receipts](interop-independent-audit.json) preserve the executed commands. Build receipts contain exact Go overlay commands and environments. Ordinary timing ended before image setup began. No workload or temporary container remains. The [local certification receipt](local-cert/receipt.json) separately records full affected suites, focused races, vet/tidy and source checks on Darwin arm64, plus Linux/FreeBSD/Windows amd64 compilation; compilation is not native execution.

## Ordinary cost and explicit acceptance

The [original summary](ordinary-results/summary.json), [12 raw observations](ordinary-results/observations.jsonl), per-role files and [independent audit](ordinary-independent-audit.json) agree: two cells × two profiles × three alternating paired rounds, all clean, no replacements and no quiet waits. Maximum foreign CPU was 0.282722 seconds. The frozen B5 driver retained its 10-second warmup, 60-second window, original seeds/affinity and 135-second invocation bound. Both profiles used BBR.

| Cell | Median paired ordinary goodput | Median paired CPU/useful byte | Original failed checks |
| --- | ---: | ---: | --- |
| Mixed-bulk | 0.944295141271208 | 1.2081314772756437 | Goodput below 0.95; CPU above 1.10 |
| Stateless-pressure | 0.9590708299335772 | 1.1593702973325581 | CPU above 1.10 |

| Cell | Control / granted median ordinary goodput, Gbit/s | Control / granted median server CPU, seconds | Control / granted median CPU/all useful byte, ns/B |
| --- | --- | --- | --- |
| Mixed-bulk | 8.653976 / 8.171908 | 83.413439 / 95.229610 | 1.237195 / 1.492362 |
| Stateless-pressure | 8.721723 / 8.356636 | 82.753650 / 91.920429 | 1.265019 / 1.466626 |

Absolute medians and medians of paired ratios are different arithmetic. Goodput counts ordinary application bytes; server CPU is divided by all useful received bytes, including approximately 2,516,582,400 background bytes per mixed-bulk observation. Mixed-bulk compares one ordinary connection plus a two-path BBR background against one ordinary connection plus two independent BBR backgrounds with matched offered load. Its goodput ratios span 0.935848–0.950103 and CPU ratios 1.200694–1.211705. Stateless ratios span 0.943310–0.967585 and 1.154364–1.168478. Original verdicts use paired medians, not a requirement that every round exceed the floor.

All other latency, memory, progress, loss/drop/write/close checks pass, and granted endpoints join. The owner reviewed the complete cells and explicitly accepted the final mixed-bulk goodput/CPU and stateless CPU exceptions in the [exact-result decision](../../2026-11-14-bbr-ordinary-cost-1368-experiments.md#final-ordinary-qualification-and-exact-result-owner-acceptance--2026-11-14-americanew_york). That decision supersedes the earlier diagnostic-only CPU exception recorded in launch/audit metadata. The original thresholds and raw failed verdicts remain unchanged; clean failures were not retried. Acceptance applies to these measured results, not a new numeric ceiling or unrestricted future exception.

## Interoperability and scope

The [six-case aggregate](interop-results/matrix-result.json) and [independent audit](interop-independent-audit.json) pass with no skips: `useful-transfer`, `abandon-reopen-late-feedback` and `same-id-migration-rebinding`, each in client and server roles. Raw case outputs retain bidirectional STREAM and 256-byte DATAGRAM traffic, useful path-2 traffic after abandonment/reopen with late feedback disposition, and useful same-ID path-1 traffic after migration/rebinding. These are the original bounded draft-21 QUIC-v1 assertions, not exhaustive qlogs or public BBR support.

Both overlays restore only measurement reachability. Public admission remains Reno-only; aggregation and full [Q2 (#599)](https://github.com/the-sarge/quic-go-fast/issues/599) remain outside this result. The separate ready-head hosted independent-peer job still requires its 16 Reno cases and zero evidence. Full-panel review and all required hosted checks remain outstanding at this receipt.

## Accounting and evidence limits

| Charge | Instances | Occupied host-seconds |
| --- | ---: | ---: |
| [Ordinary setup](ordinary-setup.json) | 0 | 4.9913044 |
| [Ordinary campaign ledger](ordinary-results/ledger.json) | 12 | 924.6414009882137 |
| [Interop image/build, six cases and aggregate](interop-independent-audit.json) | 6 | 40.825829015 |

Including prior work, [program #646](https://github.com/the-sarge/quic-go-fast/issues/646) usage is **267 / 420 instances and 12364.07078762835985 / 28800 host-seconds**, leaving **153 instances and 16435.92921237164015 host-seconds**. The [append-only ledger](../../2026-11-14-bbr-ordinary-cost-1368-experiments.md#final-bbr-interoperability-qualification--six-cases-pass) records the exact reconciliation, including the pre-execution orchestration syntax error. Interop outer wrapper time is charged once; inner test durations are descriptive. No case or allowance was added and no host policy changed.

The audit reconstructs useful-byte/rusage arithmetic and original verdicts. Foreign CPU uses stored driver accounting because raw kernel-counter endpoints were not saved; original contamination flags remain authoritative. Historical native/Reno observations retain their original source and venue limits. Raw audit outputs preserve their contemporaneous scope, and this receipt records the subsequent owner decision without rewriting them. Review and ready-head checks must complete before delivery is claimed.
