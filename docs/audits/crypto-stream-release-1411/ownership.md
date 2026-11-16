# Ownership evidence for issue #1411

Source comparison: baseline `f11a20cf56d7dcf682e5e02e7969ccd7bcd7811a`, candidate `70924089d427bc6cf94eb8f1220585ee15326d32`. Governing [contract](../../agents/crypto-stream-release-1411.md); [issue #1411](https://github.com/the-sarge/quic-go-fast/issues/1411).

## Retention graph

| Owner | Reference / storage | Lifetime after discard |
| --- | --- | --- |
| `Conn`, `packetPacker` | Baseline direct Initial/Handshake stream fields | Candidate retains only the manager; neither can keep a discarded stream alive |
| `cryptoStreamManager` | Initial, Handshake, and 1-RTT stream references | Initial/Handshake cleared by `Drop`; 1-RTT survives |
| `baseCryptoStream` | Receive `frameSorter` queues/gaps and outgoing `writeBuf` | Collectible with the stream, except independent frame/data owners; no zeroing or pool return |
| `initialCryptoStream` | Embedded base plus ClientHello cuts and send offsets | Same lifetime; scrambling stays inside the stream until actual discard |
| CRYPTO frames | `Data` slices into outgoing stream allocations | Frames retain bytes independently; GC cannot collect a reachable backing array |
| `retransmissionQueue` | Per-level crypto and other frame slices | `DropPackets` clears the level; previously issued handlers see nil and reject subsequent loss callbacks |
| Recovery packet-number spaces | Packet history and frame handlers | Existing `sentPacketHandler.DropPackets` retires local records and removes Initial/Handshake history |
| Local completion registrations | `localRegistration.packet` | Existing `retireLocal` clears the packet pointer at protocol retirement; the retained epoch has no history reference |
| In-progress coalesced emission | Constructed packet metadata, frame slices, sealed `packet.buffer` | Function-local owners survive registration-time discard; serialized data has already been appended to the packet buffer |
| `sendQueue` / native handoff | Packet buffer and completion metadata | Existing output ownership survives until submission/disposal; no stream lookup by the worker and no new buffer reuse |
| TLS | Events, transcript and TLS output buffers | Unchanged and explicitly outside scope; release of stream ownership does not promise removal of TLS retention |

`packetPacker.appendLongHeaderPacket` / `appendPacketPayload` serialize frames into the construction buffer before sealing. A frame's backing slice can therefore outlive the stream, while a constructed datagram owns its independently serialized bytes. Neither discard nor the manager accesses or clears either allocation through an outgoing alias. Native and ordinary send paths retain their existing packet/owned-datagram storage until completion; their ownership architecture is unchanged.

## Lifecycle argument

The connection goroutine owns every manager mutation. `handleHandshakeEvents` drains TLS writes and validates the preceding receive stream with `Finish` when newer read keys become available. Finishing does not drop a stream. `HandleCryptoFrame`, `GetCryptoData`, and `Finish` retain their existing validation and errors; they require a usable level rather than accepting fabricated calls after discard.

Server Initial discard occurs when processing the first authenticated Handshake packet, before processing that packet's frames. Client Initial discard occurs synchronously when its first Handshake packet is registered; all packets in that datagram were constructed first. Both happen after the Initial read-key/finish transition and the applicable outgoing TLS events. Handshake confirmation also discards Initial defensively, so discard is idempotent.

The server confirms at handshake completion; the client confirms on HANDSHAKE_DONE or an ACK proving reception of a 1-RTT packet. The confirmation function discards Initial and Handshake and then clears Handshake keys through `SetHandshakeConfirmed` without yielding the connection goroutine. ACK-triggered confirmation occurs in a 1-RTT packet, whose remaining CRYPTO frames belong to the surviving 1-RTT stream. Discarded-level packets cannot subsequently reach the manager through packet unpacking because their openers have been removed. Replay of previously undecryptable packets goes back through unpacking. Retry retains its existing Initial-stream replay behavior and does not use irreversible discard; version negotiation replaces the connection rather than resurrecting a discarded manager.

The coordinator retains the existing recovery/receive cleanup order, then releases the stream and retransmission queue for the discarded level. Recovery retirement does not schedule an independent callback; late frame handlers refer to the queue, whose nil level remains the central rejection guard. 0-RTT rejection bypasses this cleanup and preserves its existing stream/framer/flow-control reset behavior.

## Behavioral evidence

`TestConnectionDiscardCryptoStorage` failed at the baseline for both levels: drained write arrays survived GC while only the live connection remained. It passes at the candidate and separately verifies that an outstanding frame owner preserves bytes across two discards and GC. `TestConnectionDiscardCryptoRetransmissions` failed before connecting queue cleanup, then passed for both levels, including late callbacks and surviving application recovery. Receive-sorter retention and manager availability have focused regressions.

`TestConnectionDiscardCryptoPendingSend` exercises real packet construction and recovery registration for both perspectives, blocks the asynchronous sender while it borrows the datagram, discards both levels, starts shutdown, and checks that shutdown waits and bytes remain unchanged. This covers the ownership handoff without pretending to enumerate native scheduler interleavings. Existing native tests, real loopback measurements, and hosted operating-system checks supplement it.

Existing stream/manager tests cover unread-data errors, maximum offsets, duplicates and post-finish behavior. Existing connection regressions cover handshake completion/confirmation, Retry, version negotiation, 0-RTT rejection, session tickets and coalesced emissions. `TestDiscardedCryptoDeliveryLimitation` checks application-limited classification after discard and unknown classification while 1-RTT crypto retransmission remains.

Focused race validation passed on Darwin/arm64 with Go 1.27.4, including the new lifetime tests and relevant native ordinary/software paths. The root, recovery, and handshake packages also passed. This is not native Linux/Windows qualification; applicable hosted checks supply their existing coverage. No added fuzz, timing, or platform cross-product is claimed.
