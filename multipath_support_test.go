//go:build darwin || linux || freebsd

package quic

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	"github.com/quic-go/quic-go/internal/monotime"
	"github.com/quic-go/quic-go/qlog"

	"github.com/stretchr/testify/require"
)

// readMultipathEvidence decodes frozen evidence cited by the current support record.
func readMultipathEvidence(t *testing.T, path string, v any) {
	t.Helper()
	data, err := os.ReadFile(filepath.Join("docs", "audits", path))
	require.NoError(t, err)
	require.NoError(t, json.Unmarshal(data, v))
}

// Accepted BBR cost exceptions preserve the original failed verdicts and exact metrics.
// The old arrival policy remains negative; the replacement has its own positive receipt.
func TestMultipathSupportMatchesEvidence(t *testing.T) {
	// B5's receipts are in the nested docs/audits module, which Go leaves out of this module's
	// archive. Skip only when that whole tree is absent; in a checkout a missing, unreadable or
	// changed receipt still fails.
	_, err := os.Stat(filepath.Join("docs", "audits"))
	if errors.Is(err, fs.ErrNotExist) {
		t.Skip("B5 receipts are in the nested docs/audits module, which a module archive omits")
	}
	require.NoError(t, err)

	const (
		bbrCandidate         = "a1c9442f110cca36cb4752b39ce24ae998d76f05"
		aggregationCandidate = "ba51ba67bf09f872c558e1519a3839f74795a021"
	)
	var identity struct {
		Candidate string `json:"candidate"`
	}

	var interop struct {
		Status     string   `json:"status"`
		Controller string   `json:"controller"`
		Executed   []string `json:"executed"`
		Identity   struct {
			Candidate string `json:"candidate"`
		} `json:"identity"`
	}
	readMultipathEvidence(t, "2026-11-14-bbr-ordinary-cost-1368/final-qualification/interop-results/matrix-result.json", &interop)
	require.Equal(t, bbrCandidate, interop.Identity.Candidate)
	require.Equal(t, "bbrv3", interop.Controller)
	require.Equal(t, "pass", interop.Status, "BBR primary/backup is tested")
	require.Len(t, interop.Executed, 6)

	var cost struct {
		Complete    bool     `json:"campaign_complete"`
		Controller  string   `json:"controller"`
		Passed      bool     `json:"passed"`
		FailedCells []string `json:"failed_cells"`
		Cells       map[string]struct {
			Goodput struct {
				Median float64 `json:"median"`
			} `json:"goodput_ratio"`
			CPU struct {
				Median float64 `json:"median"`
			} `json:"cpu_per_useful_byte_ratio"`
		} `json:"cells"`
	}
	readMultipathEvidence(t, "2026-11-14-bbr-ordinary-cost-1368/final-qualification/ordinary-results/summary.json", &cost)
	readMultipathEvidence(t, "2026-11-14-bbr-ordinary-cost-1368/final-qualification/ordinary-results/identity.json", &identity)
	require.Equal(t, bbrCandidate, identity.Candidate)
	require.True(t, cost.Complete)
	require.Equal(t, "bbrv3", cost.Controller)
	require.False(t, cost.Passed, "BBR primary/backup is not cost-qualified")
	require.ElementsMatch(t, []string{"mixed-bulk", "stateless-pressure"}, cost.FailedCells)
	require.Equal(t, 0.944295141271208, cost.Cells["mixed-bulk"].Goodput.Median)
	require.Equal(t, 1.2081314772756437, cost.Cells["mixed-bulk"].CPU.Median)
	require.Equal(t, 0.9590708299335772, cost.Cells["stateless-pressure"].Goodput.Median)
	require.Equal(t, 1.1593702973325581, cost.Cells["stateless-pressure"].CPU.Median)

	var aggregation struct {
		Complete         bool     `json:"campaign_complete"`
		Support          string   `json:"support"`
		FailedTopologies []string `json:"failed_topologies"`
	}
	readMultipathEvidence(t, "2026-11-14-multipath-b5/aggregation-gated/aggregation/summary.json", &aggregation)
	readMultipathEvidence(t, "2026-11-14-multipath-b5/aggregation-gated/aggregation/identity.json", &identity)
	require.Equal(t, aggregationCandidate, identity.Candidate)
	require.True(t, aggregation.Complete)
	require.Equal(t, "negative", aggregation.Support, "the old arrival policy remains unsupported")
	require.Equal(t, []string{"balanced"}, aggregation.FailedTopologies)
	readMultipathEvidence(t, "2026-11-15-bbr-b11/aggregation/summary.json", &aggregation)
	readMultipathEvidence(t, "2026-11-15-bbr-b11/aggregation/identity.json", &identity)
	require.Equal(t, "8c34fbac874adf55f096b6c67d51244160169422", identity.Candidate)
	require.True(t, aggregation.Complete)
	require.Equal(t, "positive", aggregation.Support, "paced byte round-robin supports experimental BBR aggregate")
	require.Empty(t, aggregation.FailedTopologies)

}

