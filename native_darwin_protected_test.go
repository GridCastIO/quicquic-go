//go:build darwin

package quic

import (
	"bytes"
	"net/netip"
	"os"
	"sync"
	"testing"
	"testing/synctest"
	"time"

	"github.com/GridCastIO/quicquic-go/internal/handshake"
	"github.com/GridCastIO/quicquic-go/internal/monotime"
	"github.com/GridCastIO/quicquic-go/internal/protocol"
	"github.com/GridCastIO/quicquic-go/internal/wire"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"
)

// nativeDarwinProtectedSendBuffer is the send buffer the protected-member case's
// socket requests: one standard-size packet, so a protected 1-RTT packet of exactly
// the read-back capacity B is an ordinary packet of the connection.
const nativeDarwinProtectedSendBuffer = 1200

// nativeDarwinProtected is a test connection whose native ordinary sender writes
// through a given endpoint. With deferred protection its 1-RTT sealer is constructor
// proven, so production construction attaches a native protection plan; otherwise
// the transparent mock sealer leaves packets without one.
type nativeDarwinProtected struct {
	controller string
	conn       *Conn
	sender     *nativeOrdinarySender
	sealer     handshake.ShortHeaderSealer
	opener     handshake.ShortHeaderOpener
}

func newNativeDarwinProtected(t *testing.T, controller string, e *nativeEndpoint, destination netip.AddrPort, deferred bool) *nativeDarwinProtected {
	t.Helper()
	config := &Config{InitialPacketSize: 1200, EnableDatagrams: true}
	require.NoError(t, config.SetCongestionControlV1(controller))
	tc := newConfiguredEmissionTestConnection(t, false, config)
	c := tc.conn
	c.rttStats.UpdateRTT(5*time.Millisecond, 0)
	p := &nativeDarwinProtected{controller: controller, conn: c}
	if deferred {
		p.sealer, p.opener = nativeProtectionTestCrypto(t, protocol.Version1)
		require.True(t, handshake.CanReservePacketProtection(p.sealer), "the case needs the deferred protection capability; it never skips")
	} else {
		p.sealer = newMockShortHeaderSealer(gomock.NewController(t))
	}
	sealing := NewMockSealingManager(gomock.NewController(t))
	sealing.EXPECT().Get1RTTSealer().Return(p.sealer, nil).AnyTimes()
	c.emission.packer.cryptoSetup = sealing
	require.NoError(t, c.useNativeOrdinary(e, destination, packetInfo{}))
	p.sender = c.emission.local.(*nativeOrdinarySender)
	t.Cleanup(p.sender.Close)
	return p
}

// nativeDarwinProtectedMember is what the case knows of one handed-off member before
// the sender offers it: its storage, plan and recipe, whether the writer had yet to
// apply the plan, whether it carried BBR reservation credit, its deadline, and the
// DATAGRAM payload byte its plaintext repeats.
type nativeDarwinProtectedMember struct {
	record   *ordinaryLocalRecord
	buffer   *packetBuffer
	plan     *nativeProtectionPlan
	recipe   nativeProtectionRecipe
	deferred bool
	credit   bool
	oob      []byte
	deadline time.Time
	fill     byte
}

func (m nativeDarwinProtectedMember) match(member endpointMember) bool {
	return member.buffer == m.buffer && member.protection == m.plan
}

