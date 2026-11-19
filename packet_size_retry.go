package quic

import (
	"time"

	"github.com/GridCastIO/quicquic-go/internal/monotime"
	"github.com/GridCastIO/quicquic-go/internal/protocol"
)

// packetSizeRetry is confined to the connection run loop. Cooldown and elapsed
// eligibility belong to the connection; running search evidence belongs to a path.
type packetSizeRetry struct {
	deadline         monotime.Time
	pending, running bool
	next             uint8
	pathCeiling      protocol.ByteCount
}

func (c *Conn) schedulePacketSizeRetry(now monotime.Time) {
	r := &c.mtuRetry
	if r.deadline != 0 || r.pending {
		return
	}
	intervals := [...]time.Duration{60 * time.Second, 120 * time.Second, 240 * time.Second, 480 * time.Second, 900 * time.Second}
	r.deadline = now.Add(intervals[r.next])
	if int(r.next) < len(intervals)-1 {
		r.next++
	}
}

func (c *Conn) currentPathPacketCeiling() protocol.ByteCount {
	ceiling := c.effectivePacketCeiling()
	if c.mtuRetry.pathCeiling != 0 {
		ceiling = min(ceiling, c.mtuRetry.pathCeiling)
	}
	return ceiling
}

func (c *Conn) packetSizeRetryPermitted() bool {
	return c.mtuFallback.started != 0 && c.handshakeConfirmed && !c.config.DisablePathMTUDiscovery && c.conn.capabilities().DF && c.currentPathPacketCeiling() > protocol.MaxPacketBufferSize
}

func (c *Conn) packetSizeRetryTime() monotime.Time {
	if !c.packetSizeRetryPermitted() || c.mtuFallback.active {
		return 0
	}
	return c.mtuRetry.deadline
}

func (c *Conn) advancePacketSizeRetry(now monotime.Time) {
	r := &c.mtuRetry
	if !c.packetSizeRetryPermitted() || c.mtuFallback.active {
		return
	}
	if r.running {
		if !c.mtuDiscoverer.done() {
			return
		}
		r.running = false
		size := c.mtuDiscoverer.CurrentSize()
		if size > protocol.MaxPacketBufferSize && c.currentPathPacketCeiling()-size <= maxMTUDiff+1 {
			return
		}
		c.schedulePacketSizeRetry(now)
	}
	if r.deadline != 0 && !now.Before(r.deadline) {
		r.deadline, r.pending = 0, true
	}
	if !r.pending || !c.mtuDiscoverer.done() {
		return
	}
	r.pending, r.running = false, true
	c.mtuDiscoverer.Restart(c.mtuDiscoverer.CurrentSize(), c.currentPathPacketCeiling())
	c.mtuDiscoverer.Start(now)
}
