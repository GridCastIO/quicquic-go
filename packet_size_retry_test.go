package quic

import (
	"testing"
	"testing/synctest"
	"time"

	"github.com/GridCastIO/quicquic-go/internal/ackhandler"
	"go.uber.org/mock/gomock"

	"github.com/GridCastIO/quicquic-go/internal/monotime"
	"github.com/GridCastIO/quicquic-go/internal/protocol"
	"github.com/GridCastIO/quicquic-go/internal/wire"
	"github.com/stretchr/testify/require"
)

func TestPacketSizeRetryBackoff(t *testing.T) {
	c := &Conn{}
	now := monotime.Now()
	for _, seconds := range []int{60, 120, 240, 480, 900, 900} {
		c.schedulePacketSizeRetry(now)
		require.Equal(t, time.Duration(seconds)*time.Second, c.mtuRetry.deadline.Sub(now))
		deadline := c.mtuRetry.deadline
		c.schedulePacketSizeRetry(now.Add(time.Second))
		require.Equal(t, deadline, c.mtuRetry.deadline, "an existing cycle must not consume another interval")
		now = deadline
		c.mtuRetry.deadline = 0
	}
}

func TestPacketSizeRetryMigrationEligibility(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		c := newJumboRefusalEmission(t).conn
		c.conn = &dfTestSendConn{sendConn: c.conn, df: true}
		now := monotime.Now()
		c.mtuFallback.started = now
		c.schedulePacketSizeRetry(now)
		deadline := c.mtuRetry.deadline
		c.resetPathPacketSize(now.Add(59*time.Second), now.Add(59*time.Second))
		require.Equal(t, deadline, c.mtuRetry.deadline)
		require.EqualValues(t, 1, c.mtuRetry.next)
		time.Sleep(deadline.Sub(monotime.Now()))
		c.advancePacketSizeRetry(deadline)
		require.True(t, c.mtuRetry.pending)
		require.Zero(t, c.packetSizeRetryTime())
		time.Sleep(time.Second)
		c.resetPathPacketSize(deadline.Add(time.Second), deadline.Add(time.Second))
		require.True(t, c.mtuRetry.pending)
		require.EqualValues(t, 1, c.mtuRetry.next)
		c.mtuRetry.pathCeiling = 1452
		require.Zero(t, c.packetSizeRetryTime())
		c.advancePacketSizeRetry(deadline.Add(time.Second))
		require.True(t, c.mtuRetry.pending)
		c.mtuRetry.pathCeiling = 8972
		for !c.mtuDiscoverer.done() {
			ping, _ := c.mtuDiscoverer.GetPing(now)
			ping.Handler.OnAcked(ping.Frame)
		}
		time.Sleep(time.Second)
		c.advancePacketSizeRetry(deadline.Add(2 * time.Second))
		require.True(t, c.mtuRetry.running)
		require.False(t, c.mtuRetry.pending)
		require.EqualValues(t, 1, c.mtuRetry.next)
		// A partial jumbo result is not restoration to the current path's ceiling.
		time.Sleep(time.Second)
		c.mtuDiscoverer.Restart(1470, 8972)
		for !c.mtuDiscoverer.done() {
			ping, _ := c.mtuDiscoverer.GetPing(monotime.Now())
			ping.Handler.OnLost(ping.Frame)
		}
		c.advancePacketSizeRetry(deadline.Add(3 * time.Second))
		require.Equal(t, 120*time.Second, c.mtuRetry.deadline.Sub(deadline.Add(3*time.Second)))
		c.startPacketSizeFallback(deadline.Add(4 * time.Second))
		require.Zero(t, c.mtuRetry.deadline)
		require.False(t, c.mtuRetry.pending)
		require.EqualValues(t, 2, c.mtuRetry.next)
		c.advancePacketSizeRetry(deadline.Add(time.Hour))
		require.Zero(t, c.mtuRetry.deadline, "unconfirmed recovery cannot schedule")
		c.resetPathPacketSize(deadline.Add(5*time.Second), deadline.Add(5*time.Second))
		require.Equal(t, 240*time.Second, c.mtuRetry.deadline.Sub(deadline.Add(5*time.Second)))
		require.EqualValues(t, 3, c.mtuRetry.next)
	})
}

