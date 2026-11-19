//go:build darwin

package quic

import (
	"context"
	"errors"
	"net"
	"net/netip"
	"os"
	"sync"
	"sync/atomic"
	"syscall"
	"testing"
	"testing/synctest"
	"time"

	"github.com/GridCastIO/quicquic-go/internal/monotime"
	"github.com/stretchr/testify/require"
)

// MP-MAC E3: scalar lane contention records and the bounded socket-pressure
// observation. The endpoint's admission, fairness and result classification own
// the behavior; this fixture owns only the offered load and its observations.

// nativeDarwinLaneNames are the three lanes of one data participant: its two
// path lanes and its control lane.
var nativeDarwinLaneNames = [3]string{"path0", "path1", "control"}

// nativeDarwinErrorClasses are the native write error classes the observer counts.
var nativeDarwinErrorClasses = [5]string{"enobufs", "eagain", "emsgsize", "deadline", "other"}

// nativeDarwinLoad is the offered load: participants each offer requests on every
// lane, each request carrying members scalar datagrams of payload bytes. budget is
// the endpoint's write budget, and window bounds the whole load; a load that has
// not finished when its window ends is interrupted.
type nativeDarwinLoad struct {
	participants, requests, members, payload int
	budget, window                           time.Duration
}

func (l nativeDarwinLoad) facts() map[string]any {
	return map[string]any{
		"participants": l.participants, "requests": l.requests, "members": l.members, "payload": l.payload,
		"budget_ms": l.budget.Milliseconds(), "window_ms": l.window.Milliseconds(),
	}
}

// nativeDarwinWriterObserver delegates every call of the endpoint's writer to the
// real socket and keeps bounded aggregates. Only the endpoint's sole writer calls
// it, and it never blocks, so it adds no lock and no wait to the writer. The
// endpoint's join publishes its fields to the fixture.
type nativeDarwinWriterObserver struct {
	native   endpointNativeIO
	deadline time.Time
	writes   int
	// deadlineWaits counts native writes entered before their write deadline that
	// returned a timeout: the socket kept the writer waiting until the deadline.
	deadlineWaits, longWrites int
	maxWrite                  time.Duration
	errors                    [len(nativeDarwinErrorClasses)]int
}

func (o *nativeDarwinWriterObserver) SetWriteDeadline(deadline time.Time) error {
	o.deadline = deadline
	return o.native.SetWriteDeadline(deadline)
}

func (o *nativeDarwinWriterObserver) WriteMsgUDPAddrPort(b, oob []byte, addr netip.AddrPort) (int, int, error) {
	start := time.Now()
	n, oobn, err := o.native.WriteMsgUDPAddrPort(b, oob, addr)
	took := time.Since(start)
	o.writes++
	o.maxWrite = max(o.maxWrite, took)
	if took >= endpointTolerance {
		o.longWrites++
	}
	if err != nil {
		class := nativeDarwinErrorClass(err)
		o.errors[class]++
		if nativeDarwinErrorClasses[class] == "deadline" && !o.deadline.IsZero() && start.Before(o.deadline) {
			o.deadlineWaits++
		}
	}
	return n, oobn, err
}

func nativeDarwinErrorClass(err error) int {
	var timeout net.Error
	switch {
	case errors.Is(err, syscall.ENOBUFS):
		return 0
	case errors.Is(err, syscall.EAGAIN), errors.Is(err, syscall.EWOULDBLOCK):
		return 1
	case errors.Is(err, syscall.EMSGSIZE):
		return 2
	case errors.Is(err, os.ErrDeadlineExceeded), errors.As(err, &timeout) && timeout.Timeout():
		return 3
	default:
		return 4
	}
}

func (o *nativeDarwinWriterObserver) facts() map[string]any {
	classes := map[string]any{}
	for i, name := range nativeDarwinErrorClasses {
		classes[name] = o.errors[i]
	}
	return map[string]any{
		"writes": o.writes, "max_write_ns": o.maxWrite.Nanoseconds(), "long_writes": o.longWrites,
		"deadline_waits": o.deadlineWaits, "errors": classes,
	}
}

// nativeDarwinLane is one lane's offered load and what came back from it.
type nativeDarwinLane struct {
	// Every offer is admitted, refused for capacity, or closed.
	offers, admitted, refused, closed int
	// Every admitted request publishes a result the producer takes, or is withdrawn
	// when its participant detaches first.
	results, withdrawn int
	// Datagram outcomes across the taken results, and the results with a failure.
	accepted, uncertain, unsubmitted, failed int
	// Publication diagnostics the endpoint delivered to the fixture's sink.
	diagnostics int
	// Admitted requests not yet taken, and their peak.
	occupancy, maxOccupancy int
	// The longest time from a natively attempted member's return to the producer
	// taking its result: an upper bound on the time to publication. A native size
	// error counts as attempted; members that ended locally, such as queued expiry
	// or an untouched suffix, add no sample.
	nativeReturnToTake time.Duration
}

