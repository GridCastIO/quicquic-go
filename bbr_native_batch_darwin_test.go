//go:build darwin && !ios && !quic_go_no_private_syscalls

package quic

import (
	"bytes"
	"context"
	"io"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

// Over public Dial and Listen, with both transports granted, a BBR bulk transfer
// builds software-segmented members and the granted writer submits them through
// sendmsg_x (#1590 with #1589's hook). Not parallel: the sendmsg_x counters are
// process-wide.
func TestBBRNativeSoftwareGrantedTransferBatches(t *testing.T) {
	requireNativeBatchQualified(t)
	server := nativeDarwinGrant(t, newUDPConnLocalhost(t))
	nativeDarwinJoinOnCleanup(t, server)
	client := nativeDarwinGrant(t, newUDPConnLocalhost(t))
	nativeDarwinJoinOnCleanup(t, client)
	bbr := func() *Config {
		conf := &Config{}
		require.NoError(t, conf.SetCongestionControlV1("bbrv3"))
		return conf
	}
	ctx, cancel := context.WithTimeout(t.Context(), scaleDuration(10*time.Second))
	defer cancel()
	listener, err := server.Listen(nativeServerTLS(), bbr())
	require.NoError(t, err)
	conn, err := client.Dial(ctx, listener.Addr(), nativeClientTLS(), bbr())
	require.NoError(t, err)
	accepted, err := listener.Accept(ctx)
	require.NoError(t, err)
	require.Equal(t, "bbrv3", accepted.CongestionControlV1())

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
	require.Greater(t, submissionsAfter, submissions, "the granted BBR sender used sendmsg_x")
	require.Greater(t, batchedAfter-batched, submissionsAfter-submissions, "each submission carried more than one datagram")
	require.NoError(t, conn.CloseWithError(0, ""))
}
