# Jumbo recovery after fallback

**Date:** 2026-11-18. **Identity:** `JR-1231`. **Status:** approved direction and retry policy; implementation pending. **Design issue:** [Jumbo packets: design re-climbing after a fallback (#1231)](https://github.com/GridCastIO/quicquic-go/issues/1231). **Related program:** [Jumbo packets (#1215)](https://github.com/GridCastIO/quicquic-go/issues/1215). Source checked at `3bb45d0372ea1bf4e76705c79010821cce70e049`. The owner approved this design-PR scope and policy in the originating chat on November 18. Review history belongs in the merging PR, not in this normative contract.

## Outcome and boundary

Produce an audited implementation slice that lets a long-lived jumbo-active connection recover jumbo packetization after fallback. Successful padded probes must precede larger application packets. Retry intervals increase to reduce repeated interruptions on a changing path. The November 18 receiver-cutoff measurement in issue #1231 motivates this decision; its 272.708459 ms delivery gap and 56.8346% comparative goodput shortfall are one diagnostic example, not recovery deadlines or general throughput claims.

This decision supersedes only the permanent post-fallback disable and the rejected re-climbing alternative in the [original jumbo plan](2026-11-05-jumbo-packets-plan.md). Preserve the negotiated ceiling, fallback to the tested stage-one size and then the effective initial size, ordinary recovery rules, and the consumer's fixed published application DATAGRAM limit. The changing transport admission limit is distinct: `SendDatagram` may already refuse a message after shrink, and later confirmed growth may raise its limit. This plan does not make the published consumer limit dynamic.

No new configuration, exported method, dependency, worker, lock, channel, socket behavior, packet format, receive tier, fallback size or congestion algorithm is admitted. Unconfigured and peer-capped connections retain their existing behavior. Native multipath jumbo, initial discovery periodic retries before any fallback, equal-cost-path partial loss, real-link requalification, release claims, throughput targets and a general interruption bound are non-goals.

## Current enforcement and ownership

The connection run loop owns fallback and packet size. `applyPacketSizeFallback` and `watchingPacketSize` currently use `mtuFallback.started` as a permanent disable. `discoveryPacketCeiling` caps future paths after that first fallback. `startPacketSizeFallback` closes the public channel unconditionally and assumes there can be only one episode. The finder rejects stale probe callbacks with an 8-bit generation; repeated searches invalidate the original assumption that reset counts stay small. `Reset` clears stage-one observations, so it is unsuitable as an unqualified same-path retry operation.

The run loop already has recovery and discovery deadlines and emission preparation for Reno and BBR. Keep policy there. The finder owns search bounds and current-search probe receipts; emission owns real packet construction, registration and output handoff. Workers continue to report immutable local-refusal facts through the existing path-generation channel. Existing delivery behaviors include coalesced feedback and late worker completion: path generation and current state must reject irrelevant facts, and the stopped loop makes late shutdown facts inert.

## Retry policy

A retry cycle is a bounded invocation of the existing loss-tolerant MTU search from the current confirmed size toward the effective ceiling. Reaching the ceiling means satisfying the existing `maxMTUDiff` termination rule, not delivering the exact advertised ceiling. A retry timer only permits a search; an ACK for its live probe is the authority to raise packet size. Keep ordinary data at the current confirmed size while a larger probe is outstanding. Discovery-probe refusal or loss is not evidence for the data-fallback detector.

| Event or state | Required transition |
| --- | --- |
| First fallback confirmed | Arm retry for confirmation time plus 60 seconds. No retry while confirmation is active or exhausted without confirmation. |
| Eligible deadline reached | Consume the deadline once and start the search if handshake confirmation, DF, discovery configuration and effective ceiling permit it. Preserve normal send eligibility and pacing. |
| Probe ACK in the current search | Raise to the acknowledged size through the existing ACK-driven finder, admission and congestion-size update path. |
| Search completes below the effective ceiling | Keep the confirmed result; arm another search from completion time using the next backoff interval. |
| Search completes at the ceiling tolerance | Stop periodic searching. Keep accumulated backoff for any later fallback. |
| Another actual fallback | Run existing reduction and confirmation again; after confirmation use the next backoff interval. |
| Retry in flight when path changes | Invalidate its callbacks and clear path-specific recovery/watch state before processing new-path feedback. Reset packetization to the effective initial size as today. |
| New path after any fallback | Run standard-size discovery immediately under existing rules. Permit jumbo only after retained cooldown expires and standard discovery admits stage two; old-path confirmation does not authorize new-path growth. |
| Shutdown | End retry with the run loop; late ACK, loss or local-refusal facts cannot restart it. |
| Discovery disabled, DF unavailable or effective ceiling at most 1452 | No retry deadline or jumbo search. |

Backoff intervals are 60, 120, 240, 480, then 900 seconds, saturating at 900. Advance once per newly scheduled cycle, not per probe or ACK. An actual fallback supersedes a still-running search and schedules only after its smaller size is confirmed; that confirmation consumes the next interval once. Successful growth and path migration do not reset backoff. These values are owner-approved policy, not measured network constants.

Migration retains an armed absolute deadline and the next backoff interval; it does not shorten or restart a cooldown. If it cancels a running retry, arm the next interval from migration time. If no retry was armed because jumbo had been fully restored, migration after a previous fallback arms the next interval from migration time. A migration during unconfirmed recovery may arm the next interval for the new path, but jumbo still requires that path's standard discovery and fresh probe confirmation. Repeated migration carries an existing deadline forward rather than incrementing again. Initial connection discovery before the first fallback keeps today's two-stage policy.

A deadline that expires before standard discovery finishes becomes one pending eligibility state, not a repeatedly overdue timer. Stage two still requires the existing successful stage-one admission condition. If the stage-one result is below that condition, retain the smaller size and schedule the next bounded search at the next interval. A same-path retry must be able to re-run the standard search from a smaller confirmed result before attempting stage two, rather than permanently trapping a path whose standard search previously narrowed.

Use the existing connection timer. An expired deadline transitions once even if socket/congestion backpressure delays sending. Discovery remains subject to normal congestion and pacing rules, unlike fallback recovery probes. Idle retry does not add keepalives or defeat the connection idle timeout. A lost discovery probe without later traffic may remain unresolved under existing recovery rules; this design promises no idle recovery deadline. Do not create a separate discovery loss clock to strengthen that contract.

## JR1 — Restore jumbo with repeatable fallback

**Status:** implementation pending; no code is changed by this design PR. Deliver as one implementation PR. The implementation issue will point here; it must not close design issue #1231 again. This slice is self-contained and does not require a new architecture program.

**Changes:**

1. In `packet_size_fallback.go`, separate one-time first-drop notification from recovery-episode state. Reset confirmation, loss count, packet-number boundary and recovery-probe state for each episode. Close `PathMTUFallbackV1` only on the first drop. Replace permanent-disable checks in local refusal handling, `packet_size_watch.go` and `discoveryPacketCeiling` with explicit current recovery/search policy. Preserve lower-size confirmation and exhaustion.
2. Keep retry policy and saturating deadline/backoff state in the connection-owned recovery module. Integrate advancement with `packetSizeRecoveryTime` / emission preparation and the existing timer in `connection.go`. Reset watches on episode transitions. Re-enable both shrink detectors as soon as ACK-confirmed packetization exceeds 1452. A discovery probe must retain its exemption from those detectors.
3. Add a finder restart operation in `mtu_discoverer.go` that invalidates prior callbacks, starts from the current confirmed size, reopens appropriate bounds, and preserves the tested stage-one fallback and atomic report when staying on the same path. If standard discovery must be repeated, replace its fallback observation only with that path's newly validated result. A migration still clears the observation per existing semantics. Replace the 8-bit search generation with an identity safe for repeated long-lived searches (for example, a fresh per-search identity shared by callbacks).
4. Preserve the existing run-loop ACK path for publishing size increases and updating congestion packet size; preserve emission ownership, recovery registration and buffer lifetime. Use both Reno and BBR paths. Path reset cancels search evidence before old callbacks can act and retains only connection-wide cooldown/backoff policy.
5. Update `PathMTUFallbackV1`, `PathMTUSettledV1` and `PathMTUInfoV1` comments for retries. Both channels keep their identity and one-time closure semantics. The effective ceiling remains negotiated; same-path retry does not erase a still-valid fallback report. Update maintained ADR language only where implementation makes it stale.

**Acceptance criteria:**

- After confirmed fallback and cutoff removal, the same connection resumes jumbo application packets only after ACK-confirmed probe growth.
- A persistent cutoff leaves smaller application traffic usable while subsequent completed searches use the approved increasing intervals.
- A second shrink after recovery enters the existing fallback/confirmation sequence again without double-closing a public channel.
- Stale search or path feedback cannot authorize growth; unconfirmed recovery and shutdown do not start retry.
- Default and peer-capped behavior, fallback sizes, negotiated observations, first-path settled signaling and the consumer's fixed published DATAGRAM limit are preserved.
- Retry uses the existing run loop, timer, emission and send eligibility with no overdue-deadline busy wake.

**Representation and guarantee:** accepted Transport ceiling values and peer parameters are owned by existing transport validation and wire parsers; current-path/search ACK and loss facts are owned by recovery and finder identity. No new protocol parser is introduced. Behavioral evidence is example-level; no universal network-delivery guarantee is claimed. The invariants about growth authority and stale feedback are implementation requirements discharged by the finite semantic classes below.

**Artifacts and material risk:** retry is shipped behavior; probe/search authority, repeatable fallback and lifecycle invalidation are required safety enforcement. Tests are ordinary verification aids, with no new maintained diagnostic service or harness. Plan, review receipts and task pointers are process metadata. Closure triggers for stale-feedback isolation and repeatable fallback: independently reachable local refusal, remote shrink, retry, migration and shutdown can otherwise leave a live connection at an unusable packet size. One central owner is the run loop, with finder-owned probe identity.

| Semantic class | Expected disposition and owner | Finite evidence |
| --- | --- | --- |
| Confirmed fallback, restored path | Probe ACK precedes jumbo data; run loop and finder | Existing real-connection refusal/cutoff fixtures with intact stream delivery and fixed-size DATAGRAM delivery |
| Persistent cutoff and completed retries | Continue small data, enforce 60/120/240/480/900/900 scheduling; run loop | Virtual-clock transition test, independent expected timestamps |
| Successful re-climb followed by local or far-side shrink | Repeat full recovery; first-drop channel remains the same closed channel; run loop | One representative repeated cycle for each trigger |
| Lost/refused/stale discovery probe | No false data-fallback trigger or unconfirmed growth; finder and existing probe classification | Finder ACK/loss tests, real-emission probe exemption regression, stale callback after more than 256 search restarts |
| Migration in cooldown, active search or unconfirmed recovery | New-path discovery and retained backoff; no old feedback authority; run loop | Focused migration table, current-path receipt assertions |
| Initial-size confirmation, exhaustion, shutdown | Existing standard recovery; no unconfirmed retry; no post-close work; run loop | Existing recovery fixtures and focused shutdown regression |
| Default, peer-capped, disabled discovery or missing DF | Existing behavior, no retry; connection configuration | Focused preservation table and existing tests |
| Idle, pacing, socket or congestion block | Consumed/suspended deadline, ordinary send admission and idle timeout; timer and emission | Existing virtual-clock timer seam, Reno/BBR emission cases |

**TDD and evidence budget:** load `tdd` before tests. Work one behavior through red then green at the existing finder interface, virtual-clock timer and real-packer connection seams. Finder/timer tests catch transitions, scheduling and stale callbacks but miss real socket delivery. Existing connection fixtures exercise packet construction, recovery ACK processing, delivery and cleanup; they do not qualify physical-link goodput. Use representative stream and fixed-size application DATAGRAM traffic, with Reno/BBR at differing emission/recovery paths rather than multiplying every row. No new platform matrix, physical campaign, fuzz suite, performance threshold or statistical repetitions. No guard mutation is required: new behavior-specific regressions supply direct evidence at the enforcement owners.

**Validation:** focused new cases plus existing jumbo fallback/shrink, finder, idle MTU timer, path-reset and DATAGRAM preservation tests; affected-package tests, focused lifecycle race coverage, `go vet` on changed packages, and `go mod tidy -diff`. Then the existing hosted checks on the exact pushed head, including the post-ready independent multipath peer job, per the [repository overlay](../REVIEW-LOOP.md). Use one Standards/Spec preparation pass, initial full-panel RAS review, verification of accepted fixes and at most one replacement review. Do not narrow the configured panel. Squash merge only after local certification, live-head checks and base freshness verification. Journal only after merge; then reconcile implementation issue and OmniFocus.

**Blast radius and alternatives:** changes connection-local retry timing, search identity and repeated recovery transitions; adds probe traffic and the possibility of repeated interruptions after genuine regrowth. No global state, public configuration, schema, security boundary or dependency change. The owner's design is the adopted synchronous run-loop transition using existing clocks and callbacks. A separate retry worker adds cancellation, late delivery and mirrored-state obligations with no necessary work offloaded; rejected on merit, revisit none. Unqualified reuse of migration reset discards same-path fallback observations and repeats unrelated migration work; rejected on merit, revisit none. Splitting retry from repeatable fallback can ship growth without recovery on the next shrink; rejected on merit, revisit none. Effects of physical-link fluctuation and probe-induced application interference remain unqualified, with no performance claim in this slice.

**Context and stops:** implementation needs this current contract, original jumbo Decision/recovery invariants, named source seams and relevant unresolved review findings; exclude full historical audit archives. Stop for owner decision if implementing this contract requires a new exported/configuration surface, changed fallback sizes, new cross-context policy, dynamic consumer DATAGRAM limits, a separate probe-loss clock, or broader evidence. Follow the shared precise-root and finding-disposition policy before expanding scope.

## Design PR certification

This documentation PR delivers this contract and the original plan's supersession pointer. Validate relative links, Markdown whitespace, source correspondence and the single-slice identity; certify a clean exact pushed head against the current base. Run the Standards/Spec preparation pass and the full configured RAS review with this documentation scope, one initial review and at most one replacement after accepted fixes. Applicable hosted documentation checks remain authoritative. Runtime evidence above belongs to JR1 and is not claimed by this PR. Close design issue #1231 only after this plan merges, create the implementation pointer and update OmniFocus. Record the development journal account after merge.
