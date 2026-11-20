//go:build darwin || linux || freebsd

package quic

import (
	"bytes"
	"os"
	"runtime"
	"syscall"
	"testing"
	"testing/synctest"
	"time"

	"github.com/GridCastIO/quicquic-go/internal/ackhandler"
	"github.com/GridCastIO/quicquic-go/internal/congestion"
	"github.com/GridCastIO/quicquic-go/internal/handshake"
	"github.com/GridCastIO/quicquic-go/internal/monotime"
	"github.com/GridCastIO/quicquic-go/internal/protocol"
	"github.com/GridCastIO/quicquic-go/internal/wire"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"
)

func largeBBRConnection(t *testing.T, allowance protocol.ByteCount) (*Conn, *nativeOrdinarySender, *nativeProbeSocket, monotime.Time) {
	t.Helper()
	tc, sender, socket := nativeProbeRecoveryConnection(t, "bbrv3")
	c := tc.conn
	native := c.conn.(*nativeOrdinaryConn)
	native.sendConn = gsoCapableConn{native.sendConn}
	sender.nativeGSO = true
	socket.hold = nativeProbeHoldAll
	now := seedLargeBBRWindow(t, c, allowance)
	return c, sender, socket, now
}

// seedLargeBBRWindow seeds the real controller's window to allowance and installs
// a fresh pacing policy, retaining the concrete recovery owner required by
// prepared registration. These tests exercise emission geometry, not BBR's
// separately covered startup trajectory. It returns the seeding time.
func seedLargeBBRWindow(t *testing.T, c *Conn, allowance protocol.ByteCount) monotime.Time {
	t.Helper()
	now := monotime.Now()
	b := c.emission.bbr.controller
	anchor := congestion.PacketInfo{Ordinal: 1, Length: 1200, AckEliciting: true, RegistrationValid: true, SendTime: now.Add(-5 * time.Millisecond), Delivery: congestion.DeliverySnapshot{Valid: true}}
	b.Sent(congestion.SendEvent{Packet: anchor})
	b.Feedback(congestion.FeedbackEvent{Time: now, HasAck: true, RawRTT: 5 * time.Millisecond, Acked: []congestion.PacketInfo{anchor}, Delivery: congestion.DeliverySample{Delivered: uint64(allowance - b.GetCongestionWindow()), Ordinal: 1, BytesPerSecond: 100_000_000, Interval: 5 * time.Millisecond, Valid: true}})
	require.Equal(t, allowance, b.GetCongestionWindow())
	c.emission.bbr = newBBRSendPolicy(100_000_000, 1200, now)
	return now
}

func largeBBRPayloads(t *testing.T, c *Conn, payloadSize, count int) [][]byte {
	t.Helper()
	var payloads [][]byte
	for i := range count {
		payloads = append(payloads, bytes.Repeat([]byte{byte(i + 1)}, payloadSize))
	}
	queueGSOTestDatagrams(t, c, payloads)
	return payloads
}

func largeBBRRecord(t *testing.T, sender *nativeOrdinarySender) *ordinaryLocalRecord {
	t.Helper()
	for i := range sender.records {
		if sender.records[i].state == ordinaryEndpointOwned {
			return &sender.records[i]
		}
	}
	t.Fatal("no native request owns the emitted buffer")
	return nil
}

func largeBBRMember(t *testing.T, sender *nativeOrdinarySender) endpointMember {
	t.Helper()
	var member endpointMember
	sender.endpoint.do(func(state *endpointState) {
		for i := range state.records {
			r := &state.records[i]
			if r.used && !r.terminal && r.participant == sender.participant && len(r.request.members) != 0 {
				require.Len(t, r.request.members, 1, "one opportunity still makes one member")
				member = r.request.members[0]
			}
		}
	})
	require.NotNil(t, member.buffer)
	return member
}

func largeBBRPlaintext(t *testing.T, opener handshake.ShortHeaderOpener, packet []byte, cidLen int, recipe nativeProtectionRecipe) []byte {
	t.Helper()
	// Recovery may deliberately skip a PN inside a larger member.
	header := bytes.Clone(packet)
	pnOffset := int(recipe.payloadOffset) - int(recipe.pnLen)
	opener.DecryptHeader(header[pnOffset+4:pnOffset+20], &header[0], header[pnOffset:recipe.payloadOffset])
	_, pn, _, _, err := wire.ParseShortHeader(header, cidLen)
	require.NoError(t, err)
	return nativeProtectionEmissionPlaintext(t, opener, packet, int(recipe.payloadOffset), int(recipe.pnLen), pn)
}

