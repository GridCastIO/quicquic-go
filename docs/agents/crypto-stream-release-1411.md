# Release discarded handshake crypto streams (#1411)

## Accepted outcome

[Issue #1411](https://github.com/the-sarge/quic-go-fast/issues/1411) is one measurement-conditioned implementation PR. The user approved the inline plan and the additional CPU/allocation comparisons in the originating chat. Baseline: `f11a20cf56d7dcf682e5e02e7969ccd7bcd7811a`. Adopt only when fork measurements support retained-memory benefit and lifecycle correctness is preserved. A repeatable CPU/latency regression requires assessment of workload significance and the memory tradeoff before adoption; there is no arbitrary savings or regression threshold.

## Contract

After irreversible Initial/Handshake discard, connection-owned stream and retransmission state cannot produce or retain obsolete work. Previously constructed frames and datagrams remain valid until their existing owners release them. `Conn.dropEncryptionLevel` coordinates the transition synchronously; `cryptoStreamManager` solely owns stream references. Recovery, packet emission, and asynchronous send ownership remain unchanged under ADR 0004.

Acceptance criteria:

- Account for direct stream owners, receive-sorter storage, frame slices, recovery history/callbacks, retransmission queues, pending emissions and sends at the implementation revision.
- Keep `Finish` distinct from discard, preserving unread-data errors, offset validation, duplicate and post-finish behavior while the level remains usable.
- Make Initial/Handshake discard idempotent, release obsolete references, and prevent late loss callbacks from recreating discarded work without invalidating legitimate outstanding frame/send owners.
- Preserve client/server completion and confirmation, ClientHello scrambling, Retry, version negotiation, shutdown, 0-RTT rejection, 1-RTT/session tickets, API/wire contracts, and delivery-limitation classification.
- Compare baseline/candidate retained heap using identical persistent-connection workloads, with exact revisions, commands, total/per-connection results, repeat variation, and attribution of remaining retention.
- Compare complete handshake CPU/allocations, post-handshake delivery classification with empty and pending application work, and real Initial/Handshake packing including scrambling. Report platform and measurement limits.

The representation domain is existing typed encryption levels, parsed CRYPTO frames, TLS events and supported lifecycle transitions. Existing QUIC parsing and TLS processing own representation validation. The lifecycle invariant covers supported paths; finite ownership analysis and representative semantic regressions support it without claiming a formal exhaustive execution proof. Closure is triggered by lifecycle-corruption consequences across independently reachable discard, callback, and pending-send paths.

## Implementation and boundaries

Centralize stream construction and references in the concrete manager; route connection writes, ticket output, packet packing and delivery sampling through it. Discard clears Initial/Handshake references and their retransmission queues. Availability/pop queries tolerate discarded levels. Retain existing `Finish` validation and packet-buffer ownership. Compare read/finish/write reachability against discard; do not suppress reachable protocol errors to accommodate missing streams.

Production scope: `crypto_stream_manager.go`, `connection.go`, `packet_packer.go`, `delivery_sampling.go`, and necessary retransmission discard integration; corresponding focused tests and evaluation evidence. This changes private constructor/access plumbing, with no new execution context, channel, lock, mirrored lifecycle flag, dependency, public API or wire format. Stream objects are allocated once and their storage is neither zeroed nor pooled at discard.

Alternatives: clearing aliases in three owners retains a synchronization obligation and is rejected on merit; revisit trigger: none. Clearing at `Finish` releases too early and does not remove stream objects; rejected on merit, revisit trigger: none. TLS-state release, receive-queue shrinking, frame-sorter redesign, pooling, congestion-policy changes, and emission/native-I/O rewrites are excluded.

Runtime ownership behavior is shipped behavior; discard guards are required safety enforcement. Tests and the bounded measurement fixture are verification aids, not a maintained benchmarking service or new CI gate. The report, contract and review receipts are traceability metadata. Verification aids receive proportionate review without recursive completeness obligations.

## Evidence and completion

| Semantic class / seam | Expected behavior | Evidence / limitation |
| --- | --- | --- |
| Manager and stream | Finish validation preserved; repeated discard disables outgoing data | Focused regression; not whole-connection ordering |
| Real connection discard | Storage collectible with connection alive once legitimate owners end | Weak references/GC; not production savings |
| Queue and recovery callbacks | Obsolete queue emptied; late callback cannot refill | Existing and connection-level regression; not native completion |
| Real packer/emission and controlled sender | Constructed bytes survive registration-time discard, pending send and shutdown | Behavioral regression; not every OS interleaving |
| Client/server lifecycle | Completion, confirmation, scrambling, Retry, version negotiation, shutdown, 0-RTT and tickets preserved | Existing focused tests plus necessary extensions |
| Delivery sampling | Discarded state safe; surviving work retains classification | Behavior tests and CPU benchmark; not broad congestion qualification |

Use TDD at these approved seams, one behavior per red/green cycle. One representative positive per semantic behavior and negative per distinct failure mode; no fuzz campaign, mutation suite, or timing cross-product. Run focused race tests, affected-package tests, `go vet` on changed packages, `go mod tidy -diff`, formatting and diff checks. Exercise available Darwin native sends; report other platform limits and existing hosted coverage.

Heap protocol: separate client/server processes, 1,000 persistent loopback connections, fixed certificate/TLS and traffic, completed handshake plus a small bidirectional exchange, five seconds idle, keepalives disabled, timeout beyond measurement, two GCs, live connection roots, and empty-server control. Five paired baseline/candidate trials alternate order to quantify variation. Hold toolchain/platform/configuration constant, report heap profiles and total/per-connection deltas. CPU evidence uses identical benchmark code and paired runs; inspect inlining/escape changes when results warrant it. Inconclusive or absent memory benefit leads to an evaluation-only recommendation, not adjacent optimization.

Use one Standards/Spec preparation pass, the full configured RAS panel, one initial fresh review and at most one replacement after accepted fixes, with verification of accepted findings. Apply the shared disposition policy and [repository execution overlay](../REVIEW-LOOP.md). Certify the exact head, pass applicable hosted checks including the ready-only independent multipath job, and squash merge after base verification. Journal only after product merge, then revalidate deferrals and reconcile issue #1411 and its OmniFocus task.

Return for decision if safe completion requires a changed ownership/public contract, excluded work, evidence beyond the approved scope, or unresolved material performance tradeoff. Review history and measurement results belong in linked audit evidence, not appended contract revisions.

Evidence: [ownership argument](../audits/crypto-stream-release-1411/ownership.md) and [paired memory/CPU evaluation](../audits/crypto-stream-release-1411/report.md).
