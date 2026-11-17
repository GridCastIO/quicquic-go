package quic

import (
	"testing"
	"time"

	"github.com/GridCastIO/quicquic-go/internal/ackhandler"
	"github.com/GridCastIO/quicquic-go/internal/monotime"
	"github.com/GridCastIO/quicquic-go/internal/protocol"

	"github.com/stretchr/testify/require"
)

// readyPath is an active path that can carry the next packet and DATAGRAM.
func readyPath(id protocol.PathID) pathView {
	return pathView{id: id, fits: true, ready: true}
}

func aggregateChoice(t *testing.T, views []pathView, primary protocol.PathID, now monotime.Time) protocol.PathID {
	t.Helper()
	chosen, _, steering, held, _ := selectAggregate(views, primary, now)
	require.False(t, held)
	require.False(t, steering)
	return chosen
}

func TestSelectAggregateByteRoundRobin(t *testing.T) {
	now := monotime.Now()
	fast, fresh := readyPath(0), readyPath(1)
	fast.scheduled, fresh.scheduled = 3000, 1200
	chosen, _, _, held, floor := selectAggregate([]pathView{fast, fresh}, 0, now)
	require.False(t, held)
	require.Equal(t, protocol.PathID(1), chosen, "fewer scheduled bytes go first")
	require.EqualValues(t, 1200, floor, "the ledger floor is the least-served candidate's bytes")

	fresh.scheduled = 4000
	require.Equal(t, protocol.PathID(0), aggregateChoice(t, []pathView{fast, fresh}, 0, now))
	require.Equal(t, protocol.PathID(0), aggregateChoice(t, []pathView{readyPath(0), readyPath(1)}, 1, now), "equal byte ledgers tie to the lower wire ID")
}

func TestSelectAggregatePacingCreditAndPMTU(t *testing.T) {
	now := monotime.Now()
	t.Run("pacing", func(t *testing.T) {
		paced, open := readyPath(0), readyPath(1)
		paced.sendAt, open.scheduled = now.Add(time.Millisecond), 5000
		require.Equal(t, protocol.PathID(1), aggregateChoice(t, []pathView{paced, open}, 0, now), "byte round-robin is paced: a path pacing allows now goes first")
		open.sendAt = now.Add(2 * time.Millisecond)
		require.Equal(t, protocol.PathID(0), aggregateChoice(t, []pathView{paced, open}, 0, now), "with every path paced, the earliest goes")
	})
	t.Run("congestion and local credit", func(t *testing.T) {
		limited := readyPath(0)
		limited.ready = false
		require.Equal(t, protocol.PathID(1), aggregateChoice(t, []pathView{limited, readyPath(1)}, 0, now), "a path that can't take a whole packet isn't a candidate")
		other := readyPath(1)
		other.ready = false
		require.Equal(t, protocol.PathID(1), aggregateChoice(t, []pathView{limited, other}, 1, now), "with none ready, the primary waits for its ACK")
		require.Equal(t, protocol.PathID(0), aggregateChoice(t, []pathView{limited, other}, 7, now), "or the lowest wire ID while the primary is out of view")
	})
	t.Run("PMTU", func(t *testing.T) {
		small, large := readyPath(0), readyPath(1)
		small.fits = false
		chosen, steerTo, steering, held, _ := selectAggregate([]pathView{small, large}, 0, now)
		require.False(t, held)
		require.Equal(t, protocol.PathID(0), chosen)
		require.True(t, steering, "the next DATAGRAM keeps its own eligibility")
		require.Equal(t, protocol.PathID(1), steerTo)
		large.ready = false
		chosen, _, steering, _, _ = selectAggregate([]pathView{small, large}, 0, now)
		require.Equal(t, protocol.PathID(0), chosen)
		require.False(t, steering, "a fitting path that can't send isn't named")
	})
}