func TestBBRNativeLargeMemberOutcomes(t *testing.T) {
	for _, outcome := range []string{"GSO", "EIO fallback", "partial", "revoked", "expired"} {
		t.Run(outcome, func(t *testing.T) {
			nativeOrdinaryTest(t, func(t *testing.T) {
				c, sender, socket, now := largeBBRConnection(t, 65536)
				sealer, opener := nativeProtectionTestCrypto(t, protocol.Version1)
				if !handshake.CanReservePacketProtection(sealer) {
					t.Skip("runtime primitives do not provide deferred protection")
				}
				sealing := NewMockSealingManager(gomock.NewController(t))
				sealing.EXPECT().Get1RTTSealer().Return(sealer, nil).AnyTimes()
				c.emission.packer.cryptoSetup = sealing
				_, pnLen := sender.recovery.PeekPacketNumber(protocol.Encryption1RTT)
				payloadSize := int(c.maxPacketSize()-wire.ShortHeaderLen(c.connIDManager.Get(), pnLen)) - 16 - 3
				payloads := largeBBRPayloads(t, c, payloadSize, 70)
				blocked := outcome == "revoked" || outcome == "expired"
				if blocked {
					participant, err := sender.endpoint.attach(nativeTestBlockerID)
					require.NoError(t, err)
					require.NoError(t, sender.endpoint.offer(participant, 0, endpointTestRequest(nativeTestBlockerID, "block writer")))
					synctest.Wait()
				}
				if outcome == "partial" {
					sender.nativeGSO = false
				}
				socket.result = func(data []byte) (int, error) {
					if outcome == "EIO fallback" && len(socket.writes) == 1 {
						return 0, &os.SyscallError{Syscall: "sendmsg", Err: syscall.EIO}
					}
					if outcome == "partial" && len(socket.writes) == 3 {
						return 0, syscall.EAGAIN
					}
					return len(data), nil
				}
				// Readiness invokes this decision outside the emission opportunity.
				plan := c.emission.planBounded(nil, c.emission.bbr, ackhandler.SendAny, 65536, 1200, nil, false, true, now)
				require.EqualValues(t, 64800, plan.request)
				result := c.emission.send(now, true)
				require.NoError(t, result.err)
				require.True(t, result.progress)
				require.Nil(t, sender.pending)
				record := largeBBRRecord(t, sender)
				require.Len(t, record.members, 1)
				require.Equal(t, 54, record.count)
				require.Equal(t, now.Add(sender.endpoint.budget), record.deadline)
				tokens := append([]ordinaryLocalPacket(nil), record.packets...)
				synctest.Wait()
				member := largeBBRMember(t, sender)
				buffer, protection := member.buffer, member.protection
				require.EqualValues(t, protocol.MaxCoalescedPacketBufferSize, buffer.Cap())
				require.Equal(t, plan.request, buffer.Len(), "the executed ordinary request matches readiness")
				require.LessOrEqual(t, buffer.Len(), protocol.ByteCount(maxGSOUDPPayload))
				require.NotNil(t, protection)
				var recipes []nativeProtectionRecipe
				// Expiry disposes an unclaimed plan on endpoint control; virtual
				// time ordering alone is not synchronization with that future write.
				sender.endpoint.do(func(*endpointState) {
					recipes = append(recipes, protection.entries...)
				})
				require.Len(t, recipes, member.datagrams())
				require.LessOrEqual(t, len(recipes), maxGSOSegments)
				pending := c.emission.bbrPendingBytes(c.emission.bbr)
				require.Equal(t, buffer.Len(), pending)
				require.LessOrEqual(t, buffer.Len(), c.emission.bbr.quantum)
				require.LessOrEqual(t, pending, c.emission.bbr.creditLimit())
				require.Equal(t, c.emission.bbr.quantum-buffer.Len(), c.emission.bbr.budget(now))
				require.Equal(t, now, c.emission.bbr.updated)
				require.NotNil(t, c.datagramQueue.Peek(), "one handoff cannot consume the next member")
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
				require.Zero(t, c.emission.bbr.credit.pending)
				require.NoError(t, sender.consume())
				for _, packet := range tokens {
					require.Error(t, sender.recovery.CompleteLocalPacket(packet.token, ackhandler.LocalPacketAccepted, monotime.Now()), "every registration has already settled")
				}
				if blocked {
					require.Len(t, socket.writes, 1, "only the unrelated blocker reaches the socket")
					return
				}
				if outcome == "partial" {
					require.Len(t, socket.writes, 3, "accepted and uncertain packets are never retried")
					return
				}
				require.Len(t, socket.writes[0].data, int(plan.request))
				if outcome == "GSO" {
					require.Len(t, socket.writes, 1)
				} else {
					require.Len(t, socket.writes, 55)
					var scalar []byte
					for _, write := range socket.writes[1:] {
						scalar = append(scalar, write.data...)
					}
					require.Equal(t, socket.writes[0].data, scalar, "EIO fallback reuses already protected ciphertext")
				}
				for i, recipe := range recipes {
					packet := socket.writes[0].data[recipe.start:recipe.end]
					plain := largeBBRPlaintext(t, opener, packet, c.connIDManager.Get().Len(), recipe)
					require.True(t, bytes.Contains(plain, payloads[i]))
				}
			})
		})
	}
}

