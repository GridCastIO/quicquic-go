//go:build ordinarycost && ((linux && amd64) || (darwin && arm64))

package quic

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/rand/v2"
	"net"
	"net/netip"
	"os"
	"runtime"
	"slices"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/GridCastIO/quicquic-go/internal/testdata"
	"github.com/GridCastIO/quicquic-go/interop/multipath/relay"

	"github.com/stretchr/testify/require"
)

// MP-MAC C4 (#1493) binds the C3 topology relay to public QUIC workloads and the C1 metric
// records. interop/multipath/topology_comparison.py runs the relay as its own udprelay
// process beside one server and one client role and reads the observation back through
// the verify role. The client is the sender: each focal connection uploads fixed-size
// STREAM objects and a fixed-rate DATAGRAM flow through the relay, and the server counts
// what arrives. Every arm offers the same total demand; only how the arm's connections and
// paths carry it differs. The relay owns the queues; the transport keeps its own pacing,
// congestion and path decisions. The workload follows the archived B11 definitions
// (8c34fbac874adf55f096b6c67d51244160169422) without its private scheduler selection:
// every arm here reaches only public interfaces.
const (
	topologyALPN = "topology-comparison"
	// topologyWriteBudget is the grant's native request duration, the default of a
	// socket the library owns.
	topologyWriteBudget = 100 * time.Millisecond

	topologyObject = 1 << 20
	// topologyObjectsInFlight and topologyDatagramRate are an arm's total focal demand,
	// split evenly across its focal connections.
	topologyObjectsInFlight = 4
	topologyDatagramRate    = 250
	topologyChunk           = 64 << 10
	topologyDatagram        = 1000
	// topologyDialLead is how long before the timeline's start the client dials, so the
	// relay and server have bound their sockets.
	topologyDialLead = 3 * time.Second
	// topologyDrain separates the window's end from the roles' readings (at half) and
	// their closes (at its end), so no reading sees the run's own close.
	topologyDrain = 2 * time.Second

	topologyRate  = 50_000_000
	topologyDelay = 10 * time.Millisecond

	// topologyResultVersion versions the server, client and observation records.
	topologyResultVersion = 1
)

// Each stream and DATAGRAM starts with its flow's label.
const (
	topologyFocal1 byte = iota + 1
	topologyFocal2
	topologyCompetitor
)

func topologyLabelName(label byte) string {
	switch label {
	case topologyFocal1:
		return "focal-1"
	case topologyFocal2:
		return "focal-2"
	case topologyCompetitor:
		return "competitor"
	}
	return fmt.Sprintf("unknown-%d", label)
}

const (
	topologyPolicyPrimaryBackup = "primary-backup"
	topologyPolicyAggregate     = "aggregate"
)

// topologyArm is one way of carrying the focal demand. Routes are the relay routes its
// focal connections use: one ordinary connection per route, or one multipath connection
// whose path zero takes the first route and whose second path takes the other.
type topologyArm struct {
	Name      string
	Routes    []relay.RouteName
	Multipath bool
	// Policy is the public ConfigureMultipathV1 policy of a multipath arm.
	Policy string
}

// topologyArms is the closed arm inventory, in its canonical order.
var topologyArms = []topologyArm{
	{Name: "single-a", Routes: []relay.RouteName{relay.RouteA}},
	{Name: "single-b", Routes: []relay.RouteName{relay.RouteB}},
	{Name: "pair", Routes: []relay.RouteName{relay.RouteA, relay.RouteB}},
	{Name: "primary-backup", Routes: []relay.RouteName{relay.RouteA, relay.RouteB}, Multipath: true, Policy: topologyPolicyPrimaryBackup},
	{Name: "aggregate", Routes: []relay.RouteName{relay.RouteA, relay.RouteB}, Multipath: true, Policy: topologyPolicyAggregate},
}

func topologyArmNamed(name string) (topologyArm, bool) {
	i := slices.IndexFunc(topologyArms, func(a topologyArm) bool { return a.Name == name })
	if i < 0 {
		return topologyArm{}, false
	}
	return topologyArms[i], true
}

// topologyConnPlan is one client connection: its label, its relay routes in path order,
// and its share of the demand.
type topologyConnPlan struct {
	Label           byte
	Routes          []relay.RouteName
	ObjectsInFlight int
	DatagramRate    int
}

// plan returns the arm's focal connections. Each takes an even share of the total
// demand, so every arm offers the same load.
func (a topologyArm) plan() []topologyConnPlan {
	if a.Multipath {
		return []topologyConnPlan{{Label: topologyFocal1, Routes: a.Routes, ObjectsInFlight: topologyObjectsInFlight, DatagramRate: topologyDatagramRate}}
	}
	plans := make([]topologyConnPlan, len(a.Routes))
	for i, route := range a.Routes {
		plans[i] = topologyConnPlan{
			Label: topologyFocal1 + byte(i), Routes: []relay.RouteName{route},
			ObjectsInFlight: topologyObjectsInFlight / len(a.Routes), DatagramRate: topologyDatagramRate / len(a.Routes),
		}
	}
	return plans
}

// topologyCompetitorPlan is the shared topology's ordinary Reno competitor: STREAM
// objects only, through its own route into the shared queue.
var topologyCompetitorPlan = topologyConnPlan{Label: topologyCompetitor, Routes: []relay.RouteName{relay.RouteCompetitor}, ObjectsInFlight: topologyObjectsInFlight}

// topologyRelayConfig is the relay configuration of one topology kind: B11's queues, each
// holding one bandwidth-delay product of its routes' round trip, with ephemeral IPv4
// loopback fronts.
func topologyRelayConfig(kind relay.Kind, server netip.AddrPort) (relay.Config, error) {
	route := func(name relay.RouteName, queue int, delay time.Duration) relay.Route {
		return relay.Route{Name: name, Front: netip.AddrPortFrom(netip.AddrFrom4([4]byte{127, 0, 0, 1}), 0), Queue: queue, DelayNS: int64(delay)}
	}
	cfg := relay.Config{Kind: kind, Server: server}
	switch kind {
	case relay.KindDisjoint:
		cfg.Queues = []relay.Queue{{RateBPS: topologyRate, LimitBytes: 125_000}, {RateBPS: topologyRate, LimitBytes: 125_000}}
		cfg.Routes = []relay.Route{route(relay.RouteA, 0, topologyDelay), route(relay.RouteB, 1, topologyDelay)}
	case relay.KindUnequal:
		cfg.Queues = []relay.Queue{{RateBPS: topologyRate, LimitBytes: 125_000}, {RateBPS: topologyRate / 2, LimitBytes: 187_500}}
		cfg.Routes = []relay.Route{route(relay.RouteA, 0, topologyDelay), route(relay.RouteB, 1, 3*topologyDelay)}
	case relay.KindShared:
		cfg.Queues = []relay.Queue{{RateBPS: topologyRate, LimitBytes: 125_000}}
		cfg.Routes = []relay.Route{route(relay.RouteA, 0, topologyDelay), route(relay.RouteB, 0, topologyDelay), route(relay.RouteCompetitor, 0, topologyDelay)}
	default:
		return relay.Config{}, fmt.Errorf("unknown topology %q", kind)
	}
	return cfg, cfg.Validate()
}