func TestPacketSizeRetryIneligible(t *testing.T) {
	for _, name := range []string{"disabled", "no DF", "standard ceiling", "peer capped", "unconfirmed"} {
		t.Run(name, func(t *testing.T) {
			c := newJumboRefusalEmission(t).conn
			c.conn = &dfTestSendConn{sendConn: c.conn, df: name != "no DF"}
			c.mtuFallback.started = monotime.Now()
			c.schedulePacketSizeRetry(monotime.Now())
			deadline := c.mtuRetry.deadline
			switch name {
			case "disabled":
				c.config.DisablePathMTUDiscovery = true
			case "standard ceiling":
				c.mtuRetry.pathCeiling = 1452
			case "peer capped":
				c.peerParams.MaxUDPPayloadSize = 1452
			case "unconfirmed":
				c.handshakeConfirmed = false
			}
			if name == "standard ceiling" || name == "peer capped" {
				c.mtuRetry.awaitingStandard = true
				c.mtuRetry.deadline = monotime.Now().Add(-time.Second)
				deadline = c.mtuRetry.deadline
				c.mtuDiscoverer.Reset(1232, 1452)
				for !c.mtuDiscoverer.done() {
					ping, _ := c.mtuDiscoverer.GetPing(monotime.Now())
					ping.Handler.OnLost(ping.Frame)
				}
			}
			require.Zero(t, c.packetSizeRetryTime())
			c.advancePacketSizeRetry(deadline.Add(time.Hour))
			require.Equal(t, deadline, c.mtuRetry.deadline)
			require.False(t, c.mtuRetry.running)
		})
	}
}

func TestPacketSizeRetryPersistentCutoff(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		c := newJumboRefusalEmission(t).conn
		c.conn = &dfTestSendConn{sendConn: c.conn, df: true}
		now := monotime.Now()
		c.startPacketSizeFallback(now)
		c.mtuFallback.active, c.mtuFallback.confirmed = false, true
		c.schedulePacketSizeRetry(now)
		for _, interval := range []time.Duration{60, 120, 240, 480, 900, 900} {
			require.Equal(t, interval*time.Second, c.mtuRetry.deadline.Sub(now))
			time.Sleep(c.mtuRetry.deadline.Sub(monotime.Now()))
			now = monotime.Now()
			c.advancePacketSizeRetry(now)
			require.True(t, c.mtuRetry.running)
			for !c.mtuDiscoverer.done() {
				ping, size := c.mtuDiscoverer.GetPing(now)
				if size > 1472 {
					ping.Handler.OnLost(ping.Frame)
				} else {
					ping.Handler.OnAcked(ping.Frame)
				}
			}
			require.Greater(t, c.mtuDiscoverer.CurrentSize(), protocol.ByteCount(1452))
			require.LessOrEqual(t, c.mtuDiscoverer.CurrentSize(), protocol.ByteCount(1472))
			c.advancePacketSizeRetry(now)
			require.False(t, c.mtuRetry.running)
		}
	})
}

func TestPacketSizeRetryThresholdCycle(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		c := newJumboRefusalEmission(t).conn
		c.conn = &dfTestSendConn{sendConn: c.conn, df: true}
		c.mtuFallback.started = monotime.Now()
		c.mtuRetry.pathCeiling = 1468
		c.mtuDiscoverer.Reset(1232, 1468)
		now := monotime.Now()
		c.mtuRetry.running = true
		c.mtuDiscoverer.Restart(1232, 1468)
		// A cutoff can narrow the ordinary search to 1449 before jumbo confirmation.
		for !c.mtuDiscoverer.searchDone() || !c.mtuDiscoverer.stageOneDone {
			ping, size := c.mtuDiscoverer.GetPing(now)
			if size > 1452 {
				ping.Handler.OnLost(ping.Frame)
			} else {
				ping.Handler.OnAcked(ping.Frame)
			}
		}
		require.EqualValues(t, 1449, c.mtuDiscoverer.CurrentSize())
		for !c.mtuDiscoverer.done() {
			ping, _ := c.mtuDiscoverer.GetPing(now)
			ping.Handler.OnLost(ping.Frame)
		}
		c.advancePacketSizeRetry(now)
		require.Equal(t, 60*time.Second, c.mtuRetry.deadline.Sub(now))
		// The next cycle reopens the candidate after cutoff removal.
		time.Sleep(c.mtuRetry.deadline.Sub(monotime.Now()))
		now = monotime.Now()
		c.advancePacketSizeRetry(now)
		ping, size := c.mtuDiscoverer.GetPing(now)
		require.EqualValues(t, 1453, size)
		require.EqualValues(t, 1449, c.mtuDiscoverer.CurrentSize())
		ping.Handler.OnAcked(ping.Frame)
		require.EqualValues(t, 1453, c.mtuDiscoverer.CurrentSize())
		// Equal-ceiling losses end one cycle and schedule exactly one next cooldown.
		c.mtuRetry.pathCeiling = 1453
		c.mtuDiscoverer.Restart(1449, 1453)
		c.mtuRetry.running = true
		for range 3 {
			ping, _ := c.mtuDiscoverer.GetPing(now)
			ping.Handler.OnLost(ping.Frame)
		}
		c.advancePacketSizeRetry(now)
		deadline := c.mtuRetry.deadline
		require.Equal(t, 120*time.Second, deadline.Sub(now))
		c.advancePacketSizeRetry(now.Add(time.Second))
		require.Equal(t, deadline, c.mtuRetry.deadline)
	})
}

