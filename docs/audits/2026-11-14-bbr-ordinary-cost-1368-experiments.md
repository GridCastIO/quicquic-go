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
