# B5 receipt: aggregation comparison and BBR revalidation (#1044)

[B5 (#1044)](https://github.com/the-sarge/quic-go-fast/issues/1044) completed its fixed evidence. The controller-matched aggregation comparison is **valid and negative**: arm E failed the balanced cell's independent-connections floor. Aggregate support is therefore denied, and B5's evidence delivery is complete. BBR primary/backup passed its six interop cases and failed its ordinary-cost gate. That raw failure is recorded here and decided when B6 #1045 starts. The contract is the [B5 slice](../adr/2026-10-24-multipath-bbr-plan.md#b5) and its [qualification policy](../adr/2026-10-24-multipath-bbr-plan.md#qualification-and-adoption-policy). The raw evidence is under [`2026-11-14-multipath-b5/`](2026-11-14-multipath-b5/).

| Evidence | Candidate | Binary SHA-256 |
| --- | --- | --- |
| Interop, ordinary cost, Reno rerun | `4e80d3cf4fa7454ffc3e2a46655afd5f81f86313` | ordinary cost `bb631588…0853`; interop test `2247a29b…1ecd` |
| Aggregation comparison | `ba51ba67bf09f872c558e1519a3839f74795a021` | `13f05e4c36578c93aef300e00d3d28655460a45020a31a76e999f8a3c499bd23` |

The two candidates' Go sources are identical. `ba51ba67b` changes only the aggregation driver's admission gate, its tests and the ledger documents. All the evidence ran on minimax: Linux 7.0.0-30-generic, Go 1.27.4, AMD Ryzen AI Max+ 395. The [aggregation identity](2026-11-14-multipath-b5/aggregation-gated/aggregation/identity.json) and [source archive hash](2026-11-14-multipath-b5/aggregation-gated/source-archive.sha256) pin the comparison.

## Aggregation comparison

All 54 cases completed on one candidate, binary and driver, with no product failure in any arm. Three observations were contaminated by external load. The [host journal excerpt](2026-11-14-multipath-b5/host-journal-excerpt.log) records the GridCast runner containers and GARM VMs. Each had its one replacement after the quiet gate's hold, and every replacement was clean. No contaminated observation remains in the inventory. The largest foreign CPU in a kept observation was 1.41 s, against a limit of about 3.85 s. Sources: the [summary](2026-11-14-multipath-b5/aggregation-gated/aggregation/summary.json), [ledger](2026-11-14-multipath-b5/aggregation-gated/aggregation/ledger.json) and [log](2026-11-14-multipath-b5/aggregation-gated/aggregation/campaign.log).

| Threshold | Topology | Median (range) | Floor | Verdict |
| --- | --- | ---: | ---: | --- |
| E over the better single path (B) | Balanced | 1.764 (1.701–1.783) | ≥ 1.20 | Pass |
| E over two independent connections (C) | Balanced | **0.879** (0.845–0.888) | ≥ 0.95 | **Fail** |
| Reno competitor beside E vs beside C | Shared bottleneck | 0.960 (0.897–0.979) | ≥ 0.90 | Pass |

Ratios are round-paired useful goodput. **Support: negative.** The failed balanced cell blocks the aggregate support claim. By the contract, no experiment is added and no other algorithm is chosen. Passing the shared-bottleneck coexistence cell doesn't qualify aggregation on its own.

Median useful goodput per arm, in Mbit/s, over the 60-second window:

| Topology | A | B | C | D (Reno, informational) | E | F (forced round-robin) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Balanced | 46.9 | 47.0 | 94.5 | 96.0 | 83.1 | 93.8 |
| Unequal delay/rate | 47.0 | 23.4 | 70.8 | 72.0 | 48.5 | 70.5 |
| Shared bottleneck | 35.5 | 35.8 | 38.0 | 27.4 | 38.3 | 38.8 |

- **Path use:** E under-used the second path. On balanced, path b carried a median 276 MB against path a's 361 MB. F's forced round-robin split them 359/359 MB. On unequal, E sent 13 MB on the slower path, against F's 180 MB. E/F useful goodput was 0.885 on balanced, 0.688 on unequal and 0.988 on shared. These are informational, as the contract declares for F.
- **Unequal topology** (reported, no threshold): STREAM completion and DATAGRAM delivery are separate. For the slowest focal connection in each observation, E's median object p50/p99 was 740/788 ms, A's 749/886 ms, and C's 768/929 ms. E completed 332 objects, against 490 for C and 488 for F. Every arm delivered at least 99.98% of offered DATAGRAMs. E's DATAGRAM p99 latency was 37.6 ms, against about 83–90 ms for the arms that split their load across both paths. E's unequal result is 1.033 of the better single path and 0.685 of C.
- **Shared bottleneck:** the competitor's median goodput was 9.2 Mbit/s beside E and 9.4 beside C. Beside D, Reno aggregation, it was 20.6, with D's own goodput at 27.4.
- No observation recorded a product failure, an empty second or a DATAGRAM duplicate. Only D's Reno arm recorded sender losses: 467–690 per observation. The lowest DATAGRAM delivery in any observation was 99.80%.

The three contaminations and their replacements:

| Observation | Foreign CPU | Hold before replacement | Replacement foreign CPU |
| --- | ---: | ---: | ---: |
| Balanced round 0 F | 24.159 s; a GridCast runner container was created at 16:05:50, and its GARM VM started at 16:06:37 | 2,450 s | 0.774 s |
| Shared round 1 A | 5.399 s, unattributed; a GridCast container was created 6 s after the window, and its GARM VM ran from 17:44 to 17:48 | 629 s | 0.486 s |
| Shared round 2 F | 7.896 s, unattributed; the transfer window ended at 17:58:55.5, a GridCast container was created at 17:58:56.0, and named load ran from 17:59:33 to 19:12 | 4,679 s | 0.313 s |

Arm E itself was clean in all nine observations.

## Contamination stops and the fixture diagnosis

Two counted invocations on candidate `4e80d3cf4` stopped at the same point. Balanced round 0 arms A–D were clean both times. Arm E attempt 0 was contaminated, its one replacement was contaminated as well, and the driver stops when that happens. Their [first](2026-11-14-multipath-b5/aggregation/campaign.log) and [second](2026-11-14-multipath-b5/aggregation-rerun/campaign.log) logs and ledgers are preserved.

| Invocation | E attempt 0 foreign CPU | E replacement foreign CPU | Limit | Charged |
| --- | ---: | ---: | ---: | ---: |
| First | 15.499 s | 31.235 s | 3.85 s | 6 instances, 462.184 s |
| Clean rerun | 34.221 s | 36.579 s | 3.85 s | 6 instances, 462.148 s |

All four E attempts were contaminated, against 0 of 8 A–D attempts. The [resume conditions](https://github.com/the-sarge/quic-go-fast/issues/1044#issuecomment-6878881696) call for a diagnosis if E is contaminated again on a host with no external load. Given 4 of 4, the fixture was ruled out before any further counted invocation. Diagnosis runs on minimax ran the retained binary through the driver's own observation function, with a `sched_switch` trace (bpftrace) of the fixture CPUs and their SMT siblings attached. They are charged in the ledger below. The [diagnosis evidence](2026-11-14-multipath-b5/diagnosis/) keeps the tools, per-run summaries and analysis.

- **The accounting is sound.** In run 2, `/proc/schedstat` running time agreed with the traced task time within about 0.1 s on every fixture CPU: 2.5% in aggregate for E and 5.8% for A ([analysis](2026-11-14-multipath-b5/diagnosis/run2-analysis.log)). The fixture's own threads were fully inside `RUSAGE_CHILDREN`: E's traced fixture time was 22.95 s, and its rusage was 23.98 s.
- **The foreign time was external.** Run 1's E observation ran from about 14:38:00 to 14:39:16. A GridCast runner container was created inside that window, at 14:39:00 (`podman`, `dpkg-query`, `yq`, `qemu-img` image preparation), and its GARM VM started afterward, at 14:39:53. The container's burst of short-lived processes filled the trace map, and bpftrace reported 77,941 failed updates. So run 1's trace undercounts, and its numbers aren't used. In run 2, the foreign time on the fixture CPUs and their siblings was the runner's `transfer.test` (10.6 s during E, 4.1 s during A) and vCPU threads of a persistent external qemu process (PID 1462298), present in all four diagnosis traces. The preserved evidence doesn't identify its guest. The only long-running VM in the [journal supplement](2026-11-14-multipath-b5/host-journal-supplement-vm.log) is a Windows 11 guest, `qemu-1054`, running from 07:05 to 18:45. The driver's named-process pattern doesn't match that VM, so the contamination limit is what bounds its load. Run 2's arm A was contaminated by the same job (5.78 s), so arm E isn't special. No fixture thread or child carried foreign time. Kernel and other host tasks carried a few tenths of a second (`ksmd` 0.14–0.22 s, `sshd`, `landscape-sysinfo`).
- **Why every E:** each time, the external jobs arrived inside E's window. No fixture mechanism that draws external load was found. In the gated campaign below, E was clean in all nine observations, while A and F were contaminated.
- **Fixture defect found:** in both counted stops, the driver admitted E's replacement on one two-second fixture-core sample while the named external job was still running. Each replacement's quiet record shows `named_process_present: true`. The replacement then ran under the load that had contaminated its original.

The fix (`2d5dbc6db`, then `ba51ba67b` after RAS review `20261114T150737-99398a1bf609276ad71152b0` and its verification) adds a per-invocation quiet gate. Admission waits until five minutes after the last named external process or the last contaminated observation. A `pgrep` failure stops the run before any charge. The contamination limit, the one replacement per observation, the three-replacement campaign limit, the wait limit and pre-launch charging are unchanged. The fixture change makes `ba51ba67bf09f872c558e1519a3839f74795a021` the aggregation candidate. That departs from the resume condition to reuse `4e80d3cf4` and its driver, under the resume brief's rule: a fixture defect is fixed under review and re-measured on the new candidate. The aggregation binary was rebuilt from the new archive. Its hash differs because the build path is embedded, but its Go source is identical to `4e80d3cf4`, so the 18 revalidation observations keep their candidate.

## BBR primary/backup revalidation

All 18 required observations ran once on candidate `4e80d3cf4fa7454ffc3e2a46655afd5f81f86313` with no contamination and no replacement.

**Interop (6 instances): pass.** The [R17 matrix](2026-11-14-multipath-b5/interop/matrix-result.json) ran useful transfer, abandon/reopen with late feedback and same-ID migration/rebinding with the quic-go endpoint on BBR primary/backup, in both roles, against picoquic `fbd46d9a1f54ebf9397f2ee6355b5019ab379fb7`. All six cases passed.

**Ordinary cost (12 observations): fail.** Every connection in both endpoint profiles ran BBR. The [raw summary](2026-11-14-multipath-b5/ordinary-bbr/summary.json) records:

| Cell | Opted-in / unregistered goodput | CPU per useful byte | Echo p99 margin | Send-call p99 margin | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| Mixed bulk | 0.848 (0.847–0.851) | 1.367 (1.366–1.368) | −0.951 ms | −0.967 ms | Fail (goodput, CPU) |
| Stateless pressure | 0.869 (0.869–0.871) | 1.318 (1.318–1.322) | −0.934 ms | −0.975 ms | Fail (goodput, CPU) |

Medians, with paired ranges. The tolerances are at least 0.95 goodput and at most 1.10 CPU per useful byte. Both cells passed latency, write, close, progress and loss checks (no empty seconds, write errors, packet losses or DATAGRAM drops). Every mixed-bulk observation delivered 2,516,582,400 background bytes. This is a raw failure of BBR primary/backup's ordinary-cost gate. By [owner decision](https://github.com/the-sarge/quic-go-fast/issues/646#issuecomment-6878878786), what follows from it is decided when B6 #1045 starts; this receipt decides nothing about it.

## Evidence applicability

The [B3 applicability record](2026-11-13-multipath-b3-applicability.md) carried the Reno and native evidence to B3's candidate. Since then, the production changes are B4 #1043 (PR #1347), #1345 (PR #1351), B7 #1357 (PR #1364) and B5's private evidence selection. #1338 (PR #1341) added only tests. Following the [prior-evidence rule](../adr/2026-10-24-multipath-bbr-plan.md#program-budget-and-prior-evidence-validity), this records which receipts still apply to candidate `4e80d3cf4`.

| Surface | Change | Reach outside BBR multipath, and the disposition |
| --- | --- | --- |
| Path views and selection (`multipath_admission.go`, `packet_emission_path.go`, `multipath_scheduler.go`; B4) | Every eligible path is read into a view and a private scheduler chooses the route. Primary/backup stays the default. | Reaches Reno multipath, but not ordinary connections. Reno's affected cell is R18's mixed bulk, whose opted-in background is Reno multipath. It was rerun from the reserve: 6 observations. |
| Native route saturation (`native_ordinary.go`; B4) | Saturation can exclude a released record. | Applies only to a connection with path admission. E6/R21 native classes don't negotiate multipath, so their evidence still applies. |
| BBR readiness and announcement pacing (`packet_emission_bbr.go`, `local_send_credit.go`, `packet_packer.go`; B4, #1345) | BBR plans and readiness, and a BBR announcement's payload pacing | None outside BBR. Reno's announcement and ordinary connections are unchanged. |
| Same-path ACK carriage (`internal/ackhandler`, `packet_emission_ack.go`, `packet_packer.go`; B7) | A multipath receiver prefers the path an ACK acknowledges, with a bounded periodic PING | Reaches Reno multipath. An ordinary connection keeps its inherited ACK and PING behavior. For R18 it is the same mixed-bulk cell. For R17, the required independent-peer job runs all 16 Reno cases on this PR's head once it is ready, and the merge waits for that job to pass. |
| Private evidence selection (`multipath_api.go`, `multipath_credit.go`; B5) | A private selection admits BBR at the gate and copies its scheduler into the registry. | None. Its zero value is the public profile, and only in-package fixtures set it. |

- **Reno primary/backup:** R18's STREAM GSO on/off, DATAGRAM batching on/off and stateless-pressure cells run only ordinary connections, so the [R18 delivery receipt](2026-11-12-multipath-r18-delivery-receipt.md) still applies to them. Mixed bulk is replaced by the rerun below. R17 is re-established when the required independent-peer job passes on this PR's final head; the merge waits for it. The run is recorded in the closing record on #1044. The E6/R21 native evidence still applies.
- **BBR primary/backup:** no earlier interop or ordinary-cost receipt applies. Its evidence is the 18 revalidation observations above. Whether the endpoint-level E6/R21 native evidence counts toward BBR primary/backup is left to B6.
- **Aggregation:** no earlier evidence exists. Its evidence is the comparison above.

### Reno mixed-bulk rerun: owner-accepted deviation

The rerun's cause, recorded in its [identity](2026-11-14-multipath-b5/ordinary-reno-mixed/identity.json), is the B4 and B7 change to the cell's Reno multipath background. Six observations ran clean, with no replacement. [Raw summary](2026-11-14-multipath-b5/ordinary-reno-mixed/summary.json):

- Goodput: median 1.031 (range 1.026–1.031). **Pass.**
- CPU per useful byte: median 1.1223570165026708 (range 1.118–1.126). **Raw FAIL** against 1.10. This is also above the 1.108585 that R18's exact-result acceptance covered.
- Echo p99 margin: −0.607 ms. Send-call p99 margin: −0.906 ms. Write errors, empty seconds and DATAGRAM drops are all zero.

By [owner decision on #646](https://github.com/the-sarge/quic-go-fast/issues/646#issuecomment-6878878786), this exact result is an **owner-accepted deviation** under the [retained-design CPU direction for R18 (#1038)](https://github.com/the-sarge/quic-go-fast/issues/1038#issuecomment-6827181780). The raw failure against 1.10 stays on record. There is no blanket waiver, new ceiling or CPU work, and every other result keeps its raw verdict.

## Ledger

These charges go to the single cumulative ledger under the [Reno program ledger rules](../adr/2026-10-24-multipath-reno-plan.md#program-qualification-ledger-and-sequencing). By [owner decision on #646](https://github.com/the-sarge/quic-go-fast/issues/646#issuecomment-6878878786), the ceiling is 420 instances and 28,800 host-seconds.

| Charge | Instances | Host-seconds |
| --- | ---: | ---: |
| Before B5 | 120 | 1,705.941 |
| Build setup, candidate `4e80d3cf4` | 0 | 35.155 |
| Podman feasibility build | 0 | 60.220 |
| BBR interop | 6 | 15.436 |
| BBR ordinary cost | 12 | 924.568 |
| Reno mixed-bulk rerun | 6 | 462.256 |
| Aggregation, first invocation (stopped) | 6 | 462.184 |
| Aggregation, clean rerun (stopped) | 6 | 462.148 |
| Build setup, candidate `ba51ba67b` | 0 | 5.134 |
| Diagnosis observations: run 1 D and E, run 2 A and E, with tracer setup | 4 | 336.101 |
| Aggregation, gated campaign: 54 cases + 3 replacements | 57 | 4,391.486 |
| **Cumulative** | **217 / 420** | **8,860.629 / 28,800** |

B5 charged 97 instances and 7,154.688 host-seconds; 203 instances and 19,939.371 host-seconds remain. Time spent waiting for quiet held no fixture and is not charged.

The four diagnosis observations are charged under the rule that every attempt spends the ceiling. They are not comparison evidence. Their observation timers total 308.101 s. Tracer setup and teardown add an estimated 7 s per observation, 28 s in all:

- **Setup:** about 5.3 s, measured from the gap between one observation's summary and the next observation's start, in both runs.
- **Teardown:** about 0.3 s, from the file times. Each run's final teardown isn't separately measured.

The charge was added after the fact: the diagnosis scripts and the gated campaign's [identity](2026-11-14-multipath-b5/aggregation-gated/aggregation/identity.json) treated the diagnosis as uncounted. That campaign was supplied 264 instances and 24,666.958 host-seconds. With the diagnosis charged first, its allowance would have been 260 instances and 24,330.857 host-seconds. Its maximum reservation of 57 × 120 s = 6,840 s still fits, so the campaign's preflight holds. The campaign and diagnosis artifacts are unchanged; the journal supplement was added separately.