// topologySpec is one role's instruction. The server and client roles run the workload;
// relay-config writes the topology's relay configuration; verify reads the three
// records back and writes the validated observation.
type topologySpec struct {
	Role       string                             `json:"role"`
	Topology   relay.Kind                         `json:"topology"`
	Arm        string                             `json:"arm"`
	Controller string                             `json:"controller"`
	Seed       uint64                             `json:"seed"`
	Server     netip.AddrPort                     `json:"server"`
	Fronts     map[relay.RouteName]netip.AddrPort `json:"fronts,omitempty"`
	StartAt    int64                              `json:"start_at_unix_ns,omitempty"`
	WarmupNS   int64                              `json:"warmup_ns,omitempty"`
	WindowNS   int64                              `json:"window_ns,omitempty"`
	Output     string                             `json:"output"`
	// The verify role's inputs.
	RelayRecord  string `json:"relay_record,omitempty"`
	ServerResult string `json:"server_result,omitempty"`
	ClientResult string `json:"client_result,omitempty"`
}

// topologyIdentity is what every role record repeats, so readback can match them.
type topologyIdentity struct {
	Topology   relay.Kind     `json:"topology"`
	Arm        string         `json:"arm"`
	Controller string         `json:"controller"`
	Seed       uint64         `json:"seed"`
	Server     netip.AddrPort `json:"server"`
	StartAt    int64          `json:"start_at_unix_ns"`
	WarmupNS   int64          `json:"warmup_ns"`
	WindowNS   int64          `json:"window_ns"`
}

func (s topologySpec) identity() topologyIdentity {
	return topologyIdentity{Topology: s.Topology, Arm: s.Arm, Controller: s.Controller, Seed: s.Seed, Server: s.Server,
		StartAt: s.StartAt, WarmupNS: s.WarmupNS, WindowNS: s.WindowNS}
}

// validate admits the spec's topology, arm and controller on platform. A multipath arm
// needs public admission there, and aggregate needs BBR, as the public constructor
// requires; no ordinary connection stands in for a refused arm.
func (s topologySpec) validate(platform ordinaryCostPlatformProfile) error {
	if s.Controller != "reno" && s.Controller != "bbrv3" {
		return fmt.Errorf("unknown controller %q", s.Controller)
	}
	if _, err := topologyRelayConfig(s.Topology, netip.MustParseAddrPort("127.0.0.1:1")); err != nil {
		return err
	}
	arm, ok := topologyArmNamed(s.Arm)
	if !ok {
		return fmt.Errorf("unknown arm %q", s.Arm)
	}
	if arm.Multipath && !platform.negotiatedMultipath {
		return fmt.Errorf("arm %s needs negotiated multipath, which %s does not admit publicly", arm.Name, platform.name)
	}
	if arm.Policy == topologyPolicyAggregate && s.Controller != "bbrv3" {
		return fmt.Errorf("arm %s: aggregate multipath requires bbrv3", arm.Name)
	}
	return nil
}

// topologyRoutes are the routes of kind's relay, in their canonical order.
func topologyRoutes(kind relay.Kind) []relay.RouteName {
	if kind == relay.KindShared {
		return []relay.RouteName{relay.RouteA, relay.RouteB, relay.RouteCompetitor}
	}
	return []relay.RouteName{relay.RouteA, relay.RouteB}
}

// validateRun checks what the workload roles need beyond validate: the relay's bound
// fronts for exactly the topology's routes, the server and a timeline.
func (s topologySpec) validateRun() error {
	routes := topologyRoutes(s.Topology)
	if len(s.Fronts) != len(routes) {
		return fmt.Errorf("fronts %v do not name exactly the %s routes %v", s.Fronts, s.Topology, routes)
	}
	for _, route := range routes {
		front, ok := s.Fronts[route]
		if !ok || !front.Addr().Is4() || front.Port() == 0 {
			return fmt.Errorf("route %s has no bound IPv4 front", route)
		}
	}
	if !s.Server.Addr().Is4() || s.Server.Port() == 0 {
		return fmt.Errorf("server %s is not an IPv4 address and port", s.Server)
	}
	if s.StartAt <= 0 || s.WarmupNS < 0 || s.WindowNS < int64(time.Second) {
		return errors.New("the timeline needs a start and a window of at least one second")
	}
	return nil
}

func (s topologySpec) timeline() ordinaryCostTimeline {
	start := time.Unix(0, s.StartAt)
	window := start.Add(time.Duration(s.WarmupNS))
	return ordinaryCostTimeline{start: start, window: window, end: window.Add(time.Duration(s.WindowNS))}
}

// topologySecond is t's index in the window's per-second series, or -1 outside it.
func topologySecond(line ordinaryCostTimeline, t time.Time) int {
	if !line.inWindow(t) {
		return -1
	}
	return int(t.Sub(line.window) / time.Second)
}

func topologyConfig(t testing.TB, controller string, multipath bool, policy string) *Config {
	t.Helper()
	conf := &Config{
		EnableDatagrams:                true,
		InitialStreamReceiveWindow:     4 << 20,
		MaxStreamReceiveWindow:         16 << 20,
		InitialConnectionReceiveWindow: 8 << 20,
		MaxConnectionReceiveWindow:     32 << 20,
		MaxIdleTimeout:                 30 * time.Second,
	}
	require.NoError(t, conf.SetCongestionControlV1(controller))
	if multipath {
		require.NoError(t, conf.ConfigureMultipathV1(true, 2, policy))
	}
	return conf
}

func topologyServerTLS() *tls.Config {
	conf := testdata.GetTLSConfig()
	conf.NextProtos = []string{topologyALPN}
	return conf
}

func topologyClientTLS() *tls.Config {
	return &tls.Config{RootCAs: testdata.GetRootCA(), ServerName: "localhost", NextProtos: []string{topologyALPN}}
}

// topologyTransport binds an IPv4 socket. A granted transport uses the public grant, which
// only a platform with public multipath admission reaches.
func topologyTransport(t testing.TB, address netip.AddrPort, granted bool) *Transport {
	t.Helper()
	socket, err := net.ListenUDP("udp4", net.UDPAddrFromAddrPort(address))
	require.NoError(t, err)
	t.Cleanup(func() { socket.Close() })
	tr := &Transport{Conn: socket, ConnectionIDLength: 4}
	t.Cleanup(func() { tr.Close() })
	if granted {
		require.NoError(t, tr.ConfigureMultipathIOV1(topologyWriteBudget))
		// Registered after the close cleanup, so it runs first: a setup failure still
		// closes the transport and waits for its writer to return authority.
		t.Cleanup(func() {
			tr.Close()
			ctx, cancel := context.WithTimeout(context.Background(), ordinaryCostStopTimeout)
			defer cancel()
			tr.WaitMultipathIOStoppedV1(ctx)
		})
	}
	return tr
}