func (l *nativeDarwinLane) facts(participant int, name string) map[string]any {
	return map[string]any{
		"participant": participant, "lane": name,
		"offers": l.offers, "admitted": l.admitted, "refused": l.refused, "closed": l.closed,
		"results": l.results, "withdrawn": l.withdrawn,
		"accepted": l.accepted, "uncertain": l.uncertain, "unsubmitted": l.unsubmitted, "failed": l.failed,
		"diagnostics": l.diagnostics, "occupancy_max": l.maxOccupancy, "native_return_to_take_max_ns": l.nativeReturnToTake.Nanoseconds(),
	}
}

// nativeDarwinProducer offers one participant's load on its three lanes and takes
// its results. It owns each refused head until admission or teardown.
type nativeDarwinProducer struct {
	load         nativeDarwinLoad
	endpoint     *nativeEndpoint
	participant  *endpointParticipant
	destination  netip.AddrPort
	lanes        [3]nativeDarwinLane
	heads        [3]*endpointRequest
	registration [3]uint64
	occupancy    int
	maxOccupancy int
	// owned counts payload buffers this producer holds outside the endpoint.
	owned int
	// finished is set only when the whole load was taken inside the live window.
	finished   bool
	unexpected error
}

func (p *nativeDarwinProducer) head(lane int) *endpointRequest {
	if p.heads[lane] == nil {
		p.registration[lane]++
		request := &endpointRequest{
			identity:    endpointIdentity{connection: p.participant.id, path: uint64(lane), registration: p.registration[lane]},
			destination: p.destination,
		}
		for range p.load.members {
			buffer := getPacketBuffer()
			buffer.Data = append(buffer.Data, make([]byte, p.load.payload)...)
			request.members = append(request.members, endpointMember{buffer: buffer})
			p.owned++
		}
		p.heads[lane] = request
	}
	return p.heads[lane]
}

// collect takes every published result; it reports whether there was one.
func (p *nativeDarwinProducer) collect() bool {
	took := false
	for {
		result, ok := p.endpoint.take(p.participant)
		if !ok {
			return took
		}
		took = true
		p.occupancy--
		p.lanes[result.identity.path].take(result, monotime.Now())
	}
}

// take counts one result the producer took at now.
func (l *nativeDarwinLane) take(result endpointResult, now monotime.Time) {
	l.results++
	l.occupancy--
	if result.failure() != nil {
		l.failed++
	}
	for _, member := range result.members {
		l.accepted += member.accepted
		l.uncertain += member.uncertain
		l.unsubmitted += member.unsubmitted
		if member.accepted+member.uncertain > 0 || errors.Is(member.err, syscall.EMSGSIZE) {
			l.nativeReturnToTake = max(l.nativeReturnToTake, now.Sub(member.returnedAt))
		}
	}
}

// offer offers each unfinished lane's head once; it reports whether one was
// admitted and whether the endpoint closed.
func (p *nativeDarwinProducer) offer() (admitted, closed bool) {
	for i := range p.lanes {
		lane := &p.lanes[i]
		if lane.admitted == p.load.requests {
			continue
		}
		head := p.head(i)
		lane.offers++
		switch err := p.endpoint.offer(p.participant, i, *head); {
		case err == nil:
			lane.admitted++
			lane.occupancy++
			lane.maxOccupancy = max(lane.maxOccupancy, lane.occupancy)
			p.owned -= len(head.members)
			p.heads[i] = nil
			p.occupancy++
			p.maxOccupancy = max(p.maxOccupancy, p.occupancy)
			admitted = true
		case errors.Is(err, errEndpointCapacity):
			lane.refused++
		case errors.Is(err, net.ErrClosed):
			lane.closed++
			return admitted, true
		default:
			lane.closed++
			p.unexpected = err
			return admitted, true
		}
	}
	return admitted, false
}

func (p *nativeDarwinProducer) done() bool {
	for i := range p.lanes {
		if p.lanes[i].admitted != p.load.requests {
			return false
		}
	}
	return p.occupancy == 0
}

