//go:build darwin

package quic

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/netip"
	"os"
	"runtime"
	"strings"
	"sync"
	"syscall"
	"testing"
	"testing/synctest"
	"time"

	"github.com/GridCastIO/quicquic-go/internal/monotime"
	"github.com/GridCastIO/quicquic-go/internal/protocol"
	"github.com/stretchr/testify/require"
)

const (
	// nativeDarwinBudget is the write budget of every blocked-writer case. A request
	// deadline inside it is installed unchanged.
	nativeDarwinBudget = 200 * time.Millisecond
	// nativeDarwinSendBuffer is the send buffer the trigger socket requests. The
	// kernel's read-back capacity B, not this value, sizes the trigger.
	nativeDarwinSendBuffer = 4096
)

// nativeDarwinClaim is what the recorder saw of one claimed request: the deadline the
// writer installed and when that installation succeeded, its native calls, and the
// final reset. Copies are snapshots.
type nativeDarwinClaim struct {
	installed       time.Time
	installedAt     time.Time
	socket          bool
	calls, injected int
	pending         int
	returnedAt      time.Time
	reset           bool
	resetErr        error
}

// returned reports whether every native call the claim made has returned.
func (c *nativeDarwinClaim) returned() bool { return c.calls != 0 && c.pending == 0 }

// class labels one request's observation. Only an uninjected native call on the real
// socket that returned, under the request's own deadline, with the deadline reset and
// the writer seen in the Go poller's write wait, is native traversal. Every other
// class is a named failure the case runner refuses as traversal evidence.
func (c *nativeDarwinClaim) class(deadline time.Time, witnessed bool) string {
	switch {
	case c == nil || c.calls == 0:
		return "expired-before-dispatch"
	case !c.installed.Equal(deadline):
		return "stale-deadline"
	case !c.returned():
		return "missing-native-return"
	case !c.reset || c.resetErr != nil:
		return "reset-failure"
	case c.injected != 0 || !c.socket:
		return "simulated"
	case !witnessed:
		return "no-witness"
	}
	return "native-traversal"
}

// expiredClass labels a claim that expired before dispatch: claimed under the
// request's own deadline, which passed before the writer's first native call, so the
// writer refused the submission and reset the deadline. Only such a claim on the real
// socket with nothing injected is expired-claim-unsubmitted, its own success class.
// class still labels it expired-before-dispatch, a traversal failure.
func (c *nativeDarwinClaim) expiredClass(deadline time.Time) string {
	switch {
	case c == nil:
		return "unclaimed"
	case c.calls != 0:
		return "dispatched"
	case !c.installed.Equal(deadline):
		return "stale-deadline"
	case !c.reset || c.resetErr != nil:
		return "reset-failure"
	case c.injected != 0 || !c.socket:
		return "simulated"
	}
	return "expired-claim-unsubmitted"
}

// nativeDarwinIO forwards the sole writer's calls to the endpoint's native I/O and
// records each claim. inject, if set, returns a simulated error for a numbered write
// (from 1) instead of forwarding it; an injected call never reaches the socket. hold,
// if set, runs on the writer after each claim's deadline is installed, with the
// claim's number (from 0); it delays the writer and changes no native result.
// observe, if set, runs on the writer with the claim's number at three points: at
// "native-call" with the bytes about to be forwarded, at "native-return" after the
// call returns, and at "fence" after the final deadline reset returns. It changes no
// native result.
type nativeDarwinIO struct {
	native  endpointNativeIO
	socket  bool
	inject  func(call int) error
	hold    func(claim int, deadline time.Time)
	observe func(claim int, point string, data []byte)

	mutex  sync.Mutex
	writes int
	claims []*nativeDarwinClaim
}

func (n *nativeDarwinIO) SetWriteDeadline(deadline time.Time) error {
	if !deadline.IsZero() {
		n.mutex.Lock()
		number := len(n.claims)
		claim := &nativeDarwinClaim{installed: deadline, socket: n.socket}
		n.claims = append(n.claims, claim)
		n.mutex.Unlock()
		err := n.native.SetWriteDeadline(deadline)
		if err == nil {
			n.mutex.Lock()
			claim.installedAt = time.Now()
			n.mutex.Unlock()
		}
		if n.hold != nil {
			n.hold(number, deadline)
		}
		return err
	}
	err := n.native.SetWriteDeadline(deadline)
	n.mutex.Lock()
	number := len(n.claims) - 1
	if number >= 0 {
		claim := n.claims[number]
		claim.reset, claim.resetErr = true, err
	}
	n.mutex.Unlock()
	if n.observe != nil && number >= 0 {
		n.observe(number, "fence", nil)
	}
	return err
}

func (n *nativeDarwinIO) WriteMsgUDPAddrPort(b, oob []byte, destination netip.AddrPort) (int, int, error) {
	n.mutex.Lock()
	n.writes++
	call := n.writes
	if len(n.claims) == 0 {
		// A write outside an installed deadline is a stale-deadline observation.
		n.claims = append(n.claims, &nativeDarwinClaim{socket: n.socket})
	}
	number := len(n.claims) - 1
	claim := n.claims[number]
	claim.calls++
	claim.pending++
	n.mutex.Unlock()

	if n.observe != nil {
		n.observe(number, "native-call", b)
	}
	var err error
	if n.inject != nil {
		err = n.inject(call)
	}
	var written, oobn int
	injected := err != nil
	if !injected {
		written, oobn, err = n.native.WriteMsgUDPAddrPort(b, oob, destination)
	}
	if n.observe != nil {
		n.observe(number, "native-return", nil)
	}

	n.mutex.Lock()
	defer n.mutex.Unlock()
	claim.pending--
	claim.returnedAt = time.Now()
	if injected {
		claim.injected++
	}
	return written, oobn, err
}

// claim returns a snapshot of the i-th claim, or nil if the writer made fewer.
func (n *nativeDarwinIO) claim(i int) *nativeDarwinClaim {
	n.mutex.Lock()
	defer n.mutex.Unlock()
	if i >= len(n.claims) {
		return nil
	}
	snapshot := *n.claims[i]
	return &snapshot
}

func (n *nativeDarwinIO) claimCount() int {
	n.mutex.Lock()
	defer n.mutex.Unlock()
	return len(n.claims)
}

// nativeDarwinHoldUntilDeadline holds the writer in the numbered claim's deadline
// setup until that claim's deadline has passed.
func nativeDarwinHoldUntilDeadline(number int) func(int, time.Time) {
	return func(claim int, deadline time.Time) {
		if claim != number {
			return
		}
		for wait := time.Until(deadline); wait > 0; wait = time.Until(deadline) {
			time.Sleep(wait)
		}
	}
}

var nativeDarwinStacks = struct {
	sync.Mutex
	buffer []byte
}{buffer: make([]byte, 1<<20)}

