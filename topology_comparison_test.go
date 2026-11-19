//go:build ordinarycost && ((linux && amd64) || (darwin && arm64))

package quic

import (
	"context"
	"encoding/json"
	"maps"
	"net"
	"net/netip"
	"os"
	"path/filepath"
	"slices"
	"testing"
	"time"

	"github.com/GridCastIO/quicquic-go/interop/multipath/relay"

	"github.com/stretchr/testify/require"
)

// Every arm offers the same total demand, and each arm's connections use exactly its
// routes and policy. Both platform inventories are checked on any host: a multipath arm
// needs public admission, and aggregate needs BBR.
func TestTopologyComparisonArms(t *testing.T) {
	var names []string
	for _, arm := range topologyArms {
		names = append(names, arm.Name)
		var objects, rate int
		var routes []relay.RouteName
		for _, plan := range arm.plan() {
			objects += plan.ObjectsInFlight
			rate += plan.DatagramRate
			routes = append(routes, plan.Routes...)
		}
		require.Equal(t, topologyObjectsInFlight, objects, "%s: matched STREAM demand", arm.Name)
		require.Equal(t, topologyDatagramRate, rate, "%s: matched DATAGRAM demand", arm.Name)
		require.Equal(t, arm.Routes, routes, "%s: the plan uses exactly the arm's routes", arm.Name)
		require.Equal(t, arm.Multipath, arm.Policy != "", arm.Name)
	}
	require.Equal(t, []string{"single-a", "single-b", "pair", "primary-backup", "aggregate"}, names)
	require.Len(t, topologyMustArm("pair").plan(), 2, "the pair is two independent connections")
	require.Len(t, topologyMustArm("aggregate").plan(), 1, "a multipath arm is one connection over both routes")
	require.Equal(t, []relay.RouteName{relay.RouteCompetitor}, topologyCompetitorPlan.Routes)
	require.Zero(t, topologyCompetitorPlan.DatagramRate, "the competitor offers STREAM objects only")

	for _, platform := range []ordinaryCostPlatformProfile{ordinaryCostLinuxAMD64, ordinaryCostDarwinARM64} {
		for _, kind := range []relay.Kind{relay.KindDisjoint, relay.KindUnequal, relay.KindShared} {
			for _, arm := range topologyArms {
				for _, controller := range []string{"reno", "bbrv3"} {
					err := topologySpec{Topology: kind, Arm: arm.Name, Controller: controller}.validate(platform)
					switch {
					case arm.Multipath && !platform.negotiatedMultipath:
						require.ErrorContains(t, err, "negotiated multipath", "%s %s", platform.name, arm.Name)
					case arm.Policy == topologyPolicyAggregate && controller == "reno":
						require.ErrorContains(t, err, "requires bbrv3", platform.name)
					default:
						require.NoError(t, err, "%s %s %s %s", platform.name, kind, arm.Name, controller)
					}
				}
			}
		}
		for _, spec := range []topologySpec{
			{Topology: relay.KindDisjoint, Arm: "pair", Controller: "cubic"},
			{Topology: relay.KindDisjoint, Arm: "aggregate-reno", Controller: "bbrv3"},
			{Topology: "", Arm: "pair", Controller: "bbrv3"},
			{Topology: "ring", Arm: "pair", Controller: "bbrv3"},
		} {
			require.Error(t, spec.validate(platform), "%+v", spec)
		}
	}
}

