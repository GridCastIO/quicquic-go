package ackhandler

import (
	"testing"
	"time"

	"github.com/GridCastIO/quicquic-go/internal/congestion"
	"github.com/GridCastIO/quicquic-go/internal/monotime"
	"github.com/GridCastIO/quicquic-go/internal/protocol"
	"github.com/stretchr/testify/require"
)

// Keep the real controller's methods while selecting the original generic local
// completion path. These short scenarios exercise neither ProbeRTT nor persistent
// congestion, whose post-feedback handling also recognizes the concrete BBR type.
type scalarLocalBBR struct {
	congestion.SendAlgorithmWithDebugInfos
}

func completeLocalBBRTest(t *testing.T, h *sentPacketHandler, token LocalCompletionToken, outcome LocalPacketOutcome, at monotime.Time, scalar bool) {
	t.Helper()
	b := h.congestion.(*congestion.BBRSender)
	require.False(t, b.InProbeRTT())
	if scalar {
		h.congestion = scalarLocalBBR{b}
		defer func() { h.congestion = b }()
	}
	require.NoError(t, h.CompleteLocalPacket(token, outcome, at))
}

func requireLocalBBREquivalent(t *testing.T, scalar, candidate *sentPacketHandler, sr, cr *congestionRecorder) {
	t.Helper()
	require.Equal(t, sr.feedback, cr.feedback)
	for _, event := range cr.feedback {
		require.Zero(t, event.PersistentCongestion.EndOrdinal, "the scalar reference preserves the concrete controller only outside completion")
	}
	require.Equal(t, scalar.BBRDiagnostics(), candidate.BBRDiagnostics())
	ss, cs := scalar.DeliveryStats(), candidate.DeliveryStats()
	require.LessOrEqual(t, cs.RecordBytes, ss.RecordBytes, "empty completions need not grow feedback scratch")
	ss.RecordBytes, cs.RecordBytes = 0, 0
	require.Equal(t, ss, cs)
	require.Equal(t, scalar.GetLossDetectionTimeout(), candidate.GetLossDetectionTimeout())
	require.Equal(t, scalar.bytesInFlight, candidate.bytesInFlight)
	require.Equal(t, scalar.local.owner, candidate.local.owner)
	require.Equal(t, scalar.appDataPackets.lossTime, candidate.appDataPackets.lossTime)
	require.Equal(t, scalar.appDataPackets.history.NumOutstanding(), candidate.appDataPackets.history.NumOutstanding())
	require.Equal(t, scalar.congestionEvents.event.Delivery, candidate.congestionEvents.event.Delivery)
	require.Equal(t, scalar.congestionEvents.recovery.episode, candidate.congestionEvents.recovery.episode)
	require.Equal(t, scalar.congestionEvents.recovery.ackOrdinal, candidate.congestionEvents.recovery.ackOrdinal)
	require.Equal(t, scalar.congestionEvents.sampler.timingGeneration, candidate.congestionEvents.sampler.timingGeneration)
	sb, cb := scalar.congestion.(*congestion.BBRSender), candidate.congestion.(*congestion.BBRSender)
	require.Equal(t, sb.GetCongestionWindow(), cb.GetCongestionWindow())
	require.Equal(t, sb.PacingRate(), cb.PacingRate())
	require.Equal(t, sb.InRecovery(), cb.InRecovery())
}

func TestLocalBBREmptyCompletionPreservesObservations(t *testing.T) {
	for _, outcome := range []LocalPacketOutcome{LocalPacketAccepted, LocalPacketUncertain} {
		t.Run(map[LocalPacketOutcome]string{LocalPacketAccepted: "accepted", LocalPacketUncertain: "uncertain"}[outcome], func(t *testing.T) {
			var handlers [2]*sentPacketHandler
			var recorders [2]*congestionRecorder
			for arm := range handlers {
				h, r := newLocalECNTestHandler(t, true)
				handlers[arm], recorders[arm] = h, r
				now := monotime.Time(time.Second)
				pn, token := localECNPacket(t, h, now)
				completeLocalBBRTest(t, h, token, LocalPacketAccepted, now.Add(time.Millisecond), arm == 0)
				ackBBRECNAt(t, h, now.Add(10*time.Millisecond), ackRanges(pn), 1, 0)
				require.True(t, h.congestionEvents.event.Delivery.Valid)
				_, token = localECNPacket(t, h, now.Add(20*time.Millisecond))
				// A previous classifier's alarm must be cleared even when the physical
				// prefix now proves there is nothing at or below the ACK watermark.
				h.appDataPackets.lossTime = now.Add(21 * time.Millisecond)
				before := len(r.feedback)
				completeLocalBBRTest(t, h, token, outcome, now.Add(22*time.Millisecond), arm == 0)
				require.Len(t, r.feedback, before, "an empty completion sends no controller event")
				require.Zero(t, h.appDataPackets.lossTime)
				require.False(t, h.congestionEvents.event.Delivery.Valid)
				require.Zero(t, h.congestionEvents.event.Delivery.Interval)
			}
			requireLocalBBREquivalent(t, handlers[0], handlers[1], recorders[0], recorders[1])
		})
	}
}

