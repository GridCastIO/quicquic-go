# BBR ordinary-flow pipeline redesign (#1368)

## Contract and delivery

Owner dispatch: `$redesign-pipeline` on OmniFocus `kn80VyK4b9q`, 2026-11-14; finish by merging after review and required checks pass. This resumes [issue #1368](https://github.com/the-sarge/quic-go-fast/issues/1368), previously deferred. Preserve BBR's ordinary connection semantics, endpoint write-grant ownership, bounded pending local bytes, accepted/uncertain/unsubmitted outcomes, authenticated early ACK handling, loss/ECN evidence, cancellation and native borrow lifetime. Preserve default Reno and public Reno-only multipath support. BBR multipath enablement remains a separate owner decision; full Q2 [#599](https://github.com/the-sarge/quic-go-fast/issues/599) and aggregation [#1374](https://github.com/the-sarge/quic-go-fast/issues/1374) are outside this task.

The existing ordinary-cost targets are controller-matched opted-in/unregistered application goodput >= 0.95 and server CPU per useful byte <= 1.10, with the existing echo/send latency, memory, close, progress, write-error and loss checks unchanged. Qualification covers the affected mixed-bulk and stateless-pressure cells; source changes determine which existing Reno/native cases need revalidation. Useful output is receiver-counted application content during the harness's 60-second window; transport ACKs and local write completion are different boundaries. CPU/byte uses server window CPU divided by all useful bytes, including background; retain ordinary and background byte counts separately. No absolute throughput target was supplied. Report absolute throughput and CPU beside ratios.

Initial control: `62247738352d9f645935518fa9259fe4e2f48dc8`, Go 1.27.4. Historical baseline: [B5 receipt (#1044)](2026-11-14-multipath-b5-receipt.md), measured `4e80d3cf4fa7454ffc3e2a46655afd5f81f86313`. Historical mixed-bulk median ordinary goodput 8.822 → 7.483 Gbit/s; server window CPU 83.934 → 97.952 seconds. Stateless-pressure 8.864 → 7.714 Gbit/s; CPU 82.967 → 95.218 seconds. These values describe the historical candidate, not current qualification. B6 retired its BBR fixture, so fresh ordinary diagnostic selection must be explicit and cannot revive public BBR multipath support.

Existing [program ledger (#646)](https://github.com/the-sarge/quic-go-fast/issues/646): 217/420 instances and 8,860.629/28,800 host-seconds at dispatch, leaving 203 instances and 19,939.371 seconds. All remote diagnostic and qualification attempts charge this same ledger. Do not pause other projects' runners or VMs. Use the existing fixture-core/sibling quiet and contamination checks; host load elsewhere alone is not disqualification. Minimax is native Linux amd64, Ryzen AI Max+ 395, Linux 7.0.0-30-generic; server CPUs 8–11, client 12–15, SMT siblings 24–31 observed for interference. Local development host has 12 performance and four efficiency cores; local unit evidence is not native cost qualification.

## Whole-pipeline map and current design

Application `SendStream.Write` supplies stream content; the connection goroutine packs frames, owns recovery and controls BBR pacing. On an unregistered endpoint packet construction registers normal recovery and the per-connection send queue owns the asynchronous socket write. A granted endpoint installs `nativeOrdinarySender` even for a connection without multipath negotiation. Construction creates local completion identities and transfers payload/protection work to the bounded endpoint writer; the connection keeps completion tokens and packet metadata. The endpoint claims a request, sets its deadline, protects/submits UDP/GSO, clears the deadline and publishes an immutable result. The endpoint returns byte credit after payload disposal. Separately, the connection consumes immutable results before receives/timers, qualifies delivery and ECN evidence, and frees connection-side result records. Credit return and result-record reuse are different boundaries. A peer ACK settles transport delivery; receiver consumption establishes useful output. Close/revocation preserves pending native borrows and exact-once disposal.

The granted path moves encryption to the endpoint writer; this is placement, not removed work. BBR makes at most one owned handoff per emission opportunity, so the endpoint may incur more fixed submission work per useful byte. Its local completion path explicitly declines the existing Reno accepted-span optimization and invokes scalar rich delivery, ECN, loss-feedback and timer work for every packet. Loss scanning already exits when the physical history prefix is above the largest ACK; do not infer quadratic scans. Early ACKs before native completion fence delivery timing and may affect BBR rate estimation separately from CPU cost.

Inspected owners: `send_stream.go`, `packet_emission.go`, `packet_emission_bbr.go`, prepared/local emission, native protection/staging/completion, `connection.go`, and local completion/congestion dispatch in `internal/ackhandler`. Failure and path transitions have source-level coverage here; this investigation has not yet measured their cost or requalified multipath interop, ECN, migration, loss, GSO-off or DATAGRAM paths. The BBR-only E02 empty-feedback helper is provisionally retained; later sections record its evidence and limits.

## Evidence and experiments

Append-only plans and outcomes: [experiment ledger](2026-11-14-bbr-ordinary-cost-1368-experiments.md). Raw outputs and immutable source/patch manifests will live under `2026-11-14-bbr-ordinary-cost-1368/`; remote originals use a task-specific directory. Preserve unsuccessful and contaminated attempts. Timing and profiling results are separate evidence.

## Delivery state

In progress: retained E09 has a valid goodput pass (0.969333090) and CPU/useful-byte miss (1.156907217). E11's guard expansion also has a clean CPU-only miss (0.958535502 /1.152107201), but granted absolute CPU/useful byte worsens 1.1208% versus E09. Reject E11 under its predeclared useful-benefit criterion and restore E09 plus the deterministic test-fixture fix. Reassess endpoint transaction/writer/timer coordination and repeated native protection setup before selecting the next experiment. Final ordinary-cost qualification, BBR interop, full-panel review, exact-head hosted checks, merge, journal and tracker closure remain. Recommendation: use source and current attribution to identify a structural discriminator; do not repeat the clean miss or qualify prematurely.

## Current design update — E02/E03, 2026-11-14

E02's BBR-only empty-loss-feedback helper is provisionally retained: one clean pair improved granted absolute goodput from 7.595 to 7.761 Gbit/s, with CPU/useful-byte ratio 1.305 and goodput ratio 0.890. E03 synchronous protection is rejected: 6.917 Gbit/s and CPU/useful-byte ratio 1.373 despite lower total CPU. Deferred writer protection is restored byte-for-byte; the retained runtime at `1cfcd9ed0` is E02's `eab1ff617` behavior. Both overall targets remain missed. Repetition/qualification is pending.

Pipeline reassessment: completion overhead accounts for only part of the deficit; moving AES back onto the connection loses valuable overlap. Cross-turn grouping would need Building deadline/expiry coverage, credit-refusal flushes and fairness validation, so it is not yet selected. Next experiment distinguishes CPU work from local-credit waits and timing-sample exclusions with bounded scalar observation. Program cumulative usage is 225/420 instances and 9476.959039284/28800 host-seconds. No host policy changes or outstanding remote workloads remain after E03.

## Current design update — E04, 2026-11-14

E04's instrumented pair is contaminated and supplies no performance claim. Its counters and source trace shift investigation toward the four connection-side native result records and small, one-buffer requests. Granted byte-credit refusal was absent outside four probe-isolation cases; 99.418% of ACK samples were model-usable, with zero controller clock rejects. Standard GSO storage is 20 KiB, so four one-buffer records can bind before the 128 KiB byte ceiling; records can remain occupied after payload credit returns. E04 shows four nonempty records in 14 snapshots, while recovery history remains far below its capacity. This is a construction/request/result-owner mismatch to test, not a reason to enlarge a limit.

Next decision: compare bounded grouping within one emission invocation against a larger existing GSO buffer tier; preserve aggregate Q pacing, 2Q lifetime credit, receive/control fairness, first-request deadline and exact-once completion. Cross-turn Building lifetime is not required for the first discriminator. Partial-credit admission and ACK-order changes are not selected. Program cumulative usage is 227/420 instances and 9631.032339249/28800 host-seconds, leaving 193 / 19168.967660751. The product runtime still equals E02; all observer code is retained only as an evidence patch.


## Current design update — E05/E06, 2026-11-15 UTC

E05 source `dd2749714c5aabdce2a251ea5083d097954fd25a` passed correctness tests and independent source review, but its original pair and one justified replacement lacked a valid clean comparison. No throughput/CPU gain is claimed. Preserve the bounded two-buffer design in its source commit, tests and raw evidence. E06 selects the alternative request geometry: one native BBR GSO member using existing 65,535-byte storage and a 65,507-byte send ceiling when an ordinary standard-packet request needs more than 20 KiB. Keep Q / 2Q, exact reservation, one handoff, deferred protection and native ownership; prevent accidental changes to Reno/jumbo deferred eligibility. Larger construction/submission and return-time granularity are explicit costs to test. The [experiment ledger](2026-11-14-bbr-ordinary-cost-1368-experiments.md) owns the pre-code plan and finite scope.

Program #646 cumulative usage is 231/420 instances and 9939.170252017/28800 host-seconds, leaving 189 instances / 18860.829747983 seconds. No remote task workload or shared-host changes remain after the E05 replacement.


## Current design update — E06 result and E07 observation

The single-member E06 alternative reduces granted server CPU from E02's 95.280 to 88.037 seconds but lowers useful goodput from 7.761 to 7.523 Gbit/s; absolute granted CPU/useful byte improves about 4.69%. Its own control is 8.684 Gbit/s / 83.144 seconds. Both overall targets remain missed; one pair is not repeatability evidence. Keep the exact larger-member source as an experimental design under revision. Before further runtime changes, E07 repeats bounded observation for the new credit/request geometry and obtains current CPU attribution. E04's zero usable-partial-credit refusals described small requests, not this new regime.

Program #646 usage is 233/420 instances and 10093.240678141/28800 host-seconds, leaving 187 instances /18706.759321859 seconds. The E06 process is complete; no shared-host state was changed.


## Current design update — E07 admission witness and E08

E07's profiled/observed timing is excluded, but its complete counters identify repeated admission refusal despite substantial free credit. Granted interior calls refused 10.5261% of ordinary requests; 99.5573% of refusals had usable partial room, with no old-generation or isolation cause. Mean requested/free bytes across refusal calls were 60,476 / 57,076. Healthy usable-sample counts and zero paced stops deprioritize widespread timing starvation. Current CPU attribution leaves rich completion as a separate later alternative.

E08 keeps E06's single-member geometry and changes only eligible ordinary native BBR admission from exact N to a whole-packet range [M,N]. The existing synchronized credit owner chooses actual bytes, and both admission and waiter rearming use the same minimum-M predicate. ACK/control, generation, isolation and exactly-once completion remain explicit proof obligations. All other paths retain exact sizing. No performance gain is yet claimed. Program #646 usage is 235/420 instances and 10247.357461948/28800 host-seconds, leaving 185 / 18552.642538052.


## Current design update — E08 inconclusive timing

E08 source `740f07cd88f96c379991c7c3880aafac7a84e20d` passed local/native mechanism checks and independent source/test audits. Its first pair has substantial fixture-core interference in both profiles (57.415 / 38.303 foreign CPU seconds), so nominal ratios 1.031 / 1.055 are excluded. Control goodput was only 7.023 Gbit/s, granted 7.237; no improvement or feasibility claim follows. The candidate remains unchanged pending a validity reassessment.

Program #646 usage is 237/420 instances and 10401.432815502481/28800 host-seconds, leaving 183 /18398.567184497519. No task timing workload or shared-host modification remains.


## Current design update — E08 measurement dependency

The exact-binary replacement also has substantial fixture-core interference in both profiles (19.848 /15.846 foreign CPU seconds), despite the preceding 90-second quiet streak. Its descriptive ratios 0.927 /1.180 are excluded, just as the first pair's nominal pass was excluded. No performance disposition or E09 selection follows. The preplanned E08 retry has been used; further timing requires a concrete quiet execution window or equivalent native resource, not another longer quiet heuristic. Candidate documentation and review-tool preparation can proceed independently, but feasibility and qualification remain unverified.

Program #646 usage is 239/420 instances and 10555.475946517745/28800 seconds, leaving 181 /18244.524053482255. The owner was asked for the needed window/resource; no shared-host change or task timing workload remains.


## Current design update — E08 valid quiet-window comparison

The unchanged E08 binary now has a valid diagnostic in the owner-confirmed quiet window. Control/granted throughput is 8.825192105 /8.282160162 Gbit/s, CPU 82.564210 /92.252836 seconds, with negligible measured foreign CPU. Both target ratios remain missed (0.938467975 /1.190607021), but granted absolute CPU per useful byte improves 4.82% over the larger-member E06 alternative while output rises 10.09%. Provisionally carry admission with the larger member; one pair is not final qualification or repeatability evidence. Registration/publication has immediate per-packet consumers and distinct evidence lifetimes, so keep it unchanged for the next discriminator. The existing fully accepted native-member seam is the next bounded structural question; no complete-cost saving is inferred from overlapping profiles.

Program #646 usage is 241/420 instances and 10709.552619184451/28800 seconds, leaving 179 /18090.447380815549. No task workload remains.


## Current design update — E09 correctness and setup accounting

E09 is integrated with independent source/test audits clear and affected local checks passing. It reconciles a fully accepted BBR native member through the existing recovery owner while preserving ordered per-packet facts and the generic qualification traversal. Native timing is pending. The existing program #646 accounting rule requires a separate recovered setup charge: zero instances /44 conservative artifact-based seconds for eight earlier successful native build/check sets. This estimate is explicitly distinguished from an original monotonic measurement; raw observation receipts are unchanged. Corrected usage is 241/420 instances and 10753.552619184451/28800 seconds, leaving 179 /18046.447380815549 before E09 setup.


## Current design update — E09 inconclusive comparison

E09's two observations were contaminated by 50.895 /74.013 foreign CPU seconds; their nominal 0.9946 /1.1054 ratios are excluded. The 90-second prelaunch observation and subsequent fresh driver checks did not establish sustained in-run quiet. Preserve the candidate without a performance-retention claim or automatic retry. The owner has been asked for an actual continuous Minimax window; independent source review can prepare conditional next questions, but invalid timing does not select another change.

Program #646 usage, including recovered setup and measured E09 setup, is 243/420 instances and 10915.44544463989606/28800 seconds, leaving 177 /17884.55455536010394. No task operational workload remains and no shared-host policy changed.


## Current design update — E09 valid result and E10 diagnosis

The replacement is valid with negligible foreign CPU. Only CPU/useful byte fails (1.156907217); goodput passes (0.969333090), and all other product checks pass. Provisionally retain E09 and select bounded current-source member-coverage counters plus profiles, because E07 predates both admission and completion changes. Timing from that instrumented diagnostic will be excluded. Usage is 245/420 instances /11069.54967272945961 host-seconds, remaining 175 /17730.45032727054039.


## Current design update — E10 attribution and E11 witness proof

E10 timing is excluded and both observations are contaminated. Its counters nevertheless conserve: the granted interior member path handled 58.6744% of native packets; members containing another 41.1338% first failed the composite PTO group, not rich preflight. The exact failing conjunct and quiet prevalence are unknown. Source review supports testing only BBR's prior-positive-PTO requirement: full token preflight and unchanged first-packet acceptance can establish the required witness before the scalar timer update. E11's pre-code plan preserves all other guards, Reno behavior and the complete closed-span mutation proof. Usage is 247/420 instances /11231.34290643550578 seconds, remaining 173 /17568.65709356449422.


## Current design update — E11 rejected after valid comparison

E11 passed correctness and actual timing validity but did not establish useful end-to-end benefit. Its single pair passes goodput and misses CPU/useful byte; both granted output and absolute CPU/useful byte are worse than valid E09. Reject the guard expansion and dedicated tests, retaining all immutable proof and raw evidence. The selected runtime returns to E09 with its deterministic test correction. Current pipeline reassessment examines endpoint-owner coordination and repeated protection setup against mandatory construction/registration; no next runtime experiment is selected yet. Program #646 usage is **249/420 instances /11393.61225322514615 host-seconds**, remaining **171 /17406.38774677485385**. No task workload or host modification remains.