// Public policy selection is the only configuration authority for activation.
func TestMultipathSelectionPublicPolicyBoundary(t *testing.T) {
	selection := reflect.TypeFor[multipathSelection]()
	var fields []string
	for field := range selection.Fields() {
		fields = append(fields, field.Name)
	}
	require.Equal(t, []string{"enabled", "maxPaths", "scheduler"}, fields)
	conf := &Config{}
	require.NoError(t, conf.ConfigureMultipathV1(true, 2, "aggregate"))
	saved := conf.Clone()
	require.ErrorIs(t, conf.ConfigureMultipathV1(true, 2, "unknown"), ErrMultipathInvalidConfigV1)
	require.Equal(t, saved, conf)
	require.NoError(t, conf.ConfigureMultipathV1(false, 99, "unknown"))
	require.False(t, conf.MultipathEnabledV1())
}

// Public constructors preserve controller selection through setter order and cloning.
func TestMultipathSupportedCombinations(t *testing.T) {
	requireMultipathProfile(t)

	for _, policy := range []string{"primary-backup", "aggregate"} {
		for _, controllerFirst := range []bool{true, false} {
			for _, early := range []bool{false, true} {
				for _, selected := range []bool{false, true} {
					t.Run(fmt.Sprintf("BBR/%s/order-%t/early-%t/selected-%t", policy, controllerFirst, early, selected), func(t *testing.T) {
						conf := &Config{}
						if controllerFirst {
							require.NoError(t, conf.SetCongestionControlV1("bbrv3"))
						}
						require.NoError(t, conf.ConfigureMultipathV1(true, 2, policy))
						if !controllerFirst {
							require.NoError(t, conf.SetCongestionControlV1("bbrv3"))
						}
						conf = conf.Clone()
						require.Equal(t, "bbrv3", conf.CongestionControlV1())
						require.True(t, conf.MultipathEnabledV1())
						serverTr, clientTr := grantedTransport(t), grantedTransport(t)
						serverConf := conf
						if selected {
							serverConf = &Config{GetConfigForClient: func(*ClientInfo) (*Config, error) { return conf.Clone(), nil }}
						}
						ctx, cancel := context.WithTimeout(t.Context(), 10*time.Second)
						defer cancel()
						var accept func(context.Context) (*Conn, error)
						if early {
							ln, err := serverTr.ListenEarly(nativeServerTLS(), serverConf)
							require.NoError(t, err)
							t.Cleanup(func() { ln.Close() })
							accept = ln.Accept
						} else {
							ln, err := serverTr.Listen(nativeServerTLS(), serverConf)
							require.NoError(t, err)
							t.Cleanup(func() { ln.Close() })
							accept = ln.Accept
						}
						dial := clientTr.Dial
						if early {
							dial = clientTr.DialEarly
						}
						client, err := dial(ctx, serverTr.Conn.LocalAddr(), nativeClientTLS(), conf.Clone())
						require.NoError(t, err)
						t.Cleanup(func() { client.CloseWithError(0, "") })
						server, err := accept(ctx)
						require.NoError(t, err)
						t.Cleanup(func() { server.CloseWithError(0, "") })
						for _, conn := range []*Conn{client, server} {
							select {
							case <-conn.HandshakeComplete():
							case <-ctx.Done():
								t.Fatal(ctx.Err())
							}
							negotiated, err := conn.MultipathNegotiatedV1()
							require.NoError(t, err)
							require.True(t, negotiated)
							require.Equal(t, "bbrv3", conn.CongestionControlV1())
						}
					})
				}
			}
		}

	}
	t.Run("Reno primary/backup", func(t *testing.T) {
		for _, explicit := range []bool{false, true} {
			conf := multipathConfig(t)
			if explicit {
				require.NoError(t, conf.SetCongestionControlV1("reno"))
			}
			serverTr, clientTr := grantedTransport(t), grantedTransport(t)
			ln, err := serverTr.Listen(nativeServerTLS(), conf)
			require.NoError(t, err)
			t.Cleanup(func() { ln.Close() })
			ctx, cancel := context.WithTimeout(t.Context(), 10*time.Second)
			defer cancel()
			client, err := clientTr.Dial(ctx, serverTr.Conn.LocalAddr(), nativeClientTLS(), conf)
			require.NoError(t, err)
			t.Cleanup(func() { client.CloseWithError(0, "") })
			server, err := ln.Accept(ctx)
			require.NoError(t, err)
			t.Cleanup(func() { server.CloseWithError(0, "") })
			for _, conn := range []*Conn{client, server} {
				<-conn.HandshakeComplete()
				negotiated, err := conn.MultipathNegotiatedV1()
				require.NoError(t, err)
				require.True(t, negotiated)
				require.Equal(t, "reno", conn.CongestionControlV1())
				scheduler := scheduleAggregate
				require.NoError(t, conn.runPathCommand(func(r *pathCreditRegistry, _ monotime.Time) error {
					scheduler = r.scheduler
					return nil
				}))
				require.Equal(t, schedulePrimaryBackup, scheduler)
			}
		}
	})
}