// Each topology is the relay's own closed kind with B11's queues: one bandwidth-delay
// product per queue, and a competitor route only in the shared bottleneck.
func TestTopologyComparisonRelayConfigs(t *testing.T) {
	server := netip.MustParseAddrPort("127.0.0.1:4433")
	for _, kind := range []relay.Kind{relay.KindDisjoint, relay.KindUnequal, relay.KindShared} {
		cfg, err := topologyRelayConfig(kind, server)
		require.NoError(t, err, kind)
		require.Equal(t, kind, cfg.Kind)
		var names []relay.RouteName
		for _, route := range cfg.Routes {
			names = append(names, route.Name)
			q := cfg.Queues[route.Queue]
			require.Equal(t, q.RateBPS/8*uint64(2*route.DelayNS)/uint64(time.Second), q.LimitBytes, "%s %s holds one BDP", kind, route.Name)
		}
		require.Equal(t, topologyRoutes(kind), names)
	}
	_, err := topologyRelayConfig("ring", server)
	require.Error(t, err)

	spec := topologySpec{Topology: relay.KindShared, Server: server, StartAt: 1, WindowNS: int64(time.Second),
		Fronts: map[relay.RouteName]netip.AddrPort{"a": netip.MustParseAddrPort("127.0.0.1:1"), "b": netip.MustParseAddrPort("127.0.0.1:2")}}
	require.ErrorContains(t, spec.validateRun(), "fronts", "a shared run needs the competitor's front")
	spec.Fronts["competitor"] = netip.MustParseAddrPort("127.0.0.1:3")
	require.NoError(t, spec.validateRun())
	spec.Fronts["b"] = netip.MustParseAddrPort("127.0.0.1:0")
	require.ErrorContains(t, spec.validateRun(), "bound")
}

// The fixture refuses exactly what the public constructor refuses on this host, so a
// refused arm is never replaced and an admitted arm is really public. Darwin refuses
// every multipath arm until its support switch; Linux refuses only Reno aggregate.
func TestTopologyComparisonAdmission(t *testing.T) {
	require.Equal(t, multipathProfileSupported, ordinaryCostHost.negotiatedMultipath,
		"the host profile follows the public platform gate")
	for _, arm := range topologyArms {
		if !arm.Multipath {
			continue
		}
		for _, controller := range []string{"reno", "bbrv3"} {
			refused := topologySpec{Topology: relay.KindDisjoint, Arm: arm.Name, Controller: controller}.validate(ordinaryCostHost) != nil
			tr := &Transport{Conn: newUDPConnLocalhost(t), ConnectionIDLength: 4}
			t.Cleanup(func() { tr.Close() })
			if multipathProfileSupported {
				require.NoError(t, tr.ConfigureMultipathIOV1(topologyWriteBudget))
				// Runs before the socket's cleanup: the writer returns authority first.
				t.Cleanup(func() {
					tr.Close()
					ctx, cancel := context.WithTimeout(context.Background(), ordinaryCostStopTimeout)
					defer cancel()
					require.NoError(t, tr.WaitMultipathIOStoppedV1(ctx), "%s %s", arm.Name, controller)
				})
			} else {
				require.ErrorIs(t, tr.ConfigureMultipathIOV1(topologyWriteBudget), ErrMultipathUnsupportedV1)
			}
			if !refused {
				continue // an admitted combination is exercised by the smoke
			}
			ctx, cancel := context.WithTimeout(context.Background(), time.Second)
			_, err := tr.Dial(ctx, &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1), Port: 9}, topologyClientTLS(), topologyConfig(t, controller, true, arm.Policy))
			cancel()
			require.ErrorIs(t, err, ErrMultipathUnsupportedV1, "%s %s", arm.Name, controller)
		}
	}
}

type topologySmokeRun struct {
	spec   topologySpec
	rec    relay.Record
	server *topologyServerResult
	client *topologyClientResult
}

