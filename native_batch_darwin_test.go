//go:build darwin && !ios && !quic_go_no_private_syscalls

package quic

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"net"
	"net/netip"
	"os"
	"runtime"
	"strings"
	"sync/atomic"
	"syscall"
	"testing"
	"time"

	"github.com/GridCastIO/quicquic-go/internal/handshake"
	"github.com/GridCastIO/quicquic-go/internal/monotime"
	"github.com/GridCastIO/quicquic-go/internal/protocol"
	"github.com/stretchr/testify/require"
)

// requireNativeBatchQualified starts each case from a freshly qualified sendmsg_x
// capability. It runs before the endpoint starts, so the reset in its cleanup runs
// after the endpoint's writer has stopped.
func requireNativeBatchQualified(t *testing.T) {
	t.Helper()
	major, err := getMacOSVersion()
	require.NoError(t, err)
	if _, ok := sendmsgXQualifiedKernel(major, runtime.GOARCH); !ok {
		t.Skipf("unqualified Darwin kernel %d", major)
	}
	resetSendmsgXForTesting(t)
	sendmsgXEnsureQualified()
	require.True(t, sendmsgXAvailable())
}

// newNativeBatchWriter is the production writer directly over a real loopback
// socket, with no recorder in between, so the batch hook can engage.
func newNativeBatchWriter(t *testing.T) *nativeDarwinWriter {
	t.Helper()
	socket := nativeDarwinListen("udp4", net.IPv4(127, 0, 0, 1))(t)
	peerSocket := nativeDarwinListen("udp4", net.IPv4(127, 0, 0, 1))(t)
	destination := peerSocket.LocalAddr().(*net.UDPAddr).AddrPort()
	w := &nativeDarwinWriter{
		peer:        newNativeDarwinReader(t, peerSocket),
		destination: destination,
		trigger:     nativeDarwinTrigger{control: packetOOB(nil, destination, protocol.ECT0)},
	}
	w.e = startNativeEndpoint(socket, nativeDarwinBudget, nil)
	t.Cleanup(func() { <-w.e.stop() })
	p, err := w.e.attach(1)
	require.NoError(t, err)
	w.p = p
	return w
}

// nativeBatchSegments returns count distinct segments of size bytes, except a
// shorter final segment, as a software-segmented member carries them.
func nativeBatchSegments(count, size int) []string {
	segments := make([]string, count)
	for i := range segments {
		segments[i] = fmt.Sprintf("%-*s", size, fmt.Sprintf("segment-%02d", i))
	}
	segments[count-1] = segments[count-1][:size/2]
	return segments
}

func (w *nativeDarwinWriter) segmented(registration uint64, segments []string, size int) endpointRequest {
	request := w.request(registration, strings.Join(segments, ""), time.Now().Add(nativeDarwinBudget))
	request.members[0].gsoSize = uint16(size)
	return request
}

func (w *nativeDarwinWriter) readSegments(t *testing.T, segments []string) {
	t.Helper()
	for _, want := range segments {
		payload, ecn := w.read(t)
		require.Equal(t, want, payload, "segments arrive whole and in order")
		require.Equal(t, protocol.ECT0, ecn, "the member's control applies to every segment")
	}
}

// A software-segmented member on the granted socket is submitted in sendmsg_x
// chunks of at most maxSendBatch datagrams.
func TestNativeSoftwareBatchedSegments(t *testing.T) {
	requireNativeBatchQualified(t)
	w := newNativeBatchWriter(t)
	segments := nativeBatchSegments(40, 16)

	submissions, packets, _ := sendmsgXCountersSnapshot()
	result := w.send(t, w.segmented(1, segments, 16))
	require.NoError(t, result.failure())
	require.Equal(t, [3]int{40, 0, 0}, nativeDarwinCounts(result.members[0]))
	submissionsAfter, packetsAfter, _ := sendmsgXCountersSnapshot()
	require.Equal(t, uint64(2), submissionsAfter-submissions, "32 segments, then the remaining 8")
	require.Equal(t, uint64(40), packetsAfter-packets, "every segment went through sendmsg_x")
	w.readSegments(t, segments)
}

