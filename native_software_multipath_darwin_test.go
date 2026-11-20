//go:build darwin && !ios

package quic

import (
	"bytes"
	"net"
	"os"
	"slices"
	"syscall"
	"testing"
	"testing/synctest"
	"time"

	"github.com/GridCastIO/quicquic-go/internal/ackhandler"
	"github.com/GridCastIO/quicquic-go/internal/monotime"
	"github.com/GridCastIO/quicquic-go/internal/protocol"
	"github.com/stretchr/testify/require"
)

// nativeSoftwareMultipathConnection is a server whose negotiated multipath Reno
// connection has consumed-path admission and sends path zero through a recording
// native endpoint.
func nativeSoftwareMultipathConnection(t *testing.T) (*admissionFixture, *nativeOrdinarySender) {
	t.Helper()
	f := buildAdmissionFixtureFor(t, protocol.PerspectiveServer, nil, false, "reno")
	require.True(t, f.c.pathCredit.hasAdmission())
	// Keep real pacing; a short RTT lets one turn emit several packets.
	f.c.rttStats.UpdateRTT(100*time.Microsecond, 0)
	return f, f.c.emission.local.(*nativeOrdinarySender)
}

// nativeSoftwareMultipathStream opens stream 0 with ample flow control, so a test
// can queue a few packets per turn and keep congestion room for a later turn.
func nativeSoftwareMultipathStream(t *testing.T, c *Conn) *SendStream {
	t.Helper()
	c.connFlowController.UpdateSendWindow(1 << 20)
	flow := newStreamFlowController(0, c.connFlowController, 1<<20, 1<<20, 1<<20, c.flowControlRTT(), c.logger)
	return newSendStream(c.ctx, 0, c, flow, false)
}

// nativeSoftwareRecords reports the registered packets and the multi-datagram
// members of every record that is not Free, from the sender's sidecar.
func nativeSoftwareRecords(t *testing.T, sender *nativeOrdinarySender) (packets, segmented int) {
	t.Helper()
	for i := range sender.records {
		r := &sender.records[i]
		if r.state == ordinaryFree {
			continue
		}
		require.Equal(t, r.count, r.memberEnd(), "every registered packet is in a handed member")
		packets += r.count
		for _, member := range r.members {
			if member.datagrams > 1 {
				segmented++
			}
		}
	}
	return packets, segmented
}

// Production emission on Darwin builds software-segmented members for a negotiated
// multipath Reno connection's path zero, as it does for the ordinary flow. A
// pending terminal receipt keeps that path's existing constructor.
func TestNativeSoftwareMultipathEmissionSegments(t *testing.T) {
	nativeOrdinaryTest(t, func(t *testing.T) {
		f, sender := nativeSoftwareMultipathConnection(t)
		c := f.c
		require.True(t, sender.canSoftwareSegment(), "path zero of an admitted multipath connection is in the software domain")
		f.socket.hold = nativeProbeHoldAll
		queueNativeSoftwareStream(t, c)
		result := c.emission.send(monotime.Now(), true)
		require.NoError(t, result.err)
		require.True(t, result.progress)
		synctest.Wait() // the writer is parked on the first held write
		packets, segmented := nativeSoftwareRecords(t, sender)
		require.Greater(t, packets, 1, "the turn emitted more than one packet")
		require.NotZero(t, segmented, "path-zero multipath Reno shares a physical buffer across packets")
		f.socket.release()
		synctest.Wait()
		require.NoError(t, sender.consume())
		require.Len(t, f.socket.writes, packets, "a recorder writes each segment as its own datagram")
		for _, write := range f.socket.writes {
			require.Equal(t, nativeProbePeer, write.destination)
		}

		// A terminal control datagram awaiting its receipt must not share a member.
		c.pathCredit.terminals[1] = c.pathCredit.newTerminal()
		require.True(t, c.pathCredit.needsReceipt())
		require.False(t, sender.canSoftwareSegment(), "a pending receipt keeps the existing constructor")
		delete(c.pathCredit.terminals, 1)
		require.True(t, sender.canSoftwareSegment())
	})
}

