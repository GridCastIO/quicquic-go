//go:build linux || darwin || windows

package quic

import (
	"testing"
	"time"

	"github.com/GridCastIO/quicquic-go/internal/ackhandler"
	"github.com/GridCastIO/quicquic-go/internal/monotime"
	"github.com/GridCastIO/quicquic-go/internal/protocol"
	"github.com/GridCastIO/quicquic-go/internal/wire"
	"github.com/stretchr/testify/require"
)

func TestJumboFallbackPreservesBBRECN(t *testing.T) {
	for _, stage := range []string{"migration only", "stage one", "initial size"} {
		t.Run(stage, func(t *testing.T) {
			c := newJumboRefusalEmission(t, "bbrv3").conn
			// The refusal fixture normally stamps generation 9. Start on the
			// initial path shared by recovery and production local credit.
			c.pathGeneration = 0
			c.conn = &ecnTestSendConn{sendConn: c.conn, capable: true}
			q := c.emission.queue.(*sendQueue)
			t.Cleanup(func() {
				for len(q.queue) > 0 {
					(<-q.queue).release()
				}
			})
			now := monotime.Now()
			var unacked []protocol.PacketNumber
			var ect0 uint64
			emit := func(ping bool) queueEntry {
				t.Helper()
				pn, _ := c.sentPacketHandler.PeekPacketNumber(protocol.Encryption1RTT)
				if ping {
					c.queueControlFrame(&wire.PingFrame{})
				}
				result := c.triggerSending(now)
				require.NoError(t, result.err)
				if result.deadline > 0 && !result.progress {
					now = result.deadline
					result = c.triggerSending(now)
					require.NoError(t, result.err)
				}
				require.True(t, result.progress)
				require.Len(t, q.queue, 1)
				entry := <-q.queue
				unacked = append(unacked, pn)
				require.Equal(t, protocol.ECT0, entry.ecn)
				return entry
			}
			ack := func(all bool) {
				t.Helper()
				n := len(unacked) - 1
				if all {
					n = 0
				}
				var ranges []wire.AckRange
				for i := len(unacked) - 1; i >= n; i-- {
					pn := unacked[i]
					if len(ranges) > 0 && ranges[len(ranges)-1].Smallest == pn+1 {
						ranges[len(ranges)-1].Smallest = pn
					} else {
						ranges = append(ranges, wire.AckRange{Smallest: pn, Largest: pn})
					}
					ect0++
				}
				unacked = unacked[:n]
				now = now.Add(time.Millisecond)
				_, err := c.sentPacketHandler.ReceivedAck(&wire.AckFrame{AckRanges: ranges, ECT0: ect0}, protocol.Encryption1RTT, now)
				require.NoError(t, err)
			}

			// Successful feedback validates ECN before the size reduction.
			emit(true).release()
			ack(true)
			if stage != "migration only" {
				c.packetSizeFeedback.publish(c.pathGeneration, 8957)
				c.applyPacketSizeFallback(now)
				require.True(t, c.mtuFallback.active)
				require.EqualValues(t, 1438, c.mtuFallback.size)
				require.Equal(t, protocol.ECT0, c.sentPacketHandler.ECNMode(true), "same-tuple fallback must preserve validated ECN")
				if stage == "initial size" {
					for range ackhandler.MaxMTURecoveryProbes {
						emit(false).release() // padded confirmation probe is not ACKed yet
						now = c.mtuFallback.probe.deadline
						emit(false).release() // follow-up PING demonstrates liveness
						ack(false)
						c.advancePacketSizeRecovery(now)
					}
					require.EqualValues(t, 1232, c.mtuFallback.size)
					require.Equal(t, protocol.ECT0, c.sentPacketHandler.ECNMode(true))
				}
				emit(false).release()
				// Late ACKs of the retired probes complete the cumulative marking
				// evidence needed by the later migration, without confirming an old size.
				ack(true)
				require.True(t, c.mtuFallback.confirmed)
				require.Zero(t, c.pathGeneration)
				require.Zero(t, c.mtuFallback.generation)
			}

			// Hold one real emitted packet across migration: ACK evidence alone
			// cannot release the production authority's old-generation send fence.
			now = now.Add(time.Second)
			pending := emit(true)
			defer func() {
				if pending.buf != nil {
					pending.release()
				}
			}()
			c.pathGeneration++
			c.sentPacketHandler.MigratedPath(now, 1232)
			c.emission.resetLocalPath(c.pathGeneration, now)
			require.Equal(t, protocol.ECNNon, c.sentPacketHandler.ECNMode(true))
			ack(true)
			require.Equal(t, protocol.ECNNon, c.sentPacketHandler.ECNMode(true))
			pending.release()
			pending.buf = nil
			require.Equal(t, protocol.ECT0, c.sentPacketHandler.ECNMode(true), "marking must resume after counters and old sends drain")
		})
	}
}

