//go:build darwin || linux || freebsd

package quic

import (
	"bytes"
	"syscall"
	"testing"
	"testing/synctest"
	"time"

	"github.com/GridCastIO/quicquic-go/internal/ackhandler"
	"github.com/GridCastIO/quicquic-go/internal/handshake"
	"github.com/GridCastIO/quicquic-go/internal/monotime"
	"github.com/GridCastIO/quicquic-go/internal/protocol"
	"github.com/GridCastIO/quicquic-go/internal/wire"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"
)

// softwareBBRConnection is largeBBRConnection on a native connection without
// wire GSO, as on Darwin, with the construction fact pinned on so every host
// exercises the Darwin geometry (#1590).
func softwareBBRConnection(t *testing.T, allowance protocol.ByteCount) (*Conn, *nativeOrdinarySender, *nativeProbeSocket, monotime.Time) {
	t.Helper()
	c, sender, socket, now := largeBBRConnection(t, allowance)
	native := c.conn.(*nativeOrdinaryConn)
	native.sendConn = &countingCapabilitiesConn{sendConn: native.sendConn}
	c.emission.softwareBBRSegments = true
	return c, sender, socket, now
}

// softwareBBRProtection installs deferred-protection crypto, so the writer
// protects the member's packets before its first native call.
func softwareBBRProtection(t *testing.T, c *Conn) handshake.ShortHeaderOpener {
	t.Helper()
	sealer, opener := nativeProtectionTestCrypto(t, protocol.Version1)
	if !handshake.CanReservePacketProtection(sealer) {
		t.Skip("runtime primitives do not provide deferred protection")
	}
	sealing := NewMockSealingManager(gomock.NewController(t))
	sealing.EXPECT().Get1RTTSealer().Return(sealer, nil).AnyTimes()
	c.emission.packer.cryptoSetup = sealing
	return opener
}

// softwareBBRFullPayload is the DATAGRAM payload that fills one packet: the
// packet less its short header, the 16-byte AEAD tag and the 3-byte DATAGRAM
// frame header (type and two-byte length).
func softwareBBRFullPayload(c *Conn, sender *nativeOrdinarySender) int {
	_, pnLen := sender.recovery.PeekPacketNumber(protocol.Encryption1RTT)
	return int(c.maxPacketSize()-wire.ShortHeaderLen(c.connIDManager.Get(), pnLen)) - 16 - 3
}

// Without wire GSO, one ordinary BBR opportunity in largeNativeBBRGSO's domain
// builds the member wire GSO builds on Linux, as software segments: the same
// tier, ceiling, pacing charge and plan, with one native write per datagram.
func TestBBRNativeSoftwareMemberSelection(t *testing.T) {
	for _, scenario := range []string{"standard", "UDP ceiling", "small allowance", "small pacing balance", "short datagrams"} {
		t.Run(scenario, func(t *testing.T) {
			nativeOrdinaryTest(t, func(t *testing.T) {
				allowance := protocol.ByteCount(65536)
				if scenario == "small allowance" {
					allowance = 20480
				}
				c, sender, socket, now := softwareBBRConnection(t, allowance)
				if scenario == "UDP ceiling" {
					c.mtuDiscoverer = c.newPathMTUFinder(1337, 1452)
				}
				if scenario == "small pacing balance" {
					c.emission.bbr.sent(c.emission.bbr.budget(now)-20480, now)
				}
				sealer := nativeProtectionTestSealer(t)
				sealing := NewMockSealingManager(gomock.NewController(t))
				sealing.EXPECT().Get1RTTSealer().Return(sealer, nil).AnyTimes()
				c.emission.packer.cryptoSetup = sealing
				payload := 1100
				switch scenario {
				case "short datagrams":
					payload = 100
				case "UDP ceiling":
					payload = softwareBBRFullPayload(c, sender)
				}
				largeBBRPayloads(t, c, payload, 70)
				size := c.emission.packetSize()
				plan := c.emission.planBounded(nil, c.emission.bbr, ackhandler.SendAny, allowance, size, nil, false, true, now)
				budget := c.emission.bbr.budget(now)
				result := c.emission.send(now, true)
				require.NoError(t, result.err)
				require.True(t, result.progress)
				synctest.Wait()
				member := largeBBRMember(t, sender)
				require.False(t, member.nativeGSO, "the connection has no wire GSO")
				require.NotNil(t, member.protection, "BBR keeps deferred writer protection")
				require.Greater(t, member.datagrams(), 1, "one opportunity carries more than one packet")
				require.NotZero(t, member.gsoSize)
				require.LessOrEqual(t, member.buffer.Len(), plan.request)
				require.Equal(t, member.buffer.Len(), c.emission.bbrPendingBytes(c.emission.bbr), "the credit holds the member's bytes")
				require.Equal(t, budget-member.buffer.Len(), c.emission.bbr.budget(now), "pacing is charged once for the member's bytes")
				switch scenario {
				case "standard", "short datagrams", "UDP ceiling":
					require.EqualValues(t, protocol.MaxCoalescedPacketBufferSize, member.buffer.Cap())
					if scenario == "short datagrams" {
						require.Equal(t, maxGSOSegments, member.datagrams())
					}
					if scenario == "UDP ceiling" {
						require.EqualValues(t, 48*1337, member.buffer.Len(), "49 segments fit storage but exceed the UDP payload ceiling")
					}
				case "small allowance", "small pacing balance":
					require.EqualValues(t, protocol.MaxLargePacketBufferSize, member.buffer.Cap())
				}
				data, segment, datagrams := bytes.Clone(member.buffer.Data), int(member.gsoSize), member.datagrams()
				socket.release()
				synctest.Wait()
				require.NoError(t, sender.consume())
				require.Len(t, socket.writes, datagrams, "the writer submits each segment as its own datagram")
				var written []byte
				for i, write := range socket.writes {
					if i < datagrams-1 {
						require.Len(t, write.data, segment)
					}
					written = append(written, write.data...)
				}
				require.Equal(t, data, written)
				require.Zero(t, c.emission.bbr.credit.pending)
			})
		})
	}
}