// nativeDarwinWriterWaiting reports whether a goroutine stack shows the endpoint's
// sole writer inside the real Go poller's write wait.
func nativeDarwinWriterWaiting() bool {
	nativeDarwinStacks.Lock()
	defer nativeDarwinStacks.Unlock()
	stacks := string(nativeDarwinStacks.buffer[:runtime.Stack(nativeDarwinStacks.buffer, true)])
	for _, goroutine := range strings.Split(stacks, "\n\n") {
		if strings.Contains(goroutine, "internal/poll.(*pollDesc).waitWrite") && strings.Contains(goroutine, "quicquic-go.(*nativeEndpoint).write(") {
			return true
		}
	}
	return false
}

// nativeDarwinHeld returns the writer's current token if it is datagram's request and
// its borrow has not been published. It samples under the endpoint lock.
func nativeDarwinHeld(e *nativeEndpoint, datagram *endpointDatagram) *endpointToken {
	return nativeDarwinHeldMember(e, func(member endpointMember) bool { return member.datagram == datagram })
}

// nativeDarwinHeldMember returns the writer's current token if its request is one
// member that match accepts and its borrow has not been published. It samples under
// the endpoint lock.
func nativeDarwinHeldMember(e *nativeEndpoint, match func(endpointMember) bool) (held *endpointToken) {
	e.do(func(s *endpointState) {
		token := s.current
		if token != nil && len(token.request.members) == 1 && match(token.request.members[0]) && token.completion.Load() == nil {
			held = token
		}
	})
	return held
}

// nativeDarwinAwaitWait waits until the writer holds datagram's borrow while it waits
// in the Go poller, checking the borrow on both sides of the stack sample. A nil
// token means the witness was not observed before the request's deadline.
func nativeDarwinAwaitWait(e *nativeEndpoint, datagram *endpointDatagram, deadline time.Time) *endpointToken {
	return nativeDarwinAwaitMember(e, func(member endpointMember) bool { return member.datagram == datagram }, deadline)
}

// nativeDarwinAwaitMember is nativeDarwinAwaitWait for the member that match accepts.
func nativeDarwinAwaitMember(e *nativeEndpoint, match func(endpointMember) bool, deadline time.Time) *endpointToken {
	for time.Now().Before(deadline) {
		if token := nativeDarwinHeldMember(e, match); token != nil && nativeDarwinWriterWaiting() && nativeDarwinHeldMember(e, match) == token {
			return token
		}
		time.Sleep(time.Millisecond)
	}
	return nil
}

// nativeDarwinTrigger is the archived Darwin send-buffer construction adapted to the
// scalar endpoint: one datagram of exactly the read-back send capacity B with valid
// ECT(0) control. Each part fits B, and together they exceed it, so a nonblocking
// sendmsg returns EAGAIN and the Go poller waits for writability until the request's
// deadline. Its payload is typed datagram storage of exactly that size.
type nativeDarwinTrigger struct {
	capacity int
	control  []byte
}

func newNativeDarwinTrigger(t *testing.T, socket *net.UDPConn, destination netip.AddrPort) nativeDarwinTrigger {
	t.Helper()
	return newNativeDarwinSizedTrigger(t, socket, destination, nativeDarwinSendBuffer)
}

// newNativeDarwinSizedTrigger is newNativeDarwinTrigger on a socket that requests a
// send buffer of request bytes.
func newNativeDarwinSizedTrigger(t *testing.T, socket *net.UDPConn, destination netip.AddrPort, request int) nativeDarwinTrigger {
	t.Helper()
	require.NoError(t, socket.SetWriteBuffer(request))
	raw, err := socket.SyscallConn()
	require.NoError(t, err)
	var capacity int
	var optErr error
	require.NoError(t, raw.Control(func(fd uintptr) {
		capacity, optErr = syscall.GetsockoptInt(int(fd), syscall.SOL_SOCKET, syscall.SO_SNDBUF)
	}))
	require.NoError(t, optErr)
	require.Positive(t, capacity)
	require.Less(t, capacity, 60000, "the read-back capacity must stay a modest buffer")
	control := packetOOB(nil, destination, protocol.ECT0)
	require.NotEmpty(t, control)
	require.Less(t, len(control), capacity)
	return nativeDarwinTrigger{capacity: capacity, control: control}
}

// datagram returns a raw public request of size bytes and its storage.
func (g nativeDarwinTrigger) datagram(destination netip.AddrPort, deadline time.Time, size int) (endpointRequest, *endpointDatagram) {
	datagram := &endpointDatagram{data: make([]byte, size), result: make(chan endpointResult, 1)}
	return endpointRequest{
		destination: destination,
		members:     []endpointMember{{datagram: datagram, oob: g.control}},
		deadline:    deadline,
	}, datagram
}

// nativeDarwinWriter is one blocked-writer case's endpoint: the production writer over
// the recorder and a real loopback socket, a data participant and a reading peer. The
// endpoint stops in cleanup, which joins the writer after its current native return.
type nativeDarwinWriter struct {
	io          *nativeDarwinIO
	e           *nativeEndpoint
	p           *endpointParticipant
	peer        *nativeDarwinReader
	destination netip.AddrPort
	trigger     nativeDarwinTrigger
}

func newNativeDarwinWriter(t *testing.T, inject func(int) error) *nativeDarwinWriter {
	t.Helper()
	return newNativeDarwinHeldWriter(t, inject, nil)
}

// newNativeDarwinHeldWriter is newNativeDarwinWriter with the recorder's hold.
func newNativeDarwinHeldWriter(t *testing.T, inject func(int) error, hold func(int, time.Time)) *nativeDarwinWriter {
	t.Helper()
	return newNativeDarwinRecordedWriter(t, &nativeDarwinIO{inject: inject, hold: hold}, nativeDarwinSendBuffer, 1)
}

// newNativeDarwinRecordedWriter starts the writer over record, which forwards to a new
// real loopback socket that requests a send buffer of sendBuffer bytes, and attaches
// the fixture's data participant with the given ID.
func newNativeDarwinRecordedWriter(t *testing.T, record *nativeDarwinIO, sendBuffer int, participant uint64) *nativeDarwinWriter {
	t.Helper()
	socket := nativeDarwinListen("udp4", net.IPv4(127, 0, 0, 1))(t)
	peerSocket := nativeDarwinListen("udp4", net.IPv4(127, 0, 0, 1))(t)
	destination := peerSocket.LocalAddr().(*net.UDPAddr).AddrPort()
	record.native, record.socket = socket, true
	w := &nativeDarwinWriter{
		io:          record,
		peer:        newNativeDarwinReader(t, peerSocket),
		destination: destination,
		trigger:     newNativeDarwinSizedTrigger(t, socket, destination, sendBuffer),
	}
	w.e = startNativeEndpoint(w.io, nativeDarwinBudget, nil)
	t.Cleanup(func() { <-w.e.stop() })
	p, err := w.e.attach(participant)
	require.NoError(t, err)
	w.p = p
	return w
}

// request is a scalar data request with ECT(0) control.
func (w *nativeDarwinWriter) request(registration uint64, payload string, deadline time.Time) endpointRequest {
	return endpointRequest{
		identity:    endpointIdentity{connection: w.p.id, registration: registration},
		destination: w.destination,
		members:     []endpointMember{{buffer: endpointTestBuffer(payload), oob: w.trigger.control}},
		deadline:    deadline,
	}
}