// member constructs one 1-RTT packet of exactly size bytes, carrying one DATAGRAM
// frame of fill bytes, through production construction and handoff, as one member
// of a new local record. It does not offer the record: finish does.
func (p *nativeDarwinProtected) member(t *testing.T, size int, ecn protocol.ECN, fill byte) nativeDarwinProtectedMember {
	t.Helper()
	e := &p.conn.emission
	now := monotime.Now()
	if e.bbr != nil {
		require.True(t, e.reserveLocal(protocol.ByteCount(size), true, false, now), "the BBR credit admits one packet")
	}
	buffer := getPacketBuffer()
	require.True(t, p.sender.reserveBuffer(buffer.Cap()).available)
	_, pnLen := p.sender.recovery.PeekPacketNumber(protocol.Encryption1RTT)
	// A DATAGRAM frame with a length: one type byte and a two-byte length.
	payload := size - int(wire.ShortHeaderLen(p.conn.connIDManager.Get(), pnLen)) - p.sealer.Overhead() - 3
	require.NoError(t, p.conn.datagramQueue.Add(&wire.DatagramFrame{DataLenPresent: true, Data: bytes.Repeat([]byte{fill}, payload)}))
	var construction nativeProtectionConstruction
	construction.begin(e, buffer)
	receipt, err := e.appendPacketProtected(buffer, protocol.ByteCount(size), false, ecn, now, &construction)
	require.NoError(t, err)
	require.EqualValues(t, size, receipt.size)
	e.handoff(buffer, 0, ecn, sendMetadata{}, &construction)
	record := p.sender.pending
	require.NotNil(t, record)
	require.Len(t, record.request.members, 1)
	member := record.request.members[0]
	require.Same(t, buffer, member.buffer)
	m := nativeDarwinProtectedMember{record: record, buffer: buffer, plan: member.protection, credit: member.credit != nil, oob: member.oob, deadline: record.request.deadline, fill: fill}
	if m.plan != nil {
		m.deferred = m.plan.next == 0
		m.recipe = m.plan.entries[0]
	}
	return m
}

// opens reports whether data is the member's ciphertext: the peer's receive path
// accepts it under the peer's opener, with its own header, key phase and packet
// number checks, and its plaintext carries the member's DATAGRAM payload. Bytes the
// peer refuses are not, so the lifetime still names its class. The opener is
// stateful, so the control is opened before the trigger.
func (p *nativeDarwinProtected) opens(m nativeDarwinProtectedMember, data []byte) bool {
	if p.opener == nil || m.plan == nil || len(data) != int(m.recipe.end) {
		return false
	}
	peer := newPacketUnpacker(nil, p.conn.connIDManager.Get().Len())
	_, _, _, plain, err := peer.unpackShortHeaderPacket(p.opener, monotime.Now(), bytes.Clone(data))
	return err == nil && bytes.Contains(plain, bytes.Repeat([]byte{m.fill}, 64))
}

// settle waits for the endpoint's result for m's record and consumes it until the
// sender frees the record.
func (p *nativeDarwinProtected) settle(t *testing.T, m nativeDarwinProtectedMember) {
	t.Helper()
	timeout := time.After(scaleDuration(5 * time.Second))
	for {
		require.NoError(t, p.sender.consume())
		if m.record.state == ordinaryFree {
			return
		}
		select {
		case <-p.sender.completed():
		case <-timeout:
			require.FailNow(t, "the sender never settled the member's record")
		}
	}
}

// nativeDarwinBorrow is one sample of a member's borrow: the writer's current token
// is the member's request and unpublished, the buffer still has its one reference,
// and the plan is still bound to that buffer.
type nativeDarwinBorrow struct {
	sampled, held, buffer, plan bool
}

func (b nativeDarwinBorrow) borrowed() bool { return b.sampled && b.held && b.buffer && b.plan }

// nativeDarwinProtectedSample samples m's borrow under the endpoint lock. On the
// writer this takes the lock as the endpoint's control does; a sample late enough to
// pass the deadline's tolerance makes the endpoint fault the borrow as overdue, which
// keeps it borrowed and fails the case on its fault check.
func nativeDarwinProtectedSample(e *nativeEndpoint, m nativeDarwinProtectedMember) (b nativeDarwinBorrow) {
	e.do(func(s *endpointState) { b = nativeDarwinProtectedBorrow(s, m) })
	return b
}