func TestPacketSizeRetryCeilingCapturedBeforeFallback(t *testing.T) {
	c := newJumboRefusalEmission(t).conn
	// A destination ceiling can be captured before the first fallback. Initial
	// discovery retains its existing policy; post-fallback search uses that ceiling.
	c.mtuRetry.pathCeiling = 1452
	require.EqualValues(t, 8972, c.currentPathPacketCeiling())
	c.mtuFallback.started = monotime.Now()
	require.EqualValues(t, 1452, c.currentPathPacketCeiling())
}

func TestPacketSizeRetryNarrowedMigratedStandardSearch(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		c := newJumboRefusalEmission(t).conn
		c.conn = &dfTestSendConn{sendConn: c.conn, df: true}
		now := monotime.Now()
		c.mtuFallback.started = now
		c.schedulePacketSizeRetry(now)
		c.resetPathPacketSize(now.Add(59*time.Second), now.Add(59*time.Second))
		time.Sleep(60 * time.Second)
		c.advancePacketSizeRetry(monotime.Now())
		require.True(t, c.mtuRetry.pending)
		time.Sleep(time.Second)
		for !c.mtuDiscoverer.done() {
			ping, size := c.mtuDiscoverer.GetPing(now)
			if size > 1392 {
				ping.Handler.OnLost(ping.Frame)
			} else {
				ping.Handler.OnAcked(ping.Frame)
			}
		}
		require.EqualValues(t, 1390, c.mtuDiscoverer.CurrentSize())
		completion := now.Add(61 * time.Second)
		c.advancePacketSizeRetry(completion)
		require.False(t, c.mtuRetry.pending)
		require.False(t, c.mtuRetry.running)
		require.Equal(t, 120*time.Second, c.mtuRetry.deadline.Sub(completion))
		c.advancePacketSizeRetry(c.mtuRetry.deadline)
		require.True(t, c.mtuRetry.running)
		require.False(t, c.mtuDiscoverer.done())
	})
}

// The timer seam supplies a definitive discovery loss. Recovery storage and
// emission remain real; only the alarm's time and loss fact are controlled.
type retryLossAlarm struct {
	ackhandler.SentPacketHandler
	deadline monotime.Time
	ping     ackhandler.Frame
}

func (h *retryLossAlarm) GetLossDetectionTimeout() monotime.Time { return h.deadline }
func (h *retryLossAlarm) OnLossDetectionTimeout(monotime.Time) (ackhandler.TimeoutOutcome, error) {
	h.deadline = 0
	h.ping.Handler.OnLost(h.ping.Frame)
	return ackhandler.TimeoutOutcome{}, nil
}

func TestPacketSizeRetryLossCompletionWhileQueueFull(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		tc := newJumboRefusalEmission(t)
		c := tc.conn
		c.conn = &dfTestSendConn{sendConn: c.conn, df: true}
		c.config.MaxIdleTimeout = 5 * time.Minute
		c.idleTimeout = 5 * time.Minute
		c.mtuFallback.started = monotime.Now()
		c.mtuRetry.running = true
		c.mtuDiscoverer.Restart(1449, 1453)
		now := monotime.Now()
		for range 2 {
			ping, _ := c.mtuDiscoverer.GetPing(now)
			ping.Handler.OnLost(ping.Frame)
		}
		ping, _ := c.mtuDiscoverer.GetPing(now)
		lossTime := now.Add(time.Second)
		c.sentPacketHandler = &retryLossAlarm{SentPacketHandler: c.sentPacketHandler, deadline: lossTime, ping: ping}
		ctrl := gomock.NewController(t)
		sender := NewMockSender(ctrl)
		c.emission.queue = sender
		blocked := true
		available := make(chan struct{})
		sender.EXPECT().Run()
		sender.EXPECT().Close()
		sender.EXPECT().WouldBlock().DoAndReturn(func() bool { return blocked }).AnyTimes()
		sender.EXPECT().Available().Return(available).AnyTimes()
		tc.connRunner.EXPECT().Remove(gomock.Any()).AnyTimes()
		done := make(chan error, 1)
		defer func() { c.destroy(nil); synctest.Wait(); require.NoError(t, <-done) }()
		go func() { done <- c.run() }()
		c.scheduleSending()
		synctest.Wait()
		time.Sleep(time.Second)
		c.scheduleSending() // process the due ordinary loss alarm while capacity is blocked
		synctest.Wait()
		require.True(t, c.mtuDiscoverer.done())
		require.Equal(t, lossTime.Add(time.Minute), c.mtuRetry.deadline)
		blocked = false
		close(available)
		synctest.Wait()
		require.Equal(t, lossTime.Add(time.Minute), c.mtuRetry.deadline)
	})
}