// run offers the load until it is finished, interrupted or closed, then settles
// everything it owns and detaches. A refused lane waits for the endpoint's
// readiness or completion signal, or at most one endpoint lease, before the
// producer offers its unfinished lanes again; each refusal it counts is a real
// capacity response.
func (p *nativeDarwinProducer) run(ctx context.Context) {
	fallback := time.NewTimer(endpointLease)
	defer fallback.Stop()
	for ctx.Err() == nil {
		took := p.collect()
		if p.done() {
			p.finished = nativeDarwinInWindow(ctx, time.Now())
			break
		}
		admitted, closed := p.offer()
		if closed {
			break
		}
		if took || admitted {
			continue
		}
		fallback.Reset(endpointLease)
		select {
		case <-ctx.Done():
		case <-p.participant.ready:
		case <-p.participant.completed:
		case <-fallback.C:
		}
	}
	p.collect()
	for i, head := range p.heads {
		if head == nil {
			continue
		}
		for _, member := range head.members {
			member.buffer.Release()
			p.owned--
		}
		p.heads[i] = nil
		p.endpoint.cancelReadiness(p.participant, i)
	}
	// Detaching withdraws what is still queued or unpublished and returns once the
	// endpoint holds nothing of this participant's, including a current borrow.
	<-p.endpoint.detach(p.participant)
	for i := range p.lanes {
		lane := &p.lanes[i]
		lane.withdrawn = lane.admitted - lane.results
	}
}

// nativeDarwinInWindow decides whether work that completed by now finished inside
// the load window. It compares now with the window's deadline itself, since the
// context's cancellation callback can run late, and a canceled context is never in
// the window. The producer samples now after its last take returned.
func nativeDarwinInWindow(ctx context.Context, now time.Time) bool {
	deadline, ok := ctx.Deadline()
	return ctx.Err() == nil && ok && now.Before(deadline)
}

// nativeDarwinDiagnostics counts the endpoint's publication diagnostics per lane.
// The endpoint's bounded queue drops what the sink can't take; hook, when set,
// runs first and may stall the sink to show that.
type nativeDarwinDiagnostics struct {
	mutex  sync.Mutex
	counts map[[2]uint64]int
	hook   func()
}

func (d *nativeDarwinDiagnostics) sink(diagnostic endpointDiagnostic) {
	if d.hook != nil {
		d.hook()
	}
	d.mutex.Lock()
	defer d.mutex.Unlock()
	d.counts[[2]uint64{diagnostic.identity.connection, diagnostic.identity.path}]++
}

func (d *nativeDarwinDiagnostics) count(participant *endpointParticipant, lane int) int {
	d.mutex.Lock()
	defer d.mutex.Unlock()
	return d.counts[[2]uint64{participant.id, uint64(lane)}]
}

// nativeDarwinObservation is one contention or pressure observation.
type nativeDarwinObservation struct {
	load        nativeDarwinLoad
	producers   []*nativeDarwinProducer
	writer      *nativeDarwinWriterObserver
	dropped     uint64
	fault       string
	status      string
	pressure    string
	unexpected  error
	owned       int
	endpointCap [2]int // records and bytes the endpoint still charged after its join
	// detached counts the participants detached after a failed attach, before any
	// producer started.
	detached int
}

// Observation statuses. Only a complete observation can report that no pressure
// wait occurred; an incomplete or interrupted one reports that as unknown.
const (
	nativeDarwinComplete           = "complete"
	nativeDarwinIncompleteCoverage = "incomplete-coverage"
	nativeDarwinInterrupted        = "interrupted"
)

var nativeDarwinFaults = map[endpointFaultCause]string{
	endpointFaultOverdue: "overdue", endpointFaultLateReturn: "late-return", endpointFaultNative: "native",
}

