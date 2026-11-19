//go:build darwin

package quic

import (
	"context"
	"encoding/json"
	"errors"
	"net"
	"net/netip"
	"os"
	"runtime"
	"testing"
	"time"

	"github.com/GridCastIO/quicquic-go/internal/protocol"
	"github.com/stretchr/testify/require"
)

// The runner names the case record file in nativeDarwinRecordEnv.
const (
	nativeDarwinRecordEnv = "NATIVE_DARWIN_RECORD"
	nativeDarwinSchema    = "native-darwin-case/v1"
)

type nativeDarwinRecord struct {
	Schema string         `json:"schema"`
	Case   string         `json:"case"`
	Go     string         `json:"go"`
	GOOS   string         `json:"goos"`
	GOARCH string         `json:"goarch"`
	Facts  map[string]any `json:"facts"`
}

// nativeDarwinCase writes the case record only after the case passed. The record
// file is created exclusively, so a second record in one process fails the case
// instead of replacing the first.
func nativeDarwinCase(t *testing.T, name string, f func(*testing.T, map[string]any)) {
	t.Run(name, func(t *testing.T) {
		facts := map[string]any{}
		f(t, facts)
		path := os.Getenv(nativeDarwinRecordEnv)
		if path == "" || t.Failed() {
			return
		}
		data, err := json.Marshal(nativeDarwinRecord{
			Schema: nativeDarwinSchema, Case: name, Go: runtime.Version(),
			GOOS: runtime.GOOS, GOARCH: runtime.GOARCH, Facts: facts,
		})
		require.NoError(t, err)
		file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o644)
		require.NoError(t, err)
		_, err = file.Write(append(data, '\n'))
		require.NoError(t, errors.Join(err, file.Close()))
	})
}

// nativeDarwinGrant gives a new transport the private write grant over socket.
func nativeDarwinGrant(t *testing.T, socket *net.UDPConn) *Transport {
	t.Helper()
	tr := &Transport{Conn: socket}
	require.NoError(t, tr.configureNativeIO(time.Second))
	t.Cleanup(func() { tr.Close() })
	return tr
}

// nativeDarwinJoin closes the transport and waits for the join that returns write
// and deadline authority over its socket.
func nativeDarwinJoin(t *testing.T, tr *Transport) {
	t.Helper()
	require.NoError(t, tr.Close())
	ctx, cancel := context.WithTimeout(t.Context(), scaleDuration(5*time.Second))
	defer cancel()
	require.NoError(t, tr.waitNativeIOStopped(ctx))
}

// nativeDarwinReader reads with the existing Darwin socket helpers. The write grant
// takes neither read nor read-deadline ownership, so the fixture reads the granted
// socket itself before any transport reader starts.
type nativeDarwinReader struct {
	socket *net.UDPConn
	conn   *oobConn
}

func newNativeDarwinReader(t *testing.T, socket *net.UDPConn) *nativeDarwinReader {
	t.Helper()
	conn, err := newConn(socket, true, false)
	require.NoError(t, err)
	return &nativeDarwinReader{socket: socket, conn: conn}
}

// read returns one datagram's payload and metadata. Its buffer is released here.
func (r *nativeDarwinReader) read(t *testing.T) (payload string, p receivedPacket) {
	t.Helper()
	require.NoError(t, r.socket.SetReadDeadline(time.Now().Add(scaleDuration(5*time.Second))))
	p, err := r.conn.ReadPacket()
	require.NoError(t, err)
	payload = string(p.data)
	p.data = nil
	if p.buffer != nil {
		p.buffer.Release()
		p.buffer = nil
	}
	require.NoError(t, r.socket.SetReadDeadline(time.Time{}))
	return payload, p
}

func nativeDarwinLoopbackIndex(t *testing.T) uint32 {
	t.Helper()
	interfaces, err := net.Interfaces()
	require.NoError(t, err)
	for _, candidate := range interfaces {
		if candidate.Flags&net.FlagLoopback != 0 && candidate.Flags&net.FlagUp != 0 {
			return uint32(candidate.Index)
		}
	}
	require.FailNow(t, "no loopback interface is up")
	return 0
}

func nativeDarwinECNMsg(destination netip.Addr, ecn protocol.ECN) []byte {
	if destination.Unmap().Is4() {
		return appendIPv4ECNMsg(nil, ecn)
	}
	return appendIPv6ECNMsg(nil, ecn)
}

// nativeDarwinSend offers one scalar datagram through the granted endpoint and
// waits for its published result. The member's control data carries the source
// packet info and the ECN codepoint, as the native ordinary route builds them.
func nativeDarwinSend(t *testing.T, tr *Transport, destination netip.AddrPort, info packetInfo, ecn protocol.ECN, payload string) endpointResult {
	t.Helper()
	e := nativeTransportEndpoint(tr)
	require.NotNil(t, e, "the private grant installs the native endpoint")
	p, err := e.attach(1)
	require.NoError(t, err)
	defer func() { <-e.detach(p) }()
	request := endpointRequest{
		identity:    endpointIdentity{connection: 1, registration: 1},
		destination: destination,
		members:     []endpointMember{{buffer: endpointTestBuffer(payload), oob: packetOOB(info.OOB(), destination, ecn)}},
	}
	require.NoError(t, e.offer(p, 0, request))
	timeout := time.After(scaleDuration(5 * time.Second))
	for {
		if result, ok := e.take(p); ok {
			return result
		}
		select {
		case <-p.completed:
		case <-timeout:
			require.FailNow(t, "the endpoint published no result")
		}
	}
}

