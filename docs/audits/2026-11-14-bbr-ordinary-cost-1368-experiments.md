# BBR ordinary-flow experiment ledger (#1368)

Plans precede candidate edits and measurements. Append observations and corrections; retain prior predictions. Shared contract and pipeline: [working record](2026-11-14-bbr-ordinary-cost-1368.md).

## E01 — Reproduce and attribute ordinary granted BBR cost

### Plan — 2026-11-14

- **Question:** Does current ordinary BBR reproduce the granted-endpoint regression, and which owner is the best first optimization target?
- **Observation:** Historical B5 stateless-pressure goodput ratio 0.869 and server CPU/byte ratio 1.318, with low foreign CPU. Server user CPU rose, system CPU stayed similar and context switches fell. No multipath connection exists in that cell.
- **Hypothesis:** Scalar native completion repeats rich-feedback/timer work per accepted packet, adding connection-context CPU and reducing useful throughput.
- **Alternatives:** Endpoint transaction frequency and descriptor/deadline work; packet-protection placement; early-ACK timing fences lowering the model rate; historical candidate or workload drift.
- **Intervention:** Add explicit BBR selection solely to ordinary stateless-pressure diagnostics using current owners. Keep both endpoint profiles controller-matched, existing four-core affinity, offered stateless pressure and 10-second warmup/60-second useful-output window. No product changes, multipath negotiation, activation selector or shared-host policy change.
- **Prediction:** The uninstrumented pair reproduces a lower granted goodput and higher server CPU/byte. Separate profiles show added local completion/feedback CPU per useful byte if that mechanism is material. Endpoint or encryption attribution would select a different candidate.
- **Falsification:** Current timing does not reproduce the regression, or attributed local completion work is too small to explain a useful improvement. Profiles alone do not establish removable cost or end-to-end benefit.
- **Decision rules:** Retain fixture if controller/profile and workload receipts validate. Select the owner with demonstrated excess cost and a semantics-preserving mechanism. If variability or contamination prevents comparison, mark timing inconclusive and use only valid correctness/attribution evidence; any rerun needs a specific reason.
- **Invariants:** Same useful-delivery boundaries and pressure, explicit controller receipts, public Reno-only multipath, original default Reno fixture, exact source/binary identity, child cleanup, native grant join, no losses or incorrect completion.
- **Scope:** One uninstrumented pair, followed by one CPU-profiled pair if the first completes correctly: at most four counted observations, each under the existing 135-second invocation timeout. This is a finite discriminating experiment within the existing program allowance, not a new budget. Stop on fixture failure or an invalid comparison requiring diagnosis. Mixed-bulk and product qualification remain separate.

### Reproduction and validity

- **Control/candidate:** Runtime control `62247738352d9f645935518fa9259fe4e2f48dc8`; exact diagnostic fixture commit, build and binary hash recorded before launch. Both profiles use one binary. There is no runtime candidate yet.
- **Workload/commands:** Maintained `interop/multipath/ordinary_cost.py` diagnostic stateless-pressure cell, controller BBR, Go test binary built with `-tags ordinarycost`; exact arguments retained with run artifacts. CPU profiles are separate invocations and excluded from timing qualification.
- **Metric boundaries:** Receiver ordinary goodput and all useful bytes in 60 seconds, server window user/system CPU and CPU/useful byte; report client CPU separately. Echo/send-call latency, progress, loss, memory, write/close results and stateless responses remain visible. CPU sampled totals are attribution, normalized per useful output; no sum of overlapping cumulative stacks.
- **Environment/run design:** Minimax, existing server/client CPU sets and sibling contamination check. Control then granted isolates the endpoint grant; a separate profiled pair tests attribution, not repeatability. Further ordering/repetition depends on observed uncertainty. Preserve source identity, environment and all failed attempts.
- **Shared-state changes:** None; task-specific source/binary/output staging only. No runner pause, affinity changes to other workloads, system tuning or container/VM mutation.
- **Artifacts/accounting:** `docs/audits/2026-11-14-bbr-ordinary-cost-1368/`; existing program starts 217 instances / 8,860.629 host-seconds. Retain pre-launch charge and final actual duration for every attempt.

