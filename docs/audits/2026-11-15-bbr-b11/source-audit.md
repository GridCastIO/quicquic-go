# B11 source applicability and workload audit

Independent source audit for [B11 — Measure the replacement aggregation candidate (#1384)](https://github.com/the-sarge/quic-go-fast/issues/1384) found no contract-relevant discrepancy in the copied workload or driver at candidate `8c34fbac874adf55f096b6c67d51244160169422`.

Compared with base `4cb8970533917426595aef62c70ad0d1d1350b9b`, the candidate adds only `aggregation_test.go`, `interop/multipath/aggregation.py`, and its driver regression tests. No production runtime file changes. Compared directly with frozen B5 source `e048181a680f07dc7560f7df1667d8c065513583`, the workload changes are limited to removing D/F, adapting E’s activation to `conf.multipath.experimentScheduler = scheduleAggregate`, and updating the arm assertions and provenance comment.

The source preserves the following accepted measurement properties:

- **Inventory and pairing:** A/B/C/E, three topologies and three rounds produce 36 observations. Explicit orders are `ABCE`, `CEAB`, `EABC`; seeds remain `1044 + 100*topology_index + round`, with the same seed across each paired round. See driver lines 20–33 and 61–70.
- **Workload and socket matching:** 1 MiB STREAM objects, four concurrent focal objects, 64 KiB write chunks, 1,000-byte DATAGRAMs at 250 messages/second, with the C arm splitting both focal loads evenly between its two connections. Both granted client sockets exist in every arm; the shared-topology competitor remains an ordinary, ungranted Reno connection. See fixture lines 40–61 and 873–906.
- **Topologies:** balanced paths retain separate 50 Mbit/s queues and 10 ms one-way delay; unequal B retains 25 Mbit/s and 30 ms one-way delay; shared paths and the Reno competitor retain one common 50 Mbit/s queue. Queue limits and relay behavior are unchanged. See fixture lines 105–129.
- **Useful-byte boundaries:** receiver STREAM reads count bytes only during the observation window, with the existing nine-byte STREAM header excluded; unique DATAGRAM payloads count when their send timestamp lies in the window, retaining the drain behavior. STREAM completion and DATAGRAM latency remain distinct diagnostics. See fixture lines 583–657.
- **Qualification arithmetic:** the driver retains median round-paired ratios, balanced thresholds `1.20` versus the better measured single path and `0.95` versus C, and shared competitor threshold `0.90`. Unequal-path diagnostics remain unthresholded; actual E failures still yield a negative support result. See driver lines 229–278.
- **Contamination and accounting:** the fixture CPU/sibling inventory, foreign CPU calculation, 5% threshold, quiet gate, one replacement per contaminated observation, maximum three replacements, and clean-failure stop behavior are unchanged. Durable pre-launch attempt charging and supplied-capacity checks are unchanged. See driver lines 303–390 and 470–565.

The driver also adds seed/window/warmup identity validation plus driver SHA and explicit round-order metadata. These are within the accepted wrong-identity/accounting scope and do not change workload execution, throughput arithmetic, thresholds, or replacement decisions.

The candidate therefore preserves the B10 runtime applicability boundary: ordinary and primary/backup runtime paths have no source changes, and E invokes the existing private aggregate selector before construction. The inherited “about one handoff” caveat must remain an interpretation limit: the experiment supplies finite observed throughput, completion, and latency results, not a numerical service-gap promise. This audit did not re-audit scheduler internals or infer such a bound.

This audit covers source applicability and workload preservation only; it does not certify the ongoing campaign’s raw observations or independently recompute its eventual arithmetic.

**Recommendation:** continue the admitted fixed campaign, retain the unequal-path diagnostics and service-gap caveat in the receipt, then perform the independent raw-log arithmetic audit without changing the runtime or repeating clean outcomes.