// observeNativeDarwinContention starts the endpoint's real writer over native,
// attaches every participant, then offers load from one producer per participant
// and returns the observation. If an attach fails, no producer starts: the
// attached participants are detached and the observation carries the attach
// error. It joins every producer, then the writer, and then waits up to the
// endpoint's tolerance for the diagnostic sink's backlog, which touches only the
// fixture's counts, before it returns; the caller still owns native and closes it
// afterward. attached, when set, runs after each participant attaches.
func observeNativeDarwinContention(ctx context.Context, native endpointNativeIO, destination netip.AddrPort, load nativeDarwinLoad, hook func(), attached func(participant int)) nativeDarwinObservation {
	ctx, cancel := context.WithTimeout(ctx, load.window)
	defer cancel()
	writer := &nativeDarwinWriterObserver{native: native}
	diagnostics := &nativeDarwinDiagnostics{counts: map[[2]uint64]int{}, hook: hook}
	e := startNativeEndpoint(writer, load.budget, diagnostics.sink)
	observation := nativeDarwinObservation{load: load, writer: writer, fault: "none"}
	// Every participant attaches before any producer offers, so the declared load is
	// what runs from the first offer, and a refused attach is a setup failure.
	for i := range load.participants {
		participant, err := e.attach(uint64(i + 1))
		if err != nil {
			observation.unexpected = err
			break
		}
		observation.producers = append(observation.producers, &nativeDarwinProducer{load: load, endpoint: e, participant: participant, destination: destination})
		if attached != nil {
			attached(i)
		}
	}
	if observation.unexpected == nil {
		// One barrier releases the producers together.
		start := make(chan struct{})
		var wg sync.WaitGroup
		for _, producer := range observation.producers {
			wg.Go(func() {
				<-start
				producer.run(ctx)
			})
		}
		close(start)
		wg.Wait()
	} else {
		// No producer started, so none offered; detach what attached.
		for _, producer := range observation.producers {
			<-e.detach(producer.participant)
			observation.detached++
		}
	}
	<-e.stop() // the join orders every read of endpoint state below
	observation.endpointCap = [2]int{e.state.count, e.state.bytes}
	select {
	case <-e.fault:
		observation.fault = nativeDarwinFaults[e.faultRecord.cause]
	default:
	}

	// The sink runs outside the native fence. Give its backlog the endpoint's
	// tolerance to drain, then count what it delivered; a drop or a lag is missing
	// observer coverage.
	settled := time.Now().Add(endpointTolerance)
	for {
		covered := true
		for _, producer := range observation.producers {
			for lane := range producer.lanes {
				if diagnostics.count(producer.participant, lane) < producer.lanes[lane].results {
					covered = false
				}
			}
		}
		if covered || !time.Now().Before(settled) {
			break
		}
		time.Sleep(time.Millisecond)
	}
	observation.dropped = e.dropped.Load()
	for _, producer := range observation.producers {
		observation.owned += producer.owned
		if producer.unexpected != nil && observation.unexpected == nil {
			observation.unexpected = producer.unexpected
		}
		for i := range producer.lanes {
			producer.lanes[i].diagnostics = diagnostics.count(producer.participant, i)
		}
	}
	observation.derive()
	return observation
}

// derive is the one status and pressure-wait decision. Only a load that every
// producer finished inside its window, on an endpoint that never faulted, with
// every request taken and every publication observed, is complete; only a
// complete observation can report that no pressure wait occurred.
func (o *nativeDarwinObservation) derive() {
	loadComplete, coverageComplete := o.unexpected == nil && o.fault == "none", o.dropped == 0
	for _, producer := range o.producers {
		if !producer.finished {
			loadComplete = false
		}
		for _, lane := range producer.lanes {
			if lane.admitted != o.load.requests || lane.withdrawn != 0 {
				loadComplete = false
			}
			if lane.diagnostics != lane.results {
				coverageComplete = false
			}
		}
	}
	switch {
	case !loadComplete:
		o.status = nativeDarwinInterrupted
	case !coverageComplete:
		o.status = nativeDarwinIncompleteCoverage
	default:
		o.status = nativeDarwinComplete
	}
	switch {
	case o.writer.deadlineWaits > 0:
		o.pressure = "observed"
	case o.status == nativeDarwinComplete:
		o.pressure = "not-observed"
	default:
		o.pressure = "unknown"
	}
}

func (o nativeDarwinObservation) unfinished() int {
	n := 0
	for _, producer := range o.producers {
		if !producer.finished {
			n++
		}
	}
	return n
}

func (o nativeDarwinObservation) facts(facts map[string]any) {
	var lanes []any
	var occupancy []any
	for i, producer := range o.producers {
		for lane, name := range nativeDarwinLaneNames {
			lanes = append(lanes, producer.lanes[lane].facts(i, name))
		}
		occupancy = append(occupancy, producer.maxOccupancy)
	}
	facts["status"] = o.status
	facts["pressure_wait"] = o.pressure
	facts["fault"] = o.fault
	facts["unfinished_participants"] = o.unfinished()
	facts["diagnostics_dropped"] = int(o.dropped)
	facts["load"] = o.load.facts()
	facts["writer"] = o.writer.facts()
	facts["lanes"] = lanes
	facts["participant_occupancy_max"] = occupancy
}

