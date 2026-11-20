//go:build darwin && !ios && !quic_go_no_private_syscalls

package quic

import (
	"net"
	"net/netip"
	"syscall"
)

// nativeSegmentBatch lets the granted endpoint's sole writer submit a software-segmented
// member's datagrams through the shared sendmsg_x owner (darwinBatch.submit), with
// its process-wide qualification, kill switch and latch. Only the writer goroutine
// uses it, so it needs no lock. The scalar writer stays the owner of backpressure,
// deadline waits and per-datagram error classification.
type nativeSegmentBatch struct {
	darwinBatch
	destination netip.AddrPort
	addr        *net.UDPAddr
	payloads    [][]byte
}

// newNativeSegmentBatch accepts only the granted *net.UDPConn itself, whose write
// semantics are the kernel's own. Any other endpointNativeIO stays scalar.
func newNativeSegmentBatch(native endpointNativeIO) *nativeSegmentBatch {
	socket, ok := native.(*net.UDPConn)
	if !ok || socket == nil {
		return nil
	}
	raw, err := socket.SyscallConn()
	if err != nil {
		return nil
	}
	return &nativeSegmentBatch{darwinBatch: darwinBatch{raw: raw}}
}

// writeSegments submits data's segments in chunks of at most maxSendBatch while at
// least two remain, and records each outcome in result. Before every chunk it
// passes the request's submission gate, so revocation and expiry stop the member
// with the untouched suffix unsubmitted. It returns the unwritten rest, whether the
// caller may batch again after one scalar datagram, and whether result now ends the
// member. A short count stops after the accepted prefix, so the scalar writer
// retries the first unaccepted datagram and owns any wait for writability.
func (b *nativeSegmentBatch) writeSegments(token *endpointToken, member endpointMember, data []byte, segment int, result *endpointMemberResult) (rest []byte, again, stop bool) {
	for len(data) > segment {
		if err := endpointSubmissionAllowed(token); err != nil {
			result.err = err
			return data, false, true
		}
		chunk := b.payloads[:0]
		for offset := 0; offset < len(data) && len(chunk) < maxSendBatch; offset += segment {
			chunk = append(chunk, data[offset:min(offset+segment, len(data))])
		}
		accepted, err, dispatched := b.submit(chunk, member.oob, token.request.destination)
		// Borrowed payloads must not remain reachable through cached scratch.
		clear(chunk)
		b.payloads = chunk[:0]
		if !dispatched {
			return data, false, false
		}
		if err != nil {
			// Kernel progress is unpublished: none of the chunk may be resent.
			result.err = err
			result.uncertain += len(chunk)
			result.unsubmitted -= len(chunk)
			return data, false, true
		}
		result.accepted += accepted
		result.unsubmitted -= accepted
		data = data[min(accepted*segment, len(data)):]
		if accepted < len(chunk) {
			return data, true, false
		}
	}
	return data, true, false
}

// submit offers one chunk to sendmsg_x. It reports false, leaving every datagram
// to the scalar writer, when the capability declines or the call never dispatched.
func (b *nativeSegmentBatch) submit(datagrams [][]byte, oob []byte, destination netip.AddrPort) (int, error, bool) {
	if !sendmsgXAvailable() {
		sendmsgX.fallbackPackets.Add(uint64(len(datagrams)))
		return 0, nil, false
	}
	if b.rawErr || !b.initFamily() {
		return 0, nil, false
	}
	if b.addr == nil || destination != b.destination {
		b.destination, b.addr = destination, net.UDPAddrFromAddrPort(destination)
	}
	if b.family == syscall.AF_INET && b.addr.IP.To4() == nil {
		return 0, nil, false
	}
	return b.darwinBatch.submit(datagrams, oob, b.addr)
}