func topologyAddrPort(addr net.Addr) netip.AddrPort {
	ap := addr.(*net.UDPAddr).AddrPort()
	return netip.AddrPortFrom(ap.Addr().Unmap(), ap.Port())
}

// ---- server: the receiver ----

// topologyFlowStats is the receiver's account of one labeled flow. STREAM bytes count when
// read inside the window; a DATAGRAM is useful when its first copy arrives and its send
// timestamp is inside the window.
type topologyFlowStats struct {
	mu sync.Mutex
	// StreamSeries is the STREAM bytes read in each second of the window.
	StreamSeries     []uint64             `json:"stream_series"`
	StreamBytes      uint64               `json:"stream_useful_bytes"`
	ObjectsCompleted uint64               `json:"objects_completed"`
	Completion       *ordinaryCostLatency `json:"object_completion"`
	DatagramsUseful  uint64               `json:"datagrams_useful"`
	DatagramBytes    uint64               `json:"datagram_useful_bytes"`
	// DatagramDuplicates are later copies of a DATAGRAM already seen.
	DatagramDuplicates uint64               `json:"datagram_duplicates"`
	DatagramLatency    *ordinaryCostLatency `json:"datagram_latency"`
	// MaxGapNS is the longest part of the window in which nothing useful arrived.
	MaxGapNS int64 `json:"max_receive_gap_ns"`

	completion ordinaryCostHistogram
	latency    ordinaryCostHistogram
	arrivals   []time.Duration
	seen       map[uint64]struct{}
}

// arrived notes a useful arrival at now, the receive observation that also decided the
// arrival's usefulness; f.mu is held. Arrivals are kept, not folded into a running gap,
// because concurrent receive workers can take the lock out of arrival order.
func (f *topologyFlowStats) arrived(line ordinaryCostTimeline, now time.Time) {
	if line.inWindow(now) {
		f.arrivals = append(f.arrivals, now.Sub(line.window))
	}
}

// finish orders the arrivals, takes the longest gap between the window's boundaries and
// them, and summarizes the latencies.
func (f *topologyFlowStats) finish(line ordinaryCostTimeline) {
	f.mu.Lock()
	defer f.mu.Unlock()
	slices.Sort(f.arrivals)
	last := time.Duration(0)
	for _, at := range f.arrivals {
		f.MaxGapNS = max(f.MaxGapNS, int64(at-last))
		last = at
	}
	f.MaxGapNS = max(f.MaxGapNS, int64(line.end.Sub(line.window)-last))
	f.arrivals = nil
	f.Completion = f.completion.summary()
	f.DatagramLatency = f.latency.summary()
}

type topologyServerConn struct {
	conn   *Conn
	mu     sync.Mutex
	labels map[byte]bool
}

func (c *topologyServerConn) note(label byte) {
	c.mu.Lock()
	c.labels[label] = true
	c.mu.Unlock()
}

type topologyServer struct {
	line    ordinaryCostTimeline
	mu      sync.Mutex
	flows   map[byte]*topologyFlowStats
	errors  atomic.Uint64
	connsMu sync.Mutex
	conns   []*topologyServerConn
	workers sync.WaitGroup
}

func (s *topologyServer) flow(label byte) *topologyFlowStats {
	s.mu.Lock()
	defer s.mu.Unlock()
	f, ok := s.flows[label]
	if !ok {
		f = &topologyFlowStats{StreamSeries: make([]uint64, s.line.seconds()), seen: map[uint64]struct{}{}}
		s.flows[label] = f
	}
	return f
}

func (s *topologyServer) object(entry *topologyServerConn, str *ReceiveStream) {
	var header [9]byte
	if _, err := io.ReadFull(str, header[:]); err != nil {
		if time.Now().Before(s.line.end) {
			s.errors.Add(1)
		}
		return
	}
	label := header[0]
	entry.note(label)
	started := time.Unix(0, int64(binary.BigEndian.Uint64(header[1:])))
	f := s.flow(label)
	buf := make([]byte, topologyChunk)
	total := len(header)
	for {
		n, err := str.Read(buf)
		now := time.Now()
		if n > 0 {
			total += n
			if second := topologySecond(s.line, now); second >= 0 {
				f.mu.Lock()
				f.StreamSeries[second] += uint64(n)
				f.StreamBytes += uint64(n)
				f.arrived(s.line, now)
				f.mu.Unlock()
			}
		}
		if errors.Is(err, io.EOF) {
			if total == topologyObject && s.line.inWindow(now) {
				f.mu.Lock()
				f.ObjectsCompleted++
				f.completion.add(now.Sub(started))
				f.mu.Unlock()
			}
			return
		}
		if err != nil {
			// A stream the sender cancels at the window's end is not an error.
			if now.Before(s.line.end) {
				s.errors.Add(1)
			}
			return
		}
	}
}

func (s *topologyServer) datagrams(entry *topologyServerConn) {
	for {
		b, err := entry.conn.ReceiveDatagram(context.Background())
		if err != nil {
			return
		}
		now := time.Now()
		if len(b) != topologyDatagram {
			s.errors.Add(1)
			continue
		}
		label := b[0]
		entry.note(label)
		seq := binary.BigEndian.Uint64(b[1:])
		sent := time.Unix(0, int64(binary.BigEndian.Uint64(b[9:])))
		f := s.flow(label)
		f.mu.Lock()
		if _, dup := f.seen[seq]; dup {
			f.DatagramDuplicates++
		} else {
			f.seen[seq] = struct{}{}
			if s.line.inWindow(sent) {
				f.DatagramsUseful++
				f.DatagramBytes += uint64(len(b))
				f.latency.add(now.Sub(sent))
				f.arrived(s.line, now)
			}
		}
		f.mu.Unlock()
	}
}

func (s *topologyServer) handle(entry *topologyServerConn) {
	defer s.workers.Done()
	s.workers.Add(1)
	go func() {
		defer s.workers.Done()
		s.datagrams(entry)
	}()
	for {
		str, err := entry.conn.AcceptUniStream(context.Background())
		if err != nil {
			return
		}
		s.workers.Add(1)
		go func() {
			defer s.workers.Done()
			s.object(entry, str)
		}()
	}
}

type topologyServerConnResult struct {
	Labels    []string `json:"labels"`
	Multipath bool     `json:"multipath_negotiated"`
	// Remotes are the connection's peer tuples: the relay route sockets it arrived from.
	Remotes      []netip.AddrPort `json:"remotes"`
	CloseCause   string           `json:"close_cause"`
	TimeoutClose bool             `json:"timeout_close"`
}

