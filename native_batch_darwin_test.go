//go:build darwin && !ios && !quic_go_no_private_syscalls

package quic

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"net"
	"os"
	"runtime"
	"strings"
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
			default:
				original := sendmsgXKernelMajor
				sendmsgXKernelMajor = func() (int, error) { return -1, nil }
				t.Cleanup(func() { sendmsgXKernelMajor = original })
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

// Over public Dial and Listen, with both transports granted so every QUIC send
// goes through a native writer, a Reno bulk transfer is submitted through
// sendmsg_x. Not parallel: the sendmsg_x counters are process-wide.
func TestNativeSoftwareGrantedRenoTransferBatches(t *testing.T) {
	requireNativeBatchQualified(t)
	server := nativeDarwinGrant(t, newUDPConnLocalhost(t))
	client := nativeDarwinGrant(t, newUDPConnLocalhost(t))
	// Join both writers before the capability reset registered above.
	t.Cleanup(func() {
		nativeDarwinJoin(t, client)
		nativeDarwinJoin(t, server)
	})
	reno := func() *Config {
		conf := &Config{}
		require.NoError(t, conf.SetCongestionControlV1("reno"))
		return conf
	}
	ctx, cancel := context.WithTimeout(t.Context(), scaleDuration(10*time.Second))
	defer cancel()
	listener, err := server.Listen(nativeServerTLS(), reno())
	require.NoError(t, err)
	conn, err := client.Dial(ctx, listener.Addr(), nativeClientTLS(), reno())
	require.NoError(t, err)
	accepted, err := listener.Accept(ctx)
	require.NoError(t, err)
	require.Equal(t, "reno", accepted.CongestionControlV1())

	payload := make([]byte, 4<<20)
	for i := range payload {
		payload[i] = byte(i % 251)
	}
	submissions, batched, _ := sendmsgXCountersSnapshot()
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
	submissionsAfter, batchedAfter, _ := sendmsgXCountersSnapshot()
	require.Greater(t, submissionsAfter, submissions, "the granted Reno sender used sendmsg_x")
	require.Greater(t, batchedAfter-batched, submissionsAfter-submissions, "each submission carried more than one datagram")
	require.NoError(t, conn.CloseWithError(0, ""))
}