// requireSettled checks the fixture's own bookkeeping: every buffer it made is
// released or handed over, the endpoint charges nothing after its join, and each
// lane's offers and datagrams add up. It asserts nothing about native pressure.
func (o nativeDarwinObservation) requireSettled(t *testing.T) {
	t.Helper()
	require.NoError(t, o.unexpected)
	require.Zero(t, o.owned, "producer-owned buffers outstanding")
	require.Equal(t, [2]int{}, o.endpointCap, "records and bytes still charged after the join")
	require.Len(t, o.producers, o.load.participants)
	writes, admitted := 0, 0
	for _, producer := range o.producers {
		for i, lane := range producer.lanes {
			name := nativeDarwinLaneNames[i]
			require.Equal(t, lane.offers, lane.admitted+lane.refused+lane.closed, name)
			require.Equal(t, lane.admitted, lane.results+lane.withdrawn, name)
			require.Equal(t, lane.results*o.load.members, lane.accepted+lane.uncertain+lane.unsubmitted, name)
			writes += lane.accepted + lane.uncertain
			admitted += lane.admitted
		}
	}
	require.GreaterOrEqual(t, o.writer.writes, writes, "every accepted or uncertain datagram had a native write")
	// The producer's members are scalar datagrams with no write state, so neither a
	// first-send retry nor segmentation applies: at most one write per admitted member.
	require.LessOrEqual(t, o.writer.writes, admitted*o.load.members, "more native writes than admitted members")
}

// nativeDarwinGatedIO is the synthetic native side: each write waits for a permit
// or returns the next injected error. Only the endpoint's writer calls it.
type nativeDarwinGatedIO struct {
	permits  chan struct{}
	fail     func() error
	deadline time.Time
	// writes counts the writes the writer has entered.
	writes atomic.Int64
}

func (n *nativeDarwinGatedIO) SetWriteDeadline(deadline time.Time) error {
	n.deadline = deadline
	return nil
}

func (n *nativeDarwinGatedIO) WriteMsgUDPAddrPort(b, _ []byte, _ netip.AddrPort) (int, int, error) {
	n.writes.Add(1)
	if n.permits != nil {
		<-n.permits
	}
	if n.fail != nil {
		if err := n.fail(); err != nil {
			return 0, 0, err
		}
	}
	return len(b), 0, nil
}

var nativeDarwinSyntheticDestination = netip.MustParseAddrPort("127.0.0.1:443")

// TestNativeDarwinContentionAccounting is the synthetic scalar contention case: it
// runs the fixture's real producers, writer observer and diagnostic sink over a
// gated native side so that every participant contends for admission. It shows
// real progress, refused lanes and a valid negative pressure-wait result, without
// asserting anything about native pressure.
func TestNativeDarwinContentionAccounting(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		load := nativeDarwinLoad{participants: 3, requests: 6, members: 2, payload: 1200, budget: time.Second, window: time.Minute}
		permits := make(chan struct{})
		native := &nativeDarwinGatedIO{permits: permits}
		done := make(chan nativeDarwinObservation)
		go func() {
			done <- observeNativeDarwinContention(t.Context(), native, nativeDarwinSyntheticDestination, load, nil, nil)
		}()
		// Hold the writer until the producers stop being admitted.
		synctest.Wait()
		close(permits)
		observation := <-done
		observation.requireSettled(t)
		require.Equal(t, nativeDarwinComplete, observation.status)
		require.Equal(t, "not-observed", observation.pressure, "a complete observation without a deadline wait is a valid negative")
		require.Equal(t, "none", observation.fault)
		require.Zero(t, observation.dropped)
		refused := 0
		for _, producer := range observation.producers {
			require.Equal(t, 4, producer.maxOccupancy, "a participant holds at most four requests")
			for i, lane := range producer.lanes {
				require.Positive(t, lane.maxOccupancy, nativeDarwinLaneNames[i])
				require.LessOrEqual(t, lane.maxOccupancy, producer.maxOccupancy, nativeDarwinLaneNames[i])
				require.Equal(t, load.requests, lane.results, nativeDarwinLaneNames[i])
				require.Equal(t, load.requests*load.members, lane.accepted, "real progress on every lane")
				require.Equal(t, lane.results, lane.diagnostics, "every publication observed")
				refused += lane.refused
			}
		}
		require.Positive(t, refused, "the held writer refused lanes")
		require.Equal(t, 3*load.participants*load.requests*load.members, observation.writer.writes)
	})
}