type topologyServerResult struct {
	Version             int                  `json:"version"`
	Identity            topologyIdentity     `json:"identity"`
	Platform            ordinaryCostIdentity `json:"platform"`
	Go                  string               `json:"go"`
	Granted             bool                 `json:"granted"`
	Joined              bool                 `json:"joined"`
	MultipathAdvertised bool                 `json:"multipath_advertised"`
	SelfCPU             ordinaryCostMetric   `json:"self_cpu"`
	PeakRSSEnd          ordinaryCostMetric   `json:"peak_rss_end"`
	// UsefulBytes is the focal flows' receiver-counted STREAM and DATAGRAM bytes.
	UsefulBytes  ordinaryCostMetric            `json:"useful_bytes"`
	Flows        map[string]*topologyFlowStats `json:"flows"`
	Connections  []topologyServerConnResult    `json:"connections"`
	StreamErrors uint64                        `json:"stream_errors"`
}

const topologyUsefulSource = "receiver-counted focal STREAM bytes read in the window plus first-copy DATAGRAM bytes sent in the window"

// topologyRemotes returns a connection's peer tuples: every path's remote, ordered by
// wire ID, once multipath is negotiated, or the one remote of an ordinary connection.
func topologyRemotes(conn *Conn) ([]netip.AddrPort, []topologyPathResult) {
	if negotiated, _ := conn.MultipathNegotiatedV1(); !negotiated {
		return []netip.AddrPort{topologyAddrPort(conn.RemoteAddr())}, nil
	}
	var paths []topologyPathResult
	for _, path := range conn.PathsV1() {
		state, err := path.StateV1()
		if err != nil {
			continue
		}
		paths = append(paths, topologyPathResult{WireID: state.WireID, Lifecycle: state.Lifecycle, LocalUse: state.LocalUse,
			Primary: state.Primary, Remote: netip.AddrPortFrom(state.Remote.Addr().Unmap(), state.Remote.Port())})
	}
	slices.SortFunc(paths, func(a, b topologyPathResult) int { return int(a.WireID) - int(b.WireID) })
	remotes := make([]netip.AddrPort, len(paths))
	for i, p := range paths {
		remotes[i] = p.Remote
	}
	return remotes, paths
}

func topologyRunServer(t testing.TB, spec topologySpec) *topologyServerResult {
	t.Helper()
	require.NoError(t, spec.validate(ordinaryCostHost))
	require.NoError(t, spec.validateRun())
	line := spec.timeline()
	// The receiver advertises the public profile wherever it is admitted, in every arm, so
	// only the client's arm decides what is negotiated.
	advertised := ordinaryCostHost.negotiatedMultipath
	tr := topologyTransport(t, spec.Server, advertised)
	ln, err := tr.Listen(topologyServerTLS(), topologyConfig(t, "reno", advertised, topologyPolicyPrimaryBackup))
	require.NoError(t, err)
	s := &topologyServer{line: line, flows: map[byte]*topologyFlowStats{}}
	s.workers.Add(1)
	go func() {
		defer s.workers.Done()
		for {
			conn, err := ln.Accept(context.Background())
			if err != nil {
				return
			}
			entry := &topologyServerConn{conn: conn, labels: map[byte]bool{}}
			s.connsMu.Lock()
			s.conns = append(s.conns, entry)
			s.connsMu.Unlock()
			s.workers.Add(1)
			go s.handle(entry)
		}
	}()

	result := &topologyServerResult{
		Version: topologyResultVersion, Identity: spec.identity(), Platform: ordinaryCostHost.identity(), Go: runtime.Version(),
		Granted: advertised, MultipathAdvertised: advertised, Flows: map[string]*topologyFlowStats{},
	}
	time.Sleep(time.Until(line.window))
	usageStart := ordinaryCostRusage()
	time.Sleep(time.Until(line.end))
	usageEnd := ordinaryCostRusage()
	result.SelfCPU = ordinaryCostCPUMetric(ordinaryCostWindowRusage{Start: usageStart, End: usageEnd, Delta: usageEnd.since(usageStart)})

	// The client holds its connections until the drain ends, so no reading sees a close.
	time.Sleep(time.Until(line.end.Add(topologyDrain / 2)))
	// Mode, peer tuples and close cause are sampled before the close; labels are attached
	// after the receive workers join, with the flow totals they attribute.
	s.connsMu.Lock()
	sampled := slices.Clone(s.conns)
	for _, entry := range sampled {
		negotiated, err := entry.conn.MultipathNegotiatedV1()
		require.NoError(t, err)
		remotes, _ := topologyRemotes(entry.conn)
		cause, timedOut := ordinaryCostCloseCause(entry.conn)
		result.Connections = append(result.Connections, topologyServerConnResult{
			Multipath: negotiated, Remotes: remotes, CloseCause: cause, TimeoutClose: timedOut,
		})
	}
	s.connsMu.Unlock()
	result.PeakRSSEnd, err = ordinaryCostPeakRSS()
	require.NoError(t, err)

	time.Sleep(time.Until(line.end.Add(topologyDrain)))
	require.NoError(t, ln.Close())
	require.NoError(t, tr.Close())
	if advertised {
		ctx, cancel := context.WithTimeout(context.Background(), ordinaryCostStopTimeout)
		defer cancel()
		result.Joined = tr.WaitMultipathIOStoppedV1(ctx) == nil
	}
	// Late DATAGRAMs sent inside the window can still arrive during the drain, so the flow
	// accounts are final only once every receive worker has returned.
	s.workers.Wait()
	result.StreamErrors = s.errors.Load()
	for i, entry := range sampled {
		labels := []string{}
		entry.mu.Lock()
		for label := range entry.labels {
			labels = append(labels, topologyLabelName(label))
		}
		entry.mu.Unlock()
		slices.Sort(labels)
		result.Connections[i].Labels = labels
	}
	var useful uint64
	for label, f := range s.flows {
		f.finish(line)
		result.Flows[topologyLabelName(label)] = f
		if label != topologyCompetitor {
			useful += f.StreamBytes + f.DatagramBytes
		}
	}
	result.UsefulBytes = ordinaryCostObserved(useful, "bytes", topologyUsefulSource)
	return result
}

// ---- client: the sender ----

type topologyPathResult struct {
	WireID    uint32         `json:"wire_id"`
	Lifecycle string         `json:"lifecycle"`
	LocalUse  string         `json:"local_use"`
	Primary   bool           `json:"primary"`
	Remote    netip.AddrPort `json:"remote"`
}

