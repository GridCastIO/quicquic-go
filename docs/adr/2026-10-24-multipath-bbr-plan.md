# BBR and aggregation implementation plan

**Identity:** `QGF-MP646-20261024-B`. **Updated:** 2026-11-15. **Status:** accepted scoped continuation; B1–B7 complete, B8 closed without code; B9–B11 complete; B12 not implemented. **Parent:** [B track (#1014)](https://github.com/the-sarge/quic-go-fast/issues/1014). **Follow-up:** [aggregation reconsideration (#1374)](https://github.com/the-sarge/quic-go-fast/issues/1374). **Program:** [index](2026-10-24-multipath-program.md), [tracker (#646)](https://github.com/the-sarge/quic-go-fast/issues/646). Continuation children are [B9 (#1382)](https://github.com/the-sarge/quic-go-fast/issues/1382), [B10 (#1383)](https://github.com/the-sarge/quic-go-fast/issues/1383), [B11 (#1384)](https://github.com/the-sarge/quic-go-fast/issues/1384) and [B12 (#1385)](https://github.com/the-sarge/quic-go-fast/issues/1385). **Normative scope:** current outcomes, boundaries, invariants, acceptance evidence, blockers and stops. **Audit history:** [scoped handoff](../audits/2026-11-15-bbr-1374-handoff.md); [completed B1–B8 contracts](https://github.com/the-sarge/quic-go-fast/blob/b4e3a4474f51a7b1fa60a0febbc79b04da4c4e72/docs/adr/2026-10-24-multipath-bbr-plan.md).

## Goal and current shape

Enable experimental BBR primary/backup under the owner's exact-result decision, then evaluate paced byte-round-robin as the one replacement aggregation candidate. Publish aggregation only if the new candidate meets the unchanged comparative thresholds. A valid negative comparison completes the experiment and leaves aggregation unsupported. Reno stays the default, full BBRv3 qualification [Q2 (#599)](https://github.com/the-sarge/quic-go-fast/issues/599) remains deferred and is not a prerequisite, and no application adoption recommendation follows.

Verified at `b4e3a4474f51a7b1fa60a0febbc79b04da4c4e72`: `multipath_api.go:60` accepts only primary/backup, `:111` owns constructor admission, and `:118` refuses BBR. `multipath_credit.go:17` makes the registry connection-goroutine-owned; `:48` holds its scheduler and `:79` initializes activation. `multipath_admission.go:228` supplies ordered eligible views and removes fencing paths before scheduling. `multipath_scheduler.go:26` owns selection and ledger rebasing, `:61` charges actual handoff bytes, `:80` contains the existing arrival/round-robin choice and `:140` orders paced byte round-robin. `packet_emission_path.go:180` obtains readiness from the BBR opportunity planner, credit and native construction capacity; selection precedes destructive packing at `:95`. `multipath_support_test.go:110` exercises constructor admission in both configuration orders. `multipath_picoquic_matrix_test.go:59` creates sessions through the public config and transport APIs.

The [completed cost work (#1368)](https://github.com/the-sarge/quic-go-fast/issues/1368), merged in [PR #1377](https://github.com/the-sarge/quic-go-fast/pull/1377), preserves six passing BBR interoperability cases and twelve clean ordinary observations. Its [native receipt](../audits/2026-11-14-bbr-ordinary-cost-1368/final-qualification/README.md) records mixed-bulk goodput/CPU ratios **0.944295141271208 / 1.2081314772756437** and stateless-pressure **0.9590708299335772 / 1.1593702973325581**. The original 0.95 / 1.10 limits and raw failures stay intact. The [candidate applicability assessment](../audits/2026-11-14-bbr-ordinary-cost-1368/candidate-applicability.md) carries E6/R21 native and Reno evidence with concrete source limits; its contemporaneous pending-review statements are superseded by the delivery receipt on the closed issue, not silently rewritten.

B5's [valid negative comparison](../audits/2026-11-14-multipath-b5-receipt.md) is evidence for changing the candidate, not qualifying the replacement: arrival estimation achieved 83.1 Mbit/s balanced and 48.5 unequal; the fixture's forced round-robin achieved 93.8 and 70.5, against independent connections at 94.5 and 70.8. These are historical medians, not a newly computed paired pass. Frozen source, drivers and raw results remain unchanged.

## Decision

The owner explicitly chose on 2026-11-15 to plan experimental public BBR primary/backup using the completed cost evidence and its exact accepted exceptions, subject to source applicability and exact-head validation. This authorizes B9's narrow capability change. It does not declare the raw cost tests passed, transfer an exception to a changed measured workload, qualify full Q2, or authorize implementation in this handoff.

Replace the private arrival estimator with the existing paced byte-round-robin choice. A pending PTO retains precedence; no authorized primary holds ordinary work; eligible active paths exclude backups while any active path remains eligible, even if that active path is temporarily congested. Among ready candidates, sendable-now paths precede paced ones; among future-paced candidates the earliest send time wins; remaining ties prefer fewer scheduled bytes, then the lower wire ID. Continue rebasing against the least-served ready candidate and charging actual handoff bytes. This is opportunity/byte balancing, not equal packet counts, equal rates, or a bounded application-delay promise. Returning paths acquire no service debt. BBR still owns its sampler, pacing and congestion state, but scheduler ranking no longer reads delivery rate, queued bytes or RTT.

**Owner's design:** modify the connection-owned scheduler itself and remove its obsolete ranking inputs. No parallel estimator, callback, cached policy mirror, timer or worker is needed. Emission retains the existing shared readiness/reservation planner, construction, registration and output ownership. The experiment selects the private scheduler once during config-to-registry activation, not by asynchronous runtime mutation.

**Do not do this:** rerun the old arrival policy until it passes; its valid failure is settled. **Revisit if:** a separate owner-approved design gives a new causal reason, outside this continuation. **Do not do this:** retain arrival estimation as a second production option; it adds two ranking contracts without a current outcome. **Revisit if:** separately accepted evidence motivates a new policy. **Do not do this:** add coupled congestion control, application-symbol steering, Reno aggregation, a Reno estimator, public scheduler callbacks, duplication/FEC, new platforms or path counts, custom I/O, multipath QUIC v2, jumbo, or changes to native ownership, BBR controller algorithms or same-path sampling. **Revisit if:** the owner explicitly opens a separate program. **Do not do this:** optimize the already accepted ordinary-cost residuals or relax thresholds here. **Revisit if:** a separate cost decision is made. Split/merge alternatives below have `none: rejected on merit` unless their stated context or safety stop occurs.

## Binding contract and operating discipline

The shared review-loop and contract-closure baselines supplied by `$implement-architecture-slice` govern, composed with [the repository execution overlay](../REVIEW-LOOP.md); there is no repository closure overlay. Apply the shared design-cost reference to scoped replacements. One initial full-panel RAS review and at most one replacement; independent finding dispositions, precise-root comparison and approach stops apply to review and verification. Required preparation, focused tests, exact pushed-head local certification, applicable same-head hosted checks, squash merge, then append-dev-journal and pointer reconciliation remain required. Diagnose failures before reruns. Documentation uses the overlay's docs path, not invented ci-* or task-preflight gates.

Preserve ADRs [0001](0001-upstream-compatibility.md), [0003](0003-follow-stable-upstream-releases.md) and [0004](0004-packet-emission-ownership.md), Reno defaults and ordinary behavior, exact endpoint grants, local-timeout backpressure, native borrow lifetime, shared recovery bounds, same-path feedback eligibility, migration/ECN fences, and periodic per-carrier ACK-turn PINGs. The public profile remains experimental opt-in draft-21 QUIC v1 on Linux amd64, one or two paths, exact granted native UDP sockets. Unsupported configurations refuse before advertisement/attachment; absent negotiation stays ordinary. Existing protocol parsers, AEAD, public configuration validation and typed internal events own representations; there is no new parser, wire schema or persisted state.

The owner-approved historical regression suites and required independent peer job remain maintained verification aids under their existing transport-suite ownership and equivalent-replacement/feature-removal retirement. New focused cases extend those suites. The finite aggregation apparatus is reintroduced solely as the already accepted one-decision verification deliverable: payoff is a reproducible support decision; domain is the fixed B11 inventory; owner is the transport integration suite; B12 retires executable comparison/activation machinery after preserving raw evidence and the receipt. No perpetual analyzer or tuning infrastructure becomes a blocking deliverable. Runtime is shipped behavior; admission, eligibility, capacity and lifetime guards are required safety enforcement; tests/fixtures are verification aids; plans/receipts/ledger/tracking are process metadata.

## BBR and scheduling contract

Per-path BBR controller, sampler, pacing, loss and ECN state remain separate; shared logical delivery counts once. Same-path eligible ACKs alone train timing/rate, excluded cross-carrier feedback cannot bridge into later valid samples, migration preserves wire sequence and cumulative ECN with its existing fence. Cross-path ACKs still settle recovery/delivery. The existing B1–B3 feedback tests own these obligations. B7's same-path preference, release, alternation, history-room and bare-PING rules remain unchanged. No cross-path-only feedback throughput claim is made.

The new schedule changes ranking only. The registry remains the sole mutable policy/ledger owner on the connection goroutine; emission owns selected-route packing and bounded native handoff. Local credit, congestion, pacing, MTU and native construction readiness remain the existing plan/execute contract. No reselection inside an opportunity, additional wakeup or concurrency is admitted. Scheduled bytes survive same-ID route refresh with their member, rebase as today and disappear when the member does. Fresh connections reconstruct state from config; no disk restart round trip exists.

## Qualification and adoption policy

Original ordinary limits remain goodput ≥ 0.95, CPU/useful byte ≤ 1.10, p99 control/send-completion latency ≤ max(1.10 times baseline, baseline + 1 ms), bounded memory/fair progress and no timeout-only closes. B9 may carry only the exact accepted cost results named above after establishing measured-source applicability. A changed cost behavior needs the affected existing cell; a new failure needs a new owner decision rather than inheritance of the old exception.

For the replacement aggregation candidate, retain balanced useful-goodput ≥ 1.20 of the better measured single path and ≥ 0.95 of two matched independent connections; retain shared-bottleneck ordinary Reno competitor goodput ≥ 0.90 of its goodput beside the independent pair. Use median round-paired ratios, not ratios of unrelated medians. Report unequal-path STREAM completion and DATAGRAM delivery/latency separately without inventing a threshold. This is uncoupled multipath, not fairness equivalent to one congestion-controlled flow. Passing the three gates permits only B12's experimental aggregate support; no application adoption recommendation or universal network-performance guarantee follows.

<a id="candidate-and-run-ledger"></a>

## Program budget and prior-evidence validity

Use the existing [Reno ledger](2026-10-24-multipath-reno-plan.md#candidate-and-run-ledger) and live [program tracker (#646)](https://github.com/the-sarge/quic-go-fast/issues/646), not a new budget. At handoff, recorded consumption is **299/420 instances and 12815.07078762835985/28800 host-seconds**, leaving **121 instances and 15984.92921237164015 seconds**. Reconcile live usage before each invocation; charge setup, failures, contamination replacements and hosted peer work once, without double-counting inner durations. No campaign runs during handoff.

Planned regular inventory: B9 six BBR primary/backup peer cases; B11 36 comparison observations; up to four existing product-head hosted Reno matrices of 16 cases each; B12, on a positive result only, six BBR aggregate peer cases. That is **112 regular instances**, leaving 9 for affected existing cells or allowed contaminated replacements, within the same global ceiling. B11 is expected to be evidence/fixture-only after B10; its hosted matrix applies if its changed paths trigger the existing workflow, and cannot be waived merely to save capacity. Separate negotiated-zero evidence is reported but not an independent peer instance. There is no additional cumulative cap and no automatic entitlement to consume all reserve.

Retain B5's 10-second warmup, 60-second observation, three paired rounds and 120-second bounded observation invocation (the executed B5 campaign bound, not the helper default); retain independent peer setup 1200 seconds, role context 30 seconds, Go timeout 90 seconds, runner 120 seconds and outer container 150 seconds. Preflight pins exact sources, binary/driver/container/kernel/toolchain, seeds, CPU placement including SMT siblings, timeout and maximum reserved cost against the then-remaining instances and host time. Setup and occupied fixture time are charged as in the existing ledger; pre-admission quiet waiting that holds no fixture is recorded but not charged. A busy host alone is not contamination: inspect actual fixture cores/siblings and interference; distinguish efficiency-core background work from performance-core contention where the venue has that topology. Do not change host workload policy. At most three replacements per campaign and one per contaminated observation are allowed only after the existing quiet gate passes and while reserve remains; clean failure is never a rerun trigger. Diagnose failures and stop before an invocation that cannot fit. Do not claim the total worst-case envelope is pre-reserved merely because regular counts fit.

Carry E6/R21/Reno and BBR ordinary receipts only with a candidate-specific source-applicability record and their original limitations. B9's capability-only change should not change measured runtime; B10 changes aggregate ranking only, so ordinary and primary/backup receipts can carry if source inspection establishes that separation. Any affected existing cost/native cell uses reserve with a concrete causal justification. The exact-result exception is not a tolerance for future measurements. Exceeding scope, inventory or remaining capacity requires an owner decision.

## Slice graph

| Slice | State | End-to-end outcome | Blocked by | Temporary seam removal |
| --- | --- | --- | --- | --- |
| B9 | complete (#1382) | Public experimental BBR primary/backup and exact evidence/support statement | None; cost follow-up #1368 complete and owner decision recorded | None introduced |
| B10 | complete (#1383) | One private paced byte-round-robin aggregate policy through real connections | B9 | B12 removes private activation |
| B11 | complete (#1384) | Fixed comparison with valid positive or negative decision receipt | B10 | B12 retires experiment apparatus |
| B12 | frontier (#1385) | Publish the measured aggregate outcome and remove experiment activation | B11 | Removes both seams |

Existing [follow-up #1374](https://github.com/the-sarge/quic-go-fast/issues/1374) becomes the pointer-based continuation group under the existing B track; it is not dispatched as one PR. Each new slice receives one child issue after docs merge. B9→B10 is necessary because B10's narrow private selector relies on B9's real public BBR capability, avoiding another bypass of controller admission. B10→B11 freezes the exact runtime candidate before comparison. B11→B12 prevents capability support before evidence. No parallel implementation frontier exists inside this continuation; unrelated E/R/N contracts remain closed.

## Implementation slices

<a id="b9"></a>

### B9 — Enable experimental BBR primary/backup

**Completion:** implemented by [B9 (#1382)](https://github.com/the-sarge/quic-go-fast/issues/1382); [support and applicability receipt](../audits/2026-11-15-bbr-b9-support.md). B10 (#1383) is complete; B11 (#1384) is complete; B12 (#1385) is the current frontier.

**Delivers and acceptance:** public Dial/DialEarly, Listen/ListenEarly and GetConfigForClient configurations admit BBR primary/backup in the existing supported profile, in either configuration order, with Reno still default and aggregate still refused. Public two-path useful transfer and lifecycle preserve B1–B3 semantics. Publish the exact exceptions, applicability, tested profile and unqualified underlying BBR/Q2 status; do not recast raw failures. Complete all six existing BBR primary/backup independent cases on the final candidate through public admission without a product overlay: useful-transfer, abandon-reopen-late-feedback and same-id-migration-rebinding, each client/server. Preserve the existing hosted Reno inventory.

**Existing work:** retain merged B1–B7 and #1368 runtime and frozen receipts; no unmerged implementation branch is accepted. Reintroduce only the BBR controller parameter in the existing peer fixture/driver as needed, preserving default Reno and its strict case/identity accounting. Historical measurement overlays are evidence, not production dependencies.

**Owner/authority:** `Transport.admitMultipath` owns support admission; config clone/controller order and each constructor/server-selected path must reach it. Connection registry and per-path recovery retain all lifecycle mutation. Cover config construction, both orderings, cloning, ordinary fallback, rejected profiles, fresh connection, close and endpoint join. No persisted fact or second policy owner is introduced.

**Seams and scope:** none new. Files are `multipath_api.go`, existing support/API tests, `multipath_picoquic_matrix_test.go`, `interop/multipath/run.py` and their accounting tests/README, current support docs/receipt and committed completion/frontier surfaces. No controller, native-owner or scheduler algorithm change. Public capability is intentional; ordinary/default Reno behavior and other refusal conditions are preserved. Untraced effects outside these surfaces stop the slice.

**Representation/artifacts/closure:** universal admission rule over typed Config and the stated profile, enforced by the common gate; finite example-level interoperability. Shipped gate behavior, safety refusal checks, maintained test/peer aids and support metadata are classified as above. Closure is triggered by public authority granted through multiple constructors; use the admission rows below. No new authoritative disk state exists.

**TDD/evidence:** first replace BBR refusal expectations with positive constructor/clone/order tests, add public BBR two-path transfer with close/join, preserve negative profile tests and ordinary negotiation fallback, and pin the support receipt to raw failed metrics plus exact owner acceptance. These detect admission and lifecycle regressions, not network throughput. At most the inherited 16 deterministic scenario tests; existing BBR lifecycle and sampling suites remain preservation evidence. One focused race run covers public construction/close and native completion interaction. Six fixed native peer cases plus the required hosted Reno matrix; carry ordinary/native costs only through the applicability assessment. Stop for a changed cost contract, missing evidence, required new semantic cell or unexplained source difference.

**Dispatch context:** this slice, common decisions/discipline, admission matrix, budgets, the #1368 final receipt/applicability and final review receipt, plus focused gate/config/fixture source; target ≤24k input tokens, no whole historical plans. The capability change and parameterized existing fixture fit one context. Splitting evidence from gate would leave the new public claim uncertified; merging scheduler work would obscure unchanged-cost applicability. Both alternatives rejected on merit. No blocker remains beyond merged #1368 and the recorded owner decision.

<a id="b10"></a>

### B10 — Replace private aggregation with paced byte-round-robin

**Completion:** implemented by [B10 (#1383)](https://github.com/the-sarge/quic-go-fast/issues/1383); [scheduler and applicability receipt](../audits/2026-11-15-bbr-b10-scheduler.md). B11 (#1384) is complete; B12 (#1385) is the sole frontier.

**Delivers and acceptance:** replace arrival ranking with the fixed round-robin policy in Decision, through the registry, real emission and a two-connection STREAM/DATAGRAM test; public aggregate selection remains rejected. BBR primary/backup and Reno are unchanged. Remove arrival-only view fields/reads and estimator ranking code, keeping BBR model sampling intact. Preserve eligibility, backup exclusion, PTO priority, stable ties, byte rebasing, per-message steering, readiness/reservation agreement and non-destructive selection.

**Existing work:** rework the merged B4 scheduler; retain B7 and the real-packer fixture. Replace arrival-specific test expectations; preserve scheduler-independent tests. Retired forced-round-robin code is a comparison reference, not a second production baseline. Blocked by B9, which supplies public BBR primary/backup capability.

**Owner/authority/seams:** scheduler choice/ledger stay on the connection-owned registry, emission retains construction/handoff and recovery owns sampling. One unexported experiment selector on the copied multipath config may choose aggregate at activation, before first selection, only for in-package tests. Its zero value is primary/backup. It may not bypass platform/controller/grant admission or be changed on a running connection. B12 removes it. Cover copies, activation, same-ID migration, retirement/reopen, fresh-instance zero state and close; no disk persistence. This narrow temporary selector has no second lifecycle and does not widen native authority.

**Blast radius:** `multipath_scheduler.go`, aggregate-only `pathView` fields/reads in `packet_emission_path.go`, `multipath_scheduler.go` and their tests; `multipath_api.go`/`multipath_credit.go` only for selector copying/activation; aggregate/self-connection tests and support-test assertion of no public reachability. Registry membership/policy, planner, BBR sampling, native owner, wire/API and timers remain unchanged. Ranking may change useful throughput/reordering, which B11 measures; arbitrary Internet delay/fairness remains untraced and excluded. A change to those preserved owners or a need for new concurrency stops the slice.

**Representation/artifacts/closure:** immutable typed ordered path views for ≤2 live paths, representation owned by registry validation; universal eligibility/ownership constraints within that domain, finite examples for scheduling outcomes. Runtime is shipped but privately reachable; guards are safety enforcement; tests are existing maintained aids; selector is a temporary verification seam. Apply scheduler rows of the matrix below. Readiness optimization alone does not trigger additional closure; the existing readiness/reservation contract is preserved.

**TDD/evidence:** first demonstrate that unequal valid rate/RTT samples cannot override the paced-byte ranking, then test pending PTO, no primary, active-vs-backup, pacing/ties, no ready candidate, byte charge/rebase and returning-path behavior. Exercise real packing before/after samples, DATAGRAM fit/steering, refusal without destructive extraction, migration/retirement and two real BBR connections carrying useful traffic on both active paths. Keep the existing local-credit limit/GSO/MTU and native construction-capacity regressions. At most 16 deterministic scenarios, one focused race run for real connection/close, required hosted Reno matrix; no performance campaign in B10. These catch selection and ownership, not comparative benefit. Carry unaffected cost/native evidence with source justification.

**Dispatch context/audit:** this slice, Decision, scheduling contract/matrix, B9 interface/support receipt, and focused registry/emission tests; ≤24k input tokens. Split an inert view-field cleanup only if needed for context: otherwise it delivers no independent behavior and the ranking plus input removal fit together. Do not merge B11's measurement driver/campaign: runtime must freeze first. The owner-level change removes ranking obligations instead of layering a parallel scheduler. B9's edge removes the need for a controller-admission bypass. Stop for new native/recovery rules, unbounded service promises, new policy options or a widened selector.

<a id="b11"></a>

### B11 — Measure the replacement aggregation candidate

**Completion:** measured by [B11 (#1384)](https://github.com/the-sarge/quic-go-fast/issues/1384); the [fixed comparison receipt](../audits/2026-11-15-bbr-b11/README.md) records a valid positive result under all three unchanged median-paired gates. B12 (#1385) is the sole next frontier and follows its positive publication branch.

**Delivers and acceptance:** freeze B10's runtime and produce one valid controller-matched comparison under the unchanged thresholds, with raw observations, source/binary/driver identities, independent arithmetic audit, live ledger charges and a clear positive/negative aggregate support result. A valid negative completes this slice and unblocks B12's unsupported publication. Missing/invalid evidence does not. No tuning or scheduler edits occur here.

**Existing work/owner:** reuse the frozen B5 workload/driver at `e048181a680f07dc7560f7df1667d8c065513583` by explicitly copying/adapting into a new maintained finite fixture, leaving frozen files and receipts untouched. Transport integration suite owns fixture/accounting, no protocol policy. Blocked by B10's frozen candidate and private activation. Retain its selector until B12; B12 also retires the comparison apparatus.

**Inventory:** four arms A (ordinary BBR path A), B (ordinary BBR path B), C (two independent BBR connections, one per path), E (the new BBR aggregate), across balanced disjoint, unequal delay/rate and shared-bottleneck topologies, three rounds each = **36 observations**. Keep B5's workload, topology parameters, seeds, socket/flow matching, ordinary Reno competitor, 10-second warmup, 60-second window, useful-byte semantics, diagnostics and contamination rules. Use round orders **ABCE, CEAB, EABC** for rounds 0, 1 and 2 in each topology, preserving the historical six-arm schedule after filtering D/F; do not simply apply its two-position rotation to a four-arm list. Keep each original topology/round seed. Only the mode inventory and candidate ranking change. Omit Reno informational arm D and former forced-round-robin arm F because E now is that candidate; neither supplied a qualification threshold. Do not substitute their historical numbers for fresh E or baselines. Three rounds are inherited paired-median evidence, not a new statistical confidence claim.

**Scope/representation/artifacts:** new comparison test/driver/accounting regressions under root tests and `interop/multipath`, receipt/raw output under `docs/audits`, ledger and completion/frontier metadata. Typed fixture modes, existing QUIC parsers and standard JSON decoding own representation; example-level guarantee for the fixed workload/pins/native Linux amd64 venue only. The finite fixture has the payoff/domain/owner/retirement stated above. Runtime closure is not recursively imposed on the apparatus; accounting validation is ordinary focused testing. No new product authority or persisted runtime fact. External load, arbitrary peers and untested topologies remain untraced/excluded.

**TDD/evidence:** driver regressions first for exact 36-case inventory and the three stated round orders, missing/duplicate/wrong identity, round-paired arithmetic/negative verdict, contamination replacement and stop/accounting. At most 16 deterministic tests, no new timing/platform cross-product or fuzz harness. Inspect copied workload and parser identity against the frozen source; verify useful-byte arithmetic independently on the retained logs. Finish once all fixed valid observations and audit are complete, or stop at unresolved failure/budget exhaustion; never repeat clean failures. Any altered ordinary or native execution surface needs a scoped applicability decision and affected existing cell within reserve. Existing hosted checks apply to fixture changes. No new algorithm is selected on failure.

**Dispatch context/audit:** this slice, qualification/budget rules, B10 interface and source applicability, and only the bounded frozen fixture files needed to adapt A/B/C/E; ≤24k input tokens. One fixture/campaign/receipt is coherent independently of public enablement. Further splitting driver from evidence adds a PR without a completed comparison; merging B10 lets measurement findings mutate the frozen candidate, while merging B12 risks support preceding evidence. Reject both on merit. A necessary fixture/API/owner change outside this inventory stops for scoped re-audit, not unbounded experimentation.

<a id="b12"></a>

### B12 — Publish aggregation outcome and retire experiment activation

**Delivers and acceptance:** consume B11's valid result. On pass, publicly accept `aggregate` only with BBR in the existing profile, select the one round-robin policy through config/clone/activation and publish exact support limits. On negative, keep aggregate rejected for every controller and publish unsupported with its measured reason. In both outcomes, preserve B9 primary/backup and Reno default, delete the experiment-only selector and comparison runner after freezing evidence, and leave no public or private runtime bypass. No silent alternate algorithm or threshold change is permitted.

**Existing work/owner/authority:** retain B9 and B10; consume the B11 receipt. The public configuration validator and common capability gate own valid policy/controller/profile combinations; registry activation owns its one immutable scheduler choice. Cover enabled/disabled config, failed-call nonmutation, cloning, both controller/policy orderings, all constructors including server-selected configs, absent negotiation and close. Policy validity must be checked at admission, so later controller changes cannot enable Reno aggregate. B12 removes B10's selector and B11's finite apparatus; retained raw evidence is metadata, not an executable dependency on an old overlay. No disk persistence.

**Blast radius/representation/artifacts:** config selection/admission in `multipath_api.go`, registry activation, support/API tests and documentation, peer-fixture policy parameter if the result passes, and finite fixture retirement. No scheduler, controller, native-owner or protocol change. Universal supported-combination rule over the typed public Config domain at the common gate, finite example-level peer/benefit claims. Runtime selection is shipped behavior; refusal is safety enforcement; support/peer tests are maintained aids; archived observations are metadata. Apply admission matrix. Untraced network-performance domains remain excluded.

**TDD/evidence:** write positive/negative support-result table tests, policy/controller order/clone/failed-config tests, public transfer and unsupported-combination regressions, and absence-of-private-selector test first. At most 16 deterministic scenarios and one focused lifecycle race. On a positive result run the same three BBR peer scenarios in both roles with the final public aggregate policy (six cases). The existing `prefer` helper backs up every other live path, so changing only the config is insufficient: extend useful-transfer with one bounded phase that marks both live paths active through `SetLocalUseV1`, snapshots traffic after activation and demonstrates new useful STREAM traffic sent on both paths while both remain active, before its existing 30-second role context expires. Retain DATAGRAM round-trip and lifecycle assertions. The other cases retain their deliberate per-path preference where needed. This is a fixed-example witness, not an arbitrary-flow fairness promise; no new scenario, peer pin or timeout is added. Do not claim historical primary/backup cases cover the changed scheduler. Preserve default hosted Reno matrix. On negative no extra BBR aggregate peer instances are required. Verify B11 source applicability against the final runtime; only selector promotion, cleanup and docs should differ. A source change affecting measured behavior requires the affected evidence, not historical pass inheritance.

**Dispatch context/audit/stops:** this slice, decision/qualification/budgets and admission matrix, B9 support and B11 result/applicability, focused API/activation/peer source; ≤24k input tokens. Publication and selector removal are one authority-complete change; splitting would leave private activation alive or a public claim without matching validation. Merging B11 would conflate measurement and enablement. Blocker B11 is necessary even on negative. Stop for insufficient evidence, new tolerance/algorithm or a changed measured runtime that cannot fit remaining evidence capacity. Completion updates this plan/program frontier in the product PR; no routine later status PR.

## Contract closure: admission and scheduling

Both material authority/ownership consequences and independent entrypoints/states trigger the rows below. Existing typed config validation, registry eligibility and recovery owners supply representation; no handwritten external-language scanner is introduced. The universal claims are confined to the stated profile and these owners; finite representative tests terminate, not exhaustive state enumeration. No new guard mutation is mandatory: inherited and new direct behavioral tests exercise the changed rules; at most one discriminating guard bypass per owner is permitted if the accepted inherited coverage cannot otherwise be shown to reach it.

| Slice / invariant | Semantic classes and disposition | Enforcement owner | Terminating evidence / coverage |
| --- | --- | --- | --- |
| B9/B12: only supported combinations gain admission | Dial/DialEarly, Listen/ListenEarly, server-selected Config; either setter order and clone | Common `admitMultipath`, after Config validation | Constructor table, clone/order tests; planned |
| B9/B12: unsupported profile never advertises/attaches | Unsupported platform, v2, missing/conflicting grant, invalid count; Reno aggregate remains rejected | Existing profile/config/grant gate | Existing negative cases, policy/controller negative test; planned preservation |
| B9/B12: disabled or unnegotiated stays ordinary | Disabled config, ordinary peer, default Reno | Existing configuration and negotiation owners | Existing ordinary fallback plus default tests; planned preservation |
| B10: choose only authorized eligible route before destructive packing | Live/validating/suspect/fenced/retired path, no primary, active vs backup, PTO precedence | Registry eligibility and scheduler, then emission | Existing eligibility/lifecycle tests plus fixed selector tests; planned |
| B10: a selection spends only its route's admitted work | Pacing, local credit limit/GSO/isolated MTU, native capacity, DATAGRAM fit | Existing opportunity planner/credit and emission | Existing real-packer readiness/refusal/steering regressions; planned preservation |
| B10: one bounded service ledger | Zero initialization, actual byte charge, rebasing, disappearance/return, same-ID migration and close | Registry member lifetime and `noteScheduled` | Ledger table plus real two-path transfer; planned |
| B10–B12: private evidence cannot grant public support | Zero/clone activation, public aggregate refusal, final selector removal | Config gate and registry activation | Public refusal before B12, absence test after; planned |
| All: unchanged BBR feedback/native lifetime | ACK carrier, migration/ECN, local completion, shutdown | Existing sampler/recovery/native owners | Existing suites and applicability receipts; unchanged, inspect affected source |

No in-contract cell is silently uncovered: planned cells belong to their slice, preservation cells retain named tests, and arbitrary networks/platforms, full Q2, jumbo and coupled congestion control are explicit non-goals. A new material effect outside these owners stops for decision/re-audit.

## Acceptance and validation

Each product PR owns its own completion and newly ready successor state in this plan and the program index before review. Local gates are affected-package tests, `go vet` for changed packages, `go mod tidy -diff` for Go/dependency changes, the named focused race where warranted and the repository ordinary suite; focused root/internal ackhandler tests preserve path/controller behavior. Fixture changes run `python3 -m unittest discover -s interop/multipath -p 'test_*.py'`. Native-only tests must actually execute on Linux amd64, not count skips on the development host. The required peer workflow retains exact-head native hosted execution and its current inventory. No generic new stress gate is added. Apply current repository CI and exact-head rules when the base advances.

Completion is finite: named deterministic and operational evidence, accepted source applicability, full bounded review, exact-head certification/checks, merge, journal and synchronized pointers. Missing/invalid evidence remains blocking; a valid negative B11 comparison is success for evidence delivery and selects B12's negative branch. This handoff dispatches no implementation.

## Completed slices and preserved references

The following anchors preserve navigation to completed work, not new obligations or dispatchable contracts. Read the linked immutable historical plan only for a bounded referenced invariant; do not load its whole execution chronology. Existing child plan pins and frozen evidence remain untouched.

<a id="b1"></a>
### B1 — Partition BBR delivery sampling and send credit

Complete in [PR #1327](https://github.com/the-sarge/quic-go-fast/pull/1327), [child #1040](https://github.com/the-sarge/quic-go-fast/issues/1040). Preserve path-local sampling and shared logical accounting.

<a id="b2"></a>
### B2 — Preserve BBR ECN, recovery and migration evidence

Complete in [PR #1331](https://github.com/the-sarge/quic-go-fast/pull/1331), [child #1041](https://github.com/the-sarge/quic-go-fast/issues/1041). Preserve generation/ECN fences and bounded recovery.

<a id="b3"></a>
### B3 — Exercise BBR primary/backup through complete lifecycle

Complete in [PR #1343](https://github.com/the-sarge/quic-go-fast/pull/1343), [child #1042](https://github.com/the-sarge/quic-go-fast/issues/1042). Preserve lifecycle and [applicability](../audits/2026-11-13-multipath-b3-applicability.md).

<a id="b4"></a>
### B4 — Add the private aggregate scheduling policy

Complete in [PR #1347](https://github.com/the-sarge/quic-go-fast/pull/1347), [child #1043](https://github.com/the-sarge/quic-go-fast/issues/1043). B10 explicitly replaces ranking; planner/readiness ownership remains unchanged.

<a id="b5"></a>
### B5 — Measure aggregation benefit and shared-bottleneck cost

Complete, negative, in [PR #1366](https://github.com/the-sarge/quic-go-fast/pull/1366), [child #1044](https://github.com/the-sarge/quic-go-fast/issues/1044). Its [receipt](../audits/2026-11-14-multipath-b5-receipt.md) remains frozen.

<a id="b6"></a>
### B6 — Publish the supported BBR and aggregation outcome

Complete in [PR #1369](https://github.com/the-sarge/quic-go-fast/pull/1369), [child #1045](https://github.com/the-sarge/quic-go-fast/issues/1045). Its [support record](../audits/2026-11-14-multipath-b6-support.md) remains historical; B9 and B12 own subsequent support changes.

<a id="b7"></a>
### B7 — Prefer same-path ACK carriage at the multipath receiver

Complete in [PR #1364](https://github.com/the-sarge/quic-go-fast/pull/1364), [child #1357](https://github.com/the-sarge/quic-go-fast/issues/1357). ACK-turn/release/alternation and periodic per-carrier PING rules remain unchanged.

<a id="b8"></a>
### B8 — Bound completed ACK-only sent history (closed with no code)

Dropped by [owner decision on #1356](https://github.com/the-sarge/quic-go-fast/issues/1356#issuecomment-6866681570); abandoned [PR #1358](https://github.com/the-sarge/quic-go-fast/pull/1358) and [PR #1360](https://github.com/the-sarge/quic-go-fast/pull/1360) are not baselines. B7's bounded PING replaced the proposal. Revisit only if the owner withdraws that PING or a separate design keeps all ACK/loss/ECN consumers whole for retired numbers.

<a id="controller-matched-aggregation-arms"></a>

The [completed six-arm inventory](https://github.com/the-sarge/quic-go-fast/blob/b4e3a4474f51a7b1fa60a0febbc79b04da4c4e72/docs/adr/2026-10-24-multipath-bbr-plan.md#controller-matched-aggregation-arms) is historical; the current B11 four-arm inventory above is authoritative for this continuation.
