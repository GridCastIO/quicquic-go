//go:build picoquic && (linux || (darwin && arm64))

package quic

import (
	"bufio"
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"fmt"
	"math/big"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

// picoquicTuples is one execution profile's explicit loopback tuple plan.
// Index 0 is path zero, 1 is path one and 2 is the replacement or migration
// target. The Go fixture binds goIPs; the C adapter binds peerIPs.
type picoquicTuples struct {
	goIPs   [3]net.IP
	peerIPs [3]net.IP
	// explicit passes peerIPs and the replacement address to the C adapter.
	// Linux keeps the adapter's 127.0.0.1-3 defaults and unchanged argv.
	explicit bool
}

func picoquicTuplePlan(goos string) (picoquicTuples, error) {
	switch goos {
	case "linux":
		ips := [3]net.IP{net.IPv4(127, 0, 0, 1), net.IPv4(127, 0, 0, 2), net.IPv4(127, 0, 0, 3)}
		return picoquicTuples{goIPs: ips, peerIPs: ips}, nil
	case "darwin":
		// Darwin configures only 127.0.0.1 on lo0; another loopback address
		// needs a privileged alias. Distinct ephemeral ports separate tuples.
		lo := net.IPv4(127, 0, 0, 1)
		ips := [3]net.IP{lo, lo, lo}
		return picoquicTuples{goIPs: ips, peerIPs: ips, explicit: true}, nil
	default:
		return picoquicTuples{}, fmt.Errorf("no picoquic peer tuple plan for %s", goos)
	}
}

// hostPicoquicTuples is the plan for the running platform.
func hostPicoquicTuples(t testing.TB) picoquicTuples {
	t.Helper()
	plan, err := picoquicTuplePlan(runtime.GOOS)
	require.NoError(t, err)
	return plan
}

// replacement is the Go tuple address the adapter's tuple gate accepts.
func (p picoquicTuples) replacement() net.IP { return p.goIPs[2] }

// reserveUDPTuples reserves one free port on each address. The sockets close
// together, so the ports are distinct; a later bind race fails one attempt.
func reserveUDPTuples(t testing.TB, ips [3]net.IP) [3]*net.UDPAddr {
	t.Helper()
	var tuples [3]*net.UDPAddr
	for i, ip := range ips {
		socket, err := net.ListenUDP("udp4", &net.UDPAddr{IP: ip})
		require.NoError(t, err)
		defer socket.Close()
		tuples[i] = socket.LocalAddr().(*net.UDPAddr)
	}
	return tuples
}

// reservePeerTuples returns the C adapter's bind tuples for one launch.
// Darwin reserves all three together, so the adapter binds exactly the
// fixture's distinct choices or fails. Linux keeps its defaults: socket zero
// gets a reserved port only when the Go client must dial it, and the adapter
// chooses the others.
func (p picoquicTuples) reservePeerTuples(t testing.TB, dialed bool) [3]*net.UDPAddr {
	t.Helper()
	if p.explicit {
		return reserveUDPTuples(t, p.peerIPs)
	}
	var tuples [3]*net.UDPAddr
	for i, ip := range p.peerIPs {
		tuples[i] = &net.UDPAddr{IP: ip}
	}
	if dialed {
		socket, err := net.ListenUDP("udp4", tuples[0])
		require.NoError(t, err)
		tuples[0] = socket.LocalAddr().(*net.UDPAddr)
		require.NoError(t, socket.Close())
	}
	return tuples
}

// peerArgs returns the C adapter's arguments for one role launch.
func (p picoquicTuples) peerArgs(role string, peer [3]*net.UDPAddr, remotePort int, cert, key, ca string, negotiated bool) []string {
	mp := "0"
	if negotiated {
		mp = "1"
	}
	args := []string{role, strconv.Itoa(peer[0].Port), strconv.Itoa(remotePort), cert, key, ca, mp}
	if p.explicit {
		for _, tuple := range peer {
			args = append(args, tuple.String())
		}
		args = append(args, p.replacement().String())
	}
	return args
}

// picoquicPeerCommand keeps Linux's line-buffered stdbuf launch. Darwin has no
// GNU stdbuf: the C adapter writes unbuffered output, and the ordinary demo's
// readiness is a bounded successful Dial rather than a log line.
func picoquicPeerCommand(goos, binary string, args []string) (string, []string) {
	if goos == "linux" {
		return "stdbuf", append([]string{"-oL", "-eL", binary}, args...)
	}
	return binary, args
}

func writeSmokeCertificates(t *testing.T, dir string) (*x509.CertPool, tls.Certificate) {
	t.Helper()
	// integrationtests/tools imports this package, so this file builds its own chain.
	caKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	require.NoError(t, err)
	now := time.Now()
	caTemplate := &x509.Certificate{
		SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "R14 independent peer smoke CA"},
		NotBefore: now.Add(-time.Hour), NotAfter: now.Add(time.Hour), IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign,
	}
	caDER, err := x509.CreateCertificate(rand.Reader, caTemplate, caTemplate, caKey.Public(), caKey)
	require.NoError(t, err)
	ca, err := x509.ParseCertificate(caDER)
	require.NoError(t, err)
	leafKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	require.NoError(t, err)
	leafDER, err := x509.CreateCertificate(rand.Reader, &x509.Certificate{
		SerialNumber: big.NewInt(2), Subject: pkix.Name{CommonName: "localhost"}, DNSNames: []string{"localhost"},
		NotBefore: now.Add(-time.Hour), NotAfter: now.Add(time.Hour), KeyUsage: x509.KeyUsageDigitalSignature, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
	}, ca, leafKey.Public(), caKey)
	require.NoError(t, err)
	leaf, err := x509.ParseCertificate(leafDER)
	require.NoError(t, err)
	key, err := x509.MarshalPKCS8PrivateKey(leafKey)
	require.NoError(t, err)
	for name, data := range map[string][]byte{
		"cert.pem": pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: leaf.Raw}),
		"ca.pem":   pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: ca.Raw}),
		"key.pem":  pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: key}),
	} {
		require.NoError(t, os.WriteFile(filepath.Join(dir, name), data, 0o600))
	}
	roots := x509.NewCertPool()
	roots.AddCert(ca)
	return roots, tls.Certificate{Certificate: [][]byte{leaf.Raw}, PrivateKey: leafKey}
}

