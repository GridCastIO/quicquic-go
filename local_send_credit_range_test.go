package quic

import (
	"testing"

	"github.com/quic-go/quic-go/internal/monotime"
	"github.com/quic-go/quic-go/internal/protocol"
	"github.com/quic-go/quic-go/internal/wire"
	"github.com/stretchr/testify/require"
)

func TestLocalSendCreditWholePacketRange(t *testing.T) {
	for _, tc := range []struct {
		name                        string
		maximum, limit, held, grant protocol.ByteCount
	}{
		{"full request", 64800, 131072, 0, 64800},
		{"partial room", 64800, 131072, 98304, 32400},
		{"one packet", 64800, 131072, 129872, 1200},
		{"less than one packet", 64800, 131072, 129873, 0},
		{"nonmultiple room", 64800, 131072, 128671, 2400},
		{"nonmultiple maximum", 2501, 131072, 0, 2400},
		{"reduced limit", 2400, 4800, 6000, 0},
	} {
		t.Run(tc.name, func(t *testing.T) {
			c := newLocalSendCredit()
			var held *sendReservation
			if tc.held != 0 {
				held = c.reserve(tc.held, 131072, true, false)
				require.NotNil(t, held)
				defer held.complete()
			}
			r := c.reserveUpTo(tc.maximum, tc.limit, 1200)
			if tc.grant == 0 {
				require.Nil(t, r)
				require.Equal(t, tc.held, c.pending)
				return
			}
			require.NotNil(t, r)
			require.Equal(t, tc.grant, r.bytes)
			require.Equal(t, tc.held+tc.grant, c.pending)
			require.Equal(t, c.pending, c.current)
			r.resize(tc.grant - 17)
			require.Equal(t, tc.held+tc.grant-17, c.pending)
			r.complete()
			require.Equal(t, tc.held, c.pending)
			next := c.reserveUpTo(tc.maximum, tc.limit, 1200)
			require.Same(t, r, next, "the existing reservation pool serves both operations")
			next.completeLocal()
			require.Equal(t, tc.held, c.pending)
		})
	}
	for _, tc := range []struct{ maximum, size protocol.ByteCount }{{1200, 0}, {1200, -1}, {1199, 1200}} {
		c := newLocalSendCredit()
		require.Panics(t, func() { c.reserveUpTo(tc.maximum, 4800, tc.size) })
		require.Zero(t, c.pending)
	}
}

func TestLocalSendCreditRangeRefusalDrainsWakeup(t *testing.T) {
	for _, isolated := range []bool{false, true} {
		c := newLocalSendCredit()
		held := c.reserve(1200, 4800, true, isolated)
		require.NotNil(t, held)
		if !isolated {
			c.resetGeneration(1)
		}
		c.available <- struct{}{} // a coalesced, now-stale completion signal
		require.Nil(t, c.reserveUpTo(2400, 4800, 1200))
		require.Empty(t, c.available)
		require.EqualValues(t, 1200, c.pending)
		require.Equal(t, !isolated, c.waitForReservation(1200, 4800, 1200, true, false), "only generation debt permits control")
		require.Empty(t, c.available, "neither ordinary exclusion is relieved by unused byte room")
		held.complete()
		require.Len(t, c.available, 1, "terminal completion still signals")
		r := c.reserveUpTo(2400, 4800, 1200)
		require.NotNil(t, r)
		require.EqualValues(t, 2400, r.bytes)
		r.completeLocal()
		require.Zero(t, c.pending)
	}
}

func TestBBRUnregisteredCreditStillRequiresExactBatch(t *testing.T) {
	c := newEmissionTestConnection(t, true).conn
	now := monotime.Now()
	p := newBBRSendPolicy(100_000_000, 1200, now)
	c.emission.bbr = p
	held := p.credit.reserve(p.creditLimit()-2400, p.creditLimit(), true, false)
	require.NotNil(t, held)
	defer held.complete()
	require.NoError(t, c.datagramQueue.Add(&wire.DatagramFrame{DataLenPresent: true, Data: []byte("requires the exact ordinary batch")}))
	mode, allowance := c.emission.selected().(boundedRecovery).SendAllowance(now)
	plan := c.emission.planBounded(nil, p, mode, allowance, 1200, nil, false, true, now)
	require.Greater(t, plan.request, protocol.ByteCount(2400))
	before, _ := c.sentPacketHandler.PeekPacketNumber(protocol.Encryption1RTT)
	queued := c.datagramQueue.Peek()
	result := c.emission.send(now, true)
	require.NoError(t, result.err)
	require.False(t, result.progress)
	require.Equal(t, blockModeCongestionLimited, result.blocked)
	require.Equal(t, (<-chan struct{})(p.credit.available), result.available)
	require.Empty(t, p.credit.available, "the excluded exact request does not rearm for partial room")
	after, _ := c.sentPacketHandler.PeekPacketNumber(protocol.Encryption1RTT)
	require.Equal(t, before, after)
	require.Same(t, queued, c.datagramQueue.Peek())
	require.Empty(t, c.emission.queue.(*sendQueue).queue)
}
