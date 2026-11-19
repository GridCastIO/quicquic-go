//go:build linux || darwin || windows

package quic

import (
	"testing"
	"time"

	"github.com/GridCastIO/quicquic-go/internal/monotime"
	"github.com/GridCastIO/quicquic-go/internal/protocol"
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
	c := newJumboRefusalEmission(t).conn
	c.conn = &dfTestSendConn{sendConn: c.conn, df: true}
	now := monotime.Now()
	c.mtuFallback.started = now
	c.schedulePacketSizeRetry(now)
	deadline := c.mtuRetry.deadline
	c.resetPathPacketSize(now.Add(59 * time.Second))
	require.Equal(t, deadline, c.mtuRetry.deadline)
	require.EqualValues(t, 1, c.mtuRetry.next)
	c.advancePacketSizeRetry(deadline)
	require.True(t, c.mtuRetry.pending)
	require.Zero(t, c.packetSizeRetryTime())
	c.resetPathPacketSize(deadline.Add(time.Second))
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
	c.advancePacketSizeRetry(deadline.Add(2 * time.Second))
	require.True(t, c.mtuRetry.running)
	require.False(t, c.mtuRetry.pending)
	require.EqualValues(t, 1, c.mtuRetry.next)
	// A partial jumbo result is not restoration to the current path's ceiling.
	c.mtuDiscoverer.Reset(1470, 1470)
	c.advancePacketSizeRetry(deadline.Add(3 * time.Second))
	require.Equal(t, 120*time.Second, c.mtuRetry.deadline.Sub(deadline.Add(3*time.Second)))
	c.startPacketSizeFallback(deadline.Add(4 * time.Second))
	require.Zero(t, c.mtuRetry.deadline)
	require.False(t, c.mtuRetry.pending)
	require.EqualValues(t, 2, c.mtuRetry.next)
	c.advancePacketSizeRetry(deadline.Add(time.Hour))
	require.Zero(t, c.mtuRetry.deadline, "unconfirmed recovery cannot schedule")
	c.resetPathPacketSize(deadline.Add(5 * time.Second))
	require.Equal(t, 240*time.Second, c.mtuRetry.deadline.Sub(deadline.Add(5*time.Second)))
	require.EqualValues(t, 3, c.mtuRetry.next)
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
			require.Zero(t, c.packetSizeRetryTime())
			c.advancePacketSizeRetry(deadline.Add(time.Hour))
			require.Equal(t, deadline, c.mtuRetry.deadline)
			require.False(t, c.mtuRetry.running)
		})
	}
}

func TestPacketSizeRetryPersistentCutoff(t *testing.T) {
	c := newJumboRefusalEmission(t).conn
	c.conn = &dfTestSendConn{sendConn: c.conn, df: true}
	now := monotime.Now()
	c.startPacketSizeFallback(now)
	c.mtuFallback.active, c.mtuFallback.confirmed = false, true
	c.schedulePacketSizeRetry(now)
	for _, interval := range []time.Duration{60, 120, 240, 480, 900, 900} {
		require.Equal(t, interval*time.Second, c.mtuRetry.deadline.Sub(now))
		now = c.mtuRetry.deadline
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
}

func TestPacketSizeRetryThresholdCycle(t *testing.T) {
	c := newJumboRefusalEmission(t).conn
	c.conn = &dfTestSendConn{sendConn: c.conn, df: true}
	c.mtuFallback.started = monotime.Now()
	c.mtuDiscoverer.Reset(1232, 1468)
	now := monotime.Now()
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
	c.mtuRetry.running = true
	c.advancePacketSizeRetry(now)
	require.Equal(t, 60*time.Second, c.mtuRetry.deadline.Sub(now))
	// The next cycle reopens the candidate after cutoff removal.
	c.advancePacketSizeRetry(c.mtuRetry.deadline)
	ping, size := c.mtuDiscoverer.GetPing(now)
	require.Greater(t, size, protocol.ByteCount(1452))
	ping.Handler.OnAcked(ping.Frame)
	require.Greater(t, c.mtuDiscoverer.CurrentSize(), protocol.ByteCount(1452))
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