### Observations and disposition

Pending execution. Overall targets unverified; next decision is which owner to change.

### E01 interim observation — current timing baseline

Runtime control plus diagnostic fixture `a613896a04319fbe7826034755778766da3e9f31`; source/build manifest [here](2026-11-14-bbr-ordinary-cost-1368/e01-source.json). Both role processes passed in both profiles, no loss/write errors/empty seconds or contamination. [Raw summary](2026-11-14-bbr-ordinary-cost-1368/e01-timing/summary.json) records goodput 8.794 → 7.595 Gbit/s (0.863685), server CPU 82.776880 → 94.990097 seconds, CPU/useful-byte ratio 1.328660. Foreign CPU was 0.091379 and 1.4010957599999756 seconds. Both performance targets are missed in this diagnostic; other reported checks pass. This reproduces the historical direction without asserting three-round qualification. Two observations charge 154.090013534 host-seconds; cumulative program 219/420 and 9014.719013534/28800 seconds before the separately profiled pair. CPU profiling follows under E01; no runtime candidate is selected yet.

### E01 attribution and disposition — 2026-11-14

Both profiled observations completed correctly, but both exceed the existing contamination metric (16.686621490 and 20.137631113 foreign CPU-seconds). Preserve them as attribution-only evidence; exclude their timing from performance conclusions. The quiet gate reported no named process at admission; no cause for the excess metric is established. The profiled pair charged 154.063445188 seconds, bringing cumulative program usage to 221 instances / 9168.782458722 seconds. Raw [profiles summary](2026-11-14-bbr-ordinary-cost-1368/e01-profiles/summary.json) and [granted cumulative attribution](2026-11-14-bbr-ordinary-cost-1368/e01-granted-cum.txt) are retained.

Granted server samples total 110.13 CPU-seconds across the whole role process. `CompleteLocalPacket` accounts for 5.13 cumulative seconds; the encompassing native result-consumption work accounts for 7.49. Connection execution accounts for 60.89; endpoint writing 37.82, including packet protection and socket calls. These overlapping cumulative values must not be added. Completion feedback is a real local cost but cannot by itself explain or remove the entire CPU/byte gap. The clean uninstrumented pair establishes the regression. Disposition: retain the diagnostic fixture and baseline; attribution is qualified by contaminated execution and whole-process versus measurement-window boundaries. No end-to-end gain is claimed. Next: a small BBR-only empty-loss-feedback experiment, in parallel with source examination of endpoint transaction overhead.

## E02 — Avoid rich feedback preparation when local completion cannot expose loss

### Plan — 2026-11-14

