package ackhandler

import (
	"fmt"
	"testing"
	"time"

	"github.com/quic-go/quic-go/internal/monotime"
	"github.com/quic-go/quic-go/internal/protocol"
	"github.com/quic-go/quic-go/internal/utils"
	"github.com/stretchr/testify/require"
)

type localMemberTimerLogger struct {
	utils.Logger
	canceled int
}

func (l *localMemberTimerLogger) Debugf(format string, args ...any) {
	if format == "Canceling loss detection timer." {
		l.canceled++
	}
	l.Logger.Debugf(format, args...)
}

func newLocalBBRUnwitnessedMemberTest(t *testing.T, count int, kind string) (*sentPacketHandler, *congestionRecorder, []LocalCompletionToken, LocalCompletionToken, monotime.Time) {
	t.Helper()
	h, recorder := newLocalECNTestHandler(t, true)
	now := monotime.Time(time.Second)
	h.DropPackets(protocol.EncryptionInitial, now)
	h.DropPackets(protocol.EncryptionHandshake, now)
	h.appDataPackets.pns.(*skippingPacketNumberGenerator).nextToSkip = 10000
	t.Cleanup(func() { h.CloseLocal(now.Add(time.Second)) })
	if kind == "trained and ACK drained" {
		var pns []protocol.PacketNumber
		for range 2 {
			pn, token := localECNPacket(t, h, now)
			pns = append(pns, pn)
			require.NoError(t, h.CompleteLocalPacket(token, LocalPacketAccepted, now.Add(time.Millisecond)))
		}
		ackBBRECNAt(t, h, now.Add(2*time.Millisecond), ackRanges(pns...), 2, 0)
		require.False(t, h.appDataPackets.history.HasOutstandingPackets())
		require.True(t, h.congestionEvents.event.Delivery.Valid)
	}
	now = now.Add(5 * time.Millisecond)
	var prior LocalCompletionToken
	if kind == "pending predecessor" {
		_, prior = localECNPacket(t, h, now)
	}
	tokens := make([]LocalCompletionToken, count)
	for i := range tokens {
		_, tokens[i] = localECNPacket(t, h, now)
	}
	require.Zero(t, h.appDataPackets.history.latestLocalPTO())
	require.True(t, h.appDataPackets.history.localPTOTracked)
	require.True(t, h.appDataPackets.history.HasOutstandingPackets())
	return h, recorder, tokens, prior, now.Add(5 * time.Millisecond)
}

func TestLocalBBRMemberProvidesPTO(t *testing.T) {
	for _, kind := range []string{"first member", "trained and ACK drained", "pending predecessor"} {
		for _, count := range []int{2, 64} {
			for _, stale := range []bool{false, true} {
				t.Run(fmt.Sprintf("%s/%d/stale=%t", kind, count, stale), func(t *testing.T) {
					fast, fr, tokens, prior, at := newLocalBBRUnwitnessedMemberTest(t, count, kind)
					scalar, sr, reference, scalarPrior, _ := newLocalBBRUnwitnessedMemberTest(t, count, kind)
					var logs [2]*localMemberTimerLogger
					for i, h := range []*sentPacketHandler{fast, scalar} {
						h.rttStats.UpdateRTT(17*time.Millisecond, 0)
						h.ptoCount = 2
						h.appDataPackets.lossTime = at.Add(-2 * time.Millisecond)
						h.alarm = alarmTimer{}
						if stale {
							h.alarm.Time = at.Add(-time.Millisecond)
						}
						logs[i] = &localMemberTimerLogger{Logger: h.logger}
						h.logger = logs[i]
					}
					wantAlarm := at.Add(fast.getScaledPTO(true))
					cursor := fast.congestionEvents.recovery.local.qualifiedOrdinal
					require.True(t, TryCompleteLocalAcceptedPackets(fast, tokens, at))
					for _, token := range reference {
						require.NoError(t, scalar.CompleteLocalPacket(token, LocalPacketAccepted, at))
						require.Equal(t, at, scalar.appDataPackets.history.latestLocalPTO())
						require.Equal(t, wantAlarm, scalar.GetLossDetectionTimeout(), "even the first scalar completion supplies a nonzero alarm")
					}
					require.Equal(t, wantAlarm, fast.GetLossDetectionTimeout())
					requireLocalBBRMemberEquivalent(t, scalar, fast, sr, fr)
					if kind == "pending predecessor" {
						require.Equal(t, cursor, fast.congestionEvents.recovery.local.qualifiedOrdinal)
						generation := fast.congestionEvents.sampler.timingGeneration
						require.NoError(t, fast.CompleteLocalPacket(prior, LocalPacketAccepted, at.Add(time.Millisecond)))
						require.NoError(t, scalar.CompleteLocalPacket(scalarPrior, LocalPacketAccepted, at.Add(time.Millisecond)))
						require.Greater(t, fast.congestionEvents.sampler.timingGeneration, generation, "a newer predecessor still fences older member timing")
						requireLocalBBRMemberEquivalent(t, scalar, fast, sr, fr)
					}
					require.Zero(t, logs[0].canceled)
					require.Zero(t, logs[1].canceled)
					ackLocalBBRMemberTest(t, fast, at.Add(10*time.Millisecond))
					ackLocalBBRMemberTest(t, scalar, at.Add(10*time.Millisecond))
					requireLocalBBRMemberEquivalent(t, scalar, fast, sr, fr)
					require.Zero(t, fast.GetLossDetectionTimeout())
					require.Equal(t, 1, logs[0].canceled, "the actual final cancellation remains observable")
					require.Equal(t, logs[1].canceled, logs[0].canceled)
				})
			}
		}
	}
}