// Useful application transfer succeeds before and after selecting a new primary
// through public BBR admission, then every granted endpoint joins after close.
func TestMultipathBBRPublicTransferAndJoin(t *testing.T) {
	requireMultipathProfile(t)
	conf := multipathConfig(t)
	require.NoError(t, conf.SetCongestionControlV1("bbrv3"))
	serverTr, clientTr, secondTr := grantedTransport(t), grantedTransport(t), grantedTransport(t)
	ln, err := serverTr.Listen(nativeServerTLS(), conf)
	require.NoError(t, err)
	defer ln.Close()
	ctx, cancel := context.WithTimeout(t.Context(), 10*time.Second)
	defer cancel()
	client, err := clientTr.Dial(ctx, serverTr.Conn.LocalAddr(), nativeClientTLS(), conf)
	require.NoError(t, err)
	defer client.CloseWithError(0, "")
	server, err := ln.Accept(ctx)
	require.NoError(t, err)
	defer server.CloseWithError(0, "")
	transfer := func(message string) {
		t.Helper()
		stream, err := client.OpenUniStreamSync(ctx)
		require.NoError(t, err)
		_, err = stream.Write([]byte(message))
		require.NoError(t, err)
		require.NoError(t, stream.Close())
		received, err := server.AcceptUniStream(ctx)
		require.NoError(t, err)
		data, err := io.ReadAll(received)
		require.NoError(t, err)
		require.Equal(t, message, string(data))
	}
	transfer("BBR public path zero")
	path, err := client.OpenPathV1(ctx, secondTr, serverTr.Conn.LocalAddr().(*net.UDPAddr))
	require.NoError(t, err)
	require.NoError(t, path.SetLocalUseV1("active"))
	require.NoError(t, client.PathsV1()[0].SetLocalUseV1("backup"))
	state, err := path.StateV1()
	require.NoError(t, err)
	require.True(t, state.Primary)
	transfer("BBR public path one")
	require.NoError(t, client.CloseWithError(0, ""))
	require.NoError(t, server.CloseWithError(0, ""))
	for _, tr := range []*Transport{clientTr, secondTr, serverTr} {
		require.NoError(t, tr.Close())
		require.NoError(t, tr.WaitMultipathIOStoppedV1(ctx))
	}
}