// offer retries a capacity refusal, as a producer does behind the retry floor.
func (w *nativeDarwinWriter) offer(t *testing.T, request endpointRequest) {
	t.Helper()
	for {
		err := w.e.offer(w.p, 0, request)
		if !errors.Is(err, errEndpointCapacity) {
			require.NoError(t, err)
			return
		}
		time.Sleep(endpointRetry)
	}
}

// take waits for one published data result and when it became visible.
func (w *nativeDarwinWriter) take(t *testing.T) (endpointResult, time.Time) {
	t.Helper()
	timeout := time.After(scaleDuration(5 * time.Second))
	for {
		if result, ok := w.e.take(w.p); ok {
			return result, time.Now()
		}
		select {
		case <-w.p.completed:
		case <-timeout:
			require.FailNow(t, "the endpoint published no result")
		}
	}
}

func (w *nativeDarwinWriter) send(t *testing.T, request endpointRequest) endpointResult {
	t.Helper()
	w.offer(t, request)
	result, _ := w.take(t)
	return result
}

// read returns the peer's next payload and its ECN codepoint.
func (w *nativeDarwinWriter) read(t *testing.T) (string, protocol.ECN) {
	t.Helper()
	payload, p := w.peer.read(t)
	return payload, p.ecn
}

// control is the positive fixture control: an ordinary small ECT(0) datagram through
// the granted writer reaches the peer with its codepoint. It is the first claim.
func (w *nativeDarwinWriter) control(t *testing.T) {
	t.Helper()
	result := w.send(t, w.request(1, "positive control", time.Now().Add(nativeDarwinBudget)))
	require.NoError(t, result.failure())
	payload, ecn := w.read(t)
	require.Equal(t, "positive control", payload)
	require.Equal(t, protocol.ECT0, ecn)
}

func nativeDarwinDatagramResult(t *testing.T, datagram *endpointDatagram) (endpointResult, time.Time) {
	t.Helper()
	select {
	case result := <-datagram.result:
		return result, time.Now()
	case <-time.After(scaleDuration(5 * time.Second)):
		require.FailNow(t, "the endpoint published no datagram result")
		return endpointResult{}, time.Time{}
	}
}

func nativeDarwinCounts(member endpointMemberResult) [3]int {
	return [3]int{member.accepted, member.uncertain, member.unsubmitted}
}

func nativeDarwinMS(d time.Duration) float64 { return float64(d) / float64(time.Millisecond) }

func nativeDarwinSendmsgError(errno syscall.Errno) error {
	return &os.SyscallError{Syscall: "sendmsg", Err: errno}
}

// nativeDarwinTriggerFacts records what every forced-traversal case observed of its
// trigger: geometry, positive control, poller witness and the native return's
// distance from the deadline. The case has already required its class; timing is
// recorded, never judged here.
func nativeDarwinTriggerFacts(facts map[string]any, trigger nativeDarwinTrigger, class string, injected int, returnAfterDeadline time.Duration) {
	facts["evidence"] = class
	facts["send_buffer"] = trigger.capacity
	facts["control_bytes"] = len(trigger.control)
	facts["payload_bytes"] = trigger.capacity
	facts["positive_control"] = protocol.ECT0.String()
	facts["poller_witness"] = true
	facts["injected"] = injected
	facts["traced"] = false
	facts["result"] = "deadline-exceeded"
	facts["uncertain"] = 1
	facts["native_return_after_deadline_ms"] = nativeDarwinMS(returnAfterDeadline)
}

// nativeDarwinTraversalFacts adds the recorder's view of the trigger's claim.
func nativeDarwinTraversalFacts(facts map[string]any, w *nativeDarwinWriter, claim *nativeDarwinClaim, deadline time.Time, class string) {
	nativeDarwinTriggerFacts(facts, w.trigger, class, claim.injected, claim.returnedAt.Sub(deadline))
	facts["native_calls"] = claim.calls
	facts["deadline_preserved"] = claim.installed.Equal(deadline)
	facts["deadline_reset"] = claim.reset && claim.resetErr == nil
	facts["native_returned"] = claim.returned()
}

func nativeDarwinFirstSendEPERM(t *testing.T, facts map[string]any) {
	w := newNativeDarwinWriter(t, func(call int) error {
		if call == 1 || call == 3 {
			return nativeDarwinSendmsgError(syscall.EPERM)
		}
		return nil
	})
	state := &endpointWriteState{}
	first := w.request(1, "permission retry", time.Now().Add(nativeDarwinBudget))
	first.members[0].writeState = state
	result := w.send(t, first)
	require.NoError(t, result.failure())
	require.Equal(t, [3]int{1, 0, 0}, nativeDarwinCounts(result.members[0]))
	payload, ecn := w.read(t)
	require.Equal(t, "permission retry", payload, "the retry reached the socket")
	require.Equal(t, protocol.ECT0, ecn)
	claim := w.io.claim(0)
	require.Equal(t, [2]int{2, 1}, [2]int{claim.calls, claim.injected}, "one injected EPERM, then one native retry")

	// The same path's later send is not its first, so EPERM is not retried.
	later := w.request(2, "not first", time.Now().Add(nativeDarwinBudget))
	later.members[0].writeState = state
	result = w.send(t, later)
	require.ErrorIs(t, result.failure(), syscall.EPERM)
	require.Equal(t, [3]int{0, 1, 0}, nativeDarwinCounts(result.members[0]))
	claim = w.io.claim(1)
	require.Equal(t, [2]int{1, 1}, [2]int{claim.calls, claim.injected})
	_, faulted := w.e.faultObservation()
	require.False(t, faulted)

	facts["evidence"] = "simulated"
	facts["injected"] = 2
	facts["first_send_retry"] = "accepted"
	facts["retry_delivered"] = true
	facts["later_send"] = "uncertain-eperm"
	facts["faulted"] = false
}

func nativeDarwinConstructedSegmentation(t *testing.T, facts map[string]any) {
	// Writes 1–3 are the whole member's segments; write 5 is the prefix's second.
	w := newNativeDarwinWriter(t, func(call int) error {
		if call == 5 {
			return nativeDarwinSendmsgError(syscall.EAGAIN)
		}
		return nil
	})
	whole := w.request(1, "aaaabbbbcc", time.Now().Add(nativeDarwinBudget))
	whole.members[0].gsoSize = 4
	result := w.send(t, whole)
	require.NoError(t, result.failure())
	require.Equal(t, [3]int{3, 0, 0}, nativeDarwinCounts(result.members[0]))
	for _, segment := range []string{"aaaa", "bbbb", "cc"} {
		payload, ecn := w.read(t)
		require.Equal(t, segment, payload, "the shared writer sends each segment as scalar UDP")
		require.Equal(t, protocol.ECT0, ecn)
	}

	prefix := w.request(2, "ddddeeeeff", time.Now().Add(nativeDarwinBudget))
	prefix.members[0].gsoSize = 4
	result = w.send(t, prefix)
	require.ErrorIs(t, result.failure(), syscall.EAGAIN)
	require.Equal(t, [3]int{1, 1, 1}, nativeDarwinCounts(result.members[0]), "accepted prefix, attempted segment, untouched suffix")
	payload, _ := w.read(t)
	require.Equal(t, "dddd", payload)
	claim := w.io.claim(1)
	require.Equal(t, [2]int{2, 1}, [2]int{claim.calls, claim.injected}, "the suffix made no call")

	facts["evidence"] = "constructed"
	facts["segments"] = 3
	facts["whole_accepted"] = 3
	facts["whole_delivered"] = 3
	facts["prefix_injected"] = "EAGAIN"
	facts["prefix_accepted"] = 1
	facts["prefix_uncertain"] = 1
	facts["prefix_unsubmitted"] = 1
	facts["prefix_delivered"] = 1
}