func TestLocalBBRUnwitnessedMemberDeclinesAtomically(t *testing.T) {
	for _, kind := range []string{"foreign suffix", "early ACK suffix", "missing rich suffix", "all ACKed", "tracking disabled"} {
		t.Run(kind, func(t *testing.T) {
			h, recorder, tokens, _, at := newLocalBBRUnwitnessedMemberTest(t, 3, "first member")
			d := h.congestionEvents
			last := tokens[len(tokens)-1].registration
			switch kind {
			case "foreign suffix":
				_, _, other, _, _ := newLocalBBRUnwitnessedMemberTest(t, 2, "first member")
				tokens[len(tokens)-1] = other[1]
			case "early ACK suffix":
				last.earlyACK = true
			case "missing rich suffix":
				d.packets.delete(congestionKey(last.level, last.pn))
			case "all ACKed":
				ackBBRECNAt(t, h, at, ackRanges(tokens[0].registration.pn, tokens[1].registration.pn, last.pn), 3, 0)
				require.False(t, h.appDataPackets.history.HasOutstandingPackets())
			case "tracking disabled":
				h.appDataPackets.history.localPTOTracked = false
			}
			require.Zero(t, h.appDataPackets.history.latestLocalPTO())
			owner, event, alarm := h.local.owner, d.event, h.GetLossDetectionTimeout()
			feedback, cursor := len(recorder.feedback), d.recovery.local.qualifiedOrdinal
			require.False(t, TryCompleteLocalAcceptedPackets(h, tokens, at))
			require.Equal(t, owner, h.local.owner)
			require.Equal(t, event, d.event)
			require.Equal(t, alarm, h.GetLossDetectionTimeout())
			require.Len(t, recorder.feedback, feedback)
			require.Equal(t, cursor, d.recovery.local.qualifiedOrdinal)
			require.Equal(t, localPacketPending, tokens[0].registration.outcome)
		})
	}
}

func TestLocalRenoMemberStillRequiresPriorPTO(t *testing.T) {
	h, tokens := newLocalPendingSpanTest(t, false)
	require.Zero(t, h.appDataPackets.history.latestLocalPTO())
	owner := h.local.owner
	at := monotime.Time(time.Second + time.Millisecond)
	require.False(t, TryCompleteLocalAcceptedPackets(h, tokens, at))
	require.Equal(t, owner, h.local.owner)
	require.NoError(t, h.CompleteLocalPacket(tokens[0], LocalPacketAccepted, at))
	require.True(t, TryCompleteLocalAcceptedPackets(h, tokens[1:], at))
}
