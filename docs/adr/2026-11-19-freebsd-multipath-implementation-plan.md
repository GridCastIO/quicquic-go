# FreeBSD multipath implementation plan

**Date:** 2026-11-19. **Track:** MP-FBSD, one track in [MP-FBSD-20261119](2026-11-19-freebsd-multipath-program.md). **Status:** Accepted handoff; not yet implemented; no implementation dispatched. **Parent issue:** pending. **Normative scope:** Current slice contracts, preserved profile, evidence, dependencies and stop conditions. **Audit history:** [Handoff audit](../audits/2026-11-19-freebsd-multipath-handoff/README.md); [planning PR #1482](https://github.com/GridCastIO/quicquic-go/pull/1482). The completed [planning issue #1398](https://github.com/GridCastIO/quicquic-go/issues/1398) stays closed.

## Outcome and authority

Deliver the [accepted FreeBSD profile](2026-11-19-freebsd-multipath-plan.md): native amd64 and arm64, QUIC v1 draft-21, Reno primary/backup, experimental BBRv3 primary/backup and experimental BBRv3 aggregate, at most two active or validating paths including path zero. Preserve defaults, ordinary QUIC v1/v2, socket/grant ownership, deadline/resource limits and experimental BBR status. FreeBSD 386/arm, full BBR qualification, another backend, higher path counts, offload/grouping optimization and unrelated platform programs are non-goals.

This document replaces the broad F0–F4 planning units with fourteen context-sized child contracts. V1 covers venue execution readiness; S1–S3 name the known production prerequisites; E1–E3 cover native endpoint evidence methods; P1/P2 cover native peer execution and fresh STREAM evidence; C1–C3 adapt shared measurement methods; Q1 binds the concrete protocol and required owner decisions; Q2 alone changes public admission with evidence, continuing coverage and support publication. A child is one intended PR and one fresh implementation context.

This handoff publishes documents and pointers only. It authorizes no implementation dispatch, guest workload, provisioning, privileged sampler, qualification run or campaign allocation now. A later dispatch permits that child's bounded development checks, including explicitly named real-socket or ordinary-handshake smoke through infra. Qualification, pressure and comparative entrypoints remain opt-in and outside ordinary development-test selection. Q1 must obtain the already-required concrete operational/applicability/CI decisions before Q2. Historical campaign allowances and Linux cost exceptions do not transfer.

## Current shape and source-grounded decisions

Repository facts were inspected at `65d082610de7d46b8830d97142d9fd5c6219f3b6`; line anchors below refer to that source. Revalidate changed interfaces at execution preflight, without importing complete historical plan versions.

| Fact and source | Decision and consequence |
| --- | --- |
| `multipath_api.go:118,122` rejects FreeBSD; `native_transport.go:25` already grants privately; `http3/multipath_test.go:21` has a separate Linux predicate | Readiness uses existing private root-test seams. Q2 changes one capability owner plus independent public/root/HTTP3 expectations; no fake OS identity or production bypass. |
| `sys_conn_df.go:1,9,14` supplies false DF and size-error stubs; `native_ordinary.go:869,882,922` consumes size classification before recovery/path failure | S1 classifies definite EMSGSIZE through existing completion/recovery; S2 adds truthful DF capability separately. They are different invariants, despite sharing an initial file. |
| `connection.go:1263` and `multipath_admission.go:551` start first/additional-path PMTU only with DF | Enabling the helper affects ordinary FreeBSD PMTU too; S2 explicitly preserves opt-out and fallback behavior, tests both finder owners, and cannot manufacture capability from option acceptance alone. |
| `sys_conn_oob.go:123` requests packet info for wildcard sockets; `:475` delegates IPv4 source emission to x/net; `sys_conn_helper_freebsd.go:23` decodes a four-byte destination | S3 adds the missing FreeBSD IPv4 control at the existing packet-info owner, preserving specifically bound sockets and IPv6/mapped controls. Do not use Linux in_pktinfo layout. |
| Pinned x/net v0.61.0 `ipv4/sys_freebsd.go:23` omits ctlPacketInfo; pinned x/sys v0.49.0 exposes IP_SENDSRCADDR, IP_DONTFRAG and IPV6_DONTFRAG on both selected architectures | Use the kernel ABI and x/sys control-message constructors for the finite address body, without a new wire parser or upstream dependency fork. |
| `native_endpoint.go:1349,1388` serializes deadline/write/reset; the short software-DATAGRAM yield is Linux-only; `packet_emission.go:240` groups automatically only on Linux ordinary non-BBR/non-path-credit work | FreeBSD remains scalar. E1 labels constructed software groups separately; E3 observes the scalar route without inheriting the Linux yield or historical fairness deficiencies. |
| `multipath_picoquic_matrix_test.go:391,399` has fresh sent STREAM counters and whole-stream echo, but cumulative receive counters; `:589` retains unequal-PMTU expectations | P2 adds fresh transport-delivery attribution to byte-carrying packets on both active paths while retaining exact useful-content echo. Q2 preserves the unequal-MTU case; neither sent counters nor echo alone proves each path delivered fresh bytes. |
| `interop/multipath/peer.c:217,222` exposes received DATAGRAM path separately from requested echo path; `:325` assumes Linux MSG_TRUNC behavior | Reuse the shared fresh DATAGRAM witness and native peer work through explicit external child dependencies; FreeBSD still needs native build/tuple/truncation evidence. |
| `ordinary_cost_test.go:90` restricts BBR to stateless pressure; `interop/multipath/ordinary_cost.py` uses Linux metrics | Adopt the shared controller-matched workload/metric interface, add FreeBSD producers, and retain useful background delivery, offered traffic and truthful unavailable fields. |
| Infra has both VM targets, static doctors and a bounded candidate-driver/artifact interface; no project self-hosted runner is registered | V1 delivers a project workload adapter through the m4mini controller. Infra remains sole VM/lock/restore/process-lineage owner. Q1 chooses concrete continuing CI authority; Q2 delivers it. |

The selected guest metadata names FreeBSD source commit `893c7c99b60dd500a1ad30de667713e2400de15a`. Its [UDP control/output owner](https://github.com/freebsd/freebsd-src/blob/893c7c99b60dd500a1ad30de667713e2400de15a/sys/netinet/udp_usrreq.c#L907), [mapped IPv4 dispatch](https://github.com/freebsd/freebsd-src/blob/893c7c99b60dd500a1ad30de667713e2400de15a/sys/netinet6/udp6_usrreq.c#L760) and [IPv6 option owner](https://github.com/freebsd/freebsd-src/blob/893c7c99b60dd500a1ad30de667713e2400de15a/sys/netinet6/ip6_output.c#L3217) distinguish IPv4 INP_DONTFRAG from IPv6 IP6PO_DONTFRAG. An AF_INET6 UDP socket delegates option handling to ip6_ctloutput; mapped sends enter the IPv4 sender. Therefore an accepted IPV6_DONTFRAG call is not evidence of IPv4-mapped DF. S2 must keep a dual-stack socket's global DF capability false unless the selected native evidence establishes protection for every family it can send. The existing single boolean cannot truthfully describe a partly protected socket. This is a concrete applicability constraint, not approval to reduce the feature target: Q1 must record the maintainer's decision on the actual admitted socket-family domain or a separately scoped repair; Q2 remains blocked without it. No new socket, kernel patch or per-family runtime capability redesign is silently included.

The same kernel's [IP_SENDSRCADDR path](https://github.com/freebsd/freebsd-src/blob/893c7c99b60dd500a1ad30de667713e2400de15a/sys/netinet/udp_usrreq.c#L1233) consumes an IPv4 address, while IPv6/mapped packet info follows its existing distinct path. These source facts guide S3; native secondary-address reply and specifically-bound controls still determine acceptance. Local source inspection is not a guest runtime receipt.

## Existing work and shared dependencies

Retain the merged endpoint, recovery, scheduler and packet-info owners. No FreeBSD implementation child exists yet. [PR #1295 — scalar deadline experiment](https://github.com/GridCastIO/quicquic-go/pull/1295) remains Draft/unselected historical work; it is neither a baseline nor a dependency. The closed [issue #1285](https://github.com/GridCastIO/quicquic-go/issues/1285) disposition remains authoritative. Do not merge, close or rework it incidentally.

Reuse the accepted shared tooling contracts below instead of creating parallel maintained fixtures. An external child is a blocker until its implementation is merged and its completed interface is checked against this consumer contract. Open PRs are evidence to audit, not established code. The [handoff audit](../audits/2026-11-19-freebsd-multipath-handoff/README.md) records inspected diffs and relevant unresolved/re-audited history. No macOS qualification or activation child is a dependency, and this run does not rebaseline that program.

| External child | Reused contract | FreeBSD consumer |
| --- | --- | --- |
| [MP-MAC-P1 (#1488)](https://github.com/GridCastIO/quicquic-go/issues/1488) | Pinned native peer build identity, ordinary control, explicit tuples, portable truncation and matrix discovery | P1 adds FreeBSD profiles and offline infra dependency packaging. |
| [MP-MAC-P2 (#1489)](https://github.com/GridCastIO/quicquic-go/issues/1489) | Fresh post-activation DATAGRAM receipt and both-active phase | P2 adds the distinct fresh STREAM transport-delivery witness to that phase. |
| [MP-MAC-C1 (#1490)](https://github.com/GridCastIO/quicquic-go/issues/1490) | Matched Reno/BBR workload wiring and typed units/source/availability records | C1 adds FreeBSD CPU/RSS/host producers and native ordinary controls. |
| [MP-MAC-C2 (#1491)](https://github.com/GridCastIO/quicquic-go/issues/1491) | Public negotiated lifecycle-memory workload and typed lifecycle samples | C2 adds FreeBSD live-resident observations and profile applicability. |
| [MP-MAC-C4 (#1493)](https://github.com/GridCastIO/quicquic-go/issues/1493) | Matched topology/control comparison, consuming the [shared relay (#1492)](https://github.com/GridCastIO/quicquic-go/issues/1492) | C3 adds the FreeBSD execution/metric binding and native relay smoke; no relay fork. |

These are genuine consumed interfaces, not ordering based on shared files. If an external contract changes materially or is abandoned, re-audit the affected consumer and choose a replacement explicitly; do not mark the blocker complete from a draft branch or copy its partial code. Preserve the external child's ownership and review loop. The FreeBSD program mirrors no external child as a second implementation task.

## Owners, representation and finite evidence

The endpoint owns admission, queued expiry, immutable submission facts, storage custody and writer join; its sole writer owns native write/deadline/reset. Connection/path owners decide PMTU, recovery, path state and congestion behavior from those facts. A canceled observer does not cancel native work. One connection's detachment differs from transport-wide grant return. Existing exact unconnected UDP socket requirements and configuration conflicts remain intact.

The infra controller owns candidate transfer, artifact admission, guest process lineage, VM locks/restoration and cleanup facts. A project driver consumes the selected target and emits workload facts only. No copied VMX paths, SSH discovery, process sweeps, second timeout supervisor or fallback network download belongs in project code. Actual workload binary identity binds the selected toolchain: GOTOOLCHAIN=local, GOVERSION checked, and runtime.Version/build information in the receipt.

S1–S3 change shipped FreeBSD socket behavior and associated safety enforcement at existing owners; the native/public admission gate stays closed. E/P/C apparatus and development tests are verification aids; plans, results and support records are traceability metadata. Maintained aids have the explicit payoff of detecting the named socket, ownership, delivery or measurement regression; domain is the two selected architectures and each slice's finite named semantic cases; owner is the transport test/interop maintainer, with infra owning VM lifecycle; retirement is equivalent replacement or removal of the supported profile while preserving historical receipts. Q1 records explicit approval before any selected continuing aid becomes a required CI gate. Optional diagnostic completeness does not block shipped behavior.

Use typed Go socket/results, kernel-defined ABI fields, net/netip address classification and standard JSON parsers for named producer records. Versions/profiles/case IDs form a mechanically checked finite subset. Unknown/missing/mismatched identities and required cases cannot pass. Tables partition declared helper/admission inputs; native timing/delivery/performance observations remain example-level evidence. There is no universal kernel, scheduler, parser or fixture-completeness claim. No new persisted product fact or restart format becomes authoritative.

The inherited evidence boundary is one representative positive per named behavior and one negative per materially distinct named failure/owner; at most one central-guard mutation only when needed to show inherited coverage exercises that guard. No syntax-alias mutation program, statistical repeat count, platform cross-product or repeat-until-pass loop is added. Native code/ABI adapters require development checks on both selected architectures because those are distinct accepted platforms; portable accounting tests execute once per changed interface. Applicable existing hosted inventories remain unchanged. Each child has one initial RAS review and at most one replacement. Q1 alone binds qualification windows, exact toolchain applicability, operational attempts and any privileged method to the owner's concrete decision.

Deterministic adapters catch ownership/classification and miss the kernel. Real socket/ordinary controls catch native integration and miss negotiated multipath. Supported Linux controls exercise shared negotiated fixtures and do not qualify FreeBSD. Q2 executes the actual FreeBSD public activation candidate; a private-grant test cannot replace it. Native amd64 race coverage needs cgo/compiler; native arm64 uses explicit concurrency/lifecycle tests because the pinned race detector does not support it. Frozen Linux/managed-ECN receipts are applicability references only.

## Safety and activation coverage argument

Closure applies to the materially risky changed socket/admission invariants and existing ownership obligations, not recursively to fixture completeness. Preserve these semantic partitions; this is a finite coverage argument, not enumeration of every kernel state.

| Invariant and owner | Semantic classes and disposition | Terminating evidence |
| --- | --- | --- |
| Definite size rejection stays local/unsubmitted at FreeBSD classifier and connection completion | Wrapped EMSGSIZE; unrelated errno; current tuple; stale tuple; PMTU probe versus reliable data | S1 independent classification/completion regressions, preserved path usability and fitting reliable successor. No replay of accepted/uncertain prefixes. |
| DF capability is truthful for the socket at setDF; PMTU remains connection/path-owned | AF_INET; IPv6-only; dual-stack mapped/native; option failure; explicit discovery opt-out | S2 native option/error and datagram checks plus first/additional finder tests; incomplete family protection leaves capability false. Q1 resolves applicability; Q2 preserves unequal-PMTU both-role evidence. |
| Source control is emitted from the packet-info owner without changing socket ownership | Wildcard IPv4 at non-default local address; specifically bound IPv4; IPv6; admitted mapped traffic; invalid/no packet info | S3 kernel-ABI construction and native observed reply source, ordinary controls and metadata/ECN preservation. |
| Actual native borrow owns storage/deadline until return at endpoint writer | Pre-dispatch expiry; independent queued expiry during current write; return/reset; overdue borrow; close/join; late fact | E1/E2 use existing assertions; required poller traversal is distinct from injected errno and from pressure. Native execution is recorded by the accepted protocol. |
| Native endpoint pressure/diagnostics do not invent delivery or block progress | Scalar contention; refusal; negative pressure observation; real wait/error; blocked diagnostics | E3 useful survivors and bounded observations; absence is reported honestly. |
| Path/connection owners preserve lifecycle and BBR feedback | Validation, migration/rebinding, stale ACK/error, abandon/reopen, detached connection with surviving peer, per-path BBR samples/credit/PMTU/protected storage | Q1 binds existing deterministic suites and required native cases; C2 observes exact typed states, not a retired/not-retired shorthand. |
| Both active paths deliver fresh work | DATAGRAM actual callback ingress; STREAM transport acknowledgment tied to fresh byte-carrying packet identity plus exact application echo; live/active for the whole measured phase | Shared DATAGRAM witness plus P2; wrong path, stale/duplicate/inactive or uncorrelated evidence fails. |
| Public support has one finite capability owner with existing input owners | Explicit grant; owned grant; client/server and server-selected Config; HTTP/3; ordinary early return/v2; admitted/refused kernel/architecture/family; controller/policy/path/resource conflicts | Q2 independent expected-support tables and real public native peer/HTTP3 tests. Explicit grant tests do not pretend to validate Config fields they do not take. |

S1 and S2 share a source file initially but do not share an exact invariant or enforcement seam: errno classification and socket DF capability have distinct input domains and outcomes. No repeated-root stop is inferred merely from the shared file. Future findings use the shared precise invariant-and-owner comparison before any approach conclusion.

## Slice graph

| Slice | State/disposition | End-to-end outcome | Blocked by | Temporary seam |
| --- | --- | --- | --- | --- |
| V1 | New; frontier | Restored-guest candidate execution and identity | None | None |
| S1 | New; blocked | FreeBSD definite-size rejection and recovery | V1 | Existing false DF retained until S2 |
| S2 | New; blocked | Truthful FreeBSD DF capability and per-path PMTU | S1 | None |
| S3 | New; blocked | FreeBSD wildcard IPv4 reply-source control | V1 | None |
| E1 | New; blocked | Native scalar endpoint and metadata fixture | V1 | None |
| E2 | New; blocked | Go poller traversal and active-borrow lifecycle method | E1 | None |
| E3 | New; blocked | Scalar contention and pressure observation | E1 | None |
| P1 | New; blocked | FreeBSD native peer packaging and ordinary control | V1, [#1488](https://github.com/GridCastIO/quicquic-go/issues/1488) | None |
| P2 | New; blocked | Fresh per-path STREAM transport-delivery witness | [#1489](https://github.com/GridCastIO/quicquic-go/issues/1489) | None |
| C1 | New; blocked | FreeBSD ordinary workloads and truthful metric records | V1, [#1490](https://github.com/GridCastIO/quicquic-go/issues/1490) | None |
| C2 | New; blocked | FreeBSD negotiated lifecycle-memory observations | C1, [#1491](https://github.com/GridCastIO/quicquic-go/issues/1491) | None |
| C3 | New; blocked | FreeBSD topology-comparison execution binding | C1, [#1493](https://github.com/GridCastIO/quicquic-go/issues/1493) | None |
| Q1 | New; blocked | Approve the concrete native execution and applicability protocol | S2, S3, E2, E3, P1, P2, C2, C3 | None |
| Q2 | New; blocked | Qualify and activate FreeBSD public multipath | Q1 | None |

V1 is the initial FreeBSD frontier. Its native workload/identity seam is needed for S1, S3, E1, P1 and C1. S2 follows S1 because turning on DF makes local size rejection a normal recovery path. E2/E3 consume E1 independently. The explicit external interface dependencies above keep P2 and the shared-tool consumers blocked until real implementation is merged; none depends on macOS Q1/Q2. Q1 consumes the eight leaf outputs; Q2 consumes its approved protocol. Coordinate shared files with ordinary merges, not extra convenience edges.

## Implementation slices

### V1 — Restored-guest candidate execution and identity

**What it delivers:** Add one project candidate-driver adapter and runbook that use the existing infra target interface for freebsd-amd64 on minimax and freebsd-arm64 on mbp128 through m4mini. A restored guest executes a minimal ordinary QUIC/socket control and returns candidate/tree, actual binary Go identity, kernel/userland, architecture, selected address families and workload status alongside the existing infra cleanup receipt. Establish the primary Go 1.27.4 route and concrete Go 1.26.11 delivery/selection prerequisites; an unavailable second toolchain is explicitly unresolved for Q1, never relabeled as exercised. Select two existing local IPv4 addresses for the wildcard-source regression without changing host networking. Inventory C/peer/tracer/metric availability without installing it.

**Existing-work disposition:** New FreeBSD child. Retain the merged runtime owners; consume only completed, rechecked shared dependencies. No source branch is an established baseline.

**Blocked by:** None

**Single owner after merge:** Infra remains sole lifecycle, candidate/artifact, process-lineage and cleanup owner; the project driver owns its finite workload result. The guest/kernel and compiled binary own observed identities.

**Authority completeness:** No new persisted product authority. Test-owned constructors/record validation/readback and child/socket cleanup are covered at the aid interface; results never change public admission themselves.

**Transitional-seam budget:** None. No duplicate runtime state, temporary production bypass or second lifetime owner is introduced.

**Blast radius:** Project script/runbook and ordinary socket control only. Restored guest development invocation is within the future child; no baseline replacement, package installation, guest network fallback, host reservation, runner registration or copied infra controller. A missing infra capability is a named external prerequisite, not a project workaround.

**Artifact classification:** Verification aid plus process/traceability metadata under the common maintained-deliverable payoff/domain/owner/retirement contract. Shipped behavior and safety enforcement are unchanged.

**Representation contract:** Infra validates its existing canonical manifests. Project JSON validates the finite two-target workload/identity/status record using a standard parser; native control is example-level readiness, not qualification.

**Contract closure:** No recursive closure of the verification aid. It supplies the named finite semantic evidence while production enforcement remains at the existing owners.

**Evidence budget:** One positive ordinary control per selected target on the primary installed toolchain, plus malformed/mismatched candidate/binary/target/status and interruption-cleanup adapter cases. No qualification, pressure or timing samples. Read-only secondary-toolchain and native-tool inventory. The common mutation/platform/review boundary applies.

**TDD and preservation evidence:** First characterize adapter success/failure and ensure a failed workload or missing cleanup receipt cannot pass. Then use the real candidate-driver interface for the ordinary control on both restored guests. Keep artifact/network limits explicit; unavailable native prerequisites keep the affected consumer blocked.

**Dispatch context budget:** This/common contract; the accepted venue table; infra target/runbook candidate-driver interface at ac57fb5418b9fc5dcf5088ca377f71d421bb633d; existing ordinary constructor/socket smoke. No infra implementation or whole historical campaign. This is one bounded owner/adapter consumer change; a broader implementation returns to the slice audit.

**Slice decision audit:** Splitting an identity-only script from its real guest consumer leaves a horizontal contract with no end-to-end proof; rejected on merit. Splitting by architecture duplicates one adapter and infra-owned lifecycle; rejected unless native behavior demands a different project interface. Merging E1 would mix VM invocation with endpoint semantics. No blocker: both static targets and the candidate-driver interface already exist. Revisit rejected split/merge choices only on the stated trigger; otherwise none: rejected on merit. The existing state owner's direct design is retained; test adapters carry facts and never move policy into another execution context.

**Stop conditions:** Keep the child open if primary native execution or cleanup cannot complete. Escalate concrete missing infra authority instead of editing infra or provisioning. Missing Go 1.26.11 or peer tools blocks their later required use and Q1, not a false claim that V1 supplied them.

### S1 — FreeBSD definite-size rejection and recovery

**What it delivers:** Implement FreeBSD send-side EMSGSIZE classification using errors.Is through the existing syscall-error boundary. Preserve receive-side semantics. Trace the result through ordinary/native completion so a definite local size rejection remains unsubmitted, reaches the existing handshake/PMTU recovery owner and does not falsely mark the current multipath tuple suspect. Add fitting reliable successor and stale-tuple assertions; public FreeBSD admission stays closed.

**Existing-work disposition:** New FreeBSD child. Retain the merged runtime owners; consume only completed, rechecked shared dependencies. No source branch is an established baseline.

**Blocked by:** V1

**Single owner after merge:** The FreeBSD errno helper classifies local facts; connection completion and existing handshake/PMTU/path owners decide effects. No writer-to-policy side channel.

**Authority completeness:** No persisted product authority or restart schema is added. Cover setup/constructors, validation, every changed ordinary/native consumer, failure and cleanup at the named owner in this same slice; no new capability may outrun its consumer evidence.

**Transitional-seam budget:** Retain the existing false FreeBSD DF behavior while separating its OS-specific helper from the generic stub; this is unchanged behavior, not a new authority. S2 owns its replacement after size recovery is safe.

**Blast radius:** FreeBSD socket/error helpers and focused completion tests. The OS-specific classifier also affects ordinary FreeBSD on compiled 386/arm targets; their build coverage remains, with no multipath claim. No recovery algorithm, retry policy, generation fence or public error contract change.

**Artifact classification:** Shipped behavior and required safety enforcement at the named existing owners; focused tests are verification aids and receipts are traceability metadata. The common maintained-aid boundary applies without recursive closure.

**Representation contract:** Typed wrapped error chains; errors.Is owns unwrapping. Finite EMSGSIZE/non-size partitions and current/stale tuple outcomes, with native examples on both selected architectures.

**Contract closure:** The relevant named rows of the safety/activation coverage argument apply. Keep the precise invariant, owner and semantic partitions bounded; no syntax-variant or unrelated-owner matrix.

**Evidence budget:** Positive bare/wrapped EMSGSIZE and one unrelated errno, current versus stale tuple completion, fitting reliable successor and applicable existing handshake/PMTU regressions; native selected-architecture tests via V1. No injected error is called a kernel-produced errno. The common mutation/platform/review boundary applies.

**TDD and preservation evidence:** Write failing FreeBSD classification and completion tests first, including no sendFailed for the current tuple and continued usable-path reliable delivery. Retain accepted/uncertain prefix and old-tuple behavior. Use existing native_ordinary_completion_test.go and mtu_discoverer_test.go seams; they miss real kernel pressure.

**Dispatch context budget:** This/common contract; sys_conn_df.go; native_ordinary.go completion/completePacket; handshake-size feedback and focused native completion/MTU tests. V1 command/result interface only. This is one bounded owner/adapter consumer change; a broader implementation returns to the slice audit.

**Slice decision audit:** V1 is necessary for native execution/identity. Splitting the classifier from its completion consumer could merge a false recovery claim; rejected on merit. Merging S2 couples error semantics with a distinct socket-option capability and ordinary PMTU behavior; rejected on merit. Revisit rejected split/merge choices only on the stated trigger; otherwise none: rejected on merit. The existing state owner's direct design is retained; test adapters carry facts and never move policy into another execution context.

**Stop conditions:** Stop if correct handling needs a new recovery owner, changes to accepted/uncertain facts, new public behavior beyond the stated local-size correction or a different one-PR boundary.

### S2 — Truthful FreeBSD DF capability and per-path PMTU

**What it delivers:** Add the FreeBSD DF helper at the existing socket owner and preserve PMTU startup at the first/additional-path owners. Select AF_INET versus IPv6-only from the actual socket and IPV6_V6ONLY observation. Preserve capability=false for a dual-stack socket unless native evidence establishes DF for mapped and native sends; the selected kernel source currently gives no basis for such a claim. Do not set a global capability true merely because IPV6_DONTFRAG succeeded. Retain DisablePathMTUDiscovery and the unequal-MTU peer assertion.

**Existing-work disposition:** New FreeBSD child. Retain the merged runtime owners; consume only completed, rechecked shared dependencies. No source branch is an established baseline.

**Blocked by:** S1

**Single owner after merge:** Socket setup owns the capability fact; connection.startMTUDiscovery and pathCreditRegistry.startPMTU own finder startup. No per-path duplicate capability state or new socket is added.

**Authority completeness:** No persisted product authority or restart schema is added. Cover setup/constructors, validation, every changed ordinary/native consumer, failure and cleanup at the named owner in this same slice; no new capability may outrun its consumer evidence.

**Transitional-seam budget:** None. No duplicate runtime state, temporary production bypass or second lifetime owner is introduced.

**Blast radius:** FreeBSD socket initialization and ordinary PMTU become functional in the evidenced family domain before multipath activation. Failed/unsupported setup retains truthful fallback. The dual-stack limitation remains explicit for Q1. No Linux/Darwin/Windows change, packetization bound relaxation or new public API.

**Artifact classification:** Shipped behavior and required safety enforcement at the named existing owners; focused tests are verification aids and receipts are traceability metadata. The common maintained-aid boundary applies without recursive closure.

**Representation contract:** Kernel socket family/options through x/sys, with the existing bool meaning protection for the whole admitted socket. Closed family/success/failure/opt-out partitions; actual network behavior remains native example-level evidence.

**Contract closure:** The relevant named rows of the safety/activation coverage argument apply. Keep the precise invariant, owner and semantic partitions bounded; no syntax-variant or unrelated-owner matrix.

**Evidence budget:** AF_INET and IPv6-only option/oversize/fitting-send controls on both architectures where the existing local interface MTU permits a non-privileged oversize observation; record a concrete blocker if it cannot. Dual-stack mapped/native controls must not certify unsupported DF. Deterministic first/additional finder, explicit opt-out and option-error cases; full unequal-route qualification waits for Q2. The common mutation/platform/review boundary applies.

**TDD and preservation evidence:** First fail independent capability-table and finder-start expectations. Then demonstrate definite size rejection and fitting delivery without fragmentation on the selected native local routes; reuse S1 recovery. Do not change guest MTU, routes or host network policy implicitly. Native family behavior and syscall identity must be recorded separately from the deterministic tests.

**Dispatch context budget:** This/common contract and S1; sys_conn_df* helpers, connection.go startMTUDiscovery, multipath_admission.go startPMTU, TestPathMTUDiscoveryOnSelectedPath and MTU finder tests; the pinned kernel option/output excerpts. This is one bounded owner/adapter consumer change; a broader implementation returns to the slice audit.

**Slice decision audit:** S1 is a genuine prerequisite because enabling DF creates size-error feedback the old helper loses. Splitting option setup from both consumers leaves capability unvalidated; rejected on merit. Merging S3 conflates DF and source selection with different kernel owners; rejected on merit. Revisit rejected split/merge choices only on the stated trigger; otherwise none: rejected on merit. The existing state owner's direct design is retained; test adapters carry facts and never move policy into another execution context.

**Stop conditions:** If the accepted socket domain needs a per-family capability, another socket, kernel change or reduced public profile, stop for a concrete owner decision/scoped re-audit. Q1 must resolve the observed dual-stack applicability before Q2. No false capability or relaxed unequal-MTU assertion.

### S3 — FreeBSD wildcard IPv4 reply-source control

**What it delivers:** Add FreeBSD IPv4 outgoing source ancillary construction at packetInfo.OOB and its platform helper, using the four-byte IP_SENDSRCADDR ABI. Trace packetInfo producers and consumers for ordinary send, granted scalar send and path migration. Preserve specifically bound sockets without unnecessary source override and preserve existing IPv6/mapped packet-info behavior. A wildcard endpoint addressed at the selected non-default local IPv4 address must reply from that address.

**Existing-work disposition:** New FreeBSD child. Retain the merged runtime owners; consume only completed, rechecked shared dependencies. No source branch is an established baseline.

**Blocked by:** V1

**Single owner after merge:** The packet-info/socket metadata owner constructs source control; the kernel owns address validity and source selection. Endpoint/connection owners retain immutable OOB snapshots and route identity.

**Authority completeness:** No persisted product authority or restart schema is added. Cover setup/constructors, validation, every changed ordinary/native consumer, failure and cleanup at the named owner in this same slice; no new capability may outrun its consumer evidence.

**Transitional-seam budget:** None. No duplicate runtime state, temporary production bypass or second lifetime owner is introduced.

**Blast radius:** One platform-specific source-control implementation and focused ordinary/native integration tests. It affects existing ordinary FreeBSD replies as an intentional correctness fix. No new socket, global source-address cache, copied per-call validation or Linux layout assumption.

**Artifact classification:** Shipped behavior and required safety enforcement at the named existing owners; focused tests are verification aids and receipts are traceability metadata. The common maintained-aid boundary applies without recursive closure.

**Representation contract:** netip typed address and kernel-defined in_addr/cmsghdr layout via x/sys constructors. The existing wildcard receive setup owns whether packet info is present. Native observed addresses are the acceptance evidence; no claim follows from accepted options alone.

**Contract closure:** The relevant named rows of the safety/activation coverage argument apply. Keep the precise invariant, owner and semantic partitions bounded; no syntax-variant or unrelated-owner matrix.

**Evidence budget:** Wildcard/non-default-source and specifically-bound IPv4 positive controls, invalid/no packet info, IPv6 and admitted mapped preservation; native reply observations on both architectures through V1, with focused OOB layout and immutable-snapshot tests. No alias/route provisioning or packet-capture campaign. The common mutation/platform/review boundary applies.

**TDD and preservation evidence:** Write the failing peer-observed reply-source case first. Trace specifically bound receive setup (which does not request destination info) and explicit path producers so the new cmsg cannot create EINVAL on bound sockets. Test source-control plus ECN coexistence and preserve IPv6 interface identity. Pure marshaler tests catch ABI construction but miss kernel acceptance.

**Dispatch context budget:** This/common contract; sys_conn_oob.go setup/OOB/WritePacket; sys_conn_helper_freebsd.go; send_conn.go constructors/path writes; native_ordinary.go OOB snapshots; V1 local-address facts and pinned UDP source-control owner. This is one bounded owner/adapter consumer change; a broader implementation returns to the slice audit.

**Slice decision audit:** V1 supplies actual native tuples and result custody. Splitting marshaling from the native wildcard consumer could publish an unverified source fix; rejected on merit. Merging S2 combines independent invariants and expands blast radius; rejected on merit. Revisit rejected split/merge choices only on the stated trigger; otherwise none: rejected on merit. The existing state owner's direct design is retained; test adapters carry facts and never move policy into another execution context.

**Stop conditions:** Stop if correct construction requires changing packetInfo authority, passing a new public socket wrapper, configuring host aliases or redesigning unrelated platform output. A producer that supplies invalid bound-socket metadata must be resolved at its existing owner inside this bounded family or re-audited.

### E1 — Native scalar endpoint and metadata fixture

**What it delivers:** Add an explicitly selected FreeBSD native fixture/driver using the existing private root-test grant. It delivers scalar write, expiry-before-dispatch/successor, metadata/ECN and stop/join cases with exact candidate/architecture/toolchain and case statuses. Label constructed segmentation/retry members as injected writer tests, distinct from production scalar traffic. Include actual ordinary v1/v2 and root/HTTP3 fallback controls while public multipath remains refused.

**Existing-work disposition:** New FreeBSD child. Retain the merged runtime owners; consume only completed, rechecked shared dependencies. No source branch is an established baseline.

**Blocked by:** V1

**Single owner after merge:** The existing endpoint/writer owns writes, deadlines, buffers and join. The fixture owns only its sockets, offered work, observers and records; infra owns process/VM cleanup.

**Authority completeness:** No new persisted product authority. Test-owned constructors/record validation/readback and child/socket cleanup are covered at the aid interface; results never change public admission themselves.

**Transitional-seam budget:** None. No duplicate runtime state, temporary production bypass or second lifetime owner is introduced.

**Blast radius:** Root test fixture, project driver and finite records. No production override, second deadline setter, adopted GSO/GRO/grouping, changed resource limit or host networking. Existing Linux/macOS tooling and frozen receipts remain intact.

**Artifact classification:** Verification aid plus process/traceability metadata under the common maintained-deliverable payoff/domain/owner/retirement contract. Shipped behavior and safety enforcement are unchanged.

**Representation contract:** Typed request/results and standard parsed named case records. Missing/duplicate/skipped cases and identity mismatch fail. Native observations are example-level; injected errors cannot imply kernel occurrence.

**Contract closure:** No recursive closure of the verification aid. It supplies the named finite semantic evidence while production enforcement remains at the existing owners.

**Evidence budget:** One representative named scalar/expiry/metadata/join case per selected architecture plus finite receipt-accounting and interrupted-cleanup negatives. Reuse existing deterministic segmentation/prefix/EPERM-retry assertions; no live pressure or performance campaign. The common mutation/platform/review boundary applies.

**TDD and preservation evidence:** Characterize existing endpoint grant/disposal and metadata helpers first. Test expired-before-dispatch never calls the writer, useful successor progresses and successful join precedes caller socket reuse. Run selected native scalar controls; ECN family rows distinguish IPv4, IPv6-only and admitted mapped/native traffic including disabled control. Missing known source control remains a named S3 prerequisite, not a fixture pass.

**Dispatch context budget:** This/common contract, V1 driver interface, native_endpoint_test.go, native_shutdown_test.go, native_software_segmentation_test.go and relevant OOB helpers; accepted native semantic map only. This is one bounded owner/adapter consumer change; a broader implementation returns to the slice audit.

**Slice decision audit:** V1 is the execution/identity consumer dependency. A runner-only prefactor is horizontal; rejected on merit. E2 needs a distinct current native-borrow witness and E3 permits negative pressure observations, so do not merge them into E1. No S3 edge is necessary to implement independent fixture accounting; the source-selection acceptance remains with S3 and Q2. Revisit rejected split/merge choices only on the stated trigger; otherwise none: rejected on merit. The existing state owner's direct design is retained; test adapters carry facts and never move policy into another execution context.

**Stop conditions:** Keep the fixture open if its promised executable native seam or cleanup cannot work. Do not declare the known S3 failure a successful metadata observation or change runtime owners to make a fixture pass.

### E2 — Go poller traversal and active-borrow lifecycle method

**What it delivers:** Deliver a FreeBSD-native executable method for observing the actual Go write/wait/deadline path and the current native borrow on both architectures. Prefer a demonstrated real kernel trigger; otherwise use a fixture-owned ptrace syscall-boundary method with explicit amd64/arm64 ABI adapters. Demonstrate the method in bounded development observations before declaring readiness; an injected errno without observed internal/poll traversal is insufficient. Reuse that current-write witness for independent queued expiry and active close/join without changing the endpoint.

**Existing-work disposition:** New FreeBSD child. Retain the merged runtime owners; consume only completed, rechecked shared dependencies. No source branch is an established baseline.

**Blocked by:** E1

**Single owner after merge:** Go runtime/kernel own poller traversal; endpoint writer owns deadline/reset and current storage; fixture tracer only controls/observes its own child and joins it. It carries facts, never cancellation or recovery policy.

**Authority completeness:** No new persisted product authority. Test-owned constructors/record validation/readback and child/socket cleanup are covered at the aid interface; results never change public admission themselves.

**Transitional-seam budget:** None. No duplicate runtime state, temporary production bypass or second lifetime owner is introduced.

**Blast radius:** Opt-in test-owned tracing/trigger code and records. Architecture register/errno handling is explicitly different; no tracing unrelated processes, system debugger policy changes, production shim or second socket owner. Trace timing is attribution only; uninstrumented product-bound checks remain Q1/Q2 evidence.

**Artifact classification:** Verification aid plus process/traceability metadata under the common maintained-deliverable payoff/domain/owner/retirement contract. Shipped behavior and safety enforcement are unchanged.

**Representation contract:** Kernel ptrace/syscall ABI and Go stack frames own observations; typed method outcomes distinguish injected trigger, actual poller wait, native return and missing witness. Native method observations are example-level, not a general scheduler guarantee.

**Contract closure:** No recursive closure of the verification aid. It supplies the named finite semantic evidence while production enforcement remains at the existing owners.

**Evidence budget:** One successful method-readiness observation on each selected architecture, plus no-witness, expired-before-dispatch, interrupted tracer and missing-native-return fixture cases. No repeated attempts for confidence or host pressure campaign. Use inherited absolute request deadlines and the infra invocation timeout; inability to obtain the witness keeps the child open. The common mutation/platform/review boundary applies.

**TDD and preservation evidence:** First characterize MemberReturnPrecedesDeadlineReset, QueuedExpiry, OverdueBorrow, ExpiredClaimAndNextDeadline and live-close/join assertions. Test tracer cleanup and outcome classification before native use. Bind active-borrow storage retention, final reset, queued expiry and useful survivor. Select focused native amd64 race tests and arm64 concurrency equivalents for Q1; do not call unsupported arm64 race passed.

**Dispatch context budget:** This/common contract; E1 socket/result/lifetime interface; native_endpoint.go writer/expiry/completion and native_shutdown_test.go; kernel ptrace ABI for the two architectures and the minimal trigger implementation. Do not load historical campaigns or PR #1295. This is one bounded owner/adapter consumer change; a broader implementation returns to the slice audit.

**Slice decision audit:** E1 is necessary for one current-write/receipt lifetime interface. Splitting the two ABI implementations would leave the promised two-target method incomplete unless one becomes a materially different design; then re-slice. Splitting expiry/close into separate PRs duplicates the same borrow witness. Pressure is E3 because a negative pressure result is legitimate while a missing poller witness is not readiness. Revisit rejected split/merge choices only on the stated trigger; otherwise none: rejected on merit. The existing state owner's direct design is retained; test adapters carry facts and never move policy into another execution context.

**Stop conditions:** If native trigger feasibility, required privilege or per-architecture ABI exceeds one fresh context, keep this child open and return for a scoped method/slice decision. Do not implement a runtime bypass or accept a skip. A method change after Q1 needs its protocol applicability rechecked.

### E3 — Scalar contention and pressure observation

**What it delivers:** Extend the FreeBSD scalar fixture with bounded offered-load, lane progress/refusal/occupancy, useful-survivor, error/drop and wait observations. Report whether actual pressure occurred; no observed wait is a valid negative pressure result and cannot replace E2. A blocked diagnostic sink must not stall writers or connection progress.

**Existing-work disposition:** New FreeBSD child. Retain the merged runtime owners; consume only completed, rechecked shared dependencies. No source branch is an established baseline.

**Blocked by:** E1

**Single owner after merge:** Endpoint admission/fairness and result owners decide behavior; the fixture owns offered load and observations. Producers/observers join before their storage and sockets are released.

**Authority completeness:** No new persisted product authority. Test-owned constructors/record validation/readback and child/socket cleanup are covered at the aid interface; results never change public admission themselves.

**Transitional-seam budget:** None. No duplicate runtime state, temporary production bypass or second lifetime owner is introduced.

**Blast radius:** Opt-in fixture observers and records only. No Linux short-group Gosched behavior, affinity/host reservation, privileged network setup or new production diagnostic channel. Native pressure occurrence and VM scheduling remain unverified until observed.

**Artifact classification:** Verification aid plus process/traceability metadata under the common maintained-deliverable payoff/domain/owner/retirement contract. Shipped behavior and safety enforcement are unchanged.

**Representation contract:** Typed endpoint facts and native producer observations with explicit availability. Scalar production, constructed groups, induced wait and real pressure are distinct record classes; missing data is unknown, not zero.

**Contract closure:** No recursive closure of the verification aid. It supplies the named finite semantic evidence while production enforcement remains at the existing owners.

**Evidence budget:** Finite synthetic accounting/contention/diagnostic-saturation and interruption tests plus native non-pressure scalar smoke on both architectures. Actual pressure inventory and uninstrumented timing are Q1/Q2 work; no retry-until-pressure procedure. The common mutation/platform/review boundary applies.

**TDD and preservation evidence:** Use existing FairLargeAdmission and DiagnosticSaturation expectations. Reject receipts that claim pressure without an attributable wait/error; accept an honest no-pressure observation. Preserve useful survivor traffic and bounded lane/resource limits. Instrumented observation cannot supply the uninstrumented 20 ms tolerance verdict.

**Dispatch context budget:** This/common contract; E1 interface; native_admission_test.go; endpoint lane/fairness and diagnostics portions; accepted pressure-versus-poller distinction. This is one bounded owner/adapter consumer change; a broader implementation returns to the slice audit.

**Slice decision audit:** E1 is a real socket/result-lifetime dependency. E2 is not a blocker because this observation can succeed with no pressure. Splitting the offered-load producer from accounting loses the meaning of progress; rejected on merit. Merging E2 would conflate distinct evidence outcomes; rejected on merit. Revisit rejected split/merge choices only on the stated trigger; otherwise none: rejected on merit. The existing state owner's direct design is retained; test adapters carry facts and never move policy into another execution context.

**Stop conditions:** Stop if this requires host changes, a new runtime owner, unbounded observers or changing product fairness/limits. Keep missing observations explicit; do not inherit older Linux fairness defects as desired behavior.

### P1 — FreeBSD native peer packaging and ordinary control

**What it delivers:** Extend the merged shared native build/runner interface with explicit freebsd-amd64 and freebsd-arm64 profiles for the existing picoquic/PicoTLS pins. Consume prepared source/tool dependencies through infra artifacts or an infra-owned baseline, build natively with recorded C/crypto/tool identities, run ordinary client/server controls, and compile/list the root multipath matrix without executing it before Q2. Bind initial/replacement tuples, native truncation behavior and process cleanup to the guest receipt.

**Existing-work disposition:** New FreeBSD child. Retain the merged runtime owners; consume only completed, rechecked shared dependencies. No source branch is an established baseline.

**Blocked by:** V1, [#1488](https://github.com/GridCastIO/quicquic-go/issues/1488)

**Single owner after merge:** The shared peer runner owns profile/build/case identity; the pinned libraries own wire parsing; the C adapter owns its bounded command/ingress facts; infra owns guest process/VM cleanup. No second native launcher or peer fork.

**Authority completeness:** No new persisted product authority. Test-owned constructors/record validation/readback and child/socket cleanup are covered at the aid interface; results never change public admission themselves.

**Transitional-seam budget:** None. No duplicate runtime state, temporary production bypass or second lifetime owner is introduced.

**Blast radius:** FreeBSD branches in shared test/build tools, finite dependency packaging and tagged fixture applicability. No peer-pin change, guest network download, credentials, system packages, VM controller or public admission bypass. Explicit tuple identity includes ports; same loopback IP cannot substitute for a full rebinding/gating tuple.

**Artifact classification:** Verification aid plus process/traceability metadata under the common maintained-deliverable payoff/domain/owner/retirement contract. Shipped behavior and safety enforcement are unchanged.

**Representation contract:** Standard JSON and the shared version/profile validators own build/readback records; kernel sockaddr/recvmsg flags own native tuple/truncation facts. FreeBSD compiler/library fields are native fields, not fabricated Darwin SDK/otool data.

**Contract closure:** No recursive closure of the verification aid. It supplies the named finite semantic evidence while production enforcement remains at the existing owners.

**Evidence budget:** One native pinned build/adapter self-test, both ordinary roles and matrix discovery per selected architecture on the primary toolchain; finite missing/wrong dependency/identity/duplicate/skipped case and child-exit cleanup tests. No live multipath or qualification matrix. Keep the current peer pins unchanged. The common mutation/platform/review boundary applies.

**TDD and preservation evidence:** First fail unsupported FreeBSD profile and native-record cases. Verify raw source/artifact hashes, actual test binary build identity, explicit tuple binding and oversized-datagram truncation. Build/list TestPicoquicMultipathMatrix and named zero-negotiation cases. Native ordinary controls catch integration, not multipath. Preserve Linux and Darwin profile/accounting tests without rerunning their campaigns.

**Dispatch context budget:** This/common contract; V1 interface; completed MP-MAC-P1 interface and its unresolved tuple-gate history; interop/multipath native_build.py/run.py/peer.c and tagged launch/tuple tests. Load only the final merged shared implementation, not its entire review history. This is one bounded owner/adapter consumer change; a broader implementation returns to the slice audit.

**Slice decision audit:** V1 supplies the guest/dependency route and MP-MAC-P1 supplies the maintained native build/identity/launch consumer seam. Building a separate FreeBSD launcher would duplicate supervision and receipt authority; rejected on merit. Splitting build, ordinary control and discovery leaves no usable matrix execution route. P2 is independent receipt semantics and not a blocker. Revisit rejected split/merge choices only on the stated trigger; otherwise none: rejected on merit. The existing state owner's direct design is retained; test adapters carry facts and never move policy into another execution context.

**Stop conditions:** Keep the child open if offline dependencies do not fit the admitted artifact/baseline route, native peer build or full tuple identity fails, or cleanup cannot join. Escalate missing infrastructure authority rather than editing host state. A shared predecessor that changes materially requires consumer re-audit before dispatch.

### P2 — Fresh per-path STREAM transport-delivery witness

**What it delivers:** Extend the merged both-active phase and fresh DATAGRAM witness with STREAM evidence tied to fresh phase stream IDs/byte ranges and authenticated acknowledgment of the packets carrying them, or equivalent actual receiver-ingress byte evidence. Retain existing fresh sent counters and exact whole-stream echo. Both live active paths must contribute new byte-carrying transport delivery within the same phase, with application content verified separately; cumulative receive counters or a survivor retransmission cannot satisfy the per-path claim.

**Existing-work disposition:** New FreeBSD child. Retain the merged runtime owners; consume only completed, rechecked shared dependencies. No source branch is an established baseline.

**Blocked by:** [#1489](https://github.com/GridCastIO/quicquic-go/issues/1489)

**Single owner after merge:** The existing fixture phase owns offered-work identity; QUIC/qlog producers own packet/path/ACK facts; the fixture validator correlates those typed facts without becoming a wire parser. The application echo owns useful-content verification.

**Authority completeness:** No new persisted product authority. Test-owned constructors/record validation/readback and child/socket cleanup are covered at the aid interface; results never change public admission themselves.

**Transitional-seam budget:** None. No duplicate runtime state, temporary production bypass or second lifetime owner is introduced.

**Blast radius:** Shared matrix/trace accounting and tests only, for both roles. No production receipt API, scheduler steering, ACK forgery, parser fork, new controller or increased offered-work bound. The phase retains its current finite bound and active/live assertions.

**Artifact classification:** Verification aid plus process/traceability metadata under the common maintained-deliverable payoff/domain/owner/retirement contract. Shipped behavior and safety enforcement are unchanged.

**Representation contract:** Standard qlog/JSON parsing plus typed packet-number-space/path/stream-range/phase identities from authenticated transport events. A finite canonical event/phase subset is validated; parser aliases and unrelated wire syntax remain parser-owned.

**Contract closure:** No recursive closure of the verification aid. It supplies the named finite semantic evidence while production enforcement remains at the existing owners.

**Evidence budget:** One correlated positive per role and materially distinct stale-phase, wrong-path, duplicate-only, inactive-path and unacknowledged-byte negatives, within the existing phase bound. Portable fixture accounting and existing supported Linux control interfaces establish readiness; actual FreeBSD both-role delivery waits for Q2. No new live campaign is authorized by readiness. The common mutation/platform/review boundary applies.

**TDD and preservation evidence:** Write the case where whole-stream echo succeeds only after survivor retransmission while one path has no fresh acknowledged bytes; it must fail. Keep sent/echo regressions, per-phase active/live checks and the shared DATAGRAM witness. Distinguish synthetic fixture facts from live authenticated observations. If the current producer lacks the needed packet/ACK linkage, use its existing test trace seam; do not add a public observability interface.

**Dispatch context budget:** This/common contract; completed MP-MAC-P2 phase/receipt interface; matrixUsefulTransfer, typed matrixTrace/qlog parsing, current sent/received packet and ACK representations. No peer native build or complete historical wire specification. This is one bounded owner/adapter consumer change; a broader implementation returns to the slice audit.

**Slice decision audit:** MP-MAC-P2 is a consumed single phase/identity authority, avoiding a competing fresh-phase ledger. No P1 or V1 edge is needed for portable witness accounting. Splitting production from validation or roles yields a half-witness; rejected on merit. Merging native peer porting mixes independent interfaces; rejected on merit. Revisit rejected split/merge choices only on the stated trigger; otherwise none: rejected on merit. The existing state owner's direct design is retained; test adapters carry facts and never move policy into another execution context.

**Stop conditions:** Stop if the required live transport evidence cannot be obtained through existing fixture/trace interfaces, needs production API changes, or cannot fit the bounded phase. Do not relabel transport ACK as application consumption or accept counters without fresh byte identity.

### C1 — FreeBSD ordinary workloads and truthful metric records

**What it delivers:** Extend the shared ordinary workload/metric interface with both FreeBSD profiles. Supply native process CPU and peak-RSS records with explicit raw unit, conversion, producer and window/lifetime meaning, plus available guest/host scheduling facts from infra/native producers. Preserve matched Reno/BBRv3 unregistered/granted STREAM, DATAGRAM, mixed-bulk and stateless-pressure wiring, offered traffic and receiver-verified useful bytes. Before Q2, private grants cover ordinary cases only; negotiated mixed bulk remains refused on FreeBSD and is characterized through the existing supported Linux control.

**Existing-work disposition:** New FreeBSD child. Retain the merged runtime owners; consume only completed, rechecked shared dependencies. No source branch is an established baseline.

**Blocked by:** V1, [#1490](https://github.com/GridCastIO/quicquic-go/issues/1490)

**Single owner after merge:** The workload owns demand and receiver-verified useful bytes; native metric adapters own observed values/availability; existing transport/controller owners are unchanged. Reuse the shared record/validation owner from MP-MAC-C1.

**Authority completeness:** No new persisted product authority. Test-owned constructors/record validation/readback and child/socket cleanup are covered at the aid interface; results never change public admission themselves.

**Transitional-seam budget:** None. No duplicate runtime state, temporary production bypass or second lifetime owner is introduced.

**Blast radius:** FreeBSD-only metric/grant adapters and shared explicit profile selection. No /proc, Linux affinity/foreign-CPU arithmetic, assumed zero counters, fabricated GSO arm, host reservation or privileged sampling. FreeBSD ru_maxrss units and exec inheritance must be characterized before choosing peak-RSS semantics.

**Artifact classification:** Verification aid plus process/traceability metadata under the common maintained-deliverable payoff/domain/owner/retirement contract. Shipped behavior and safety enforcement are unchanged.

**Representation contract:** Typed metric records retain unit/source/availability and workload identity; kernel getrusage/sysctl interfaces own producer values. Missing counters are unavailable/inconclusive. Canonical producer records, not a generic metric language or universal quiet-host verdict.

**Contract closure:** No recursive closure of the verification aid. It supplies the named finite semantic evidence while production enforcement remains at the existing owners.

**Evidence budget:** Finite unit/window/unavailable/identity/accounting tests; one native ordinary STREAM/DATAGRAM/stateless smoke for each selected architecture using the primary toolchain and matched controller wiring; no cost verdict or statistical repetition. Reuse the shared Linux negotiated mixed-bulk characterization and preserve its useful-background checks. The common mutation/platform/review boundary applies.

**TDD and preservation evidence:** First fail FreeBSD profile/collector tests. Verify CPU window deltas and peak-versus-live memory distinction using producer-shaped fixtures and a bounded native unit/exec characterization. Validate useful bytes from every required flow and offered/reset accounting; BBR loss counters unavailable from a Reno-only producer must stay unavailable. FreeBSD opted-in mixed bulk must not silently become an ordinary background substitute; Q2 executes the actual negotiated workload.

**Dispatch context budget:** This/common contract; V1 interface; completed MP-MAC-C1 typed metric/workload contract; ordinary_cost platform adapters and driver validation. Load selected FreeBSD resource/host producer docs, not Linux campaigns or Darwin plist captures. This is one bounded owner/adapter consumer change; a broader implementation returns to the slice audit.

**Slice decision audit:** Both dependencies are real: native workload execution and the single maintained metric/workload record seam. A second FreeBSD measurement framework adds duplicate authority; rejected on merit. Splitting units from the real workload consumer is horizontal. Lifecycle memory and topology comparison remain distinct consumers C2/C3. Revisit rejected split/merge choices only on the stated trigger; otherwise none: rejected on merit. The existing state owner's direct design is retained; test adapters carry facts and never move policy into another execution context.

**Stop conditions:** Stop if truthful metrics require an unapproved privileged collector, changing workload meaning, tuning the transport or broadening the record grammar. Missing native counters never become zero and a smoke number never establishes a support exception.

### C2 — FreeBSD negotiated lifecycle-memory observations

**What it delivers:** Bind the shared negotiated lifecycle fixture to FreeBSD live-resident memory observations distinct from peak RSS. Preserve the same matched baseline and exact typed path states: established connection, validated backup retained, and a consistently selected retained or closed state after abandonment; retiring is not a completed sample. Observe detachment/survivor/close without reinterpreting those transitions. Prepare and compile FreeBSD execution while its public multipath gate remains closed.

**Existing-work disposition:** New FreeBSD child. Retain the merged runtime owners; consume only completed, rechecked shared dependencies. No source branch is an established baseline.

**Blocked by:** C1, [#1491](https://github.com/GridCastIO/quicquic-go/issues/1491)

**Single owner after merge:** Path.StateV1 and connection/transport lifecycle owners supply state; the shared workload selects sample boundaries; the FreeBSD collector reads memory facts. No duplicate lifecycle model or inferred state from timing.

**Authority completeness:** No new persisted product authority. Test-owned constructors/record validation/readback and child/socket cleanup are covered at the aid interface; results never change public admission themselves.

**Transitional-seam budget:** None. No duplicate runtime state, temporary production bypass or second lifetime owner is introduced.

**Blast radius:** Native current-resident adapter and explicit profile binding only. Use a typed kernel-supported observation or a narrowly specified producer; do not use lifetime Maxrss as a phase-window resident value. No memory limit change, new production diagnostic counter or scheduler control.

**Artifact classification:** Verification aid plus process/traceability metadata under the common maintained-deliverable payoff/domain/owner/retirement contract. Shipped behavior and safety enforcement are unchanged.

**Representation contract:** Typed lifecycle enum/state snapshots and native resident metric with unit/source/availability. The matched states are the finite comparison domain. Unavailable or retiring samples cannot be a passed retained/closed observation.

**Contract closure:** No recursive closure of the verification aid. It supplies the named finite semantic evidence while production enforcement remains at the existing owners.

**Evidence budget:** One finite positive per selected phase and negative retiring/mismatched phase/unavailable-unit cases. Native FreeBSD collector smoke on both architectures; supported Linux negotiated lifecycle control inherited from the shared fixture. Actual FreeBSD negotiated samples are Q2 under Q1. The common mutation/platform/review boundary applies.

**TDD and preservation evidence:** First test phase/metric identity and reject a retiring sample even if elapsed time looks sufficient. Characterize native current-resident units/readback separately from peak RSS. Preserve survivor traffic and wait-for-detach versus wait-for-IO-stopped distinctions. Build/refuse the FreeBSD public workload until Q2.

**Dispatch context budget:** This/common contract; C1 metric identity; completed MP-MAC-C2 lifecycle fixture; Path.StateV1 and public path/detachment APIs; selected FreeBSD current-resident producer. This is one bounded owner/adapter consumer change; a broader implementation returns to the slice audit.

**Slice decision audit:** C1 is the actual metric/result interface and MP-MAC-C2 the single lifecycle workload, so both edges are necessary. Splitting phases loses the matched lifecycle comparison; rejected on merit. Merging C1 expands ordinary workload scope into negotiated state transitions; rejected on merit. Revisit rejected split/merge choices only on the stated trigger; otherwise none: rejected on merit. The existing state owner's direct design is retained; test adapters carry facts and never move policy into another execution context.

**Stop conditions:** Stop if no truthful live-resident measure exists in the approved native environment, lifecycle state needs a new production API, or a valid matched sample requires broader workload semantics. Do not replace a missing measure with peak RSS.

### C3 — FreeBSD topology-comparison execution binding

**What it delivers:** Extend the shared comparison workload and relay consumer with FreeBSD profiles and native identity/metrics. Preserve matched single-path, two-independent-connection, primary/backup and aggregate arms, balanced disjoint, unequal delay/rate and shared-bottleneck/Reno-competitor semantics. Run a finite native real-UDP relay/record/cleanup smoke; compile/refuse negotiated FreeBSD comparison until Q2. Reuse the existing shared relay, not archived B11 executables or a platform fork.

**Existing-work disposition:** New FreeBSD child. Retain the merged runtime owners; consume only completed, rechecked shared dependencies. No source branch is an established baseline.

**Blocked by:** C1, [#1493](https://github.com/GridCastIO/quicquic-go/issues/1493)

**Single owner after merge:** The shared relay owns queue admission and joined socket lifetime; the comparison workload owns matched arms and useful-delivery meaning; C1 supplies native metric facts. Transport owns pacing/congestion unchanged.

**Authority completeness:** No new persisted product authority. Test-owned constructors/record validation/readback and child/socket cleanup are covered at the aid interface; results never change public admission themselves.

**Transitional-seam budget:** None. No duplicate runtime state, temporary production bypass or second lifetime owner is introduced.

**Blast radius:** FreeBSD profile/adapter and driver binding only. No PF/dummynet, route changes, privileged packet capture, controller tuning or second queue state machine. The shared relay currently models explicit IPv4 topologies; this comparison domain does not replace separate IPv6/mapped correctness qualification.

**Artifact classification:** Verification aid plus process/traceability metadata under the common maintained-deliverable payoff/domain/owner/retirement contract. Shipped behavior and safety enforcement are unchanged.

**Representation contract:** The shared relay canonical topology and record validators plus typed comparison identities own the finite model. Native relay fidelity is an observation, not a physical-network guarantee. Unsupported topology/identity or missing accounting cannot pass.

**Contract closure:** No recursive closure of the verification aid. It supplies the named finite semantic evidence while production enforcement remains at the existing owners.

**Evidence budget:** Finite profile/identity/arm/missing-data tests and one native UDP relay smoke on each selected architecture, preserving the existing queue schedule/accounting tests. Full rate/queue/clock fidelity and all comparative thresholds are Q1/Q2 observations, without invented repeats. The common mutation/platform/review boundary applies.

**TDD and preservation evidence:** First reject a mismatched controller, wrong topology identity, absent competitor or zero/missing useful bytes. Verify all shared-bottleneck participants actually use the same queue and cleanup joins. Preserve observed lateness/drop records and the shared producer's stated validation scope; do not recursively prove that every arbitrary JSON record could have arisen.

**Dispatch context budget:** This/common contract; C1 metric interface; completed MP-MAC-C4 comparison and transitive MP-MAC-C3 relay public interfaces; accepted numerical comparison criteria. No complete archived relay source or unresolved source-branch baseline. This is one bounded owner/adapter consumer change; a broader implementation returns to the slice audit.

**Slice decision audit:** C1 provides truthful native metrics and MP-MAC-C4 provides the single matched-arm consumer of the shared relay. These are actual interface edges, not dependence on macOS qualification. A second relay/comparison tool duplicates ownership and is rejected on merit. Further splitting profile and its UDP consumer is horizontal. Revisit rejected split/merge choices only on the stated trigger; otherwise none: rejected on merit. The existing state owner's direct design is retained; test adapters carry facts and never move policy into another execution context.

**Stop conditions:** Stop if the completed shared interface cannot represent the accepted comparison without changing its queue/arm semantics, a native fidelity shortfall needs runtime tuning, or host-network privileges are needed. Re-audit the consumer instead of silently absorbing another program's open work.

### Q1 — Approve the concrete native execution and applicability protocol

**What it delivers:** Publish one concrete protocol binding the merged interfaces to exact candidate, native venues, installed Go 1.26.11/1.27.4 binaries and applicability, executable commands, finite semantic inventory, output fields, attribution/contamination rules and continuing CI owner/route. Present the completed package for the maintainer's required release/socket-family, operational, privilege and maintained-CI decisions; retain the exact decision receipt before completion. Resolve the source-visible dual-stack DF limitation explicitly. No qualification or comparative run executes in Q1.

**Existing-work disposition:** New FreeBSD child. Retain the merged runtime owners; consume only completed, rechecked shared dependencies. No source branch is an established baseline.

**Blocked by:** S2, S3, E2, E3, P1, P2, C2, C3

**Single owner after merge:** The protocol owns the finite collection contract; the maintainer owns release/family applicability, operational scope, privilege and support exceptions. Infra and fixture results supply facts, never execution authority.

**Authority completeness:** Metadata only. Publish commands, identities, applicability and the exact owner approval together; a partial/unapproved protocol cannot authorize Q2.

**Transitional-seam budget:** None. No duplicate runtime state, temporary production bypass or second lifetime owner is introduced.

**Blast radius:** Protocol and current interface/identity correspondence only. No provisioning, installed-toolchain fiction, runner registration, privilege use, native attempt, budget reset or new performance exception. Missing concrete prerequisites keep this child open.

**Artifact classification:** Process/traceability metadata; Q1 records explicit payoff/domain/owner/retirement approval for selected continuing verification aids.

**Representation contract:** Finite named case/command/identity table and exact owner decision receipt. Standard parsed tool identities; example-level platform evidence. No broad manifest language or generalized proof of the apparatus.

**Contract closure:** Not triggered for protocol metadata. Bind the existing safety/activation rows to executable evidence without recursively proving fixtures.

**Evidence budget:** One correspondence audit and approval of the actual executable table. No operational samples. Retain accepted product thresholds and the 20 ms endpoint tolerance; any repeated-run/statistical question, exception or additional cell needs the existing explicit owner decision. The common mutation/platform/review boundary applies.

**TDD and preservation evidence:** No code TDD. Map every required accepted semantic row to a command, expected native identity, observation field and missing-evidence disposition. Bind first/additional PMTU, EMSGSIZE recovery, family/source/ECN, actual Go poller versus pressure, protected-buffer/close/join, migration/rebinding/stale feedback, detachment survivors, BBR per-path sampling/credit and native amd64 race/arm64 concurrency. Include both-role Reno/BBR peer inventories, fresh STREAM/DATAGRAM witnesses, public/root/HTTP3 controls, matched costs including negotiated mixed bulk, lifecycle memory and topology comparisons. Resolve live Go 1.26.11 delivery before calling that toolchain a qualified cell.

**Dispatch context budget:** This/common contract; current leaf receipts/interfaces from the eight blockers and their transitive predecessors; accepted target/profile/semantic/threshold sections; current guest/toolchain/CI facts. Do not load all fixture internals or entire historical campaigns. This is one bounded owner/adapter consumer change; a broader implementation returns to the slice audit.

**Slice decision audit:** Each leaf contributes an executable method, prerequisite or truthful measurement required before activation; the dependencies are semantic, not convenient ordering. Splitting inventory from its owner decision leaves an incomplete execution contract; rejected on merit. Merging Q2 mixes unresolved authority with runtime activation/collection; rejected on merit. Revisit rejected split/merge choices only on the stated trigger; otherwise none: rejected on merit. The existing state owner's direct design is retained; test adapters carry facts and never move policy into another execution context.

**Stop conditions:** Keep Q1 open when toolchain, family/release scope, native method, continuing CI or concrete operational authority is missing. A reduced profile, per-family capability redesign, kernel change, new socket owner or changed numerical criterion requires an explicit maintainer decision and affected-slice re-audit before Q2.

### Q2 — Qualify and activate FreeBSD public multipath

**What it delivers:** Prepare one exact activation candidate for the approved FreeBSD architecture/release/socket-family domain; update the common capability decision, independent root/HTTP3 applicability and public support comments/errors; transition the prepared FreeBSD runner/workload profiles from readiness-only refusal to Q1-approved qualification through real public admission; run Q1's exact native protocol on both architectures; and merge acceptance-expecting tests, continuing native CI, support record, README/usage and release note with the gate. The fixture transition covers the peer matrix/zero cases and negotiated mixed-bulk, lifecycle and comparison cases, including grant selection and readiness expectations. Preserve case inventories, workload meaning, identity validation and refusal outside the approved domain. All three selected controller/policy combinations remain the target. Missing or unaccepted evidence leaves the branch unmerged.

**Existing-work disposition:** New FreeBSD child. Retain the merged runtime owners; consume only completed, rechecked shared dependencies. No source branch is an established baseline.

**Blocked by:** Q1

**Single owner after merge:** The common platform capability owner decides eligibility; existing socket/grant and Config admission owners retain their own input checks; endpoint/connection owners retain runtime behavior. Support records inform the maintainer and do not become a runtime side channel.

**Authority completeness:** No persisted product authority or restart schema is added. Cover setup/constructors, validation, every changed ordinary/native consumer, failure and cleanup at the named owner in this same slice; no new capability may outrun its consumer evidence.

**Transitional-seam budget:** None. No duplicate runtime state, temporary production bypass or second lifetime owner is introduced.

**Blast radius:** Capability/helper, independent test applicability, the prepared FreeBSD runner/workload profile and grant selectors, selected CI integration and support metadata only, after known runtime repairs are merged. No new scheduler, deadline owner, packet format, public bypass, extra path, peer pin or reduced target. Any additional runtime repair is separately bounded before this candidate can expand; a required workload or record redesign returns for re-audit.

**Artifact classification:** Shipped behavior and required safety enforcement at the named existing owners; focused tests are verification aids and receipts are traceability metadata. The common maintained-aid boundary applies without recursive closure.

**Representation contract:** Typed GOOS/GOARCH/kernel and actual socket-family partition at the common eligibility/admission owners, with canonical kernel version values defined by Q1. Independent table expectations cover declared accept/refuse classes. Native behavior/cost remains example-level qualification; unknown/error version observations follow the approved refusal policy.

**Contract closure:** The relevant named rows of the safety/activation coverage argument apply. Keep the precise invariant, owner and semantic partitions bounded; no syntax-variant or unrelated-owner matrix.

**Evidence budget:** Exactly Q1's owner-approved operational inventory plus named local input-owner tables and applicable existing hosted checks. One initial review and at most one replacement. No spare attempts, platform expansion, statistical repetition or inherited Linux exception is inferred; diagnose failures before any legitimate rerun. The common mutation/platform/review boundary applies.

**TDD and preservation evidence:** First fail independent positive FreeBSD support expectations and preserve Linux amd64, unsupported architectures/releases/families, Config cloning/setter order, controller/policy/path cap, enabled v2 refusal and granted ordinary v2 success. Cover explicit/library-owned grants, constructors/server-selected Config and HTTP3 at the real interfaces. Change the focused profile/mode-selection expectations from readiness refusal to exactly the approved public peer and negotiated workload cases, retaining out-of-domain refusal and identity validation. Run the exact native endpoint, BBR, PMTU, family/ECN, lifecycle, peer and measurement evidence; no production-predicate-based skips. Separate native fact, raw numerical verdict and any exact-result support decision.

**Dispatch context budget:** This/common contract; Q1 approved protocol and ready method interfaces; multipath_api.go/platform helper/socket admission and independent root/HTTP3 tables; the existing profile/mode/grant selectors and focused tests in interop/multipath/run.py, ordinary_cost_test.go, interop/multipath/ordinary_cost.py and the completed lifecycle/comparison consumers; selected CI/support files. No whole fixture internals or historical campaign dumps. Discovering another runtime repair or required workload/record redesign invalidates this small activation-boundary claim. This is one bounded owner/adapter consumer change; a broader implementation returns to the slice audit.

**Slice decision audit:** Q1 is the genuine authority/executable-evidence dependency with all prerequisites transitively satisfied. Splitting admission from native evidence, tests and support publication creates an unsafe intermediate claim; rejected on merit. Splitting by architecture/controller contradicts the accepted initial target; revisit only on an evidence-backed maintainer decision. Revisit rejected split/merge choices only on the stated trigger; otherwise none: rejected on merit. The existing state owner's direct design is retained; test adapters carry facts and never move policy into another execution context.

**Stop conditions:** Stop on absent native poller/family/PMTU evidence, unapproved failed cost disposition, unavailable CI/toolchain/venue, new runtime repair/owner/interface or inability to retain one PR. Do not silently drop arm64, aggregate, an approved family or protected-buffer/lifecycle evidence. Broader representation/topology/product changes return to architecture-handoff.

## Acceptance and validation

- Each of the fourteen named children delivers its complete interface and finite evidence; a missing method or an honest blocker is not completion of that child's promised outcome.
- Shared dependencies are consumed only after their implementation is merged and their actual contract checked; there is no second copy of those external tasks or fixtures.
- Public FreeBSD admission stays closed through readiness and socket repairs. Q1 resolves concrete release/family/toolchain/operational/CI authority, and Q2 publishes the exact qualified profile with activation.
- S1–S3 preserve ordinary behavior outside their named correctness changes; native evidence and source-visible dual-stack limitations remain explicit.
- Native useful delivery, absolute deadline/borrow/join, PMTU, family/ECN, BBR, ordinary cost and comparison obligations map to their real owners and Q1-bound commands. A skipped required case is not a pass.

Universal wording above ranges only over the finite named child graph or explicit semantic input partitions. Kernel/ABI, typed Go/netip and standard JSON/qlog producers own representation. The declared representative evidence and bounded review allowance terminate each task; no recursive fixture-completeness gate is added.

For changed Go packages run focused tests, go vet and go mod tidy -diff when applicable, with the native/race checks justified by the slice. For Python/C adapters run the finite parser/identity/cleanup/compile/ordinary-control tests and preserve shared platform interfaces. Freeze concrete commands in execution preflight using the named current seams; no historical campaign is triggered by a test-name match. A FreeBSD ABI helper's build coverage includes the existing 386/arm targets without a new runtime claim.

## Operating discipline

The shared review-loop and contract-closure baselines supplied by $implement-architecture-slice govern, composed with [the repository execution overlay](../REVIEW-LOOP.md); use the shared design-cost reference for scoped re-audit. They govern artifact/representation gates, finite evidence/review scope, semantic-family closure, exact invariant-and-owner repeated-root comparison, diagnosis before reruns, exact-head certification, same-head hosted checks, merge and journal. No repository baseline copy or new CI portfolio is created.

For this handoff, finish the independent slice-decision audit before any commit/publication, then the Standards/Spec preparation and full configured RAS review through installed wrappers. Certify the clean exact pushed head, relative links, source correspondence and graph. Require successful applicable hosted checks, mark ready and squash merge with head matching. Only then verify the exact default-branch plan commit, publish thin child/parent/tracker issues and update the specified OmniFocus parent. No implementation or qualification agent is launched by this handoff.

For a future child, its product PR owns its plan/index completion and affected successor-frontier transition before review. After exact-head merge, record the dev-journal completion account, reconcile native issue dependencies/readiness and pointer-based mirrors, and complete its OmniFocus task. Administrative status is distinct from code-head certification; no plan SHA is mirrored into OmniFocus. Do not open a routine third PR merely for status.

Dispatch belongs to the operator: one fresh agent per verified frontier child with $implement-architecture-slice and context cleared between children. That skill may re-audit within the same representation, accepted outcome and one-PR boundary; changes of owner, topology, adjacent scope, product intent or irreversible authority require a decision or architecture-handoff.