type smokePeer struct {
	ready chan struct{}
	done  chan struct{}
	err   error // published by closing done
}

func startSmokePeer(t *testing.T, ctx context.Context, binary, dir string, args ...string) *smokePeer {
	t.Helper()
	ctx, cancel := context.WithCancel(ctx)
	name, argv := picoquicPeerCommand(runtime.GOOS, binary, args)
	cmd := exec.CommandContext(ctx, name, argv...)
	cmd.Dir = dir
	output, err := cmd.StdoutPipe()
	require.NoError(t, err)
	cmd.Stderr = cmd.Stdout
	log, err := os.Create(filepath.Join(dir, "peer.log"))
	require.NoError(t, err)
	peer := &smokePeer{ready: make(chan struct{}), done: make(chan struct{})}
	require.NoError(t, cmd.Start())
	go func() {
		scanner := bufio.NewScanner(output)
		ready := false
		for scanner.Scan() {
			line := scanner.Text()
			fmt.Fprintln(log, line)
			if !ready && strings.Contains(line, "Waiting for packets") {
				close(peer.ready)
				ready = true
			}
		}
		peer.err = cmd.Wait()
		if peer.err == nil {
			peer.err = scanner.Err()
		}
		log.Close()
		close(peer.done)
	}()
	t.Cleanup(func() {
		cancel()
		<-peer.done
	})
	return peer
}

func (p *smokePeer) wait(t *testing.T) {
	t.Helper()
	<-p.done
	require.NoError(t, p.err, "see peer.log")
}

