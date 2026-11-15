package ackhandler

import (
	"fmt"
	"testing"
	"time"

	"github.com/quic-go/quic-go/internal/congestion"
	"github.com/quic-go/quic-go/internal/monotime"
	"github.com/quic-go/quic-go/internal/protocol"
	"github.com/stretchr/testify/require"
)

func newLocalBBRMemberTest(t *testing.T, count int, phase string) (*sentPacketHandler, *congestionRecorder, []LocalCompletionToken, monotime.Time) {
	t.Helper()
	capable := phase != "unmarked"
	h, recorder := newLocalECNTestHandler(t, true, &capable)
	now := monotime.Time(time.Second)
	h.DropPackets(protocol.EncryptionInitial, now)
	h.DropPackets(protocol.EncryptionHandshake, now)
	h.appDataPackets.pns.(*skippingPacketNumberGenerator).nextToSkip = 10000
	t.Cleanup(func() { h.CloseLocal(now.Add(time.Second)) })
	pn, seed := localECNPacket(t, h, now)
	require.NoError(t, h.CompleteLocalPacket(seed, LocalPacketAccepted, now.Add(time.Millisecond)))
	if phase != "testing" {
		// Keep a second eligible packet for PTO while the first ACK leaves a
		// real valid delivery diagnostic for member completion to clear.
		_, seed = localECNPacket(t, h, now.Add(time.Millisecond))
		require.NoError(t, h.CompleteLocalPacket(seed, LocalPacketAccepted, now.Add(1500*time.Microsecond)))
		ect := uint64(1)
		if !capable {
			ect = 0
		}
		ackBBRECNAt(t, h, now.Add(2*time.Millisecond), ackRanges(pn), ect, 0)
	}
	if phase == "skipped" {
		h.appDataPackets.pns.(*skippingPacketNumberGenerator).nextToSkip = 3
	}
	tokens := make([]LocalCompletionToken, count)
	for i := range tokens {
		_, tokens[i] = localECNPacket(t, h, now.Add(5*time.Millisecond))
	}
	if phase == "draining" {
		h.bbrECN.resetPath(1)
	}
	return h, recorder, tokens, now.Add(10 * time.Millisecond)
}

func requireLocalBBRMemberEquivalent(t *testing.T, scalar, fast *sentPacketHandler, sr, fr *congestionRecorder) {
	t.Helper()
	requireLocalBBREquivalent(t, scalar, fast, sr, fr)
	s, f := scalar.congestionEvents, fast.congestionEvents
	require.Equal(t, s.event, f.event)
	require.Equal(t, s.recovery.index, f.recovery.index)
	require.Equal(t, s.recovery.unconfirmedLoss, f.recovery.unconfirmedLoss)
	require.Equal(t, s.recovery.local.qualifiedOrdinal, f.recovery.local.qualifiedOrdinal)
	require.Equal(t, s.recovery.local.lastEligible, f.recovery.local.lastEligible)
	for i, outcome := range s.recovery.local.outcomes {
		other := f.recovery.local.outcomes[i]
		require.Equal(t, outcome.qualified, other.qualified)
		require.Equal(t, outcome.eligibleAt, other.eligibleAt)
		require.Equal(t, outcome.registration == nil, other.registration == nil)
	}
	require.Equal(t, scalar.local.ecn.confirmed, fast.local.ecn.confirmed)
	require.Equal(t, scalar.local.ecn.unresolved, fast.local.ecn.unresolved)
	require.Equal(t, scalar.local.ecn.testingPending, fast.local.ecn.testingPending)
	require.Equal(t, scalar.bbrECN.sent, fast.bbrECN.sent)
	require.Equal(t, scalar.bbrECN.state, fast.bbrECN.state)
	require.Equal(t, scalar.bbrECN.fence, fast.bbrECN.fence)
	require.Equal(t, scalar.appDataPackets.history.unresolvedLocal, fast.appDataPackets.history.unresolvedLocal)
	for pn, packet := range scalar.appDataPackets.history.Packets() {
		key := congestionKey(packet.EncryptionLevel, pn)
		si, sok := s.packets.get(key)
		fi, fok := f.packets.get(key)
		require.Equal(t, sok, fok)
		require.Equal(t, si, fi)
	}
}

