# Chunked frame sorter evaluation — issue #1410

Status: the maintainer **approved adoption of the modified candidate with the recorded tradeoffs** and directed [PR #1426](https://github.com/the-sarge/quic-go-fast/pull/1426) through full review, qualification and merge. [Adoption receipt](adoption.md). The [targeted remeasurement report](map-release.md) records terminal retained heap falling from 393,671 to 87 bytes per live sorter at 4,096 gaps. The initial comparison below remains frozen evidence for the representation/cap tradeoff; its terminal-memory results describe the candidate before map release. Review and qualification remain required before merge.

Scope and authority: [issue #1410](https://github.com/the-sarge/quic-go-fast/issues/1410), [approved evaluation plan](plan.md), and [approval receipt for issue #1410](https://github.com/the-sarge/quic-go-fast/issues/1410#issuecomment-6905849360). The source candidate is adapted from [upstream PR #6185](https://github.com/quic-go/quic-go/pull/6185), commit `8d34dbcccc219375fa9fbaa9b7b22caeebd7d49d`. Measurements below are local to this fork, not upstream results.

## Compared revisions

| Variant | Exact revision | Representation and cap |
| --- | --- | --- |
| Baseline | `f4f51b28c09cbfc8b8ac3ced09cf81eb02993b12` | Original linked list, 1,000 gaps; evaluation tests added to production base `571ba7762067e6703743d010c4662a9855a13be2` |
| Candidate A | `79fc4161c8ef483e3501f3de56d4e3a7cb68bef6` | Chunked gaps, original 1,000 cap |
| Candidate B | `f03f9a1cb4ce2ff4963ce93de5a0d6c91770fefd` | Same chunks, 4,096 cap; only the cap differs from A |
| Modified candidate C | `066f012b17c7127c86990eeb5010e2c8b7002b36` | Candidate B plus terminal queue-map release; see [targeted results](map-release.md) |

All variants use the same benchmark and retained-heap source. The original campaign below compares baseline/A/B; Candidate C has a separate targeted campaign. Test binary hashes and evidence hashes are in [the manifest](evidence/manifest.json). Later report-only commits do not change the measured Go source. The implementation keeps the fork's gap-limit rejection callback, independently copies receive-phase snapshots from the chunks, and drops gap/snapshot storage on discard. Candidate B preserves the existing queue-map cleanup policy, which deletes entries but retains the map. Candidate C releases that map after the callbacks; its separate results supersede the terminal-memory findings for the proposed adoption candidate.

## Failure reproduction and correctness

The input model sends 12,000 frames of 1,200 bytes. In the loss case the first two frames of each ten-frame group are delayed until a second receive pass: a 20% accumulated loss episode over a 14.4 MB span. This requires a receive window at least that large; the upstream report used 1 GiB. There is no sender recovery loop, packet timing, congestion controller or network peer in this test.

Both the baseline and Candidate A fail at zero-based frame **9,992**, offset **11,990,400**, after **7,992 successful pushes**, when the gap count exceeds 1,000. Candidate B accepts the first pass and delivers all **14,400,000 bytes** in order after delayed repair, with contents verified. All three pass the in-order and bounded-reordering controls; the latter repairs each pair at the end of its ten-frame group. Callback counters cover submitted inputs, including the rejected input and repeated terminal discard. See the [baseline](evidence/baseline-recovery.log), [Candidate A](evidence/chunks1000-recovery.log) and [Candidate B](evidence/chunks4096-recovery.log) receipts.

Candidate B passed:

- Existing sorter data/overlap/duplicate/Peek tests and fuzz seed corpus, without an extended fuzz campaign.
- Added boundary tests at 31, 32, 33, 63, 64, 65 and 192 fragmented frames: forward and reverse repair, split/merge, multi-chunk overlap replacement, byte/Peek results, actual chunk invariants, independent phase snapshots and exactly-once callbacks.
- Cap-boundary callback cleanup, including all retained entries and repeated discard.
- Existing receive-phase, receive-stream retirement, CRYPTO and initial-CRYPTO tests, plus fragmented receive-stream replacement with phase-aware reads.
- Root and internal/protocol package tests, focused race tests, vet and module tidiness.

[Focused tests](evidence/candidate-b-focused.log), [package tests](evidence/package-tests.log), [race tests](evidence/race.log), [vet](evidence/vet.log), and [tidy](evidence/tidy.log) are retained. These are evaluation checks on the measured code, not final pushed-head certification. Standards/Spec preparation, full configured RAS review, hosted checks and post-ready independent-peer qualification remain for an accepted candidate.

## Initial timing and allocation methodology

Apple M4 Max, macOS 27.2.1, Go 1.27.4 darwin/arm64; `GOMAXPROCS=1`, `GOGC=100`, `GOMEMLIMIT=off`. Ten samples per supported case, 200 ms per sample, rotating baseline/A/B order between rounds. Tests and builds finished before the timing campaign. No CPU pinning or frequency control was available. Core identity came from IORegistry and activity from Mach per-core CPU ticks: cores 0–3 are efficiency cores; 4–15 are performance cores. During benchmark passes, total performance-core activity ranged from 2.78 to 3.72 core equivalents out of 12, including the benchmark; efficiency-core activity ranged from 0.54 to 1.47 out of 4. This was a busy host, not an idle-host claim. Aggregate activity does not prove absence of scheduler interference. [Environment](evidence/environment.json) and [per-core observations](evidence/load.jsonl) preserve the details.

Sorter microbenchmarks use shared 1,200-byte data to isolate sorting. The lossy workload repairs the oldest hole and introduces a new one; the reordered workload delivers each new pair backwards while a distant backlog remains. That backlog begins at byte offset `1<<40`; this is a synthetic stress position. Receive-stream measurements use the real stream ingestion/read path with permissive flow-control fixtures, not a production-window transfer. One reordered/lossy operation handles two frames; an in-order operation handles one. Overlap results include creating, filling, replacing and retiring the queue. Construction results include one push/pop and discard. Phase-snapshot measurements isolate the one-time copy from a prepopulated sorter.

Numbers below are medians. Full confidence ranges, p-values, allocation results and all tested gap counts are in [benchstat](evidence/benchstat.log); [summary JSON](evidence/summary.json) also retains min/max and the number of paired samples that were slower. Statistical tests are per case and are not adjusted for multiple comparisons. Small percentage changes are not evidence of end-to-end goodput changes. No workload-weighted aggregate is used for the decision.

| Workload | Baseline | A: chunks/1,000 | B: chunks/4,096 | B versus baseline |
| --- | ---: | ---: | ---: | ---: |
| In-order sorter | 28.70 ns | 27.58 ns | 28.00 ns | -2.4% |
| Lossy, 2 gaps | 63.27 ns | 68.34 ns | 69.33 ns | **+9.6%** |
| Lossy, 10 gaps | 111.4 ns | 113.3 ns | 111.9 ns | No significant B difference |
| Lossy, 1,000 gaps | 1,123.5 ns | 183.6 ns | 184.4 ns | -83.6% |
| Duplicate, 2 gaps | 7.32 ns | 10.62 ns | 10.58 ns | **+44.4%**, about 3.25 ns |
| Duplicate, 1,000 gaps | 982.4 ns | 19.62 ns | 19.88 ns | -98.0% |
| Reordered, 2 gaps | 65.96 ns | 70.61 ns | 71.34 ns | **+8.2%** |
| Reordered, 10 gaps | 83.80 ns | 92.90 ns | 98.30 ns | **+17.3%**, noisier cell |
| Reordered, 64 gaps | 94.63 ns | 125.70 ns | 126.15 ns | **+33.3%** |
| Reordered, 1,000 gaps | 106.0 ns | 129.3 ns | 131.2 ns | **+23.7%** |
| Construct/push/pop/discard | 194.1 ns | 153.5 ns | 150.8 ns | -22.3% |
| Overlap lifecycle, 1,000 gaps | 641.7 µs | 122.6 µs | 122.7 µs | -80.9% |
| In-order ReceiveStream, no phase | 148.65 ns | 149.45 ns | 148.95 ns | No significant difference |
| Reordered ReceiveStream, 1,000 gaps, no phase | 367.75 ns | 382.25 ns | 382.60 ns | **+4.0%**, all ten B pairs slower |
| Reordered ReceiveStream, 1,000 gaps, phase enabled | 370.80 ns | 382.75 ns | 385.55 ns | **+4.0%**, all ten B pairs slower |
| Phase snapshot, 1,000 gaps | 4.212 µs | 1.412 µs | 1.418 µs | -66.3% |

Both chunked variants show the same substantive pattern at common counts: these regressions are primarily representation costs, not the cap increase. The cap-only difference between A and B is not used to infer tiny code-generation or timing effects. At 4,096 gaps, B measures 210.5 ns per lossy operation, 23.11 ns per duplicate, 135.7 ns per reordered operation, 405.7/409.1 ns per reordered stream operation without/with phase recording, and 6.906 µs per phase snapshot. Baseline/A do not support these counts and are skipped in throughput benchmarks; they are not zero-cost or successful comparison points.

Allocation tradeoffs are material even when elapsed time improves. At 1,000 gaps the lossy microbenchmark rises from approximately 0 to **36 B/op**. Go's integer `allocs/op` output truncates fractional amortized allocation rates to zero; this case is not allocation-free. Chunk splits allocate backing arrays. The overlap lifecycle at 1,000 gaps rises from **27 to 66 allocations** and about **193,248 to 231,264 B/op** (+19.7% bytes), despite being much faster. At ten gaps that lifecycle rises from 7 to 11 allocations and 1,272 to 1,664 B/op. In-order sorter processing stays at zero allocations; construction remains four allocations while falling from 528 to 440 B/op. Receive-stream allocation counts are unchanged in the measured cases. Snapshot storage costs 16,384 allocated bytes at 1,000 gaps and 65,536 at 4,096.

## Initial retained memory, before map release

Each cell runs in a fresh process with 16 live sorters. Each received 1,200-byte payload has its own 2,048-byte backing buffer, retained by a cleanup callback. Measurements use post-GC heap deltas while the sorter objects remain reachable. This models sorter-owned retention; it is not process RSS, peak memory, a packet-pool residency measurement, or a universal per-stream bound. A stream's flow-control window and queued contiguous data also govern memory; the gap count alone is not a complete byte-memory ceiling.

The partial stage repairs and drains half the holes. The drained stage repairs all holes but keeps the stream/sorter alive. The discarded stage terminates the fragmented queue directly. All values are bytes per live sorter, with phase recording enabled:

| Stage | Baseline, 1,000 gaps | Chunks, 1,000 gaps | Chunks, 4,096 gaps |
| --- | ---: | ---: | ---: |
| Fragmented | 2,256,855 | 2,246,311 | 9,193,623 |
| Partial repair/drain | 1,187,008 | 1,182,240 | 4,829,648 |
| Fully drained, still live | 115,008 | 116,960 | 464,464 |
| Terminal discard, still live | 98,567 | 98,519 | 393,671 |

At a common 1,000-gap count, chunks save about 10.5 KB while fragmented, retain about 2 KB more after drain, and are essentially equal after discard. A and B are identical in these common-count memory cells. Allowing 4,096 gaps raises the fixture's fragmented retained heap to about **8.77 MiB**, versus **2.15 MiB** for baseline capacity. Of that, 8,386,560 versus 2,045,952 bytes are queued payload backing buffers. This is the cost of permitting more retained work, not a claim that ordinary streams always allocate 8.77 MiB.

The phase snapshot's original backing array remains retained after `phaseAt` advances to the final interval: the remaining slice capacity may be only 16 bytes, but the heap still includes the full 16,384-byte or 65,536-byte allocation. Terminal discard releases the snapshot and payload references. It also releases all chunks. The remaining roughly **96 KiB / 384 KiB** after discard is consistent with the empty queue map's retained backing storage; `discard` deletes entries but leaves `s.queue` reachable. Dropping the sorter itself would permit its collection, but that is deliberately outside this probe. [Raw retained-memory cells](evidence/retained.jsonl) include phase-disabled cases, exact callback counts, queued backing capacities and suffix snapshot capacities.

## Current adoption decision

The maintainer approved the proposed terminal queue-map release and remeasurement. Candidate C implements that one production assignment in the existing retirement owner. [The targeted report](map-release.md) records red/green retirement tests, the full validation results, all 16 discarded-state memory cells and ten samples of each affected lifecycle timing case.

**The maintainer accepted Candidate C and its recorded tradeoffs.** The 4,096-gap terminal fixture now retains 87 bytes per live sorter instead of 393,671, with unchanged allocation counts and allocated bytes in all remeasured lifecycle cases. Four of five timing cases have no significant median change; the 100-gap overlap lifecycle is 0.94% slower. Elevated-load outliers are retained and discussed. Active fragmentation, pre-terminal retention, extra chunk allocations and the prior roughly 4% reordered-stream slowdown remain explicit costs. No hot-path improvement from map release is claimed.

The approved adoption now proceeds through full configured RAS review, main reconciliation, final certification and hosted/post-ready qualification before merge. A chunks-only change at the old cap still fails the motivating loss model, and a cap-only linked-list change remains outside the approved plan. No automatic numerical acceptance threshold is imposed.

## Reproduction

Create dedicated feature worktrees at the three pinned revisions under the approved worktree root, and build each with `go test -c -o <evidence-dir>/<variant>.test .`. Record its revision in `<variant>.sha`. Baseline/A intentionally fail the delayed-recovery regression; build-only and benchmark-only commands still work. The benchmark and heap probes require no production configuration switch.

```sh
python3 docs/audits/frame-sorter-1410/measure.py <evidence-dir>
python3 docs/audits/frame-sorter-1410/summarize.py <evidence-dir>
```

`measure.py` uses macOS IORegistry and Mach interfaces for the recorded host; these are frozen experiment helpers, not a maintained cross-platform benchmark service. `summarize.py` expects `benchstat` in the evidence directory; [its exact version](evidence/benchstat-version.log) is recorded. The effective timing command for each variant/sample is:

```sh
GOMAXPROCS=1 GOGC=100 GOMEMLIMIT=off <variant>.test -test.run='^$' -test.bench='^BenchmarkFrameSorter' -test.benchtime=200ms -test.cpu=1 -test.count=1
```

A representative retained cell is:

```sh
GOMAXPROCS=1 GOGC=100 GOMEMLIMIT=off SORTER_HEAP_GAPS=4096 SORTER_HEAP_PHASE=true SORTER_HEAP_STAGE=discarded <candidate-b>.test -test.run='^TestFrameSorterRetainedHeap$' -test.count=1
```

The retained stages are `fragmented`, `partial`, `drained` and `discarded`; counts are 10/1,000 for all variants plus 4,096 for B, with phase false/true. Raw timing files are compressed in [baseline](evidence/baseline.bench.gz), [Candidate A](evidence/chunks1000.bench.gz), and [Candidate B](evidence/chunks4096.bench.gz). No timing samples were discarded or repeated. This report does not claim network-transfer throughput or platform-general qualification.