func TestLocalBBRCompletionPreservesLossAndSpuriousRecovery(t *testing.T) {
	var handlers [2]*sentPacketHandler
	var recorders [2]*congestionRecorder
	for arm := range handlers {
		h, r := newLocalECNTestHandler(t, true)
		// Both arms ACK the same six-packet sequence; keep random skips outside it.
		h.appDataPackets.pns.(*skippingPacketNumberGenerator).nextToSkip = 10000
		handlers[arm], recorders[arm] = h, r
		now := monotime.Time(time.Second)
		low, pending := localECNPacket(t, h, now)
		var high protocol.PacketNumber
		for range 4 {
			pn, token := localECNPacket(t, h, now.Add(time.Millisecond))
			high = pn
			completeLocalBBRTest(t, h, token, LocalPacketAccepted, now.Add(2*time.Millisecond), arm == 0)
		}
		ackBBRECNAt(t, h, now.Add(10*time.Millisecond), ackRanges(high), 1, 0)
		require.NotNil(t, pending.registration.packet, "pending native work is not network loss")
		before := len(r.feedback)
		completeLocalBBRTest(t, h, pending, LocalPacketAccepted, now.Add(11*time.Millisecond), arm == 0)
		require.Len(t, r.feedback, before+1)
		require.Len(t, r.feedback[before].Lost, 1)
		require.Equal(t, low, r.feedback[before].Lost[0].PacketNumber)
		require.True(t, h.congestion.InRecovery())
		// A subsequent empty completion must retain the active episode; later
		// real receipts still settle its spurious loss and boundary crossing.
		fresh, token := localECNPacket(t, h, now.Add(12*time.Millisecond))
		completeLocalBBRTest(t, h, token, LocalPacketAccepted, now.Add(13*time.Millisecond), arm == 0)
		ackBBRECNAt(t, h, now.Add(20*time.Millisecond), ackRanges(low, 1, 2, 3, high, fresh), 6, 0)
		require.False(t, h.congestion.InRecovery())
	}
	requireLocalBBREquivalent(t, handlers[0], handlers[1], recorders[0], recorders[1])
}

func TestLocalBBRCompletionPreservesDelayedECNAndEarlyACK(t *testing.T) {
	var handlers [2]*sentPacketHandler
	var recorders [2]*congestionRecorder
	for arm := range handlers {
		h, r := newLocalECNTestHandler(t, true)
		handlers[arm], recorders[arm] = h, r
		now := monotime.Time(time.Second)
		pn, early := localECNPacket(t, h, now)
		_, pending := localECNPacket(t, h, now)
		ackBBRECNAt(t, h, now.Add(time.Millisecond), ackRanges(pn), 1, 1)
		require.True(t, h.local.ecn.pending)
		before := len(r.feedback)
		completeLocalBBRTest(t, h, pending, LocalPacketAccepted, now.Add(2*time.Millisecond), arm == 0)
		require.Len(t, r.feedback, before+1)
		event := r.feedback[before]
		require.False(t, event.HasAck)
		require.True(t, event.ECNChecked)
		require.Equal(t, uint64(1), event.ECN.Delta.CE)
		before = len(r.feedback)
		delivery := h.congestionEvents.event.Delivery
		completeLocalBBRTest(t, h, early, LocalPacketAccepted, now.Add(3*time.Millisecond), arm == 0)
		require.Len(t, r.feedback, before, "the early ACK already retired protocol ownership")
		require.Equal(t, delivery, h.congestionEvents.event.Delivery, "a retired identity returns before the empty-sample update")
	}
	requireLocalBBREquivalent(t, handlers[0], handlers[1], recorders[0], recorders[1])
}