// TestNativeDarwinContentionObservations distinguishes the observation outcomes the
// fixture can report, over the synthetic native side.
func TestNativeDarwinContentionObservations(t *testing.T) {
	load := nativeDarwinLoad{participants: 2, requests: 3, members: 2, payload: 1200, budget: time.Second, window: time.Minute}

	t.Run("immediate ENOBUFS", func(t *testing.T) {
		synctest.Test(t, func(t *testing.T) {
			failures := 2
			native := &nativeDarwinGatedIO{fail: func() error {
				if failures == 0 {
					return nil
				}
				failures--
				return &os.SyscallError{Syscall: "sendmsg", Err: syscall.ENOBUFS}
			}}
			observation := observeNativeDarwinContention(t.Context(), native, nativeDarwinSyntheticDestination, load, nil, nil)
			observation.requireSettled(t)
			require.Equal(t, nativeDarwinComplete, observation.status)
			require.Equal(t, 2, observation.writer.errors[0], "immediate ENOBUFS")
			require.Zero(t, observation.writer.deadlineWaits)
			require.Equal(t, "not-observed", observation.pressure, "an immediate local error is not a pressure wait")
			uncertain, failed := 0, 0
			for _, producer := range observation.producers {
				for _, lane := range producer.lanes {
					uncertain += lane.uncertain
					failed += lane.failed
				}
			}
			require.Equal(t, 2, uncertain, "the endpoint reports an ENOBUFS write as uncertain")
			require.Equal(t, 2, failed)
		})
	})

	t.Run("pressure wait", func(t *testing.T) {
		synctest.Test(t, func(t *testing.T) {
			// The synthetic socket keeps the first write waiting until its deadline,
			// as a full send buffer would, and then times out.
			waited := false
			native := &nativeDarwinGatedIO{}
			native.fail = func() error {
				if waited {
					return nil
				}
				waited = true
				time.Sleep(time.Until(native.deadline))
				return os.ErrDeadlineExceeded
			}
			observation := observeNativeDarwinContention(t.Context(), native, nativeDarwinSyntheticDestination, load, nil, nil)
			observation.requireSettled(t)
			require.Equal(t, 1, observation.writer.deadlineWaits)
			require.Equal(t, "observed", observation.pressure)
			require.Equal(t, "none", observation.fault, "a return at the deadline is within the endpoint's tolerance")
		})
	})

	t.Run("missing observer coverage", func(t *testing.T) {
		synctest.Test(t, func(t *testing.T) {
			// A stalled sink cannot hold the writer: the endpoint drops diagnostics
			// beyond its bounded queue, and the observation says so.
			release := make(chan struct{})
			defer close(release)
			wide := nativeDarwinLoad{participants: 8, requests: 8, members: 1, payload: 1200, budget: time.Second, window: time.Minute}
			observation := observeNativeDarwinContention(t.Context(), &nativeDarwinGatedIO{}, nativeDarwinSyntheticDestination, wide, func() { <-release }, nil)
			observation.requireSettled(t)
			require.Positive(t, observation.dropped)
			require.Equal(t, nativeDarwinIncompleteCoverage, observation.status)
			require.Equal(t, "unknown", observation.pressure, "an incomplete observation makes no negative claim")
			for _, producer := range observation.producers {
				for _, lane := range producer.lanes {
					require.Equal(t, wide.requests, lane.results, "the load itself completed")
				}
			}
		})
	})

	t.Run("interrupted load", func(t *testing.T) {
		synctest.Test(t, func(t *testing.T) {
			permits := make(chan struct{})
			native := &nativeDarwinGatedIO{permits: permits}
			ctx, cancel := context.WithCancel(t.Context())
			done := make(chan nativeDarwinObservation)
			go func() {
				done <- observeNativeDarwinContention(ctx, native, nativeDarwinSyntheticDestination, load, nil, nil)
			}()
			synctest.Wait()
			cancel()
			// The producers stop offering and detach; detaching waits for the current
			// borrow, so the observation returns only after its native write does.
			synctest.Wait()
			select {
			case <-done:
				t.Fatal("teardown returned while the writer still held a borrow")
			default:
			}
			close(permits)
			observation := <-done
			observation.requireSettled(t)
			require.Equal(t, nativeDarwinInterrupted, observation.status)
			require.Equal(t, "unknown", observation.pressure)
			withdrawn := 0
			for _, producer := range observation.producers {
				for _, lane := range producer.lanes {
					withdrawn += lane.withdrawn
				}
			}
			require.Positive(t, withdrawn, "queued work was withdrawn")
		})
	})

	t.Run("endpoint fault", func(t *testing.T) {
		synctest.Test(t, func(t *testing.T) {
			// The first write returns well after its deadline: the endpoint faults and
			// publishes the queued work as local failures. Every request is admitted and
			// taken, yet the load did not complete.
			one := nativeDarwinLoad{participants: 1, requests: 1, members: 1, payload: 1200, budget: time.Second, window: time.Minute}
			late := true
			native := &nativeDarwinGatedIO{}
			native.fail = func() error {
				if late {
					late = false
					time.Sleep(time.Until(native.deadline.Add(endpointTolerance + 30*time.Millisecond)))
				}
				return nil
			}
			observation := observeNativeDarwinContention(t.Context(), native, nativeDarwinSyntheticDestination, one, nil, nil)
			observation.requireSettled(t)
			require.NotEqual(t, "none", observation.fault)
			attempted := 0
			for _, lane := range observation.producers[0].lanes {
				require.Equal(t, 1, lane.results, "every request was taken")
				if lane.accepted+lane.uncertain == 0 {
					require.Zero(t, lane.nativeReturnToTake, "work that ended locally adds no native-return sample")
				} else {
					attempted++
				}
			}
			require.Equal(t, 1, attempted, "only the late write reached the socket")
			require.Equal(t, nativeDarwinInterrupted, observation.status)
			require.Equal(t, "unknown", observation.pressure)
		})
	})

	t.Run("every participant attaches before any offer", func(t *testing.T) {
		synctest.Test(t, func(t *testing.T) {
			native := &nativeDarwinGatedIO{}
			var writes []int64
			observation := observeNativeDarwinContention(t.Context(), native, nativeDarwinSyntheticDestination, load, nil, func(int) {
				// Any producer already started runs until it blocks; an admitted offer
				// reaches the ungated writer.
				synctest.Wait()
				writes = append(writes, native.writes.Load())
			})
			require.Equal(t, make([]int64, load.participants), writes, "native writes as each participant attached")
			observation.requireSettled(t)
			require.Equal(t, nativeDarwinComplete, observation.status)
		})
	})

	t.Run("a refused attach offers nothing", func(t *testing.T) {
		synctest.Test(t, func(t *testing.T) {
			// One participant more than the endpoint holds: it refuses the last attach.
			full := nativeDarwinLoad{participants: endpointParticipants + 1, requests: 1, members: 1, payload: 1200, budget: time.Second, window: time.Minute}
			native := &nativeDarwinGatedIO{}
			observation := observeNativeDarwinContention(t.Context(), native, nativeDarwinSyntheticDestination, full, nil, nil)
			require.ErrorIs(t, observation.unexpected, errEndpointCapacity, "the attach error is the observation's")
			require.Zero(t, native.writes.Load(), "nothing was written")
			require.Len(t, observation.producers, endpointParticipants)
			for _, producer := range observation.producers {
				for _, lane := range producer.lanes {
					require.Zero(t, lane.offers, "no producer offered")
				}
			}
			require.Equal(t, endpointParticipants, observation.detached, "every attached participant was detached")
			require.Equal(t, [2]int{}, observation.endpointCap, "the joined endpoint charges nothing")
			require.Equal(t, nativeDarwinInterrupted, observation.status)
		})
	})

	t.Run("a fault after every attach is interrupted, not an attach error", func(t *testing.T) {
		synctest.Test(t, func(t *testing.T) {
			three := nativeDarwinLoad{participants: 3, requests: 2, members: 1, payload: 1200, budget: time.Second, window: time.Minute}
			// The first write finds the socket gone, which faults the endpoint.
			native := &nativeDarwinGatedIO{fail: func() error { return &os.SyscallError{Syscall: "sendmsg", Err: syscall.EBADF} }}
			observation := observeNativeDarwinContention(t.Context(), native, nativeDarwinSyntheticDestination, three, nil, func(int) { synctest.Wait() })
			observation.requireSettled(t)
			require.Equal(t, "native", observation.fault)
			require.Equal(t, nativeDarwinInterrupted, observation.status)
			require.Equal(t, "unknown", observation.pressure)
		})
	})

	t.Run("native return timing", func(t *testing.T) {
		// Only natively attempted members sample the return-to-take interval; work
		// that ended locally carries a local decision time, not a native return.
		now := monotime.Now()
		var lane nativeDarwinLane
		lane.take(endpointResult{members: []endpointMemberResult{
			{accepted: 1, returnedAt: now.Add(-3 * time.Millisecond)},
			{unsubmitted: 1, err: os.ErrDeadlineExceeded, returnedAt: now.Add(-9 * time.Millisecond)},
		}}, now)
		require.Equal(t, 3*time.Millisecond, lane.nativeReturnToTake)
		lane.take(endpointResult{members: []endpointMemberResult{
			{uncertain: 1, err: syscall.ENOBUFS, returnedAt: now.Add(-5 * time.Millisecond)},
		}}, now)
		require.Equal(t, 5*time.Millisecond, lane.nativeReturnToTake)
		// A native size error leaves its member unsubmitted, but the socket returned it.
		lane.take(endpointResult{members: []endpointMemberResult{
			{unsubmitted: 1, err: &os.SyscallError{Syscall: "sendmsg", Err: syscall.EMSGSIZE}, returnedAt: now.Add(-7 * time.Millisecond)},
		}}, now)
		require.Equal(t, 7*time.Millisecond, lane.nativeReturnToTake)
		require.Equal(t, [4]int{3, 1, 1, 2}, [4]int{lane.results, lane.accepted, lane.uncertain, lane.unsubmitted})
	})

	t.Run("completion against the window", func(t *testing.T) {
		now := time.Now()
		live, cancel := context.WithDeadline(context.Background(), now.Add(time.Hour))
		defer cancel()
		require.True(t, nativeDarwinInWindow(live, now))
		require.False(t, nativeDarwinInWindow(live, now.Add(time.Hour)), "a take at the deadline is outside the window")
		// The deadline has passed but its cancellation callback hasn't run yet.
		require.False(t, nativeDarwinInWindow(nativeDarwinLateTimer{deadline: now}, now.Add(time.Millisecond)))
		require.True(t, nativeDarwinInWindow(nativeDarwinLateTimer{deadline: now}, now.Add(-time.Millisecond)))
		canceled, cancelNow := context.WithDeadline(context.Background(), now.Add(time.Hour))
		cancelNow()
		require.False(t, nativeDarwinInWindow(canceled, now), "a canceled load is not in its window")
		require.False(t, nativeDarwinInWindow(context.Background(), now), "a load has a window")
	})

	t.Run("finished outside the window", func(t *testing.T) {
		// The status decision alone: a producer whose last result was drained during
		// cleanup, after its window ended, has full counts but did not finish in time.
		lanes := [3]nativeDarwinLane{}
		for i := range lanes {
			lanes[i] = nativeDarwinLane{admitted: 1, results: 1, diagnostics: 1}
		}
		observation := nativeDarwinObservation{
			load: nativeDarwinLoad{participants: 1, requests: 1, members: 1}, writer: &nativeDarwinWriterObserver{}, fault: "none",
			producers: []*nativeDarwinProducer{{lanes: lanes}},
		}
		observation.derive()
		require.Equal(t, nativeDarwinInterrupted, observation.status)
		require.Equal(t, "unknown", observation.pressure)
		require.Equal(t, 1, observation.unfinished())
		observation.producers[0].finished = true
		observation.derive()
		require.Equal(t, nativeDarwinComplete, observation.status)
		require.Equal(t, "not-observed", observation.pressure)
	})
}