// nativeDarwinProtectedJoinSample is nativeDarwinProtectedSample with the join's
// state read under the same endpoint lock, so the two are one observation.
func nativeDarwinProtectedJoinSample(e *nativeEndpoint, m nativeDarwinProtectedMember, retired <-chan struct{}) (b nativeDarwinBorrow, joinOpen bool) {
	e.do(func(s *endpointState) {
		b = nativeDarwinProtectedBorrow(s, m)
		select {
		case <-retired:
		default:
			joinOpen = true
		}
	})
	return b, joinOpen
}

// nativeDarwinProtectedBorrow is m's borrow under the endpoint lock.
func nativeDarwinProtectedBorrow(s *endpointState, m nativeDarwinProtectedMember) (b nativeDarwinBorrow) {
	token := s.current
	b.sampled = true
	b.held = token != nil && len(token.request.members) == 1 && m.match(token.request.members[0]) && token.completion.Load() == nil
	b.buffer = m.buffer.refCount == 1
	b.plan = m.plan != nil && m.plan.buffer == m.buffer
	return b
}

// nativeDarwinProtectedLifetime is the observation of one protected member's
// storage: what it carried when admitted, the bytes at its native call, its borrow in
// the call, at the native return and after the final deadline reset, and its release
// by the join.
type nativeDarwinProtectedLifetime struct {
	// planned: the admitted member carried a frozen plan that the writer had yet to apply.
	planned bool
	// bbr: a bbrv3 connection built the member with its BBR reservation credit.
	bbr bool
	// ciphertext: the plan was fully applied when the native call began, and the
	// bytes handed to it open under the peer's opener.
	ciphertext             bool
	call, returned, fenced nativeDarwinBorrow
	// released: the buffer and plan had been released when the join fired.
	released bool
}

// class labels the observation. Only a planned BBR member whose ciphertext reached
// the native call and that stayed borrowed in the call, at the native return and
// after the final fence, then was released by the join, is borrowed-through-fence.
// Every other class names the first failure, in this order.
func (l nativeDarwinProtectedLifetime) class() string {
	switch {
	case !l.planned:
		return "unprotected"
	case !l.bbr:
		return "not-bbr"
	case !l.ciphertext:
		return "plaintext-at-native-call"
	case !l.call.borrowed():
		return "released-during-call"
	case !l.returned.borrowed():
		return "released-at-return"
	case !l.fenced.borrowed():
		return "released-before-fence"
	case !l.released:
		return "not-released"
	}
	return "borrowed-through-fence"
}

// nativeDarwinProtectedObserver is the recorder's observe hook for one armed claim. On
// the writer it keeps the bytes handed to the claim's native call, whether the plan
// was fully applied then, the borrow at the native return and after the final
// deadline reset, and whether the join was still open then.
type nativeDarwinProtectedObserver struct {
	mutex   sync.Mutex
	claim   int
	e       *nativeEndpoint
	member  nativeDarwinProtectedMember
	retired <-chan struct{}

	seen nativeDarwinProtectedObservation
}

// nativeDarwinProtectedObservation is what the observer saw on the writer: the bytes
// handed to the armed claim's native call and whether the plan was fully applied
// then, the borrow at the native return and after the final deadline reset, and
// whether the join was still open then.
type nativeDarwinProtectedObservation struct {
	sent             []byte
	applied          bool
	returned, fenced nativeDarwinBorrow
	joinOpenAtFence  bool
}

// lifetime derives m's lifetime from the case's own borrow sample in the call, what
// the observer saw on the writer, and the release the case read after the join.
func (p *nativeDarwinProtected) lifetime(m nativeDarwinProtectedMember, call nativeDarwinBorrow, seen nativeDarwinProtectedObservation, released bool) nativeDarwinProtectedLifetime {
	return nativeDarwinProtectedLifetime{
		planned:    m.plan != nil && m.deferred,
		bbr:        p.controller == "bbrv3" && p.conn.emission.bbr != nil && m.credit,
		ciphertext: seen.applied && p.opens(m, seen.sent),
		call:       call, returned: seen.returned, fenced: seen.fenced, released: released,
	}
}

