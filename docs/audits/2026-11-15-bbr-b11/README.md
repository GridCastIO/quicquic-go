# B11 replacement aggregation comparison

[B11 (#1384)](https://github.com/the-sarge/quic-go-fast/issues/1384) measures the frozen B10 candidate under [continuation #1374](https://github.com/the-sarge/quic-go-fast/issues/1374) and the [accepted B11 contract](../../adr/2026-10-24-multipath-bbr-plan.md#b11--measure-the-replacement-aggregation-candidate) at `76954048981e4c0da3f1618ef3038fe1ca7d5576`. Publication and experiment retirement belong to [B12 (#1385)](https://github.com/the-sarge/quic-go-fast/issues/1385).

## Candidate and applicability

Measured candidate `8c34fbac874adf55f096b6c67d51244160169422`, tree `7de8175a101d7bdb8f1ca6962beb1a4652a3a48d`, derives from base `4cb8970533917426595aef62c70ad0d1d1350b9b`. The only source additions are the finite aggregation fixture, driver and focused accounting regressions. No production runtime file changes. The [independent source audit](source-audit.md) compares the copied files with frozen B5 revision `e048181a680f07dc7560f7df1667d8c065513583`; its workload, topology, socket matching, original seeds, useful-byte semantics, contamination rules and timing remain unchanged. E activates B10's existing private selector before connection construction. Historical frozen files and observations are untouched. The [B10 applicability receipt](../2026-11-15-bbr-b10-scheduler.md) therefore carries ordinary, primary/backup, native and Reno evidence with its original limitations and the exact accepted ordinary-cost exceptions. This comparison makes no full BBR Q2 or application-adoption claim.

The finite fixture is owned by the transport integration suite and retires in B12 (#1385). Typed fixture modes, existing QUIC parsers and standard JSON decoding own representation. This is example-level evidence for the fixed workload and pinned native venue; arbitrary peers, Internet topologies and universal fairness remain outside the claim.

## Inventory and venue

The 36 required observations are A (ordinary BBR path A), B (ordinary BBR path B), C (two independent BBR connections, one per path), and E (the frozen private BBR aggregate), over balanced disjoint, unequal delay/rate and shared-bottleneck topologies. Each topology uses orders ABCE, CEAB and EABC for rounds zero, one and two. Seeds are 1044–1046, 1144–1146 and 1244–1246 respectively. All runs retain 10 seconds warmup, 60 seconds observation, and the executed B5 outer observation bound of 120 seconds. The shared topology retains the ordinary Reno competitor.

The native venue is Minimax, AMD Ryzen AI Max+ 395, Linux amd64 kernel 7.0.0-30-generic and Go1.27.4, without emulation or a container. Relay CPUs4–5, server8–11 and client12–15 retain SMT siblings20–21 and24–31. [Setup identity and outer receipt](setup.json) pin the source archive, observed sibling map and actual build/test charge; [setup output](setup.log) records all three native deterministic fixture tests passing. The campaign identity pins its binary and driver SHA256 and the remaining allowance supplied at admission. The existing quiet gate and 5% foreign-CPU threshold inspect the fixture cores and siblings; pre-admission waits hold no fixture and are not charged. No host workload policy changes.

The executed build was `CGO_ENABLED=0 GOAMD64=v1 go test -c -tags aggregation -o ../aggregation.test .` from the exact archived source, followed by the three deterministic fixture tests. The native driver invocation used the pinned binary with `--candidate 8c34fbac874adf55f096b6c67d51244160169422 --remaining-instances 83 --remaining-host-seconds 15630.0579618896227535 --timeout-seconds 120`; that allowance is a historical receipt after setup, not permission for another run.

## Focused validation

The exact inventory regression first failed the frozen driver's 54 observations, then passed at 36 with the three specified orders. Wrong seed/window regressions first failed without identity validation and then passed. Thirteen driver tests cover missing/duplicate/smoke/wrong identity, invalid baseline evidence versus negative aggregate outcomes, median round-paired arithmetic, unchanged thresholds, contamination-only replacement and quiet hold, and durable failure/capacity charging. The three native Go fixture tests cover relay queue behavior, topology and arm identity, for 16 deterministic tests total. The paired-arithmetic regression uses deliberately different round magnitudes so ratios of medians cannot substitute for median paired ratios. No new fuzz, timing or platform cross-product is introduced.

## Interpretation

Useful goodput counts receiver-read STREAM payload bytes in the observation window plus unique DATAGRAM payload bytes whose send timestamp is inside the window. STREAM completion and DATAGRAM delivery/latency are reported separately. B10's inherited “about one handoff” comment does not establish a numerical service-gap bound: future-paced ready candidates can participate in the service floor, and pacing priority precedes byte ranking. The unequal-path observations describe finite measured behavior under that policy; they do not establish a universal application-delay or equal-rate promise.

The [independent arithmetic audit](arithmetic-audit.md) and [full integer/Decimal results](arithmetic-audit.json) reproduce the three gates directly from raw role JSON/logs without importing the driver. It checks all 58 receiver STREAM series and useful DATAGRAM count/byte arithmetic across 37 attempts, plus identity and inventory. Individual DATAGRAM timestamps are not retained, so deduplication and latency quantiles rely on the inspected receiver instrumentation. A separate post-campaign [native hash read](native-hashes.txt) confirms the retained executable, driver and source archive still match the recorded identities. The one-use auditor script is archived outside the repository; it is not a maintained validation dependency.

## Result and qualification

The fixed comparison is **positive**: all 36 required observations are valid, with no aggregate product failure. The campaign used 37 charged attempts because unequal round zero A attempt zero was contaminated and replaced once after the existing quiet hold passed. Both attempts remain in the raw evidence. There are no clean-result reruns. The [observations](aggregation/observations.jsonl), [superseded observation](aggregation/superseded.jsonl), [attempt ledger](aggregation/ledger.json), [driver summary](aggregation/summary.json) and per-role JSON/logs retain all values.

The three accepted gates use medians of round-paired ratios:

| Gate | Round 0 | Round 1 | Round 2 | Median | Required |
| --- | ---: | ---: | ---: | ---: | ---: |
| Balanced E / better single A | 1.993477928 | 1.990457023 | 1.988197925 | 1.990457023 | ≥ 1.20 |
| Balanced E / independent C | 0.994787599 | 0.991018403 | 0.988218920 | 0.991018403 | ≥ 0.95 |
| Shared Reno competitor beside E / beside C | 1.044398214 | 0.893054277 | 1.069269575 | 1.044398214 | ≥ 0.90 |

The shared round-one competitor ratio is 0.893054277, below 0.90 individually. It remains in the paired inventory; the unchanged acceptance rule is the median of three paired ratios, 1.044398214. These three rounds do not establish a statistical confidence interval or per-round fairness guarantee. The better balanced single path is A, selected from measured median useful bytes before forming paired ratios. Ratios of unrelated medians are not used for the gates.

| Topology | A median Mbit/s | B median Mbit/s | C median Mbit/s | E median Mbit/s |
| --- | ---: | ---: | ---: | ---: |
| balanced | 47.022315 | 46.968161 | 94.521069 | 93.737946 |
| unequal | 46.992751 | 23.199417 | 70.877674 | 70.454539 |
| shared | 35.424097 | 36.028163 | 38.159548 | 38.002385 |

Unequal-path diagnostics are reported separately, without qualification thresholds. Values below are rounds zero/one/two; C has two independent focal connections, so each latency cell retains the A-path/B-path pair rather than inventing a combined percentile.

| Arm | Completed 1 MiB STREAM objects | STREAM completion p99 ms | DATAGRAM useful delivery | DATAGRAM latency p99 ms |
| --- | --- | --- | --- | --- |
| A | 320 / 320 / 320 | 882.116 / 877.659 / 877.581 | 0.999800 / 0.999667 / 0.999933 | 29.716 / 29.475 / 29.503 |
| B | 152 / 152 / 151 | 1769.875 / 1760.233 / 1759.068 | 1.000000 / 1.000000 / 1.000000 | 83.151 / 83.328 / 82.268 |
| C | 490 / 490 / 492 | 489.543, 903.613 / 483.093, 897.109 / 463.642, 902.630 | 1.000000 / 1.000000 / 1.000000 | 29.598, 84.272 / 29.653, 85.922 / 29.661, 84.297 |
| E | 488 / 488 / 488 | 605.054 / 614.276 / 608.897 | 0.999800 / 1.000000 / 0.999933 | 83.173 / 82.729 / 83.138 |

Every unequal observation reports zero empty STREAM seconds. E completed 488 objects in each round; its p99 STREAM completion was 605.054/614.276/608.897 ms and DATAGRAM p99 latency 83.173/82.729/83.138 ms. These are measured outcomes at the fixed load, not numerical service guarantees.

## Charges and closure boundary

The [native charge receipt](native-charge.json) sums actual outer observation envelopes once, including the discarded attempt: 37 instances and 2850.03670255187898 host-seconds. Setup adds zero instances and 4.9198307460173965 seconds, totaling 2854.9565332978963765 seconds for this native work. Quiet waiting before admission holds no fixture and is uncharged. The [campaign log](aggregation/campaign.log) retains the named-process/core contention and quiet hold; no host workload policy changed. Global [program #646](https://github.com/the-sarge/quic-go-fast/issues/646) progressed from 337 instances /13165.02220736435985 seconds before setup to 374 /16019.9787406622562265 after the campaign, leaving 46 instances /12780.0212593377437735 seconds before this product PR's hosted peer job. Hosted charges and final exact-head review/certification receipts belong to the product PR discussion and live ledger, without double-counting inner durations.

This positive result selects B12 (#1385)'s experimental BBR aggregate publication branch, subject to that slice's final public admission, independent-peer, cleanup and source-applicability obligations. Aggregation remains publicly rejected in B11 (#1384). The product PR owns B11 completion and the B12 frontier; no follow-up algorithm, threshold adjustment, further campaign or full Q2/adoption claim is introduced.
