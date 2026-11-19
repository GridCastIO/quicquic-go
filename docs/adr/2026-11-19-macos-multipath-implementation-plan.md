# macOS multipath implementation plan

**Date:** 2026-11-19. **Track:** MP-MAC, one track in [MP-MAC-20261119](2026-11-19-macos-multipath-program.md). **Status:** Accepted handoff; implementation in progress. **Parent issue:** pending. **Normative scope:** Current slice contracts, preserved profile, evidence, dependencies and stop conditions. **Audit history:** [Handoff audit](../audits/2026-11-19-macos-multipath-handoff/README.md); [planning PR #1479](https://github.com/GridCastIO/quicquic-go/pull/1479). The completed [planning issue #1396](https://github.com/GridCastIO/quicquic-go/issues/1396) stays closed.

## Outcome and authority

Enable the approved native Darwin arm64 profile only after its native evidence exists: QUIC v1 draft-21, Reno primary/backup, experimental BBRv3 primary/backup and experimental BBRv3 aggregate, with at most two active or validating protocol paths including path zero. Reno remains default; Reno aggregate and enabled QUIC v2 remain refused. Intel and other Darwin majors remain separately qualified targets. Full BBR qualification, a higher common path cap, private batching optimization and unrelated platform programs are non-goals.

The [accepted target and semantic plan](2026-11-18-macos-multipath-plan.md) supplies the settled profile and native-evidence distinctions. This document replaces its proposed M1/M2/ME/M3/M4 work units with eleven audited child contracts; it does not reduce that outcome. E1–E3 implement M1 readiness, P1–P2 implement M2 readiness, C1–C4 implement ME readiness, Q1 binds their concrete execution protocol, and Q2 combines M3/M4 activation, evidence, continuing coverage and support publication. There is one intended PR and one fresh implementation context per child.

The handoff publishes documents and dispatch pointers only. It launches no implementation, qualification, privileged sampler or infrastructure provisioning. A later dispatch of a readiness child permits its scoped implementation and ordinary development tests, including the narrowly stated local socket/handshake smoke; it does not allocate native qualification, cost/topology measurements or a campaign. Q1 must obtain the owner's decision on a concrete protocol and operational inventory before Q2 can be dispatched. No historical attempt allowance, performance exception or exhausted budget is inherited.

## Current shape and existing-work disposition

Facts below were inspected at source `0fbad183f7c92eba8fa234cb9194d87029e4014d`; line anchors refer to that commit. Existing runtime owners are retained.

| Fact | Source | Consequence |
| --- | --- | --- |
| Darwin already reaches the bounded native endpoint through the private grant seam | `native_transport.go:1,25,49`; `native_endpoint.go:420` | E fixtures use the existing real socket/writer. No production bypass or new writer is needed. |
| The native writer owns deadline installation, sends, final reset and whole-borrow completion | `native_endpoint.go:1349`; expiry/control remains with the endpoint owner | Preserve authority until actual return; queued expiry and close cannot impersonate writer completion. |
| Local error classification and accepted/uncertain/unsubmitted outcomes have existing owners | `native_endpoint.go:1424,1475` | New fixtures observe those results; they do not reinterpret local backpressure as network loss. |
| Darwin produces scalar packets; automatic software grouping is Linux-only | `packet_emission.go:240`; `sys_conn_helper_darwin.go:42` | Constructed segmented members are separately labeled writer-level tests, never ordinary Darwin emission evidence. |
| Explicit grants and enabled admission share the platform predicate; native grant setup validates duration/socket ownership/conflicts; Config selection owns path count/policy; enabled admission checks controller/policy/version compatibility | `multipath_api.go:65–163`; `native_transport.go:25–48`; `sys_conn_df_darwin.go:76` | Q2 changes one platform capability owner, preserving each input owner, the ordinary-traffic early return and granted ordinary QUIC v2. |
| Public tests can currently skip according to production support; HTTP/3 also has a separate Linux-only predicate | `multipath_api_test.go:28`; `http3/multipath_test.go:20` | Q2 must state expected support independently so a wrong gate cannot skip its own regression. |
| The peer runner pins Linux/Go identity, container assumptions and launch tools | `interop/multipath/run.py:94,128,170`; `integrationtests/self/picoquic_control_test.go:35,156` | P1 adds an explicit native Darwin mode while preserving the current Linux mode. |
| Both-active aggregate STREAM deltas exist; DATAGRAM sends precede activation | `multipath_picoquic_matrix_test.go:391,399` | P2 must correlate new post-activation payloads with actual ingress paths. |
| Peer DATAGRAM callback exposes path identity, but the current echo path comes from a payload byte | `interop/multipath/peer.c:217,222,374` | The receive callback path, not the requested echo path, owns ingress evidence. |
| Ordinary measurement is Linux-only, BBR is restricted to stateless pressure, and RSS/host tools use Linux interfaces | `ordinary_cost_test.go:1,90,265`; `interop/multipath/ordinary_cost.py:294,385,481` | C1 supplies explicit native adapters and BBR bulk workloads; it must not fabricate equivalent counters. |
| `ConnectionStats().PacketsLost` is recorded by the ordinary fixture, but its increment belongs to Reno/CUBIC | `ordinary_cost_test.go:576`; `internal/congestion/cubic_sender.go:216` | Mark that metric unavailable for BBR; use named relay/receiver/endpoint observations where available. |
| Existing public path tests reach validated backup, abandonment and detachment states | `multipath_api_test.go:568` | C2 uses these public interfaces on Linux for readiness; native Darwin execution waits for Q2's real admission candidate. |

**Existing-work disposition:** retain the merged endpoint, Reno and BBR owners and the settled profile. [PR #1295 — lazy scalar deadline experiment](https://github.com/GridCastIO/quicquic-go/pull/1295) stays Draft/unselected historical evidence, excluded from this graph. Its Linux-only adapter and exhausted comparison inventory are not an established baseline or a macOS prerequisite; the [closure of issue #1285](https://github.com/GridCastIO/quicquic-go/issues/1285#issuecomment-6788620596) governs it. Do not merge, rework or close it incidentally. Revisit only under a separately accepted repair contract supported by relevant new evidence. No existing macOS implementation child or program is being grandfathered, and no unrelated legacy program is rebaselined.

## Decisions and preserved ownership

Use the native endpoint's existing grant, request/result and join interfaces. The connection goroutine retains path, packet-number, recovery and scheduling decisions; the writer performs socket work and returns facts. The shared endpoint state owner handles admission, expiry and completion publication. No secondary deadline owner, helper cancellation state machine, production global override, fake platform identity or exported qualification bypass is allowed. The exact unconnected `*net.UDPConn` requirement and existing conflicts remain intact. A write grant grants neither read nor close ownership; transport detachment and transport-wide grant return remain different events.

The initial measurement venue remains the recorded Darwin 27 arm64 host tuple and proposed Go 1.26.11/1.27.4 support matrix. Q1 resolves installed toolchain paths, version applicability, default/private-syscall-opt-out cells, earlier/later Darwin 27 applicability and continuing-runner availability against actual readiness outputs. A build, Linux container or Rosetta run cannot substitute for required native evidence. Lack of evidence leaves Q2 unmerged; a reduced controller/policy target, broader admitted platform domain, relaxed limit or new cost exception requires an owner decision.

Readiness is useful before public admission: E fixtures cross existing private endpoint seams; P1 demonstrates an ordinary native peer; P2 validates its receipt producer/validator through fixture accounting and both-role characterization; a live Linux aggregate control needs separate approval. C1's negotiated mixed-bulk smoke and C2/C4 public multipath controls use already-supported Linux and build/refuse on Darwin. These are explicit evidence classes. They do not need an unmerged support switch or a hidden bypass. C1's ordinary granted workloads can use a root-test-only private grant setup; they must not claim negotiated multipath on that seam.

P1 uses test-owned `127.0.0.1` sockets with distinct ephemeral ports for Darwin tuples, including replacement tuples, and passes explicit tuples to both the Go fixture and C peer. Preserve Linux address defaults. For the native adapter, use the existing unbuffered peer output; for the ordinary demo, bounded successful Dial establishes readiness rather than requiring a buffered log line. Both child processes remain canceled and joined. Isolated user-owned build-tool prefixes are permitted in that later development slice; system package changes, privileged aliases, peer-pin changes and runner provisioning are outside it.

C1 keeps per-process `getrusage` CPU and peak RSS units explicit, using Darwin bytes versus Linux kB. Host activity comes from an optional native `powermetrics --format plist` adapter parsed by `plistlib`, preserving raw NUL-separated plist records and explicit performance/efficiency labels. No handwritten parser claims general plist coverage. Required privilege, unsupported fields or incomplete windows yield unavailable/inconclusive attribution, never a quiet-host pass. Q1 selects and authorizes any actual sampler invocation; C1 tests its adapter with recorded producer-shaped fixtures. Do not transfer Linux foreign-CPU arithmetic or thresholds to different native counters.

C2 observes live/retained memory at matched negotiated-connection lifecycle states separately from lifetime peak RSS. C3 supplies a narrowly maintained userspace UDP relay successor to the archived B11 queue design: distinct queues for disjoint paths, unequal configured rates/delays, and one shared queue including the Reno competitor for the shared-bottleneck case. C4 consumes that relay and C1's metric records while retaining topology/control identity. The relay owns its queues; the existing transport still owns pacing and congestion decisions. No PF/dummynet, privileged host-network changes, controller tuning or retired-script resurrection is implicit.

**Owner's-design comparison:** the state owners' direct designs are retained: endpoint-owned deadlines and completion, peer-owned ingress facts, transport-owned path lifecycle, and metric collectors that return observed facts. The native process/host adapters are contained only around test tooling, where Linux and Darwin are real differing producers. Moving those facts into production would add runtime interfaces and diagnostic obligations outside the accepted outcome; rejected, revisit only if a separately accepted production observability requirement makes them necessary. The userspace relay is external controlled test infrastructure; changing a transport scheduler to emulate topology would corrupt the subject under measurement and is rejected on merit.

**Rejected alternatives — do not do these:** Reno-only or primary/backup-only delivery contradicts the accepted profile; revisit only on an evidence-backed owner decision. Unrestricted Darwin admission includes unqualified targets; revisit only after separately accepted qualification. Splitting support publication from the gate permits an unsupported intermediate claim; none: rejected on merit. A standalone platform-helper prefactor adds a merge gate without needed independent behavior; none: rejected on merit. A generic cross-platform qualification framework or recursive proof of fixtures exceeds this finite program; none: rejected on merit. Reusing frozen B11 executables as maintained dependencies violates their evidence status; revisit only through a separately accepted maintenance contract. Preserve frozen bytes and existing numbered ADRs; no new domain term or numbered ADR is needed.

## Slice graph

| Slice | State/disposition | End-to-end outcome | Blocked by | Temporary seam removed |
| --- | --- | --- | --- | --- |
| E1 | Complete ([PR #1498](https://github.com/GridCastIO/quicquic-go/pull/1498)) | Granted scalar socket fixture and native case receipt | None | None |
| E2 | New; frontier | Blocked-writer deadline/borrow fixture | E1 | None |
| E3 | New; frontier | Scalar contention and pressure-observation fixture | E1 | None |
| P1 | New; frontier | Native pinned peer build, launch and ordinary control | None | None |
| P2 | New; frontier | Fresh aggregate DATAGRAM ingress witness | None | None |
| C1 | New; frontier | Native ordinary workloads and truthful metrics | None | None |
| C2 | New; blocked | Negotiated lifecycle-memory observation | C1 | None |
| C3 | New; frontier | Scoped UDP queue/topology relay | None | None |
| C4 | New; blocked | Topology/control comparison workload | C1, C3 | None |
| Q1 | New; blocked | Concrete approved execution/venue protocol | E2, E3, P1, P2, C2, C4 | None |
| Q2 | New; blocked | Qualified public activation, continuing coverage and support | Q1 | None |

E1, P1, P2, C1 and C3 are parallel-safe in separate worktrees. E2/E3 follow E1 independently; C2 follows C1, while C4 requires both C1 and C3. P1/P2 may touch the same peer files but neither needs the other's behavior; coordinate ordinary merges without adding a convenience dependency. Q1 requires the six leaf readiness outputs, with their prerequisites transitively satisfied, because it must bind executable commands and known limitations. Q2 requires Q1's accepted protocol and owner decision. Shared-host measurement coordination is an operational condition, not a convenience blocking edge. No separate ordering is imposed by file proximity.

## Common slice contract

Each readiness slice produces a bounded verification aid and accompanying process/traceability metadata. Existing runtime safety enforcement stays unchanged. Its apparatus is a maintained deliverable for the named domain, owned by the transport test/interop maintainer; its payoff is detecting the named Darwin support regression and making the required native observation attributable. It retires on equivalent replacement or removal of that support profile, preserving accepted historical receipts. This is not a requirement to prove harness completeness. Q1 explicitly records the owner-approved payoff, domain, owner and retirement policy for any selected aid that will become a required continuing CI check; an unapproved aid cannot become a new product blocker by reviewer demand. Q2's already accepted native evidence remains required independently of optional recurring checks.

Representation is typed Go requests/results, exact explicit socket tuples and standard-library parsed versioned JSON/plist records from the named fixture producers. Receipt accounting is a canonical-subset guarantee over declared case IDs, identity fields and statuses; runtime/native observations are example-level evidence. Standard parsers own syntax; named fixture runners own semantic case/identity validation. Unknown or malformed records fail rather than count as evidence. There is no universal platform or scheduler guarantee. No new persisted product fact becomes authoritative; fixture receipts never authorize runtime behavior by themselves.

The evidence budget is semantic, not a campaign allocation: one representative positive case for each named behavior and one negative for each materially distinct named failure/owner; one execution of focused development tests on each platform whose adapter changed; no statistical repeats, extra platform cross-products, new mutation harness, capture campaign or repeat-until-pass behavior. Existing required hosted jobs retain their existing finite inventories. At most one central-guard mutation is permitted only if inherited coverage cannot otherwise demonstrate the named guard; none is required by default. Each child receives one initial RAS review and at most one replacement under the shared policy. Exact qualification timings, toolchain/build matrix and operational attempts are selected in Q1 before execution, retaining the established request-deadline/tolerance contract rather than inventing a new bound.

Qualification, pressure and comparative-cost entrypoints remain behind explicit build tags and CLI profile selectors, separate from default development-test selection. Their ordinary accounting/adapter tests do not accidentally launch those operational modes.

TDD crosses the real interface named by each slice. Adapter/accounting tests catch bookkeeping and failure cleanup but miss OS behavior; local real-socket or ordinary-handshake smoke catches adapter integration but is not qualification; public Linux controls catch supported protocol behavior but do not qualify Darwin; Q2's native observations catch the selected real-platform cases but not unobserved failures or general performance. Tests must label these distinctions. A fixture that cannot produce its promised executable method stays open with a concrete blocker; recording a blocker does not make successors ready.

No temporary duplicate runtime representation, second mutation owner or double-open product lifetime is introduced. Explicit test adapters are durable platform variants, not transitional aliases awaiting a successor. A slice discovering a temporary production seam must stop for re-audit rather than silently assign its removal to Q2. Effects not yet traced are confined to native trigger feasibility, exact host sampling availability, native build compatibility and measured costs; they remain execution decisions/observations, not permission to change production behavior.

Every dispatch includes this common contract, the named slice and its referenced source interfaces, the program graph, the settled profile table, and only the linked unresolved history named by that slice. The maximum relevant historical material is the cited decision/receipt plus the governing diff for the current contract, not complete prior plan versions or campaigns. Source lists are scopes, not permission to edit every listed file. A fresh context must contain implementation, local fixes and verification; if it requires redesigning a neighboring interface, re-audit/split before editing.

## Native safety and activation coverage argument

The endpoint borrow invariant is materially consequential and crosses independent expiry, close and native-return states. Its existing enforcement owner remains `nativeEndpoint` and its sole writer; E slices add proportionate observations, not another enforcement system. Q2's admission invariant is materially consequential because distinct constructors/grants can admit an unsupported public combination. Its representation is the finite typed platform/controller/configuration partition, owned by the common platform helper plus existing admission checks. Native evidence remains example-level. No recursive closure of test infrastructure is required.

| Invariant/class | Expected disposition and owner | Evidence owner | Status |
| --- | --- | --- | --- |
| Exact grant; duplicate/conflicting grant; post-join write authority | Existing grant validator rejects invalid ownership; writer join returns authority only after actual exit | E1 positive/refusal/post-join controls, Q2 public lifecycle | Planned |
| Current native borrow; final deadline reset; canceled waiter | Borrowed storage stays live until writer and reset finish; canceled wait is not join | E2 deterministic return/reset, selected race cases and executable method; Q1 binds commands; Q2 records actual native active-close witness and focused race results | Planned |
| Queued expiry while writer blocked; expired claim and successor | Endpoint state owner expires queued work; writer does not send expired claims or reuse stale deadline | E2 typed results and executable trigger; Q1 approves the bounded command; Q2 records the actual poller witness and queued-expiry observation | Planned |
| Local EAGAIN/timeout/ENOBUFS versus EMSGSIZE | Existing classifier preserves local backpressure versus size feedback; simulated/native/pressure evidence stays distinct | E2/E3; unobserved UDP ENOBUFS is explicit | Planned |
| Lane contention, diagnostic backpressure and absent pressure wait | Existing bounded admissions/fairness remain authoritative; observation can be negative without retries | E3 and current deterministic lane tests | Planned |
| Admitted Linux and selected Darwin arm64 tuples versus other/unknown/iOS targets | One capability decision admits only the selected domain and fails closed | Q2 independent table expectations, exact native identity | Planned |
| Exact socket/duration/grant ownership and socket conflicts | Existing native grant validator checks explicit duration/exact unconnected socket and library-owned socket setup; enabled admission retains applicable conflicts | Q2 explicit-grant, owned-socket and admission controls, including granted ordinary QUIC v2 success | Planned |
| Three admitted controller/policy combinations versus Reno aggregate and enabled v2 | Config selection and enabled constructor/server-selected admission retain controller/policy/version checks; explicit grants do not accept Config inputs | Q2 public/root/HTTP3 configuration controls with independent expectations | Planned |
| BBR per-path sampling/recovery eligibility, pending-local credit, migration/ECN fences and protected-member lifetime | Existing BBR/path-recovery and endpoint completion owners retain their respective facts; Reno observations cannot stand in for BBR-specific behavior | E2 selects focused race cases; Q1 binds existing BBR tests and native protected-member/transfer/migration/close observations; Q2 records results on its exact candidate | Planned |
| IPv4-only, IPv6-only and dual-stack mapped IPv4/native IPv6 delivery; packet-info address/interface identity and ECN | Existing Darwin socket helpers and granted endpoint retain packet metadata ownership | E1 supplies the methods; Q1 binds each family/metadata/ECN receipt and ordinary ECN-disabled control from the accepted native semantic map; Q2 records exact-candidate results; missing required family evidence blocks activation | Planned |
| Aggregate scheduling versus useful receipt | Existing scheduler retains selection; fresh independent-peer ingress while both paths remain live/active establishes receipt | P2 phase accounting and Q2 both-role aggregate witness | Planned |
| Validation before migration cutover; isolation from old-tuple errors/ACKs; detachment versus transport join | Existing connection/path owners preserve tuple generation and authority; old feedback cannot alter the replacement; detachment does not imply transport join | Portable multipath_migration_test.go assertions, including TestPathMigrationLateOldGenerationAck and old-tuple errors, establish stale-feedback handling; Q1 binds native public migration/survivor and both-role same-ID peer rebinding observations; Q2 records transition and useful-transfer results | Planned |

## Implementation slices

### E1 — Granted scalar socket fixture and case receipt

**What it delivers:** A Darwin-tagged root fixture reaches the real private endpoint grant, sends and receives scalar UDP with metadata, joins, and returns write/deadline authority. A minimal Darwin case runner records source/tree, binary, toolchain, build mode and native identity and rejects missing/duplicate/skipped required case records. This is an executable endpoint test method with ordinary local smoke evidence, not a support receipt.

**Existing-work disposition:** New slice on the current default branch; retain the inspected runtime owners. No unmerged implementation branch is a prerequisite.

**Blocked by:** None

**Single owner after merge:** The existing endpoint owns grant/deadline/borrow transitions. The fixture owns its sockets and case expectations; one runner owns expected-case accounting and its child process lifetime. It never changes connection/path policy.

**Authority completeness:** No new persisted product authority. Constructors, record validation, subprocess exit/cleanup and receipt readback are covered for this verification aid; a receipt cannot open public admission.

**Transitional-seam budget:** None. Named test adapters are maintained platform variants; no duplicate runtime state, temporary production override or double-open product lifetime is permitted.

**Blast radius:** New Darwin test/driver files and narrowly shared test mechanics only. Real sockets, one owned test subprocess and receipt output add cleanup/identity obligations; no production worker, dependency, ABI or socket privilege changes. Exact native timing and pressure remain unverified until Q2.

**Artifact classification:** Verification aid plus process/traceability metadata under the common maintained-deliverable contract. Existing shipped behavior and safety enforcement remain unchanged.

**Representation contract:** The common typed/canonical fixture-result contract applies; standard parsers own syntax. Named finite semantic cases receive representative regression coverage; native observations remain example-level.

**Contract closure:** No recursive closure of this verification aid. It supplies the named rows of the common native safety coverage argument; production enforcement ownership remains unchanged.

**Evidence budget:** The listed semantic cases, one positive per named behavior and one negative per distinct listed failure, terminate development validation. Use the common platform/review limits; no qualification/performance inventory, statistical repetition or extra mutation program is allocated.

**TDD and preservation evidence:** First characterize TestNativeIOGrantValidation and TestNativeIOStopAndJoin, then make missing/duplicate/skipped identity and timeout/reaping cases fail in the runner seam. Exercise IPv4, IPv6 and both mapped/native delivery on a dual-stack socket, source/interface/ECN identity, duplicate/conflicting grants and caller write/deadline use after join. One ordinary local real-socket smoke per family supplies adapter evidence. Preserve Linux runner behavior through its existing accounting tests and public Darwin refusal through unchanged support tests.

**Dispatch context budget:** This slice/common contract; settled socket/profile rows; native_transport.go, native_endpoint.go grant/constructor interfaces, sys_conn_helper_darwin.go and sys_conn_oob.go; native_shutdown_test.go and relevant socket tests; only the runner/fixture diff. Existing Linux qualification code is reference for record shape, not an instruction to port its entire campaign.

**Slice decision audit:** Splitting the generic runner from its first scalar consumer yields an unexercised horizontal abstraction; rejected on merit. Merging E2 or E3 would mix ordinary grant/metadata behavior with blocked-write or observational-pressure semantics; do not merge them. Revisit: none: rejected on merit. No technical blocker exists: the private grant already supports Darwin.

**Stop conditions:** Stop if this needs a production owner/interface change, new public bypass, privileged host modification, unbounded fixture language, adjacent slice redesign or an unresolved capability that prevents the promised deliverable. Keep the child open with the concrete blocker; do not declare readiness from a skip.

### E2 — Blocked-writer deadline and borrow-lifecycle fixture

**What it delivers:** Extend E1 with an executable bounded scalar EAGAIN-to-Go-poller method using read-back socket capacity, valid ECT control and payload-plus-ancillary space demand, followed by deadline/result/successor observations. Reuse that one current-write witness for queued expiry and active-close/join; retain first-send EPERM, constructed segmentation/prefix and scalar EMSGSIZE as separately classified cases. Implementation and simulated accounting validation merge before any separately authorized native feasibility/qualification attempt. Select the existing Darwin endpoint race cases for borrow, deadline reset and shutdown as a concrete output, without adding a new stress inventory.

**Existing-work disposition:** New slice on the current default branch; retain the inspected runtime owners. No unmerged implementation branch is a prerequisite.

**Blocked by:** E1

**Single owner after merge:** The existing native writer owns actual call and final reset; endpoint control owns queued expiry; the fixture driver observes stack/result facts and its own process cleanup. It cannot release a borrowed buffer or invent successful join.

**Authority completeness:** No new persisted product authority. Constructors, record validation, subprocess exit/cleanup and receipt readback are covered for this verification aid; a receipt cannot open public admission.

**Transitional-seam budget:** None. Named test adapters are maintained platform variants; no duplicate runtime state, temporary production override or double-open product lifetime is permitted.

**Blast radius:** E1 fixture/driver extension and focused tests, no runtime changes. Trigger construction must use correctly sized typed request storage rather than appending an arbitrary B-sized payload to the small pooled buffer. Syscall tracing is optional attribution; Q2 qualification using E2 requires an actual Go poller/write-wait witness. Judge native timing only from untraced observations. Feasibility on the selected kernel/toolchain is explicitly untraced until authorized collection.

**Artifact classification:** Verification aid plus process/traceability metadata under the common maintained-deliverable contract. Existing shipped behavior and safety enforcement remain unchanged.

**Representation contract:** The common typed/canonical fixture-result contract applies; standard parsers own syntax. Named finite semantic cases receive representative regression coverage; native observations remain example-level.

**Contract closure:** No recursive closure of this verification aid. It supplies the named rows of the common native safety coverage argument; production enforcement ownership remains unchanged.

**Evidence budget:** The listed semantic cases, one positive per named behavior and one negative per distinct listed failure, terminate development validation. Use the common platform/review limits; no qualification/performance inventory, statistical repetition or extra mutation program is allocated.

**TDD and preservation evidence:** First use existing MemberReturnPrecedesDeadlineReset, QueuedExpiry, OverdueBorrow, ExpiredClaimAndNextDeadline, NativeIOStopAndJoin and NativeLiveCloseDuringCurrentWrite expectations. Add fixture classification tests for absent stack witness, expired-before-dispatch versus blocked native call, missing native return, final reset failure, and cleanup on interrupted observation. Verify the compiled method preserves the request absolute deadline across the native call and never labels injected errno as native traversal. The positive actual poller witness and timing observations are Q2 work under Q1, not readiness execution. Record the selected focused race commands against the named return/reset/borrow/shutdown tests for Q1 to bind and Q2 to execute. Native protected-member evidence remains explicitly BBR-aware through the common coverage row and Q1 protocol.

**Dispatch context budget:** This/common contract plus E1 runner/result interface, native_endpoint.go writer/expiry/result portions, native_shutdown_test.go, named endpoint tests and the archived Darwin trigger protocol section. Do not ingest the complete Linux campaign or PR #1295 implementation.

**Slice decision audit:** E1 is a real blocker because the method consumes its socket/identity/case lifetime interface. Separate queued-expiry, close and deadline PRs would duplicate the same borrowed-current-write witness; rejected on merit. Merge with E3 is rejected because pressure absence can succeed observationally while missing forced traversal cannot qualify support. Revisit: none: rejected on merit. Native feasibility failure is an execution blocker, not permission to change the endpoint owner.

**Stop conditions:** Stop if this needs a production owner/interface change, new public bypass, privileged host modification, unbounded fixture language, adjacent slice redesign or an unresolved capability that prevents the promised deliverable. Keep the child open with the concrete blocker; do not declare readiness from a skip. If Q2 cannot obtain the actual Go write-wait witness, activation stays blocked: diagnose the trigger, route method repairs to this fixture owner and obtain Q1 reapproval for any changed protocol before a rerun. Absence is not evidence of safe native deadline behavior.

### E3 — Scalar contention and pressure-observation fixture

**What it delivers:** Extend E1 with scalar lane contention records and a bounded socket-pressure observation mode: offers, accepted/uncertain/unsubmitted counts, lane progress/refusal/occupancy, immediate local errors, writer wait observations and native return/publication times. The executable method reports absent pressure waits honestly and separates them from E2's required induced traversal. Collection waits for Q1/Q2.

**Existing-work disposition:** New slice on the current default branch; retain the inspected runtime owners. No unmerged implementation branch is a prerequisite.

**Blocked by:** E1

**Single owner after merge:** Existing endpoint admission/fairness and result classification remain owners of behavior. The fixture owns offered load and observations; diagnostics are bounded and cannot block the writer or become a new admission policy.

**Authority completeness:** No new persisted product authority. Constructors, record validation, subprocess exit/cleanup and receipt readback are covered for this verification aid; a receipt cannot open public admission.

**Transitional-seam budget:** None. Named test adapters are maintained platform variants; no duplicate runtime state, temporary production override or double-open product lifetime is permitted.

**Blast radius:** Test producer/observer and driver extensions only. Synchronization and teardown must join observers/producers before sockets or storage are released. No Linux marked-group yield, affinity, process termination, host reservation or privileged network setup transfers. Native pressure occurrence remains unknown.

**Artifact classification:** Verification aid plus process/traceability metadata under the common maintained-deliverable contract. Existing shipped behavior and safety enforcement remain unchanged.

**Representation contract:** The common typed/canonical fixture-result contract applies; standard parsers own syntax. Named finite semantic cases receive representative regression coverage; native observations remain example-level.

**Contract closure:** No recursive closure of this verification aid. It supplies the named rows of the common native safety coverage argument; production enforcement ownership remains unchanged.

**Evidence budget:** The listed semantic cases, one positive per named behavior and one negative per distinct listed failure, terminate development validation. Use the common platform/review limits; no qualification/performance inventory, statistical repetition or extra mutation program is allocated.

**TDD and preservation evidence:** First characterize current bounded lane/admission and nonblocking diagnostic tests. Fixture tests distinguish real progress, a refused lane, missing observer coverage, immediate ENOBUFS, and a valid negative pressure-wait result; interrupted load must clean up. One synthetic scalar contention accounting case exercises the actual fixture interfaces without asserting native pressure. Actual pressure attempts and scheduler observations belong to the Q1 inventory; no retries to rescue a negative observation.

**Dispatch context budget:** This/common contract, E1 runner contract, current endpoint admission/fairness and diagnostics portions, native_admission_test.go and TestNativeEndpointFairLargeAdmission/TestNativeEndpointDiagnosticSaturation in native_endpoint_test.go. Historical E6 is limited applicability context; its older fairness expectations are not normative.

**Slice decision audit:** E1 is necessary for socket/case lifetime and receipt accounting. E2 success is not a blocker: this observation can legitimately report no pressure wait. Splitting counters from their offered-load consumer yields no trustworthy observation; rejected on merit. Merging E2 conflates two evidence meanings and expands one context; rejected on merit.

**Stop conditions:** Stop if this needs a production owner/interface change, new public bypass, privileged host modification, unbounded fixture language, adjacent slice redesign or an unresolved capability that prevents the promised deliverable. Keep the child open with the concrete blocker; do not declare readiness from a skip.

### P1 — Native pinned peer build and ordinary control

**What it delivers:** Add an explicit native Darwin build/execution profile for the existing picoquic/PicoTLS pins, compiler/SDK/binary identity, explicit loopback tuples, portable truncation checks, bounded launch/readiness and child joining. Produce a native build plus the existing ordinary client/server control pair on the selected development toolchain. Preserve Linux Docker identity/defaults. A missing tool is a failing prerequisite, not a successful native receipt. Port and compile the tagged root matrix and its launch helpers for Darwin, including initial/replacement tuples and peer arguments for both roles; list TestPicoquicMultipathMatrix in the native test binary without executing multipath before Q2.

**Existing-work disposition:** New slice on the current default branch; retain the inspected runtime owners. No unmerged implementation branch is a prerequisite.

**Blocked by:** None

**Single owner after merge:** The Go fixture owns test socket tuples and child lifecycle; the C adapter consumes explicit tuples and reports callback facts. The runner owns execution identity and case accounting. Existing peer protocol implementation remains upstream-owned at its current pins.

**Authority completeness:** No new persisted product authority. Constructors, record validation, subprocess exit/cleanup and receipt readback are covered for this verification aid; a receipt cannot open public admission.

**Transitional-seam budget:** None. Named test adapters are maintained platform variants; no duplicate runtime state, temporary production override or double-open product lifetime is permitted.

**Blast radius:** Native build recipe, runner execution-profile branch, C socket adapter and ordinary launch helper. Use an isolated user-owned tool prefix for needed CMake/build prerequisites, recording provenance; no system package changes, global library injection, privileged aliases, peer-pin change or continuing runner provisioning. Native build compatibility must be demonstrated, not inferred from tags. The bounded test-adapter scope also includes multipath_picoquic_matrix_test.go build constraints/matrixTransport/role launches/replacement tuples and Linux-tagged multipath_picoquic_test.go helpers; preserve Linux defaults and receipt semantics.

**Artifact classification:** Verification aid plus process/traceability metadata under the common maintained-deliverable contract. Existing shipped behavior and safety enforcement remain unchanged.

**Representation contract:** The common typed/canonical fixture-result contract applies; standard parsers own syntax. Named finite semantic cases receive representative regression coverage; native observations remain example-level.

**Contract closure:** No recursive closure of this verification aid. Its native build, matrix discovery, tuple/launch interface and ordinary controls feed Q1's executable peer protocol and Q2's wire observations; they do not themselves supply a direct native safety-table witness. Runtime enforcement ownership remains unchanged.

**Evidence budget:** The listed semantic cases, one positive per named behavior and one negative per distinct listed failure, terminate development validation. Use the common platform/review limits; no qualification/performance inventory, statistical repetition or extra mutation program is allocated.

**TDD and preservation evidence:** First test Linux/native identity dispatch, wrong/missing identity, duplicate/skipped/missing cases and launch failure/timeout cleanup. Test explicit tuple exchange and platform-correct truncation rejection. Then build the pinned peer natively and run the bounded ordinary control pair using successful QUIC handshake as readiness. Preserve both child exit checking and join; skip-based success is forbidden. No native multipath matrix is run here. Compile the tagged native root test binary and require its discovery receipt to list TestPicoquicMultipathMatrix. Separately, record both successful ordinary handshake roles from the integrationtests/self test binary; neither receipt substitutes for the other. Inspect explicit initial and replacement tuples and both-role launch arguments.

**Dispatch context budget:** This/common contract, interop/multipath/{Dockerfile,run.py,peer.c,README.md}, build/launch/identity/address portions of multipath_picoquic_test.go and multipath_picoquic_matrix_test.go, integrationtests/self/picoquic_control_test.go, and pinned upstream build guidance. Matrix semantics and P2 receipt logic remain outside the adapter port; no complete historical peer campaign.

**Slice decision audit:** No blocker: ordinary peer construction does not require multipath admission or endpoint fixture readiness. A build-only or launcher-only PR lacks the usable native peer path this contract promises; do not split them. Revisit: none: rejected on merit. P2 is independent witness semantics, so shared files require merge coordination rather than a dependency or merged slice. Do not merge P1/P2; revisit: none: rejected on merit. Matrix compilation/discovery belongs to the same native launch adapter: the separate ordinary helper cannot establish that Q1 has a runnable matrix command. A separate tags-only slice has no complete usable interface; none: rejected on merit. P2 still owns fresh receipt semantics independently.

**Stop conditions:** Stop if this needs a production owner/interface change, new public bypass, privileged host modification, unbounded fixture language, adjacent slice redesign or an unresolved capability that prevents the promised deliverable. Keep the child open with the concrete blocker; do not declare readiness from a skip.

### P2 — Fresh aggregate DATAGRAM ingress witness

**What it delivers:** Extend the existing useful-transfer phase with a fresh nonce and bounded sequence of identifiable payloads after simultaneous activation, independent-peer callback receipts carrying actual ingress path, and acceptance requiring useful matching receipt on both paths in each role. Sender deltas remain scheduling evidence. Receipt production and validation ship together; native Darwin execution waits for Q2. Snapshot per-path DATAGRAM counters after activation. In each role, require both paths to report Lifecycle `live` and LocalUse `active` on every bounded offer round and at phase end; fresh nonce-matched ingress on both paths across successive single-path intervals cannot pass.

**Existing-work disposition:** New slice on the current default branch; retain the inspected runtime owners. No unmerged implementation branch is a prerequisite.

**Blocked by:** None

**Single owner after merge:** The independent peer callback owns actual ingress facts; the Go matrix witness owns phase/payload membership and acceptance. The production aggregate scheduler still owns path selection. Requested payload path or echoed byte never substitutes for actual ingress.

**Authority completeness:** No new persisted product authority. Constructors, record validation, subprocess exit/cleanup and receipt readback are covered for this verification aid; a receipt cannot open public admission.

**Transitional-seam budget:** None. Named test adapters are maintained platform variants; no duplicate runtime state, temporary production override or double-open product lifetime is permitted.

**Blast radius:** Peer callback diagnostic record and matrix test phase/parser only; preserve existing scenario inventory and protocol pins. The record parser uses an explicitly emitted finite record shape rather than parsing arbitrary peer logs as a language. No production scheduling fix, new unbounded traffic phase or wire extension.

**Artifact classification:** Verification aid plus process/traceability metadata under the common maintained-deliverable contract. Existing shipped behavior and safety enforcement remain unchanged.

**Representation contract:** The common typed/canonical fixture-result contract applies; standard parsers own syntax. Named finite semantic cases receive representative regression coverage; native observations remain example-level.

**Contract closure:** No recursive closure of this verification aid. It supplies the named rows of the common native safety coverage argument; production enforcement ownership remains unchanged.

**Evidence budget:** The listed semantic cases, one positive per named behavior and one negative per distinct listed failure, terminate development validation. Use the common platform/review limits; no qualification/performance inventory, statistical repetition or extra mutation program is allocated.

**TDD and preservation evidence:** Make five fixture-semantic cases discriminating first: fresh matching receipts on both paths pass; pre-activation/wrong-phase receipts fail; duplicates do not count as new receipts; one-path-only delivery fails; sender-only progress fails. Characterize both roles and preserve the existing STREAM witness and bounded offered-work limit. Existing supported Linux fixture/runner accounting is the development control; any additional live aggregate run needs explicit protocol inventory, not assumed CI coverage. The default hosted peer job runs Reno defaults. P2 ships the callback producer and Go validator together and completes on those five fixture cases plus both-role characterization. Unless the owner separately approves a bounded Linux attribution run, Q2 supplies the first planned live both-role aggregate witness. A first failure leaves Darwin attribution inconclusive until fixture behavior is distinguished from platform behavior. Include loss of either path's live/active eligibility within the existing wrong-phase case; retain exactly the five fixture-semantic cases. Keep sender counter deltas distinct from useful peer receipt.

**Dispatch context budget:** This/common contract; matrixUsefulTransfer, matrixSession.datagram and phase accounting in multipath_picoquic_matrix_test.go; peer.c DATAGRAM callback and path-callback initialization; the pinned picoquic callback contract linked in the audit. P1 native adapter output is not required to implement the witness.

**Slice decision audit:** No blocker: existing Linux peer fixture already supplies the real interface. P1's native tuple adaptation is independent and adds no receipt semantic prerequisite. Splitting receipt production from validation or splitting roles yields half a witness; rejected on merit. Merging P1 needlessly couples porting with acceptance semantics; rejected on merit.

**Stop conditions:** Stop if this needs a production owner/interface change, new public bypass, privileged host modification, unbounded fixture language, adjacent slice redesign or an unresolved capability that prevents the promised deliverable. Keep the child open with the concrete blocker; do not declare readiness from a skip.

### C1 — Matched ordinary workloads and native metric records

**What it delivers:** Extend the ordinary fixture to matched Reno/BBR STREAM, DATAGRAM, mixed and response-pressure workloads, with an explicit native execution profile and truthful metric records. Supply self CPU, raw peak RSS/unit normalization, useful bytes, controller/source identity and value/source/availability fields, plus the optional native plist host-observation adapter. Preserve the Linux profile and its existing thresholds. Produce semantic workload smoke results, not comparative cost conclusions.

**Existing-work disposition:** New slice on the current default branch; retain the inspected runtime owners. No unmerged implementation branch is a prerequisite.

**Blocked by:** None

**Single owner after merge:** The fixture owns workload demand and useful-delivery accounting; process collectors own observed CPU/RSS values; the native host producer owns cluster facts; the driver owns measurement windows, cancellation and joins. Missing BBR loss metrics stay unavailable. These owners supply facts and never tune controllers.

**Authority completeness:** No new persisted product authority. Constructors, record validation, subprocess exit/cleanup and receipt readback are covered for this verification aid; a receipt cannot open public admission.

**Transitional-seam budget:** None. Named test adapters are maintained platform variants; no duplicate runtime state, temporary production override or double-open product lifetime is permitted.

**Blast radius:** ordinary_cost_test.go and its native platform helpers, ordinary_cost.py and focused collector/record tests. Two real platform adapters share the minimal result seam consumed by C2/C4; no general benchmark framework or production telemetry. Private ordinary endpoint grant setup is root-test-only and cannot masquerade as negotiated public Darwin multipath.

**Artifact classification:** Verification aid plus process/traceability metadata under the common maintained-deliverable contract. Existing shipped behavior and safety enforcement remain unchanged.

**Representation contract:** The common typed/canonical fixture-result contract applies; standard parsers own syntax. Named finite semantic cases receive representative regression coverage; native observations remain example-level.

**Contract closure:** No recursive closure of this verification aid. Its workload/metric/identity records feed C2/C4 and Q1's ordinary-cost protocol, then Q2's native observations; the outputs are measurement evidence, not direct native safety-table enforcement or witnesses.

**Evidence budget:** The listed semantic cases, one positive per named behavior and one negative per distinct listed failure, terminate development validation. Use the common platform/review limits; no qualification/performance inventory, statistical repetition or extra mutation program is allocated.

**TDD and preservation evidence:** First cover controller/workload admission, CPU interval arithmetic, raw byte/kB conversion, genuine zero versus unavailable BBR counter, missing native identity, malformed/incomplete plist records and interrupted subprocess/sampler cleanup. Run one semantic fixture smoke per distinct workload wiring, with Reno/BBR selection represented, avoiding comparative sampling claims. Recorded plist fixtures test the host adapter; no privileged powermetrics sampling occurs here. Preserve existing Linux result consumers and default execution behavior. Assign the negotiated mixed-bulk smoke to supported Linux public admission, preserving one negotiated background connection with two observed live paths. Darwin readiness covers ordinary traffic, the private ordinary grant and collector checks; Q1 binds the native negotiated mixed-bulk observation for Q2. Do not substitute an ordinary background connection for that workload.

**Dispatch context budget:** This/common contract; ordinary_cost_test.go workload/configuration/result/collector sections, ordinary_cost.py execution/metrics portions, native grant interface for ordinary test setup, and standard getrusage/plist producer contracts. C2/C4 receive only the resulting collector/record interface, not C1 implementation history.

**Slice decision audit:** No blocker: ordinary QUIC and the existing private ordinary grant do not require public multipath activation. Splitting collectors from their real ordinary workload consumer leaves units/window semantics unexercised; rejected on merit. C2 has a separate negotiated lifecycle owner and C4 a topology/control owner, so merging them would inflate the context; rejected on merit.

**Stop conditions:** Stop if this needs a production owner/interface change, new public bypass, privileged host modification, unbounded fixture language, adjacent slice redesign or an unresolved capability that prevents the promised deliverable. Keep the child open with the concrete blocker; do not declare readiness from a skip.

### C2 — Negotiated lifecycle-memory observation

**What it delivers:** Add a phase-labelled memory observation through the real public multipath lifecycle: negotiated idle, validated backup and observed post-retirement state of the sampled path ID, with matched comparison state and joins. Detachment of an old transport during same-ID migration does not retire the still-live path and cannot satisfy the third sample. Record transport detachment and grant join separately when used. Use C1's identity/metric record seam, adding live/retained Go-heap observation separately from peak RSS. Linux public execution demonstrates apparatus wiring; Darwin builds and expected refusal preserve the gate until Q2. Each sample records the path ID and exact StateV1.Lifecycle. The third sample rejects `retiring`; label `retained` and `closed` distinctly, and have Q1 bind the same qualifying phase on both sides of each comparison. This refines the existing three phases and adds no fourth sample.

**Existing-work disposition:** New slice on the current default branch; retain the inspected runtime owners. No unmerged implementation branch is a prerequisite.

**Blocked by:** C1

**Single owner after merge:** Existing public connection/path interfaces own negotiation, validation, abandonment and detachment. The fixture observes StateV1 before each sample and owns consistent memory sampling. A requested transition does not become an observed state merely because the command returned.

**Authority completeness:** No new persisted product authority. Constructors, record validation, subprocess exit/cleanup and receipt readback are covered for this verification aid; a receipt cannot open public admission.

**Transitional-seam budget:** None. Named test adapters are maintained platform variants; no duplicate runtime state, temporary production override or double-open product lifetime is permitted.

**Blast radius:** A narrow lifecycle workload/result consumer and focused tests. Use public ConfigureMultipathIOV1, constructors, OpenPathV1, StateV1, AbandonV1 and detachment/join interfaces. No private admission override, new path state or production memory counter. If forced GC defines the fixture method, apply and label it consistently; Go heap is not total resident memory.

**Artifact classification:** Verification aid plus process/traceability metadata under the common maintained-deliverable contract. Existing shipped behavior and safety enforcement remain unchanged.

**Representation contract:** The common typed/canonical fixture-result contract applies; standard parsers own syntax. Named finite semantic cases receive representative regression coverage; native observations remain example-level. Lifecycle identity is the existing typed StateV1 result for the sampled path ID, not a fixture-invented retirement flag. The third-phase canonical subset is `retained` or `closed`, with one exact qualifying state selected consistently by Q1.

**Contract closure:** No recursive closure of this verification aid. Its observed path-ID/lifecycle-phase memory records feed Q1's comparison protocol and Q2's native memory observations; they are distinct from the table's detachment/transport-authority safety witness.

**Evidence budget:** The listed semantic cases, one positive per named behavior and one negative per distinct listed failure, terminate development validation. Use the common platform/review limits; no qualification/performance inventory, statistical repetition or extra mutation program is allocated.

**TDD and preservation evidence:** First reject an ordinary/unnegotiated backup control and stale/requested-but-unobserved phase records. Check idle-to-backup-to-retirement observations and partial-failure cleanup with the existing Linux public path control. Verify phase/role labels and correct matching baseline in the C1 result seam. Darwin compile/refusal tests are readiness only; native lifecycle memory samples and cost disposition belong to Q2.

**Dispatch context budget:** This/common contract; C1 collector/result interface; multipath_api_test.go public helper and lifecycle sections; public path/detachment declarations and relevant path state definitions. No endpoint implementation or historical memory campaign is required.

**Slice decision audit:** C1 is a real blocker because this slice deliberately consumes its units/availability/identity record seam, avoiding a parallel collector. Splitting lifecycle phases removes the within-fixture comparison; rejected on merit. Merging ordinary bulk cost with negotiated retention combines distinct behavior owners without necessity; rejected on merit.

**Stop conditions:** Stop if this needs a production owner/interface change, new public bypass, privileged host modification, unbounded fixture language, adjacent slice redesign or an unresolved capability that prevents the promised deliverable. Keep the child open with the concrete blocker; do not declare readiness from a skip.

### C3 — Scoped UDP queue and topology relay

**What it delivers:** Create a narrowly maintained real-UDP relay based on the archived B11 queue design, with explicit disjoint, unequal and shared-bottleneck queue identities, bounded backlog/drop behavior, configured rate/delay, realized per-route delivery records and joined teardown. It is independently consumable through one explicit tuple/topology interface; no QUIC performance campaign or controller comparison is included.

**Existing-work disposition:** New slice on the current default branch; retain the inspected runtime owners. No unmerged implementation branch is a prerequisite.

**Blocked by:** None

**Single owner after merge:** One synchronized relay queue owner decides backlog admission/drop and delivery scheduling. UDP reader/delivery workers report facts and are joined in the existing proven order before output is finalized. The transport under test is not modified.

**Authority completeness:** No new persisted product authority. Constructors, record validation, subprocess exit/cleanup and receipt readback are covered for this verification aid; a receipt cannot open public admission.

**Transitional-seam budget:** None. Named test adapters are maintained platform variants; no duplicate runtime state, temporary production override or double-open product lifetime is permitted.

**Blast radius:** New maintained fixture/relay source and tests under the multipath tooling scope; archived source stays byte-for-byte frozen. Real UDP sockets and relay goroutines add bounded cleanup/queue obligations inside this fixture. Topology is a closed enum/configuration, not a generic graph language. No PF/dummynet, privileges, production scheduler or host traffic changes.

**Artifact classification:** Verification aid plus process/traceability metadata under the common maintained-deliverable contract. Existing shipped behavior and safety enforcement remain unchanged.

**Representation contract:** The common typed/canonical fixture-result contract applies; standard parsers own syntax. Named finite semantic cases receive representative regression coverage; native observations remain example-level.

**Contract closure:** No recursive closure of this verification aid. Its queue/topology/delivery interface and relay observations feed C4's workload and Q1's topology protocol; they are not direct native safety-table witnesses.

**Evidence budget:** The listed semantic cases, one positive per named behavior and one negative per distinct listed failure, terminate development validation. Use the common platform/review limits; no qualification/performance inventory, statistical repetition or extra mutation program is allocated.

**TDD and preservation evidence:** First test representative queue admission/drop arithmetic, distinct versus shared queue identity, unequal rate/delay selection and rejected invalid configuration. Then exercise local UDP routing, realized receipt accounting and cleanup with pending deliveries/reader exit. These tests demonstrate adapter semantics, not timing fidelity at qualification load. Native comparative throughput and relay CPU observations remain Q2 work.

**Dispatch context budget:** This/common contract and archived B11 queue/topology/cleanup/tests at 8c34fbac874adf55f096b6c67d51244160169422, bounded to aggregation_test.go sections cited in the audit. Do not import the archived private activation or Python campaign loop. The new relay interface and tests fit one fresh context.

**Slice decision audit:** No blocker: the relay delivers a real UDP topology without C1 metrics or QUIC admission. This is the justified split from the broad ME work: an independently green adapter precedes its QUIC comparison consumer C4. Further splitting queue arithmetic from UDP lifetime would leave the external seam untested; rejected on merit. Merging C4 is unnecessary and increases concurrency-plus-measurement context; rejected on merit.

**Stop conditions:** Stop if this needs a production owner/interface change, new public bypass, privileged host modification, unbounded fixture language, adjacent slice redesign or an unresolved capability that prevents the promised deliverable. Keep the child open with the concrete blocker; do not declare readiness from a skip.

### C4 — Topology comparison workload and controls

**What it delivers:** Bind the C3 relay to current public QUIC interfaces and C1 metric records for single-path A, single-path B, independent pair, primary/backup and aggregate arms across the three declared topology types, including the shared-bottleneck Reno competitor where fairness is reported. Record useful STREAM/DATAGRAM delivery, receiver gaps/latency, observed relay drops, relay CPU and topology identity separately. Produce executable comparison apparatus; collect no native performance campaign here.

**Existing-work disposition:** New slice on the current default branch; retain the inspected runtime owners. No unmerged implementation branch is a prerequisite.

**Blocked by:** C1, C3

**Single owner after merge:** C3 owns relay queues; public transport owners retain path/controller decisions; the comparison fixture owns matched demand, arm selection and useful-byte/phase accounting; C1 owns metric representation. No requested topology or sender counter substitutes for realized delivery.

**Authority completeness:** No new persisted product authority. Constructors, record validation, subprocess exit/cleanup and receipt readback are covered for this verification aid; a receipt cannot open public admission.

**Transitional-seam budget:** None. Named test adapters are maintained platform variants; no duplicate runtime state, temporary production override or double-open product lifetime is permitted.

**Blast radius:** New bounded comparison workload/driver plus immediate relay/metric integration. Preserve experimental uncoupled/no-general-fairness limitations and current public Linux support. Linux functional controls and Darwin build/refusal remain distinct. No retired experiment loop, fixed historical run order, optimizer or production metric source is revived.

**Artifact classification:** Verification aid plus process/traceability metadata under the common maintained-deliverable contract. Existing shipped behavior and safety enforcement remain unchanged.

**Representation contract:** The common typed/canonical fixture-result contract applies; standard parsers own syntax. Named finite semantic cases receive representative regression coverage; native observations remain example-level.

**Contract closure:** No recursive closure of this verification aid. Its matched topology/control workload records feed Q1's comparison protocol and Q2's cost/performance disposition; functional apparatus controls do not replace the table's independent peer receipt witness.

**Evidence budget:** The listed semantic cases, one positive per named behavior and one negative per distinct listed failure, terminate development validation. Use the common platform/review limits; no qualification/performance inventory, statistical repetition or extra mutation program is allocated.

**TDD and preservation evidence:** First exercise exact arm/controller selection, invalid policy refusal, missing arm/metric/topology identity, matched demand and receiver-versus-sender accounting. Use the real public Linux interfaces for a bounded functional comparison smoke and ensure all child processes/relays join on failure. No throughput gain, statistical confidence or fairness acceptance follows from that smoke; Q1 selects finite native collection and comparable criteria.

**Dispatch context budget:** This/common contract, C1 result/collector and C3 relay interfaces, current public path/controller APIs, B11 metric/control definitions only and the new comparison diff. Exclude the full historical BBR program and retired campaign scripts.

**Slice decision audit:** Both blockers are real consumed interfaces: metrics/identity from C1 and realized UDP topology from C3. P1/P2/C2 are not prerequisites. Splitting the arm definitions into separate PRs leaves no complete matched comparison; rejected on merit. Merging the independently useful C3 relay increases context without necessity; rejected on merit.

**Stop conditions:** Stop if this needs a production owner/interface change, new public bypass, privileged host modification, unbounded fixture language, adjacent slice redesign or an unresolved capability that prevents the promised deliverable. Keep the child open with the concrete blocker; do not declare readiness from a skip.

### Q1 — Bind the concrete execution protocol and venue

**What it delivers:** One reviewed protocol/receipt document binds the merged apparatus interfaces to exact candidate-selection rules, executable commands, native venue/access, installed Go toolchains, build variants, admitted-release applicability, collection inventory, comparison criteria, attribution/contamination rules and continuing coverage. Present that concrete package for the owner's already-required execution/privilege/maintained-aid decisions; record the exact approval before completing this child. No qualification campaign executes in Q1. Bind E2's selected focused Darwin race cases and the existing BBR per-path sampling/recovery/protected-member evidence to finite commands and expected observations. Place the first approved actual Go write-wait observation early in Q2; record its receipt fields, fixture owner and missing-trigger repair/reapproval route.

**Existing-work disposition:** New slice on the current default branch; retain the inspected runtime owners. No unmerged implementation branch is a prerequisite.

**Blocked by:** E2, E3, P1, P2, C2, C4

**Single owner after merge:** The protocol owns the declared finite collection scope and identity map; the user/authorized maintainer owns venue access, privileged sampling, operational inventory and support exceptions. Fixture results supply facts. Neither a runner nor a readiness label grants execution authority.

**Authority completeness:** Process metadata only. Record exact approved document revision, commands, venue/toolchain bindings and privilege/CI decisions together; do not publish a partially approved inventory as executable. Missing approval keeps this child open and Q2 blocked.

**Transitional-seam budget:** None. The protocol is the single collection contract consumed by Q2; its current status/pointers are updated in place, with chronology in linked discussion.

**Blast radius:** Documentation and existing command/identity validation only; no installation, privileged sampler launch, cloud reservation, runtime code, budget reset or live runner registration. Exact platform/toolchain/build cross-products must be justified by semantic differences, not multiplied for confidence.

**Artifact classification:** Process/traceability metadata. Selected future CI/fixture aids require explicit maintained-blocker approval with payoff, finite profile/domain, transport integration/interop owner and equivalent-replacement/feature-removal retirement. Unselected diagnostic aids remain nonblocking.

**Representation contract:** Finite named command/case/identity table in the protocol, standard parsed tool outputs and exact owner decision receipt. Example-level qualification; no universal kernel/fairness claim or broad handwritten manifest grammar.

**Contract closure:** Not triggered for protocol metadata; it references the existing safety/activation semantic rows and fixes their executable inventory without recursively proving the tools.

**Evidence budget:** One read-only inventory/command correspondence audit and owner decision on the concrete table. No native attempts or performance samples. Preserve existing numerical cost criteria and deadline tolerance; any new exception or repeated-run design needs the explicit owner decision. One initial review plus at most one replacement.

**TDD and preservation evidence:** No code TDD. Cross-check each required native semantic row against an available command, expected identity, output field and missing-evidence disposition. Resolve Go 1.26.11/1.27.4 applicability, both private-syscall modes, earlier/later Darwin 27 coverage, real poller versus pressure observations, BBR metrics, shared-bottleneck controls and continuing runner identity. A missing tool, venue or observation source is a concrete blocker, not a waived row. Trace the BBR coverage row to multipath_bbr_test.go, bbr_native_credit_test.go, bbr_native_large_test.go, BBR member-completion and native_software_protection_test.go evidence; distinguish reusable deterministic checks from native protected-buffer/transfer/migration/close observations. Bind focused endpoint race results separately from optional continuing CI selection. Include the negotiated mixed-bulk native case and P1's discovered matrix command. Bind all required rows in the [accepted native semantic map](2026-11-18-macos-multipath-plan.md#native-semantic-evidence-map), including the named family/packet-info/ECN controls and native migration/rebinding observations. Keep portable stale-feedback assertions distinct from native transition evidence; choose one exact qualifying C2 lifecycle state consistently for each matched memory comparison.

**Dispatch context budget:** This/common contract; current readiness interface/limitation receipts from the six leaf blockers; the settled target/semantic tables; current host/toolchain facts and owner decision. No complete fixture source, historical performance runs or prior plan versions. The task is protocol binding, not reimplementation. Include the focused existing BBR test interfaces named in the coverage row only to bind commands/observations, not to redesign their owners.

**Slice decision audit:** All six blockers are necessary because only their completed methods can supply concrete commands and known evidence limits. Authoring a speculative protocol first would reintroduce re-derivation. Merging Q2 would mix unresolved operational authority with implementation/collection; rejected on merit. Further splitting inventory from approval yields an incomplete execution contract; rejected on merit.

**Stop conditions:** Keep the child open if venue/toolchain/privilege/continuing-coverage authority or concrete finite scope is unresolved. Escalate only the concrete required decision. A proposed narrower public profile, changed runtime owner, relaxed bound or new product dependency requires owner approval and scoped re-audit before Q2.

### Q2 — Qualify and activate the approved public profile

**What it delivers:** One unmerged candidate changes the common capability helper to the approved Darwin domain while preserving Linux amd64 and common controller/path checks; updates public comments/errors and independent root/HTTP3 applicability; executes Q1's exact native protocol on that candidate; and merges acceptance-expecting tests, selected continuing CI, support record, README/usage and new release entry with activation. All three approved controller/policy combinations must qualify; missing/unacceptable evidence leaves the branch unmerged.

**Existing-work disposition:** New slice on the current default branch; retain the inspected runtime owners. No unmerged implementation branch is a prerequisite.

**Blocked by:** Q1

**Single owner after merge:** The common platform helper owns platform capability; existing transport admission owns configuration/socket/controller policy; existing endpoint/connection owners retain runtime behavior. Qualification records inform the maintainer's support decision and do not become a runtime side channel.

**Authority completeness:** Cover explicit grants, client/server constructors and server-selected configurations before they can advertise or attach an admitted profile. Public fallback/refusal, supported/unsupported table cases and root/HTTP3 tests ship with the change. No persisted product authority or restart format is added.

**Transitional-seam budget:** None after merge. No hidden bypass, environment switch, temporary broad Darwin predicate or split public-support claim. The exact candidate remains a feature branch until evidence is accepted.

**Blast radius:** A small platform helper/build constraints, public support text/tests, selected CI configuration and support metadata. It changes public refusal only for the selected Darwin domain. Endpoint timing, buffering, scheduling, congestion algorithms and private-syscall allowlists are unchanged. Any necessary runtime repair is separately scoped before it can expand this PR.

**Artifact classification:** Capability/admission change is shipped behavior and required support enforcement; tests/selected CI are verification aids with Q1's explicit maintained scope; receipts/support/release text are metadata. Frozen evidence remains untouched.

**Representation contract:** Typed GOOS/GOARCH/kernel result partition and existing configuration/socket validators own the finite public domain. Kernel parsing remains with the existing platform helper. Table coverage is complete for declared semantic partitions; native behavior/performance remains example-level qualification, never a guarantee over all kernel interleavings.

**Contract closure:** The common activation coverage argument applies at each actual input owner: platform eligibility at explicit grants and enabled admission; duration/exact-socket/grant ownership at explicit and library-owned socket setup; applicable socket conflicts at admission; enabled controller/policy/version checks at constructor and server-selected Config admission. Explicit grants do not take Config inputs. Tests use independent expectations, including granted ordinary QUIC v2 success. Endpoint and BBR safety evidence retains its existing owners and Q1-bound methods. No extra mutation or parser-conformance program.

**Evidence budget:** Exactly the owner-approved Q1 protocol and existing repository CI inventory, plus the named local predicate/configuration tests. One initial review and at most one replacement. No spare attempts, statistical repetitions or platform extensions are inferred; diagnose failures before a legitimate rerun. New required evidence outside the protocol returns for a decision.

**TDD and preservation evidence:** First add independent expected-platform/controller/socket tables that fail for the selected Darwin domain while preserving Linux success and nonselected/iOS/unknown-major refusals; exercise constructor and explicit-grant paths and HTTP/3 applicability. Preserve setter order/clones, v2 refusal, ordinary fallback and unsupported Reno aggregation. Run Q1 native endpoint, lifecycle, both-role Reno/BBR peer, fresh aggregate receipt, ordinary cost, lifecycle memory and topology comparisons on the real exact candidate. Publish missing/negative evidence and attribution honestly; Linux observations do not qualify Darwin. Record Q1's focused Darwin endpoint race results and BBR-specific sampling/recovery/native protected-member evidence on the same activation candidate. Run the approved first poller observation early; absent evidence blocks activation and routes trigger diagnosis/repair to E2's owner, with Q1 reapproval of protocol changes before rerun. Preserve granted ordinary QUIC v2 while refusing enabled multipath v2. Record the Q1-bound IPv4-only, IPv6-only, dual-stack mapped/native, packet-info/interface and ECN results plus the ordinary ECN-disabled control; missing required family evidence blocks activation. Preserve the portable late-old-tuple feedback assertions and record the separately bound native migration/survivor and both-role same-ID rebinding observations.

**Dispatch context budget:** This/common contract, Q1 approved protocol and readiness interfaces, current multipath_api.go/platform helper/public test and HTTP3 applicability sections, selected CI files and user-facing support docs. Do not load all fixture internals or historical campaign reports. Implementation is only the gate/tests/publication delta plus finite execution; discovering a runtime repair invalidates this context claim.

**Slice decision audit:** Q1 is a genuine authority and executable-evidence dependency, transitively binding all readiness methods. Splitting platform activation from evidence/acceptance tests/support publication creates an unsafe intermediate claim; rejected on merit. Splitting by controller contradicts the owner-approved target; revisit only on an evidence-backed owner decision. Additional prefactoring is unnecessary unless current code changes invalidate the small common-helper design.

**Stop conditions:** Stop on absent native poller evidence, unapproved/failed cost disposition, unavailable venue or CI scope, unassessed admitted release/toolchain, changed peer pins, new production owner/interface, need for private batching, or inability to retain this one-PR boundary. Do not silently narrow the profile or weaken 20 ms tolerance. Use scoped re-audit only within the accepted representation/outcome/PR boundary; otherwise return to architecture-handoff or owner decision.

## Acceptance criteria and validation gates

- Each readiness child delivers its stated executable interface plus its finite development evidence; neither skipped work nor a recorded blocker completes a child.
- The preserved three-combination profile and two-path limit remain explicit; public Darwin admission stays closed until Q2's exact candidate meets Q1.
- Q1 records concrete tools, identity, authority and finite execution scope before Q2 is ready; incomplete or unavailable evidence never becomes support by inference.
- Q2 merges admission, acceptance tests, selected continuing coverage and support publication together, preserving ordinary/default-off, Linux, Intel/other-platform refusal and frozen evidence.
- Every child has one plan contract, one issue, one intended PR and one OmniFocus task; parent/tracker/task notes remain pointers. Commit-specific certification is separate from administrative readiness.

These criteria use the finite domains and owners defined above. "Every" means the eleven declared children or named semantic partitions, not an open parser/platform universe. Terminate with the named representative evidence and the shared review allowance. Do not recursively expand harness obligations.

For Go changes, run the affected packages and `go vet` on them, plus `go mod tidy -diff` when relevant, and the justified selected race cases. Test commands are fixed in each execution preflight from the names in its accepted contract and current files; do not run a whole historical campaign to satisfy a name match. For Python/C adapters, run their finite unit/compile/ordinary-smoke checks and existing callers' preserved Linux controls. Build both selected Darwin architecture/toolchain modes only where the accepted profile or changed adapter makes them semantic distinctions; Q1 owns qualification execution cells.

## Operating discipline

The shared review-loop and contract-closure baselines supplied by `$implement-architecture-slice` govern every child, composed with [the repository execution overlay](../REVIEW-LOOP.md); use the shared design-cost reference for scoped re-audit. No repository baseline copy or additional CI portfolio is created. Their representation/artifact gates, finite evidence/review limits, semantic-family closure, precise invariant-and-owner repeated-root comparison, review-and-verification-aware approach stops and diagnosis-before-rerun policy apply. A common file or lifecycle topic alone is not a repeated root.

For this documentation handoff, finish the slice audit before any commit/publication, then the Standards/Spec preparation and full configured RAS review through the installed wrapper skills. Certify the clean exact pushed head, added relative links, source correspondence and graph identity/dependencies; observe successful applicable hosted checks, mark ready and squash merge with head matching. No Go or native campaign execution is part of this handoff. Publish issues and mirrors only after verifying the exact default-branch plan commit.

For each future child, its product PR owns the plan/index completion and successor-frontier transition before review. Complete review and exact-head local certification, observe applicable hosted checks on that same head, confirm base freshness and merge. The docs-only multipath job exclusion does not apply to implementation PRs. Record the dev-journal completion account only after merge, then reconcile issue dependencies/frontier and complete the matching OmniFocus task. Do not make a routine third PR for status or mirror a plan SHA into OmniFocus.

A child is dispatchable only when its real blockers and any explicit authority prerequisites are satisfied. Parent/track issues are not implementation requests. The handoff reports the frontier; the operator chooses dispatch. This publication runs no implementation agent.
