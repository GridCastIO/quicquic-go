//go:build darwin || linux || freebsd

package quic

import (
	"bytes"
	"errors"
	"syscall"
	"testing"
	"testing/synctest"
	"time"

	"github.com/quic-go/quic-go/internal/ackhandler"
	"github.com/quic-go/quic-go/internal/handshake"
	"github.com/quic-go/quic-go/internal/monotime"
	"github.com/quic-go/quic-go/internal/protocol"
	"github.com/quic-go/quic-go/internal/wire"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"
)

// Hooks observe real registration and the boundary after the first handoff,
// without replacing construction, credit or terminal-result processing.
type bbrGroupPolicy struct {
	emissionPolicy
	between    func()
	registered func()
}

func (p *bbrGroupPolicy) noteEmissionRegistration() {
	p.emissionPolicy.noteEmissionRegistration()
	if p.registered != nil {
		f := p.registered
		p.registered = nil
		f()
	}
}

func (p *bbrGroupPolicy) emissionClosePending() bool {
	if p.between != nil {
		f := p.between
		p.between = nil
		f()
	}
	return p.emissionPolicy.emissionClosePending()
}

func bbrGroupConnection(t *testing.T, gso bool, payloads ...int) (*Conn, *nativeOrdinarySender, *nativeProbeSocket) {
	t.Helper()
	tc, sender, socket := nativeProbeRecoveryConnection(t, "bbrv3")
	c := tc.conn
	if gso {
		native := c.conn.(*nativeOrdinaryConn)
		native.sendConn = gsoCapableConn{native.sendConn}
	}
	sender.nativeGSO = false // observe every packet, including a software GSO member
	socket.hold = nativeProbeHoldAll
	for i, n := range payloads {
		require.NoError(t, c.datagramQueue.Add(&wire.DatagramFrame{DataLenPresent: true, Data: bytes.Repeat([]byte{byte('a' + i)}, n)}))
	}
	return c, sender, socket
}

func bbrGroupRecord(t *testing.T, s *nativeOrdinarySender) *ordinaryLocalRecord {
	t.Helper()
	for i := range s.records {
		if s.records[i].state == ordinaryEndpointOwned {
			return &s.records[i]
		}
	}
	t.Fatal("no owned native record")
	return nil
}

func TestBBRNativeGroupProtectionAndResults(t *testing.T) {
	for _, outcome := range []string{"accepted", "partial", "revoked"} {
		t.Run(outcome, func(t *testing.T) {
			nativeOrdinaryTest(t, func(t *testing.T) {
				c, sender, socket := bbrGroupConnection(t, true, 400, 400, 500, 500, 600, 600)
				sealer, opener := nativeProtectionTestCrypto(t, protocol.Version1)
				if !handshake.CanReservePacketProtection(sealer) {
					t.Skip("runtime primitives do not provide deferred protection")
				}
				sealing := NewMockSealingManager(gomock.NewController(t))
				sealing.EXPECT().Get1RTTSealer().Return(sealer, nil).AnyTimes()
				c.emission.packer.cryptoSetup = sealing
				now := monotime.Now()
				var deadline monotime.Time
				c.emission.policy = &bbrGroupPolicy{emissionPolicy: c, between: func() {
					require.Len(t, sender.pending.members, 1)
					deadline = sender.pending.deadline
					time.Sleep(10 * time.Microsecond) // must not refill this group's pacing or deadline
				}}
				if outcome == "partial" {
					socket.result = func(data []byte) (int, error) {
						if len(socket.writes) == 3 {
							return 0, syscall.EAGAIN
						}
						return len(data), nil
					}
				}
				budget := c.emission.bbr.budget(now)
				result := c.emission.send(now, true)
				require.NoError(t, result.err)
				require.True(t, result.progress)
				require.Nil(t, sender.pending, "the call seals every builder")
				record := bbrGroupRecord(t, sender)
				require.Len(t, record.members, 2)
				require.Equal(t, 4, record.count)
				require.Equal(t, deadline, record.deadline)
				require.NotNil(t, c.datagramQueue.Peek(), "a third ordinary buffer waits for the next call")
				tokens := append([]ordinaryLocalPacket(nil), record.packets...)
				var total protocol.ByteCount
				for _, member := range record.members {
					require.Equal(t, 2, member.datagrams)
					total += member.bytes
				}
				require.Equal(t, total, c.emission.bbr.credit.pending)
				require.LessOrEqual(t, total, budget)
				require.LessOrEqual(t, total, c.emission.bbr.creditLimit())
				require.Equal(t, budget-total, c.emission.bbr.budget(now))
				require.Equal(t, now, c.emission.bbr.updated)
				synctest.Wait()
				var buffers []*packetBuffer
				var plans []*nativeProtectionPlan
				var recipes []nativeProtectionRecipe
				sender.endpoint.do(func(state *endpointState) {
					request := state.current.request
					require.Len(t, request.members, 2, "both members share one actual native request")
					require.Equal(t, deadline.ToTime(), request.deadline)
					for _, member := range request.members {
						require.NotNil(t, member.protection)
						buffers = append(buffers, member.buffer)
						plans = append(plans, member.protection)
						recipes = append(recipes, member.protection.entries...)
					}
				})
				require.NotSame(t, plans[0], plans[1])
				if outcome == "revoked" {
					sender.endpoint.cancelGeneration(sender.participant, sender.generation)
				}
				socket.release()
				synctest.Wait()
				for _, buffer := range buffers {
					require.Zero(t, buffer.refCount)
				}
				for _, plan := range plans {
					require.Nil(t, plan.buffer)
				}
				require.Zero(t, c.emission.bbr.credit.pending, "the native owner returns each member's credit")
				require.NoError(t, sender.consume())
				for _, packet := range tokens {
					require.Error(t, sender.recovery.CompleteLocalPacket(packet.token, ackhandler.LocalPacketAccepted, monotime.Now()), "each registration is already settled")
				}
				if outcome == "accepted" {
					require.Len(t, socket.writes, 4)
					for i, write := range socket.writes {
						r := recipes[i]
						plain := nativeProtectionEmissionPlaintext(t, opener, write.data, int(r.payloadOffset), int(r.pnLen), protocol.PacketNumber(i))
						require.True(t, bytes.Contains(plain, bytes.Repeat([]byte{byte('a' + i)}, []int{400, 400, 500, 500}[i])))
					}
				} else if outcome == "partial" {
					require.Len(t, socket.writes, 3, "uncertain and unsubmitted suffixes are never retried")
				} else {
					require.Len(t, socket.writes, 1, "revocation stops every later native submission")
				}
			})
		})
	}
}