// arm selects the claim to observe. It precedes the claim's offer.
func (o *nativeDarwinProtectedObserver) arm(claim int, e *nativeEndpoint, member nativeDarwinProtectedMember, retired <-chan struct{}) {
	o.mutex.Lock()
	defer o.mutex.Unlock()
	o.claim, o.e, o.member, o.retired = claim, e, member, retired
}

func (o *nativeDarwinProtectedObserver) observe(claim int, point string, data []byte) {
	o.mutex.Lock()
	defer o.mutex.Unlock()
	if o.e == nil || claim != o.claim {
		return
	}
	switch point {
	case "native-call":
		o.seen.sent = bytes.Clone(data)
		plan := o.member.plan
		o.seen.applied = plan != nil && int(plan.next) == len(plan.entries)
		for i := 0; o.seen.applied && i < len(plan.entries); i++ {
			o.seen.applied = plan.entries[i].protection == (handshake.PacketProtection{})
		}
	case "native-return":
		o.seen.returned = nativeDarwinProtectedSample(o.e, o.member)
	case "fence":
		o.seen.fenced = nativeDarwinProtectedSample(o.e, o.member)
		select {
		case <-o.retired:
		default:
			o.seen.joinOpenAtFence = true
		}
	}
}

// snapshot returns the observation so far.
func (o *nativeDarwinProtectedObserver) snapshot() nativeDarwinProtectedObservation {
	o.mutex.Lock()
	defer o.mutex.Unlock()
	return o.seen
}

// nativeDarwinProtectedReleased reports whether the member's buffer and plan have
// been released. It is read after the join, which follows that release.
func nativeDarwinProtectedReleased(m nativeDarwinProtectedMember) bool {
	return m.buffer.refCount == 0 && m.plan != nil && m.plan.buffer == nil
}

func nativeDarwinAwaitJoin(t *testing.T, retired <-chan struct{}) time.Time {
	t.Helper()
	select {
	case <-retired:
		return time.Now()
	case <-time.After(scaleDuration(5 * time.Second)):
		require.FailNow(t, "the closed sender's participant never retired")
		return time.Time{}
	}
}

