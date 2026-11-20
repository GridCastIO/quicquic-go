//go:build darwin && !ios

package quic

import (
	"bytes"
	"net"
	"net/netip"
	"testing"
	"testing/synctest"

	"github.com/GridCastIO/quicquic-go/internal/ackhandler"
	"github.com/GridCastIO/quicquic-go/internal/monotime"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"
)

// openZeroBuilder is a negotiated multipath Reno server whose path zero has
// written on its tuple and still holds the next turn's software builder open.
type openZeroBuilder struct {
	f        *admissionFixture
	sender   *nativeOrdinarySender
	observer *nativeSoftwareFenceObserver
	stream   *SendStream
	m        *pathMember
	// The open builder's packets and the state before the tuple changes.
	pending   *ordinaryLocalRecord
	tokens    []ackhandler.LocalCompletionToken
	completed int
	writes    int
	outcome   string
	old       *endpointWriteState
}

func newOpenZeroBuilder(t *testing.T) *openZeroBuilder {
	t.Helper()
	f, sender := nativeSoftwareMultipathConnection(t)
	c := f.c
	f.supplyPeerCIDs(t) // path zero's standby CID for a cutover
	observer := &nativeSoftwareFenceObserver{LocalSentPacketHandler: sender.recovery}
	sender.recovery = observer
	b := &openZeroBuilder{f: f, sender: sender, observer: observer, stream: nativeSoftwareMultipathStream(t, c), m: c.pathCredit.members[0]}

	// A sealed turn on the old tuple writes its first datagram.
	require.NoError(t, b.stream.TryWriteAll(bytes.Repeat([]byte("old-tuple"), 300)))
	require.NoError(t, c.emission.send(monotime.Now(), true).err)
	synctest.Wait()
	require.NoError(t, sender.consume())
	require.NotEmpty(t, f.socket.writes)
	for _, write := range f.socket.writes {
		require.Equal(t, nativeProbePeer, write.destination)
	}
	require.True(t, sender.writeState.wroteFirstPacket, "the old tuple's first datagram was written")

	// The next turn's builder is still open when the tuple changes.
	require.NoError(t, b.stream.TryWriteAll(bytes.Repeat([]byte("open-builder"), 500)))
	require.NoError(t, c.emission.advanceForPlatform(monotime.Now(), false, c.emission.softwareSegments).err)
	pending := sender.pending
	require.NotNil(t, pending)
	require.Equal(t, ordinaryBuilding, pending.state, "the turn's builder is still open")
	require.Greater(t, pending.count, 1)
	datagrams, segmented := 0, false
	for _, member := range pending.members {
		datagrams += member.datagrams
		segmented = segmented || member.datagrams > 1
	}
	require.True(t, segmented, "the open builder holds a software-segmented member")
	require.Equal(t, pending.count, datagrams, "every registered packet is in a handed member")
	// Settlement reuses the record's slices, so the tokens are copied.
	for _, packet := range pending.packets[:pending.count] {
		b.tokens = append(b.tokens, packet.token)
	}
	b.pending, b.completed, b.writes = pending, len(observer.completed), len(f.socket.writes)
	b.outcome, b.old = b.m.lastOutcome, sender.writeState
	withFirstPathFinder(f) // a cutover resets the handshake's path MTU finder
	return b
}