// A local error inside a path-zero software member keeps the exact accepted
// prefix, the one uncertain datagram and the unsubmitted rest, and the path
// credit registry sees that member's own counts.
func TestNativeSoftwareMultipathCreditOutcomes(t *testing.T) {
	nativeOrdinaryTest(t, func(t *testing.T) {
		f, sender := nativeSoftwareMultipathConnection(t)
		c := f.c
		observer := &nativeSoftwareFenceObserver{LocalSentPacketHandler: sender.recovery}
		sender.recovery = observer
		cause := &os.SyscallError{Syscall: "sendmsg", Err: syscall.EAGAIN}
		f.socket.hold = nativeProbeHoldAll
		f.socket.result = func(data []byte) (int, error) {
			if len(f.socket.writes) == 3 {
				return 0, cause
			}
			return len(data), nil
		}
		// A few full-size packets: one natural turn, one request, one member.
		stream := nativeSoftwareMultipathStream(t, c)
		require.NoError(t, stream.TryWriteAll(bytes.Repeat([]byte("credit-outcome"), 400)))
		result := c.emission.send(monotime.Now(), true)
		require.NoError(t, result.err)
		synctest.Wait()

		var record *ordinaryLocalRecord
		for i := range sender.records {
			if sender.records[i].state != ordinaryFree {
				require.Nil(t, record, "the turn is one request")
				record = &sender.records[i]
			}
		}
		require.NotNil(t, record)
		require.Len(t, record.members, 1, "the turn is one member")
		datagrams := record.members[0].datagrams
		require.GreaterOrEqual(t, datagrams, 4, "the failure lands inside the member, before its last datagram")
		tokens := make([]ackhandler.LocalCompletionToken, 0, record.count)
		for _, packet := range record.packets[:record.count] {
			tokens = append(tokens, packet.token)
		}
		require.Len(t, tokens, datagrams)

		f.socket.release()
		synctest.Wait()
		require.NoError(t, sender.consume(), "local backpressure is not a connection error")
		require.Len(t, f.socket.writes, 3, "the writer stops the member at its failed datagram")
		require.Len(t, observer.completed, datagrams)
		for i, completion := range observer.completed {
			require.Equal(t, tokens[i], completion.token, "completions keep packet order")
			want := ackhandler.LocalPacketUnsubmitted
			switch {
			case i < 2:
				want = ackhandler.LocalPacketAccepted
			case i == 2:
				want = ackhandler.LocalPacketUncertain
			}
			require.Equal(t, want, completion.outcome, "packet %d", i)
			require.Equal(t, observer.completed[0].at, completion.at, "one member shares its native return")
		}
		require.Equal(t, "uncertain", c.pathCredit.members[0].lastOutcome)
	})
}

// A path-zero move finishes the software builder before it changes destination
// and write state, so no member spans two tuples. The next member starts on the
// new tuple's fresh write state, whose first datagram keeps its scalar retry.
func TestNativeSoftwareMultipathZeroMoveSeals(t *testing.T) {
	nativeOrdinaryTest(t, func(t *testing.T) {
		f, sender := nativeSoftwareMultipathConnection(t)
		c := f.c
		f.socket.hold = nativeProbeHoldAll
		// A few packets per turn leave congestion room for the turn after the move.
		stream := nativeSoftwareMultipathStream(t, c)
		require.NoError(t, stream.TryWriteAll(bytes.Repeat([]byte("before-move"), 500)))
		result := c.emission.advanceForPlatform(monotime.Now(), false, c.emission.softwareSegments)
		require.NoError(t, result.err)
		pending := sender.pending
		require.NotNil(t, pending)
		require.Equal(t, ordinaryBuilding, pending.state, "the turn's builder is still open")
		_, segmented := nativeSoftwareRecords(t, sender)
		require.NotZero(t, segmented)
		old := sender.writeState
		moved := &net.UDPAddr{IP: net.IPv4(192, 0, 2, 77), Port: 4433}
		destination, ok := nativeDestination(moved)
		require.True(t, ok)

		c.emission.moveLocalZero(nil, moved, packetInfo{}, f.tc.sendConn)
		require.Nil(t, sender.pending, "the move finished the builder before changing the tuple")
		require.NotEqual(t, ordinaryBuilding, pending.state)
		for i := range sender.records {
			// An endpoint-owned record's request moved to the endpoint with its
			// snapshot (clearRequest); the writes below show where those went.
			if r := &sender.records[i]; r.state != ordinaryFree && len(r.request.members) > 0 {
				require.Equal(t, nativeProbePeer, r.request.destination, "no record carries the new tuple yet")
			}
		}
		require.Equal(t, destination, sender.destination)
		require.NotSame(t, old, sender.writeState)
		require.False(t, sender.writeState.wroteFirstPacket)
		require.True(t, sender.canSoftwareSegment(), "a path-zero move keeps the software domain")

		// The gate stays open once released, so later writes pass without a hold.
		f.socket.release()
		synctest.Wait()
		require.NoError(t, sender.consume())
		before := len(f.socket.writes)
		require.NoError(t, stream.TryWriteAll(bytes.Repeat([]byte("after-move"), 500)))
		next := c.emission.send(monotime.Now(), true)
		require.NoError(t, next.err)
		synctest.Wait()
		_, segmented = nativeSoftwareRecords(t, sender)
		require.NotZero(t, segmented, "the new tuple builds software members")
		require.NoError(t, sender.consume())
		after := f.socket.writes[before:]
		require.NotEmpty(t, after)
		require.NotZero(t, before, "the pre-move turn reached the old tuple")
		for _, write := range f.socket.writes[:before] {
			require.Equal(t, nativeProbePeer, write.destination)
		}
		for _, write := range after {
			require.Equal(t, destination, write.destination)
		}
		require.True(t, sender.writeState.wroteFirstPacket, "the new tuple's first datagram was written")
		require.False(t, slices.ContainsFunc(after, func(w nativeProbeWrite) bool { return w.destination == nativeProbePeer }))
	})
}
