//go:build darwin || linux || freebsd

package quic

import (
	"bytes"
	"testing"
	"testing/synctest"

	"github.com/quic-go/quic-go/internal/ackhandler"
	"github.com/quic-go/quic-go/internal/handshake"
	"github.com/quic-go/quic-go/internal/monotime"
	"github.com/quic-go/quic-go/internal/protocol"
	"github.com/quic-go/quic-go/internal/wire"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"
)

func TestBBRNativeCreditPartialMember(t *testing.T) {
	for _, tc := range []struct {
		name              string
		free, grant, tier protocol.ByteCount
		short             bool
	}{
		{"partial large", 32768, 32400, protocol.MaxCoalescedPacketBufferSize, false},
		{"jumbo configured standard", 32768, 32400, protocol.MaxCoalescedPacketBufferSize, false},
		{"below large tier", 20480, 20400, protocol.MaxLargePacketBufferSize, false},
		{"above large tier", 21600, 21600, protocol.MaxCoalescedPacketBufferSize, false},
		{"one packet", 1200, 1200, protocol.MaxLargePacketBufferSize, false},
		{"short segments", 32768, 32400, protocol.MaxCoalescedPacketBufferSize, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			nativeOrdinaryTest(t, func(t *testing.T) {
				c, sender, socket, now := largeBBRConnection(t, 65536)
				if tc.name == "jumbo configured standard" {
					c.packetCeiling = 8972
					c.peerParams = &wire.TransportParameters{MaxUDPPayloadSize: 8972}
					c.mtuDiscoverer = c.newPathMTUFinder(1200, 8972)
				}
				sealer, opener := nativeProtectionTestCrypto(t, protocol.Version1)
				if !handshake.CanReservePacketProtection(sealer) {
					t.Skip("runtime primitives do not provide deferred protection")
				}
				sealing := NewMockSealingManager(gomock.NewController(t))
				sealing.EXPECT().Get1RTTSealer().Return(sealer, nil).AnyTimes()
				c.emission.packer.cryptoSetup = sealing
				_, pnLen := sender.recovery.PeekPacketNumber(protocol.Encryption1RTT)
				payloadSize := int(c.maxPacketSize()-wire.ShortHeaderLen(c.connIDManager.Get(), pnLen)) - 16 - 3
				if tc.short {
					payloadSize = 100
				}
				payloads := largeBBRPayloads(t, c, payloadSize, 70)
				p := c.emission.bbr
				held := p.credit.reserve(p.creditLimit()-tc.free, p.creditLimit(), true, false)
				require.NotNil(t, held)
				defer held.complete()
				plan := c.emission.planBounded(nil, p, ackhandler.SendAny, 65536, 1200, nil, false, true, now)
				require.EqualValues(t, 64800, plan.request)
				result := c.emission.send(now, true)
				require.NoError(t, result.err)
				require.True(t, result.progress)
				require.Nil(t, sender.pending, "outer finish seals this one member")
				record := largeBBRRecord(t, sender)
				require.Len(t, record.members, 1)
				require.Equal(t, now.Add(sender.endpoint.budget), record.deadline)
				synctest.Wait()
				member := largeBBRMember(t, sender)
				require.Equal(t, tc.tier, member.buffer.Cap(), "allocation follows the grant, not the maximum plan")
				require.NotNil(t, member.protection)
				if tc.short {
					require.Equal(t, maxGSOSegments, member.datagrams())
					require.Less(t, member.buffer.Len(), tc.grant, "short physical bytes release unused admission")
				} else {
					require.Equal(t, tc.grant, member.buffer.Len())
					require.EqualValues(t, tc.grant/1200, member.datagrams())
				}
				physical := member.buffer.Len()
				require.Equal(t, held.bytes+physical, c.emission.bbrPendingBytes(p))
				require.LessOrEqual(t, c.emission.bbrPendingBytes(p), p.creditLimit())
				require.Equal(t, p.quantum-physical, p.budget(now))
				require.Equal(t, now, p.updated, "packing does not refresh pacing time")
				require.NotNil(t, c.datagramQueue.Peek(), "the remaining payload belongs to a later opportunity")
				// HoldAll and synctest.Wait leave the writer blocked in its first
				// socket call after protectAll; it cannot mutate recipes until released.
				recipes := append([]nativeProtectionRecipe(nil), member.protection.entries...)
				tokens := append([]ordinaryLocalPacket(nil), record.packets...)
				socket.release()
				synctest.Wait()
				require.Zero(t, member.buffer.refCount)
				require.Nil(t, member.protection.buffer)
				require.NoError(t, sender.consume())
				require.Equal(t, held.bytes, c.emission.bbrPendingBytes(p))
				require.Len(t, socket.writes, 1)
				for i, recipe := range recipes {
					packet := socket.writes[0].data[recipe.start:recipe.end]
					plain := largeBBRPlaintext(t, opener, packet, c.connIDManager.Get().Len(), recipe)
					require.True(t, bytes.Contains(plain, payloads[i]))
				}
				for _, packet := range tokens {
					require.Error(t, sender.recovery.CompleteLocalPacket(packet.token, ackhandler.LocalPacketAccepted, monotime.Now()))
				}
			})
		})
	}
}

