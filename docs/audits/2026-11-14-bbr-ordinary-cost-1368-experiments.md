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
