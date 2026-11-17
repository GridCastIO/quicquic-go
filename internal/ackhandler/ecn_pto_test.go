package ackhandler

import (
	"fmt"
	"slices"
	"testing"
	"time"

	"github.com/GridCastIO/quicquic-go/internal/monotime"
	"github.com/GridCastIO/quicquic-go/internal/protocol"
	"github.com/GridCastIO/quicquic-go/internal/utils"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"
)

func TestECNPTOTestingLoss(t *testing.T) {
	for _, local := range []bool{false, true} {
		for _, bbr := range []bool{false, true} {
			t.Run(fmt.Sprintf("local=%t/BBR=%t", local, bbr), func(t *testing.T) {
				var h *sentPacketHandler
				var recorder *congestionRecorder
				if local {
					h, recorder = newLocalECNTestHandler(t, bbr)
				} else {
					h = NewSentPacketHandler(0, 1200, utils.NewRTTStats(), &utils.ConnectionStats{}, true, true, nil, protocol.PerspectiveServer, nil, utils.DefaultLogger).(*sentPacketHandler)
					recorder = &congestionRecorder{}
					if bbr {
						controller := EnableBBR(h, 1200, func() protocol.ByteCount { return 0 })
						h.congestionEvents.sink = &localRichRecorder{recorder: recorder, controller: controller}
						EnableBBRECN(h, func(bool) (uint64, bool, bool) { return h.congestionEvents.pathGeneration, true, true })
					}
				}
				now := monotime.Time(time.Second)
				var frames packetTracker
				var pns []protocol.PacketNumber
				for range numECNTestingPackets {
					pn := h.PopPacketNumber(protocol.Encryption1RTT)
					pns = append(pns, pn)
					mark := h.ECNMode(true)
					require.Equal(t, protocol.ECT0, mark)
					if local {
						token, err := h.RegisterLocalPacket(PacketContext{}, now, pn, protocol.InvalidPacketNumber, nil, []Frame{frames.NewPingFrame(pn)}, protocol.Encryption1RTT, mark, 1200)
						require.NoError(t, err)
						require.NoError(t, h.CompleteLocalPacket(token, LocalPacketAccepted, now.Add(time.Millisecond)))
					} else {
						h.SentPacket(now, pn, protocol.InvalidPacketNumber, nil, []Frame{frames.NewPingFrame(pn)}, protocol.Encryption1RTT, mark, 1200, false, false)
					}
				}
				losses := func() uint64 {
					if bbr {
						return h.bbrECN.testingLost
					}
					return uint64(h.ecnTracker.(*ecnTracker).numLostTesting)
				}
				cwnd := h.congestion.GetCongestionWindow()
				for i := range pns {
					require.True(t, h.QueueProbePacketAt(protocol.Encryption1RTT, now.Add(2*time.Millisecond)))
					require.Equal(t, uint64(i+1), losses())
					require.Equal(t, pns[:i+1], frames.Lost)
				}
				require.False(t, h.QueueProbePacketAt(protocol.Encryption1RTT, now.Add(3*time.Millisecond)))
				require.Zero(t, h.bytesInFlight)
				require.Equal(t, cwnd, h.congestion.GetCongestionWindow(), "PTO retirement is not congestion loss")
				if bbr {
					require.Equal(t, ecnStateFailed, h.bbrECN.state)
				} else {
					require.Equal(t, ecnStateFailed, h.ecnTracker.(*ecnTracker).state)
				}
				for range 2 {
					ackBBRECNAt(t, h, now.Add(4*time.Millisecond), ackRanges(slices.Clone(pns)...), 10, 0)
					require.Equal(t, uint64(10), losses())
					require.Equal(t, pns, frames.Lost)
					require.Empty(t, frames.Acked, "retired frames must not settle again")
					require.Zero(t, h.bytesInFlight)
				}
				for _, feedback := range recorder.feedback {
					require.Empty(t, feedback.Lost, "PTO supplies no congestion-loss credit")
				}
			})
		}
	}
}