func ackLocalBBRMemberTest(t *testing.T, h *sentPacketHandler, at monotime.Time) {
	t.Helper()
	var pns []protocol.PacketNumber
	for pn := range h.appDataPackets.history.Packets() {
		pns = append(pns, pn)
	}
	ackBBRECNAt(t, h, at, ackRanges(pns...), h.local.ecn.confirmed.ECT0, 0)
}

func TestLocalBBRAcceptedMemberScalarEquivalence(t *testing.T) {
	for _, phase := range []string{"unmarked", "testing", "capable", "draining", "skipped"} {
		for _, count := range []int{2, 64} {
			t.Run(fmt.Sprintf("%s/%d", phase, count), func(t *testing.T) {
				fast, fr, tokens, at := newLocalBBRMemberTest(t, count, phase)
				scalar, sr, reference, _ := newLocalBBRMemberTest(t, count, phase)
				if phase != "testing" {
					require.True(t, fast.congestionEvents.event.Delivery.Valid)
				}
				for _, h := range []*sentPacketHandler{fast, scalar} {
					h.rttStats.UpdateRTT(17*time.Millisecond, 0)
					h.appDataPackets.lossTime = at.Add(-time.Millisecond)
				}
				require.True(t, TryCompleteLocalAcceptedPackets(fast, tokens, at))
				for _, token := range reference {
					require.NoError(t, scalar.CompleteLocalPacket(token, LocalPacketAccepted, at))
				}
				requireLocalBBRMemberEquivalent(t, scalar, fast, sr, fr)
				require.Zero(t, fast.appDataPackets.lossTime)
				for _, token := range tokens {
					require.ErrorIs(t, fast.CompleteLocalPacket(token, LocalPacketAccepted, at), errLocalCompletionToken)
				}
				ackLocalBBRMemberTest(t, fast, at.Add(time.Millisecond))
				ackLocalBBRMemberTest(t, scalar, at.Add(time.Millisecond))
				requireLocalBBRMemberEquivalent(t, scalar, fast, sr, fr)
			})
		}
	}
}

func TestLocalBBRAcceptedMemberQualificationOrder(t *testing.T) {
	for _, kind := range []string{"pending predecessor", "newer predecessor", "interstitial and suffix", "evicted prefix"} {
		t.Run(kind, func(t *testing.T) {
			setup := func() (*sentPacketHandler, *congestionRecorder, []LocalCompletionToken, LocalCompletionToken, monotime.Time) {
				h, recorder, _, at := newLocalBBRMemberTest(t, 0, "capable")
				if kind == "evicted prefix" {
					// Use the real ring's bounded eviction, not a fabricated cursor.
					h.congestionEvents.recovery = recoveryEvidence{capacity: 4}
				}
				register := func() LocalCompletionToken {
					_, token := localECNPacket(t, h, at.Add(-time.Millisecond))
					return token
				}
				prior := register()
				tokens := []LocalCompletionToken{register()}
				if kind == "interstitial and suffix" {
					middle := register()
					require.NoError(t, h.CompleteLocalPacket(middle, LocalPacketAccepted, at.Add(time.Millisecond)))
				}
				tokens = append(tokens, register())
				if kind == "interstitial and suffix" || kind == "evicted prefix" {
					suffix := register()
					require.NoError(t, h.CompleteLocalPacket(suffix, LocalPacketAccepted, at.Add(2*time.Millisecond)))
				}
				if kind == "evicted prefix" {
					register() // evicts the pending predecessor, retaining both members
					require.Positive(t, h.congestionEvents.recovery.evicted)
				} else if kind != "pending predecessor" {
					require.NoError(t, h.CompleteLocalPacket(prior, LocalPacketAccepted, at.Add(3*time.Millisecond)))
				}
				return h, recorder, tokens, prior, at
			}
			fast, fr, tokens, prior, at := setup()
			scalar, sr, reference, scalarPrior, _ := setup()
			before := fast.congestionEvents.recovery.local.qualifiedOrdinal
			require.True(t, TryCompleteLocalAcceptedPackets(fast, tokens, at))
			for _, token := range reference {
				require.NoError(t, scalar.CompleteLocalPacket(token, LocalPacketAccepted, at))
			}
			requireLocalBBRMemberEquivalent(t, scalar, fast, sr, fr)
			if kind == "pending predecessor" {
				require.Equal(t, before, fast.congestionEvents.recovery.local.qualifiedOrdinal)
				require.NoError(t, fast.CompleteLocalPacket(prior, LocalPacketAccepted, at.Add(time.Millisecond)))
				require.NoError(t, scalar.CompleteLocalPacket(scalarPrior, LocalPacketAccepted, at.Add(time.Millisecond)))
				requireLocalBBRMemberEquivalent(t, scalar, fast, sr, fr)
			}
			ackLocalBBRMemberTest(t, fast, at.Add(5*time.Millisecond))
			ackLocalBBRMemberTest(t, scalar, at.Add(5*time.Millisecond))
			requireLocalBBRMemberEquivalent(t, scalar, fast, sr, fr)
		})
	}
}

