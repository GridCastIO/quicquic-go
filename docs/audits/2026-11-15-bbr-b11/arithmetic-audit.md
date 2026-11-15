# Independent arithmetic audit — B11 issue #1384

Independent result: **positive** under the accepted median round-paired criteria. Source `8c34fbac874adf55f096b6c67d51244160169422`; 36 valid observations from 37 retained attempts. This audit reads role JSON/logs directly and uses Python integer/Decimal arithmetic without importing or executing the campaign driver or its summarizer. The driver summary is compared only after independent derivation.

Checked 58 receiver flow series across all 37 attempts: every 60-bucket STREAM sum matches its stored total; each useful DATAGRAM count × 1000 matches its useful byte count. Focal useful bytes sum these two measures and exclude the ordinary Reno competitor. Throughput is useful bytes × 8 / 60 / 1,000,000. DATAGRAM deduplication and timing are verified against pinned fixture source; individual message/timestamp samples are not retained, so uniqueness and latency quantiles cannot be reconstructed independently of the receiver instrumentation.

Inventory, sequence, pins and role agreement checks passed: three topologies × three rounds × A/B/C/E, orders ABCE/CEAB/EABC, seeds 1044 + 100 × topology index + round, 10-second warmup, 60-second window, 120-second invocation bound. All role JSON agrees with ledger copies and all 111 role logs report PASS. Expected BBR focal and ordinary Reno competitor controllers, aggregate negotiation/two active paths, matched flow counts, 15,000 offered DATAGRAMs per observation, topology rates/delays/queues, endpoints and timestamps agree. Setup source archive hash, source tree, pinned driver hash, native Linux amd64 build information, Go 1.27.4, CPU placement and SMT sibling set agree with retained pins. The binary hash is recorded, not remeasured from a local executable.

| Topology | Round | A useful bytes | B useful bytes | C useful bytes | E useful bytes |
|---|---:|---:|---:|---:|---:|
| balanced | 0 | 352667360 | 351964756 | 706718297 | 703034598 |
| balanced | 1 | 353494714 | 352261210 | 709992906 | 703616036 |
| balanced | 2 | 352357432 | 352811153 | 708908017 | 700556315 |
| unequal | 0 | 352048792 | 173696164 | 529443769 | 529887177 |
| unequal | 1 | 353096621 | 174862559 | 531903625 | 528409042 |
| unequal | 2 | 352445633 | 173995629 | 531582554 | 528225401 |
| shared | 0 | 263812828 | 274750625 | 287814656 | 285017889 |
| shared | 1 | 269113397 | 270211226 | 286196613 | 293048918 |
| shared | 2 | 265680730 | 263099358 | 282284242 | 276592006 |

| Accepted criterion | Round 0 | Round 1 | Round 2 | Paired median | Floor |
|---|---:|---:|---:|---:|---:|
| balanced E/single | 1.993477928 | 1.990457023 | 1.988197925 | 1.990457023 | 1.20 |
| balanced E/C | 0.994787599 | 0.991018403 | 0.988218920 | 0.991018403 | 0.95 |
| shared competitor E/C | 1.044398214 | 0.893054277 | 1.069269575 | 1.044398214 | 0.90 |

Balanced better measured single is A: median A 352,667,360 versus B 352,261,210 useful bytes. A is selected once on its median and then paired by round. Shared competitor round 1 is **0.893054277**, below 0.90; it remains retained and reported. Its three-round median passes the accepted criterion. There is no clean rerun or replacement of that below-floor round.

| Shared competitor STREAM bytes | Round 0 | Round 1 | Round 2 |
|---|---:|---:|---:|
| C | 67854148 | 70389921 | 74138350 |
| E | 70866751 | 62862020 | 79273882 |

Unequal-path diagnostics have no acceptance threshold. STREAM completion and DATAGRAM delivery/latency are kept separate below; for C each slash-separated value preserves focal-a / focal-b and is not presented as a merged quantile.

| Arm / round | Useful Mbit/s | STREAM objects completed | STREAM p50 ms | STREAM p99 ms | DATAGRAM useful delivery | DATAGRAM p99 ms |
|---|---:|---:|---|---|---:|---|
| A / 0 | 46.939838933 | 320 | 748.216003 | 882.115698 | 0.999800000 | 29.715949 |
| A / 1 | 47.079549467 | 320 | 748.437367 | 877.659412 | 0.999666667 | 29.475483 |
| A / 2 | 46.992751067 | 320 | 748.280562 | 877.581105 | 0.999933333 | 29.502875 |
| B / 0 | 23.159488533 | 152 | 1593.887413 | 1769.874742 | 1.000000000 | 83.151349 |
| B / 1 | 23.315007867 | 152 | 1588.884673 | 1760.233046 | 1.000000000 | 83.327904 |
| B / 2 | 23.199417200 | 151 | 1593.490276 | 1759.068383 | 1.000000000 | 82.268097 |
| C / 0 | 70.592502533 | 490 | 373.578965 / 767.797691 | 489.542596 / 903.613125 | 1.000000000 | 29.598428 / 84.271539 |
| C / 1 | 70.920483333 | 490 | 372.214728 / 768.40589 | 483.09297 / 897.109207 | 1.000000000 | 29.653292 / 85.922082 |
| C / 2 | 70.877673867 | 492 | 372.822611 / 767.812346 | 463.642258 / 902.62965 | 1.000000000 | 29.661372 / 84.29693 |
| E / 0 | 70.651623600 | 488 | 519.86912 | 605.054101 | 0.999800000 | 83.17266 |
| E / 1 | 70.454538933 | 488 | 519.657763 | 614.276243 | 1.000000000 | 82.729332 |
| E / 2 | 70.430053467 | 488 | 521.130926 | 608.897189 | 0.999933333 | 83.138389 |

Time accounting: exact Decimal sum of the 37 individual occupied_s fields is **2850.03670255187898 host-seconds**. Setup is separate at **4.9198307460173965 host-seconds**, giving **2854.9565332978963765** together. Ledger's float accumulator is 2850.036702551879; the difference is -2E-14 seconds (rounding only). Retained contaminated unequal / round 0 / A / attempt 0 contributes 77.01157137099653 seconds and is charged once; valid replacement attempt 1 is charged once. All other attempts are attempt 0, so no clean reruns are present. The replacement follows recorded quiet admission; pre-admission waiting is excluded from occupied time.

Scope: this is finite example-level evidence from the fixed native Linux amd64 venue. It does not establish universal network throughput, arbitrary unequal-delay behavior, one-flow fairness, or an application-adoption recommendation. Raw role metrics agree with driver totals; no material arithmetic discrepancy was found.

Recommendation: accept this positive arithmetic result for issue #1384, preserve the below-floor individual shared round and exact ledger charge, and let issue #1385 consume it only within the accepted experimental aggregate-support scope.