// nativeDarwinContentionCase is the native scalar contention case: the bounded
// development load on a real loopback socket. The record keeps every lane's
// offers, refusals, occupancy, outcomes and publication lag, and the writer's
// observations. It is smoke evidence for the method; whatever pressure it saw or
// didn't see is an observation, not an assertion.
func nativeDarwinContentionCase(t *testing.T, facts map[string]any) {
	load := nativeDarwinLoad{participants: 3, requests: 8, members: 2, payload: 1200, budget: time.Second, window: scaleDuration(10 * time.Second)}
	observation := observeNativeDarwinLoopback(t, load)
	observation.requireSettled(t)
	require.Equal(t, nativeDarwinComplete, observation.status)
	require.Equal(t, "none", observation.fault)
	for _, producer := range observation.producers {
		for i, lane := range producer.lanes {
			require.Positive(t, lane.accepted, "real progress on %s", nativeDarwinLaneNames[i])
		}
	}
	observation.facts(facts)
}

// observeNativeDarwinLoopback offers load from an unconnected loopback socket to a
// peer socket. Both sockets close only after the observation has joined the
// endpoint, so no write can reach a released socket.
func observeNativeDarwinLoopback(t *testing.T, load nativeDarwinLoad) nativeDarwinObservation {
	t.Helper()
	socket := nativeDarwinListen("udp4", net.IPv4(127, 0, 0, 1))(t)
	peer := nativeDarwinListen("udp4", net.IPv4(127, 0, 0, 1))(t)
	require.Nil(t, socket.RemoteAddr(), "the endpoint requires an unconnected socket")
	return observeNativeDarwinContention(t.Context(), socket, peer.LocalAddr().(*net.UDPAddr).AddrPort(), load, nil, nil)
}

// nativeDarwinLateTimer is a context whose deadline has passed before its
// cancellation ran.
type nativeDarwinLateTimer struct {
	context.Context
	deadline time.Time
}

func (c nativeDarwinLateTimer) Deadline() (time.Time, bool) { return c.deadline, true }
func (nativeDarwinLateTimer) Err() error                    { return nil }