type nativeDarwinFamily struct {
	name string
	// granted binds the granted socket on a wildcard address, so packet info is read.
	granted func(*testing.T) *net.UDPConn
	// peerNetwork and peerIP bind the peer; target is the granted socket's address
	// from the peer, and the source the peer must see on the reply.
	peerNetwork string
	peerIP      net.IP
	target      netip.Addr
}

func (f nativeDarwinFamily) run(t *testing.T, facts map[string]any) {
	loopback := nativeDarwinLoopbackIndex(t)
	grantedSocket := f.granted(t)
	tr := nativeDarwinGrant(t, grantedSocket)
	granted := newNativeDarwinReader(t, grantedSocket)
	peerSocket, err := net.ListenUDP(f.peerNetwork, &net.UDPAddr{IP: f.peerIP})
	require.NoError(t, err)
	t.Cleanup(func() { peerSocket.Close() })
	peer := newNativeDarwinReader(t, peerSocket)
	peerAddress := peerSocket.LocalAddr().(*net.UDPAddr).AddrPort()
	target := netip.AddrPortFrom(f.target, grantedSocket.LocalAddr().(*net.UDPAddr).AddrPort().Port())

	// Toward the granted socket: delivery, source, destination packet info and ECN.
	_, _, err = peerSocket.WriteMsgUDPAddrPort([]byte("to granted"), nativeDarwinECNMsg(target.Addr(), protocol.ECNCE), target)
	require.NoError(t, err)
	payload, in := granted.read(t)
	require.Equal(t, "to granted", payload)
	source := in.remoteAddr.(*net.UDPAddr).AddrPort()
	require.Equal(t, peerAddress.Addr(), source.Addr().Unmap(), "the peer's source address")
	require.Equal(t, peerAddress.Port(), source.Port())
	require.Equal(t, f.target, in.info.addr, "the local destination from packet info")
	require.Equal(t, loopback, in.info.ifIndex, "the receiving interface from packet info")
	require.Equal(t, protocol.ECNCE, in.ecn)

	// Back through the granted writer to the address the packet came from. The writer
	// gets the received packet info as control data; loopback routing can pick the
	// same source without it, so the peer's view shows the expected tuple only.
	result := nativeDarwinSend(t, tr, source, in.info, protocol.ECT0, "from granted")
	require.NoError(t, result.failure())
	require.Len(t, result.members, 1)
	member := result.members[0]
	require.Equal(t, [3]int{1, 0, 0}, [3]int{member.accepted, member.uncertain, member.unsubmitted}, "accepted, uncertain, unsubmitted")
	payload, out := peer.read(t)
	require.Equal(t, "from granted", payload)
	require.Equal(t, target, out.remoteAddr.(*net.UDPAddr).AddrPort(), "the peer sees the granted address and port")
	require.Equal(t, protocol.ECT0, out.ecn)

	nativeDarwinJoin(t, tr)

	facts["family"] = f.name
	facts["granted_local"] = grantedSocket.LocalAddr().String()
	facts["peer"] = peerAddress.String()
	facts["inbound_source"] = source.String()
	facts["inbound_destination"] = in.info.addr.String()
	facts["inbound_interface"] = in.info.ifIndex
	facts["inbound_ecn"] = in.ecn.String()
	facts["outbound_accepted"] = member.accepted
	facts["outbound_source"] = out.remoteAddr.String()
	facts["outbound_ecn"] = out.ecn.String()
	facts["joined"] = true
}

func nativeDarwinListen(network string, ip net.IP) func(*testing.T) *net.UDPConn {
	return func(t *testing.T) *net.UDPConn {
		t.Helper()
		socket, err := net.ListenUDP(network, &net.UDPAddr{IP: ip})
		require.NoError(t, err)
		t.Cleanup(func() { socket.Close() })
		return socket
	}
}

func nativeDarwinDualStack(t *testing.T) *net.UDPConn {
	t.Helper()
	socket := listenDualStackUDP(t)
	t.Cleanup(func() { socket.Close() })
	return socket
}

