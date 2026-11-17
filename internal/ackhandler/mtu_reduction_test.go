package ackhandler

import (
	"fmt"
	"testing"
	"time"

	"github.com/GridCastIO/quicquic-go/internal/monotime"
	"github.com/GridCastIO/quicquic-go/internal/protocol"
	"github.com/GridCastIO/quicquic-go/internal/utils"
	"github.com/GridCastIO/quicquic-go/internal/wire"
	"github.com/stretchr/testify/require"
)

func TestMTUReductionRenoPacing(t *testing.T) {
	for _, size := range []protocol.ByteCount{1200, 1452} {
		t.Run(fmt.Sprint(size), func(t *testing.T) {
			rtt := utils.NewRTTStats()
			rtt.UpdateRTT(time.Second, 0)
			h := NewSentPacketHandler(0, 1500, rtt, &utils.ConnectionStats{}, true, false, nil, protocol.PerspectiveClient, nil, utils.DefaultLogger).(*sentPacketHandler)
			now := monotime.Time(1)
			sendCongestionTestPacket(h, now, protocol.Encryption1RTT, 1500)
			ResetForMTUReduction(h, now, size, nil)
			require.Zero(t, h.bytesInFlight)
			// The reset sender retains the one-second RTT and starts with a
			// ten-packet burst at the reduced size, followed by 40 packets/s.
			for range 10 {
				require.True(t, h.congestion.HasPacingBudget(now))
				require.Zero(t, h.TimeUntilSend())
				sendCongestionTestPacket(h, now, protocol.Encryption1RTT, size)
			}
			require.False(t, h.congestion.HasPacingBudget(now))
			deadline := h.TimeUntilSend()
			require.Equal(t, 25*time.Millisecond, deadline.Sub(now))
			require.False(t, h.congestion.HasPacingBudget(deadline.Add(-time.Nanosecond)))
			require.True(t, h.congestion.HasPacingBudget(deadline))
		})
	}
}

func TestMTUReductionPreservesECNAndResetsSamples(t *testing.T) {
	h, r := newBBRECNTestHandler()
	first := sendBBRECNPacket(h, h.ECNMode(true), false)
	ackBBRECN(t, h, ackRanges(first), 1, 0)
	require.True(t, r.feedback[len(r.feedback)-1].ECN.Eligible)
	for i, size := range []protocol.ByteCount{1438, 1232} {
		old := sendBBRECNPacket(h, h.ECNMode(true), false)
		oldSample := r.sends[len(r.sends)-1].Packet.SampleGeneration
		rtt := h.rttStats.SmoothedRTT()
		ResetForMTUReduction(h, monotime.Now(), size, nil)
		require.Zero(t, h.bytesInFlight)
		require.Equal(t, rtt, h.rttStats.SmoothedRTT())
		require.Equal(t, protocol.ECT0, h.ECNMode(true))
		fresh := sendBBRECNPacket(h, h.ECNMode(true), false)
		packet := r.sends[len(r.sends)-1].Packet
		require.Zero(t, packet.PathGeneration)
		require.Greater(t, packet.SampleGeneration, oldSample)

		// Old markings still contribute cumulative ECN evidence, but the
		// retired registration cannot supply a new delivery-rate sample.
		ackBBRECN(t, h, ackRanges(old), uint64(2+2*i), 0)
		event := r.feedback[len(r.feedback)-1]
		require.Empty(t, event.Acked)
		require.False(t, event.Delivery.Valid)
		require.True(t, event.ECN.Eligible)
		ackBBRECN(t, h, ackRanges(fresh), uint64(3+2*i), 0)
		require.True(t, r.feedback[len(r.feedback)-1].ECN.Eligible)
	}
}

func TestMTUReductionPreservesECNRestrictions(t *testing.T) {
	t.Run("invalid counters", func(t *testing.T) {
		h, r := newBBRECNTestHandler()
		first := sendBBRECNPacket(h, h.ECNMode(true), false)
		ackBBRECN(t, h, ackRanges(first), 1, 0)
		next := sendBBRECNPacket(h, h.ECNMode(true), false)
		ackBBRECN(t, h, ackRanges(next), 0, 0)
		require.True(t, r.feedback[len(r.feedback)-1].ECN.Failed)
		ResetForMTUReduction(h, monotime.Now(), 1232, nil)
		require.Equal(t, protocol.ECNNon, h.ECNMode(true))
	})

	t.Run("migration in progress", func(t *testing.T) {
		h, r := newBBRECNTestHandler()
		first := sendBBRECNPacket(h, h.ECNMode(true), false)
		ackBBRECN(t, h, ackRanges(first), 1, 0)
		old := sendBBRECNPacket(h, h.ECNMode(true), false)
		h.MigratedPath(monotime.Now(), 1438)
		drained, capable := false, true
		// The connection's authority advances once for migration, and not
		// again when the packet budget shrinks on that tuple.
		h.bbrECN.path = func(bool) (uint64, bool, bool) { return 1, drained, capable }
		ResetForMTUReduction(h, monotime.Now().Add(time.Millisecond), 1232, nil)
		require.Equal(t, protocol.ECNNon, h.ECNMode(true))
		drained = true
		require.Equal(t, protocol.ECNNon, h.ECNMode(true), "drain alone cannot replace cumulative counter evidence")
		drained = false
		ackBBRECN(t, h, ackRanges(old), 2, 0)
		require.False(t, r.feedback[len(r.feedback)-1].ECN.Eligible)
		require.Equal(t, protocol.ECNNon, h.ECNMode(true), "counter evidence alone cannot replace send drain")
		drained, capable = true, false
		require.Equal(t, protocol.ECNUnsupported, h.ECNMode(true))
		capable = true
		require.Equal(t, protocol.ECT0, h.ECNMode(true))
	})
}

