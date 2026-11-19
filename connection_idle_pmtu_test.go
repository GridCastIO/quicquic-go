package quic

import (
	"testing"
	"testing/synctest"
	"time"

	"github.com/GridCastIO/quicquic-go/internal/monotime"
	"github.com/GridCastIO/quicquic-go/internal/wire"
	"go.uber.org/mock/gomock"
)

func TestConnectionTimerWakesForIdleMTUProbe(t *testing.T) {
	for _, test := range []struct {
		name    string
		prepare func(*Conn, monotime.Time)
		want    time.Duration
	}{
		{name: "probe due", want: 5 * time.Millisecond},
		{name: "retry hard blocked", prepare: func(c *Conn, now monotime.Time) {
			c.packetCeiling = 8972
			c.peerParams = &wire.TransportParameters{MaxUDPPayloadSize: 8972}
			c.conn = &dfTestSendConn{sendConn: c.conn, df: true}
			c.mtuFallback.started = now
			c.mtuRetry.deadline = now.Add(5 * time.Millisecond)
			c.blocked = blockModeHardBlocked
		}, want: 5 * time.Millisecond},
		{name: "elapsed retry congestion blocked", prepare: func(c *Conn, now monotime.Time) {
			c.packetCeiling = 8972
			c.peerParams = &wire.TransportParameters{MaxUDPPayloadSize: 8972}
			c.conn = &dfTestSendConn{sendConn: c.conn, df: true}
			c.mtuFallback.started = now
			c.mtuRetry.deadline = now.Add(-time.Second)
			c.advancePacketSizeRetry(now)
			c.blocked = blockModeCongestionLimited
		}, want: time.Minute},
		{name: "retry paced", prepare: func(c *Conn, now monotime.Time) {
			c.packetCeiling = 8972
			c.peerParams = &wire.TransportParameters{MaxUDPPayloadSize: 8972}
			c.conn = &dfTestSendConn{sendConn: c.conn, df: true}
			c.mtuFallback.started = now
			c.mtuDiscoverer.Reset(1438, 1452)
			c.mtuRetry.deadline = now
			c.advancePacketSizeRetry(now)
			c.pacingDeadline = now.Add(10 * time.Millisecond)
		}, want: 10 * time.Millisecond},

		{name: "pacing", prepare: func(c *Conn, now monotime.Time) { c.pacingDeadline = now.Add(10 * time.Millisecond) }, want: 10 * time.Millisecond},
		{name: "in flight", prepare: func(c *Conn, now monotime.Time) { c.mtuDiscoverer.GetPing(now) }, want: 15 * time.Second},
		{name: "not started", prepare: func(c *Conn, _ monotime.Time) { c.mtuDiscoverer = newMTUDiscoverer(c.rttStats, 1232, 1452, nil) }, want: 15 * time.Second},
		{name: "settled", prepare: func(c *Conn, now monotime.Time) {
			c.mtuDiscoverer = newMTUDiscoverer(c.rttStats, 1452, 1452, nil)
			c.mtuDiscoverer.Start(now)
		}, want: 15 * time.Second},
		{name: "hard blocked", prepare: func(c *Conn, _ monotime.Time) { c.blocked = blockModeHardBlocked }, want: time.Minute},
		{name: "congestion limited", prepare: func(c *Conn, _ monotime.Time) { c.blocked = blockModeCongestionLimited }, want: time.Minute},
		{name: "unconfirmed", prepare: func(c *Conn, _ monotime.Time) { c.handshakeConfirmed = false }, want: 15 * time.Second},
	} {
		t.Run(test.name, func(t *testing.T) {
			synctest.Test(t, func(t *testing.T) {
				ctrl := gomock.NewController(t)
				tc := newServerTestConnection(t, ctrl,
					&Config{MaxIdleTimeout: time.Minute, KeepAlivePeriod: 15 * time.Second}, false,
					connectionOptHandshakeConfirmed(), connectionOptRTT(time.Millisecond))
				c := tc.conn
				now := monotime.Now()
				c.lastPacketReceivedTime = now
				c.keepAliveInterval = 15 * time.Second
				c.idleTimeout = time.Minute
				c.mtuDiscoverer = newMTUDiscoverer(c.rttStats, 1232, 1452, nil)
				c.mtuDiscoverer.Start(now)
				if test.prepare != nil {
					test.prepare(c, now)
				}
				c.timer = time.NewTimer(time.Hour)
				defer c.timer.Stop()
				c.maybeResetTimer()
				select {
				case <-c.timer.C:
					if elapsed := monotime.Since(now); elapsed != test.want {
						t.Fatalf("timer: got %v, want %v", elapsed, test.want)
					}
				case <-time.After(test.want + time.Millisecond):
					t.Fatalf("timer: no wake by %v, want %v", test.want+time.Millisecond, test.want)
				}
			})
		})
	}
}
