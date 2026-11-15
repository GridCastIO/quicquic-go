//go:build darwin || linux || freebsd

package quic

import (
	"context"
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
// The previous aggregation candidate still has a valid negative result.
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
	require.Equal(t, "negative", aggregation.Support, "aggregation is unsupported")
	require.Equal(t, []string{"balanced"}, aggregation.FailedTopologies)
}

// The Config's multipath request holds only what ConfigureMultipathV1 sets, so no private
// selection can reach the capability gate or the path registry.
func TestMultipathSelectionHasNoPrivateBypass(t *testing.T) {
	selection := reflect.TypeFor[multipathSelection]()
	var fields []string
	for field := range selection.Fields() {
		fields = append(fields, field.Name)
	}
	require.Equal(t, []string{"enabled", "maxPaths"}, fields)
}

// Public constructors preserve controller selection through setter order and cloning.
func TestMultipathSupportedCombinations(t *testing.T) {
	requireMultipathProfile(t)
	t.Run("aggregate", func(t *testing.T) {
		for _, controller := range []string{"reno", "bbrv3"} {
			conf := &Config{}
			require.NoError(t, conf.SetCongestionControlV1(controller))
			require.ErrorIs(t, conf.ConfigureMultipathV1(true, 2, "aggregate"), ErrMultipathInvalidConfigV1)
			require.False(t, conf.MultipathEnabledV1())
		}
	})

	for _, controllerFirst := range []bool{true, false} {
		for _, early := range []bool{false, true} {
			for _, selected := range []bool{false, true} {
				t.Run(fmt.Sprintf("BBR/order-%t/early-%t/selected-%t", controllerFirst, early, selected), func(t *testing.T) {
					conf := &Config{}
					if controllerFirst {
						require.NoError(t, conf.SetCongestionControlV1("bbrv3"))
					}
					require.NoError(t, conf.ConfigureMultipathV1(true, 2, "primary-backup"))
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

// Both paths carry useful application data through public BBR admission, then every
// granted endpoint returns its native write authority after close.
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