// The first datagram on a fresh write state keeps its scalar EPERM retry; only the
// rest of the member is batched.
func TestNativeSoftwareBatchFirstDatagramScalar(t *testing.T) {
	requireNativeBatchQualified(t)
	w := newNativeBatchWriter(t)
	segments := nativeBatchSegments(5, 16)
	request := w.segmented(1, segments, 16)
	request.members[0].writeState = &endpointWriteState{}

	submissions, packets, _ := sendmsgXCountersSnapshot()
	result := w.send(t, request)
	require.NoError(t, result.failure())
	require.Equal(t, [3]int{5, 0, 0}, nativeDarwinCounts(result.members[0]))
	submissionsAfter, packetsAfter, _ := sendmsgXCountersSnapshot()
	require.Equal(t, uint64(1), submissionsAfter-submissions)
	require.Equal(t, uint64(4), packetsAfter-packets, "the first datagram stayed scalar")
	w.readSegments(t, segments)
}

// nativeBatchHookedRaw runs after once each dispatched or refused raw write returns.
type nativeBatchHookedRaw struct {
	syscall.RawConn
	after func()
}

func (r nativeBatchHookedRaw) Write(f func(uintptr) bool) error {
	err := r.RawConn.Write(f)
	r.after()
	return err
}

// The submission gate runs before every chunk: a deadline that passes after the
// first chunk leaves the rest of the member unsubmitted, never uncertain, and
// nothing more reaches the socket.
func TestNativeSoftwareBatchExpiryBetweenChunks(t *testing.T) {
	requireNativeBatchQualified(t)
	socket := nativeDarwinListen("udp4", net.IPv4(127, 0, 0, 1))(t)
	peerSocket := nativeDarwinListen("udp4", net.IPv4(127, 0, 0, 1))(t)
	destination := peerSocket.LocalAddr().(*net.UDPAddr).AddrPort()
	raw, err := socket.SyscallConn()
	require.NoError(t, err)
	segments := nativeBatchSegments(40, 16)
	token := &endpointToken{request: &endpointRequest{
		destination: destination,
		deadline:    time.Now().Add(time.Minute),
		members: []endpointMember{{
			buffer: endpointTestBuffer(strings.Join(segments, "")), gsoSize: 16,
			oob: packetOOB(nil, destination, protocol.ECT0),
		}},
	}}
	batch := &nativeSegmentBatch{darwinBatch: darwinBatch{raw: nativeBatchHookedRaw{RawConn: raw, after: func() {
		token.request.deadline = time.Now().Add(-time.Millisecond)
	}}}}

	submissions, _, _ := sendmsgXCountersSnapshot()
	var scratch handshake.PacketProtectionScratch
	var oobScratch [128]byte
	result := writeEndpointRequestWithScratch(socket, batch, token, &scratch, oobScratch[:0])
	require.ErrorIs(t, result.failure(), os.ErrDeadlineExceeded)
	require.Equal(t, [3]int{32, 0, 8}, nativeDarwinCounts(result.members[0]), "accepted chunk, untouched suffix")
	submissionsAfter, _, _ := sendmsgXCountersSnapshot()
	require.Equal(t, uint64(1), submissionsAfter-submissions, "the expired suffix made no call")

	peer := newNativeDarwinReader(t, peerSocket)
	for _, want := range segments[:32] {
		payload, _ := peer.read(t)
		require.Equal(t, want, payload)
	}
	require.NoError(t, peerSocket.SetReadDeadline(time.Now().Add(scaleDuration(100*time.Millisecond))))
	_, _, err = peerSocket.ReadFrom(make([]byte, 64))
	require.ErrorIs(t, err, os.ErrDeadlineExceeded, "nothing past the deadline reached the peer")
}