func nativeDarwinScalarEMSGSIZE(t *testing.T, facts map[string]any) {
	w := newNativeDarwinWriter(t, nil)
	w.control(t)
	request, datagram := w.trigger.datagram(w.destination, time.Now().Add(nativeDarwinBudget), w.trigger.capacity+1)
	require.NoError(t, w.e.offer(w.e.public, 0, request))
	result, _ := nativeDarwinDatagramResult(t, datagram)
	require.ErrorIs(t, result.failure(), syscall.EMSGSIZE, "a payload above the send capacity is size feedback")
	require.Equal(t, [3]int{0, 0, 1}, nativeDarwinCounts(result.members[0]), "size feedback submitted nothing")
	require.False(t, localEndpointBackpressure(result.failure()), "size feedback is not local backpressure")
	claim := w.io.claim(1)
	require.Equal(t, [2]int{1, 0}, [2]int{claim.calls, claim.injected})

	successor := w.send(t, w.request(2, "after size feedback", time.Now().Add(nativeDarwinBudget)))
	require.NoError(t, successor.failure())
	payload, _ := w.read(t)
	require.Equal(t, "after size feedback", payload, "the oversized datagram never arrived")
	_, faulted := w.e.faultObservation()
	require.False(t, faulted)

	facts["evidence"] = "native-size-feedback"
	facts["send_buffer"] = w.trigger.capacity
	facts["payload_bytes"] = w.trigger.capacity + 1
	facts["errno"] = "EMSGSIZE"
	facts["unsubmitted"] = 1
	facts["backpressure"] = false
	facts["injected"] = 0
	facts["successor_delivered"] = true
	facts["faulted"] = false
}

// nativeDarwinExpiredBeforeDispatchSuccessor is the protocol's D15 A case: native
// expiry before dispatch with successor progress. A request already expired at the
// claim boundary is never claimed (that is queued expiry), so the recorder holds the
// writer in the claim's deadline setup until its deadline passes. The production
// writer then refuses the submission itself, with no native call, and resets the
// real socket's deadline. A successor with its own deadline is then written natively
// and read by the peer. Nothing is injected and no poller wait is involved, so the
// record has no witness, no native return time and no timing verdict for the expired
// claim. The endpoint still requires the whole borrow, the hold and the deadline
// reset included, to complete before the deadline plus its tolerance; otherwise it
// faults (overdue or late return) and the case fails.
func nativeDarwinExpiredBeforeDispatchSuccessor(t *testing.T, facts map[string]any) {
	const expiredClaim, successorClaim = 1, 2 // claim 0 is the positive control
	w := newNativeDarwinHeldWriter(t, nil, nativeDarwinHoldUntilDeadline(expiredClaim))
	w.control(t)
	deadline := time.Now().Add(nativeDarwinBudget)
	w.offer(t, w.request(2, "expired", deadline))
	expired, _ := w.take(t)
	require.EqualValues(t, 2, expired.identity.registration)
	require.ErrorIs(t, expired.failure(), os.ErrDeadlineExceeded)
	require.Equal(t, [3]int{0, 0, 1}, nativeDarwinCounts(expired.members[0]), "the expired claim submitted nothing")
	claim := w.io.claim(expiredClaim)
	require.NotNil(t, claim, "the request was never claimed")
	require.False(t, claim.installedAt.IsZero(), "the claim's deadline was never installed")
	require.True(t, claim.installedAt.Before(deadline), "the claim's deadline was installed before it passed")
	class := claim.expiredClass(deadline)
	require.Equal(t, "expired-claim-unsubmitted", class)

	successorDeadline := time.Now().Add(nativeDarwinBudget)
	successor := w.send(t, w.request(3, "successor", successorDeadline))
	require.EqualValues(t, 3, successor.identity.registration)
	require.NoError(t, successor.failure())
	require.Equal(t, [3]int{1, 0, 0}, nativeDarwinCounts(successor.members[0]))
	payload, ecn := w.read(t)
	require.Equal(t, "successor", payload, "the expired request never reached the peer")
	require.Equal(t, protocol.ECT0, ecn)
	next := w.io.claim(successorClaim)
	require.True(t, next.installed.Equal(successorDeadline), "the successor has its own deadline")
	require.True(t, next.socket)
	require.Equal(t, [2]int{1, 0}, [2]int{next.calls, next.injected}, "one native call on the real socket")
	require.Equal(t, 3, w.io.claimCount())
	_, faulted := w.e.faultObservation()
	require.False(t, faulted)

	counts := nativeDarwinCounts(expired.members[0])
	facts["evidence"] = class
	facts["positive_control"] = protocol.ECT0.String()
	facts["expired_claim"] = expiredClaim
	facts["expired_registration"] = expired.identity.registration
	facts["expired_during"] = "deadline-setup"
	facts["expired_native_calls"] = claim.calls
	facts["expired_deadline_preserved"] = claim.installed.Equal(deadline)
	facts["expired_deadline_reset"] = claim.reset && claim.resetErr == nil
	facts["expired_result"] = "deadline-exceeded"
	facts["expired_accepted"] = counts[0]
	facts["expired_uncertain"] = counts[1]
	facts["expired_unsubmitted"] = counts[2]
	facts["successor_claim"] = successorClaim
	facts["successor_registration"] = successor.identity.registration
	facts["successor_native_calls"] = next.calls
	facts["successor_deadline_preserved"] = true
	facts["successor_accepted"] = successor.members[0].accepted
	facts["successor_delivered"] = true
	facts["injected"] = claim.injected + next.injected
	facts["traced"] = false
	facts["faulted"] = false
}