type mtuRecoveryTestHandler struct{ FrameHandler }

func (*mtuRecoveryTestHandler) IsMTURecoveryPacket() {}

func TestMTURecoveryECNLossVerdict(t *testing.T) {
	for _, bbr := range []bool{false, true} {
		for _, verdict := range []string{"lost", "cancelled", "confirmed"} {
			t.Run(fmt.Sprintf("BBR=%t/%s", bbr, verdict), func(t *testing.T) {
				h := NewSentPacketHandler(0, 1452, utils.NewRTTStats(), &utils.ConnectionStats{}, true, true, nil, protocol.PerspectiveServer, nil, utils.DefaultLogger).(*sentPacketHandler)
				recorder := &congestionRecorder{}
				if bbr {
					controller := EnableBBR(h, 1452, func() protocol.ByteCount { return 0 })
					h.congestionEvents.sink = &localRichRecorder{recorder: recorder, controller: controller}
					EnableBBRECN(h, func(bool) (uint64, bool, bool) { return h.congestionEvents.pathGeneration, true, true })
				}
				now := monotime.Time(time.Second)
				var confirmations []protocol.PacketNumber
				ObservePacketSize(h, func(_ PacketContext, _ protocol.ByteCount, pn protocol.PacketNumber) {
					confirmations = append(confirmations, pn)
				}, nil)
				var frames packetTracker
				pn := h.PopPacketNumber(protocol.Encryption1RTT)
				ping := frames.NewPingFrame(pn)
				ping.Handler = &mtuRecoveryTestHandler{ping.Handler}
				h.SentPacket(now, pn, protocol.InvalidPacketNumber, nil, []Frame{ping}, protocol.Encryption1RTT, h.ECNMode(true), 1452, true, false)
				// Unrelated flight survives dedicated retirement.
				other := h.PopPacketNumber(protocol.Encryption1RTT)
				h.SentPacket(now, other, protocol.InvalidPacketNumber, nil, []Frame{{Frame: &wire.PingFrame{}}}, protocol.Encryption1RTT, protocol.ECNNon, 64, false, false)
				if verdict == "confirmed" {
					ackBBRECNAt(t, h, now.Add(time.Millisecond), ackRanges(pn), 0, 1)
				}
				cwnd := h.congestion.GetCongestionWindow()
				if verdict == "lost" {
					DeclareMTURecoveryProbesLost(h, now.Add(time.Millisecond))
				} else {
					RetireMTURecoveryProbes(h, now.Add(time.Millisecond))
				}
				// Repeated loss declaration cannot recreate a retired packet's verdict.
				DeclareMTURecoveryProbesLost(h, now.Add(2*time.Millisecond))
				require.Equal(t, protocol.ByteCount(64), h.bytesInFlight)
				require.Equal(t, cwnd, h.congestion.GetCongestionWindow())
				losses := func() uint64 {
					if bbr {
						return h.bbrECN.testingLost
					}
					return uint64(h.ecnTracker.(*ecnTracker).numLostTesting)
				}
				wantLosses := uint64(0)
				if verdict == "lost" {
					wantLosses = 1
				}
				require.Equal(t, wantLosses, losses())
				require.Empty(t, frames.Lost)
				for range 2 {
					ackBBRECNAt(t, h, now.Add(3*time.Millisecond), ackRanges(pn), 0, 1)
				}
				require.Equal(t, wantLosses, losses())
				require.Equal(t, protocol.ByteCount(64), h.bytesInFlight)
				if verdict == "cancelled" {
					require.Empty(t, confirmations)
				} else {
					require.Equal(t, []protocol.PacketNumber{pn}, confirmations)
				}
				for _, event := range recorder.feedback {
					require.Empty(t, event.Lost)
				}
				RetireMTURecoveryProbes(h, now.Add(4*time.Millisecond))
				require.Empty(t, h.mtuRecoveryAcks)
			})
		}
	}
}