type bbrGroupRecoveryStop struct {
	ackhandler.LocalSentPacketHandler
	boundedRecovery
}

func (h bbrGroupRecoveryStop) SendAllowance(monotime.Time) (ackhandler.SendMode, protocol.ByteCount) {
	return ackhandler.SendAck, 0
}

type bbrGroupFullQueue struct{ sender }

func (bbrGroupFullQueue) WouldBlock() bool { return true }

func TestBBRNativeGroupStopsAfterProgress(t *testing.T) {
	for _, stop := range []string{"receive", "close", "pacing", "congestion", "capacity", "empty", "error"} {
		t.Run(stop, func(t *testing.T) {
			nativeOrdinaryTest(t, func(t *testing.T) {
				payloads := []int{200, 200, 200}
				if stop == "empty" {
					payloads = payloads[:1]
				}
				c, sender, socket := bbrGroupConnection(t, false, payloads...)
				now := monotime.Now()
				policy := &bbrGroupPolicy{emissionPolicy: c, between: func() {
					switch stop {
					case "receive":
						buf := getPacketWithContents(append([]byte{0xc0, 0xde, 0xad, 0xbe, 0xef, 0, 0}, make([]byte, 40)...))
						c.handlePacket(receivedPacket{data: buf.Data, buffer: buf, rcvTime: now})
					case "close":
						c.destroyImpl(errors.New("close after first member"))
					case "pacing":
						c.emission.bbr.sent(c.emission.bbr.budget(now), now)
					case "congestion":
						c.sentPacketHandler = bbrGroupRecoveryStop{sender.recovery, c.sentPacketHandler.(boundedRecovery)}
					case "capacity":
						c.emission.queue = bbrGroupFullQueue{sender}
					case "error":
						sealing := NewMockSealingManager(gomock.NewController(t))
						sealing.EXPECT().Get1RTTSealer().Return(nil, errors.New("second pack failed"))
						c.emission.packer.cryptoSetup = sealing
					}
				}}
				if stop == "receive" || stop == "close" {
					policy.registered, policy.between = policy.between, nil
				}
				c.emission.policy = policy
				result := c.emission.send(now, true)
				require.True(t, result.progress, "first handoff survives the second decision")
				if stop == "error" {
					require.ErrorContains(t, result.err, "second pack failed")
				} else {
					require.NoError(t, result.err)
				}
				if stop == "capacity" {
					require.Equal(t, emissionQueueFull, result.stop)
					require.Equal(t, sender.Available(), result.available)
					require.Equal(t, blockModeHardBlocked, result.blocked)
				} else if stop == "receive" {
					require.Equal(t, emissionReceivePending, result.stop)
					_, err := c.handlePackets()
					require.NoError(t, err)
				} else if stop != "empty" && stop != "error" {
					require.Equal(t, deadlineSendImmediately, result.deadline, "the full loop handles the next nonordinary turn")
				}
				require.Nil(t, sender.pending)
				require.Len(t, bbrGroupRecord(t, sender).members, 1)
				socket.release()
				synctest.Wait()
				require.NoError(t, sender.consume())
				require.Len(t, socket.writes, 1)
				require.Zero(t, c.emission.bbr.credit.pending)
			})
		})
	}
}