func TestBBRNativeLargeMemberSelection(t *testing.T) {
	for _, scenario := range []string{"standard", "jumbo configured standard", "active jumbo", "UDP ceiling", "small allowance", "small pacing balance", "short datagrams", "GSO disabled"} {
		t.Run(scenario, func(t *testing.T) {
			nativeOrdinaryTest(t, func(t *testing.T) {
				allowance := protocol.ByteCount(65536)
				if scenario == "small allowance" {
					allowance = 20480
				}
				c, sender, socket, now := largeBBRConnection(t, allowance)
				if scenario == "jumbo configured standard" || scenario == "active jumbo" {
					c.packetCeiling = 8972
					c.peerParams = &wire.TransportParameters{MaxUDPPayloadSize: 8972}
					size := protocol.ByteCount(1200)
					if scenario == "active jumbo" {
						size = 8972
					}
					c.mtuDiscoverer = c.newPathMTUFinder(size, 8972)
				}
				if scenario == "GSO disabled" {
					native := c.conn.(*nativeOrdinaryConn)
					native.sendConn = &countingCapabilitiesConn{sendConn: native.sendConn}
					// Platforms without the software construction fact keep one
					// packet; TestBBRNativeSoftwareMemberSelection covers Darwin (#1590).
					require.Equal(t, runtime.GOOS == "darwin", c.emission.softwareBBRSegments, "the construction fact is Darwin's alone")
					c.emission.softwareBBRSegments = false
				}
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
					_, pnLen := sender.recovery.PeekPacketNumber(protocol.Encryption1RTT)
					payload = int(c.maxPacketSize()-wire.ShortHeaderLen(c.connIDManager.Get(), pnLen)) - 16 - 3
				}
				largeBBRPayloads(t, c, payload, 70)
				result := c.emission.send(now, true)
				require.NoError(t, result.err)
				require.True(t, result.progress)
				synctest.Wait()
				member := largeBBRMember(t, sender)
				switch scenario {
				case "standard", "jumbo configured standard", "short datagrams", "UDP ceiling":
					require.EqualValues(t, protocol.MaxCoalescedPacketBufferSize, member.buffer.Cap())
					require.NotNil(t, member.protection)
					if scenario == "short datagrams" {
						require.Equal(t, maxGSOSegments, member.datagrams())
						require.Less(t, member.buffer.Len(), protocol.ByteCount(protocol.MaxLargePacketBufferSize))
					}
					if scenario == "UDP ceiling" {
						require.EqualValues(t, 48*1337, member.buffer.Len(), "49 segments fit storage but exceed the UDP payload ceiling")
					}
				case "small allowance", "small pacing balance":
					require.EqualValues(t, protocol.MaxLargePacketBufferSize, member.buffer.Cap())
				case "GSO disabled":
					require.EqualValues(t, protocol.MaxPacketBufferSize, member.buffer.Cap())
					require.Equal(t, 1, member.datagrams())
				case "active jumbo":
					if runtime.GOOS == "linux" {
						require.EqualValues(t, protocol.MaxCoalescedPacketBufferSize, member.buffer.Cap())
						require.Nil(t, member.protection, "active jumbo's coalesced tier stays synchronous")
					} else {
						require.EqualValues(t, protocol.MaxLargePacketBufferSize, member.buffer.Cap())
					}
				}
				socket.release()
				synctest.Wait()
				require.NoError(t, sender.consume())
				require.Zero(t, c.emission.bbr.credit.pending)
			})
		})
	}
}