// The software geometry applies only where largeNativeBBRGSO does, on a
// platform with the construction fact and without wire GSO. Every other plan
// keeps its existing request.
func TestBBRNativeSoftwarePlanScope(t *testing.T) {
	for _, scope := range []string{"selected", "fact off", "wire GSO", "unregistered", "Reno", "multipath", "nonzero route", "handshake", "active jumbo", "steered", "PTO", "MTU"} {
		t.Run(scope, func(t *testing.T) {
			nativeOrdinaryTest(t, func(t *testing.T) {
				c, sender, _, now := softwareBBRConnection(t, 65536)
				e, p := &c.emission, c.emission.bbr
				defer func() { e.local, e.bbr, e.pathCredit = sender, p, nil }()
				var route *pathRoute
				confirmed, mode, size := true, ackhandler.SendAny, protocol.ByteCount(1200)
				var mtu *mtuFinder
				steered := scope == "steered"
				switch scope {
				case "fact off":
					e.softwareBBRSegments = false
				case "wire GSO":
					native := c.conn.(*nativeOrdinaryConn)
					native.sendConn = native.sendConn.(*countingCapabilitiesConn).sendConn // largeBBRConnection's GSO-capable conn
				case "unregistered":
					e.local = nil
				case "Reno":
					e.bbr = nil
				case "multipath":
					e.pathCredit = &pathCreditRegistry{conn: c}
				case "nonzero route":
					route = &pathRoute{}
				case "handshake":
					confirmed = false
				case "active jumbo":
					size = 8972
				case "PTO":
					mode = ackhandler.SendPTOAppData
				case "MTU":
					mtu = c.newPathMTUFinder(1200, 1452)
				}
				plan := e.planBounded(route, p, mode, 65536, size, mtu, steered, confirmed, now)
				switch scope {
				case "selected", "wire GSO":
					require.EqualValues(t, 64800, plan.request, "the large native member, from software or wire segments")
				case "steered":
					require.Equal(t, stepSteered, plan.step)
					require.Equal(t, size, plan.request, "steered work keeps one packet")
				case "PTO":
					require.Equal(t, stepProbe, plan.step)
				case "MTU":
					require.Equal(t, stepMTUProbe, plan.step)
					require.LessOrEqual(t, plan.request, protocol.ByteCount(1452))
				default:
					require.Equal(t, size, plan.request, "excluded plans keep one packet without wire GSO")
				}
			})
		})
	}
}