func TestBBRNativeGroupSecondReservationPreservesControl(t *testing.T) {
	for _, ack := range []bool{false, true} {
		t.Run(map[bool]string{false: "no ACK", true: "due ACK"}[ack], func(t *testing.T) {
			nativeOrdinaryTest(t, func(t *testing.T) {
				c, sender, socket := bbrGroupConnection(t, true, 400, 400, 300, 300)
				now := monotime.Now()
				// Fix pacing inputs while real BBR recovery still owns registration.
				c.emission.bbr = newBBRSendPolicy(100_000_000, 1200, now)
				var held *sendReservation
				c.emission.policy = &bbrGroupPolicy{emissionPolicy: c, between: func() {
					p := c.emission.bbr
					held = p.credit.reserve(p.creditLimit()-p.credit.pending-1200, p.creditLimit(), false, false)
					require.NotNil(t, held)
					if ack {
						require.NoError(t, c.receivedPacketHandler.ReceivedPacket(4, protocol.ECNNon, protocol.Encryption1RTT, now, true))
						require.NoError(t, c.receivedPacketHandler.ReceivedPacket(5, protocol.ECNNon, protocol.Encryption1RTT, now, true))
					}
				}}
				result := c.emission.send(now, true)
				require.NoError(t, result.err)
				require.True(t, result.progress)
				require.NotNil(t, held)
				defer held.complete()
				require.NotNil(t, c.datagramQueue.Peek(), "the refused ordinary suffix stays queued")
				owned := 0
				for i := range sender.records {
					if r := &sender.records[i]; r.state == ordinaryEndpointOwned {
						owned++
						require.Len(t, r.members, 1, "an exempt ACK must not join the ordinary request")
					}
				}
				if ack {
					require.Equal(t, 2, owned)
					require.True(t, result.retry)
				} else {
					require.Equal(t, 1, owned)
					require.Equal(t, blockModeCongestionLimited, result.blocked)
					require.Equal(t, (<-chan struct{})(c.emission.bbr.credit.available), result.available)
					select {
					case <-result.available:
						t.Fatal("unused ACK credit must not create a retry spin")
					default:
					}
				}
				socket.release()
				synctest.Wait()
				require.NoError(t, sender.consume())
				require.Equal(t, held.bytes, c.emission.bbr.credit.pending)
			})
		})
	}
}

func TestBBRNativeGroupRefusalWithoutACKConstructionCapacity(t *testing.T) {
	nativeOrdinaryTest(t, func(t *testing.T) {
		c, sender, socket := bbrGroupConnection(t, false, 200, 200, 200, 200, 200)
		now := monotime.Now()
		c.emission.bbr = newBBRSendPolicy(100_000_000, 1200, now)
		// Three requests retain their real records while the socket is blocked.
		for range 3 {
			require.False(t, sender.WouldBlock())
			require.True(t, c.emission.reserveLocal(1200, true, false, now))
			result := c.emission.boundedDatagrams(now, 1200, 1200)
			require.NoError(t, result.err)
			require.True(t, result.progress)
			sender.finish()
		}
		var held *sendReservation
		c.emission.policy = &bbrGroupPolicy{emissionPolicy: c, between: func() {
			p := c.emission.bbr
			held = p.credit.reserve(p.creditLimit()-p.credit.pending-600, p.creditLimit(), false, false)
			require.NotNil(t, held)
			require.NoError(t, c.receivedPacketHandler.ReceivedPacket(4, protocol.ECNNon, protocol.Encryption1RTT, now, true))
			require.NoError(t, c.receivedPacketHandler.ReceivedPacket(5, protocol.ECNNon, protocol.Encryption1RTT, now, true))
		}}
		result := c.emission.send(now, true)
		require.NoError(t, result.err)
		require.True(t, result.progress)
		require.NotNil(t, held)
		defer held.complete()
		require.Equal(t, emissionQueueFull, result.stop)
		require.Equal(t, blockModeHardBlocked, result.blocked)
		require.Equal(t, sender.Available(), result.available)
		require.Nil(t, sender.pending)
		for i := range sender.records {
			require.Equal(t, ordinaryEndpointOwned, sender.records[i].state)
			require.Len(t, sender.records[i].members, 1)
		}
		require.NotNil(t, c.receivedPacketHandler.GetAckFrame(protocol.Encryption1RTT, now, false), "the failed ACK construction reservation must not consume the due ACK")
		socket.release()
		synctest.Wait()
		require.NoError(t, sender.consume())
		require.Len(t, socket.writes, 4)
		require.Equal(t, held.bytes, c.emission.bbr.credit.pending)
	})
}