func TestBBRNativeLargeGenerationDebtPreservesControl(t *testing.T) {
	for _, ack := range []bool{false, true} {
		t.Run(map[bool]string{false: "no ACK", true: "due ACK"}[ack], func(t *testing.T) {
			nativeOrdinaryTest(t, func(t *testing.T) {
				c, sender, socket, now := largeBBRConnection(t, 65536)
				largeBBRPayloads(t, c, 1100, 1)
				p := c.emission.bbr
				held := p.credit.reserve(p.creditLimit()-32768, p.creditLimit(), true, false)
				require.NotNil(t, held)
				defer held.complete()
				c.emission.resetLocalPath(1, now)
				if ack {
					require.NoError(t, c.receivedPacketHandler.ReceivedPacket(4, protocol.ECNNon, protocol.Encryption1RTT, now, true))
					require.NoError(t, c.receivedPacketHandler.ReceivedPacket(5, protocol.ECNNon, protocol.Encryption1RTT, now, true))
				}
				result := c.emission.send(now, true)
				require.NoError(t, result.err)
				require.NotNil(t, c.datagramQueue.Peek(), "generation debt refuses ordinary packing despite partial room")
				require.Equal(t, ack, result.progress)
				if ack {
					require.True(t, result.retry)
					synctest.Wait()
					member := largeBBRMember(t, sender)
					require.EqualValues(t, protocol.MaxPacketBufferSize, member.buffer.Cap())
					require.Nil(t, member.protection, "ACK-only placement remains unchanged")
				} else {
					require.Equal(t, blockModeCongestionLimited, result.blocked)
					require.Equal(t, (<-chan struct{})(p.credit.available), result.available)
					select {
					case <-result.available:
						t.Fatal("unused ACK credit must not leave a retry spin")
					default:
					}
				}
				socket.release()
				synctest.Wait()
				require.NoError(t, sender.consume())
				require.Equal(t, held.bytes, p.credit.pending)
			})
		})
	}
}

func TestBBRNativeLargePlanScope(t *testing.T) {
	for _, scope := range []string{"unregistered", "Reno", "multipath", "nonzero route", "handshake", "PTO", "MTU"} {
		t.Run(scope, func(t *testing.T) {
			nativeOrdinaryTest(t, func(t *testing.T) {
				c, sender, _, now := largeBBRConnection(t, 65536)
				e, p := &c.emission, c.emission.bbr
				defer func() { e.local, e.bbr, e.pathCredit = sender, p, nil }()
				var route *pathRoute
				confirmed, mode := true, ackhandler.SendAny
				var mtu *mtuFinder
				switch scope {
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
				case "PTO":
					mode = ackhandler.SendPTOAppData
				case "MTU":
					mtu = c.newPathMTUFinder(1200, 1452)
				}
				plan := e.planBounded(route, p, mode, 65536, 1200, mtu, false, confirmed, now)
				switch scope {
				case "PTO":
					require.Equal(t, stepProbe, plan.step)
				case "MTU":
					require.Equal(t, stepMTUProbe, plan.step)
					require.LessOrEqual(t, plan.request, protocol.ByteCount(1452))
				case "handshake":
					require.EqualValues(t, 1200, plan.request)
				default:
					require.EqualValues(t, 20400, plan.request, "excluded ordinary plans retain the standard 20 KiB tier")
				}
			})
		})
	}
}