// nativeDarwinBBRProtectedCloseJoin is the protocol's D13 A case (#1570), the BBR
// analogue of active-close-join. A bbrv3 connection's native ordinary sender hands
// the endpoint writer, over the recorder on a real socket, one protected 1-RTT packet
// of exactly the read-back send capacity B, so the archived trigger holds the
// writer in the Go poller until the member's deadline. The connection's sender closes
// during that held write. The member stays borrowed in the call, at the native
// return and after the final deadline reset, and the join follows its release.
func nativeDarwinBBRProtectedCloseJoin(t *testing.T, facts map[string]any) {
	const triggerClaim = 1 // claim 0 is the positive control
	observer := &nativeDarwinProtectedObserver{}
	// The connection's participant ID comes from a process-wide counter, so the
	// fixture's own participant takes an ID that counter never reaches.
	w := newNativeDarwinRecordedWriter(t, &nativeDarwinIO{observe: observer.observe}, nativeDarwinProtectedSendBuffer, nativeTestBlockerID)
	require.Equal(t, nativeDarwinProtectedSendBuffer, w.trigger.capacity, "the protected trigger is one standard-size packet")
	p := newNativeDarwinProtected(t, "bbrv3", w.e, w.destination, true)
	require.NotNil(t, p.conn.emission.bbr, "the connection's controller is bbrv3")

	// The positive control is itself a small protected BBR member the peer opens.
	control := p.member(t, 300, protocol.ECT0, 0x43)
	require.NotNil(t, control.plan)
	p.sender.finish()
	payload, received := w.peer.read(t)
	require.Equal(t, protocol.ECT0, received.ecn)
	controlOpened := p.opens(control, []byte(payload))
	require.True(t, controlOpened, "the peer opens the protected control")
	p.settle(t, control)

	trigger := p.member(t, w.trigger.capacity, protocol.ECT0, 0x54)
	require.NotNil(t, trigger.plan, "production construction attached a native protection plan")
	require.True(t, trigger.deferred, "the writer, not construction, applies the plan")
	require.True(t, trigger.credit, "the member carries the BBR reservation credit")
	retired := p.sender.participant.retired
	observer.arm(triggerClaim, w.e, trigger, retired)
	p.sender.finish()
	token := nativeDarwinAwaitMember(w.e, trigger.match, trigger.deadline)
	require.NotNil(t, token, "the writer never waited in the Go poller")
	call := nativeDarwinProtectedSample(w.e, trigger)
	require.True(t, call.borrowed(), "the member is borrowed in the call")

	closing := time.Now()
	p.sender.Close()
	closed, joinOpenAtClose := nativeDarwinProtectedJoinSample(w.e, trigger, retired)
	require.True(t, closed.borrowed(), "the close returns while the native call holds the member")
	require.True(t, joinOpenAtClose, "the join is still open when the close returns")
	// The same native call is still in the Go poller once the close has returned.
	before := nativeDarwinHeldMember(w.e, trigger.match)
	waiting := nativeDarwinWriterWaiting()
	after := nativeDarwinHeldMember(w.e, trigger.match)
	require.True(t, before == token && waiting && after == token, "the trigger's native call is still waiting after the close returns")
	joined := nativeDarwinAwaitJoin(t, retired)
	released := nativeDarwinProtectedReleased(trigger)
	require.True(t, released, "the join follows the member's release")

	fact := token.completion.Load()
	require.NotNil(t, fact)
	require.False(t, fact.fault)
	require.ErrorIs(t, fact.result.failure(), os.ErrDeadlineExceeded)
	require.Equal(t, [3]int{0, 1, 0}, nativeDarwinCounts(fact.result.members[0]))
	claim := w.io.claim(triggerClaim)
	class := claim.class(trigger.deadline, true)
	require.Equal(t, "native-traversal", class)
	require.Equal(t, 1, claim.calls, "the trigger's claim made one native call")
	require.Equal(t, len(trigger.oob), claim.control, "the native call forwarded the member's own control")
	require.False(t, claim.returnedAt.Before(trigger.deadline), "the poller returned at the deadline")
	require.True(t, claim.returnedAt.After(closing), "close began while the member was in the native call")
	require.False(t, joined.Before(fact.returnedAt), "the join never precedes the whole borrow's return")

	seen := observer.snapshot()
	require.True(t, seen.joinOpenAtFence, "the join was still open after the final deadline reset")
	require.Len(t, seen.sent, w.trigger.capacity, "the native call carried exactly B bytes")
	require.Less(t, len(trigger.oob), w.trigger.capacity)
	lifetime := p.lifetime(trigger, call, seen, released)
	require.Equal(t, "borrowed-through-fence", lifetime.class())

	// The endpoint did not fault, and the trigger was never delivered: the fixture's
	// own successor is the peer's next datagram.
	successor := w.send(t, w.request(3, "successor", time.Now().Add(nativeDarwinBudget)))
	require.NoError(t, successor.failure())
	payload, ecn := w.read(t)
	require.Equal(t, "successor", payload, "the protected trigger was not delivered")
	require.Equal(t, protocol.ECT0, ecn)
	_, faulted := w.e.faultObservation()
	require.False(t, faulted)

	nativeDarwinTraversalFacts(facts, w, claim, trigger.deadline, class)
	// The control and the bytes the member's native call carried.
	facts["control_bytes"] = claim.control
	facts["payload_bytes"] = len(seen.sent)
	facts["controller"] = p.controller
	facts["bbr_credit"] = trigger.credit
	facts["protection_plan"] = trigger.plan != nil
	facts["protected_by_writer"] = trigger.deferred && seen.applied
	facts["native_ciphertext_opened"] = lifetime.ciphertext
	facts["control_opened"] = controlOpened
	facts["borrowed_in_call"] = call.borrowed()
	facts["close_returned_while_borrowed"] = closed.borrowed()
	facts["borrowed_at_native_return"] = seen.returned.borrowed()
	facts["borrowed_at_fence"] = seen.fenced.borrowed()
	facts["lifetime"] = lifetime.class()
	facts["released_at_join"] = released
	facts["joined_after_return"] = true
	facts["successor_delivered"] = true
	facts["faulted"] = false
	facts["close_to_join_ms"] = nativeDarwinMS(joined.Sub(closing))
}

