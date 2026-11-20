//go:build darwin && !ios && !quic_go_no_private_syscalls

package quic

import (
	"bytes"
	"context"
	"io"
	"net"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

// The mixed-bulk shape end to end: a negotiated multipath Reno connection on
// granted Darwin transports sends path zero's software segments through
// sendmsg_x. Not parallel: the sendmsg_x counters are process-wide.
func TestNativeSoftwareGrantedMultipathTransferBatches(t *testing.T) {
	requireNativeBatchQualified(t)
	requireMultipathProfile(t)
	// The deltas span from before any writer exists to after every writer is
	// joined, so they cover only completed sendmsg_x calls (#1596).
	submissions, batched, _ := sendmsgXCountersSnapshot()
	// Each writer is also joined by its own cleanup, so a failure partway through
	// still joins it before the capability reset registered above.
	server := grantedTransport(t)
	nativeDarwinJoinOnCleanup(t, server)
	client := grantedTransport(t)
	nativeDarwinJoinOnCleanup(t, client)
	second := grantedTransport(t)
	nativeDarwinJoinOnCleanup(t, second)
	config := func() *Config {
		conf := multipathConfig(t)
		require.NoError(t, conf.SetCongestionControlV1("reno"))
		return conf
	}
	ctx, cancel := context.WithTimeout(t.Context(), scaleDuration(10*time.Second))
	defer cancel()
	listener, err := server.Listen(nativeServerTLS(), config())
	require.NoError(t, err)
	serverAddr := server.Conn.LocalAddr().(*net.UDPAddr)
	conn, err := client.Dial(ctx, serverAddr, nativeClientTLS(), config())
	require.NoError(t, err)
	accepted, err := listener.Accept(ctx)
	require.NoError(t, err)
	<-accepted.HandshakeComplete()
	require.Equal(t, "reno", accepted.CongestionControlV1())
	negotiated, err := accepted.MultipathNegotiatedV1()
	require.NoError(t, err)
	require.True(t, negotiated, "the server's connection is multipath")
	_, err = conn.OpenPathV1(ctx, second, serverAddr)
	require.NoError(t, err)

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
	nativeDarwinJoin(t, second)
	submissionsAfter, batchedAfter, _ := sendmsgXCountersSnapshot()
	require.Greater(t, submissionsAfter, submissions, "the granted multipath Reno sender used sendmsg_x")
	require.Greater(t, batchedAfter-batched, submissionsAfter-submissions, "average datagrams per sendmsg_x call > 1")
}