// topologyClientFlow is the sender's account of one connection. Its counters describe
// what was offered, never what arrived.
type topologyClientFlow struct {
	Label           string               `json:"label"`
	Controller      string               `json:"controller"`
	Routes          []relay.RouteName    `json:"routes"`
	Policy          string               `json:"policy,omitempty"`
	ObjectsInFlight int                  `json:"objects_in_flight"`
	DatagramRate    int                  `json:"datagram_rate"`
	Multipath       bool                 `json:"multipath_negotiated"`
	Paths           []topologyPathResult `json:"paths,omitempty"`
	// Remotes are the relay fronts the connection sent to, in path order.
	Remotes            []netip.AddrPort   `json:"remotes"`
	ObjectsStarted     uint64             `json:"objects_started"`
	StreamBytesWritten uint64             `json:"stream_bytes_written"`
	DatagramsOffered   uint64             `json:"datagrams_offered"`
	DatagramErrors     uint64             `json:"datagram_send_errors"`
	PacketsSent        uint64             `json:"packets_sent"`
	Lost               ordinaryCostMetric `json:"packets_lost_metric"`
	CloseCause         string             `json:"close_cause"`
	TimeoutClose       bool               `json:"timeout_close"`

	conn    *Conn
	label   byte
	started atomic.Uint64
	written atomic.Uint64
	offered atomic.Uint64
	failed  atomic.Uint64
}

type topologyClientResult struct {
	Version  int                  `json:"version"`
	Identity topologyIdentity     `json:"identity"`
	Platform ordinaryCostIdentity `json:"platform"`
	Go       string               `json:"go"`
	SelfCPU  ordinaryCostMetric   `json:"self_cpu"`
	// Joined reports that every granted client transport returned its write authority.
	Joined bool                  `json:"joined"`
	Flows  []*topologyClientFlow `json:"flows"`
}

func (f *topologyClientFlow) objects(line ordinaryCostTimeline, payload []byte) {
	ctx, cancel := context.WithDeadline(context.Background(), line.end)
	defer cancel()
	for time.Now().Before(line.end) {
		str, err := f.conn.OpenUniStreamSync(ctx)
		if err != nil {
			return
		}
		str.SetWriteDeadline(line.end)
		f.started.Add(1)
		var header [9]byte
		header[0] = f.label
		binary.BigEndian.PutUint64(header[1:], uint64(time.Now().UnixNano()))
		if _, err := str.Write(header[:]); err != nil {
			str.CancelWrite(0)
			return
		}
		remaining := topologyObject - len(header)
		for remaining > 0 {
			n, err := str.Write(payload[:min(remaining, len(payload))])
			f.written.Add(uint64(n))
			remaining -= n
			if err != nil {
				str.CancelWrite(0)
				return
			}
		}
		str.Close()
	}
}

func (f *topologyClientFlow) datagrams(line ordinaryCostTimeline) {
	if f.DatagramRate == 0 {
		return
	}
	period := time.Second / time.Duration(f.DatagramRate)
	// Admission waits at most until the window ends; a refused message is a send error.
	ctx, cancel := context.WithDeadline(context.Background(), line.end)
	defer cancel()
	b := make([]byte, topologyDatagram)
	b[0] = f.label
	var seq uint64
	for next := line.start; next.Before(line.end); next = next.Add(period) {
		time.Sleep(time.Until(next))
		seq++
		now := time.Now()
		binary.BigEndian.PutUint64(b[1:], seq)
		binary.BigEndian.PutUint64(b[9:], uint64(now.UnixNano()))
		err := f.conn.SendDatagramContext(ctx, b)
		if line.inWindow(now) {
			f.offered.Add(1)
			if err != nil {
				f.failed.Add(1)
			}
		}
	}
}

func topologyDial(t testing.TB, tr *Transport, front netip.AddrPort, conf *Config) *Conn {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), topologyDialLead)
	defer cancel()
	conn, err := tr.Dial(ctx, net.UDPAddrFromAddrPort(front), topologyClientTLS(), conf)
	require.NoError(t, err)
	return conn
}

func topologyRunClient(t testing.TB, spec topologySpec) *topologyClientResult {
	t.Helper()
	require.NoError(t, spec.validate(ordinaryCostHost))
	require.NoError(t, spec.validateRun())
	arm, _ := topologyArmNamed(spec.Arm)
	line := spec.timeline()
	time.Sleep(time.Until(line.start.Add(-topologyDialLead)))

	var granted []*Transport
	var flows []*topologyClientFlow
	connect := func(plan topologyConnPlan, controller string, multipath bool, policy string) {
		tr := topologyTransport(t, netip.MustParseAddrPort("127.0.0.1:0"), multipath)
		if multipath {
			granted = append(granted, tr)
		}
		conn := topologyDial(t, tr, spec.Fronts[plan.Routes[0]], topologyConfig(t, controller, multipath, policy))
		for _, route := range plan.Routes[1:] {
			second := topologyTransport(t, netip.MustParseAddrPort("127.0.0.1:0"), true)
			granted = append(granted, second)
			ctx, cancel := context.WithTimeout(context.Background(), topologyDialLead)
			path, err := conn.OpenPathV1(ctx, second, net.UDPAddrFromAddrPort(spec.Fronts[route]))
			cancel()
			require.NoError(t, err)
			// A validated path starts as a backup; aggregate uses it only once active.
			if policy == topologyPolicyAggregate {
				require.NoError(t, path.SetLocalUseV1("active"))
			}
		}
		flows = append(flows, &topologyClientFlow{
			Label: topologyLabelName(plan.Label), Controller: conn.CongestionControlV1(), Routes: plan.Routes, Policy: policy,
			ObjectsInFlight: plan.ObjectsInFlight, DatagramRate: plan.DatagramRate, conn: conn, label: plan.Label,
		})
	}
	for _, plan := range arm.plan() {
		connect(plan, spec.Controller, arm.Multipath, arm.Policy)
	}
	if spec.Topology == relay.KindShared {
		connect(topologyCompetitorPlan, "reno", false, "")
	}
	require.False(t, time.Now().After(line.start), "setup outlasted its budget")
	time.Sleep(time.Until(line.start))

	random := rand.New(rand.NewPCG(spec.Seed, spec.Seed))
	payload := make([]byte, topologyChunk)
	for i := range payload {
		payload[i] = byte(random.Uint32())
	}
	var wait sync.WaitGroup
	for _, f := range flows {
		for range f.ObjectsInFlight {
			wait.Add(1)
			go func() {
				defer wait.Done()
				f.objects(line, payload)
			}()
		}
		wait.Add(1)
		go func() {
			defer wait.Done()
			f.datagrams(line)
		}()
	}
	time.Sleep(time.Until(line.window))
	usageStart := ordinaryCostRusage()
	time.Sleep(time.Until(line.end))
	usageEnd := ordinaryCostRusage()
	wait.Wait()
	result := &topologyClientResult{
		Version: topologyResultVersion, Identity: spec.identity(), Platform: ordinaryCostHost.identity(), Go: runtime.Version(),
		SelfCPU: ordinaryCostCPUMetric(ordinaryCostWindowRusage{Start: usageStart, End: usageEnd, Delta: usageEnd.since(usageStart)}),
	}
	// Paths and statistics are read before any close would retire them.
	time.Sleep(time.Until(line.end.Add(topologyDrain / 2)))
	for _, f := range flows {
		var err error
		f.Multipath, err = f.conn.MultipathNegotiatedV1()
		require.NoError(t, err)
		f.Remotes, f.Paths = topologyRemotes(f.conn)
		stats := f.conn.ConnectionStats()
		f.PacketsSent = stats.PacketsSent
		f.Lost = ordinaryCostLostMetric(f.Controller, stats.PacketsLost)
		f.CloseCause, f.TimeoutClose = ordinaryCostCloseCause(f.conn)
		f.ObjectsStarted, f.StreamBytesWritten = f.started.Load(), f.written.Load()
		f.DatagramsOffered, f.DatagramErrors = f.offered.Load(), f.failed.Load()
		result.Flows = append(result.Flows, f)
	}
	time.Sleep(time.Until(line.end.Add(topologyDrain)))
	for _, f := range flows {
		require.NoError(t, f.conn.CloseWithError(0, ""))
	}
	result.Joined = true
	for _, tr := range granted {
		require.NoError(t, tr.Close())
		ctx, cancel := context.WithTimeout(context.Background(), ordinaryCostStopTimeout)
		joined := tr.WaitMultipathIOStoppedV1(ctx) == nil // every grant is waited for
		cancel()
		result.Joined = result.Joined && joined
	}
	return result
}

