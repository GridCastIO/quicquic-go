//go:build darwin || linux || freebsd

package quic

import (
	"context"
	"encoding/json"
	"errors"
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

// B6 (#1045) publishes the multipath combinations that B5's evidence supports: Reno
// primary/backup only. BBR primary/backup passed its interop cases and failed its
// ordinary-cost gate, and the aggregate comparison was valid and negative.

// readB5Evidence decodes one file of B5's frozen receipt evidence.
func readB5Evidence(t *testing.T, path string, v any) {
	t.Helper()
	data, err := os.ReadFile(filepath.Join("docs", "audits", "2026-11-14-multipath-b5", path))
	require.NoError(t, err)
	require.NoError(t, json.Unmarshal(data, v))
}

// The B5 receipts that the support statement cites keep their candidate identities and
// the verdicts that leave BBR primary/backup and aggregation unsupported.
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
		bbrCandidate         = "4e80d3cf4fa7454ffc3e2a46655afd5f81f86313"
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
	readB5Evidence(t, "interop/matrix-result.json", &interop)
	require.Equal(t, bbrCandidate, interop.Identity.Candidate)
	require.Equal(t, "bbrv3", interop.Controller)
	require.Equal(t, "pass", interop.Status, "BBR primary/backup is tested")
	require.Len(t, interop.Executed, 6)

	var cost struct {
		Complete    bool     `json:"campaign_complete"`
		Controller  string   `json:"controller"`
		Passed      bool     `json:"passed"`
		FailedCells []string `json:"failed_cells"`
	}
	readB5Evidence(t, "ordinary-bbr/summary.json", &cost)
	readB5Evidence(t, "ordinary-bbr/identity.json", &identity)
	require.Equal(t, bbrCandidate, identity.Candidate)
	require.True(t, cost.Complete)
	require.Equal(t, "bbrv3", cost.Controller)
	require.False(t, cost.Passed, "BBR primary/backup is not cost-qualified")
	require.ElementsMatch(t, []string{"mixed-bulk", "stateless-pressure"}, cost.FailedCells)

	var aggregation struct {
		Complete         bool     `json:"campaign_complete"`
		Support          string   `json:"support"`
		FailedTopologies []string `json:"failed_topologies"`
	}
	readB5Evidence(t, "aggregation-gated/aggregation/summary.json", &aggregation)
	readB5Evidence(t, "aggregation-gated/aggregation/identity.json", &identity)
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

// The capability gate admits exactly Reno primary/backup, the default controller. It
// refuses BBR primary/backup from a dial, a listener and a server-selected Config, in
// either configuration order, and ConfigureMultipathV1 refuses aggregation with either
// controller.
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

	t.Run("BBR primary/backup", func(t *testing.T) {
		target := &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1), Port: 9}
		for _, controllerFirst := range []bool{true, false} {
			conf := &Config{}
			if controllerFirst {
				require.NoError(t, conf.SetCongestionControlV1("bbrv3"))
			}
			require.NoError(t, conf.ConfigureMultipathV1(true, 2, "primary-backup"))
			if !controllerFirst {
				require.NoError(t, conf.SetCongestionControlV1("bbrv3"))
			}
			_, err := grantedTransport(t).Dial(t.Context(), target, nativeClientTLS(), conf)
			require.ErrorIs(t, err, ErrMultipathUnsupportedV1)
			_, err = grantedTransport(t).DialEarly(t.Context(), target, nativeClientTLS(), conf)
			require.ErrorIs(t, err, ErrMultipathUnsupportedV1)
			_, err = grantedTransport(t).Listen(nativeServerTLS(), conf)
			require.ErrorIs(t, err, ErrMultipathUnsupportedV1)
			_, err = grantedTransport(t).ListenEarly(nativeServerTLS(), conf)
			require.ErrorIs(t, err, ErrMultipathUnsupportedV1)

			srv := grantedTransport(t)
			ln, err := srv.Listen(nativeServerTLS(), &Config{GetConfigForClient: func(*ClientInfo) (*Config, error) { return conf, nil }})
			require.NoError(t, err)
			t.Cleanup(func() { ln.Close() })
			cl := &Transport{Conn: newUDPConnLocalhost(t)}
			t.Cleanup(func() { cl.Close() })
			ctx, cancel := context.WithTimeout(t.Context(), 5*time.Second)
			_, err = cl.Dial(ctx, srv.Conn.LocalAddr(), nativeClientTLS(), nil)
			cancel()
			var transportErr *TransportError
			require.ErrorAs(t, err, &transportErr)
			require.Equal(t, ConnectionRefused, transportErr.ErrorCode)
		}
	})

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