func nativeDarwinEAGAINToDeadline(t *testing.T, facts map[string]any) {
	w := newNativeDarwinWriter(t, nil)
	w.control(t)
	deadline := time.Now().Add(nativeDarwinBudget)
	request, datagram := w.trigger.datagram(w.destination, deadline, w.trigger.capacity)
	require.NoError(t, w.e.offer(w.e.public, 0, request))
	require.NotNil(t, nativeDarwinAwaitWait(w.e, datagram, deadline), "the writer never waited in the Go poller")
	result, seen := nativeDarwinDatagramResult(t, datagram)
	require.ErrorIs(t, result.failure(), os.ErrDeadlineExceeded)
	require.Equal(t, [3]int{0, 1, 0}, nativeDarwinCounts(result.members[0]), "a native timeout never proves zero submission")
	claim := w.io.claim(1)
	class := claim.class(deadline, true)
	require.Equal(t, "native-traversal", class)
	require.False(t, claim.returnedAt.Before(deadline), "the poller returned at the deadline")

	// The successor gets its own deadline, and it is the next datagram the peer sees.
	successorDeadline := time.Now().Add(nativeDarwinBudget)
	successor := w.send(t, w.request(2, "successor", successorDeadline))
	require.NoError(t, successor.failure())
	payload, ecn := w.read(t)
	require.Equal(t, "successor", payload, "the timed-out trigger was not delivered")
	require.Equal(t, protocol.ECT0, ecn)
	next := w.io.claim(2)
	require.True(t, next.installed.Equal(successorDeadline), "the successor never reuses a stale deadline")
	require.True(t, next.reset)
	_, faulted := w.e.faultObservation()
	require.False(t, faulted)

	nativeDarwinTraversalFacts(facts, w, claim, deadline, class)
	facts["publication_ms"] = nativeDarwinMS(seen.Sub(claim.returnedAt))
	facts["successor_deadline_preserved"] = true
	facts["successor_delivered"] = true
	facts["faulted"] = false
}

// nativeDarwinQueuedExpiryTiming times a queued request's expiry from decision, the
// endpoint state owner's terminal decision for its member, and the request's
// deadline. The fixture saw the result at seen; the time from the decision to then is
// publication and collection, never expiry. A decision before the deadline, or one
// the fixture could not yet have seen, is not a queued expiry.
func nativeDarwinQueuedExpiryTiming(decision monotime.Time, deadline, seen time.Time) (expiry, publication time.Duration, err error) {
	if decision.IsZero() {
		return 0, 0, errors.New("the queued result carries no expiry decision")
	}
	decided := decision.ToTime()
	switch {
	case decided.Before(deadline):
		return 0, 0, fmt.Errorf("the queued request expired %s before its deadline", deadline.Sub(decided))
	case decided.After(seen):
		return 0, 0, fmt.Errorf("the queued request expired %s after the fixture observed it", decided.Sub(seen))
	}
	return decided.Sub(deadline), seen.Sub(decided), nil
}

func nativeDarwinQueuedExpiry(t *testing.T, facts map[string]any) {
	w := newNativeDarwinWriter(t, nil)
	w.control(t)
	start := time.Now()
	currentDeadline := start.Add(nativeDarwinBudget)
	request, datagram := w.trigger.datagram(w.destination, currentDeadline, w.trigger.capacity)
	require.NoError(t, w.e.offer(w.e.public, 0, request))
	require.NotNil(t, nativeDarwinAwaitWait(w.e, datagram, currentDeadline), "the writer never waited in the Go poller")
	queuedDeadline := start.Add(nativeDarwinBudget / 2)
	require.True(t, time.Now().Before(queuedDeadline), "the witness arrived after the queued deadline")
	w.offer(t, w.request(2, "queued", queuedDeadline))
	require.True(t, time.Now().Before(queuedDeadline), "the queued request was admitted after its deadline")

	queued, seen := w.take(t)
	require.EqualValues(t, 2, queued.identity.registration)
	require.ErrorIs(t, queued.failure(), os.ErrDeadlineExceeded)
	require.Equal(t, [3]int{0, 0, 1}, nativeDarwinCounts(queued.members[0]), "queued work expires unsubmitted")
	require.True(t, seen.Before(currentDeadline), "its expiry can't wait for the current request's return")
	expiry, publication, err := nativeDarwinQueuedExpiryTiming(queued.members[0].returnedAt, queuedDeadline, seen)
	require.NoError(t, err)
	require.NotNil(t, nativeDarwinHeld(w.e, datagram), "the current request still holds its borrow")
	require.True(t, nativeDarwinWriterWaiting(), "the current request is still in the Go poller")
	require.Equal(t, 2, w.io.claimCount(), "the expired request was never claimed")

	current, _ := nativeDarwinDatagramResult(t, datagram)
	require.ErrorIs(t, current.failure(), os.ErrDeadlineExceeded)
	require.Equal(t, [3]int{0, 1, 0}, nativeDarwinCounts(current.members[0]))
	claim := w.io.claim(1)
	class := claim.class(currentDeadline, true)
	require.Equal(t, "native-traversal", class)

	nativeDarwinTraversalFacts(facts, w, claim, currentDeadline, class)
	facts["queued_result"] = "deadline-exceeded"
	facts["queued_unsubmitted"] = 1
	facts["queued_claimed"] = false
	facts["queued_before_current_deadline"] = true
	facts["writer_waiting_at_queued_expiry"] = true
	facts["queued_expiry_ms"] = nativeDarwinMS(expiry)
	facts["queued_publication_ms"] = nativeDarwinMS(publication)
}