// ---- readback ----

// topologyObservation is the verify role's validated record of one observation.
type topologyObservation struct {
	Version  int                   `json:"version"`
	Identity topologyIdentity      `json:"identity"`
	Platform ordinaryCostIdentity  `json:"platform"`
	Relay    relay.Record          `json:"relay"`
	Server   *topologyServerResult `json:"server"`
	Client   *topologyClientResult `json:"client"`
	// WorkloadFailures are functional failures of a valid record, never record errors.
	WorkloadFailures []string `json:"workload_failures"`
}

// topologyDecode reads exactly one JSON value into v, refusing unknown fields and
// trailing data.
func topologyDecode(r io.Reader, v any) error {
	dec := json.NewDecoder(r)
	dec.DisallowUnknownFields()
	if err := dec.Decode(v); err != nil {
		return err
	}
	if _, err := dec.Token(); !errors.Is(err, io.EOF) {
		return errors.New("trailing data")
	}
	return nil
}

// topologyDecodeFile reads a role record strictly and completely: no unknown field, no
// trailing data, and every field the record encodes stated in the file. Decoding fills an
// omitted field with its zero value, which would otherwise pass a zero seed or an
// unavailable BBR loss metric the producer never wrote.
func topologyDecodeFile(path string, v any) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	if err := topologyDecode(bytes.NewReader(data), v); err != nil {
		return fmt.Errorf("%s: %w", path, err)
	}
	encoded, err := json.Marshal(v)
	if err != nil {
		return err
	}
	var stated, want any
	if err := json.Unmarshal(data, &stated); err != nil {
		return err
	}
	if err := json.Unmarshal(encoded, &want); err != nil {
		return err
	}
	if err := topologyStated(stated, want, "record"); err != nil {
		return fmt.Errorf("%s: %w", path, err)
	}
	return nil
}

// topologyStated requires stated to carry every key want has, recursively, with a null
// only where the record itself encodes one.
func topologyStated(stated, want any, at string) error {
	if stated == nil && want != nil {
		return fmt.Errorf("%s is not stated", at)
	}
	switch want := want.(type) {
	case map[string]any:
		got, _ := stated.(map[string]any)
		for key, value := range want {
			v, ok := got[key]
			if !ok {
				return fmt.Errorf("%s.%s is not stated", at, key)
			}
			if err := topologyStated(v, value, at+"."+key); err != nil {
				return err
			}
		}
	case []any:
		got, _ := stated.([]any)
		for i, value := range want {
			if i >= len(got) {
				return fmt.Errorf("%s[%d] is not stated", at, i)
			}
			if err := topologyStated(got[i], value, fmt.Sprintf("%s[%d]", at, i)); err != nil {
				return err
			}
		}
	}
	return nil
}

// topologyVerify reads the relay record through the relay's own readback and both role
// records strictly, and validates the observation they form.
func topologyVerify(spec topologySpec, platform ordinaryCostPlatformProfile) (*topologyObservation, error) {
	f, err := os.Open(spec.RelayRecord)
	if err != nil {
		return nil, err
	}
	rec, err := relay.ReadRecord(f)
	f.Close()
	if err != nil {
		return nil, err
	}
	var server topologyServerResult
	if err := topologyDecodeFile(spec.ServerResult, &server); err != nil {
		return nil, err
	}
	var client topologyClientResult
	if err := topologyDecodeFile(spec.ClientResult, &client); err != nil {
		return nil, err
	}
	if err := topologyCheck(spec, platform, rec, &server, &client); err != nil {
		return nil, err
	}
	return &topologyObservation{
		Version: topologyResultVersion, Identity: spec.identity(), Platform: platform.identity(), Relay: rec,
		Server: &server, Client: &client, WorkloadFailures: topologyFailures(spec, &server, &client),
	}, nil
}