// A software BBR member keeps exact per-datagram facts and returns its credit
// once: accepted, a mid-member error, and revocation or expiry before the
// writer claims it.
func TestBBRNativeSoftwareMemberOutcomes(t *testing.T) {
	for _, outcome := range []string{"accepted", "partial", "revoked", "expired"} {
		t.Run(outcome, func(t *testing.T) {
			nativeOrdinaryTest(t, func(t *testing.T) {
				c, sender, socket, now := softwareBBRConnection(t, 65536)
				opener := softwareBBRProtection(t, c)
				payloads := largeBBRPayloads(t, c, softwareBBRFullPayload(c, sender), 70)
				blocked := outcome == "revoked" || outcome == "expired"
				if blocked {
					participant, err := sender.endpoint.attach(nativeTestBlockerID)
					require.NoError(t, err)
					require.NoError(t, sender.endpoint.offer(participant, 0, endpointTestRequest(nativeTestBlockerID, "block writer")))
					synctest.Wait()
				}
				socket.result = func(data []byte) (int, error) {
					if outcome == "partial" && len(socket.writes) == 3 {
						return 0, syscall.EAGAIN
					}
					return len(data), nil
				}
				result := c.emission.send(now, true)
				require.NoError(t, result.err)
				require.True(t, result.progress)
				record := largeBBRRecord(t, sender)
				require.Len(t, record.members, 1)
				require.Equal(t, 54, record.count)
				tokens := append([]ordinaryLocalPacket(nil), record.packets...)
				synctest.Wait()
				member := largeBBRMember(t, sender)
				buffer, protection := member.buffer, member.protection
				require.False(t, member.nativeGSO)
				require.Equal(t, 54, member.datagrams())
				require.NotNil(t, protection)
				var recipes []nativeProtectionRecipe
				sender.endpoint.do(func(*endpointState) {
					recipes = append(recipes, protection.entries...)
				})
				require.Len(t, recipes, 54)
				require.Equal(t, buffer.Len(), c.emission.bbrPendingBytes(c.emission.bbr))
				switch outcome {
				case "revoked":
					sender.endpoint.cancelGeneration(sender.participant, sender.generation)
				case "expired":
					time.Sleep(sender.endpoint.budget + time.Millisecond)
				}
				socket.release()
				synctest.Wait()
				require.Zero(t, buffer.refCount)
				require.Nil(t, protection.buffer)
				require.Zero(t, c.emission.bbr.credit.pending, "the credit returns exactly once")
				require.NoError(t, sender.consume())
				for _, packet := range tokens {
					require.Error(t, sender.recovery.CompleteLocalPacket(packet.token, ackhandler.LocalPacketAccepted, monotime.Now()), "every registration has already settled")
				}
				switch outcome {
				case "revoked", "expired":
					require.Len(t, socket.writes, 1, "only the unrelated blocker reaches the socket")
				case "partial":
					require.Len(t, socket.writes, 3, "accepted and uncertain packets are never retried")
				case "accepted":
					require.Len(t, socket.writes, 54)
					for i, recipe := range recipes {
						packet := socket.writes[i].data
						require.Len(t, packet, int(recipe.end-recipe.start))
						plain := largeBBRPlaintext(t, opener, packet, c.connIDManager.Get().Len(), recipe)
						require.True(t, bytes.Contains(plain, payloads[i]), "each datagram is ciphertext of its own packet")
					}
				}
			})
		})
	}
}

// A software BBR member's storage, plan and credit stay borrowed through every
// native call and the final fence, even when the sender closes while the
// writer is inside the member; no datagram is submitted after the close.
func TestBBRNativeSoftwareMemberBorrowThroughFence(t *testing.T) {
	nativeOrdinaryTest(t, func(t *testing.T) {
		c, sender, socket, now := softwareBBRConnection(t, 65536)
		softwareBBRProtection(t, c)
		largeBBRPayloads(t, c, softwareBBRFullPayload(c, sender), 70)
		socket.hold = func([]byte) bool { return len(socket.writes) == 2 }
		result := c.emission.send(now, true)
		require.NoError(t, result.err)
		require.True(t, result.progress)
		synctest.Wait() // the writer is parked inside its second native call
		member := largeBBRMember(t, sender)
		buffer, plan := member.buffer, member.protection
		require.Greater(t, member.datagrams(), 2)
		participant, endpoint := sender.participant, sender.endpoint
		pending := c.emission.bbr.credit.pending
		require.Equal(t, buffer.Len(), pending)
		sender.Close()
		synctest.Wait()
		borrowed := func() (held bool) {
			endpoint.do(func(s *endpointState) {
				token := s.current
				held = token != nil && len(token.request.members) == 1 && token.request.members[0].buffer == buffer && token.completion.Load() == nil
			})
			return held
		}
		require.True(t, borrowed(), "the closed participant's member is still the writer's current borrow")
		require.EqualValues(t, 1, buffer.refCount)
		require.Same(t, buffer, plan.buffer, "the plan stays bound to its storage")
		require.Equal(t, pending, c.emission.bbr.credit.pending, "no credit returns while the member is borrowed")
		select {
		case <-participant.retired:
			t.Fatal("the participant retired during its native borrow")
		default:
		}
		socket.release()
		synctest.Wait()
		<-participant.retired
		require.Len(t, socket.writes, 2, "no datagram is submitted after the close")
		require.Zero(t, buffer.refCount)
		require.Nil(t, plan.buffer)
		require.Zero(t, c.emission.bbr.credit.pending)
	})
}