// Without a qualified capability the granted writer stays scalar: it consults the
// capability, submits no batch and delivers every segment.
func TestNativeSoftwareBatchFallback(t *testing.T) {
	for _, mode := range []string{"disabled", "unqualified", "architecture"} {
		t.Run(mode, func(t *testing.T) {
			resetSendmsgXForTesting(t)
			switch mode {
			case "disabled":
				t.Setenv(sendmsgXDisableEnv, "true")
			case "architecture":
				major, err := getMacOSVersion()
				require.NoError(t, err)
				original := qualifiedDarwinKernelMajors
				qualifiedDarwinKernelMajors = map[int]sendmsgXQualification{
					major: {product: "test-only excluded architecture", arch: "excluded"},
				}
				t.Cleanup(func() { qualifiedDarwinKernelMajors = original })
			case "unqualified":
				original := sendmsgXKernelMajor
				sendmsgXKernelMajor = func() (int, error) { return -1, nil }
				t.Cleanup(func() { sendmsgXKernelMajor = original })
			default:
				t.Fatalf("unknown fallback mode %q", mode)
			}
			sendmsgXEnsureQualified()
			require.False(t, sendmsgXAvailable())
			w := newNativeBatchWriter(t)
			segments := nativeBatchSegments(40, 16)

			submissions, _, fallback := sendmsgXCountersSnapshot()
			result := w.send(t, w.segmented(1, segments, 16))
			require.NoError(t, result.failure())
			require.Equal(t, [3]int{40, 0, 0}, nativeDarwinCounts(result.members[0]))
			submissionsAfter, _, fallbackAfter := sendmsgXCountersSnapshot()
			require.Equal(t, submissions, submissionsAfter, "no batch without the capability")
			require.Greater(t, fallbackAfter, fallback, "the declined consultation is observable")
			w.readSegments(t, segments)
		})
	}
}

// Production emission of confirmed ordinary Reno reaches the socket through
// sendmsg_x: the constructor builds software segments and the granted writer
// batches them. No member is built by hand.
func TestNativeSoftwareRenoEmissionBatches(t *testing.T) {
	requireNativeBatchQualified(t)
	socket := nativeDarwinListen("udp4", net.IPv4(127, 0, 0, 1))(t)
	peerSocket := nativeDarwinListen("udp4", net.IPv4(127, 0, 0, 1))(t)
	peer := newNativeDarwinReader(t, peerSocket)
	endpoint := startNativeEndpoint(socket, nativeDarwinBudget, nil)
	t.Cleanup(func() { <-endpoint.stop() })
	conf := &Config{InitialPacketSize: 1200, DisablePathMTUDiscovery: true}
	require.NoError(t, conf.SetCongestionControlV1("reno"))
	tc := newConfiguredEmissionTestConnection(t, false, conf)
	c := tc.conn
	c.rttStats.UpdateRTT(100*time.Microsecond, 0)
	require.NoError(t, c.useNativeOrdinary(endpoint, peerSocket.LocalAddr().(*net.UDPAddr).AddrPort(), packetInfo{}))
	sender := c.emission.local.(*nativeOrdinarySender)
	t.Cleanup(sender.Close)
	queueNativeSoftwareStream(t, c)

	submissions, batched, _ := sendmsgXCountersSnapshot()
	result := c.emission.send(monotime.Now(), true)
	require.NoError(t, result.err)
	require.True(t, result.progress)
	// The endpoint owns the request's descriptors once admitted; the sender's
	// sidecar keeps each member's datagram count and bytes until Free.
	var records []*ordinaryLocalRecord
	var datagrams, size, segmented int
	for i := range sender.records {
		r := &sender.records[i]
		if r.state == ordinaryFree {
			continue
		}
		records = append(records, r)
		for _, member := range r.members {
			datagrams += member.datagrams
			size += int(member.bytes)
			if member.datagrams > 1 {
				segmented++
			}
		}
	}
	require.Greater(t, datagrams, 2, "the turn emitted enough packets to batch")
	require.NotZero(t, segmented, "production construction built a multi-datagram member")
	timeout := time.After(scaleDuration(5 * time.Second))
	for _, r := range records {
		for r.state != ordinaryFree {
			require.NoError(t, sender.consume())
			if r.state == ordinaryFree {
				break
			}
			select {
			case <-sender.completed():
			case <-timeout:
				require.FailNow(t, "the sender never settled the turn's records")
			}
		}
	}
	var received int
	for range datagrams {
		payload, _ := peer.read(t)
		require.LessOrEqual(t, len(payload), 1200, "each segment arrives as its own datagram")
		received += len(payload)
	}
	require.Equal(t, size, received, "every byte of the turn arrived")
	require.NoError(t, peerSocket.SetReadDeadline(time.Now().Add(scaleDuration(100*time.Millisecond))))
	_, _, err := peerSocket.ReadFrom(make([]byte, 1500))
	require.ErrorIs(t, err, os.ErrDeadlineExceeded, "no extra datagram arrived")
	submissionsAfter, batchedAfter, _ := sendmsgXCountersSnapshot()
	require.Greater(t, submissionsAfter, submissions, "Reno's software segments went through sendmsg_x")
	require.Greater(t, batchedAfter-batched, submissionsAfter-submissions, "each submission carried more than one datagram")
}