- **Question:** Can the local completion owner avoid repeated empty feedback setup and pending-byte locking while preserving BBR recovery, diagnostics and actual loss/ECN events?
- **Observation:** E01's attributed completion path includes feedback setup/finish for every accepted packet even when the physical packet-history prefix exceeds the largest ACK. The scan itself already returns immediately. This local path is about 4.7% of whole-role sampled CPU, so it is not a complete explanation or sufficient remedy for the overall gap.
- **Hypothesis:** The empty feedback wrapper adds removable connection-context cost. A BBR-only branch at the existing no-loss proof can remove scratch preparation, sorting and pending-byte lookup without skipping meaningful feedback.
- **Alternatives:** The wrapper is too cheap for a detectable end-to-end gain; extra dispatch in the candidate cancels the saving; native transaction/registration work remains the main limiter.
- **Intervention:** After unchanged local congestion/ECN completion and fresh live-packet check, retain ordered history qualification. Only with a rich BBR dispatcher and the existing physical-prefix no-scan predicate, clear lossTime and preserve empty delivery diagnostics and recovery-episode bookkeeping through a private helper. Otherwise run the original feedback/scan path. Preserve timer update and deferred undo settlement. No batching, new persistent state, native ownership change or Reno-path change.
- **Prediction:** Reduce completion work and server CPU/useful byte modestly (roughly 1–3%, a hypothesis not a new acceptance limit); overall targets may remain missed. Clean same-workload candidate timing must support any end-to-end claim. No controller callback may disappear if it carries ACK, ECN, loss or changed flight.
- **Falsification:** A behavioral difference in timer, delivery diagnostics, recovery episode, delayed ECN, early ACK, lost packet or spurious receipt; or valid timing shows no useful effect and the added implementation cost is unjustified.
- **Decision rules:** Retain a proven useful reduction with acceptable code cost, revise a named implementation defect, reject unsupported complexity, or mark timing inconclusive if environmental validity/variability prevents a conclusion. Do not move the overall 0.95/1.10 targets.
- **Invariants/checks:** Existing local/BBR tests plus focused original-path equivalence for stale lossTime, a prior valid diagnostic sample, a lower pending packet beneath an ACK, delayed ECN and loss/spurious recovery. Confirm ordinary Reno still executes the original branch. No new concurrency or lifetime mechanism.
- **Scope/reproduction:** Runtime control a613896a04319fbe7826034755778766da3e9f31; candidate commit/build hash recorded before native execution. Native stateless-pressure diagnostic under E01 workload and clean timing rules, one two-observation pair first; choose any further measurement only from observed uncertainty. Local focused tests may compare the same owner directly. No mixed-bulk or qualification claim from this experiment alone.
- **Termination/accounting:** Stop after focused correctness and one diagnostic pair, or first unexplained correctness/fixture failure. Remaining existing program allowance before E02: 199 instances / 19631.217541278 seconds. Shared-host changes none. Raw evidence under the existing issue artifact directory. Timing is unprofiled; no cumulative profile percentages are treated as speedup predictions.

### Observations and disposition

Pending candidate implementation.

## E03 — BBR protection placement ablation

### Plan — 2026-11-14, prepared while E02 measures

- **Question:** Does moving encryption to the native writer help ordinary BBR enough to justify its protection-plan construction and native-writer occupancy?
- **Observation:** E01 profiles attribute 10.26 cumulative seconds to writer protection and 2.27 to protection construction reservation; these are contaminated whole-process observations, not additive removable-cost estimates. Historical Reno protection placement improved throughput, but BBR has one handoff per pacing opportunity and two-quanta credit rather than Reno's larger grouped work.
- **Hypothesis:** Ordinary BBR's smaller request geometry makes deferred protection overhead or native-writer occupancy more costly than the overlap it enables. The existing synchronous protection path may reduce CPU per useful byte or pipeline delay.
- **Alternatives:** Deferred encryption is essential because the connection goroutine is already the limiter; removing overlap lowers throughput despite cheaper metadata. Endpoint transaction frequency rather than protection placement may dominate.
- **Intervention:** One experimental guard in `nativeProtectionConstruction.begin` declines deferred protection when `e.bbr != nil`. The existing prepared packer then encrypts synchronously. Keep local registration/completion, endpoint grant/deadlines/fairness, BBR pacing quantum/credit and handoff count unchanged. Use E02 as the control; this isolates placement/plan removal as a combined mechanism. No cross-turn Building lifetime is introduced: that alternative would also need deadline coverage and flush-before-credit-wait semantics and is not the smallest current discriminator.
- **Prediction:** If plan overhead/native-writer occupancy dominates, granted CPU/byte falls and throughput is preserved or improves. If connection critical-path placement dominates, throughput worsens. No invented numeric acceptance limit; only a clean corresponding end-to-end observation supports a gain.
- **Falsification/disposition:** Reject if throughput worsens or CPU benefit is unsupported relative to loss of overlap. Retain only if useful under the unchanged contract, then add BBR-specific placement/crypto lifecycle coverage for the final behavior. If placement remains ambiguous, a later plan-retaining synchronous ablation could distinguish bookkeeping from placement, but is not pre-authorized as a needless rerun.
- **Invariants/checks:** Existing native protection/crypto/prepared emission and BBR GSO tests; native pair's real BBR setup/transfer/close. Initial prototype uses the existing synchronous path and is not final qualification. Reno and negotiated multipath placement are unchanged, as the original deferred route already excludes multipath.
- **Reproduction/scope:** E02 `eab1ff6179644fba867bd14c71ba3bd96eee5c91` plus the single guard; exact candidate/patch and binary hash retained. One unprofiled stateless-pressure pair after E02, original affinity/warmup/window/seed and contamination accounting. No simultaneous host measurement. Stop after the pair or a correctness/fixture failure; charge the existing program ledger. No shared-host changes.

