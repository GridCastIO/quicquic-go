//go:build darwin && !ios && !quic_go_no_private_syscalls

package quic

import (
	"fmt"
	"net"
	"os"
	"runtime"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/GridCastIO/quicquic-go/internal/handshake"
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
func TestNativeDarwinBatchedSegments(t *testing.T) {
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
func TestNativeDarwinBatchFirstDatagramScalar(t *testing.T) {
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
func TestNativeDarwinBatchExpiryBetweenChunks(t *testing.T) {
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
func TestNativeDarwinBatchFallback(t *testing.T) {
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
