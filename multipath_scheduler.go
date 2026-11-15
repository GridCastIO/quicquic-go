package quic

import (
	"slices"

	"github.com/quic-go/quic-go/internal/monotime"
	"github.com/quic-go/quic-go/internal/protocol"
)

// pathScheduler is a multipath connection's private scheduling policy. It owns the
// choice of route only; emission keeps packing, credit, registration and each
// DATAGRAM's eligibility. Aggregate is reachable only through the private experiment
// selector; the public policy remains primary/backup.
type pathScheduler uint8

const (
	schedulePrimaryBackup pathScheduler = iota
	// scheduleAggregate balances eligible opportunities with paced byte round-robin.
	scheduleAggregate
)

// schedule chooses the opportunity's route from immutable views in path ID order.
func (p *pathCreditRegistry) schedule(views []pathView, now monotime.Time) (chosen, steerTo protocol.PathID, steering, held bool) {
	if p.scheduler != scheduleAggregate {
		return selectPath(views, p.primary)
	}
	chosen, steerTo, steering, held, floor := selectAggregate(views, p.primary, now)
	// Rebase the ledger on its least-served candidate, so it stays within about one
	// handoff and a returning path is neither starved nor owed a backlog.
	for _, m := range p.members {
		m.scheduled -= min(m.scheduled, floor)
	}
	return chosen, steerTo, steering, held
}

// viewOf reads one eligible path for selection, after bringing a nonzero route up
// to its current tuple.
func (p *pathCreditRegistry) viewOf(m *pathMember, now monotime.Time) pathView {
	var route *pathRoute
	recovery := p.conn.sentPacketHandler
	if m.id != 0 {
		p.refreshRoute(m)
		route, recovery = &m.route, m.route.recovery
	}
	view := p.conn.emission.pathView(m.id, route, recovery, now)
	view.backup, view.scheduled = m.backup, m.scheduled
	return view
}

// noteScheduled charges a handoff's bytes to the round-robin ledger of the path
// that carried it.
func (p *pathCreditRegistry) noteScheduled(route *pathRoute, n protocol.ByteCount) {
	if p.scheduler == schedulePrimaryBackup {
		return
	}
	var id protocol.PathID
	if route != nil {
		id = route.context.PathID
	}
	if m := p.members[id]; m != nil {
		m.scheduled += uint64(n)
	}
}

// selectAggregate is the aggregate policy. A pending PTO goes first, so a path's
// probe retries its reliable data there. With no primary, ordinary work holds, as
// it does under primary/backup. Otherwise active paths are the candidates while any is
// eligible, and backups only when none is. Among candidates that can take a whole
// packet, paced byte round-robin chooses. Ties go to the lower
// wire ID. With no candidate ready, the primary waits, as it does under primary/backup.
// floor is the least ledger among the round-robin candidates.
func selectAggregate(views []pathView, primary protocol.PathID, now monotime.Time) (chosen, steerTo protocol.PathID, steering, held bool, floor uint64) {
	if index := slices.IndexFunc(views, func(view pathView) bool { return view.probing }); index >= 0 {
		return views[index].id, 0, false, false, 0
	}
	if primary == noPrimary {
		// No path is authorized to carry ordinary work: a stale one waits for revalidation.
		return 0, 0, false, true, 0
	}
	active := false
	for _, view := range views {
		active = active || !view.backup
	}
	candidate := func(view pathView) bool { return !active || !view.backup }
	pick, wait, first := -1, -1, true
	for i, view := range views {
		if !candidate(view) {
			continue
		}
		if wait < 0 || view.id == primary {
			wait = i
		}
		if !view.ready {
			continue
		}
		if first || view.scheduled < floor {
			floor, first = view.scheduled, false
		}
		if pick < 0 || roundRobinBefore(view, views[pick], now) {
			pick = i
		}
	}
	if pick < 0 {
		if wait < 0 {
			return 0, 0, false, true, 0
		}
		pick = wait
	}
	steerTo, steering = steerFor(views[pick], views)
	return views[pick].id, steerTo, steering, false, floor
}

// roundRobinBefore orders paced byte round-robin: a path pacing allows now before
// one it doesn't, the earlier send time among paced paths, then fewer bytes served.
func roundRobinBefore(a, b pathView, now monotime.Time) bool {
	aNow, bNow := !a.sendAt.After(now), !b.sendAt.After(now)
	switch {
	case aNow != bNow:
		return aNow
	case !aNow && a.sendAt != b.sendAt:
		return a.sendAt < b.sendAt
	default:
		return a.scheduled < b.scheduled
	}
}
