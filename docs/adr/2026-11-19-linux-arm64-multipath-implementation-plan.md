# Linux ARM64 multipath implementation plan

**Date:** 2026-11-19. **Identity:** MP-ARM, track 1 of 1 in MP-ARM-20261119. **Status:** Accepted handoff; not implemented. **Depends on:** No other platform program. **Normative scope:** Current outcomes, invariants, boundaries, acceptance evidence, blockers and stop conditions. **Audit history:** [Source and slice audit](../audits/2026-11-19-linux-arm64-handoff/README.md). **Program:** [Index](2026-11-19-linux-arm64-multipath-program.md).

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

**Rejected alternatives — do not do these:** A separate ARM64 endpoint duplicates lifetime policy without evidence; revisit only if native evidence proves the current owner cannot express a platform requirement. Early Reno-only support violates full parity; revisit only on an explicit evidence-backed product decision. A production admission bypass or fake OS identity invalidates qualification; none: rejected on merit. Reusing retired B11 collectors as maintained dependencies violates frozen-evidence ownership; use only scoped source mechanics in C3/C4. Emulated runs and historical amd64 exceptions cannot establish ARM64 support or tolerances; none: rejected on merit. A blanket A0-before-all ordering has no code necessity for P1/P2/C3; none: rejected on merit. Do not copy or rebaseline the separate macOS program; if its shared tooling merges first, adapt/reuse the actual merged interface within the current child's contract instead of creating a second collector. A topology/owner change beyond that contract requires scoped re-audit.

**Non-goals:** New runtime APIs, protocol/schema changes, controller/scheduler tuning, higher path counts, hardware-NIC performance claims, arbitrary ARM kernels/CPUs, physical-host reservations, new peer pins, full BBR qualification, blanket recurring CI or statistical campaign allowances. Untraced effects are actual native trigger/offload capability, shared-host scheduling attribution and measured costs; they remain explicit later evidence obligations, never silently accepted runtime changes.

## Slice graph

| Slice | State/disposition | End-to-end outcome | Blocked by | Temporary seam removed |
| --- | --- | --- | --- | --- |
| A0 | New; frontier | Prepared native venue/toolchain identities and prerequisite receipt | None | None |
| E1 | New; blocked | Native ARM64 endpoint fixture and exact build/case accounting | A0 | None |
| P1 | New; frontier | Pinned native ARM64 peer build and ordinary controls | None | None |
| P2 | New; frontier | Fresh both-active DATAGRAM ingress witness | None | None |
| C1 | New; blocked | Matched ordinary workloads, ARM64 metrics and CPU placement | A0 | None |
| C2 | New; blocked | Negotiated lifecycle-memory observation | C1 | None |
| C3 | New; frontier | Scoped real-UDP topology relay | None | None |
| C4 | New; blocked | Matched topology comparison consumer | C1, C3 | None |
| Q1 | New; blocked | Concrete approved execution protocol | E1, P1, P2, C2, C4 | None |
| Q2 | New; blocked | Native qualification and complete public activation | Q1 | None |

A0, P1, P2 and C3 are parallel-safe in separate worktrees. E1/C1 consume A0's prepared compiler/venue/CPU facts; P1's isolated native container build supplies its own build toolchain and needs neither tracing privileges nor multipath admission. P2 can use existing supported Linux fixture semantics. C2 consumes C1's identity/metric interface; C4 consumes C1 and C3. Q1 binds all leaf methods and actual limitations before Q2. File overlap with another platform program requires merge coordination, not speculative cross-program blockers. No integration branch is needed.

## Common contract for every slice