// nativeBBRBorrowCapture is what the observation hook copies from the endpoint's
// current request inside the member's own sendmsg_x call.
type nativeBBRBorrowCapture struct {
	observed, protected, nativeGSO bool
	members, datagrams             int
	recipes                        []nativeProtectionRecipe
	// The borrow's state after the hook's transaction's first advance.
	stillCurrent       bool
	published, credits int
}

// One ordinary BBR opportunity, built by production emission on a real endpoint
// socket, reaches the raw peer datagram by datagram through sendmsg_x (#1595):
// every datagram is its own packet's ciphertext, with its recipe's length. The
// batching verdict comes from the quiescent counters, not from the hook.
// Not parallel: rawSendmsgX and the sendmsg_x counters are process-wide.
func TestBBRNativeSoftwareEmissionBatches(t *testing.T) {
	requireNativeBatchQualified(t)
	socket := nativeDarwinListen("udp4", net.IPv4(127, 0, 0, 1))(t)
	peerSocket := nativeDarwinListen("udp4", net.IPv4(127, 0, 0, 1))(t)
	peer := newNativeDarwinReader(t, peerSocket)

	// The hook wraps the existing injection seam and still calls the real
	// syscall. Registered before the endpoint's stop, its restore runs after the
	// writer is joined, on every path.
	var endpoint *nativeEndpoint
	var participant *endpointParticipant
	var capture nativeBBRBorrowCapture // guarded by endpoint control
	var entered atomic.Bool            // the hook enters endpoint control once
	original := rawSendmsgX
	t.Cleanup(func() { rawSendmsgX = original })
	rawSendmsgX = func(fd int, msgs []msghdrX) (int, syscall.Errno) {
		if entered.Swap(true) {
			return original(fd, msgs)
		}
		// The writer makes native calls outside endpoint control (write), so it
		// can enter control here, as other owners do during any native call. Neither
		// of this one transaction's advances can settle the borrow: the writer has
		// not published its completion, so reconcileCurrent leaves the current
		// token fenced unless it is past deadline plus tolerance, and only expired
		// or revoked queued records are published. The borrow-state fields below
		// check the first advance's result: the member is still current, nothing
		// was published, and no credit was detached for return.
		endpoint.do(func(s *endpointState) {
			token := s.current
			if token == nil || token.request.identity.connection != participant.id {
				return
			}
			capture.observed = true
			capture.members = len(token.request.members)
			member := token.request.members[0]
			capture.protected = member.protection != nil
			capture.nativeGSO = member.nativeGSO
			capture.datagrams = member.datagrams()
			if member.protection != nil {
				for _, recipe := range member.protection.entries {
					recipe.protection = handshake.PacketProtection{} // geometry only
					capture.recipes = append(capture.recipes, recipe)
				}
			}
			capture.stillCurrent = s.current == token
			capture.published = len(participant.results)
			capture.credits = len(s.credits)
		})
		return original(fd, msgs)
	}
	endpoint = startNativeEndpoint(socket, nativeDarwinBudget, nil)
	t.Cleanup(func() { <-endpoint.stop() })

	conf := &Config{InitialPacketSize: 1200, EnableDatagrams: true}
	require.NoError(t, conf.SetCongestionControlV1("bbrv3"))
	tc := newConfiguredEmissionTestConnection(t, false, conf)
	c := tc.conn
	c.rttStats.UpdateRTT(5*time.Millisecond, 0)
	require.True(t, c.emission.softwareBBRSegments, "Darwin builds BBR software segments")
	require.NoError(t, c.useNativeOrdinary(endpoint, peerSocket.LocalAddr().(*net.UDPAddr).AddrPort(), packetInfo{}))
	sender := c.emission.local.(*nativeOrdinarySender)
	t.Cleanup(sender.Close)
	participant = sender.participant
	native := c.conn.(*nativeOrdinaryConn)
	native.sendConn = &countingCapabilitiesConn{sendConn: native.sendConn} // no wire GSO
	now := seedLargeBBRWindow(t, c, 65536)
	opener := softwareBBRProtection(t, c)
	payloads := largeBBRPayloads(t, c, softwareBBRFullPayload(c, sender), 70)

	submissions, batched, _ := sendmsgXCountersSnapshot()
	result := c.emission.send(now, true)
	require.NoError(t, result.err)
	require.True(t, result.progress)
	var records []*ordinaryLocalRecord
	for i := range sender.records {
		if r := &sender.records[i]; r.state != ordinaryFree {
			records = append(records, r)
		}
	}
	require.NotEmpty(t, records)
	timeout := time.After(scaleDuration(5 * time.Second))
	for _, r := range records {
		for r.state != ordinaryFree {
			require.NoError(t, sender.consume())
			if r.state == ordinaryFree {
				break
			}
			select {
			case <-sender.completed():
			case <-timeout:
				require.FailNow(t, "the sender never settled the turn's records")
			}
		}
	}
	// Every call this endpoint made has returned and its records have settled.
	submissionsAfter, batchedAfter, _ := sendmsgXCountersSnapshot()
	require.Zero(t, c.emission.bbr.credit.pending, "the member's credit returned")

	var observed nativeBBRBorrowCapture
	endpoint.do(func(*endpointState) { observed = capture })
	require.True(t, observed.observed, "the hook saw the member inside its sendmsg_x call")
	require.Equal(t, 1, observed.members, "one opportunity makes one member")
	require.True(t, observed.protected, "the writer protects the member from its plan")
	require.False(t, observed.nativeGSO, "Darwin has no wire GSO")
	require.Greater(t, observed.datagrams, 1, "a multi-datagram software member")
	require.Len(t, observed.recipes, observed.datagrams)
	require.True(t, observed.stillCurrent, "the hook's transaction left the member current")
	require.Zero(t, observed.published, "no result was published during the borrow")
	require.Zero(t, observed.credits, "no credit was returned during the borrow")

	cidLen := c.connIDManager.Get().Len()
	for i, recipe := range observed.recipes {
		payload, _ := peer.read(t)
		datagram := []byte(payload)
		require.Len(t, datagram, int(recipe.end-recipe.start), "datagram %d has its recipe's length", i)
		plain := largeBBRPlaintext(t, opener, datagram, cidLen, recipe)
		require.True(t, bytes.Contains(plain, payloads[i]), "datagram %d is its own packet's ciphertext", i)
	}
	require.NoError(t, peerSocket.SetReadDeadline(time.Now().Add(scaleDuration(100*time.Millisecond))))
	_, _, err := peerSocket.ReadFrom(make([]byte, 1500))
	require.ErrorIs(t, err, os.ErrDeadlineExceeded, "no extra datagram arrived")
	require.Greater(t, submissionsAfter, submissions, "BBR's software segments went through sendmsg_x")
	require.Greater(t, batchedAfter-batched, submissionsAfter-submissions, "average datagrams per sendmsg_x call > 1")
}

