# E07 mechanical extraction (#1368)

This disposable helper extends the frozen [E04 extractor](e04-analyze.py) for the E07 observer/profile pair in [issue #1368](https://github.com/the-sarge/quic-go-fast/issues/1368). It reads captured JSON only, emits descriptive counters and ratios, and sets `qualification` to `false`. It does not launch work, change validity rules or create a maintained test dependency. The whole-process CPU profiles remain separate attribution artifacts; their overlapping stacks are not additive removable-time estimates.

Schema and hook meanings were checked against observer source `c1853e6b4f67c7859bf45f1d43e3ce18eb8396de` and its [committed E07 schema](https://github.com/the-sarge/quic-go-fast/blob/c1853e6b4f67c7859bf45f1d43e3ce18eb8396de/docs/audits/2026-11-14-bbr-ordinary-cost-1368/e07-observer-schema.md). That observer ports E04 onto E06 without changing existing field paths. This is an extractor compatibility pin; the run's own source/archive/binary receipt remains the authority for what was executed. No E07 captured data was available when this helper was prepared, so preparation checks cover syntax, CLI and pinned-schema/source inspection, not a completed run analysis.

## Use

```sh
python3 -B docs/audits/2026-11-14-bbr-ordinary-cost-1368/e07-analyze.py /absolute/path/to/e07-observed > /absolute/path/to/e07-analysis.json
```

The input directory must contain the diagnostic driver's complete `summary.json`, including both ordinary-role observations. The output records that file's SHA-256 and preserves each attempt's profile, status, start timestamp, occupancy, foreign CPU and contamination flag. It does not filter contaminated attempts or turn instrumented timings into qualification evidence. Missing fields or malformed array sizes produce an extraction error instead of silently accepting E04 data as E07. Division by zero produces JSON `null`.

## Counters and boundaries

All E04 field paths retain their meanings. Lifetime data comes from `bbr_observation.final_before_teardown`; `final_recorded` must be read alongside it. These totals include startup and warmup and omit work after the freeze. Only the first `snapshot_count` entries are inspected, with `snapshot_overflow` preserved. The fixture obtains these arrays after connection completion; the helper performs no live observation.

Interior summaries use the unchanged inclusive 17–73-second selection after attempt registration. This lies within the approximate five-second setup, ten-second warmup and sixty-second measurement timeline; it is not an exact measurement-window boundary. The helper reports the actual first/last monotonic and wall timestamps, actual monotonic span and adjacent snapshot gaps. It subtracts cumulative counters at those two endpoints; array counts are subtracted elementwise. Gauge min/median/max values describe selected snapshots and are not weighted by time. One selected snapshot produces zero span/deltas. Counter events belong to their observation point: a retry or native duration recorded inside the interval can begin before its first snapshot.

Recovery valid/invalid/unanchored samples, timing exclusions/mismatches/fences, early ACKs and sampler resets remain in `ack_lifetime` and `ack_delta`. Model usable samples and clock rejection/reset counters remain separate in `model_lifetime` and `model_delta`. Exclusion and mismatch populations overlap. Native duration totals include only valid timestamps; `Missing` and `Negative` remain separate. No subtraction is performed on cumulative extrema or boolean state; lifetime extrema remain available, and the first/last `RetryOpen` flags are recorded explicitly.

| Added field under snapshot/final `emission` | Meaning |
| --- | --- |
| `HandoffSizeBuckets` | Seven counts of actual buffer bytes at emission handoff, inclusive upper bounds 1,452; 16,384; 20,480; 32,768; 49,152; 65,507; infinity. Includes ordinary data and BBR control/probe traffic. |
| `GSOHandoffs` | Nonzero GSO argument at handoff, before any later fallback. This records intent, not a successful GSO syscall. |
| `ScalarHandoffs` | Zero GSO argument at handoff. |

The bins appear unchanged in `emission_lifetime.counters.HandoffSizeBuckets` and as elementwise differences in `emission_delta.HandoffSizeBuckets` / `emission_interior.counters.HandoffSizeBuckets`. The same sections retain all partial-credit counts, refusal byte sums and retry counts. The helper reports bin sum minus `Handoffs` and GSO-plus-scalar minus `Handoffs` without hiding any discrepancy. Zero is the observer's expected accounting identity, not a new performance gate. The output's upper-bound arrays use `null` for infinity.

`native_lifetime` and `native_interior` preserve the eight-bin `OpportunityToReturn` and `ReturnToConsume` histograms: inclusive 10, 25, 50, 100, 250, 500 and 1,000 microseconds, then infinity. Interior counts and nanoseconds are differences; lifetime maxima are never treated as interval maxima. Means divide valid duration totals by their valid counts. Histogram sum-minus-count values expose extraction/accounting discrepancies.

## Limits of the geometry proxies

E06's selected ordinary path has one handoff per opportunity. A handoff is not a native request admission, result record, syscall or delivered member: refusals, BBR control/probe work, staging, pending work and consumption have different boundaries. `ConsumeClockReads` counts observed native result-record consumption under BBR; `Members / ConsumeClockReads` and `MemberBytes / ConsumeClockReads` describe consumed-record geometry only. Neither ratio establishes request arrival rate, kernel batching, service latency per packet or causal gap time. Partial accepted datagrams contribute to `AcceptedDatagrams`, while `AcceptedBytes` includes only fully accepted error-free members; do not invent bytes for partial prefixes.

`OpportunityToReturn` starts at the existing reservation/opportunity timestamp rather than buffer handoff. `ReturnToConsume` ends at the observer's one clock read before per-member recovery, so it includes endpoint reconciliation and connection scheduling. These spans cover multiple owners; they do not isolate encryption or completion CPU. `RefusedUsablePartialRoom` demonstrates enough free credit for a smaller reservation, not that the rest of an alternative send would be legal or faster. Native intervals, counter frequencies and model gauges remain descriptive under observer/profiler overhead and host interference. Use the separately captured profiles for overlapping owner attribution and the frozen uninstrumented pairs for performance evidence.