func TestLocalBBRAcceptedMemberRecoveryDiagnostics(t *testing.T) {
	for _, kind := range []string{"entered", "exit and undo", "pending recovery"} {
		t.Run(kind, func(t *testing.T) {
			fast, fr, tokens, at := newLocalBBRMemberTest(t, 2, "capable")
			scalar, sr, reference, _ := newLocalBBRMemberTest(t, 2, "capable")
			for _, h := range []*sentPacketHandler{fast, scalar} {
				// Seed the one-shot reducer boundary explicitly. The real scalar
				// completion remains the oracle for both its state and final event.
				r := &h.congestionEvents.recovery
				r.episode = congestion.RecoveryEpisode{ID: 1, Boundary: 1, Active: true, Entered: true, UndoPossible: true}
				if kind == "exit and undo" {
					r.ackOrdinal = 2
				} else if kind == "pending recovery" {
					r.members = map[uint64]struct{}{1: {}}
				}
			}
			require.True(t, TryCompleteLocalAcceptedPackets(fast, tokens, at))
			for _, token := range reference {
				require.NoError(t, scalar.CompleteLocalPacket(token, LocalPacketAccepted, at))
			}
			requireLocalBBRMemberEquivalent(t, scalar, fast, sr, fr)
			require.False(t, fast.congestionEvents.event.RecoveryEpisode.Entered)
			require.False(t, fast.congestionEvents.event.RecoveryEpisode.Exited)
			require.False(t, fast.congestionEvents.event.RecoveryEpisode.UndoEligible)
			ackLocalBBRMemberTest(t, fast, at.Add(time.Millisecond))
			ackLocalBBRMemberTest(t, scalar, at.Add(time.Millisecond))
			requireLocalBBRMemberEquivalent(t, scalar, fast, sr, fr)
		})
	}
}

func TestLocalBBRAcceptedMemberDeclinesAtomically(t *testing.T) {
	for _, kind := range []string{"missing delivery", "retained delivery", "wrong ordinal", "old generation", "missing local fact", "excluded outcome", "missing timing", "early ACK", "pending ECN", "ECN constraint", "foreign suffix", "duplicate suffix", "old epoch", "backward return", "oversize"} {
		t.Run(kind, func(t *testing.T) {
			count := 3
			if kind == "oversize" {
				count = 65
			}
			h, recorder, tokens, at := newLocalBBRMemberTest(t, count, "capable")
			d := h.congestionEvents
			last := tokens[len(tokens)-1].registration
			key := congestionKey(last.level, last.pn)
			switch kind {
			case "missing delivery":
				d.packets.delete(key)
			case "retained delivery":
				d.retire(key, at, h.rttStats.PTO(true), deliveryRetiredPTO)
				require.NotNil(t, d.sampler.retained[key])
			case "wrong ordinal":
				d.packets.borrow(key).Ordinal++
			case "old generation":
				d.packets.borrow(key).PathGeneration++
			case "missing local fact":
				d.recovery.local.outcomes[d.recovery.find(key)].registration = nil
			case "excluded outcome":
				d.recovery.setState(d.recovery.find(key), outcomeExcluded)
			case "missing timing":
				last.timingMissing = true
			case "early ACK":
				ackBBRECNAt(t, h, at, ackRanges(last.pn), 2, 0)
			case "pending ECN":
				h.local.ecn.pending = true
			case "ECN constraint":
				h.local.ecn.constraints = []localECNConstraint{{frontier: last.pn}}
			case "foreign suffix":
				_, _, other, _ := newLocalBBRMemberTest(t, 2, "capable")
				tokens[len(tokens)-1] = other[1]
			case "duplicate suffix":
				tokens[len(tokens)-1] = tokens[0]
			case "old epoch":
				h.appDataPackets.localEpoch = &localRegistrationEpoch{owner: &h.local.owner}
			case "backward return":
				at = tokens[0].registration.registeredAt.Add(-1)
			}
			owner, alarm, event, feedback := h.local.owner, h.GetLossDetectionTimeout(), d.event, len(recorder.feedback)
			unresolved, cursor := h.appDataPackets.history.numUnresolvedLocal, d.recovery.local.qualifiedOrdinal
			first, present := d.packets.get(congestionKey(tokens[0].registration.level, tokens[0].registration.pn))
			require.True(t, present)
			require.False(t, TryCompleteLocalAcceptedPackets(h, tokens, at))
			require.Equal(t, owner, h.local.owner)
			require.Equal(t, alarm, h.GetLossDetectionTimeout())
			require.Equal(t, event, d.event)
			require.Len(t, recorder.feedback, feedback)
			require.Equal(t, unresolved, h.appDataPackets.history.numUnresolvedLocal)
			require.Equal(t, cursor, d.recovery.local.qualifiedOrdinal)
			after, _ := d.packets.get(congestionKey(tokens[0].registration.level, tokens[0].registration.pn))
			require.Equal(t, first, after)
			require.Equal(t, localPacketPending, tokens[0].registration.outcome)
		})
	}
}