### Observations and disposition

Pending ablation.

### E02 observations and provisional retain decision — 2026-11-14

Candidate `eab1ff6179644fba867bd14c71ba3bd96eee5c91` passed the complete ACK-handler suite, focused local BBR/ECN race tests, vet and module tidiness. Equivalence tests preserve diagnostic sample invalidation, stale loss alarm clearing, actual loss below an ACK, spurious recovery, delayed CE and early-ACK terminal return. [Source/build record](2026-11-14-bbr-ordinary-cost-1368/e02-source.json); [raw timing summary](2026-11-14-bbr-ordinary-cost-1368/e02-timing/summary.json).

The clean native pair measured unregistered/granted goodput 8.720423390 / 7.761433737 Gbit/s, server CPU 82.030382 / 95.279944 seconds, ratios 0.890029462 goodput and 1.305035652 CPU/useful byte. Foreign CPU 0.134248 / 0.115463 seconds. No losses, write errors, empty seconds or contamination. Relative to E01 the granted throughput rose 2.19% and CPU/useful byte fell about 1.84%; the control throughput fell 0.84%, so ratio movement overstates the candidate's absolute gain. One pair does not establish repeatability. Retain provisionally as a small local improvement, subject to the combined candidate's final qualification; both overall targets remain missed. The source mechanism supports removal of empty work; the measured local result is consistent with the modest prediction, not a complete remedy.

Two observations charge 154.103248318 seconds. Cumulative program usage is 223/420 instances and 9322.885707040/28800 seconds; remaining 197 instances / 19477.114292960 seconds before E03. Next decision: E03 protection-placement ablation on this candidate, with original batching/credit and no shared-host changes.

### E03 observations and reject decision — 2026-11-14

The one-guard candidate `7dffd409ec5a2878f8b0ade8f2665bd63bda90fc` passed focused native-protection/prepared-packet/BBR-GSO tests. The [clean timing pair](2026-11-14-bbr-ordinary-cost-1368/e03-timing/summary.json) measured control/granted goodput 8.853279010 / 6.916882345 Gbit/s and CPU 83.152392 / 89.215095 seconds; ratios 0.781279155 and 1.373274507. Foreign CPU was 0.070025 / 0.238745 seconds; no correctness/latency/write/loss/progress failures. [Exact source/build](2026-11-14-bbr-ordinary-cost-1368/e03-source.json).

Reject synchronous protection for ordinary BBR. Relative to E02, granted total CPU fell 6.37% but throughput fell 10.88%; useful-byte CPU worsened. Control throughput rose 1.52%, so ratios also reflect comparator drift, but the granted absolute regression is clear. Moving work back to the connection loses valuable overlap; this is not an optimization despite the lower total CPU. Restore the original deferred-protection guard byte-for-byte. No further plan-retaining synchronous ablation is justified by this result. Both overall targets remain missed. Next: distinguish local-credit waiting and timing-sample exclusions with bounded scalar observation before a larger grouping change.

E03 charges two observations / 154.073332245 seconds. Cumulative program usage 225/420 instances and 9476.959039284/28800 seconds; remaining 195 instances / 19323.040960716 seconds. No shared environment changes require restoration.
