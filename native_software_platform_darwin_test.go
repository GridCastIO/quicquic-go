//go:build darwin && !ios

package quic

import (
	"testing"
	"testing/synctest"

	"github.com/GridCastIO/quicquic-go/internal/monotime"
	"github.com/stretchr/testify/require"
)

// Production emission on Darwin builds software-segmented members for confirmed
// ordinary primary Reno, as on Linux without wire GSO. This holds on every Darwin
// build; whether the writer batches them is the private-syscall hook's concern.
func TestNativeSoftwareRenoEmissionSegments(t *testing.T) {
	nativeOrdinaryTest(t, func(t *testing.T) {
		tc, sender, socket := nativeSoftwareBoundaryConnection(t)
		socket.hold = nativeProbeHoldAll
		c := tc.conn
		queueNativeSoftwareStream(t, c)
		result := c.emission.send(monotime.Now(), true)
		require.NoError(t, result.err)
		require.True(t, result.progress)
		synctest.Wait() // the writer is parked on the first held write
		var packets, segmented int
		for i := range sender.records {
			r := &sender.records[i]
			if r.state == ordinaryFree {
				continue
			}
			require.Equal(t, r.count, r.memberEnd(), "every registered packet is in a handed member")
			packets += r.count
			for _, member := range r.request.members {
				require.False(t, member.nativeGSO, "Darwin has no wire GSO")
				if member.gsoSize != 0 && member.datagrams() > 1 {
					segmented++
				}
			}
		}
		require.Greater(t, packets, 1, "the turn emitted more than one packet")
		require.NotZero(t, segmented, "confirmed ordinary Reno shares a physical buffer across packets")
		socket.release()
		synctest.Wait()
		require.NoError(t, sender.consume())
		require.Len(t, socket.writes, packets, "a recorder writes each segment as its own datagram")
	})
}