// Over public Dial and Listen, with both transports granted so every QUIC send
// goes through a native writer, a Reno bulk transfer is submitted through
// sendmsg_x. Not parallel: the sendmsg_x counters are process-wide.
func TestNativeSoftwareGrantedRenoTransferBatches(t *testing.T) {
	nativeGrantedTransferBatches(t, "reno")
}

// The same transfer under BBR builds software-segmented members (#1590), which
// the granted writer also submits through sendmsg_x.
func TestBBRNativeSoftwareGrantedTransferBatches(t *testing.T) {
	nativeGrantedTransferBatches(t, "bbrv3")
}

// nativeGrantedTransferBatches sends 4 MiB over public Dial and Listen between
// two granted transports using controller, and requires the transfer to arrive
// intact through sendmsg_x calls that average more than one datagram each.
func nativeGrantedTransferBatches(t *testing.T, controller string) {
	t.Helper()
	requireNativeBatchQualified(t)
	// Each sendmsg_x call counts its submission before its datagrams, so a
	// snapshot taken while a writer is live can see a call's datagrams without its
	// submission (#1596). The deltas span from before any writer exists to after
	// every writer is joined, so they cover only completed calls.
	submissions, batched, _ := sendmsgXCountersSnapshot()
	// Each writer is also joined by its own cleanup, so a failure partway through
	// still joins it before the capability reset registered above.
	server := nativeDarwinGrant(t, newUDPConnLocalhost(t))
	nativeDarwinJoinOnCleanup(t, server)
	client := nativeDarwinGrant(t, newUDPConnLocalhost(t))
	nativeDarwinJoinOnCleanup(t, client)
	config := func() *Config {
		conf := &Config{}
		require.NoError(t, conf.SetCongestionControlV1(controller))
		return conf
	}
	ctx, cancel := context.WithTimeout(t.Context(), scaleDuration(10*time.Second))
	defer cancel()
	listener, err := server.Listen(nativeServerTLS(), config())
	require.NoError(t, err)
	conn, err := client.Dial(ctx, listener.Addr(), nativeClientTLS(), config())
	require.NoError(t, err)
	accepted, err := listener.Accept(ctx)
	require.NoError(t, err)
	require.Equal(t, controller, accepted.CongestionControlV1())

	payload := make([]byte, 4<<20)
	for i := range payload {
		payload[i] = byte(i % 251)
	}
	str, err := conn.OpenStreamSync(ctx)
	require.NoError(t, err)
	_, err = str.Write([]byte("go"))
	require.NoError(t, err)
	served, err := accepted.AcceptStream(ctx)
	require.NoError(t, err)
	_, err = io.ReadFull(served, make([]byte, 2))
	require.NoError(t, err)
	written := make(chan error, 1)
	go func() {
		_, err := served.Write(payload)
		if err == nil {
			err = served.Close()
		}
		written <- err
	}()
	deadline, ok := ctx.Deadline()
	require.True(t, ok)
	require.NoError(t, str.SetReadDeadline(deadline))
	data, err := io.ReadAll(str)
	require.NoError(t, err)
	require.NoError(t, <-written)
	require.True(t, bytes.Equal(payload, data), "the transfer arrived intact")
	require.NoError(t, conn.CloseWithError(0, ""))
	nativeDarwinJoin(t, server)
	nativeDarwinJoin(t, client)
	submissionsAfter, batchedAfter, _ := sendmsgXCountersSnapshot()
	require.Greater(t, submissionsAfter, submissions, "the granted %s sender used sendmsg_x", controller)
	require.Greater(t, batchedAfter-batched, submissionsAfter-submissions, "average datagrams per sendmsg_x call > 1")
}