// CE-only discovery can establish jumbo delivery without establishing ECN
// capability. A later dedicated probe loss must still reach that testing epoch.
func TestJumboFallbackTestingECNLoss(t *testing.T) {
	c := newConfiguredEmissionTestConnection(t, false, &Config{InitialPacketSize: 1452, EnableDatagrams: true}).conn
	sink := installEmissionBBRECN(c)
	c.packetCeiling = 8972
	c.peerParams = &wire.TransportParameters{MaxUDPPayloadSize: 8972}
	c.packetSizeFeedback.wakeup = make(chan struct{}, 1)
	c.mtuFallback.dropped = make(chan struct{})
	c.mtuDiscoverer = c.newPathMTUFinder(1452, 8972)
	ackhandler.ObservePacketSize(c.sentPacketHandler, c.confirmPacketSizeFallback, c.notePacketSizeLoss)
	q := c.emission.queue.(*sendQueue)
	t.Cleanup(func() {
		for len(q.queue) > 0 {
			(<-q.queue).release()
		}
	})
	now := monotime.Now()
	var ce uint64
	ackDelay := time.Millisecond
	ack := func(pn protocol.PacketNumber) {
		t.Helper()
		now = now.Add(ackDelay)
		ce++
		_, err := c.sentPacketHandler.ReceivedAck(&wire.AckFrame{AckRanges: []wire.AckRange{{Smallest: pn, Largest: pn}}, ECNCE: ce}, protocol.Encryption1RTT, now)
		require.NoError(t, err)
	}
	take := func() {
		t.Helper()
		require.Len(t, q.queue, 1)
		entry := <-q.queue
		defer entry.release()
		require.Equal(t, protocol.ECT0, entry.ecn)
	}
	c.mtuDiscoverer.Start(now)
	now = c.mtuDiscoverer.NextProbeTime()
	discovery, _ := c.sentPacketHandler.PeekPacketNumber(protocol.Encryption1RTT)
	result := c.triggerSending(now)
	require.NoError(t, result.err)
	if !result.progress && result.deadline > 0 {
		now = result.deadline
		result = c.triggerSending(now)
	}
	require.True(t, result.progress, "%+v", result)
	take()
	ack(discovery)
	require.Greater(t, c.maxPacketSize(), protocol.ByteCount(protocol.MaxPacketBufferSize))
	require.False(t, sink.events[len(sink.events)-1].ECN.Eligible)
	require.False(t, sink.events[len(sink.events)-1].ECN.Failed)
	require.Equal(t, protocol.ECT0, c.sentPacketHandler.ECNMode(true))

	c.packetSizeFeedback.publish(c.pathGeneration, c.maxPacketSize())
	c.applyPacketSizeFallback(now)
	require.True(t, c.mtuFallback.active)
	require.EqualValues(t, 1452, c.mtuFallback.size)
	require.True(t, c.triggerSending(now).progress)
	take()
	probe := c.mtuFallback.probe
	require.NotNil(t, probe)
	ackDelay = time.Microsecond

	// Send the remaining testing packets before the owned deadline. Their small
	// CE-only ACKs establish liveness without establishing ECN capability.
	for range 8 {
		pn, _ := c.sentPacketHandler.PeekPacketNumber(protocol.Encryption1RTT)
		c.queueControlFrame(&wire.PingFrame{})
		result := c.triggerSending(now)
		require.NoError(t, result.err)
		require.True(t, result.progress)
		take()
		ack(pn)
		require.True(t, now.Before(probe.deadline))
	}
	require.Equal(t, uint64(9), ce)
	require.True(t, probe.laterSmallAck)
	require.Zero(t, c.mtuFallback.lost, "later ACK alone supplies no loss verdict")
	require.False(t, sink.events[len(sink.events)-1].ECN.Failed)
	now = probe.deadline
	c.advancePacketSizeRecovery(now)
	require.Equal(t, 1, c.mtuFallback.lost)
	// A subsequent admitted ACK exposes the validator result. This fresh probe
	// is Not-ECT in both Unknown and Failed, so it adds no marked receipt.
	pn, _ := c.sentPacketHandler.PeekPacketNumber(protocol.Encryption1RTT)
	require.True(t, c.triggerSending(now).progress)
	require.Len(t, q.queue, 1)
	entry := <-q.queue
	require.Equal(t, protocol.ECNNon, entry.ecn)
	entry.release()
	_, err := c.sentPacketHandler.ReceivedAck(&wire.AckFrame{AckRanges: []wire.AckRange{{Smallest: pn, Largest: pn}}, ECNCE: ce}, protocol.Encryption1RTT, now.Add(time.Millisecond))
	require.NoError(t, err)
	require.True(t, c.mtuFallback.confirmed)
	require.True(t, sink.events[len(sink.events)-1].ECN.Failed, "CE receipts plus the qualified probe loss must finish ECN validation")
	for _, event := range sink.events {
		require.Empty(t, event.Lost, "dedicated loss supplies no congestion-loss credit")
	}
}