// TestPicoquicMatrixTuplePlan inspects both profiles' explicit initial and
// replacement tuples and both-role adapter arguments, then binds the running
// platform's Go tuples. It launches no peer.
func TestPicoquicMatrixTuplePlan(t *testing.T) {
	linux, err := picoquicTuplePlan("linux")
	require.NoError(t, err)
	for i, want := range []string{"127.0.0.1", "127.0.0.2", "127.0.0.3"} {
		require.Equal(t, want, linux.goIPs[i].String())
		require.Equal(t, want, linux.peerIPs[i].String())
	}
	// Linux argv is unchanged: socket zero's port only; the adapter keeps its defaults.
	linuxServer := linux.reservePeerTuples(t, true)
	require.NotZero(t, linuxServer[0].Port, "the dialed socket has a reserved port")
	require.Equal(t, []string{"server", strconv.Itoa(linuxServer[0].Port), "0", "c", "k", "a", "1"},
		linux.peerArgs("server", linuxServer, 0, "c", "k", "a", true))
	linuxClient := linux.reservePeerTuples(t, false)
	require.Equal(t, []string{"client", "0", "4433", "c", "k", "a", "0"}, linux.peerArgs("client", linuxClient, 4433, "c", "k", "a", false))
	for _, tuple := range append(linuxServer[1:], linuxClient[:]...) {
		require.Zero(t, tuple.Port, "Linux leaves the other adapter ports to the adapter")
	}
	require.Equal(t, "127.0.0.3", linux.replacement().String())

	darwin, err := picoquicTuplePlan("darwin")
	require.NoError(t, err)
	for i := range 3 {
		require.Equal(t, "127.0.0.1", darwin.goIPs[i].String())
		require.Equal(t, "127.0.0.1", darwin.peerIPs[i].String())
	}
	require.Equal(t, "127.0.0.1", darwin.replacement().String())
	lo := net.IPv4(127, 0, 0, 1)
	peer := [3]*net.UDPAddr{{IP: lo, Port: 5001}, {IP: lo, Port: 5002}, {IP: lo, Port: 5003}}
	explicit := []string{"127.0.0.1:5001", "127.0.0.1:5002", "127.0.0.1:5003", "127.0.0.1"}
	require.Equal(t, append([]string{"server", "5001", "0", "c", "k", "a", "1"}, explicit...), darwin.peerArgs("server", peer, 0, "c", "k", "a", true))
	require.Equal(t, append([]string{"client", "5001", "4433", "c", "k", "a", "1"}, explicit...), darwin.peerArgs("client", peer, 4433, "c", "k", "a", true))
	// Darwin reserves every adapter tuple: distinct, nonzero ports, with socket zero as requested.
	for _, dialed := range []bool{true, false} {
		reserved := darwin.reservePeerTuples(t, dialed)
		require.Len(t, map[string]bool{reserved[0].String(): true, reserved[1].String(): true, reserved[2].String(): true}, 3)
		for _, tuple := range reserved {
			require.NotZero(t, tuple.Port)
			require.Equal(t, "127.0.0.1", tuple.IP.String())
		}
	}

	_, err = picoquicTuplePlan("windows")
	require.ErrorContains(t, err, "no picoquic peer tuple plan")

	name, args := picoquicPeerCommand("linux", "/peer", []string{"x"})
	require.Equal(t, "stdbuf", name)
	require.Equal(t, []string{"-oL", "-eL", "/peer", "x"}, args)
	name, args = picoquicPeerCommand("darwin", "/peer", []string{"x"})
	require.Equal(t, "/peer", name)
	require.Equal(t, []string{"x"}, args)

	// The running platform's three Go tuples bind as distinct UDP tuples.
	seen := map[string]bool{}
	for _, ip := range hostPicoquicTuples(t).goIPs {
		socket, err := net.ListenUDP("udp4", &net.UDPAddr{IP: ip})
		require.NoError(t, err)
		t.Cleanup(func() { socket.Close() })
		seen[socket.LocalAddr().String()] = true
	}
	require.Len(t, seen, 3)
}

// TestPicoquicMatrixPeerLaunch shows that an early exit is not readiness and
// that cancellation kills and joins a running child. It needs no peer binary.
func TestPicoquicMatrixPeerLaunch(t *testing.T) {
	exited, err := exec.LookPath("false")
	require.NoError(t, err)
	peer := startSmokePeer(t, t.Context(), exited, t.TempDir())
	select {
	case <-peer.done:
		require.Error(t, peer.err)
	case <-peer.ready:
		t.Fatal("an exited peer reported readiness")
	case <-time.After(10 * time.Second):
		t.Fatal("the exited peer was not joined")
	}
	select {
	case <-peer.ready:
		t.Fatal("an exited peer reported readiness")
	default:
	}

	sleep, err := exec.LookPath("sleep")
	require.NoError(t, err)
	ctx, cancel := context.WithCancel(t.Context())
	running := startSmokePeer(t, ctx, sleep, t.TempDir(), "60")
	cancel()
	select {
	case <-running.done:
		require.Error(t, running.err, "the canceled child was killed")
	case <-time.After(10 * time.Second):
		t.Fatal("the canceled peer was not joined")
	}
}

// TestPicoquicMatrixPeerAdapter exchanges the host plan's explicit tuples with
// the pinned C adapter's fixed self-test: it binds those addresses and reports
// an oversized datagram as truncated. It runs no QUIC connection.
func TestPicoquicMatrixPeerAdapter(t *testing.T) {
	binary := os.Getenv("PICOQUIC_BINARY")
	require.NotEmpty(t, binary, "PICOQUIC_BINARY must name the pinned C adapter")
	plan := hostPicoquicTuples(t)
	requested := reserveUDPTuples(t, plan.peerIPs)
	args := []string{"self-test"}
	for _, tuple := range requested {
		args = append(args, tuple.String())
	}
	ctx, cancel := context.WithTimeout(t.Context(), 20*time.Second)
	defer cancel()
	output, err := exec.CommandContext(ctx, binary, args...).CombinedOutput()
	require.NoError(t, err, "%s", output)
	t.Logf("adapter self-test:\n%s", output)
	// The adapter binds exactly the requested tuples.
	for i, tuple := range requested {
		require.Contains(t, strings.Split(string(output), "\n"), fmt.Sprintf("bound socket %d %s", i, tuple), "socket %d", i)
	}
	require.Contains(t, string(output), "self-test datagram 1200 bytes received 1200 truncated 0")
	require.Contains(t, string(output), "self-test datagram 2048 bytes received 1536 truncated 1")
	require.Contains(t, string(output), "self-test pass")
}