// TestNativeDarwinScalar is MP-MAC E1's granted scalar fixture. Each subtest is one
// named case: interop/multipath/native_darwin.py runs it alone in its own process
// and reads the case record it writes. Without nativeDarwinRecordEnv the cases are
// ordinary development tests and write nothing. A case never skips. It sends and
// receives scalar UDP through the real private grant on real loopback sockets, so
// it is local smoke evidence for the endpoint method, not a support receipt.
func TestNativeDarwinScalar(t *testing.T) {
	ipv4, ipv6 := netip.MustParseAddr("127.0.0.1"), netip.IPv6Loopback()
	for _, family := range []nativeDarwinFamily{
		{name: "ipv4", granted: nativeDarwinListen("udp4", net.IPv4zero), peerNetwork: "udp4", peerIP: net.IPv4(127, 0, 0, 1), target: ipv4},
		{name: "ipv6", granted: nativeDarwinListen("udp6", net.IPv6zero), peerNetwork: "udp6", peerIP: net.IPv6loopback, target: ipv6},
		{name: "dual-stack-mapped-ipv4", granted: nativeDarwinDualStack, peerNetwork: "udp4", peerIP: net.IPv4(127, 0, 0, 1), target: ipv4},
		{name: "dual-stack-native-ipv6", granted: nativeDarwinDualStack, peerNetwork: "udp6", peerIP: net.IPv6loopback, target: ipv6},
	} {
		nativeDarwinCase(t, family.name, family.run)
	}

	nativeDarwinCase(t, "grant-refusal", func(t *testing.T, facts map[string]any) {
		socket := nativeDarwinListen("udp4", net.IPv4(127, 0, 0, 1))(t)
		first := nativeDarwinGrant(t, socket)
		require.ErrorIs(t, first.configureNativeIO(time.Second), ErrMultipathInvalidConfigV1, "repeated on one transport")
		second := &Transport{Conn: socket}
		require.ErrorIs(t, second.configureNativeIO(time.Second), ErrMultipathInvalidConfigV1, "the socket's grant is still held")
		require.Nil(t, second.responses)

		connected, err := net.DialUDP("udp4", nil, socket.LocalAddr().(*net.UDPAddr))
		require.NoError(t, err)
		t.Cleanup(func() { connected.Close() })
		require.ErrorIs(t, (&Transport{Conn: connected}).configureNativeIO(time.Second), ErrMultipathUnsupportedV1, "a connected socket")

		// The Darwin send thread QoS option excludes the grant.
		qos := &Transport{Conn: nativeDarwinListen("udp4", net.IPv4(127, 0, 0, 1))(t)}
		require.NoError(t, qos.ConfigureSendThreadQoSV1())
		require.ErrorIs(t, qos.configureNativeIO(time.Second), ErrMultipathUnsupportedV1, "send thread QoS")
		require.Nil(t, qos.responses)

		nativeDarwinJoin(t, first)
		regrant := &Transport{Conn: socket}
		require.NoError(t, regrant.configureNativeIO(time.Second), "the join returned the grant")
		t.Cleanup(func() { regrant.Close() })

		facts["repeated_grant"] = "invalid-config"
		facts["held_socket"] = "invalid-config"
		facts["connected_socket"] = "unsupported"
		facts["send_thread_qos"] = "unsupported"
		facts["regranted_after_join"] = true
	})

	nativeDarwinCase(t, "post-join-authority", func(t *testing.T, facts map[string]any) {
		socket := nativeDarwinListen("udp4", net.IPv4(127, 0, 0, 1))(t)
		peerSocket := nativeDarwinListen("udp4", net.IPv4(127, 0, 0, 1))(t)
		peer := newNativeDarwinReader(t, peerSocket)
		tr := nativeDarwinGrant(t, socket)

		written, err := tr.WriteTo([]byte("granted"), peerSocket.LocalAddr())
		require.NoError(t, err)
		require.Equal(t, len("granted"), written)
		payload, _ := peer.read(t)
		require.Equal(t, "granted", payload)
		require.ErrorIs(t, tr.waitNativeIOStopped(t.Context()), ErrMultipathNotStoppingV1, "a live grant returns no authority")

		nativeDarwinJoin(t, tr)
		_, err = tr.WriteTo([]byte("late"), peerSocket.LocalAddr())
		require.ErrorIs(t, err, net.ErrClosed, "the joined transport can't write")

		// After the join the caller's own write deadline governs the socket.
		require.NoError(t, socket.SetWriteDeadline(time.Now().Add(-time.Second)))
		_, err = socket.WriteToUDP([]byte("expired"), peerSocket.LocalAddr().(*net.UDPAddr))
		require.ErrorIs(t, err, os.ErrDeadlineExceeded)
		require.NoError(t, socket.SetWriteDeadline(time.Time{}))
		_, err = socket.WriteToUDP([]byte("caller"), peerSocket.LocalAddr().(*net.UDPAddr))
		require.NoError(t, err)
		payload, from := peer.read(t)
		require.Equal(t, "caller", payload, "the expired write submitted nothing")
		require.Equal(t, socket.LocalAddr().String(), from.remoteAddr.String())

		facts["endpoint_write_delivered"] = true
		facts["live_wait"] = "not-stopping"
		facts["joined"] = true
		facts["transport_write_after_join"] = "closed"
		facts["caller_deadline_enforced"] = true
		facts["caller_write_delivered"] = true
	})

	// MP-MAC E3's scalar lane contention record, in native_darwin_contention_test.go.
	nativeDarwinCase(t, "scalar-contention", nativeDarwinContentionCase)
}