// topologySmoke runs one observation in process through a real relay on loopback. Its
// numbers are not measurements.
func topologySmoke(t *testing.T, kind relay.Kind, arm, controller string) topologySmokeRun {
	t.Helper()
	probe := newUDPConnLocalhost(t)
	server := topologyAddrPort(probe.LocalAddr())
	require.NoError(t, probe.Close())
	cfg, err := topologyRelayConfig(kind, server)
	require.NoError(t, err)
	r, err := relay.Start(cfg)
	require.NoError(t, err)
	t.Cleanup(func() { r.Close() })
	spec := topologySpec{
		Topology: kind, Arm: arm, Controller: controller, Seed: 1, Server: server, Fronts: r.Fronts(),
		StartAt: time.Now().Add(1500 * time.Millisecond).UnixNano(), WarmupNS: int64(200 * time.Millisecond), WindowNS: int64(time.Second),
	}
	servers := make(chan *topologyServerResult, 1)
	go func() {
		defer close(servers)
		servers <- topologyRunServer(t, spec)
	}()
	// A failed client still waits for the server goroutine before cleanup.
	t.Cleanup(func() { <-servers })
	client := topologyRunClient(t, spec)
	result := <-servers
	require.NotNil(t, result, "the server role failed")
	rec, err := r.Close()
	require.NoError(t, err)
	return topologySmokeRun{spec: spec, rec: rec, server: result, client: client}
}

// clone deep-copies a run through its JSON form, as readback would see it.
func (run topologySmokeRun) clone(t *testing.T) topologySmokeRun {
	t.Helper()
	// Decoding into fresh values: json.Unmarshal reuses an existing slice's backing array.
	out := topologySmokeRun{spec: run.spec}
	out.spec.Fronts = maps.Clone(run.spec.Fronts)
	b, err := json.Marshal(run.rec)
	require.NoError(t, err)
	require.NoError(t, json.Unmarshal(b, &out.rec))
	b, err = json.Marshal(run.server)
	require.NoError(t, err)
	require.NoError(t, json.Unmarshal(b, &out.server))
	b, err = json.Marshal(run.client)
	require.NoError(t, err)
	require.NoError(t, json.Unmarshal(b, &out.client))
	return out
}

func topologyMustArm(name string) topologyArm {
	arm, ok := topologyArmNamed(name)
	if !ok {
		panic("no arm " + name)
	}
	return arm
}

func (run topologySmokeRun) check() error {
	return topologyCheck(run.spec, ordinaryCostHost, run.rec, run.server, run.client)
}

// The functional comparison smoke runs real public QUIC through the relay: every arm on
// the disjoint topology, aggregate on the unequal one, and on the shared bottleneck an
// ordinary arm and Reno primary/backup beside the Reno competitor. Linux runs each case;
// Darwin runs the ordinary arms and refuses the multipath ones, which need public admission.
// No throughput, fairness or statistical result follows from it.
func TestTopologyComparisonSmoke(t *testing.T) {
	cases := []struct {
		kind       relay.Kind
		arm        string
		controller string
	}{
		{relay.KindDisjoint, "single-a", "bbrv3"},
		{relay.KindDisjoint, "single-b", "bbrv3"},
		{relay.KindDisjoint, "pair", "bbrv3"},
		{relay.KindDisjoint, "primary-backup", "bbrv3"},
		{relay.KindDisjoint, "aggregate", "bbrv3"},
		{relay.KindUnequal, "aggregate", "bbrv3"},
		{relay.KindShared, "single-a", "bbrv3"},
		{relay.KindShared, "primary-backup", "reno"},
	}
	for _, c := range cases {
		t.Run(string(c.kind)+"/"+c.arm+"/"+c.controller, func(t *testing.T) {
			spec := topologySpec{Topology: c.kind, Arm: c.arm, Controller: c.controller}
			arm, _ := topologyArmNamed(c.arm)
			if arm.Multipath && !ordinaryCostHost.negotiatedMultipath {
				require.ErrorContains(t, spec.validate(ordinaryCostHost), "negotiated multipath")
				return
			}
			run := topologySmoke(t, c.kind, c.arm, c.controller)
			require.NoError(t, run.check())
			require.Empty(t, topologyFailures(run.spec, run.server, run.client))
			for _, f := range run.client.Flows {
				got := run.server.Flows[f.Label]
				require.NotNil(t, got, f.Label)
				require.NotZero(t, got.StreamBytes, "%s: receiver-counted STREAM delivery", f.Label)
				require.LessOrEqual(t, got.StreamBytes, f.StreamBytesWritten)
				if f.DatagramRate > 0 {
					require.NotZero(t, got.DatagramsUseful, f.Label)
					require.NotZero(t, got.DatagramLatency.Count, f.Label)
				}
				require.Positive(t, got.MaxGapNS, f.Label)
			}
			if c.kind == relay.KindShared && c.arm == "single-a" {
				topologyRefusals(t, run)
			}
		})
	}
}