func TestECNPTOExcludesOtherEncryptionLevels(t *testing.T) {
	for _, level := range []protocol.EncryptionLevel{protocol.EncryptionInitial, protocol.EncryptionHandshake, protocol.Encryption0RTT} {
		t.Run(level.String(), func(t *testing.T) {
			h := NewSentPacketHandler(0, 1200, utils.NewRTTStats(), &utils.ConnectionStats{}, true, false, nil, protocol.PerspectiveServer, nil, utils.DefaultLogger).(*sentPacketHandler)
			h.ecnTracker = NewMockECNHandler(gomock.NewController(t)) // No ECN calls are permitted.
			now := monotime.Time(time.Second)
			sendCongestionTestPacket(h, now, level, 1200)
			queueLevel := level
			if level == protocol.Encryption0RTT {
				queueLevel = protocol.Encryption1RTT
			}
			require.True(t, h.QueueProbePacketAt(queueLevel, now.Add(time.Millisecond)))
			require.False(t, h.QueueProbePacketAt(queueLevel, now.Add(2*time.Millisecond)))
		})
	}
	t.Run("disabled", func(t *testing.T) {
		h := NewSentPacketHandler(0, 1200, utils.NewRTTStats(), &utils.ConnectionStats{}, true, false, nil, protocol.PerspectiveServer, nil, utils.DefaultLogger).(*sentPacketHandler)
		now := monotime.Time(time.Second)
		sendCongestionTestPacket(h, now, protocol.Encryption1RTT, 1200)
		require.True(t, h.QueueProbePacketAt(protocol.Encryption1RTT, now.Add(time.Millisecond)))
	})
}

func TestLocalECNPTOExcludesUnsent(t *testing.T) {
	for _, bbr := range []bool{false, true} {
		t.Run(fmt.Sprintf("BBR=%t", bbr), func(t *testing.T) {
			h, _ := newLocalECNTestHandler(t, bbr)
			now := monotime.Time(time.Second)
			_, token := localECNPacket(t, h, now)
			require.False(t, h.QueueProbePacketAt(protocol.Encryption1RTT, now.Add(time.Millisecond)), "pending transmission cannot be retired by PTO")
			require.NoError(t, h.CompleteLocalPacket(token, LocalPacketUnsubmitted, now.Add(2*time.Millisecond)))
			require.False(t, h.QueueProbePacketAt(protocol.Encryption1RTT, now.Add(3*time.Millisecond)))
			require.Equal(t, protocol.ECT0, h.ECNMode(true))
			if bbr {
				require.Zero(t, h.bbrECN.testingSent)
				require.Zero(t, h.bbrECN.testingLost)
			} else {
				require.Zero(t, h.ecnTracker.(*ecnTracker).numSentTesting)
				require.Zero(t, h.ecnTracker.(*ecnTracker).numLostTesting)
			}
		})
	}
}

func TestECNOrdinaryLossThenPTO(t *testing.T) {
	h := NewSentPacketHandler(0, 1200, utils.NewRTTStats(), &utils.ConnectionStats{}, true, true, nil, protocol.PerspectiveServer, nil, utils.DefaultLogger).(*sentPacketHandler)
	now := monotime.Time(time.Second)
	var frames packetTracker
	var pns []protocol.PacketNumber
	for range 11 {
		pn := h.PopPacketNumber(protocol.Encryption1RTT)
		pns = append(pns, pn)
		h.SentPacket(now, pn, protocol.InvalidPacketNumber, nil, []Frame{frames.NewPingFrame(pn)}, protocol.Encryption1RTT, h.ECNMode(true), 1200, false, false)
	}
	ackBBRECNAt(t, h, now.Add(time.Millisecond), ackRanges(pns[10]), 0, 0)
	tracker := h.ecnTracker.(*ecnTracker)
	require.Equal(t, uint8(8), tracker.numLostTesting)
	require.Equal(t, pns[:8], frames.Lost)
	for range 2 {
		require.True(t, h.QueueProbePacketAt(protocol.Encryption1RTT, now.Add(2*time.Millisecond)))
	}
	require.False(t, h.QueueProbePacketAt(protocol.Encryption1RTT, now.Add(3*time.Millisecond)))
	require.Equal(t, uint8(10), tracker.numLostTesting)
	require.Equal(t, pns[:10], frames.Lost)
	require.Equal(t, ecnStateFailed, tracker.state)
}