Every slice below includes this common contract, the settled profile and the specific fields beneath its heading. One slice is one intended PR and one fresh agent context. Existing-work disposition is new work on the merged baseline; [PR #1295](https://github.com/GridCastIO/quicquic-go/pull/1295) is excluded as unselected historical work, with the source/diff/closure assessment in the audit. Do not cherry-pick its scalar adapter, reopen its spent allowance or make it a dependency.

Readiness tools are verification aids; plans, preparation receipts and qualification reports are process/traceability metadata. Existing runtime behavior and required safety enforcement stay unchanged until Q2. The narrowly scoped aids have transport test/interop maintainership, payoff in reproducible named native regression observations, and domain limited to these platforms/toolchains/scenarios. Ordinary maintained fixture extensions retire with equivalent replacement or support removal; the finite C3/C4 comparison successor retires after the ARM64 support decision, archiving its raw evidence, unless the owner explicitly selects continued maintenance in Q1. Q1 must record explicit maintained-blocker approval, payoff, domain, owner and retirement for selected new continuing CI aids. Unapproved ancillary aids cannot block shipped behavior by reviewer demand.

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

**What it delivers:** Produce a reproducible preparation runbook and observed readiness receipt for the proposed native guest: image/configuration/kernel identity, native architecture, exact isolated Go 1.26.11/1.27.4 installation paths/checksums and GOTOOLCHAIN=local identities, available CPU IDs and tool/privilege/capability prerequisites. Prepare only a task-owned tool prefix when authorized; shared guest image/package/runner changes remain in their owning infrastructure workflow. An unavailable prerequisite keeps this child open, not green by documentation.

**Existing-work disposition:** New slice on the merged baseline; retain the existing runtime owners. The common prior-work exclusion and cross-program reuse rule apply.

**Blocked by:** None

**Single owner after merge:** The infrastructure owner owns the guest and access; A0 owns its task-local installation/receipt; Go distributions own compiler/poller identity. It creates no runtime capability decision.

**Authority completeness:** No new persisted product authority or restart format. The common constructor/validation/cleanup/readback contract applies. Receipts cannot open public admission.

**Transitional-seam budget:** None; the common zero-temporary-runtime-seam rule applies. No successor is asked to remove a knowingly incoherent intermediate state.

**Blast radius:** Preparation metadata and isolated tool distribution only; no shared VM replacement, global PATH/package changes, workload execution, host affinity, process termination or CI registration. Verify native Docker builder identity separately from the qualification guest; neither substitutes for the other.

**Artifact classification:** Process/traceability metadata and task-local tool preparation; no runtime behavior or new maintained verification framework.

**Representation contract:** Exact native uname/OS/package/tool outputs and installed distribution digests, parsed by their normal tools. Example-level environment observation; explicitly record unavailable privileges or offloads. An image label is not a reproducible image digest.

**Contract closure:** Not independently triggered: no changed product authority or runtime invariant. This slice provides finite evidence interfaces to the common coverage argument, without recursively proving the aid.

**Evidence budget:** One read-only identity/prerequisite pass, exact checksums and one local version/build identity check per prepared compiler. No qualification, pressure, tracing capture, benchmark or new harness. Privileged feasibility operations require the infrastructure owner’s concrete authorization; record existing authority or leave the prerequisite unresolved. The common review and non-recursion limits apply.

**TDD and preservation evidence:** No production TDD. Check the runbook against observed installation paths, versioned selection and actual permissions; reject wrong-architecture/compiler identity and missing prerequisites in its finite checklist. Presence of strace/nft is not permission or a real poller witness. Socket/offload feasibility is explicitly carried to E1/Q1 if it requires an operational probe.

**Dispatch context budget:** This/common contract; target plan venue table; native_qualification.py prerequisite/build interface; exact local Lima configuration and tool distributions. No native fixture or historical campaign internals.

**Slice decision audit:** No blockers: preparation is independently useful. Splitting toolchains from their actual venue identity leaves no reproducible native build input; merging E1 mixes infrastructure identity with fixture semantics. Both rejected; none: rejected on merit. A0 does not gate P1’s self-contained native container build or platform-independent P2/C3.

**Stop conditions:** No access or required identity, missing install/privilege authority, non-native execution or need for shared infrastructure mutation keeps A0 open for the concrete owner decision. Do not reserve a different host or relabel Docker Desktop as this guest.

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

**What it delivers:** Add explicit ARM64 image/Go archive/checksum and runner identities to the existing peer build; compile/discover the tagged root matrix and execute both ordinary QUIC roles natively. Adapt root matrix tags and the integration ordinary-control architecture assertion while preserving amd64. Record native host/image/binary/toolchain identities and package pins for the ordinary-control receipt as well as matrix modes; current run.py only binds detailed identity for matrix/zero modes. No public multipath campaign runs here.

**Existing-work disposition:** New slice on the merged baseline; retain the existing runtime owners. The common prior-work exclusion and cross-program reuse rule apply.

**Blocked by:** None

**Single owner after merge:** Go fixture owns sockets/child lifetime; pinned peer owns protocol behavior; Docker build owns binary inputs; run.py owns selected execution identity/case accounting. Host, image and binary architecture must agree without binfmt/QEMU substitution.

**Authority completeness:** No new persisted product authority or restart format. The common constructor/validation/cleanup/readback contract applies. Receipts cannot open public admission.

**Transitional-seam budget:** None; the common zero-temporary-runtime-seam rule applies. No successor is asked to remove a knowingly incoherent intermediate state.

**Blast radius:** interop/multipath/Dockerfile, run.py/test_run.py, README, root peer test build constraints and integrationtests/self/picoquic_control_test.go. Preserve protocol dependency pins, distro snapshot and amd64 behavior. Verify an architecture-specific image digest; do not assume the existing amd64 digest supports ARM64.

**Artifact classification:** Verification aids plus process/traceability metadata, with the common payoff/domain/owner/retirement policy; existing shipped behavior and safety enforcement remain unchanged.

**Representation contract:** Explicit linux/amd64 or linux/arm64 profile; Docker manifest/image inspection, Go tool output and standard parsed receipt identities. No unrestricted machine-name wildcard. Ordinary handshake is adapter evidence, not public multipath qualification.

**Contract closure:** Not independently triggered: no changed product authority or runtime invariant. This slice provides finite evidence interfaces to the common coverage argument, without recursively proving the aid.

**Evidence budget:** Representative profile/identity/accounting negatives, native image build, root matrix binary discovery and one ordinary handshake with complete fixed-payload exchange per role. Preserve existing amd64 accounting/build controls. No additional peer scenarios or retries are allocated. The common review and non-recursion limits apply.

**TDD and preservation evidence:** First test wrong/missing architecture, absent/duplicate/skipped case, failed child/timeout cleanup and image/compiler mismatch. Require TestPicoquicMultipathMatrix in the root binary discovery separately from the successful integration ordinary client/server controls. Pin both peer commits unchanged and keep observed socket tuples/role arguments explicit.

**Dispatch context budget:** This/common contract; Dockerfile, run.py/test_run.py, peer build/launch helpers, root matrix build/role interface, ordinary control and pinned build inputs. Exclude P2 phase semantics and historical peer campaigns.

**Slice decision audit:** No A0 edge: the native container builder supplies its own exact Go/build inputs and ordinary handshake needs no tracing, grant or public multipath gate. Its kernel identity is reported honestly; Q1 later selects the qualification venue. Build-only/launcher-only splitting leaves no end-to-end usable peer; P2 merging couples independent witness semantics. Both rejected; none: rejected on merit.

**Stop conditions:** Stop on unavailable native builder, incompatible pinned peer, needed pin change, emulation, undefined image identity or production admission bypass. An unavailable builder is a concrete blocker, not permission to claim a cross-build as readiness.

### P2 — Add a fresh both-active DATAGRAM ingress witness

**What it delivers:** Extend useful-transfer with a fresh nonce/sequence after both paths are activated, snapshot per-path counters then, and require matching useful receipt on both actual ingress paths in each role. Both paths must remain StateV1 live and LocalUse active on every bounded offer round and at phase end. Ship peer receipt production and matrix validation together; preserve the STREAM witness.

**Existing-work disposition:** New slice on the merged baseline; retain the existing runtime owners. The common prior-work exclusion and cross-program reuse rule apply.

**Blocked by:** None

**Single owner after merge:** Peer callback owns actual ingress; Go matrix owns phase/payload membership and finite acceptance; production scheduler owns selection. Payload-requested reply path and sender deltas never substitute for actual useful ingress.

**Authority completeness:** No new persisted product authority or restart format. The common constructor/validation/cleanup/readback contract applies. Receipts cannot open public admission.

**Transitional-seam budget:** None; the common zero-temporary-runtime-seam rule applies. No successor is asked to remove a knowingly incoherent intermediate state.

**Blast radius:** matrixUsefulTransfer/datagram phase, peer.c callback emitted records and associated fixture tests. Finite explicit record shape/standard parser, no generic log scanner, runtime receiver API, wire extension or scheduler tuning. Preserve bounded offered work and existing scenario inventory.

**Artifact classification:** Verification aids plus process/traceability metadata, with the common payoff/domain/owner/retirement policy; existing shipped behavior and safety enforcement remain unchanged.

**Representation contract:** Canonical explicitly emitted nonce/sequence/path/phase record; actual callback or existing received-packet trace owns ingress identity. Example-level useful delivery, not statistical fairness or a claim about every packet.

**Contract closure:** Not independently triggered: no changed product authority or runtime invariant. This slice provides finite evidence interfaces to the common coverage argument, without recursively proving the aid.

**Evidence budget:** Five semantic fixture cases: fresh both-path matching pass; stale/wrong phase or lost live-active eligibility fails; duplicate receipt does not add progress; one-path-only fails; sender-only progress fails. Characterize both roles. No extra live aggregate campaign is implied by default Reno hosted CI. The common review and non-recursion limits apply.

**TDD and preservation evidence:** Write the five discriminating cases first and exercise callback producer/validator wiring with both-role characterization. Keep the existing supported Linux fixture as development control. Q1 binds the first planned live both-role aggregate observation to Q2; if it fails, distinguish fixture attribution from platform behavior before reruns. No qualification claim arises from synthetic receipts.

**Dispatch context budget:** This/common contract; matrixSession/matrixUsefulTransfer/datagram/trace interfaces, peer.c DATAGRAM/path callbacks and pinned callback contract. No P1 output or ARM64 venue is required.

**Slice decision audit:** No blocker: current amd64 fixture supplies the interface. Splitting producer from validator or splitting roles creates half a witness; merging P1 adds unrelated build ownership. Revisit: none: rejected on merit. This slice is shared semantic work; reuse an equivalent merged macOS P2 implementation if it lands first, with the same accepted contract and no duplicate witness.

**Stop conditions:** Stop if actual ingress cannot be observed through the existing peer/trace seam, if receipt freshness requires a runtime API or if bounded offered work cannot express the witness. Do not silently equate requested path with ingress.

### C1 — Adapt matched ordinary workloads and ARM64 metrics

**What it delivers:** Extend the maintained Linux ordinary-cost apparatus to explicit ARM64, controller-matched Reno/BBRv3 STREAM/DATAGRAM/mixed/response-pressure workloads and truthful CPU/RSS/useful-byte/latency records. Use validated role CPU sets from A0 available CPUs and corresponding scheduler counters, not historical 8–15/24–31 indices. Supply record value/source/availability and exact source/compiler/venue identity. Readiness smoke supplies no comparative cost conclusion.

**Existing-work disposition:** New slice on the merged baseline; retain the existing runtime owners. The common prior-work exclusion and cross-program reuse rule apply.

**Blocked by:** A0

**Single owner after merge:** Fixture owns demand/useful delivery; Linux collectors own CPU/RSS facts; driver owns windows, role placement and child joins. The host owns P/E-core facts, which guest CPU IDs do not invent. No collector chooses controller policy or turns unavailable BBR counters into zero.

**Authority completeness:** No new persisted product authority or restart format. The common constructor/validation/cleanup/readback contract applies. Receipts cannot open public admission.

**Transitional-seam budget:** None; the common zero-temporary-runtime-seam rule applies. No successor is asked to remove a knowingly incoherent intermediate state.

**Blast radius:** ordinary_cost_test.go, ordinary_cost.py/test_ordinary_cost.py and narrowly shared metric/placement functions. Retain existing amd64 selectors/thresholds. Root-test-only private grant may exercise unnegotiated ordinary traffic before ARM64 activation; negotiated mixed bulk uses supported amd64 for readiness and Q2 for ARM64. No new production telemetry or generic benchmark framework.

**Artifact classification:** Verification aids plus process/traceability metadata, with the common payoff/domain/owner/retirement policy; existing shipped behavior and safety enforcement remain unchanged.

**Representation contract:** Typed workload/controller/profile records, Linux standard proc/getrusage fields and explicit CPU-ID sets validated against observed available CPUs. Canonical subset for record identity/units/availability; example-level measurements. Keep guest CPU accounting separate from host placement claims.

**Contract closure:** Not independently triggered: no changed product authority or runtime invariant. This slice provides finite evidence interfaces to the common coverage argument, without recursively proving the aid.

**Evidence budget:** One positive per workload wiring/metric behavior and negative for invalid controller/profile, bad CPU masks/counter mapping, wrong identity, missing/invalid units, unavailable-versus-zero and partial cleanup. One bounded ordinary smoke per distinct wiring; negotiated mixed-bulk control on supported amd64 only. Historical campaign/retry/quiet-wait constants grant no ARM64 attempts. The common review and non-recursion limits apply.

**TDD and preservation evidence:** First discriminate controller selection, CPU interval/CPU-set mapping, RSS byte/kB conversion, useful delivery versus offered bytes, missing counters and canceled roles. Verify GSO capability is required for cells without disable override, including mixed and pressure; A0 flags alone are not engagement evidence. Preserve genuine negotiated two-live-path mixed bulk and record limitation until Q2. Use exact prepared toolchains and native ordinary/private-grant smoke after A0.

**Dispatch context budget:** This/common contract; A0 venue/CPU/compiler receipt; ordinary_cost_test.go workload/configuration/metrics sections and driver identity/placement/judge interfaces. C2/C4 consume resulting records only; no frozen campaign loops or endpoint implementation.

**Slice decision audit:** A0 is a real blocker for this selected-guest native metrics/placement contract. Splitting metric units from their actual workload consumer leaves window/accounting semantics unexercised; rejected on merit. C2 introduces negotiated lifecycle sampling and C4 topology arms, so keep them separate; none: rejected on merit.

**Stop conditions:** Stop on unobservable required metric/CPU mapping, unavailable required GSO cell, need to bypass negotiated ARM64 admission, a new tolerance, host reservation/privileged sampler or production repair. Report limitations instead of synthesizing valid measurements.

### C2 — Observe negotiated lifecycle memory

**What it delivers:** Use C1 records to observe negotiated idle, validated backup and post-retirement memory for a named path ID through public APIs. Record exact StateV1.Lifecycle at each sample; third phase rejects retiring and distinguishes retained from closed. Q1 selects the same qualifying state for both sides of a comparison. Keep live/retained Go heap separate from peak RSS, and transport detachment separate from path retirement and grant join.

**Existing-work disposition:** New slice on the merged baseline; retain the existing runtime owners. The common prior-work exclusion and cross-program reuse rule apply.

**Blocked by:** C1

**Single owner after merge:** Existing connection/path lifecycle owns the states; fixture observes StateV1 and owns consistently labelled samples. A requested transition or old-transport detachment cannot stand in for observed retirement.

**Authority completeness:** No new persisted product authority or restart format. The common constructor/validation/cleanup/readback contract applies. Receipts cannot open public admission.

**Transitional-seam budget:** None; the common zero-temporary-runtime-seam rule applies. No successor is asked to remove a knowingly incoherent intermediate state.

**Blast radius:** Narrow lifecycle workload and C1 metric consumer only. Public configure/open/state/abandon/detachment/join interfaces; no new path state, memory counter or private negotiated-admission override. Label forced GC consistently if selected; Go heap is not resident memory.

**Artifact classification:** Verification aids plus process/traceability metadata, with the common payoff/domain/owner/retirement policy; existing shipped behavior and safety enforcement remain unchanged.

**Representation contract:** Typed public path ID/Lifecycle and canonical C1 records. Third sample is explicitly retained or closed, never retiring; example-level memory observation, not a leak proof.

**Contract closure:** Not independently triggered: no changed product authority or runtime invariant. This slice provides finite evidence interfaces to the common coverage argument, without recursively proving the aid.

**Evidence budget:** Three observed lifecycle phases, one representative rejection each for unnegotiated control, stale/requested-only state and mismatched sampled path/phase; one supported amd64 public lifecycle smoke and failure cleanup. Native ARM64 samples remain Q2. The common review and non-recursion limits apply.

**TDD and preservation evidence:** First fail ordinary/unnegotiated backup controls, detach-with-live-same-ID substitution and unobserved retirement. Exercise observed idle/backup/retained-or-closed states, role/phase matching, metric unit distinctions and joined failure teardown. ARM64 compile/refusal does not count as memory evidence.

**Dispatch context budget:** This/common contract; C1 result/collector interface; public path StateV1/AbandonV1 and relevant lifecycle helper tests. Exclude endpoint internals and historical memory campaigns.

**Slice decision audit:** C1 supplies the single metric/identity seam, avoiding a second collector. Splitting the phases destroys the within-fixture comparison; merging ordinary bulk with negotiated retention mixes owners. Revisit: none: rejected on merit.

**Stop conditions:** Stop if no accepted lifecycle state is observable, private negotiation is needed, a production memory interface is required or metrics cannot compare the same phase. Do not add an extra phase or relax the accepted state by inference.

### C3 — Build a scoped real-UDP topology relay

**What it delivers:** Create a finite comparison relay from reviewed frozen B11 mechanics, with explicit balanced-disjoint, unequal-delay/rate and shared-bottleneck queue identities, bounded backlog/drop behavior, realized UDP delivery and joined cleanup. It is independently usable without QUIC admission, cost metrics or a performance campaign.

**Existing-work disposition:** New slice on the merged baseline; retain the existing runtime owners. The common prior-work exclusion and cross-program reuse rule apply.

**Blocked by:** None

**Single owner after merge:** One synchronized relay queue owner decides admission/drop/scheduling. Reader/delivery workers supply facts and join before final records; transport/controller policy remains outside the relay.

**Authority completeness:** No new persisted product authority or restart format. The common constructor/validation/cleanup/readback contract applies. Receipts cannot open public admission.

**Transitional-seam budget:** None; the common zero-temporary-runtime-seam rule applies. No successor is asked to remove a knowingly incoherent intermediate state.

**Blast radius:** New opt-in comparison fixture/test source only; frozen aggregation_test.go at 8c34fbac874adf55f096b6c67d51244160169422 stays unchanged. Closed topology enum/configuration, not a general graph language. No host nftables/tc rule, privileged route mutation or production worker.

**Artifact classification:** Verification aids plus process/traceability metadata, with the common payoff/domain/owner/retirement policy; existing shipped behavior and safety enforcement remain unchanged.

**Representation contract:** Typed tuple/topology/rate/delay/backlog input and standard parsed result records, canonical subset of the three named topologies. Native queue timing under load remains example-level. Payload relay is not ECN/ancillary metadata evidence.

**Contract closure:** Not independently triggered: no changed product authority or runtime invariant. This slice provides finite evidence interfaces to the common coverage argument, without recursively proving the aid.

**Evidence budget:** Representative valid topology/queue arithmetic, rejected invalid configuration, distinct/shared queue identity, local UDP route delivery and pending-worker/reader-failure cleanup. No load fidelity/performance campaign or statistical timing repetition. The common review and non-recursion limits apply.

**TDD and preservation evidence:** First test bounded queue admission/drop, unequal rates/delays, shared versus separate bottleneck identity and invalid tuple/configuration; then real UDP round trip and cleanup while work remains. Record delivered bytes/drops independently of configured intent. Do not import retired experimentScheduler or campaign loop.

**Dispatch context budget:** This/common contract; frozen B11 aggregation_test.go queue/UDP/lifetime/tests only, with exact source anchors in audit; new relay interface and tests. No complete BBR program or Python campaign script.

**Slice decision audit:** No blocker: the real UDP interface is independently green. Queue-only prefactoring leaves lifetime untested; merging C4 combines independent concurrency and workload accounting. Both rejected; none: rejected on merit. Reuse a suitable merged macOS relay rather than a parallel copy, retaining this finite retirement contract.

**Stop conditions:** Stop if the relay requires privileged/global network state, unbounded topology syntax, an ECN claim, production scheduler changes or a second queue owner.

### C4 — Bind the matched topology comparison workload

**What it delivers:** Bind C3 topology to current public QUIC and C1 metrics for ordinary BBR path A, ordinary BBR path B, two independent BBR connections and the current two-path aggregate, with the shared-bottleneck ordinary Reno competitor required by the existing criterion. Preserve useful-byte, demand, latency/gap, relay-drop/CPU and realized topology identity. Deliver functional apparatus, not a native performance conclusion.

**Existing-work disposition:** New slice on the merged baseline; retain the existing runtime owners. The common prior-work exclusion and cross-program reuse rule apply.

**Blocked by:** C1, C3

**Single owner after merge:** C3 owns queues; public transport owns paths/controller policy; comparison fixture owns matched arm/demand/phase accounting; C1 owns metrics. Configured intent or sender bytes cannot replace realized useful delivery.

**Authority completeness:** No new persisted product authority or restart format. The common constructor/validation/cleanup/readback contract applies. Receipts cannot open public admission.

**Transitional-seam budget:** None; the common zero-temporary-runtime-seam rule applies. No successor is asked to remove a knowingly incoherent intermediate state.

**Blast radius:** New finite opt-in comparison workload/driver and immediate record/relay integration. Use the public multipath configuration with policy "aggregate" and explicit active paths; never restore retired conf.multipath.experimentScheduler. Preserve uncoupled/no-general-fairness limits and frozen source. No optimizer or imported historical attempt schedule.

**Artifact classification:** Verification aids plus process/traceability metadata, with the common payoff/domain/owner/retirement policy; existing shipped behavior and safety enforcement remain unchanged.

**Representation contract:** Closed arm/topology/controller set, typed public path/configuration and C1/C3 records. Canonical identity/accounting; example-level performance. Relay observations do not qualify packet-info/ECN.

**Contract closure:** Not independently triggered: no changed product authority or runtime invariant. This slice provides finite evidence interfaces to the common coverage argument, without recursively proving the aid.

**Evidence budget:** Representative arm/controller/topology selection, invalid or missing arm/metric/identity, matched demand, useful receiver accounting, paired comparison arithmetic, valid negative candidate verdict versus invalid baseline/comparator, and child/relay failure cleanup; one supported amd64 functional comparison smoke. No gain, fairness or confidence claim follows. The common review and non-recursion limits apply.

**TDD and preservation evidence:** First fail missing control/metric/topology, unequal unlabelled demand and sender-only useful-byte substitution. Check paired arithmetic and ensure a valid negative candidate result stays negative while an invalid baseline/comparator is reported as invalid, never filtered into a passing verdict. Exercise real public supported Linux construction/activation and joined teardown. ARM64 build/refusal stays separate until Q2. Preserve B11 applicable benefit/cost criteria; no new threshold or transferred exception.

**Dispatch context budget:** This/common contract; C1 record interface, C3 relay interface, current public controller/path APIs and frozen B11 metric/control definitions. Exclude retired campaign execution loop and other platform internals.

**Slice decision audit:** C1/C3 are real consumed interfaces. Splitting individual arms leaves no matched comparison; merging the independently usable relay adds unnecessary context. Revisit: none: rejected on merit. P1/P2/C2 are not direct blockers.

**Stop conditions:** Stop on required new topology/metric/threshold, public bypass, peer-pin change, production algorithm repair or inability to fit the comparison consumer in one context.

### Q1 — Approve the concrete native execution protocol

**What it delivers:** Publish one concrete reviewed protocol binding the merged methods to exact candidate identity rules, executable commands, venue/image/kernel/toolchains, native case/role/controller/family inventory, timing/attribution rules, CPU placement, comparable cost criteria and continuing native coverage. Obtain and record the owner’s approval of the actual finite operational scope and any privilege/maintained-aid decisions before completing this child. No qualification campaign runs here. Bind source applicability explicitly: freeze production/build inputs before collection, retain the actual measurement commit and binary/tool identities, and permit only reviewed receipt/support metadata and finite-aid retirement afterward. Never relabel an earlier observation as executed on the final SHA; a changed production/build input invalidates affected evidence. Final local certification and hosted checks still run on the exact final head.

**Existing-work disposition:** New slice on the merged baseline; retain the existing runtime owners. The common prior-work exclusion and cross-program reuse rule apply.

**Blocked by:** E1, P1, P2, C2, C4

**Single owner after merge:** Protocol owns finite command/case/identity mapping; maintainer owns venue/privilege/operational allowance, new continuing CI and any explicit cost exception. Tools report facts; ready labels do not authorize collection.

**Authority completeness:** No new persisted product authority or restart format. The common constructor/validation/cleanup/readback contract applies. Receipts cannot open public admission.

**Transitional-seam budget:** None; the common zero-temporary-runtime-seam rule applies. No successor is asked to remove a knowingly incoherent intermediate state.

**Blast radius:** Protocol and command-correspondence metadata only. No VM mutation, sampler/benchmark launch, budget reset, cloud reservation or runner registration. Native hosted ubuntu-24.04-arm and local guest have distinct roles; verify actual execution identity, not label alone.

**Artifact classification:** Process/traceability metadata. Selected continuing verification aids require the common explicit approval, payoff, domain, owner and retirement record.

**Representation contract:** Finite command/case/identity table and exact approval receipt; standard tool outputs, canonical inventory, example-level native qualification. No generic manifest language or universal kernel/performance claim.

**Contract closure:** Not independently triggered: no changed product authority or runtime invariant. This slice provides finite evidence interfaces to the common coverage argument, without recursively proving the aid.

**Evidence budget:** One source/method-to-command audit and concrete owner decision. Zero native qualification/performance attempts. Select meaningful platform/toolchain distinctions and exact repetitions only when required by an accepted question; do not inherit old six-by-two/36-observation/three-round/quiet-retry budgets automatically. The common review and non-recursion limits apply.

**TDD and preservation evidence:** No code TDD. Bind every row of the safety table to command, expected identity/output and missing-evidence disposition. Include both Go pins, all three policies, independent peer roles, negotiated zero separately, native address-family/packet-info/ECN/offload applicability, E1 current poller/group-yield/timing/pressure distinctions, focused race and BBR protection/recovery, public migration/survivor, C1 mixed/pressure GSO requirements, C2 exact third phase and C4 controls. Put first actual ARM64 poller traversal early in Q2. Preserve 1.10 CPU ratio/10% RSS limits and applicable B11 criteria; amd64 exceptions do not transfer. Bind skip-sensitive continuing native unit/public/focused race and explicitly decide peer matrix/cadence without assuming twice the current campaign.

**Dispatch context budget:** This/common contract and safety/profile tables; leaf readiness interface/limitation receipts and A0 identities transitively; current CI and cost criterion sections. No fixture reimplementation or complete historical campaign. Missing authority is presented as the concrete package, not an abstract permission request.

**Slice decision audit:** Each leaf provides a real executable method or limit required by the protocol. A speculative protocol before those interfaces invites re-derivation; merging Q2 mixes undecided execution authority with activation. Separating inventory from its approval leaves an incomplete contract. Revisit: none: rejected on merit.

**Stop conditions:** Keep Q1 open and Q2 blocked until the concrete venue/privilege/finite inventory/continuing-aid decisions are recorded. If full parity requires a changed product outcome, owner or one-PR boundary, return to handoff/owner decision rather than waive a row.

### Q2 — Qualify and activate the complete Linux ARM64 profile

**What it delivers:** On one unmerged feature candidate, extend the common capability gate to Linux ARM64, update independent root/HTTP3 acceptance/refusal expectations, run Q1’s exact native protocol, and merge the gate, acceptance tests, approved continuing native CI, support receipt, README/usage and new release entry together. All three accepted controller/policy combinations must qualify. Missing, invalid or unacceptable evidence leaves activation unmerged. After retaining the accepted raw evidence, this same PR retires the finite C3/C4 execution apparatus unless Q1 records explicit continued-maintenance approval; preserve reused tooling still owned by another active accepted program, and retire only the ARM64-specific finite entrypoints in that case.

**Existing-work disposition:** New slice on the merged baseline; retain the existing runtime owners. The common prior-work exclusion and cross-program reuse rule apply.

**Blocked by:** Q1

**Single owner after merge:** Common capability decision owns platform eligibility; native grant installer owns socket/duration/authority; enabled admission owns Config/controller/policy/version; existing endpoint/connection/recovery owners retain runtime state. Qualification facts inform the maintainer’s support decision, never become a runtime side channel.

**Authority completeness:** No new persisted product authority or restart format. The common constructor/validation/cleanup/readback contract applies. All grant/constructor/server-selected entrypoints and their actual input checks ship with activation.

**Transitional-seam budget:** None; the common zero-temporary-runtime-seam rule applies. No successor is asked to remove a knowingly incoherent intermediate state.

**Blast radius:** Platform predicate/helper, support comments/errors, root/HTTP3 test applicability, approved CI, support metadata and the declared finite comparison-aid retirement. Review the bounded post-collection diff for unchanged qualified production/build inputs, retaining the actual evidence source identity. Preserve then-current accepted macOS/other-platform behavior if it has merged, with no cross-program prerequisite. No endpoint timing/algorithm/backend redesign, performance optimization or peer update fits this slice.

**Artifact classification:** Shipped behavior and required support enforcement for admission; verification aids for tests/approved CI; process metadata for receipts and publication.

**Representation contract:** Typed GOOS/GOARCH and existing Config/socket validators define the finite support partition. No new compiler-version parser or kernel allowlist. Independent table expectations cover declared partitions; native timing/performance is bounded example-level evidence from the approved venue.

**Contract closure:** The common bounded native safety/admission coverage argument applies at the named enforcement owners; no recursive harness closure.

**Evidence budget:** Exactly Q1’s approved native operational inventory, local platform/configuration regression cases against the recorded exact qualification candidate, with only Q1-approved source-inert retirement/metadata changes afterward; final local certification and existing applicable hosted jobs use the exact final head. One initial review and at most one replacement. No extra attempts, broader platform evidence or repeated collection without the governing decision. The common review and non-recursion limits apply.

**TDD and preservation evidence:** First write independent expected-platform/entrypoint tests failing for ARM64 admission while preserving Linux amd64 and other established outcomes; test explicit/owned grants, constructor/server-selected configuration, setter orders/clones, v2/Reno aggregate refusals and ordinary v2/default-off/HTTP3 preservation. Execute Q1 endpoint/poller/borrow/race/BBR/public lifecycle/peer/cost/memory/topology cases, separating attribution from untraced deadline timing and pressure. Missing required cases/skips fail readiness. Require fresh both-role aggregate ingress, selected compiler/image/socket identities and current native software-yield evidence. Document limitations honestly.

**Dispatch context budget:** This/common contract; Q1 approved exact protocol and readiness interfaces; current common capability/grant/admission sections, public/root/HTTP3 tests, selected CI and support docs. Exclude fixture internals and campaign history unless diagnosing a concrete accepted failure. A runtime repair invalidates this small activation-context claim.

**Slice decision audit:** Q1 is the actual authority/evidence dependency and transitively covers tooling. Splitting activation from tests/evidence/CI/support leaves an unsupported public interval; none: rejected on merit. Splitting by controller violates full parity; revisit only on explicit owner decision. A separate helper-only prefactor has no necessary independently delivered behavior.

**Stop conditions:** Stop on failed/missing native traversal, required family/offload evidence, unaccepted cost, changed venue without applicability, expired authority, widened runtime ownership/representation or inability to preserve one PR. Diagnose before reruns. Do not relax tolerance, silently narrow support or treat historical exceptions as ARM64 approval.

## Acceptance criteria and validation gates

- Each readiness child delivers its stated usable interface and named terminating evidence; missing prerequisites or skipped cases do not complete it.
- Public Linux ARM64 admission remains closed until Q2, which preserves the accepted full-parity profile and then-current supported platforms.
- Q1 records a concrete approved protocol before Q2 is ready; no campaign, operational allowance or new continuing CI is inferred from this handoff.
- Q2 merges admission, independent acceptance tests, approved continuing native coverage and support publication together after exact-candidate evidence is accepted.
- Every declared slice maps once to a plan contract, child issue, intended PR and OmniFocus task; administrative readiness remains distinct from code-head certification.

Universal words in these criteria range over the ten declared slices and finite typed semantic partitions above, with their named owners and terminating evidence. Native/platform/performance observations remain example-level. This documentation publication terminates at source correspondence, all slice fields/edges, relative links and no unauthorized runtime change, using the shared review allowance.

For Go changes run affected-package tests, go vet on those packages and go mod tidy -diff when applicable; use the specifically selected race/native gates. For Python/C adapters run the named finite accounting/compile/smoke checks and preserved amd64 controls. Derive exact commands in each child's preflight from its accepted named tests/current interfaces. Never invoke an entire historical campaign merely because its filename resembles the slice.

## Operating discipline

The shared [review-loop](https://github.com/the-sarge/skills/blob/main/_shared/REVIEW-LOOP.md) and [contract-closure](https://github.com/the-sarge/skills/blob/main/_shared/CONTRACT-CLOSURE.md) baselines supplied by $implement-architecture-slice govern, composed with the [repository execution overlay](../REVIEW-LOOP.md). Use the shared design-cost reference for re-audit. Their representation/artifact gates, finite evidence/review limits, semantic-family closure, precise-root side-by-side comparison, review/verification-aware approach stops, exact-head local certification, same-head hosted checks, merge/journal/tracking and diagnosis-before-rerun rules apply directly; no repository baseline copy is created.

For this handoff, complete independent slice audits before committing, then the Standards/Spec preparation and full configured RAS review through the installed skills. Repository ordinary workflows run on draft PRs; complete review and clean exact-head local docs certification before marking ready. Require applicable checks successful on that exact live head, verify current base and squash with head matching. No Go tests, native workload or implementation dispatch belongs to this documentation run. Issues/mirrors follow verified default-branch publication only.

Each future child owns its plan/index completion and affected successor frontier in the same PR before review. After exact-head merge, record the hosted development-journal completion account, reconcile child/parent/tracker dependencies and OmniFocus, then complete the slice task. Do not add a routine administrative third PR or duplicate plan SHA in OmniFocus. The operator chooses dispatch, one fresh agent per verified frontier child using $implement-architecture-slice; parent issues are not implementation requests.