// topologyCheck is the comparison's record validation. It requires one identity across
// the spec and every record, the topology's own relay configuration and realized fronts,
// the arm's exact connections, controllers and matched demand, receiver counts within
// sender counts, the C1 metrics the comparison reads, and route use realized by the
// relay: a route the arm does not use carries nothing, and every route it uses delivers
// in both directions. It judges no performance.
func topologyCheck(spec topologySpec, platform ordinaryCostPlatformProfile, rec relay.Record, server *topologyServerResult, client *topologyClientResult) error {
	if err := spec.validate(platform); err != nil {
		return err
	}
	if err := spec.validateRun(); err != nil {
		return err
	}
	arm, _ := topologyArmNamed(spec.Arm)
	want := spec.identity()
	for role, r := range map[string]struct {
		version  int
		identity topologyIdentity
		platform ordinaryCostIdentity
		goVer    string
	}{"server": {server.Version, server.Identity, server.Platform, server.Go}, "client": {client.Version, client.Identity, client.Platform, client.Go}} {
		if r.version != topologyResultVersion {
			return fmt.Errorf("%s record version %d, want %d", role, r.version, topologyResultVersion)
		}
		if r.identity != want {
			return fmt.Errorf("%s identity %+v is not the spec's %+v", role, r.identity, want)
		}
		if r.platform != platform.identity() || r.platform.GOOS != platform.goos || r.platform.GOARCH != platform.goarch {
			return fmt.Errorf("%s platform %+v is not %s", role, r.platform, platform.name)
		}
		if r.goVer == "" || r.goVer != rec.Go {
			return fmt.Errorf("%s toolchain %q is not the relay's %q", role, r.goVer, rec.Go)
		}
	}
	if rec.GOOS != platform.goos || rec.GOARCH != platform.goarch {
		return fmt.Errorf("relay ran on %s/%s, not %s", rec.GOOS, rec.GOARCH, platform.name)
	}

	// Topology identity: the relay ran this topology's configuration and bound the fronts
	// the client used.
	cfg, err := topologyRelayConfig(spec.Topology, spec.Server)
	if err != nil {
		return err
	}
	recCfg, err := json.Marshal(rec.Config)
	if err != nil {
		return err
	}
	wantCfg, err := json.Marshal(cfg)
	if err != nil {
		return err
	}
	if string(recCfg) != string(wantCfg) {
		return fmt.Errorf("relay configuration %s is not the %s topology's %s", recCfg, spec.Topology, wantCfg)
	}
	backs := map[relay.RouteName]netip.AddrPort{}
	used := map[relay.RouteName]bool{}
	for _, route := range rec.Routes {
		if spec.Fronts[route.Name] != route.Front {
			return fmt.Errorf("route %s was bound at %s, but the client was given %s", route.Name, route.Front, spec.Fronts[route.Name])
		}
		backs[route.Name] = route.Back
	}

	// Arm identity and matched demand: exactly the arm's connections, then the competitor.
	plans := arm.plan()
	if spec.Topology == relay.KindShared {
		plans = append(plans, topologyCompetitorPlan)
	}
	if len(client.Flows) != len(plans) {
		return fmt.Errorf("arm %s on %s needs %d client connections, got %d", arm.Name, spec.Topology, len(plans), len(client.Flows))
	}
	var objects, rate int
	for i, plan := range plans {
		f := client.Flows[i]
		if f == nil {
			return fmt.Errorf("client flow %d is missing", i)
		}
		competitor := plan.Label == topologyCompetitor
		controller, policy := spec.Controller, arm.Policy
		if competitor {
			controller, policy = "reno", ""
		}
		if f.Label != topologyLabelName(plan.Label) || !slices.Equal(f.Routes, plan.Routes) || f.Policy != policy {
			return fmt.Errorf("client flow %d (%s over %v, policy %q) is not arm %s's %s over %v", i, f.Label, f.Routes, f.Policy, arm.Name, topologyLabelName(plan.Label), plan.Routes)
		}
		if f.Controller != controller {
			return fmt.Errorf("%s ran %s, not %s", f.Label, f.Controller, controller)
		}
		if f.ObjectsInFlight != plan.ObjectsInFlight || f.DatagramRate != plan.DatagramRate {
			return fmt.Errorf("%s offered %d objects and %d DATAGRAMs/s, not its share %d and %d", f.Label, f.ObjectsInFlight, f.DatagramRate, plan.ObjectsInFlight, plan.DatagramRate)
		}
		if !competitor {
			objects += f.ObjectsInFlight
			rate += f.DatagramRate
		}
		if err := topologyCheckLost(f.Lost, controller); err != nil {
			return fmt.Errorf("%s: %w", f.Label, err)
		}
		// The client sent to the relay fronts of its own routes, in path order.
		fronts := make([]netip.AddrPort, len(plan.Routes))
		for j, route := range plan.Routes {
			fronts[j] = spec.Fronts[route]
			used[route] = true
		}
		if f.Multipath && !slices.Equal(f.Remotes, fronts) || !f.Multipath && !slices.Equal(f.Remotes, fronts[:1]) {
			return fmt.Errorf("%s sent to %v, not its route fronts %v", f.Label, f.Remotes, fronts)
		}
	}
	if objects != topologyObjectsInFlight || rate != topologyDatagramRate {
		return fmt.Errorf("arm %s offered %d objects and %d DATAGRAMs/s, not the matched %d and %d", arm.Name, objects, rate, topologyObjectsInFlight, topologyDatagramRate)
	}

	// Receiver counts never exceed what the sender offered.
	for _, f := range client.Flows {
		got := server.Flows[f.Label]
		if got == nil {
			continue
		}
		if got.StreamBytes > f.StreamBytesWritten || got.ObjectsCompleted > f.ObjectsStarted || got.DatagramsUseful > f.DatagramsOffered {
			return fmt.Errorf("%s: the receiver counted %d STREAM bytes, %d objects and %d DATAGRAMs, beyond the %d, %d and %d sent",
				f.Label, got.StreamBytes, got.ObjectsCompleted, got.DatagramsUseful, f.StreamBytesWritten, f.ObjectsStarted, f.DatagramsOffered)
		}
	}
	var useful uint64
	for label, got := range server.Flows {
		if !slices.ContainsFunc(client.Flows, func(f *topologyClientFlow) bool { return f.Label == label }) {
			return fmt.Errorf("the receiver counted a flow %q that no connection sent", label)
		}
		if got == nil || len(got.StreamSeries) != int(time.Duration(spec.WindowNS)/time.Second) {
			return fmt.Errorf("%s: the STREAM series does not cover the window", label)
		}
		var series uint64
		for _, bytes := range got.StreamSeries {
			series += bytes
		}
		if series != got.StreamBytes || got.DatagramBytes != got.DatagramsUseful*topologyDatagram {
			return fmt.Errorf("%s: useful bytes do not match their series and DATAGRAM count", label)
		}
		if got.MaxGapNS < 0 || got.MaxGapNS > spec.WindowNS || got.Completion == nil || got.DatagramLatency == nil {
			return fmt.Errorf("%s: gap or latency account is missing", label)
		}
		// Each latency sample is taken with the count it describes.
		if got.Completion.Count != got.ObjectsCompleted || got.DatagramLatency.Count != got.DatagramsUseful {
			return fmt.Errorf("%s: %d completion and %d DATAGRAM latency samples for %d objects and %d DATAGRAMs",
				label, got.Completion.Count, got.DatagramLatency.Count, got.ObjectsCompleted, got.DatagramsUseful)
		}
		if label != topologyLabelName(topologyCompetitor) {
			useful += got.StreamBytes + got.DatagramBytes
		}
	}

	// The C1 metrics the comparison reads.
	for name, m := range map[string]ordinaryCostMetric{"server self_cpu": server.SelfCPU, "client self_cpu": client.SelfCPU, "server peak_rss_end": server.PeakRSSEnd} {
		if !m.Available || m.Value == nil || m.Source == "" || m.Unit == "" {
			return fmt.Errorf("%s is not an observed metric", name)
		}
	}
	if u := server.UsefulBytes; !u.Available || u.Value == nil || *u.Value != useful || u.Unit != "bytes" || u.Source != topologyUsefulSource {
		return fmt.Errorf("server useful_bytes does not total the focal flows' %d receiver-counted bytes", useful)
	}

	// Realized topology: the server saw each connection from the relay sockets of its
	// routes, and the relay carried traffic exactly on the routes in use.
	if server.Granted != platform.negotiatedMultipath || server.MultipathAdvertised != platform.negotiatedMultipath {
		return errors.New("server grant or advertisement does not match the platform's public admission")
	}
	attributed := map[string]bool{}
	for _, conn := range server.Connections {
		switch {
		case len(conn.Labels) == 0:
			continue // a connection that carried no labeled flow has nothing to attribute
		case len(conn.Labels) > 1 || attributed[conn.Labels[0]]:
			return fmt.Errorf("server connections mix or repeat flows: %v", conn.Labels)
		}
		attributed[conn.Labels[0]] = true
		i := slices.IndexFunc(client.Flows, func(f *topologyClientFlow) bool { return f.Label == conn.Labels[0] })
		if i < 0 {
			return fmt.Errorf("server connection labeled %s matches no client connection", conn.Labels[0])
		}
		f := client.Flows[i]
		if conn.Multipath != f.Multipath {
			return fmt.Errorf("server saw %s with multipath %v, the client %v", f.Label, conn.Multipath, f.Multipath)
		}
		want := make([]netip.AddrPort, 0, len(f.Routes))
		for _, route := range f.Routes {
			want = append(want, backs[route])
		}
		if !f.Multipath {
			want = want[:1]
		}
		if !slices.Equal(conn.Remotes, want) {
			return fmt.Errorf("server saw %s from %v, not its routes' relay sockets %v", f.Label, conn.Remotes, want)
		}
	}
	for _, f := range client.Flows {
		if server.Flows[f.Label] != nil && !attributed[f.Label] {
			return fmt.Errorf("%s delivered useful bytes, but no server connection carried it", f.Label)
		}
	}
	for _, route := range rec.Routes {
		carried := route.Forward.Received != 0 || route.Reverse.Received != 0
		if !used[route.Name] && carried {
			return fmt.Errorf("route %s carried traffic that arm %s does not send there", route.Name, arm.Name)
		}
		if used[route.Name] && (route.Forward.Delivered == 0 || route.Reverse.Delivered == 0) {
			return fmt.Errorf("route %s delivered nothing in one direction although arm %s uses it", route.Name, arm.Name)
		}
	}
	return nil
}