func TestECNPTOPathOwnership(t *testing.T) {
	for _, local := range []bool{false, true} {
		t.Run(fmt.Sprintf("local=%t", local), func(t *testing.T) {
			now := monotime.Time(time.Second)
			var h *sentPacketHandler
			if local {
				h, _ = newLocalECNTestHandler(t, true)
			} else {
				h = NewSentPacketHandler(0, 1200, utils.NewRTTStats(), &utils.ConnectionStats{}, true, false, nil, protocol.PerspectiveClient, nil, utils.DefaultLogger).(*sentPacketHandler)
				EnableBBR(h, 1200, func() protocol.ByteCount { return 0 })
				EnableBBRECN(h, func(bool) (uint64, bool, bool) { return h.congestionEvents.pathGeneration, true, true })
			}
			h.DropPackets(protocol.EncryptionInitial, now)
			h.DropPackets(protocol.EncryptionHandshake, now)
			auth := &testECNAuthority{drained: true, capable: true}
			ctx, sink := addTestBBRPath(t, h, 17, auth)
			send := func(id protocol.PathID, at monotime.Time) protocol.PacketNumber {
				t.Helper()
				target := h.RecoveryOnPath(id)
				if !local {
					return sendMarkedPathPacket(h, id, at, pingFrame)
				}
				pn := target.PopPacketNumber(protocol.Encryption1RTT)
				token, err := h.RegisterLocalPacket(PacketContext{PathID: id, TupleGeneration: auth.generation}, at, pn, protocol.InvalidPacketNumber, nil, []Frame{pingFrame(pn)}, protocol.Encryption1RTT, target.ECNMode(true), 1200)
				require.NoError(t, err)
				require.NoError(t, h.CompleteLocalPacket(token, LocalPacketAccepted, at.Add(time.Millisecond)))
				return pn
			}
			rootPN := send(0, now)
			oldPN := send(17, now)
			require.Equal(t, rootPN, oldPN, "overlapping numbers must remain path-local")
			require.True(t, ctx.QueueProbePacketAt(protocol.Encryption1RTT, now.Add(2*time.Millisecond)))
			require.Equal(t, uint64(1), ctx.bbrECN.testingLost)
			require.Zero(t, h.bbrECN.testingLost)
			require.Equal(t, protocol.ByteCount(1200), h.bytesInFlight)
			require.Zero(t, ctx.bytesInFlight)
			ctx.MigratedPath(now.Add(3*time.Millisecond), 1200)
			auth.generation = 1
			require.Equal(t, protocol.ECNNon, ctx.ECNMode(true))
			ecnPathAck(t, h, 17, 0, now.Add(4*time.Millisecond), 0, 1, oldPN)
			feedback := lastFeedback(t, &sink.congestionRecorder)
			require.False(t, feedback.ECN.Eligible)
			require.False(t, feedback.Congested)
			require.Equal(t, protocol.ECT0, ctx.ECNMode(true))
			require.Equal(t, ecnStateTesting, ctx.bbrECN.state, "old feedback cannot establish new-tuple capability")
			require.Zero(t, h.bbrECN.accepted)
			fresh := send(17, now.Add(5*time.Millisecond))
			ecnPathAck(t, h, 17, 0, now.Add(7*time.Millisecond), 1, 1, fresh)
			require.Equal(t, ecnStateCapable, ctx.bbrECN.state)
			for _, event := range sink.feedback {
				require.Empty(t, event.Lost)
			}
		})
	}
}