// nativeDarwinActiveCloseJoin closes the production granted Transport, whose endpoint
// writes to the socket directly, so no recorder sees its claim. The request's
// deadline is read from the writer's held token instead, and the final reset from the
// caller's untouched write after the join.
func nativeDarwinActiveCloseJoin(t *testing.T, facts map[string]any) {
	socket := nativeDarwinListen("udp4", net.IPv4(127, 0, 0, 1))(t)
	peerSocket := nativeDarwinListen("udp4", net.IPv4(127, 0, 0, 1))(t)
	peer := newNativeDarwinReader(t, peerSocket)
	destination := peerSocket.LocalAddr().(*net.UDPAddr).AddrPort()
	tr := &Transport{Conn: socket}
	require.NoError(t, tr.configureNativeIO(nativeDarwinBudget))
	t.Cleanup(func() { tr.Close() })
	// Initialization sizes the socket's buffers, so it precedes the trigger's capacity
	// read-back; Close would otherwise initialize, and grow B, during the blocked write.
	require.NoError(t, tr.init(false))
	trigger := newNativeDarwinTrigger(t, socket, destination)
	e := nativeTransportEndpoint(tr)
	require.NotNil(t, e)
	control := nativeDarwinSend(t, tr, destination, packetInfo{}, protocol.ECT0, "positive control")
	require.NoError(t, control.failure())
	payload, received := peer.read(t)
	require.Equal(t, "positive control", payload)
	require.Equal(t, protocol.ECT0, received.ecn)

	deadline := time.Now().Add(nativeDarwinBudget)
	request, datagram := trigger.datagram(destination, deadline, trigger.capacity)
	require.NoError(t, e.offer(e.public, 0, request))
	token := nativeDarwinAwaitWait(e, datagram, deadline)
	require.NotNil(t, token, "the writer never waited in the Go poller")
	var installed time.Time
	e.do(func(s *endpointState) {
		if s.current == token && token.completion.Load() == nil {
			installed = token.request.deadline
		}
	})
	require.True(t, installed.Equal(deadline), "the still-held request keeps its absolute deadline")

	closing := time.Now()
	require.NoError(t, tr.Close())
	require.Equal(t, token, nativeDarwinHeld(e, datagram), "close returns while the native call holds its borrow")
	canceled, cancel := context.WithCancel(t.Context())
	cancel()
	require.ErrorIs(t, tr.waitNativeIOStopped(canceled), context.Canceled, "a canceled wait is not the join")
	require.True(t, nativeDarwinWriterWaiting(), "the writer is still in the Go poller after the canceled wait")
	joining, stop := context.WithTimeout(t.Context(), scaleDuration(5*time.Second))
	defer stop()
	require.NoError(t, tr.waitNativeIOStopped(joining))
	joined := time.Now()

	// The writer publishes before it exits, and the join follows writer exit.
	fact := token.completion.Load()
	require.NotNil(t, fact)
	require.False(t, fact.fault)
	require.ErrorIs(t, fact.result.failure(), os.ErrDeadlineExceeded)
	require.Equal(t, [3]int{0, 1, 0}, nativeDarwinCounts(fact.result.members[0]))
	// The member's time is the native return; fact.returnedAt also covers the reset.
	nativeReturn := fact.result.members[0].returnedAt.ToTime()
	require.True(t, nativeReturn.After(closing), "close began while the trigger was in the native call")
	require.False(t, nativeReturn.Before(deadline), "the poller returned at the deadline")
	require.False(t, joined.Before(fact.returnedAt), "the join never precedes the whole borrow's return")

	// The join returned write authority with the writer's deadline reset: an
	// untouched caller write is not refused by the expired request deadline.
	_, err := tr.WriteTo([]byte("late"), peerSocket.LocalAddr())
	require.ErrorIs(t, err, net.ErrClosed)
	_, err = socket.WriteToUDP([]byte("caller"), peerSocket.LocalAddr().(*net.UDPAddr))
	require.NoError(t, err)
	payload, _ = peer.read(t)
	require.Equal(t, "caller", payload, "the trigger was not delivered")

	// The production endpoint writes only to the real socket, so nothing is injected.
	nativeDarwinTriggerFacts(facts, trigger, "native-traversal", 0, nativeReturn.Sub(deadline))
	facts["request_deadline_preserved"] = true
	facts["reset_observed_by_caller_write"] = true
	facts["close_returned_while_borrowed"] = true
	facts["canceled_wait"] = "canceled"
	facts["returned_after_close_began"] = true
	facts["joined_after_return"] = true
	facts["transport_write_after_join"] = "closed"
	facts["caller_write_delivered"] = true
	facts["close_to_join_ms"] = nativeDarwinMS(joined.Sub(closing))
}

// TestNativeDarwinBlockedWriter is MP-MAC E2's blocked-writer method, run case by case
// by interop/multipath/native_darwin.py --profile blocked-writer. The
// separately classified cases are ordinary Darwin development tests: an injected
// first-send EPERM before a native retry, a constructed segmented member and its
// prefix, and scalar EMSGSIZE size feedback. The remaining cases are built only with
// the nativequal tag, which only that profile selects. The protocol's expired claim
// and successor keeps its own class; its expiry is positioned against the endpoint
// tolerance, so ordinary runs never register it. The forced-traversal cases reuse one
// current write that waits in the Go poller for queued expiry, active close and join,
// and the protocol's D13 A BBR protected-member lifetime through an active close.
// Their execution is separately authorized native work; a case never skips.
func TestNativeDarwinBlockedWriter(t *testing.T) {
	nativeDarwinCase(t, "first-send-eperm", nativeDarwinFirstSendEPERM)
	nativeDarwinCase(t, "constructed-segmentation-prefix", nativeDarwinConstructedSegmentation)
	nativeDarwinCase(t, "scalar-emsgsize", nativeDarwinScalarEMSGSIZE)
	if !nativeDarwinTraversal {
		return
	}
	nativeDarwinCase(t, "expired-before-dispatch-successor", nativeDarwinExpiredBeforeDispatchSuccessor)
	nativeDarwinCase(t, "eagain-to-deadline", nativeDarwinEAGAINToDeadline)
	nativeDarwinCase(t, "queued-expiry", nativeDarwinQueuedExpiry)
	nativeDarwinCase(t, "active-close-join", nativeDarwinActiveCloseJoin)
	nativeDarwinCase(t, "bbr-protected-close-join", nativeDarwinBBRProtectedCloseJoin)
}

