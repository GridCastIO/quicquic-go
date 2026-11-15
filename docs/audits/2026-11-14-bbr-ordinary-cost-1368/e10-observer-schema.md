# E10 accepted-member observation schema (#1368)

This disposable observer is based on pre-code plan `872af89701460a94fcde7861fb156321bb2d9afa`, with the retained E09 runtime unchanged. It adds measurements, not an optimization. All E10 instrumented/profiled timing is excluded from acceptance. No observer code or exported observation seam belongs in the final product.

The ordinary fixture emits `bbr_observation` for each server connection and client flow. It contains `snapshots[128]`, `snapshot_count`, `snapshot_overflow`, `final_before_teardown`, and `final_recorded`. Only the first `snapshot_count` entries are valid. Snapshots are cumulative, copied by value at the existing BBR send-opportunity hook at most once per second. Inactive connections have gaps. `mono_ns` is process-local monotonic time; `unix_ns` derives from that same timestamp without another clock. One final clock freezes evidence before local drain and controller teardown. Final totals include startup/warmup and exclude work after the freeze. Fixture extraction waits for connection context completion; server extraction additionally follows listener/transport close and worker completion. No live connection-owned state is read by a fixture worker.

Every snapshot contains `geometry` and `native`. Geometry fields are `handoffs`, `bytes`, `datagrams`, `gso_handoffs`, `scalar_handoffs`, and `size_buckets[7]`. Buckets have inclusive byte upper bounds `[1452,16384,20480,32768,49152,65507,infinity]` and count actual buffer length, not allocation or reservation. Datagrams are physical outgoing datagram segments inferred from the existing GSO size, including a final short segment; this is not a QUIC packet count for coalesced handshakes. GSO intent can fall back to scalar syscalls. Geometry includes all BBR handoffs, including control/probe traffic, and does not establish native acceptance.

Native fields are `attempts`, `datagrams`, `seam_attempts`, `successes`, `declines[6]`, and `recovery`. Every count object has unsigned cumulative `members` and `packets`. Native attempts count validated terminal members offered to `completeAcceptedPackets`, after consumeResult's accounting checks; malformed terminal results and residual unsubmitted suffix cleanup are outside this denominator. Packet weighting uses `len(packets)`; the separate native `datagrams` total preserves coalesced geometry. Native first-decline indices are `0=result_error, 1=partial, 2=packet_geometry, 3=too_small, 4=too_large, 5=mtu`. These preserve the existing short-circuit order. A native decline never reaches recovery; a recovery decline is not counted again as a native decline.

Recovery fields are `attempts`, `rich_attempts`, `successes`, `rich_successes`, and `declines[33]`. They observe the same boolean completion decision once, using a borrowed caller-owned counter pointer that is never retained. The original unobserved entry uses nil counters. `rich_attempts` begins only after every common token/history preflight succeeds and the actual BBR helper is entered. Reno successes equal `successes-rich_successes`. Common decline indices 0–22 and rich decline indices 23–32 identify the first failed predicate for the whole member, with no second preflight or foreign mutable-state reads. For predicates within a loop, token order precedes later tokens' failures.

| Index | Recovery first decline |
| --- | --- |
| 0 | `handler` |
| 1 | `shape` |
| 2 | `local_state` |
| 3 | `qlog` |
| 4 | `handshake` |
| 5 | `amplification` |
| 6 | `lost_queue` |
| 7 | `rich_controller` |
| 8 | `unexpected_bbr_ecn` |
| 9 | `pto` |
| 10 | `physical_prefix` |
| 11 | `pending_ecn` |
| 12 | `ecn_constraints` |
| 13 | `ecn_tracker` |
| 14 | `token_owner` |
| 15 | `token_level` |
| 16 | `token_outcome` |
| 17 | `token_acked` |
| 18 | `token_early_ack` |
| 19 | `token_order` |
| 20 | `token_time` |
| 21 | `packet_state` |
| 22 | `history_identity` |
| 23 | `rich_size` |
| 24 | `rich_timing` |
| 25 | `rich_ordinal` |
| 26 | `rich_delivery` |
| 27 | `rich_delivery_ordinal` |
| 28 | `rich_generation` |
| 29 | `rich_recovery` |
| 30 | `rich_recovery_ordinal` |
| 31 | `rich_recovery_state` |
| 32 | `rich_registration` |

For both member and packet counts, require `native.attempts = native.seam_attempts + sum(native.declines)`, `native.seam_attempts = recovery.attempts`, `native.successes = recovery.successes`, `recovery.attempts = recovery.successes + sum(recovery.declines)`, and `recovery.rich_attempts = recovery.rich_successes + sum(recovery.declines[23:33])`. Common preflight survival is `rich_attempts + successes - rich_successes`. Geometry must satisfy `handoffs = sum(size_buckets) = gso_handoffs + scalar_handoffs`. These identities apply to cumulative values and matching snapshot deltas.

All counters and arrays are connection-owned and survive local/controller resets because storage belongs to the native sender/emission owner. There are no extra packet/member clocks, endpoint locks, hot-path global atomics, queues, callbacks, ACK/model observers, or decision inputs. uint64 counters are not saturating: verify monotonic snapshots, conservation, `snapshot_overflow == 0`, and completed final freeze before interpreting the bounded run. Use actual common interior snapshot bounds for adjacent deltas; do not equate them with the exact 60-second useful-output window or whole-role CPU-profile duration. Whole-process profile paths overlap and cannot be added as removable cost.