func TestNativeProtectionCoalescedScope(t *testing.T) {
	for _, scope := range []string{"ordinary", "Reno", "active jumbo", "control", "outside opportunity", "small reservation"} {
		t.Run(scope, func(t *testing.T) {
			f := newNativeProtectionEmissionFixture(t)
			e := &f.conn.emission
			e.bbr = newBBRSendPolicy(100_000_000, 1200, f.now)
			e.inOpportunity = true
			require.True(t, e.reserveLocal(64800, true, false, f.now))
			reservation := e.reservation
			defer reservation.completeLocal()
			switch scope {
			case "Reno":
				e.bbr = nil
			case "active jumbo":
				f.conn.packetCeiling = 8972
				f.conn.peerParams = &wire.TransportParameters{MaxUDPPayloadSize: 8972}
				f.conn.mtuDiscoverer = f.conn.newPathMTUFinder(8972, 8972)
			case "control":
				e.paceReservation = false
			case "outside opportunity":
				e.inOpportunity = false
			case "small reservation":
				reservation.resize(1200)
			}
			sealing := NewMockSealingManager(gomock.NewController(t))
			sealing.EXPECT().Get1RTTSealer().Return(f.sealer, nil)
			e.packer.cryptoSetup = sealing
			buffer := getCoalescedPacketBuffer()
			defer buffer.Release()
			var construction nativeProtectionConstruction
			construction.begin(e, buffer)
			defer construction.discard()
			_, err := e.appendNativePacket(buffer, 1200, false, protocol.ECNNon, f.now, &construction)
			require.NoError(t, err)
			if scope == "ordinary" {
				require.NotNil(t, construction.plan)
			} else {
				require.Nil(t, construction.plan, "excluded coalesced construction must stay synchronous")
				_, pnLen := f.sender.recovery.PeekPacketNumber(protocol.Encryption1RTT)
				plain := nativeProtectionEmissionPlaintext(t, f.opener, buffer.Data, int(wire.ShortHeaderLen(f.conn.connIDManager.Get(), pnLen)), int(pnLen), 0)
				require.NotEmpty(t, plain)
			}
			for _, packet := range f.sender.pending.packets {
				require.NoError(t, f.sender.recovery.CompleteLocalPacket(packet.token, ackhandler.LocalPacketUnsubmitted, monotime.Now()))
			}
		})
	}
}

func TestNativeProtectionCoalescedUnsupportedSealer(t *testing.T) {
	f := newNativeProtectionEmissionFixture(t)
	e := &f.conn.emission
	e.bbr = newBBRSendPolicy(100_000_000, 1200, f.now)
	e.inOpportunity = true
	require.True(t, e.reserveLocal(64800, true, false, f.now))
	defer e.reservation.completeLocal()
	largeBBRPayloads(t, f.conn, 1100, 21)
	e.packer.framer = f.conn.framer
	wrapper := &nativeProtectionEmissionObservedSealer{ShortHeaderSealer: f.sealer}
	sealing := NewMockSealingManager(gomock.NewController(t))
	gomock.InOrder(sealing.EXPECT().Get1RTTSealer().Return(f.sealer, nil).Times(20), sealing.EXPECT().Get1RTTSealer().Return(wrapper, nil))
	e.packer.cryptoSetup = sealing
	buffer := getCoalescedPacketBuffer()
	defer buffer.Release()
	var construction nativeProtectionConstruction
	construction.begin(e, buffer)
	defer construction.discard()
	for range 20 {
		_, err := e.appendNativePacket(buffer, 1200, false, protocol.ECNNon, f.now, &construction)
		require.NoError(t, err)
	}
	require.Greater(t, buffer.Len(), protocol.ByteCount(protocol.MaxLargePacketBufferSize))
	plan := construction.plan
	require.NotNil(t, plan)
	recipes := append([]nativeProtectionRecipe(nil), plan.entries...)
	observed := false
	wrapper.onOverhead = func() {
		observed = true
		require.Nil(t, construction.plan)
		require.Nil(t, plan.buffer, "the unsupported observer sees a fully materialized prefix and released plan")
		for i, r := range recipes {
			plain := largeBBRPlaintext(t, f.opener, buffer.Data[r.start:r.end], f.conn.connIDManager.Get().Len(), r)
			require.True(t, bytes.Contains(plain, bytes.Repeat([]byte{byte(i + 1)}, 1100)))
		}
	}
	_, err := e.appendNativePacket(buffer, 1200, false, protocol.ECNNon, f.now, &construction)
	require.NoError(t, err)
	require.True(t, observed)
	require.Equal(t, 1, wrapper.seals)
	require.Nil(t, construction.plan)
	for _, packet := range f.sender.pending.packets {
		require.NoError(t, f.sender.recovery.CompleteLocalPacket(packet.token, ackhandler.LocalPacketUnsubmitted, monotime.Now()))
	}
}
