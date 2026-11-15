//go:build linux || darwin || windows

package quic

import (
	"testing"
	"time"

	"github.com/quic-go/quic-go/internal/ackhandler"
	"github.com/quic-go/quic-go/internal/monotime"
	"github.com/quic-go/quic-go/internal/protocol"
	"github.com/quic-go/quic-go/internal/wire"
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