// The public aggregate policy traverses admission and copies its choice before either
// connection runs. No command changes a running connection's scheduler.
func TestMultipathAggregateTransferAndJoin(t *testing.T) {
	requireMultipathProfile(t)
	conf := multipathConfig(t)
	require.NoError(t, conf.SetCongestionControlV1("bbrv3"))
	conf.EnableDatagrams = true
	conf.DisablePathMTUDiscovery = true // MTU probe charging has separate real-packer coverage.
	require.NoError(t, conf.ConfigureMultipathV1(true, 2, "aggregate"))
	clientConf, serverConf := conf.Clone(), conf.Clone()
	require.NoError(t, conf.ConfigureMultipathV1(true, 2, "primary-backup"))
	sink := newQlogSink()
	clientConf.Tracer = sink.tracer
	serverTr, clientTr, secondTr := grantedTransport(t), grantedTransport(t), grantedTransport(t)
	ln, err := serverTr.Listen(nativeServerTLS(), serverConf)
	require.NoError(t, err)
	defer ln.Close()
	ctx, cancel := context.WithTimeout(t.Context(), 10*time.Second)
	defer cancel()
	deadline, _ := ctx.Deadline()
	client, err := clientTr.Dial(ctx, serverTr.Conn.LocalAddr(), nativeClientTLS(), clientConf)
	require.NoError(t, err)
	defer client.CloseWithError(0, "")
	server, err := ln.Accept(ctx)
	require.NoError(t, err)
	defer server.CloseWithError(0, "")
	path, err := client.OpenPathV1(ctx, secondTr, serverTr.Conn.LocalAddr().(*net.UDPAddr))
	require.NoError(t, err)
	require.NoError(t, path.SetLocalUseV1("active"))
	for _, c := range []*Conn{client, server} {
		var scheduler pathScheduler
		require.NoError(t, c.runPathCommand(func(r *pathCreditRegistry, _ monotime.Time) error { scheduler = r.scheduler; return nil }))
		require.Equal(t, scheduleAggregate, scheduler)
	}
	streamBytes, datagrams := map[uint64]int64{}, map[uint64]int{}
	observed := 0
	observe := func() {
		events := sink.recorded()
		for _, event := range events[observed:] {
			packet, ok := event.(qlog.PacketSent)
			if !ok || packet.Path == nil {
				continue
			}
			for _, frame := range packet.Frames {
				switch f := frame.Frame.(type) {
				case *qlog.StreamFrame:
					streamBytes[packet.Path.PathID] += f.Length
				case *qlog.DatagramFrame:
					datagrams[packet.Path.PathID]++
				}
			}
		}
		observed = len(events)
	}
	// A fixed tiny burst need not use both paths: pacing and previous handoffs
	// can consume its turns. Offer bounded work until carriage is witnessed,
	// allowing pacing to advance between opportunities. These are fixture
	// limits (at most 1 MiB per phase), not a scheduler service promise.
	opportunities := time.NewTicker(time.Millisecond)
	defer opportunities.Stop()
	next := func() {
		t.Helper()
		select {
		case <-opportunities.C:
		case <-ctx.Done():
			t.Fatal(ctx.Err())
		}
	}
	payload := bytes.Repeat([]byte{'s'}, 16*1024)
	for round := 0; round < 64 && (streamBytes[0] == 0 || streamBytes[1] == 0); round++ {
		next()
		stream, err := client.OpenUniStreamSync(ctx)
		require.NoError(t, err)
		require.NoError(t, stream.SetWriteDeadline(deadline))
		writeDone := make(chan error, 1)
		go func() {
			_, err := stream.Write(payload)
			if err == nil {
				err = stream.Close()
			}
			writeDone <- err
		}()
		received, err := server.AcceptUniStream(ctx)
		require.NoError(t, err)
		require.NoError(t, received.SetReadDeadline(deadline))
		data, err := io.ReadAll(received)
		require.NoError(t, err)
		require.NoError(t, <-writeDone)
		require.Equal(t, payload, data)
		observe()
	}
	for round := 0; round < 1024 && (datagrams[0] == 0 || datagrams[1] == 0); round++ {
		next()
		message := bytes.Repeat([]byte{byte(round)}, 1024)
		require.NoError(t, client.SendDatagram(message))
		got, err := server.ReceiveDatagram(ctx)
		require.NoError(t, err)
		require.Equal(t, message, got)
		observe()
	}
	require.NoError(t, client.CloseWithError(0, ""))
	require.NoError(t, server.CloseWithError(0, ""))
	for _, tr := range []*Transport{clientTr, secondTr, serverTr} {
		require.NoError(t, tr.Close())
		require.NoError(t, tr.WaitMultipathIOStoppedV1(ctx))
	}
	select {
	case <-sink.closed:
	case <-ctx.Done():
		t.Fatal(ctx.Err())
	}
	observe()
	for _, id := range []uint64{0, 1} {
		require.Positive(t, streamBytes[id], "path %d carried STREAM", id)
		require.Positive(t, datagrams[id], "path %d carried DATAGRAM", id)
	}
	t.Logf("STREAM bytes by path: %v; DATAGRAMs by path: %v", streamBytes, datagrams)
}

// Admission rechecks the final controller even after a valid BBR selection was cloned.
func TestMultipathAggregateRejectsChangedController(t *testing.T) {
	requireMultipathProfile(t)
	conf := &Config{}
	require.NoError(t, conf.SetCongestionControlV1("bbrv3"))
	require.NoError(t, conf.ConfigureMultipathV1(true, 2, "aggregate"))
	conf = conf.Clone()
	require.NoError(t, conf.SetCongestionControlV1("reno"))
	target := &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1), Port: 9}
	ctx := t.Context()
	tr := grantedTransport(t)
	for _, dial := range []func(context.Context, net.Addr, *tls.Config, *Config) (*Conn, error){tr.Dial, tr.DialEarly} {
		_, err := dial(ctx, target, nativeClientTLS(), conf)
		require.ErrorIs(t, err, ErrMultipathUnsupportedV1)
	}
	_, err := tr.Listen(nativeServerTLS(), conf)
	require.ErrorIs(t, err, ErrMultipathUnsupportedV1)
	_, err = tr.ListenEarly(nativeServerTLS(), conf)
	require.ErrorIs(t, err, ErrMultipathUnsupportedV1)
	serverTr := grantedTransport(t)
	ln, err := serverTr.Listen(nativeServerTLS(), &Config{GetConfigForClient: func(*ClientInfo) (*Config, error) { return conf.Clone(), nil }})
	require.NoError(t, err)
	defer ln.Close()
	dialCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	_, err = tr.Dial(dialCtx, serverTr.Conn.LocalAddr(), nativeClientTLS(), nil)
	var refused *TransportError
	require.ErrorAs(t, err, &refused)
	require.Equal(t, ConnectionRefused, refused.ErrorCode)
}