// nativeDarwinSimulatedRun is one member's held write, active close and join over
// the gated simulated writer: the observation at the native write's entry, while the
// final deadline reset is held, and after the join, with the derived lifetime.
type nativeDarwinSimulatedRun struct {
	protected *nativeDarwinProtected
	member    nativeDarwinProtectedMember
	call      nativeDarwinBorrow
	closed    nativeDarwinBorrow
	// entry is the observation when the native write began, and fencing the one
	// while the final deadline reset was held after the native return.
	entry, fencing  nativeDarwinProtectedObservation
	joinOpenAtReset bool
	seen            nativeDarwinProtectedObservation
	released        bool
	lifetime        nativeDarwinProtectedLifetime
	class           string
}

// nativeDarwinSimulatedProtected drives one member of a controller connection, with or
// without deferred protection, through the case's held write, active close and join
// over a simulated writer whose native write and final deadline reset are each gated.
// It checks the ordering every path shares: nothing returns or fences while the call
// is held, nothing fences while the reset is held, and the join waits for the fence.
func nativeDarwinSimulatedProtected(t *testing.T, controller string, deferred bool, ecn protocol.ECN) (run nativeDarwinSimulatedRun) {
	t.Helper()
	write, reset := make(chan struct{}), make(chan struct{})
	var writeOnce, resetOnce sync.Once
	releaseWrite := func() { writeOnce.Do(func() { close(write) }) }
	releaseReset := func() { resetOnce.Do(func() { close(reset) }) }
	observer := &nativeDarwinProtectedObserver{}
	entries := make(chan nativeDarwinProtectedObservation, 1)
	record := &nativeDarwinIO{native: endpointTestNative{
		send: func([]byte) (int, error) {
			entries <- observer.snapshot()
			<-write
			return 0, os.ErrDeadlineExceeded
		},
		deadline: func(deadline time.Time) error {
			if deadline.IsZero() {
				<-reset
			}
			return nil
		},
	}, observe: observer.observe}
	e := startNativeEndpoint(record, nativeDarwinBudget, nil)
	t.Cleanup(func() { releaseWrite(); releaseReset(); <-e.stop() })
	p := newNativeDarwinProtected(t, controller, e, netip.MustParseAddrPort("127.0.0.1:1234"), deferred)
	m := p.member(t, nativeDarwinProtectedSendBuffer, ecn, 0x54)
	retired := p.sender.participant.retired
	observer.arm(0, e, m, retired)
	p.sender.finish()
	synctest.Wait()
	select {
	case run.entry = <-entries:
	default:
		require.FailNow(t, "the writer never began the native write")
	}
	run.protected, run.member = p, m
	run.call = nativeDarwinProtectedSample(e, m)
	p.sender.Close()
	run.closed = nativeDarwinProtectedSample(e, m)
	synctest.Wait()
	select {
	case <-retired:
		require.FailNow(t, "the join preceded the native return")
	default:
	}
	held := observer.snapshot()
	require.False(t, held.returned.sampled, "nothing has returned yet")
	require.False(t, held.fenced.sampled)

	releaseWrite()
	synctest.Wait()
	run.fencing = observer.snapshot()
	select {
	case <-retired:
	default:
		run.joinOpenAtReset = true
	}

	releaseReset()
	synctest.Wait()
	select {
	case <-retired:
	default:
		require.FailNow(t, "the native return and fence did not release the join")
	}
	run.released = nativeDarwinProtectedReleased(m)
	run.seen = observer.snapshot()
	run.lifetime = p.lifetime(m, run.call, run.seen, run.released)
	run.class = record.claim(0).class(m.deadline, true)
	return run
}
