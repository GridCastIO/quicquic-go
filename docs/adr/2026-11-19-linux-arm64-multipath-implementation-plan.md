# Linux ARM64 multipath implementation plan

**Date:** 2026-11-19. **Identity:** MP-ARM, track 1 of 1 in MP-ARM-20261119. **Status:** Accepted handoff; not implemented. **Depends on:** Selected shared tooling children from the macOS program, listed below; no macOS activation or support decision dependency. **Normative scope:** Current outcomes, invariants, boundaries, acceptance evidence, blockers and stop conditions. **Audit history:** [Source and slice audit](../audits/2026-11-19-linux-arm64-handoff/README.md). **Program:** [Index](2026-11-19-linux-arm64-multipath-program.md).

## Goal and settled profile

Make the existing Linux native endpoint and public multipath profile usable on native Linux ARM64 without a second backend, scheduler or capability owner. This packages the accepted full-parity outcome of [planning issue #1395](https://github.com/GridCastIO/quicquic-go/issues/1395) and [PR #1481](https://github.com/GridCastIO/quicquic-go/pull/1481). The [target/evidence plan](2026-11-19-linux-arm64-multipath-plan.md) supplies settled context; this document replaces its broad A0–A4 outlines with executable child contracts. The handoff authorizes documentation and tracking, not dispatch or native qualification collection.

| Surface | Accepted outcome and preserved boundary |
| --- | --- |
| Public profile | Experimental opt-in draft-21 multipath, QUIC v1, one or two paths including path zero; default disabled. Reno primary/backup remains default; BBRv3 primary/backup and BBRv3 aggregate are both required and experimental. No Reno aggregate or enabled QUIC v2. |
| Aggregate policy | Existing uncoupled paced byte round-robin, explicit local activation, backup exclusion and PTO precedence. Both-active useful STREAM and fresh DATAGRAM receipt are required; no general gain or fairness guarantee. |
| Socket authority | Exact unconnected *net.UDPConn; exclusive write/write-deadline grant before initialization; no read-deadline or caller-close transfer. Preserve library-owned socket grants and unsupported managed/external/fixed-peer/jumbo/QoS combinations. |
| Lifetime | Request duration 1 ms–1 s, 100 ms owned default, existing 20 ms supported-environment tolerance and resource limits. Storage remains borrowed through native return and final deadline reset. Connection-specific transport detachment is distinct from transport-wide grant return after close/join. |
| Families and ordinary traffic | IPv4-only, IPv6-only, dual-stack mapped/native delivery, packet info/interface, ECN, scalar/software segmentation and available offloads. Preserve default-off/unnegotiated ordinary QUIC v1/v2, HTTP/3 and granted ordinary traffic. |
| Initial evidence domain | Native little-endian Linux ARM64, proposed Ubuntu 24.04.4 Lima vz guest on Apple M4 Max, kernel 6.8.0-142-generic, Go 1.26.11 and 1.27.4. A0 binds actual prepared identities; Q1 binds their finite applicability. Neither emulation nor cross-builds establish native support. |

Retain [endpoint ownership](2026-10-24-multipath-endpoint-plan.md), [Reno support/cost criteria](2026-10-24-multipath-reno-plan.md), [BBR policy](2026-10-24-multipath-bbr-plan.md), [packet-emission ownership](0004-packet-emission-ownership.md), root [glossary](../../GLOSSARY.md) and [maintained-code conventions](../agents/conventions.md). Completed [multipath program #646](https://github.com/GridCastIO/quicquic-go/issues/646) and [BBR continuation #1374](https://github.com/GridCastIO/quicquic-go/issues/1374) stay closed. No new domain term or numbered ADR is needed.

## Current shape and decisions

Source facts below are verified at `38338dc8a9fe010a5a26e5fac7992f7eb137f11a`; line anchors identify that source, not a future branch. Historical receipts and candidate identities stay in the audit.

| Verified owner/source | Consequence for the design |
| --- | --- |
| [multipath_api.go:101](../../multipath_api.go#L101), [multipath_api.go:118](../../multipath_api.go#L118), [multipath_api.go:125](../../multipath_api.go#L125) | Explicit grants and enabled constructor/server-selected admission share the platform predicate. Change that owner only in Q2. Keep socket/duration checks at grant installation and Config policy/version checks at admission. |
| [native_transport.go:25](../../native_transport.go#L25), [native_transport.go:97](../../native_transport.go#L97) | Existing Linux build already covers ARM64; one exact-socket registry, endpoint and join own authority. No ARM64 backend gap has been demonstrated. |
| [multipath_api_test.go:28](../../multipath_api_test.go#L28), [multipath_api_test.go:115](../../multipath_api_test.go#L115), [http3/multipath_test.go:21](../../http3/multipath_test.go#L21) | Root test selection currently reads the production constant, while HTTP/3 has a test-owned predicate. Q2 must make root expectations independent so a closed ARM64 gate cannot hide behind skips. |
| [native_qualification_test.go:1](../../native_qualification_test.go#L1), [native_qualification.py:125](../../interop/multipath/native_qualification.py#L125), [native_qualification.py:137](../../interop/multipath/native_qualification.py#L137) | Fixture/driver assume amd64. Driver selects versioned GOTOOLCHAIN and hashes selected GOROOT/poller sources; E1 must bind those to A0's exact prepared distribution. Six classes and two pins are existing method inventory, not a new campaign allowance. |
| [Dockerfile:3](../../interop/multipath/Dockerfile#L3), [Dockerfile:7](../../interop/multipath/Dockerfile#L7), [picoquic_control_test.go:34](../../integrationtests/self/picoquic_control_test.go#L34), [multipath_picoquic_matrix_test.go:1](../../multipath_picoquic_matrix_test.go#L1) | Image, archive checksum, ordinary-control assertion and root matrix tags need explicit ARM64 support. Preserve picoquic fbd46d9a1f54ebf9397f2ee6355b5019ab379fb7 and PicoTLS e446233b4100ebcdec60901c05bfb7f4cd369c5d. |
| [matrixUsefulTransfer:391](../../multipath_picoquic_matrix_test.go#L391), [peer callback:217](../../interop/multipath/peer.c#L217) | Existing DATAGRAMs precede simultaneous activation. Actual callback ingress and payload-requested echo path are different facts; P2 owns a fresh phase witness with both-path eligibility. |
| [ordinary_cost_test.go:90](../../ordinary_cost_test.go#L90), [ordinary_cost_test.go:312](../../ordinary_cost_test.go#L312), [ordinary_cost.py:47](../../interop/multipath/ordinary_cost.py#L47), [ordinary_cost.py:481](../../interop/multipath/ordinary_cost.py#L481) | Current tooling is amd64-specific, limits BBR to pressure diagnostics, uses CPU masks beyond the 12-vCPU guest, and uses the public grant. C1 needs explicit architecture/controller/placement and ordinary-only private test setup without bypassing negotiated admission. |
| [ordinary_cost.py:144](../../interop/multipath/ordinary_cost.py#L144), [ordinary_cost_test.go:783](../../ordinary_cost_test.go#L783) | Mixed bulk requires a real negotiated two-path connection. ARM64 readiness cannot replace it with ordinary background traffic; native execution waits for Q2. |
| [unit.yml](../../.github/workflows/unit.yml), [multipath-interop.yml](../../.github/workflows/multipath-interop.yml) | Current pins are 1.26.11/1.27.4. Existing ready-PR peer coverage is amd64 Reno, sixteen role/scenario cases plus separate zero vectors. Q1 selects continuing ARM64 scope; it is not an automatic doubled matrix. |

The proposed guest has 12 vCPUs and 80 GiB; installed Go 1.27.0 is neither pin and is absent from its shell PATH. Tool presence does not prove strace/namespace/nftables permission. Its virtual eth0 reports UDP segmentation disabled; loopback flags are promising but actual sockets need witnesses. Docker Desktop's LinuxKit kernel is a separate venue. A0 records image/configuration identity and isolated preparation needs; no global guest replacement, package change, CPU reservation or host-process termination follows from this plan. Shared background activity is normal; distinguish host performance/efficiency-core contention when observable rather than infer contamination from load average or vCPU numbers.

**Owner's design:** Retain endpoint-owned deadlines/borrowing, connection-owned path/protocol consequences, peer-owned ingress facts and collector-owned measurements. Parameterize existing Linux fixtures at real architecture/placement seams; do not build an ARM64 runtime adapter beside the owner. The contained test adapters add identity and cleanup obligations only. Moving observations into production would expand the runtime interface without an accepted need; do not do this. **Revisit:** a separately accepted production observability requirement.

**Rejected alternatives — do not do these:** A separate ARM64 endpoint duplicates lifetime policy without evidence; revisit only if native evidence proves the current owner cannot express a platform requirement. Early Reno-only support violates full parity; revisit only on an explicit evidence-backed product decision. A production admission bypass or fake OS identity invalidates qualification; none: rejected on merit. Reusing retired B11 collectors as maintained dependencies violates frozen-evidence ownership; consume the separately scoped shared relay/comparison owners. Revisit: none: rejected on merit. Emulated runs and historical amd64 exceptions cannot establish ARM64 support or tolerances; none: rejected on merit. A blanket A0-before-peer-build ordering has no code necessity: P1 consumes its shared builder interface and own native container inputs; none: rejected on merit. Do not copy or rebaseline the separate macOS program. Revisit only on an explicit scoped request to change that program. Consume its selected shared owners after their accepted contracts merge; an open PR is not an established baseline. A topology/owner change beyond this contract requires scoped re-audit.

**Non-goals:** New runtime APIs, protocol/schema changes, controller/scheduler tuning, higher path counts, hardware-NIC performance claims, arbitrary ARM kernels/CPUs, physical-host reservations, new peer pins, full BBR qualification, blanket recurring CI or statistical campaign allowances. Untraced effects are actual native trigger/offload capability, shared-host scheduling attribution and measured costs; they remain explicit later evidence obligations, never silently accepted runtime changes.

## Shared owners and slice graph

The shared contracts are already published at default-branch plan commit `24cd8a12dbf63bdd8bfbffdcfc07ca987739e465`. Their implementation outputs are prerequisites, not established baselines. Consume only the actual merged interface after its owner has completed review/certification/CI and the accepted contract is verified. A closed issue or a draft PR's completion row alone is insufficient. This scoped handoff changes no macOS issue, label, plan or task, and creates no duplicate implementation or no-op adoption child.

| Shared outcome | Existing sole child/owner | ARM use |
| --- | --- | --- |
| Peer execution profiles and native identity | [MP-MAC-P1 (#1488)](https://github.com/GridCastIO/quicquic-go/issues/1488), [accepted P1 contract](https://github.com/GridCastIO/quicquic-go/blob/24cd8a12dbf63bdd8bfbffdcfc07ca987739e465/docs/adr/2026-11-19-macos-multipath-implementation-plan.md#p1--native-pinned-peer-build-and-ordinary-control) | ARM P1 extends this one dispatcher/identity/helper interface with linux/arm64; it preserves existing linux/amd64 and darwin/arm64 behavior. |
| Fresh both-active ingress witness | [MP-MAC-P2 (#1489)](https://github.com/GridCastIO/quicquic-go/issues/1489), [accepted P2 contract](https://github.com/GridCastIO/quicquic-go/blob/24cd8a12dbf63bdd8bfbffdcfc07ca987739e465/docs/adr/2026-11-19-macos-multipath-implementation-plan.md#p2--fresh-aggregate-datagram-ingress-witness) | Q1 binds its actual peer-callback ingress semantics for native ARM64 execution; no ARM P2 implementation is created. |
| Shared workloads and metric representation | [MP-MAC-C1 (#1490)](https://github.com/GridCastIO/quicquic-go/issues/1490), [accepted C1 contract](https://github.com/GridCastIO/quicquic-go/blob/24cd8a12dbf63bdd8bfbffdcfc07ca987739e465/docs/adr/2026-11-19-macos-multipath-implementation-plan.md#c1--matched-ordinary-workloads-and-native-metric-records) | ARM C1 extends this one Linux ARM64 profile/CPU-placement seam through the actual merged ordinary, lifecycle and comparison consumers instead of rebuilding them. |
| Negotiated lifecycle memory | [MP-MAC-C2 (#1491)](https://github.com/GridCastIO/quicquic-go/issues/1491), [accepted C2 contract](https://github.com/GridCastIO/quicquic-go/blob/24cd8a12dbf63bdd8bfbffdcfc07ca987739e465/docs/adr/2026-11-19-macos-multipath-implementation-plan.md#c2--negotiated-lifecycle-memory-observation) | ARM C1 binds Linux ARM64 selection/identity/placement to the actual consumer; Q1 selects its three observed public phases. No second collector or ARM C2 child. |
| Portable UDP topology relay | [MP-MAC-C3 (#1492)](https://github.com/GridCastIO/quicquic-go/issues/1492), [accepted C3 contract](https://github.com/GridCastIO/quicquic-go/blob/24cd8a12dbf63bdd8bfbffdcfc07ca987739e465/docs/adr/2026-11-19-macos-multipath-implementation-plan.md#c3--scoped-udp-queue-and-topology-relay) | Shared C4 consumes it; this is a transitive prerequisite, not another ARM relay/task or direct convenience edge. |
| Matched topology comparison | [MP-MAC-C4 (#1493)](https://github.com/GridCastIO/quicquic-go/issues/1493), [accepted C4 contract](https://github.com/GridCastIO/quicquic-go/blob/24cd8a12dbf63bdd8bfbffdcfc07ca987739e465/docs/adr/2026-11-19-macos-multipath-implementation-plan.md#c4--topology-comparison-workload-and-controls) | ARM C1 binds the actual consumer's Linux ARM64 selection/identity/placement. Q1 consumes its public workload and shared metrics/relay, selecting ARM's accepted A/B/C/E arms and shared-bottleneck competitor. A richer tool does not add primary/backup collection to ARM's inventory. |

| ARM slice | State/disposition | End-to-end outcome | Blocked by | Temporary seam removed |
| --- | --- | --- | --- | --- |
| A0 | New; frontier | Prepared native venue/toolchain identities and prerequisite receipt | None | None |
| E1 | New; blocked | Native ARM64 endpoint fixture and exact build/case accounting | A0 | None |
| P1 | New ARM delta; blocked | Native Linux ARM64 peer image/profile and ordinary controls | Shared P1 #1488 | None |
| C1 | New ARM delta; blocked | Linux ARM64 profile/identity/placement through shared measurement consumers | A0, shared C2 #1491, C4 #1493 | None |
| Q1 | New; blocked | Concrete approved ARM64 execution protocol | E1, P1, C1, shared P2 #1489 | None |
| Q2 | New; blocked | Native qualification and complete support decision | Q1 | None |

A0 is the ARM-owned frontier. After A0, E1 can run while shared tooling proceeds. ARM P1 becomes independent of E1/C1 once shared P1 merges; ARM C1 follows A0 and the final shared lifecycle/comparison consumers; their shared metrics and relay dependencies are transitive. Q1 consumes the three ARM readiness outputs plus shared ingress P2; C1 supplies the verified consumer applicability. These are consumed interfaces/authority, not file-order dependencies. None waits for macOS public activation. No integration branch is needed.

For shared ingress, the independent peer receive callback must bind each fresh offer nonce/sequence to its actual ingress path in both roles, with both paths live/active during the bounded phase. A Go receive trace is supporting counter evidence only: echoes returning over two paths cannot turn one-path offer ingress into a pass. The existing one-path negative covers that distinction. Five shared fixture cases and role wiring remain readiness evidence; the first planned live ARM aggregate observation belongs to Q2, an explicit untraced live-integration effect until then.

For shared lifecycle memory, negotiated idle records live path zero and absence of the later backup in PathsV1. Validated-backup and post-retirement samples identify the same subsequently opened backup ID and exact StateV1.Lifecycle; reject retiring and distinguish retained/closed, selecting one consistent comparable third state in Q1. No absent backup handle is invented. For shared comparison, C4 supplies matched records; Q1 owns the selected paired calculation and verifies its valid-negative versus invalid-comparator dispositions. Missing controls or candidate failure cannot be filtered into a pass. C1 owns the finite ARM64 selection/identity/placement adaptation through the actual merged lifecycle/comparison consumers. Q1 inspects those accepted interfaces; an unfulfilled contract or a needed lifecycle/topology/collector redesign remains a concrete blocker/re-audit, never presumed successful or duplicated speculatively.

## Common contract for every slice

Every slice below includes this common contract, the settled profile and the specific fields beneath its heading. One slice is one intended PR and one fresh agent context. Existing-work disposition is new ARM-specific work on the merged baseline plus explicitly selected, still-unmerged shared dependencies; [PR #1295](https://github.com/GridCastIO/quicquic-go/pull/1295) is excluded as unselected historical work, with the source/diff/closure assessment in the audit. Do not cherry-pick its scalar adapter, reopen its spent allowance or make it a dependency.

Readiness tools are verification aids; plans, preparation receipts and qualification reports are process/traceability metadata. Existing runtime behavior and required safety enforcement stay unchanged until Q2. The narrowly scoped aids have transport test/interop maintainership, payoff in reproducible named native regression observations, and domain limited to these platforms/toolchains/scenarios. Ordinary maintained fixture extensions retire with equivalent replacement or support removal; any ARM-specific finite measurement entrypoints retire after the definitive ARM64 support decision, archiving raw evidence, unless the owner explicitly selects continued maintenance in Q1. Shared tools remain maintained as long as their owning support contract requires, even after its implementation program completes; ARM64 has no authority to retire them. Q1 must record explicit maintained-blocker approval, payoff, domain, owner and retirement for selected new continuing CI aids. Unapproved ancillary aids cannot block shipped behavior by reviewer demand.

Representation owners are typed Go configurations/requests/results, existing wire parsers, standard JSON parsers, exact emitted diagnostic records and the named fixture's semantic validator. Receipt accounting guarantees a canonical subset of explicit case/identity/status fields; native execution is example-level evidence. No handwritten parser claims universal external-language or platform coverage. Unknown identity, missing/duplicate/skipped required cases and malformed owned records cannot count as a pass. No receipt becomes runtime authority, and no new persisted product fact or restart format is introduced.

The common authority-completeness obligation for a changed verification aid is to keep its constructor, record validation, process/socket cleanup and readback coherent in the same PR; it creates no destructive product consumer. The transitional-seam budget is zero new temporary runtime representations, mutation paths, state mirrors or double-open lifetimes. Named architecture adapters are supported variants, not temporary second owners. A discovered runtime seam returns for re-audit, never silently becomes Q2 cleanup.

Development evidence terminates at one representative positive per named behavior and one negative per materially distinct named failure/owner, plus the explicitly named bounded build or smoke controls. These are interface tests, not a qualification/performance campaign. No statistical repeats, historical campaign loops, extra platform cross-products, privileged captures or repeat-until-pass behavior are authorized. At most one central guard mutation is available only when needed to discriminate inherited coverage; none is required by default. Each PR receives one initial review and at most one replacement under the shared policy. Operational entrypoints remain opt-in by build tag/CLI mode so ordinary tests do not launch them. Q1 owns the exact later collection inventory and authority.

Adapter/accounting tests catch selection, units, identity and cleanup but miss OS behavior. Real socket/ordinary-handshake smoke catches adapter integration but does not qualify timing, congestion or performance. Existing amd64 public controls exercise negotiated behavior without authorizing ARM64 admission. Q2's exact-candidate observations cover only the approved native cases. Preserve these distinctions in receipts. A skip or blocker record never completes a promised executable method.

Each dispatch receives the common contract, exact slice, referenced invariants and source interfaces, graph and only the slice's relevant unresolved history plus the governing diff if the contract changed. Do not load full old plans or campaigns. Source lists bound the context, not blanket edit authority. Runtime repairs, adjacent-owner redesign, new maintained frameworks or inability to finish implementation/fixes/verification in that context require re-audit/splitting.

## Native safety and activation coverage argument

The accepted endpoint borrow/lifetime invariant has material authority/storage consequences across independently reachable states; public admission likewise spans distinct entrypoints. Existing runtime owners remain authoritative. This table supplies the bounded semantic census for E1/Q1/Q2, without recursive closure of verification aids. Go/wire representations remain with their existing typed validators/parsers; native observations are example-level. No new repeated-root conclusion is inferred from prior prose findings or a common lifecycle topic.

| Invariant / semantic class | Disposition and enforcement owner | Finite evidence and status |
| --- | --- | --- |
| Exact grant, duplicate/conflicting grant, post-join authority | Grant validator/native writer rejects invalid ownership and returns authority only after actual join | Existing grant/stop tests; E1 build/fixture binding; Q2 native post-join write/deadline control. Planned. |
| Queued expiry versus current native borrow and final reset | Endpoint control expires queued work; writer holds storage through actual call/reset | Existing expiry/member-return/software-protection tests and focused race; six-class native method with actual poller witness, independently untraced timing. Planned. |
| Local timeout/EAGAIN/ENOBUFS versus size/path feedback | Existing completion classifier and connection owner preserve bounded uncertainty and distinguish local backpressure | Current deterministic classification/prefix tests; injected native EAGAIN traversal plus separate actual-pressure observation. Simulated GSO EIO remains labelled. Planned. |
| Software segmentation, GSO/fallback and queued successor | Existing writer preserves one deadline, accepted prefix and suffix status, grouping/yield | E1 current software-group/yield witnesses; Q2 capability-engaged paths and useful delivery. Absent hardware offload is no hardware claim. Planned. |
| Shutdown, captured producers and shared endpoint contention | Endpoint sealing/join and bounded admission owners retain storage/service rules | Native live-close/captured-producer/participant tests, selected race and native contention/progress observation. Planned. |
| Platform eligibility at explicit grant and enabled admission | One capability predicate admits Linux amd64/ARM64 after Q2; other domains retain their then-current accepted outcome | Independent root/HTTP3 expected-platform tables and both entrypoints. No predicate-derived expected success. Planned. |
| Socket/duration versus Config policy/version | Grant installer owns exact socket/duration/ownership; admission owns enabled controller/policy/version and applicable conflicts | Explicit and owned grants, constructor/server-selected Config, setter-order/clone, unsupported controller/Reno aggregate/v2 refusals; granted ordinary v2 remains valid. Planned. |
| IPv4/IPv6/dual-stack, packet info/interface and ECN | Existing socket/ancillary owners preserve delivered metadata and datagram boundaries | Current socket tests plus native scalar/software and available offload witnesses; transport-owned socket for receive coalescing, since write grant alone is no receive-format permission. Planned. |
| Validation, same-ID migration, stale tuple feedback, detachment | Connection/path generation owners fence old feedback; detachment differs from transport-wide join | Portable stale-feedback assertions plus native public migration/survivor transfer and both-role independent same-ID rebinding. Planned. |
| BBR recovery/credit/protected buffers and policy | Existing per-path BBR/recovery and endpoint completion owners retain facts | multipath_bbr_test.go, bbr_native_credit_test.go, bbr_native_large_test.go, software-protection cases, native BBR transfer/migration/close. Reno alone is insufficient. Planned. |
| Both-active aggregate receipt | Scheduler owns eligibility; peer owns actual ingress; witness owns phase acceptance | P2 five semantic fixture cases and Q2 fresh both-role native STREAM/DATAGRAM observations while both paths remain live/active. Planned. |
| Independent interoperability | Public configurations and pinned peer own their protocol representations | Q1 binds eight existing Reno scenarios per role, BBR useful-transfer/abandon-reopen/migration per role for each policy, plus distinct negotiated-zero evidence. Planned. |
| Ordinary/default-off preservation and costs | Existing transport/controller owners unchanged; collectors supply observed facts | Ordinary v1/v2/HTTP3 controls; C1/C2/C4 methods; Q2 controller-matched cost/memory/topology disposition. No transferred amd64 exception. Planned. |

## Implementation slices

### A0 — Bind the native venue and prepared toolchains

**What it delivers:** Produce a reproducible preparation runbook and observed readiness receipt for the proposed native guest: image/configuration/kernel identity, native architecture, exact isolated Go 1.26.11/1.27.4 installation paths/checksums and GOTOOLCHAIN=local identities, available CPU IDs and tool/privilege/capability prerequisites. Prepare only a task-owned tool prefix when authorized; shared guest image/package/runner changes remain in their owning infrastructure workflow. Completion requires guest access and native/image/kernel identity, both prepared compiler distributions with checksums and usable version/build identities, available CPU IDs, required tool presence and authority for any necessary task-owned installation. Missing preparation keeps A0 open. Record tracing-injection, namespace and nftables availability/permission and observed offload information for Q1; undecided authorization for those later operations or unverified offload engagement alone does not block A0.

**Existing-work disposition:** New slice on the merged baseline; retain the existing runtime owners. The common prior-work exclusion and cross-program reuse rule apply.

**Blocked by:** None

**Single owner after merge:** The infrastructure owner owns the guest and access; A0 owns its task-local installation/receipt; Go distributions own compiler/poller identity. It creates no runtime capability decision.

**Authority completeness:** No new persisted product authority or restart format. The common constructor/validation/cleanup/readback contract applies. Receipts cannot open public admission.

**Transitional-seam budget:** None; the common zero-temporary-runtime-seam rule applies. No successor is asked to remove a knowingly incoherent intermediate state.

**Blast radius:** Preparation metadata and isolated tool distribution only; no shared VM replacement, global PATH/package changes, workload execution, host affinity, process termination or CI registration. Keep guest and Docker builder identities distinct; required builder verification and availability belong solely to P1 and cannot block A0 completion.

**Artifact classification:** Process/traceability metadata and task-local tool preparation; no runtime behavior or new maintained verification framework.

**Representation contract:** Exact native uname/OS/package/tool outputs and installed distribution digests, parsed by their normal tools. Example-level environment observation; explicitly record unavailable privileges or offloads. An image label is not a reproducible image digest.

**Contract closure:** Not independently triggered: no changed product authority or runtime invariant. This slice provides finite evidence interfaces to the common coverage argument, without recursively proving the aid.

**Evidence budget:** One read-only identity/prerequisite pass, exact checksums and one local version/build identity check per prepared compiler. No qualification, pressure, tracing capture, benchmark or new harness. Do not perform privileged feasibility operations here. Record existing tracing/namespace/nftables authority or its absence for Q1’s concrete operational decision; this record does not grant permission or establish socket engagement. The common review and non-recursion limits apply.

**TDD and preservation evidence:** No production TDD. Check the runbook against observed installation paths, versioned selection and actual permissions; reject wrong-architecture/compiler identity and missing completion-gating preparation in its finite checklist. Presence of strace/nft is not permission or a real poller witness. Socket/offload feasibility is explicitly carried to E1/Q1 if it requires an operational probe.

**Dispatch context budget:** This/common contract; target plan venue table; native_qualification.py prerequisite/build interface; exact local Lima configuration and tool distributions. No native fixture or historical campaign internals.

**Slice decision audit:** No blockers: preparation is independently useful. Splitting toolchains from their actual venue identity leaves no reproducible native build input; merging E1 mixes infrastructure identity with fixture semantics. Both rejected; none: rejected on merit. A0 does not gate P1’s self-contained native container build or external shared implementation owners.

**Stop conditions:** No guest access or required native/compiler identity, incomplete tool preparation, missing authority for a necessary task-owned installation, non-native execution or required shared infrastructure mutation keeps A0 open for the concrete owner decision. Missing authorization for later tracing/namespace/nftables operations remains a Q1 prerequisite; offload engagement remains later execution evidence. Do not reserve a different host or relabel Docker Desktop as this guest.

### E1 — Adapt the native endpoint fixture and build attribution

**What it delivers:** Extend the existing Linux qualification fixture/driver and its accounting tests to explicit amd64 and ARM64 identities, binding each selected compiler/GOROOT/poller/test binary to A0. Preserve all six existing class definitions plus current software-group/yield witnesses. Select existing family/metadata applicability and focused race commands, with native scalar/private-endpoint smoke; public ARM64 refusal stays unchanged. Final injected traversal and qualification collection belong to Q2.

**Existing-work disposition:** New slice on the merged baseline; retain the existing runtime owners. The common prior-work exclusion and cross-program reuse rule apply.

**Blocked by:** A0

**Single owner after merge:** Existing endpoint control owns queue expiry; sole writer owns native borrow/deadline/reset; connection owns protocol consequences. The driver owns exact case accounting and child cleanup; it observes facts and never grants public support.

**Authority completeness:** No new persisted product authority or restart format. The common constructor/validation/cleanup/readback contract applies. Receipts cannot open public admission.

**Transitional-seam budget:** None; the common zero-temporary-runtime-seam rule applies. No successor is asked to remove a knowingly incoherent intermediate state.

**Blast radius:** native_qualification_test.go, native_qualification.py/test_native_qualification.py and narrow fixture applicability only. Inspect ARM64 syscall/cmsg alignment and selected Go poller source. Do not create a new writer, production observer or architecture wildcard. Actual injected traversal, pressure and timing remain unqualified.

**Artifact classification:** Verification aids plus process/traceability metadata, with the common payoff/domain/owner/retirement policy; existing shipped behavior and safety enforcement remain unchanged.

**Representation contract:** Common typed/canonical record contract, explicit Linux architecture enum, case IDs and toolchain identities. strace text is used only for its emitted narrow method witnesses; no broad syscall-language guarantee. Unrecognized evidence fails qualification.

**Contract closure:** The common bounded native safety/admission coverage argument applies at the named enforcement owners; no recursive harness closure.

**Evidence budget:** Existing Python accounting tests plus new representative architecture/identity/missing/duplicate/skip failures, tagged builds on both pins, one native scalar socket smoke per required family and selected deterministic/race tests. No six-class-by-two-pin campaign or native fault injection is commissioned here. The common review and non-recursion limits apply.

**TDD and preservation evidence:** First fail wrong native/target identity, mismatched selected GOROOT, missing/skipped cases and cleanup errors; characterize TestNativeIOGrantValidation/TestNativeIOStopAndJoin and existing expiry/borrow/grouping expectations. Reuse existing IPv4, IPv6 and dual-stack socket/metadata tests through their current seams; add no new family fixture unless inspection establishes a missing accepted case, in which case re-audit its context before expanding E1. Preserve the distinction between injected EAGAIN attribution, uninstrumented deadline tolerance and actual-pressure observation. Bind focused native_shutdown/native_software_protection/BBR-credit/member tests without weakening expectations.

**Dispatch context budget:** This/common contract and safety table; A0 exact installation/venue receipt; native_qualification_test.go and native_qualification.py/tests; existing socket tests and named endpoint/race interfaces. Only the relevant poller/syscall source and fixture diff, no E6 campaign history beyond method limits.

**Slice decision audit:** A0 supplies exact installations and venue prerequisites consumed by the build/smoke contract. Separate tags-only and driver-only PRs would leave ARM64 identity unbound; rejected on merit. The six-class method already exists, so this is one applicability/attribution adaptation, unlike inventing a new backend. Merging P1 or C1 adds independent peer/cost owners; none: rejected on merit.

**Stop conditions:** Stop if ARM64 requires production behavior changes, native method replacement, undefined ancillary representation, new privileged infrastructure action or a fixture scope too wide for this context. Missing/skipped evidence cannot complete the child.

### P1 — Build the pinned native ARM64 peer and ordinary controls

**What it delivers:** Consume the merged shared P1 profile/identity and common Go peer-helper interface, then add explicit Linux ARM64 image/Go archive/checksum and runner identities; compile/discover the tagged root matrix and execute both ordinary QUIC roles natively. Adapt root matrix tags and the integration ordinary-control architecture assertion while preserving amd64. Record native host/image/binary/toolchain identities and package pins for the ordinary-control receipt as well as matrix modes; current run.py only binds detailed identity for matrix/zero modes. No public multipath campaign runs here.

**Existing-work disposition:** New slice on the merged baseline; retain the existing runtime owners. The common prior-work exclusion and cross-program reuse rule apply.

**Blocked by:** Shared MP-MAC-P1 (#1488)

**Single owner after merge:** Go fixture owns sockets/child lifetime; pinned peer owns protocol behavior; Docker build owns binary inputs; run.py owns selected execution identity/case accounting. Host, image and binary architecture must agree without binfmt/QEMU substitution.

**Authority completeness:** No new persisted product authority or restart format. The common constructor/validation/cleanup/readback contract applies. Receipts cannot open public admission.

**Transitional-seam budget:** None; the common zero-temporary-runtime-seam rule applies. No successor is asked to remove a knowingly incoherent intermediate state.

**Blast radius:** interop/multipath/Dockerfile, run.py/test_run.py, README, root peer test build constraints and integrationtests/self/picoquic_control_test.go. Preserve protocol dependency pins, distro snapshot, amd64 and merged Darwin profile behavior. Extend the selected dispatcher rather than creating a parallel profile owner. Verify an architecture-specific image digest; do not assume the existing amd64 digest supports ARM64.

**Artifact classification:** Verification aids plus process/traceability metadata, with the common payoff/domain/owner/retirement policy; existing shipped behavior and safety enforcement remain unchanged.

**Representation contract:** Explicit linux/amd64 or linux/arm64 profile; Docker manifest/image inspection, Go tool output and standard parsed receipt identities. No unrestricted machine-name wildcard. Ordinary handshake is adapter evidence, not public multipath qualification.

**Contract closure:** Not independently triggered: no changed product authority or runtime invariant. This slice provides finite evidence interfaces to the common coverage argument, without recursively proving the aid.

**Evidence budget:** Representative profile/identity/accounting negatives, native image build, root matrix binary discovery and one ordinary handshake with complete fixed-payload exchange per role. Preserve existing amd64 accounting/build controls. No additional peer scenarios or retries are allocated. The common review and non-recursion limits apply.

**TDD and preservation evidence:** First test wrong/missing architecture, absent/duplicate/skipped case, failed child/timeout cleanup and image/compiler mismatch. Require TestPicoquicMultipathMatrix in the root binary discovery separately from the successful integration ordinary client/server controls. Pin both peer commits unchanged and keep observed socket tuples/role arguments explicit.

**Dispatch context budget:** This/common contract; Dockerfile, run.py/test_run.py, peer build/launch helpers, root matrix build/role interface, ordinary control and pinned build inputs. Include the bounded governing diff of the merged change completing shared P1 (#1488) and its actual accepted interface; exclude shared P2 phase semantics and historical peer campaigns.

**Slice decision audit:** Shared P1 #1488 is necessary because this delta consumes its execution-profile, binary-settings, ordinary/discovery receipt and common Go tuple/launch interfaces. An independent dispatcher would add duplicate identity ownership; rejected on merit. No A0 edge: the native container builder supplies its own exact Go/build inputs and ordinary handshake needs no tracing, grant or public multipath gate. Its kernel identity is reported honestly; Q1 later selects the qualification venue. Build-only/launcher-only splitting leaves no end-to-end usable peer; shared P2 witness work is owned externally and must not be duplicated. Both rejected; none: rejected on merit.

**Stop conditions:** Stop on unavailable native builder, incompatible pinned peer, needed pin change, emulation, undefined image identity or production admission bypass. An unavailable builder is a concrete blocker, not permission to claim a cross-build as readiness.

### C1 — Adapt matched ordinary workloads and ARM64 metrics

**What it delivers:** Consume the merged shared workload/metric interfaces and final lifecycle/comparison consumers, then extend one explicit Linux ARM64 profile through their build selection, prepared-toolchain attribution, validated role CPU/scheduler sets, launch parameters and identity records. Retain its Reno/BBRv3 STREAM/DATAGRAM/mixed/response-pressure and truthful CPU/RSS/useful-byte/latency records without rebuilding the shared collector. Use validated role CPU sets from A0 available CPUs and corresponding scheduler counters, not historical 8–15/24–31 indices. Supply record value/source/availability and exact source/compiler/venue identity. Readiness smoke supplies no comparative cost conclusion.

**Existing-work disposition:** New slice on the merged baseline; retain the existing runtime owners. The common prior-work exclusion and cross-program reuse rule apply.

**Blocked by:** A0, shared MP-MAC-C2 (#1491), MP-MAC-C4 (#1493). Their shared metrics C1 and relay C3 prerequisites are transitive.

**Single owner after merge:** Fixture owns demand/useful delivery; Linux collectors own CPU/RSS facts; driver owns windows, role placement and child joins. The host owns P/E-core facts, which guest CPU IDs do not invent. No collector chooses controller policy or turns unavailable BBR counters into zero.

**Authority completeness:** No new persisted product authority or restart format. The common constructor/validation/cleanup/readback contract applies. Receipts cannot open public admission.

**Transitional-seam budget:** None; the common zero-temporary-runtime-seam rule applies. No successor is asked to remove a knowingly incoherent intermediate state.

**Blast radius:** The existing ordinary-cost profile/placement functions and immediate build/profile/launch/identity interfaces of the merged lifecycle/comparison consumers. Permit explicit architecture selection, CPU-set/counter parameter plumbing and call-site wiring only; retain workload algorithms, lifecycle transitions, comparison arms/topology, metric schemas and existing amd64/Darwin behavior. Shared owners keep their algorithms and records; this slice creates no second collector or lifecycle/comparison implementation. A separately selected root-test-only private grant smoke may exercise unnegotiated ordinary traffic before ARM64 activation; it never replaces the public measurement entrypoint or satisfies support evidence. Q1/Q2 granted-ordinary measurements must call public ConfigureMultipathIOV1 on the actual activation candidate; negotiated mixed bulk uses supported amd64 for readiness and Q2 for ARM64. No new production telemetry or generic benchmark framework.

**Artifact classification:** Verification aids plus process/traceability metadata, with the common payoff/domain/owner/retirement policy; existing shipped behavior and safety enforcement remain unchanged.

**Representation contract:** Typed workload/controller/profile records, Linux standard proc/getrusage fields and explicit CPU-ID sets validated against observed available CPUs. Canonical subset for record identity/units/availability; example-level measurements. Keep guest CPU accounting separate from host placement claims.

**Contract closure:** Not independently triggered: no changed product authority or runtime invariant. This slice provides finite evidence interfaces to the common coverage argument, without recursively proving the aid.

**Evidence budget:** One positive per workload wiring/metric behavior and negative for invalid controller/profile, bad CPU masks/counter mapping, wrong identity, missing/invalid units, unavailable-versus-zero and partial cleanup. One bounded ordinary smoke per distinct wiring; negotiated mixed-bulk control on supported amd64 only. Add compiled ARM64 consumer discovery or bounded interface checks and preserved public refusal for negotiated lifecycle/comparison entrypoints, using existing shared functional evidence for their unchanged semantics. No ARM64 negotiated collection occurs before Q2. Historical campaign/retry/quiet-wait constants grant no ARM64 attempts. The common review and non-recursion limits apply.

**TDD and preservation evidence:** First discriminate controller selection, CPU interval/CPU-set mapping, RSS byte/kB conversion, useful delivery versus offered bytes, missing counters and canceled roles. Verify GSO capability is required for cells without disable override, including mixed and pressure; A0 flags alone are not engagement evidence. Preserve genuine negotiated two-live-path mixed bulk and record limitation until Q2. Use exact prepared toolchains and native ordinary/private-grant smoke after A0. First fail wrong/missing Linux ARM64 profile or identity, unavailable/out-of-range role CPU sets and incorrect scheduler-counter propagation at the actual ordinary/lifecycle/comparison launch seams. Confirm discovery/build applicability and preserved pre-activation refusal; no private negotiated-admission bypass is permitted.

**Dispatch context budget:** This/common contract; A0 venue/CPU/compiler receipt; the shared profile/metric/placement interface and the final ordinary/lifecycle/comparison selection, launch, identity and counter-parameter entrypoints. Include only the bounded governing diffs completing shared C1 (#1490), C2 (#1491) and C4 (#1493) at those interfaces, not their full algorithms or historical plans. One explicit architecture input flows through existing owners; no complete lifecycle/relay/workload implementation, frozen campaign loop or endpoint internals are in this context.

**Slice decision audit:** A0 supplies actual guest facts; shared C2 #1491 and C4 #1493 supply the final consumers whose ARM64 entrypoints this slice adapts. Shared metrics C1 #1490 and relay C3 #1492 are transitive prerequisites, not redundant direct edges. Splitting this finite profile/placement path by consumer would leave the same architecture input partially wired; rejected on merit. Merging lifecycle/topology algorithms into C1 would cross existing owners and its context bound; rejected on merit. No duplicate/adoption-only child is created. Revisit the boundary only if actual applicability requires a new algorithm, representation, owner or wider context.

**Stop conditions:** Stop on unobservable required metric/CPU mapping, unavailable required GSO cell, required lifecycle/topology/collector redesign, new metric representation, need to bypass negotiated ARM64 admission, a new tolerance, host reservation/privileged sampler or production repair. Report limitations instead of synthesizing valid measurements.

### Q1 — Approve the concrete native execution protocol

**What it delivers:** Publish one concrete reviewed protocol binding the merged methods to exact candidate identity rules, executable commands, venue/image/kernel/toolchains, native case/role/controller/family inventory, timing/attribution rules, CPU placement, comparable cost criteria and continuing native coverage. Obtain and record the owner’s approval of the actual finite operational scope and any privilege/maintained-aid decisions before completing this child. No qualification campaign runs here. Bind source applicability explicitly: freeze production/build inputs before collection, retain the actual measurement commit and binary/tool identities, and permit only reviewed receipt/support metadata and finite-aid retirement afterward. Never relabel an earlier observation as executed on the final SHA; a changed production/build input invalidates affected evidence. Final local certification and hosted checks still run on the exact final head.

**Existing-work disposition:** New slice on the merged baseline; retain the existing runtime owners. The common prior-work exclusion and cross-program reuse rule apply.

**Blocked by:** E1, P1, C1, shared MP-MAC-P2 (#1489)

**Single owner after merge:** Protocol owns finite command/case/identity mapping and the selected decision procedure over matched comparison records; maintainer owns venue/privilege/operational allowance, new continuing CI and any explicit cost exception. Tools report facts; ready labels do not authorize collection.

**Authority completeness:** No new persisted product authority or restart format. The common constructor/validation/cleanup/readback contract applies. Receipts cannot open public admission.

**Transitional-seam budget:** None; the common zero-temporary-runtime-seam rule applies. No successor is asked to remove a knowingly incoherent intermediate state.

**Blast radius:** Protocol and command-correspondence metadata only. No VM mutation, sampler/benchmark launch, budget reset, cloud reservation or runner registration. Native hosted ubuntu-24.04-arm and local guest have distinct roles; verify actual execution identity, not label alone.

**Artifact classification:** Process/traceability metadata. Selected continuing verification aids require the common explicit approval, payoff, domain, owner and retirement record.

**Representation contract:** Finite command/case/identity table and exact approval receipt; standard tool outputs, canonical inventory, example-level native qualification. No generic manifest language or universal kernel/performance claim.

**Contract closure:** Not independently triggered: no changed product authority or runtime invariant. This slice provides finite evidence interfaces to the common coverage argument, without recursively proving the aid.

**Evidence budget:** One source/method-to-command audit and concrete owner decision, including the existing comparison interpretation obligation. Name pairing keys, useful-byte definitions, applicable paired-ratio/aggregation arithmetic and invalid-comparator handling. Verify the procedure with equivalent existing shared checks or reproducible worked records: a representative positive, a valid negative candidate and an invalid/mismatched comparator, with differing paired values that distinguish the selected calculation from an incorrect aggregate calculation. Record expected results. These are synthetic protocol checks, not a new maintained verdict tool or native observations. Zero native qualification/performance attempts. Select meaningful platform/toolchain distinctions and exact repetitions only when required by an accepted question; do not inherit old six-by-two/36-observation/three-round/quiet-retry budgets automatically. The common review and non-recursion limits apply.

**TDD and preservation evidence:** No code TDD. Bind every row of the safety table to command, expected identity/output and missing-evidence disposition. Include both Go pins, all three policies, independent peer roles, negotiated zero separately, native address-family/packet-info/ECN/offload applicability, E1 current poller/group-yield/timing/pressure distinctions, focused race and BBR protection/recovery, public migration/survivor, C1 mixed/pressure GSO requirements, the shared lifecycle idle path-zero/backup-absent baseline and later same-backup third phase, shared peer-callback ingress (not reverse echo path), and comparison controls/negative-verdict arithmetic. Put first actual ARM64 poller traversal early in Q2; a method failure routes to E1 scoped re-audit and protocol reapproval before any further attempt. Keeping this first observation in Q2 avoids allocating an unapproved injected readiness run; do not move it earlier without explicit operational approval. Bind granted-ordinary support measurements to public ConfigureMultipathIOV1, not the isolated private readiness smoke. Preserve 1.10 CPU ratio/10% RSS limits and applicable B11 criteria; amd64 exceptions do not transfer. Bind skip-sensitive continuing native unit/public/focused race on both Go 1.26.11 and Go 1.27.4, and explicitly decide peer matrix/cadence without assuming twice the current campaign.

**Dispatch context budget:** This/common contract and safety/profile tables; the three ARM readiness interfaces, C1’s accepted lifecycle/comparison applicability and the merged shared P2 ingress interface, with A0 identities transitively; current CI and cost criterion sections. No fixture reimplementation or complete historical campaign. Missing authority is presented as the concrete package, not an abstract permission request.

**Slice decision audit:** The three ARM outputs and shared P2 supply real executable methods/limits. C1 consumes the final shared C2/C4 interfaces and transitively shared C1/C3; no redundant direct shared-consumer/relay edges or duplicate ARM adoption PRs are added. A speculative protocol before those interfaces invites re-derivation; merging Q2 mixes undecided execution authority with activation. Separating inventory from its approval leaves an incomplete contract. Revisit: none: rejected on merit.

**Stop conditions:** Keep Q1 open and Q2 blocked until the concrete venue/privilege/finite inventory/continuing-aid decisions are recorded. If full parity requires a changed product outcome, owner or one-PR boundary, return to handoff/owner decision rather than waive a row.

### Q2 — Qualify and activate the complete Linux ARM64 profile

**What it delivers:** On one unmerged feature candidate, extend the common capability gate to Linux ARM64, update independent root/HTTP3 acceptance/refusal expectations, run Q1’s exact native protocol, and merge the gate, acceptance tests, approved continuing native CI, support receipt, README/usage and new release entry together. All three accepted controller/policy combinations must qualify. Missing, invalid or unacceptable evidence leaves activation unmerged. After retaining raw evidence, this same child retires only ARM-specific finite entrypoints unless Q1 records continued-maintenance approval. Preserve shared tools while their owning support contract requires them, regardless of program completion. On a definitive owner decision not to activate, Q2 instead publishes the negative support disposition/evidence and safe ARM-only retirement in one PR with admission closed; a failure still under investigation keeps the child open. No-go is an explicit owner decision, not an automatic response to one failed observation.

**Existing-work disposition:** New slice on the merged baseline; retain the existing runtime owners. The common prior-work exclusion and cross-program reuse rule apply.

**Blocked by:** Q1

**Single owner after merge:** Common capability decision owns platform eligibility; native grant installer owns socket/duration/authority; enabled admission owns Config/controller/policy/version; existing endpoint/connection/recovery owners retain runtime state. Qualification facts inform the maintainer’s support decision, never become a runtime side channel.

**Authority completeness:** No new persisted product authority or restart format. The common constructor/validation/cleanup/readback contract applies. All grant/constructor/server-selected entrypoints and their actual input checks ship with activation.

**Transitional-seam budget:** None; the common zero-temporary-runtime-seam rule applies. No successor is asked to remove a knowingly incoherent intermediate state.

**Blast radius:** Platform predicate/helper, support comments/errors, root/HTTP3 test applicability, approved CI, support metadata and retirement of separately identified ARM-specific finite entrypoints unless Q1 approves continued maintenance. Review the bounded post-collection diff for unchanged qualified production/build inputs, retaining the actual evidence source identity. Preserve then-current accepted macOS/other-platform behavior if it has merged, with no cross-program prerequisite. No shared-aid deletion or endpoint timing/algorithm/backend redesign, performance optimization or peer update fits this slice.

**Artifact classification:** Shipped behavior and required support enforcement for admission; verification aids for tests/approved CI; process metadata for receipts and publication.

**Representation contract:** Typed GOOS/GOARCH and existing Config/socket validators define the finite support partition. No new compiler-version parser or kernel allowlist. Independent table expectations cover declared partitions; native timing/performance is bounded example-level evidence from the approved venue.

**Contract closure:** The common bounded native safety/admission coverage argument applies at the named enforcement owners; no recursive harness closure.

**Evidence budget:** Exactly Q1’s approved native operational inventory, local platform/configuration regression cases against the recorded exact qualification candidate, with only Q1-approved source-inert retirement/metadata changes afterward; final local certification and existing applicable hosted jobs use the exact final head. One initial review and at most one replacement. No extra attempts, broader platform evidence or repeated collection without the governing decision. The common review and non-recursion limits apply.

**TDD and preservation evidence:** First write independent expected-platform/entrypoint tests failing for ARM64 admission while preserving Linux amd64 and other established outcomes; test explicit/owned grants, constructor/server-selected configuration, setter orders/clones, v2/Reno aggregate refusals and ordinary v2/default-off/HTTP3 preservation. Use public ConfigureMultipathIOV1 for granted-ordinary measurement, keeping private smoke records nonqualifying. Execute Q1 endpoint/poller/borrow/race/BBR/public lifecycle/peer/cost/memory/topology cases, separating attribution from untraced deadline timing and pressure. Missing required cases/skips fail readiness. Require fresh both-role aggregate ingress, selected compiler/image/socket identities and current native software-yield evidence. Document limitations honestly.

**Dispatch context budget:** This/common contract; Q1 approved exact protocol and readiness interfaces; current common capability/grant/admission sections, public/root/HTTP3 tests, selected CI and support docs. Exclude fixture internals and campaign history unless diagnosing a concrete accepted failure. A runtime repair invalidates this small activation-context claim.

**Slice decision audit:** Q1 is the actual authority/evidence dependency and transitively covers tooling. Splitting activation from tests/evidence/CI/support leaves an unsupported public interval; none: rejected on merit. Splitting by controller violates full parity; revisit only on explicit owner decision. A separate helper-only prefactor has no necessary independently delivered behavior; revisit: none: rejected on merit.

**Stop conditions:** Stop on failed/missing native traversal, required family/offload evidence, unaccepted cost, changed venue without applicability, expired authority, widened runtime ownership/representation or inability to preserve one PR. Diagnose before reruns. Do not relax tolerance, silently narrow support or treat historical exceptions as ARM64 approval.

## Acceptance criteria and validation gates

- Each readiness child delivers its stated usable interface and named terminating evidence; missing prerequisites or skipped cases do not complete it.
- Public Linux ARM64 admission remains closed until Q2, which preserves the accepted full-parity profile and then-current supported platforms.
- Q1 records a concrete approved protocol before Q2 is ready; no campaign, operational allowance or new continuing CI is inferred from this handoff.
- On accepted qualification Q2 merges admission, independent acceptance tests, approved continuing native coverage and support publication together; on an explicit definitive no-go it records the negative disposition and ARM-only retirement with admission closed.
- Every ARM-owned slice maps once to a plan contract, child issue, intended PR and OmniFocus task; administrative readiness remains distinct from code-head certification.

Universal words in these criteria range over the six ARM-owned slices and finite typed semantic partitions above, with their named owners and terminating evidence. Native/platform/performance observations remain example-level. This documentation publication terminates at source correspondence, all slice fields/edges, relative links and no unauthorized runtime change, using the shared review allowance.

For Go changes run affected-package tests, go vet on those packages and go mod tidy -diff when applicable; use the specifically selected race/native gates. For Python/C adapters run the named finite accounting/compile/smoke checks and preserved amd64 controls. Derive exact commands in each child's preflight from its accepted named tests/current interfaces. Never invoke an entire historical campaign merely because its filename resembles the slice.

## Operating discipline

The shared [review-loop](https://github.com/the-sarge/skills/blob/main/_shared/REVIEW-LOOP.md) and [contract-closure](https://github.com/the-sarge/skills/blob/main/_shared/CONTRACT-CLOSURE.md) baselines supplied by $implement-architecture-slice govern, composed with the [repository execution overlay](../REVIEW-LOOP.md). Use the shared design-cost reference for re-audit. Their representation/artifact gates, finite evidence/review limits, semantic-family closure, precise-root side-by-side comparison, review/verification-aware approach stops, exact-head local certification, same-head hosted checks, merge/journal/tracking and diagnosis-before-rerun rules apply directly; no repository baseline copy is created.

For this handoff, complete independent slice audits before committing, then the Standards/Spec preparation and full configured RAS review through the installed skills. Repository ordinary workflows run on draft PRs; complete review and clean exact-head local docs certification before marking ready. Require applicable checks successful on that exact live head, verify current base and squash with head matching. No Go tests, native workload or implementation dispatch belongs to this documentation run. Issues/mirrors follow verified default-branch publication only.

Each future child owns its plan/index completion and affected successor frontier in the same PR before review. After exact-head merge, record the hosted development-journal completion account, reconcile child/parent/tracker dependencies and OmniFocus, then complete the slice task. Do not add a routine administrative third PR or duplicate plan SHA in OmniFocus. The operator chooses dispatch, one fresh agent per verified frontier child using $implement-architecture-slice; parent issues are not implementation requests.