// nativeDarwinJoinOnCleanup joins tr's writer in its own cleanup. Go cancels
// t.Context before cleanups run, so the wait gets a fresh bounded context.
func nativeDarwinJoinOnCleanup(t *testing.T, tr *Transport) {
	t.Helper()
	t.Cleanup(func() {
		require.NoError(t, tr.Close())
		ctx, cancel := context.WithTimeout(context.Background(), scaleDuration(5*time.Second))
		defer cancel()
		require.NoError(t, tr.waitNativeIOStopped(ctx))
	})
}

// A named IPv6 zone stays scalar: the hook declines before dispatch, so a cached
// sockaddr can't carry an interface index the name no longer resolves to.
func TestNativeSoftwareBatchNamedZoneScalar(t *testing.T) {
	requireNativeBatchQualified(t)
	socket, err := net.ListenUDP("udp6", &net.UDPAddr{IP: net.IPv6loopback})
	if err != nil {
		t.Skipf("no IPv6 loopback: %v", err)
	}
	t.Cleanup(func() { socket.Close() })
	batch := newNativeSegmentBatch(socket)
	require.NotNil(t, batch)
	port := socket.LocalAddr().(*net.UDPAddr).AddrPort().Port()
	// The same socket batches an unzoned destination, so the decline below is the
	// zone's, not the IPv6 family's.
	accepted, err, dispatched := batch.submit([][]byte{[]byte("a"), []byte("b")}, nil, netip.AddrPortFrom(netip.IPv6Loopback(), port))
	require.NoError(t, err)
	require.True(t, dispatched, "an unzoned IPv6 destination batches")
	require.Equal(t, 2, accepted)
	destination := netip.AddrPortFrom(netip.MustParseAddr("fe80::1%lo0"), port)
	submissions, _, _ := sendmsgXCountersSnapshot()
	accepted, err, dispatched = batch.submit([][]byte{[]byte("a"), []byte("b")}, nil, destination)
	require.NoError(t, err)
	require.False(t, dispatched, "a named zone leaves the chunk to the scalar writer")
	require.Zero(t, accepted)
	submissionsAfter, _, _ := sendmsgXCountersSnapshot()
	require.Equal(t, submissions, submissionsAfter, "nothing reached sendmsg_x")
}