// TestNativeDarwinWriterMethod checks the blocked-writer method's own observations
// with simulated native I/O. It catches mislabeled or lost observations; it says
// nothing about the Darwin kernel or the Go poller.
func TestNativeDarwinWriterMethod(t *testing.T) {
	t.Run("the request deadline is installed unchanged and a simulated wait is not traversal", func(t *testing.T) {
		synctest.Test(t, func(t *testing.T) {
			record := &nativeDarwinIO{native: endpointTestNative{send: func([]byte) (int, error) {
				time.Sleep(nativeDarwinBudget / 2)
				return 0, os.ErrDeadlineExceeded
			}}}
			e := startNativeEndpoint(record, nativeDarwinBudget, nil)
			defer func() { <-e.stop() }()
			deadline := time.Now().Add(nativeDarwinBudget / 2)
			request, datagram := nativeDarwinTrigger{capacity: 8}.datagram(netip.MustParseAddrPort("127.0.0.1:1234"), deadline, 8)
			require.NoError(t, e.offer(e.public, 0, request))
			synctest.Wait()
			require.NotNil(t, nativeDarwinHeld(e, datagram), "the simulated wait holds the borrow")
			require.False(t, nativeDarwinWriterWaiting(), "a simulated wait is not in the Go poller")
			result := <-datagram.result
			require.ErrorIs(t, result.failure(), os.ErrDeadlineExceeded)
			claim := record.claim(0)
			require.True(t, claim.installed.Equal(deadline))
			require.True(t, claim.reset)
			require.True(t, claim.returned())
			require.Equal(t, "simulated", claim.class(deadline, true), "not a socket, even with a witness")
			require.Equal(t, "stale-deadline", claim.class(deadline.Add(time.Nanosecond), true))
		})
	})

	t.Run("an injected errno on the real socket is never native traversal", func(t *testing.T) {
		socket := nativeDarwinListen("udp4", net.IPv4(127, 0, 0, 1))(t)
		record := &nativeDarwinIO{native: socket, socket: true, inject: func(int) error { return nativeDarwinSendmsgError(syscall.EAGAIN) }}
		e := startNativeEndpoint(record, nativeDarwinBudget, nil)
		defer func() { <-e.stop() }()
		deadline := time.Now().Add(nativeDarwinBudget)
		request, datagram := nativeDarwinTrigger{}.datagram(socket.LocalAddr().(*net.UDPAddr).AddrPort(), deadline, 8)
		require.NoError(t, e.offer(e.public, 0, request))
		result, _ := nativeDarwinDatagramResult(t, datagram)
		require.ErrorIs(t, result.failure(), syscall.EAGAIN)
		claim := record.claim(0)
		require.Equal(t, 1, claim.injected)
		require.Equal(t, "simulated", claim.class(deadline, true))
		claim.injected = 0
		require.Equal(t, "no-witness", claim.class(deadline, false), "a native return without the poller witness")
		require.Equal(t, "native-traversal", claim.class(deadline, true))
	})

	t.Run("a request expired before dispatch makes no native call", func(t *testing.T) {
		synctest.Test(t, func(t *testing.T) {
			record := &nativeDarwinIO{native: endpointTestNative{}}
			e := startNativeEndpoint(record, nativeDarwinBudget, nil)
			defer func() { <-e.stop() }()
			deadline := time.Now().Add(-time.Millisecond)
			request, datagram := nativeDarwinTrigger{}.datagram(netip.MustParseAddrPort("127.0.0.1:1234"), deadline, 8)
			require.NoError(t, e.offer(e.public, 0, request))
			result := <-datagram.result
			require.ErrorIs(t, result.failure(), os.ErrDeadlineExceeded)
			require.Equal(t, [3]int{0, 0, 1}, nativeDarwinCounts(result.members[0]))
			require.Nil(t, record.claim(0))
			require.Equal(t, "expired-before-dispatch", record.claim(0).class(deadline, true))
			require.Equal(t, "unclaimed", record.claim(0).expiredClass(deadline), "queued expiry is never a claim")
		})
	})

	t.Run("a claim that expires in deadline setup is its own class and the successor is another claim", func(t *testing.T) {
		synctest.Test(t, func(t *testing.T) {
			record := &nativeDarwinIO{native: endpointTestNative{}, hold: nativeDarwinHoldUntilDeadline(0)}
			e := startNativeEndpoint(record, nativeDarwinBudget, nil)
			defer func() { <-e.stop() }()
			destination := netip.MustParseAddrPort("127.0.0.1:1234")
			deadline := time.Now().Add(nativeDarwinBudget / 2)
			request, datagram := nativeDarwinTrigger{}.datagram(destination, deadline, 8)
			require.NoError(t, e.offer(e.public, 0, request))
			result := <-datagram.result
			require.ErrorIs(t, result.failure(), os.ErrDeadlineExceeded)
			require.Equal(t, [3]int{0, 0, 1}, nativeDarwinCounts(result.members[0]))
			expired := record.claim(0)
			require.NotNil(t, expired, "the request was claimed")
			require.False(t, expired.installedAt.IsZero(), "the deadline was installed")
			require.True(t, expired.installedAt.Before(deadline), "installed before its deadline")
			require.Zero(t, expired.calls)
			require.True(t, expired.reset)
			require.Equal(t, "expired-before-dispatch", expired.class(deadline, true), "still a traversal failure")
			require.Equal(t, "simulated", expired.expiredClass(deadline), "not a socket")
			expired.socket = true
			require.Equal(t, "expired-claim-unsubmitted", expired.expiredClass(deadline))
			require.Equal(t, "stale-deadline", expired.expiredClass(deadline.Add(time.Nanosecond)))
			unreset, refused, injected := *expired, *expired, *expired
			unreset.reset = false
			refused.resetErr = errors.New("reset refused")
			injected.injected = 1
			require.Equal(t, "reset-failure", unreset.expiredClass(deadline))
			require.Equal(t, "reset-failure", refused.expiredClass(deadline))
			require.Equal(t, "simulated", injected.expiredClass(deadline))

			// The successor is a separate claim under its own deadline, offered behind the
			// retry floor as a producer does.
			successorDeadline := time.Now().Add(nativeDarwinBudget / 2)
			request, datagram = nativeDarwinTrigger{}.datagram(destination, successorDeadline, 8)
			for err := e.offer(e.public, 0, request); err != nil; err = e.offer(e.public, 0, request) {
				require.ErrorIs(t, err, errEndpointCapacity)
				time.Sleep(endpointRetry)
			}
			result = <-datagram.result
			require.NoError(t, result.failure())
			require.Equal(t, [3]int{1, 0, 0}, nativeDarwinCounts(result.members[0]))
			require.Equal(t, 2, record.claimCount())
			successor := record.claim(1)
			require.True(t, successor.installed.Equal(successorDeadline))
			require.Equal(t, 1, successor.calls)
			require.Equal(t, "dispatched", successor.expiredClass(successorDeadline))
			require.Equal(t, "unclaimed", record.claim(2).expiredClass(successorDeadline))
		})
	})

	t.Run("an interrupted observation reports the missing return and cleanup waits for it", func(t *testing.T) {
		synctest.Test(t, func(t *testing.T) {
			release := make(chan struct{})
			record := &nativeDarwinIO{native: endpointTestNative{send: func(data []byte) (int, error) {
				<-release
				return len(data), nil
			}}}
			e := startNativeEndpoint(record, nativeDarwinBudget, nil)
			var once sync.Once
			unblock := func() { once.Do(func() { close(release) }) }
			defer func() { unblock(); <-e.stop() }()
			deadline := time.Now().Add(nativeDarwinBudget)
			request, datagram := nativeDarwinTrigger{}.datagram(netip.MustParseAddrPort("127.0.0.1:1234"), deadline, 8)
			require.NoError(t, e.offer(e.public, 0, request))
			synctest.Wait()
			// The observation ends here, with the native call still outstanding.
			require.Equal(t, "missing-native-return", record.claim(0).class(deadline, true))
			token := nativeDarwinHeld(e, datagram)
			require.NotNil(t, token)
			stopped := e.stop()
			synctest.Wait()
			select {
			case <-stopped:
				require.FailNow(t, "the endpoint joined before the native return")
			default:
			}
			require.Nil(t, token.completion.Load(), "the borrow stays live until the native return")
			unblock()
			<-stopped
			require.NotNil(t, token.completion.Load(), "the writer published the borrow before its exit")
			require.True(t, record.claim(0).returned())
		})
	})

	t.Run("queued expiry is timed from the endpoint's decision", func(t *testing.T) {
		deadline := time.Now()
		seen := deadline.Add(9 * time.Millisecond)
		at := func(d time.Duration) monotime.Time { return monotime.FromTime(deadline.Add(d)) }
		expiry, publication, err := nativeDarwinQueuedExpiryTiming(at(2*time.Millisecond), deadline, seen)
		require.NoError(t, err)
		require.Equal(t, 2*time.Millisecond, expiry, "the decision, not the observation")
		require.Equal(t, 7*time.Millisecond, publication, "collection delay is publication, never expiry")
		_, _, err = nativeDarwinQueuedExpiryTiming(at(0), deadline, seen)
		require.NoError(t, err, "a decision at the deadline is on time")
		_, _, err = nativeDarwinQueuedExpiryTiming(at(9*time.Millisecond), deadline, seen)
		require.NoError(t, err, "a decision at the observation is not after it")
		_, _, err = nativeDarwinQueuedExpiryTiming(0, deadline, seen)
		require.ErrorContains(t, err, "no expiry decision")
		_, _, err = nativeDarwinQueuedExpiryTiming(at(-time.Millisecond), deadline, seen)
		require.ErrorContains(t, err, "before its deadline")
		_, _, err = nativeDarwinQueuedExpiryTiming(at(10*time.Millisecond), deadline, seen)
		require.ErrorContains(t, err, "after the fixture observed it")
	})

	t.Run("a late collection is publication, not queued expiry", func(t *testing.T) {
		synctest.Test(t, func(t *testing.T) {
			release := make(chan struct{})
			record := &nativeDarwinIO{native: endpointTestNative{send: func(data []byte) (int, error) {
				<-release
				return len(data), nil
			}}}
			e := startNativeEndpoint(record, nativeDarwinBudget, nil)
			var once sync.Once
			unblock := func() { once.Do(func() { close(release) }) }
			defer func() { unblock(); <-e.stop() }()
			p, err := e.attach(1)
			require.NoError(t, err)
			destination := netip.MustParseAddrPort("127.0.0.1:1234")
			start := time.Now()
			current, datagram := nativeDarwinTrigger{}.datagram(destination, start.Add(nativeDarwinBudget), 8)
			require.NoError(t, e.offer(e.public, 0, current))
			synctest.Wait()
			require.NotNil(t, nativeDarwinHeld(e, datagram), "the current request holds the writer")
			queuedDeadline := start.Add(nativeDarwinBudget / 2)
			require.NoError(t, e.offer(p, 0, endpointRequest{
				identity:    endpointIdentity{connection: 1, registration: 2},
				destination: destination,
				members:     []endpointMember{{buffer: endpointTestBuffer("queued")}},
				deadline:    queuedDeadline,
			}))
			// The fixture collects the expired result well after the endpoint decided it.
			const delay = 7 * time.Millisecond
			time.Sleep(time.Until(queuedDeadline) + delay)
			queued, ok := e.take(p)
			seen := time.Now()
			require.True(t, ok)
			require.ErrorIs(t, queued.failure(), os.ErrDeadlineExceeded)
			require.Equal(t, [3]int{0, 0, 1}, nativeDarwinCounts(queued.members[0]))
			expiry, publication, err := nativeDarwinQueuedExpiryTiming(queued.members[0].returnedAt, queuedDeadline, seen)
			require.NoError(t, err)
			require.Zero(t, expiry, "the endpoint expired the queued request at its deadline")
			require.Equal(t, delay, publication, "the collection delay")
			require.Equal(t, 1, record.claimCount(), "the expired request was never claimed")
		})
	})

	t.Run("a final deadline reset failure is its own class", func(t *testing.T) {
		synctest.Test(t, func(t *testing.T) {
			resetErr := errors.New("reset refused")
			record := &nativeDarwinIO{native: endpointTestNative{deadline: func(deadline time.Time) error {
				if deadline.IsZero() {
					return resetErr
				}
				return nil
			}}}
			e := startNativeEndpoint(record, nativeDarwinBudget, nil)
			defer func() { <-e.stop() }()
			deadline := time.Now().Add(nativeDarwinBudget)
			request, datagram := nativeDarwinTrigger{}.datagram(netip.MustParseAddrPort("127.0.0.1:1234"), deadline, 8)
			require.NoError(t, e.offer(e.public, 0, request))
			result := <-datagram.result
			require.ErrorIs(t, result.err, resetErr, "the reset failure is the request's own error")
			require.Equal(t, [3]int{1, 0, 0}, nativeDarwinCounts(result.members[0]), "it never rewrites member facts")
			require.ErrorIs(t, record.claim(0).resetErr, resetErr)
			require.Equal(t, "reset-failure", record.claim(0).class(deadline, true))
		})
	})

	t.Run("a protected BBR member stays borrowed through the native return and the final fence", func(t *testing.T) {
		nativeOrdinaryTest(t, func(t *testing.T) {
			lifetime, closed, seen, class := nativeDarwinSimulatedProtected(t, "bbrv3", true, protocol.ECT0)
			require.True(t, lifetime.planned, "a frozen plan the writer had yet to apply")
			require.True(t, lifetime.bbr, "bbrv3 with its reservation credit")
			require.True(t, seen.applied, "the writer applied the plan before the native call")
			require.True(t, lifetime.ciphertext, "the native call carried the peer-opened ciphertext")
			require.True(t, lifetime.call.borrowed(), "the simulated call holds the member")
			require.True(t, closed.borrowed(), "the close returns while the member is borrowed")
			require.True(t, seen.returned.borrowed(), "borrowed at the native return")
			require.True(t, seen.fenced.borrowed(), "borrowed after the final deadline reset")
			require.True(t, seen.joinOpenAtFence, "the join waits for the fence")
			require.True(t, lifetime.released, "released by the join")
			require.Equal(t, "borrowed-through-fence", lifetime.class())
			require.Equal(t, "simulated", class, "a simulated writer is never native traversal")
		})
	})

	t.Run("a member without a plan or BBR credit is not the protected case's evidence", func(t *testing.T) {
		// Reno's local completions carry no ECN mark, and the mark is not under test.
		for _, tc := range []struct {
			controller string
			deferred   bool
			class      string
		}{{"bbrv3", false, "unprotected"}, {"reno", true, "not-bbr"}} {
			t.Run(tc.class, func(t *testing.T) {
				nativeOrdinaryTest(t, func(t *testing.T) {
					lifetime, _, _, _ := nativeDarwinSimulatedProtected(t, tc.controller, tc.deferred, protocol.ECNNon)
					require.Equal(t, tc.class, lifetime.class())
				})
			})
		}
	})

	t.Run("each protected lifetime failure is its own class, first failure first", func(t *testing.T) {
		borrowed := nativeDarwinBorrow{sampled: true, held: true, buffer: true, plan: true}
		complete := nativeDarwinProtectedLifetime{planned: true, bbr: true, ciphertext: true, call: borrowed, returned: borrowed, fenced: borrowed, released: true}
		require.Equal(t, "borrowed-through-fence", complete.class())
		for _, tc := range []struct {
			class  string
			mutate func(*nativeDarwinProtectedLifetime)
		}{
			{"unprotected", func(l *nativeDarwinProtectedLifetime) { l.planned, l.bbr = false, false }},
			{"not-bbr", func(l *nativeDarwinProtectedLifetime) { l.bbr, l.ciphertext = false, false }},
			{"plaintext-at-native-call", func(l *nativeDarwinProtectedLifetime) { l.ciphertext, l.call.held = false, false }},
			{"released-during-call", func(l *nativeDarwinProtectedLifetime) { l.call.buffer, l.returned.plan = false, false }},
			{"released-during-call", func(l *nativeDarwinProtectedLifetime) { l.call.sampled = false }},
			{"released-at-return", func(l *nativeDarwinProtectedLifetime) { l.returned.plan, l.fenced.held = false, false }},
			{"released-at-return", func(l *nativeDarwinProtectedLifetime) { l.returned.sampled = false }},
			{"released-before-fence", func(l *nativeDarwinProtectedLifetime) { l.fenced.held, l.released = false, false }},
			{"released-before-fence", func(l *nativeDarwinProtectedLifetime) { l.fenced.buffer = false }},
			{"not-released", func(l *nativeDarwinProtectedLifetime) { l.released = false }},
		} {
			lifetime := complete
			tc.mutate(&lifetime)
			require.Equal(t, tc.class, lifetime.class())
		}
	})
}