func TestPacketSizeRetryMigrationCutoverClock(t *testing.T) {
	c := newJumboRefusalEmission(t).conn
	received := monotime.Now()
	cutover := received.Add(time.Second)
	c.mtuFallback.started = received
	c.resetPathPacketSize(received, cutover)
	require.Equal(t, cutover.Add(time.Minute), c.mtuRetry.deadline)
	require.EqualValues(t, 1, c.mtuRetry.next)
	c.resetPathPacketSize(received, cutover.Add(time.Second))
	require.Equal(t, cutover.Add(time.Minute), c.mtuRetry.deadline)
	require.EqualValues(t, 1, c.mtuRetry.next)
}

func TestPacketSizeRetryReceiveCompletionWhileQueueFull(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		tc := newJumboRefusalEmission(t)
		c := tc.conn
		c.conn = &dfTestSendConn{sendConn: c.conn, df: true}
		c.idleTimeout = 5 * time.Minute
		now := monotime.Now()
		c.mtuFallback.started = now
		c.mtuRetry.running = true
		c.mtuDiscoverer.Restart(1449, 1453)
		c.maxPayloadSizeEstimate.Store(uint32(estimateMaxPayloadSize(1449)))
		for range 2 {
			ping, _ := c.mtuDiscoverer.GetPing(now)
			ping.Handler.OnLost(ping.Frame)
		}
		require.NoError(t, c.emission.mtuProbe(c.mtuDiscoverer, now).err)
		(<-c.emission.queue.(*sendQueue).queue).buf.Release()
		// A later ACK declares the third live candidate lost by packet distance.
		var last protocol.PacketNumber
		for range 4 {
			packet, buffer, err := c.emission.packer.PackMTUProbePacket(ackhandler.Frame{Frame: &wire.PingFrame{}}, 64, c.version)
			require.NoError(t, err)
			packet.IsPathMTUProbePacket = false
			require.NoError(t, c.emission.registerPacket(packet, protocol.ECNUnsupported, now))
			last = packet.PacketNumber
			buffer.Release()
		}
		payload, err := (&wire.AckFrame{AckRanges: []wire.AckRange{{Smallest: last, Largest: last}}}).Append(nil, c.version)
		require.NoError(t, err)
		payload = append(payload, 0x01) // PING creates the ordinary delayed-ACK alarm.
		incoming := getShortHeaderPacket(t, tc.remoteAddr, tc.srcConnID, 1, payload)
		ctrl := gomock.NewController(t)
		unpacker := NewMockUnpacker(ctrl)
		unpacker.EXPECT().UnpackShortHeader(protocol.PathID(0), gomock.Any(), gomock.Any()).Return(protocol.PacketNumber(1), protocol.PacketNumberLen2, protocol.KeyPhaseZero, payload, nil)
		c.unpacker = unpacker
		sender := NewMockSender(ctrl)
		c.emission.queue = sender
		blocked, queued := true, false
		available := make(chan struct{})
		sender.EXPECT().Run()
		sender.EXPECT().Close()
		sender.EXPECT().WouldBlock().DoAndReturn(func() bool {
			if !queued {
				queued = true
				c.handlePacket(incoming)
			}
			return blocked
		}).AnyTimes()
		sender.EXPECT().Available().Return(available).AnyTimes()
		sender.EXPECT().Send(gomock.Any(), gomock.Any(), gomock.Any(), gomock.Any()).Do(func(b *packetBuffer, _ uint16, _ protocol.ECN, _ sendMetadata) { b.Release() }).AnyTimes()
		tc.connRunner.EXPECT().Remove(gomock.Any()).AnyTimes()
		done := make(chan error, 1)
		defer func() { c.destroy(nil); synctest.Wait(); require.NoError(t, <-done) }()
		go func() { done <- c.run() }()
		c.scheduleSending()
		synctest.Wait()
		require.True(t, queued)
		require.EqualValues(t, 1449, c.mtuDiscoverer.CurrentSize())
		require.True(t, c.mtuDiscoverer.done())
		require.Equal(t, now.Add(time.Minute), c.mtuRetry.deadline)
		require.Equal(t, now, monotime.Now(), "completion is published before the delayed-ACK alarm")
		blocked = false
		close(available)
		synctest.Wait()
		require.Equal(t, now.Add(time.Minute), c.mtuRetry.deadline)
	})
}