// topologyCheckLost requires C1's packet-loss representation for controller: an observed
// count from the Reno/CUBIC sender, and an explicit unavailable metric for BBR, which
// has no producer.
func topologyCheckLost(m ordinaryCostMetric, controller string) error {
	want := ordinaryCostLostMetric(controller, 0)
	if m.Unit != want.Unit || m.Source != want.Source || m.Available != want.Available || m.Bytes != nil {
		return fmt.Errorf("packets-lost metric %+v is not %s's representation", m, controller)
	}
	if m.Available && m.Value == nil || !m.Available && (m.Value != nil || m.Reason == "") {
		return fmt.Errorf("packets-lost metric %+v needs a count when observed and a reason otherwise", m)
	}
	return nil
}

// topologyFailures are functional failures of a valid observation: a flow with no useful
// delivery, a close or stream error during the run, write authority that did not return,
// and a multipath arm whose connection did not negotiate or keep its two live paths in
// the arm's local use.
func topologyFailures(spec topologySpec, server *topologyServerResult, client *topologyClientResult) []string {
	arm, _ := topologyArmNamed(spec.Arm)
	failures := []string{}
	for _, f := range client.Flows {
		got := server.Flows[f.Label]
		switch {
		case got == nil || got.StreamBytes == 0:
			failures = append(failures, f.Label+": no useful STREAM delivery")
		case f.DatagramRate > 0 && got.DatagramsUseful == 0:
			failures = append(failures, f.Label+": no useful DATAGRAM delivery")
		}
		if f.CloseCause != "" {
			failures = append(failures, fmt.Sprintf("%s closed during the run: %s", f.Label, f.CloseCause))
		}
		if f.Label == topologyLabelName(topologyCompetitor) || !arm.Multipath {
			if f.Multipath {
				failures = append(failures, f.Label+": an ordinary connection negotiated multipath")
			}
			continue
		}
		if !f.Multipath {
			failures = append(failures, f.Label+": multipath was not negotiated")
			continue
		}
		var lifecycles, uses []string
		for _, p := range f.Paths {
			lifecycles = append(lifecycles, p.Lifecycle)
			uses = append(uses, p.LocalUse)
		}
		wantUse := []string{"active", "backup"}
		if arm.Policy == topologyPolicyAggregate {
			wantUse = []string{"active", "active"}
		}
		if !slices.Equal(lifecycles, []string{"live", "live"}) || !slices.Equal(uses, wantUse) {
			failures = append(failures, fmt.Sprintf("%s: paths %v in local use %v, not live %v", f.Label, lifecycles, uses, wantUse))
		}
	}
	for _, conn := range server.Connections {
		if conn.CloseCause != "" {
			failures = append(failures, fmt.Sprintf("server connection %v closed during the run: %s", conn.Labels, conn.CloseCause))
		}
	}
	if server.StreamErrors != 0 {
		failures = append(failures, fmt.Sprintf("server: %d stream errors", server.StreamErrors))
	}
	if server.Granted && !server.Joined {
		failures = append(failures, "server: write authority did not return")
	}
	if !client.Joined {
		failures = append(failures, "client: write authority did not return")
	}
	return failures
}

// TestTopologyComparisonRole runs the one role that TOPOLOGY_COMPARISON_SPEC names.
func TestTopologyComparisonRole(t *testing.T) {
	raw := os.Getenv("TOPOLOGY_COMPARISON_SPEC")
	if raw == "" {
		t.Skip("the topology comparison driver supplies the role specification")
	}
	var spec topologySpec
	require.NoError(t, topologyDecode(strings.NewReader(raw), &spec), "the driver supplies the spec")
	var result any
	switch spec.Role {
	case "relay-config":
		require.NoError(t, spec.validate(ordinaryCostHost))
		cfg, err := topologyRelayConfig(spec.Topology, spec.Server)
		require.NoError(t, err)
		result = cfg
	case "server":
		result = topologyRunServer(t, spec)
	case "client":
		result = topologyRunClient(t, spec)
	case "verify":
		observation, err := topologyVerify(spec, ordinaryCostHost)
		require.NoError(t, err)
		result = observation
	default:
		t.Fatalf("unknown role %q", spec.Role)
	}
	data, err := json.MarshalIndent(result, "", "  ")
	require.NoError(t, err)
	require.NoError(t, os.WriteFile(spec.Output, append(data, '\n'), 0o644))
}