func TestSelectAggregateBackupExclusion(t *testing.T) {
	now := monotime.Now()
	active, backup := readyPath(0), readyPath(1)
	active.scheduled = 1_000_000
	backup.backup = true
	require.Equal(t, protocol.PathID(0), aggregateChoice(t, []pathView{active, backup}, 0, now), "a backup stays out while an active path is eligible")
	active.ready = false
	require.Equal(t, protocol.PathID(0), aggregateChoice(t, []pathView{active, backup}, 0, now), "even when the active path waits on congestion")

	first, second := readyPath(0), readyPath(1)
	first.backup, second.backup = true, true
	first.scheduled = 1_000_000
	require.Equal(t, protocol.PathID(1), aggregateChoice(t, []pathView{first, second}, 0, now), "with only backups eligible, they aggregate")

	steer := readyPath(1)
	steer.backup = true
	active = readyPath(0)
	active.fits = false
	_, steerTo, steering, _, _ := selectAggregate([]pathView{active, steer}, 0, now)
	require.True(t, steering, "a DATAGRAM only a backup fits may still leave there")
	require.Equal(t, protocol.PathID(1), steerTo)
}

func TestSelectAggregateDeterministicTies(t *testing.T) {
	now := monotime.Now()
	for range 3 {
		require.Equal(t, protocol.PathID(0), aggregateChoice(t, []pathView{readyPath(0), readyPath(1)}, 1, now), "the ledger ties to the wire ID, not the primary")
	}
	_, _, _, held, _ := selectAggregate(nil, noPrimary, now)
	require.True(t, held, "no eligible path carries nothing ordinary")
}

// A path whose PTO fired goes first, so its probe retries the reliable data it
// carried on that same path, even ahead of a less-served path or as a backup.
func TestSelectAggregateSamePathRetryFirst(t *testing.T) {
	now := monotime.Now()
	probing := pathView{id: 1, probing: true, backup: true}
	require.Equal(t, protocol.PathID(1), aggregateChoice(t, []pathView{readyPath(0), probing}, 0, now))
}

// With no primary, a stale path awaiting revalidation carries nothing ordinary,
// under either private policy, while its pending PTO still goes.
func TestSelectAggregateHoldsWithoutPrimary(t *testing.T) {
	now := monotime.Now()
	_, _, _, held, _ := selectAggregate([]pathView{readyPath(0), readyPath(1)}, noPrimary, now)
	require.True(t, held)
	chosen, _, _, held, _ := selectAggregate([]pathView{readyPath(0), {id: 1, probing: true}}, noPrimary, now)
	require.False(t, held, "a stale path's pending PTO still goes")
	require.Equal(t, protocol.PathID(1), chosen)
}

func TestAggregateByteLedger(t *testing.T) {
	p := &pathCreditRegistry{scheduler: scheduleAggregate, members: map[protocol.PathID]*pathMember{0: {id: 0}, 1: {id: 1}}}
	p.noteScheduled(nil, 2400)
	p.noteScheduled(&pathRoute{context: ackhandler.PacketContext{PathID: 1}}, 1200)
	require.EqualValues(t, 2400, p.members[0].scheduled)
	require.EqualValues(t, 1200, p.members[1].scheduled)
	now := monotime.Now()
	a, b := readyPath(0), readyPath(1)
	a.scheduled, b.scheduled = 2400, 1200
	chosen, _, _, held := p.schedule([]pathView{a, b}, now)
	require.False(t, held)
	require.Equal(t, protocol.PathID(1), chosen)
	require.EqualValues(t, 1200, p.members[0].scheduled)
	require.Zero(t, p.members[1].scheduled)
	// While one member is ineligible, the ready member rebases without leaving
	// service debt for the returning path.
	a.scheduled = 1200
	p.schedule([]pathView{a}, now)
	require.Zero(t, p.members[0].scheduled)
	require.Zero(t, p.members[1].scheduled)
	a.scheduled, b.scheduled = 0, 0
	chosen, _, _, _ = p.schedule([]pathView{a, b}, now)
	require.Equal(t, protocol.PathID(0), chosen)
}
