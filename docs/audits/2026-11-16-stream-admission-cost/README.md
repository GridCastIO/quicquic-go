# S1 STREAM admission cost decision

**Decision: SUPPORT.** S1 [#1438](https://github.com/the-sarge/quic-go-fast/issues/1438) is complete when this receipt merges. S2 [#1439](https://github.com/the-sarge/quic-go-fast/issues/1439) may then implement its already accepted shared-validation/length-only skip design. This is selection authority for that small change, not evidence of its speedup or permission to expand the experiment. The [normative S1 contract](../../adr/2026-11-16-stream-admission-plan.md#s1--measure-current-admission-cost-and-settle-selection) was accepted at `b6cbcf823fb8d4fa5b9effe3ba64a63660fe0899`; parent [#1437](https://github.com/the-sarge/quic-go-fast/issues/1437) and program [#1440](https://github.com/the-sarge/quic-go-fast/issues/1440) retain pointer-only tracking.

## Source and finite execution

Measured runtime source: `b1898abdd910373f7ad5dc24bdacb2d2b3a19751`, unchanged from the accepted plan at the admission/parser/queue seams. The only compiled addition was the disposable root-package fixture archived as [s1_admission_cost_test.go.txt](s1_admission_cost_test.go.txt), SHA-256 `a5cdbf7527fe9add9bcb61d7559bbae2a9660f52e91bba26792fa72204f03c76`. It has been removed from compiled source. The text is frozen evidence with no maintained execution or CI obligation. No candidate parser or runtime change was measured or delivered.

[Environment](environment.txt): Go 1.27.4, darwin/arm64, macOS 27.2.1 (26B131), Apple M4 Max, 128 GiB memory, twelve performance and four efficiency cores. `GOFLAGS` was empty, `GOTOOLCHAIN=auto`; each benchmark command selected `-cpu=1` (one Go execution thread). CPU placement, clock frequency and thermal state were not controlled. Fixture construction, real receive-queue population, payload parsing/checks and admission characterization were outside the timed loops; sinks consume the admission verdict and parser consumed length. The owning-parse timing excludes ParseType, while admission includes its real complete scan; these are different operations, not a subtraction experiment.

Characterization passed via `go test . -run '^TestS1AdmissionFixtures$' -count=1 -v`, with [raw output](fixtures.txt). The first characterization compile identified a pointer/value initializer mismatch in the disposable fixture; correcting `Conn.frameParser` to its existing value type resolved it before any timed invocation. No production failing test was expected. The following two benchmark commands each ran exactly once, with Go's adaptive benchmark iterations and no added trials:

```sh
go test . -run '^$' -bench '^BenchmarkS1DatagramAdmissionCost$' -benchmem -benchtime=1s -count=1 -cpu=1
go test ./internal/wire -run '^$' -bench '^BenchmarkParseStreamFrame$' -benchmem -benchtime=1s -count=1 -cpu=1
```

Both exited 0. The admission command ran from 20:44:10.808 to 20:44:22.484 UTC on November 16, 2026; the ordinary parser command ran from 20:44:22.484 to 20:44:24.208 UTC. The wrapper and load sampler are archived as [measure.py.txt](measure.py.txt), also disposable frozen evidence.

## Fixtures and observations

All fixtures use legal constructed frames, 1-RTT, enabled DATAGRAMs, a configured ceiling of 8,972 and explicit FrameParser STREAM cap of 8,972. The receive queue is populated through `HandleDatagramFrame`, and its room is verified through `receiveQueueLen`. The four cases all enter the actual admission scan because plaintext frame bytes exceed queue room. The expected verdict is verified outside timing and admission leaves the queue unchanged.

| Fixture | Payload / frame count | Plaintext frame bytes | Queue room | Admission |
| --- | --- | --- | --- | --- |
| STREAM, empty queue | 1,200 / 1 | 1,204 | 1,024 | accept |
| STREAM, empty queue | 8,900 / 1 | 8,904 | 1,024 | accept |
| STREAM, full queue | 64 / 1 | 68 | 0 | accept |
| DATAGRAM, four slots free | 1,099 / 8 | 8,816 | 4 | refuse |

Raw [admission and owning parse output](admission.txt) reports:

| Fixture | Operation | ns/op | B/op | allocs/op |
| --- | --- | ---: | ---: | ---: |
| STREAM 1,200, empty | admission | 29.22 | 0 | 0 |
| STREAM 1,200, empty | owning parse/PutBack | 23.30 | 0 | 0 |
| STREAM 8,900, empty | admission | 142.0 | 0 | 0 |
| STREAM 8,900, empty | owning parse/PutBack | 110.9 | 0 | 0 |
| STREAM 64, full | admission | 40.29 | 112 | 2 |
| STREAM 64, full | owning parse/PutBack | 33.60 | 112 | 2 |
| Eight DATAGRAMs, room four | admission | 157.9 | 256 | 8 |

The existing [ordinary parser benchmark output](ordinary-parser.txt) is 198.2 ns/op, 0 B/op, 0 allocs/op. Its iteration parses ten 200–209-byte STREAM frames through the free parser and helper, including type parsing and helper checks. It is preservation context, not a configured-jumbo admission measurement and not directly comparable to one S1 frame operation.

## Host activity and limits

The coordinator held new local test/build commands from the four other program workers during this window. The host was still active. Unprivileged Mach per-core tick counters, mapped through IODeviceTree's logical CPU IDs ([mapping](cpu-clusters.json)), distinguish efficiency CPUs 0–3 from performance CPUs 4–15. [Raw tick deltas](host-load.json) cover a one-second pre-sample and each whole command, including setup and the benchmark itself.

| Sample | Mean efficiency-core busy | Mean performance-core busy | Performance-core range |
| --- | ---: | ---: | ---: |
| One second before commands | 20.05% | 25.56% | 0.00–45.45% |
| Admission command | 41.50% | 53.39% | 38.59–67.13% |
| Ordinary parser command | 27.80% | 31.25% | 10.98–48.21% |

Performance-core activity was present, not inferred from efficiency-core activity. These aggregate counters cannot attribute residency or contention to the benchmark process, and the scheduler remained unpinned. Privileged `powermetrics` was unavailable without credentials; no privileged sampling was performed. The figures are usable local cost observations with this disclosed load, not an isolated-host timing guarantee. There are no repeated trials, confidence intervals, cross-platform claims, exact candidate comparisons or end-to-end throughput assertions.

## Why SUPPORT

The source identifies attributable materialization at the selected seam: admission calls the owning STREAM parser, whose existing owner acquires frame/storage and copies payload, then immediately PutBack without delivering that frame. The configured 8,900-byte case measures a 110.9 ns owning operation and a 142.0 ns actual admission scan; the 64-byte case independently exposes 112 bytes and two allocations in both operations below the 128-byte pool threshold. The 1,200-byte case is cheap and already allocation-free, which limits the expected payoff on that workload.

The exposure includes qualifying ordinary-sized and STREAM-only packets on a receiver with jumbo ceiling and DATAGRAMs enabled, and small packets when the receive queue is occupied; it is not restricted to packets actually carrying DATAGRAMs or negotiated jumbo-active packets. Avoiding an 8,900-byte payload copy and temporary pool activity, plus removing the small-frame materialization allocations from this otherwise delivery-free scan, justifies trying the already bounded shared wire-validator change. The observed submicrosecond scale supports only this narrow change, not a new packet walker or broader parser redesign. The DATAGRAM-heavy case has its own eight allocations and remains outside S2; the decision does not claim to solve that cost.

The timing paths are not subtracted to estimate validation-only cost, and no measured fraction is asserted to be removable. The candidate may alter ordinary-parser code generation or erase the apparent benefit. S2 must therefore honor its existing finite matched-comparison and ordinary-allocation preservation contract and terminate without the optimization if benefit is immaterial, outweighed or inconclusive. This S1 selection adds no threshold, trial inventory, release gate or F12 dependency.

## Artifact and closure receipt

Archived source, raw output and host observations are frozen experiment evidence; this receipt and the plan/program state are process metadata. The real wire parser and receive queue retain runtime authority. Coverage is example-level only, contract closure is not triggered, and no runtime behavior, public API, schema, dependency or ownership changes. Source identity, raw observations, four fixture outcomes and removal of the compiled disposable source discharge S1's finite evidence inventory. Review, exact-head docs certification and merge receipts belong in the product PR discussion; journal history follows merge.