func TestJumboRecheckTestingECNLoss(t *testing.T) {
	for _, laterSmallACK := range []bool{false, true} {
		name := "no later small ACK"
		if laterSmallACK {
			name = "qualified loss"
		}
		t.Run(name, func(t *testing.T) {
			c := newJumboRefusalEmission(t).conn
			c.pathGeneration = 0
			sink := installEmissionBBRECN(c)
			c.emission.bbr = newBBRSendPolicyWithCeiling(1_000_000, c.maxPacketSize(), c.packetCeiling.size(), monotime.Now())
			ackhandler.ObservePacketSize(c.sentPacketHandler, c.confirmPacketSizeFallback, c.notePacketSizeLoss)
			q := c.emission.queue.(*sendQueue)
			t.Cleanup(func() {
				for len(q.queue) > 0 {
					(<-q.queue).release()
				}
			})
			now := monotime.Now()
			var ce uint64
			send := func(ping bool, mark protocol.ECN) protocol.PacketNumber {
				t.Helper()
				pn, _ := c.sentPacketHandler.PeekPacketNumber(protocol.Encryption1RTT)
				if ping {
					c.queueControlFrame(&wire.PingFrame{})
				}
				result := c.triggerSending(now)
				require.NoError(t, result.err)
				if !result.progress && result.deadline > 0 {
					now = result.deadline
					result = c.triggerSending(now)
					require.NoError(t, result.err)
				}
				require.True(t, result.progress)
				require.Len(t, q.queue, 1)
				entry := <-q.queue
				require.Equal(t, mark, entry.ecn)
				entry.release()
				return pn
			}
			ack := func(pn protocol.PacketNumber, marked bool) {
				t.Helper()
				now = now.Add(time.Microsecond)
				if marked {
					ce++
				}
				_, err := c.sentPacketHandler.ReceivedAck(&wire.AckFrame{AckRanges: []wire.AckRange{{Smallest: pn, Largest: pn}}, ECNCE: ce}, protocol.Encryption1RTT, now)
				require.NoError(t, err)
			}
			// Feed the existing watch's three ordinary-loss facts; its liveness ACK
			// and subsequent padded recheck both use real emission and registration.
			for range 3 {
				c.notePacketSizeLoss(ackhandler.PacketContext{}, c.maxPacketSize(), now)
			}
			now = c.mtuWatch.deadline
			ack(send(false, protocol.ECT0), true)
			require.True(t, c.mtuWatch.recheck)
			send(false, protocol.ECT0)
			probe := c.mtuWatch.probe
			require.NotNil(t, probe)
			if laterSmallACK {
				// The first send is the small follow-up; the others are ordinary PINGs.
				for i := range 8 {
					ack(send(i != 0, protocol.ECT0), true)
				}
				require.True(t, now.Before(probe.deadline))
				require.True(t, probe.laterSmallAck)
				now = probe.deadline
				c.advancePacketSizeWatch(now)
				require.Equal(t, 1, c.mtuWatch.lostProbes)
			} else {
				now = probe.deadline
				c.advancePacketSizeWatch(now)
				require.False(t, c.mtuWatch.recheck, "expiry without small delivery returns to liveness")
				require.Zero(t, c.mtuWatch.lostProbes)
				ack(send(false, protocol.ECT0), true) // liveness
				ack(send(false, protocol.ECT0), true) // successful recheck clears the watch
				require.False(t, c.mtuWatch.checking)
				for range 6 {
					ack(send(true, protocol.ECT0), true)
				}
			}
			require.Equal(t, uint64(9), ce)
			ack(send(true, protocol.ECNNon), false)
			require.Equal(t, laterSmallACK, sink.events[len(sink.events)-1].ECN.Failed)
			for _, event := range sink.events {
				require.Empty(t, event.Lost)
			}
		})
	}
}