// topologyRefusals mutates a valid shared single-a run: each missing or inconsistent
// identity, metric, demand, receiver count or route is refused, and file readback
// accepts only the strict records.
func topologyRefusals(t *testing.T, run topologySmokeRun) {
	t.Helper()
	require.Equal(t, uint64(0), run.rec.Routes[1].Forward.Received, "single-a sends nothing through route b")
	focal := run.client.Flows[0].Label
	for name, mutate := range map[string]func(*topologySmokeRun){
		"missing arm identity":      func(r *topologySmokeRun) { r.client.Identity.Arm = "" },
		"other arm":                 func(r *topologySmokeRun) { r.spec.Arm = "single-b" },
		"other controller":          func(r *topologySmokeRun) { r.client.Flows[0].Controller = "reno" },
		"missing topology identity": func(r *topologySmokeRun) { r.server.Identity.Topology = "" },
		"other relay configuration": func(r *topologySmokeRun) { r.rec.Config.Routes[0].DelayNS++ },
		"unrealized front": func(r *topologySmokeRun) {
			r.spec.Fronts["a"], r.spec.Fronts["b"] = r.spec.Fronts["b"], r.spec.Fronts["a"]
		},
		"missing competitor": func(r *topologySmokeRun) { r.client.Flows = r.client.Flows[:1] },
		"unmatched demand":   func(r *topologySmokeRun) { r.client.Flows[0].ObjectsInFlight = 2 },
		"missing CPU metric": func(r *topologySmokeRun) {
			r.server.SelfCPU = ordinaryCostUnavailable("ns", ordinaryCostCPUSource, "test")
		},
		"sender-counted useful bytes": func(r *topologySmokeRun) {
			v := *r.server.UsefulBytes.Value + r.client.Flows[0].StreamBytesWritten
			r.server.UsefulBytes.Value = &v
		},
		"receiver beyond sender": func(r *topologySmokeRun) {
			r.server.Flows[focal].DatagramsUseful = r.client.Flows[0].DatagramsOffered + 1
		},
		"measured DATAGRAMs reported unsampled": func(r *topologySmokeRun) {
			r.server.Flows[focal].DatagramLatency = &ordinaryCostLatency{}
		},
		"unused route carried traffic": func(r *topologySmokeRun) { r.rec.Routes[1].Forward.Received = 1 },
		"server saw another route": func(r *topologySmokeRun) {
			for i := range r.server.Connections {
				if slices.Equal(r.server.Connections[i].Labels, []string{focal}) {
					r.server.Connections[i].Remotes = []netip.AddrPort{r.rec.Routes[1].Back}
				}
			}
		},
		"unknown record version": func(r *topologySmokeRun) { r.server.Version = 2 },
		"no server witness": func(r *topologySmokeRun) {
			r.server.Connections = slices.DeleteFunc(r.server.Connections, func(c topologyServerConnResult) bool {
				return slices.Equal(c.Labels, []string{focal})
			})
		},
		"BBR loss claimed": func(r *topologySmokeRun) {
			r.client.Flows[0].Lost = ordinaryCostObserved(0, "packets", "ConnectionStats().PacketsLost")
		},
		"Reno loss withheld": func(r *topologySmokeRun) {
			r.client.Flows[1].Lost = ordinaryCostUnavailable("packets", "ConnectionStats().PacketsLost", "test")
		},
	} {
		mutated := run.clone(t)
		require.NoError(t, mutated.check(), "the clone is valid")
		mutate(&mutated)
		require.Error(t, mutated.check(), name)
	}

	// File readback: the relay's own reader and strict role records.
	dir := t.TempDir()
	write := func(name string, v any) string {
		path := filepath.Join(dir, name)
		b, err := json.Marshal(v)
		require.NoError(t, err)
		require.NoError(t, os.WriteFile(path, b, 0o644))
		return path
	}
	spec := run.spec
	spec.RelayRecord, spec.ServerResult, spec.ClientResult = write("relay.json", run.rec), write("server.json", run.server), write("client.json", run.client)
	observation, err := topologyVerify(spec, ordinaryCostHost)
	require.NoError(t, err)
	require.Empty(t, observation.WorkloadFailures)
	require.Equal(t, topologyResultVersion, observation.Version)

	b, err := os.ReadFile(spec.ServerResult)
	require.NoError(t, err)
	require.NoError(t, os.WriteFile(spec.ServerResult, append(b[:len(b)-1], []byte(`,"extra":1}`)...), 0o644))
	_, err = topologyVerify(spec, ordinaryCostHost)
	require.ErrorContains(t, err, "unknown field")
	spec.ServerResult = write("server2.json", run.server)

	// A field the producer never wrote is refused, not read as its zero value: an omitted
	// availability would pass for BBR's unavailable loss metric, an omitted seed for seed 0.
	omit := func(name string, v any, drop func(map[string]any)) string {
		var doc map[string]any
		b, err := json.Marshal(v)
		require.NoError(t, err)
		require.NoError(t, json.Unmarshal(b, &doc))
		drop(doc)
		return write(name, doc)
	}
	require.Equal(t, "bbrv3", run.spec.Controller, "the shared run's loss metric is unavailable")
	spec.ClientResult = omit("client-lost.json", run.client, func(doc map[string]any) {
		delete(doc["flows"].([]any)[0].(map[string]any)["packets_lost_metric"].(map[string]any), "available")
	})
	_, err = topologyVerify(spec, ordinaryCostHost)
	require.ErrorContains(t, err, "packets_lost_metric.available is not stated")
	spec.ClientResult = write("client2.json", run.client)
	spec.ServerResult = omit("server-seed.json", run.server, func(doc map[string]any) {
		delete(doc["identity"].(map[string]any), "seed")
	})
	_, err = topologyVerify(spec, ordinaryCostHost)
	require.ErrorContains(t, err, "identity.seed is not stated")
	spec.ServerResult = omit("server-null-seed.json", run.server, func(doc map[string]any) {
		doc["identity"].(map[string]any)["seed"] = nil
	})
	_, err = topologyVerify(spec, ordinaryCostHost)
	require.ErrorContains(t, err, "identity.seed is not stated", "a null seed states no identity")
	spec.ServerResult = write("server3.json", run.server)
	spec.ClientResult = omit("client-null-lost.json", run.client, func(doc map[string]any) {
		doc["flows"].([]any)[0].(map[string]any)["packets_lost_metric"].(map[string]any)["available"] = nil
	})
	_, err = topologyVerify(spec, ordinaryCostHost)
	require.ErrorContains(t, err, "packets_lost_metric.available is not stated", "a null availability states nothing")
	spec.ClientResult = write("client3.json", run.client)
	spec.ServerResult = omit("server-null-sample.json", run.server, func(doc map[string]any) {
		doc["flows"].(map[string]any)["focal-1"].(map[string]any)["stream_series"].([]any)[0] = nil
	})
	_, err = topologyVerify(spec, ordinaryCostHost)
	require.ErrorContains(t, err, "stream_series[0] is not stated", "a null sample is not an observed zero")
	spec.ServerResult = write("server4.json", run.server)

	unbalanced := run.clone(t).rec
	unbalanced.Routes[0].Forward.Delivered++
	spec.RelayRecord = write("relay2.json", unbalanced)
	_, err = topologyVerify(spec, ordinaryCostHost)
	require.Error(t, err, "the relay's readback refuses an unbalanced record")
}