func TestBBRNativeActiveJumboStillRequiresExactBatch(t *testing.T) {
	nativeOrdinaryTest(t, func(t *testing.T) {
		c, sender, socket, now := largeBBRConnection(t, 65536)
		c.packetCeiling = 8972
		c.peerParams = &wire.TransportParameters{MaxUDPPayloadSize: 8972}
		c.mtuDiscoverer = c.newPathMTUFinder(8972, 8972)
		largeBBRPayloads(t, c, 100, 1)
		p := c.emission.bbr
		held := p.credit.reserve(p.creditLimit()-10000, p.creditLimit(), true, false)
		require.NotNil(t, held)
		defer held.complete()
		plan := c.emission.planBounded(nil, p, ackhandler.SendAny, 65536, 8972, nil, false, true, now)
		require.Greater(t, plan.request, protocol.ByteCount(10000))
		before, _ := sender.recovery.PeekPacketNumber(protocol.Encryption1RTT)
		queued := c.datagramQueue.Peek()
		result := c.emission.send(now, true)
		require.NoError(t, result.err)
		require.False(t, result.progress)
		require.Equal(t, blockModeCongestionLimited, result.blocked)
		require.Equal(t, (<-chan struct{})(p.credit.available), result.available)
		require.Empty(t, p.credit.available)
		after, _ := sender.recovery.PeekPacketNumber(protocol.Encryption1RTT)
		require.Equal(t, before, after)
		require.Same(t, queued, c.datagramQueue.Peek())
		synctest.Wait()
		require.Empty(t, socket.writes)
		require.Equal(t, held.bytes, c.emission.bbrPendingBytes(p))
	})
}

func TestBBRNativeCreditRefusalDoesNotPack(t *testing.T) {
	for _, isolated := range []bool{false, true} {
		nativeOrdinaryTest(t, func(t *testing.T) {
			c, sender, socket, now := largeBBRConnection(t, 65536)
			largeBBRPayloads(t, c, 100, 1)
			p := c.emission.bbr
			amount := p.creditLimit() - 1199
			if isolated {
				amount = 1200
			}
			held := p.credit.reserve(amount, p.creditLimit(), true, isolated)
			require.NotNil(t, held)
			defer held.complete()
			before, _ := sender.recovery.PeekPacketNumber(protocol.Encryption1RTT)
			queued := c.datagramQueue.Peek()
			for range 2 {
				result := c.emission.send(now, true)
				require.NoError(t, result.err)
				require.False(t, result.progress)
				require.Equal(t, blockModeHardBlocked, result.blocked)
				require.Equal(t, (<-chan struct{})(p.credit.available), result.available)
				require.Empty(t, p.credit.available, "a true refusal must not spin")
				after, _ := sender.recovery.PeekPacketNumber(protocol.Encryption1RTT)
				require.Equal(t, before, after)
				require.Same(t, queued, c.datagramQueue.Peek())
				require.Nil(t, sender.pending)
			}
			synctest.Wait()
			require.Empty(t, socket.writes)
			require.Equal(t, amount, c.emission.bbrPendingBytes(p))
		})
	}
}

func TestBBRNativeCreditRearmsMinimum(t *testing.T) {
	for _, completion := range []string{"before rearm", "after rearm", "none"} {
		t.Run(completion, func(t *testing.T) {
			nativeOrdinaryTest(t, func(t *testing.T) {
				c, sender, socket, now := largeBBRConnection(t, 65536)
				largeBBRPayloads(t, c, 1100, 4)
				p := c.emission.bbr
				old := p.credit.reserve(1200, p.creditLimit(), true, false)
				require.NotNil(t, old)
				defer func() {
					if old != nil {
						old.complete()
					}
				}()
				completeOld := func() {
					done := make(chan struct{})
					go func(r *sendReservation) {
						r.complete()
						close(done)
					}(old)
					<-done
					old = nil
				}
				c.emission.resetLocalPath(1, now)
				current := p.credit.reserve(p.creditLimit()-2400, p.creditLimit(), false, false)
				require.NotNil(t, current)
				defer current.complete()
				originalACKs := c.emission.packer.acks
				acks := NewMockAckFrameSource(gomock.NewController(t))
				acks.EXPECT().GetAckFrame(protocol.Encryption1RTT, now, true).DoAndReturn(func(protocol.EncryptionLevel, monotime.Time, bool) *wire.AckFrame {
					if completion == "before rearm" {
						completeOld()
					}
					return nil
				})
				c.emission.packer.acks = acks
				before, _ := sender.recovery.PeekPacketNumber(protocol.Encryption1RTT)
				queued := c.datagramQueue.Peek()
				result := c.emission.send(now, true)
				c.emission.packer.acks = originalACKs
				require.NoError(t, result.err)
				require.False(t, result.progress)
				require.Equal(t, blockModeCongestionLimited, result.blocked, "ACK/PTO timers remain eligible")
				require.Equal(t, (<-chan struct{})(p.credit.available), result.available)
				after, _ := sender.recovery.PeekPacketNumber(protocol.Encryption1RTT)
				require.Equal(t, before, after)
				require.Same(t, queued, c.datagramQueue.Peek())
				if completion != "before rearm" {
					require.Empty(t, p.credit.available, "unused ACK allowance creates no wakeup")
				}
				if completion == "none" {
					return
				}
				if completion == "after rearm" {
					completeOld()
				}
				select {
				case <-result.available:
				default:
					t.Fatal("completion making M fit must wake even though the original maximum still does not")
				}
				require.EqualValues(t, 2400, p.creditLimit()-c.emission.bbrPendingBytes(p))
				result = c.emission.send(now, true)
				require.NoError(t, result.err)
				require.True(t, result.progress)
				synctest.Wait()
				member := largeBBRMember(t, sender)
				require.LessOrEqual(t, member.buffer.Len(), protocol.ByteCount(2400))
				socket.release()
				synctest.Wait()
				require.NoError(t, sender.consume())
				require.Equal(t, current.bytes, c.emission.bbrPendingBytes(p))
			})
		})
	}
}
