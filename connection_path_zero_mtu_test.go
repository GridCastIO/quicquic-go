//go:build darwin || linux || freebsd

package quic

import (
	"context"
	"testing"
	"testing/synctest"
	"time"

	"github.com/GridCastIO/quicquic-go/internal/ackhandler"
	"github.com/GridCastIO/quicquic-go/internal/monotime"
	"github.com/GridCastIO/quicquic-go/internal/protocol"
	"github.com/GridCastIO/quicquic-go/internal/wire"
	"github.com/stretchr/testify/require"
)

// Observe the accounting handoff while retaining real ACK processing and recovery.
type pathZeroMTURecovery interface {
	ackhandler.SentPacketHandler
	pathAckReceiver
	RecoveryOnPath(protocol.PathID) ackhandler.SentPacketHandler
}

type pathZeroMTUAccounting struct {
	pathZeroMTURecovery
	size protocol.ByteCount
}

func (h *pathZeroMTUAccounting) SetMaxDatagramSize(size protocol.ByteCount) {
	h.size = size
	h.pathZeroMTURecovery.SetMaxDatagramSize(size)
}

func TestPathZeroMTUGrowthAfterAbortedMigration(t *testing.T) {
	for _, controller := range []string{"reno", "bbrv3"} {
		t.Run(controller, func(t *testing.T) {
			nativeOrdinaryTest(t, func(t *testing.T) {
				f := newReliableFixtureFor(t, protocol.PerspectiveClient, nil, controller)
				c, p := f.c, f.c.pathCredit
				c.mtuDiscoverer = c.newPathMTUFinder(1280, 1320)
				finder := c.mtuDiscoverer
				f.setPathMTU(1, 1450)
				target, socket := migrationTarget(t, f.admissionFixture)
				ctx, cancel := context.WithCancel(context.Background())
				defer cancel()
				errs := migrateAsync(ctx, f.admissionFixture, 0, target)
				f.pass(t)
				challenges := socketChallenges(t, f.admissionFixture, socket, 0)
				require.NotEmpty(t, challenges)
				f.write(t, 1000)
				f.pass(t)
				for range suspectPTOAttempts - 1 {
					f.policyPTO(t, 0)
				}
				f.socket.hold = nativeProbeHoldAll
				f.write(t, 1000)
				f.pass(t)
				f.policyPTO(t, 0)
				require.True(t, p.members[0].suspect)
				require.True(t, f.receive(t, 0, p.members[0].addr, 1200, &wire.PathResponseFrame{Data: challenges[0]}))
				f.pass(t)
				require.True(t, p.members[0].fencing())
				require.True(t, p.members[0].suspect)
				require.Greater(t, c.maxPayloadSizeEstimate.Load(), uint32(estimateMaxPayloadSize(1320)))

				cancel()
				require.ErrorIs(t, <-errs, context.Canceled)
				f.pass(t)
				f.socket.hold = nil
				f.socket.release()
				synctest.Wait()
				f.pass(t)
				require.Same(t, finder, c.mtuDiscoverer)
				f.answerChallenge(t, 0)
				f.ackPath(t, 0, 0, f.parseWrites(t, 0))
				require.False(t, p.members[0].suspect)
				p.selectPrimaryPrivate(0)
				f.socket.writes = nil
				finder.Start(monotime.Now())
				time.Sleep(time.Until(finder.NextProbeTime().ToTime()) + time.Millisecond)
				f.pass(t)
				writes := f.parseWrites(t, 0)
				require.NotEmpty(t, writes)
				require.Len(t, writes[0].data, 1300)
				realHandler := c.sentPacketHandler
				accounting := &pathZeroMTUAccounting{pathZeroMTURecovery: realHandler.(pathZeroMTURecovery)}
				c.sentPacketHandler = accounting
				f.ackPath(t, 0, 0, writes[:1])
				c.sentPacketHandler = realHandler
				require.EqualValues(t, 1300, accounting.size, "own ACK growth reaches real congestion accounting")
				require.EqualValues(t, 1300, finder.CurrentSize())
				require.True(t, finder.done())
				select {
				case <-c.PathMTUSettledV1():
				default:
					t.Fatal("path zero's acknowledged growth must settle below the survivor's cached limit")
				}
				f.socket.writes = nil
				f.write(t, 4000)
				f.drain(t)
				var largestDataPacket int
				for _, write := range f.parseWrites(t, 0) {
					if len(write.streams) > 0 {
						largestDataPacket = max(largestDataPacket, len(write.data))
					}
				}
				require.Equal(t, 1300, largestDataPacket, "STREAM packets use and respect the finder's bound")
				if controller == "bbrv3" {
					require.EqualValues(t, 2600, c.emission.bbr.quantum, "ordinary emission refreshes BBR's two-packet quantum")
				}
				c.peerParams.MaxDatagramFrameSize = wire.MaxDatagramSize
				c.emission.selectRoute(monotime.Now())
				var tooLarge *DatagramTooLargeError
				require.ErrorAs(t, c.SendDatagram(make([]byte, 1300)), &tooLarge)
				require.EqualValues(t, datagramPayloadLimit(1300, c.connIDManager.Get()), tooLarge.MaxDatagramPayloadSize)
				require.NoError(t, c.SendDatagram(make([]byte, tooLarge.MaxDatagramPayloadSize)))
			})
		})
	}
}
