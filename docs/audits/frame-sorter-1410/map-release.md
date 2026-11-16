# Terminal map-release results — issue #1410

Status: the maintainer-approved modification and targeted remeasurement are complete. **Recommend adoption of the modified candidate, subject to the maintainer accepting the remaining measured tradeoffs and the normal review/qualification process.** No production adoption decision or merge has occurred. This report supplies the requested return for decision for [issue #1410](https://github.com/the-sarge/quic-go-fast/issues/1410) and [draft PR #1426](https://github.com/the-sarge/quic-go-fast/pull/1426).

## Modification and scope

Measured modified code: `066f012b17c7127c86990eeb5010e2c8b7002b36`; [the manifest](evidence/map-release/manifest.json) also records the binary and evidence hashes. The production delta from previous Candidate B (`f03f9a1cb4ce2ff4963ce93de5a0d6c91770fefd`) is one assignment, `s.queue = nil`, after invoking the retained cleanup callbacks in `frameSorter.discard`. The owner has already sealed admission; future Push is forbidden. No insertion, lookup, cap, phase, stream, or CRYPTO code changed. The 4,096-gap limit remains the evaluated proposal.

A new regression test covers both gapped and fully drained queues. Before the change, both cases fail because an empty queue map remains allocated. After the change, the map reference is nil, callbacks still release, repeated discard is safe, and Pop, Peek and HasMoreData preserve their empty-state behavior. See [red evidence](evidence/map-release/red.log) and [passing focused suite](evidence/map-release/focused.log).

## Terminal retained memory

The existing probe is unchanged: a fresh process for each cell, 16 live sorters, individual 2,048-byte backing buffers holding 1,200-byte frames, two forced GCs, then retained heap measured with the sorter objects still reachable. The targeted run measures terminal discard at 10, 1,000 and 4,096 gaps, phase recording off/on; the baseline only supports the first two. All 16 cells are in [raw retained results](evidence/map-release/retained.jsonl).

| Gaps before discard | Original linked list | Previous chunks/4,096 candidate | Modified chunks/4,096 candidate |
| --- | ---: | ---: | ---: |
| 10 | 921–924 B | 873 B | 81 B |
| 1,000 | 98,567 B | 98,519 B | 87 B |
| 4,096 | Unsupported | 393,671 B | 87 B |

Values are bytes per live sorter in this fixture. Apart from the small baseline 10-gap variation, phase-disabled and phase-enabled results match. At 4,096 gaps the modification removes **393,584 bytes (about 384.4 KiB), or 99.978%**, of the previously retained terminal heap. Payload backing bytes, queued frames and snapshot capacity are zero; all 4,095 retained frame callbacks have run. The residual 81–87 bytes includes the live sorter and amortized fixture overhead, not a universal object-size guarantee. This is retained heap, not RSS or peak memory.

This modification does not reduce active fragmentation or pre-terminal retention. The original measurements of approximately 8.77 MiB for a phase-enabled, fragmented 4,096-gap fixture and 464,464 bytes after draining while keeping the sorter active remain the applicable evidence. The larger gap capacity still permits more retained payloads and larger phase snapshots. Only the terminal state changed.

## Affected timing and allocations

The same benchmark source and previously pinned binaries were used, with an additional binary for the modified candidate. Prior binary hashes were verified against the initial manifest. Ten interleaved 200 ms samples were run for construction/push/pop/discard and the overlap lifecycle at 10, 100, 1,000 and 4,096 gaps. The linked-list baseline was remeasured in the same campaign at its supported counts. Compilation and tests finished before timing. No samples were discarded or repeated.

Go 1.27.4 darwin/arm64 on the Apple M4 Max, `GOMAXPROCS=1`, `GOGC=100`, `GOMEMLIMIT=off`. Per-core activity is recorded using the same Mach/IORegistry method as the original evaluation. Performance-core activity, including the benchmark, ranged from 3.55 to 6.93 core equivalents out of 12; efficiency-core activity ranged from 0.47 to 2.32 out of 4. These are distinct load observations, not an assumption that efficiency-core work caused performance-core contention. No CPU affinity or frequency controls were applied.

| Lifecycle operation | Original baseline median | Previous candidate median | Modified candidate median | Modified versus previous |
| --- | ---: | ---: | ---: | --- |
| Construct, push, pop, discard | 204.35 ns | 160.05 ns | 161.25 ns | +0.75%; no significant difference, p=0.092 |
| Overlap, 10 gaps | 1.2095 µs | 1.0780 µs | 1.0790 µs | +0.09%; no significant difference, p=0.616 |
| Overlap, 100 gaps | 18.202 µs | 12.292 µs | 12.408 µs | **+0.94%**, p=0.014 |
| Overlap, 1,000 gaps | 624.796 µs | 124.283 µs | 124.5175 µs | +0.19%; no significant difference, p=0.436 |
| Overlap, 4,096 gaps | Unsupported | 473.430 µs | 473.0695 µs | -0.08%; no significant difference, p=0.684 |

These are per-case benchstat comparisons, not multiple-comparison-adjusted claims. The 100-gap result is a small observed regression, about 116 ns over the entire create/fill/replace/discard lifecycle; it is not omitted merely because it is small. The modified candidate remains about 32% faster than the original baseline in that case and about 80% faster at 1,000 gaps.

The modified candidate's zero-based timing pass 6 contains high outliers: 275.061 µs for the 1,000-gap overlap case and 806.715 µs for the 4,096-gap case, versus medians of 124.518 and 473.070 µs. That pass also records the campaign's maximum performance-core activity, 6.93 core equivalents, and efficiency-core activity, 2.32. This association is consistent with interference but does not establish the cause of each sample. All samples remain in the distributions; the absence of a significant median difference is not a claim of equal tail latency. [Direct previous/modified comparison](evidence/map-release/candidate-comparison.log), [three-way comparison](evidence/map-release/benchstat.log), [min/max and samples](evidence/map-release/summary.json), and [per-core observations](evidence/map-release/load.jsonl) provide the full evidence.

Allocation counts and bytes allocated are identical between the previous and modified candidates in every remeasured case: construction 4 allocations / 440 B; overlap at 10 gaps 11 / 1,664 B; at 100 gaps 24 / 17,264 B; at 1,000 gaps 66 / 231,264 B; at 4,096 gaps 190 / 938,048 B. Releasing a terminal map changes what stays reachable, not what was allocated to handle the queue.

## Remaining adoption tradeoffs

The earlier hot-path measurements were not rerun because those paths and the benchmark source did not change. They remain the evidence for the proposed chunked representation: around 84% faster lossy sorting and 98% faster duplicate lookup at 1,000 gaps, but around 24% slower reordered sorting and 4% slower corresponding ReceiveStream processing. In-order receive-stream processing showed no meaningful regression. Small-gap regressions, extra lossy/overlap allocations, and the increased active-memory envelope remain explicit. See [the initial evaluation](README.md) for all workloads and limitations. No network-goodput improvement or platform-general qualification is claimed.

The new modification removes the identified terminal-memory penalty with no allocation increase and no broad lifecycle timing regression in the finite measurements. The one 0.94% lifecycle increase and the noisy high samples above remain part of the decision. Recommendation: accept this modified candidate for adoption and proceed to the already-required review and qualification, rather than adding more unbounded tuning. The maintainer may instead defer adoption if the remaining reordering/allocation/active-memory costs are unsuitable.

## Validation and next step

The new regression's red/green result, full root and internal/protocol package tests, focused sorter/receive-phase/receive-stream retirement/CRYPTO/fuzz-seed tests, focused race tests, vet and tidy passed on the modified code. See [package tests](evidence/map-release/package-tests.log), [race](evidence/map-release/race.log), [vet](evidence/map-release/vet.log), and [tidy](evidence/map-release/tidy.log). No extended fuzz campaign was added.

The draft stays pending the maintainer's adoption decision. Full configured RAS review, reconciliation with the latest main, final pushed-head certification, hosted checks, actual post-ready independent-peer qualification and merge have not been completed for this candidate. Approval to make and measure this change was not approval to adopt or merge it.

## Reproduction

Build the pinned modified revision with `go test -c -o <new-evidence-dir>/maprelease.test .` and record its SHA in `maprelease.sha`. Copy or link the verified initial `baseline.test` and `chunks4096.test` binaries and their `.sha` files into that directory, along with the original benchstat binary. The manifest records all exact input hashes. Then run:

```sh
python3 docs/audits/frame-sorter-1410/remeasure-map-release.py <new-evidence-dir>
python3 docs/audits/frame-sorter-1410/summarize-map-release.py <new-evidence-dir>
```

The effective timing selector is `-test.bench='^BenchmarkFrameSorter(Construct|Overlap)$'`; the heap selector is `-test.run='^TestFrameSorterRetainedHeap$'` with `SORTER_HEAP_STAGE=discarded`, gap counts and phases as above. [Environment](evidence/map-release/environment.json), [manifest](evidence/map-release/manifest.json), and compressed raw timing files for [baseline](evidence/map-release/baseline.bench.gz), [previous candidate](evidence/map-release/chunks4096.bench.gz), and [modified candidate](evidence/map-release/maprelease.bench.gz) are retained separately from the frozen initial campaign.