func TestLocalBBRAcceptedMemberFallsBackForEvents(t *testing.T) {
	for _, kind := range []string{"delayed CE", "lower pending loss"} {
		t.Run(kind, func(t *testing.T) {
			var handlers [2]*sentPacketHandler
			var recorders [2]*congestionRecorder
			for arm := range handlers {
				h, recorder := newLocalECNTestHandler(t, true)
				handlers[arm], recorders[arm] = h, recorder
				now := monotime.Time(time.Second)
				h.DropPackets(protocol.EncryptionInitial, now)
				h.DropPackets(protocol.EncryptionHandshake, now)
				h.appDataPackets.pns.(*skippingPacketNumberGenerator).nextToSkip = 10000
				seedPN, seed := localECNPacket(t, h, now)
				require.NoError(t, h.CompleteLocalPacket(seed, LocalPacketAccepted, now.Add(time.Millisecond)))
				low, first := localECNPacket(t, h, now.Add(time.Millisecond))
				_, second := localECNPacket(t, h, now.Add(time.Millisecond))
				if kind == "delayed CE" {
					ackBBRECNAt(t, h, now.Add(2*time.Millisecond), ackRanges(seedPN), 1, 1)
					require.True(t, h.local.ecn.pending)
				} else {
					var high protocol.PacketNumber
					for range 4 {
						pn, token := localECNPacket(t, h, now.Add(2*time.Millisecond))
						high = pn
						require.NoError(t, h.CompleteLocalPacket(token, LocalPacketAccepted, now.Add(3*time.Millisecond)))
					}
					ackBBRECNAt(t, h, now.Add(4*time.Millisecond), ackRanges(high), 1, 0)
					require.NotNil(t, first.registration.packet)
				}
				at := now.Add(5 * time.Millisecond)
				before := len(recorder.feedback)
				if arm == 0 {
					owner := h.local.owner
					require.False(t, TryCompleteLocalAcceptedPackets(h, []LocalCompletionToken{first, second}, at))
					require.Equal(t, owner, h.local.owner)
				}
				for _, token := range []LocalCompletionToken{first, second} {
					require.NoError(t, h.CompleteLocalPacket(token, LocalPacketAccepted, at))
				}
				require.Greater(t, len(recorder.feedback), before)
				if kind == "delayed CE" {
					require.True(t, recorder.feedback[before].ECNChecked)
					require.Equal(t, uint64(1), recorder.feedback[before].ECN.Delta.CE)
				} else {
					require.Equal(t, low, recorder.feedback[before].Lost[0].PacketNumber)
				}
			}
			requireLocalBBRMemberEquivalent(t, handlers[1], handlers[0], recorders[1], recorders[0])
		})
	}
}