// requireCancelled checks the old tuple's member right after the tuple change,
// then that a later turn builds software members for the new destination only.
func (b *openZeroBuilder) requireCancelled(t *testing.T, destination netip.AddrPort) {
	t.Helper()
	f, sender, c := b.f, b.sender, b.f.c
	require.Nil(t, sender.pending, "the open builder was settled")
	require.Equal(t, ordinaryFree, b.pending.state)
	cancelled := b.observer.completed[b.completed:]
	require.Len(t, cancelled, len(b.tokens), "0 accepted, 0 uncertain and every datagram unsubmitted")
	for i, completion := range cancelled {
		require.Equal(t, b.tokens[i], completion.token, "completions keep packet order")
		require.Equal(t, ackhandler.LocalPacketUnsubmitted, completion.outcome, "packet %d", i)
	}
	require.Len(t, f.socket.writes, b.writes, "the old tuple's member wrote nothing")
	require.False(t, sender.writeState.wroteFirstPacket, "the new tuple's first write can retry")
	require.Equal(t, destination, sender.destination)
	require.True(t, sender.canSoftwareSegment(), "a same-endpoint rebind keeps the software domain")

	require.NoError(t, b.stream.TryWriteAll(bytes.Repeat([]byte("new-tuple"), 500)))
	require.NoError(t, c.emission.send(monotime.Now(), true).err)
	synctest.Wait()
	_, segmented := nativeSoftwareRecords(t, sender)
	require.NotZero(t, segmented, "the new tuple builds software members")
	require.NoError(t, sender.consume(), "no cancelled packet completes again")
	after := f.socket.writes[b.writes:]
	require.NotEmpty(t, after)
	for _, write := range after {
		require.Equal(t, destination, write.destination)
	}
	require.True(t, sender.writeState.wroteFirstPacket, "the new tuple's first datagram was written")
	for _, token := range b.tokens {
		seen := 0
		for _, completion := range b.observer.completed {
			if completion.token == token {
				seen++
			}
		}
		require.Equal(t, 1, seen, "each cancelled packet completes once")
	}
}

// A same-transport path-zero tuple change never submits an open software builder
// to the old tuple, restarts the write state's first-write fallback, and leaves
// later members to the new destination.
func TestNativeSoftwareMultipathZeroRebindCancels(t *testing.T) {
	rebound := &net.UDPAddr{IP: net.IPv4(192, 0, 2, 78), Port: 4433}
	destination, ok := nativeDestination(rebound)
	require.True(t, ok)

	// rebindZero itself cancels the open builder. This is commitTuple's path-zero
	// branch without its leading leaveRoute, which would finish the builder first.
	t.Run("rebind", func(t *testing.T) {
		nativeOrdinaryTest(t, func(t *testing.T) {
			b := newOpenZeroBuilder(t)
			c, m := b.f.c, b.m
			b.f.tc.sendConn.EXPECT().ChangeRemoteAddr(rebound, gomock.Any())
			c.pathGeneration++
			m.tuple = c.pathGeneration
			c.emission.resetLocalPath(c.pathGeneration, monotime.Now())
			c.emission.rebindLocalZero(rebound, packetInfo{})
			require.Same(t, b.old, b.sender.writeState, "a rebind keeps path zero's write state")
			require.Equal(t, b.outcome, m.lastOutcome, "the old tuple's cancellation is not the new tuple's outcome")
			b.requireCancelled(t, destination)
		})
	})

	// The production cutover on the same transport. Its leaveRoute finishes the
	// builder, the endpoint refuses the retired zero epoch's request, and the
	// sender settles it before rebindLocalZero runs. serviceCutover's fence would
	// wait for this builder, so the test commits directly.
	t.Run("commit", func(t *testing.T) {
		nativeOrdinaryTest(t, func(t *testing.T) {
			b := newOpenZeroBuilder(t)
			p, m := b.f.c.pathCredit, b.m
			transport := m.transport
			p.beginIncomingCutover(m, rebound, packetInfo{}, m.largestNonProbing, monotime.Now())
			require.NotNil(t, m.candidate)
			require.Same(t, transport, m.candidate.transport, "a same-transport cutover")
			tuple := m.tuple
			b.f.tc.sendConn.EXPECT().ChangeRemoteAddr(rebound, gomock.Any())
			p.commitTuple(m, m.candidate, monotime.Now())
			require.Greater(t, m.tuple, tuple, "the cutover advanced path zero's tuple")
			b.requireCancelled(t, destination)
		})
	})
}
