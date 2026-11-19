//go:build ordinarycost && ((linux && amd64) || (darwin && arm64))

package quic

import (
	"context"
	"crypto/tls"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"math/bits"
	"math/rand/v2"
	"net"
	"os"
	"runtime"
	"slices"
	"sync"
	"sync/atomic"
	"syscall"
	"testing"
	"time"

	"github.com/GridCastIO/quicquic-go/internal/testdata"

	"github.com/stretchr/testify/require"
)

// This is R18's paired workload: interop/multipath/ordinary_cost.py runs one role per
// process on its own cores, and judges the results. Both roles take one shared wall-clock
// timeline, so no start message crosses the path being measured. MP-MAC C1 (#1490) adds
// the native Darwin arm64 profile and matched Reno/BBR workloads; ordinary_cost_linux_test.go
// and ordinary_cost_darwin_test.go hold each platform's grant and RSS collector.
const (
	ordinaryCostALPN = "ordinary-cost"
	// ordinaryCostWriteBudget is the grant's native request duration, the default of a
	// socket the library owns.
	ordinaryCostWriteBudget = 100 * time.Millisecond

	ordinaryCostChunk       = 64 << 10
	ordinaryCostDatagram    = 1190
	ordinaryCostEcho        = 8
	ordinaryCostEchoPeriod  = 10 * time.Millisecond
	ordinaryCostFloodPacket = 100
	// The flood offers 10,000 unknown-CID packets each second, in 10 packet bursts.
	ordinaryCostFloodBurst  = 10
	ordinaryCostFloodPeriod = time.Millisecond
	// ordinaryCostBackgroundRate is the mixed cell's total background load in bytes each
	// second, one connection's in the opted-in profile and split evenly in the control.
	ordinaryCostBackgroundRate = 40 << 20

	ordinaryCostMemorySample = 20 * time.Second
	ordinaryCostDrain        = 2 * time.Second
	ordinaryCostStopTimeout  = 5 * time.Second
)

const (
	ordinaryCostStream byte = iota + 1
	ordinaryCostDatagrams
	ordinaryCostEchoes
)

const (
	ordinaryCostOrdinary   = "ordinary"
	ordinaryCostBackground = "background"
)

type ordinaryCostSpec struct {
	Controller string `json:"controller,omitempty"`
	Role       string `json:"role"`
	Cell       string `json:"cell"`
	Profile    string `json:"profile"`
	Seed       uint64 `json:"seed"`
	Address    string `json:"address"`
	Output     string `json:"output"`
	StartAt    int64  `json:"start_at_unix_ns"`
	WarmupNS   int64  `json:"warmup_ns"`
	WindowNS   int64  `json:"window_ns"`
}

func (s ordinaryCostSpec) granted() bool { return s.Profile == "opted-in" }

func (s ordinaryCostSpec) controller() string {
	if s.Controller == "" {
		return "reno"
	}
	return s.Controller
}

// ordinaryCostPlatformProfile is one platform's execution profile: its cell inventory and
// what its public admission and ordinary emission can do there.
type ordinaryCostPlatformProfile struct {
	name, goos, goarch string
	cells              []string
	// negotiatedMultipath reports public multipath admission, which the opted-in mixed-bulk
	// cell needs. No other cell stands in for it.
	negotiatedMultipath bool
	// gso reports segmentation offload in ordinary emission; Darwin emits scalar packets.
	gso bool
	// legacyRSSKB keeps the Linux rss_kb_* fields that the Reno thresholds read.
	legacyRSSKB bool
	grantSeam   string
}

var (
	ordinaryCostLinuxAMD64 = ordinaryCostPlatformProfile{
		name: "linux-amd64", goos: "linux", goarch: "amd64",
		cells:               []string{"stream-gso-on", "stream-gso-off", "datagram-batch-on", "datagram-batch-off", "mixed-bulk", "stateless-pressure"},
		negotiatedMultipath: true, gso: true, legacyRSSKB: true,
		grantSeam: "public Transport.ConfigureMultipathIOV1",
	}
	ordinaryCostDarwinARM64 = ordinaryCostPlatformProfile{
		name: "darwin-arm64", goos: "darwin", goarch: "arm64",
		cells:     []string{"stream", "datagram", "mixed-bulk", "stateless-pressure"},
		grantSeam: "private Transport.configureNativeIO, root tests only; never negotiates multipath",
	}
)

// ordinaryCostWorkload names the wiring a cell runs. Acceleration arms share a wiring.
func ordinaryCostWorkload(cell string) string {
	switch cell {
	case "stream-gso-on", "stream-gso-off", "stream":
		return "stream"
	case "datagram-batch-on", "datagram-batch-off", "datagram":
		return "datagram"
	case "mixed-bulk":
		return "mixed"
	case "stateless-pressure":
		return "pressure"
	}
	return ""
}

// validateFor admits Reno and BBR on every workload of the platform's inventory.
func (s ordinaryCostSpec) validateFor(platform ordinaryCostPlatformProfile) error {
	switch s.controller() {
	case "reno", "bbrv3":
	default:
		return errors.New("unknown ordinary-cost controller")
	}
	if !slices.Contains(platform.cells, s.Cell) {
		return fmt.Errorf("cell %q is not in the %s inventory", s.Cell, platform.name)
	}
	if s.Cell == "mixed-bulk" && s.granted() && !platform.negotiatedMultipath {
		return fmt.Errorf("opted-in mixed-bulk needs negotiated multipath, which %s does not admit publicly", platform.name)
	}
	return nil
}

// ordinaryCostIdentity names the platform profile a role ran under.
type ordinaryCostIdentity struct {
	Profile string `json:"profile"`
	GOOS    string `json:"goos"`
	GOARCH  string `json:"goarch"`
}

func (p ordinaryCostPlatformProfile) identity() ordinaryCostIdentity {
	return ordinaryCostIdentity{Profile: p.name, GOOS: runtime.GOOS, GOARCH: runtime.GOARCH}
}

// ordinaryCostMetric is one observed value with its unit and producer. An unavailable
// metric has no value: it is never a zero.
type ordinaryCostMetric struct {
	Value     *uint64 `json:"value"`
	Unit      string  `json:"unit"`
	Bytes     *uint64 `json:"bytes,omitempty"`
	Source    string  `json:"source"`
	Available bool    `json:"available"`
	Reason    string  `json:"reason,omitempty"`
}

func ordinaryCostObserved(value uint64, unit, source string) ordinaryCostMetric {
	return ordinaryCostMetric{Value: &value, Unit: unit, Source: source, Available: true}
}

func ordinaryCostUnavailable(unit, source, reason string) ordinaryCostMetric {
	return ordinaryCostMetric{Unit: unit, Source: source, Reason: reason}
}

const ordinaryCostCPUSource = "getrusage(RUSAGE_SELF) user+system time, window end minus start"

// ordinaryCostCPUMetric is the role process's own CPU over the measurement window.
func ordinaryCostCPUMetric(window ordinaryCostWindowRusage) ordinaryCostMetric {
	cpu := window.Delta.cpu()
	if cpu < 0 {
		return ordinaryCostUnavailable("ns", ordinaryCostCPUSource, "negative CPU interval")
	}
	return ordinaryCostObserved(uint64(cpu), "ns", ordinaryCostCPUSource)
}

// ordinaryCostRSSMetric keeps a peak-RSS reading in its producer's unit and adds bytes.
func ordinaryCostRSSMetric(raw uint64, unit, source string) (ordinaryCostMetric, error) {
	var scale uint64
	switch unit {
	case "kB":
		scale = 1024
	case "bytes":
		scale = 1
	default:
		return ordinaryCostMetric{}, fmt.Errorf("unknown RSS unit %q", unit)
	}
	high, normalized := bits.Mul64(raw, scale)
	if high != 0 {
		return ordinaryCostMetric{}, fmt.Errorf("RSS %d %s overflows bytes", raw, unit)
	}
	metric := ordinaryCostObserved(raw, unit, source)
	metric.Bytes = &normalized
	return metric, nil
}

// ordinaryCostLostMetric reports ConnectionStats().PacketsLost only where its producer is:
// the Reno/CUBIC sender increments it, and BBR never does.
func ordinaryCostLostMetric(controller string, lost uint64) ordinaryCostMetric {
	const source = "ConnectionStats().PacketsLost"
	if controller != "reno" {
		return ordinaryCostUnavailable("packets", source, "only the Reno/CUBIC sender counts lost packets; "+controller+" leaves the counter at zero")
	}
	return ordinaryCostObserved(lost, "packets", source)
}

func (s ordinaryCostSpec) timeline() ordinaryCostTimeline {
	start := time.Unix(0, s.StartAt)
	window := start.Add(time.Duration(s.WarmupNS))
	return ordinaryCostTimeline{start: start, window: window, end: window.Add(time.Duration(s.WindowNS))}
}

type ordinaryCostTimeline struct{ start, window, end time.Time }

func (l ordinaryCostTimeline) inWindow(t time.Time) bool {
	return !t.Before(l.window) && t.Before(l.end)
}

func (l ordinaryCostTimeline) seconds() int {
	return int(l.end.Sub(l.window) / time.Second)
}

// ordinaryCostHistogram is a log-linear latency histogram with 16 buckets per power of
// two, an upper-bound error of 6.25%. One goroutine owns it until its summary is read.
type ordinaryCostHistogram struct {
	counts [64 * 16]uint64
	total  uint64
	max    uint64
}

func ordinaryCostBucket(ns uint64) int {
	if ns < 16 {
		return int(ns)
	}
	exponent := bits.Len64(ns) - 5
	return exponent*16 + int(ns>>exponent)
}

// ordinaryCostBucketTop is the largest value bucket index holds.
func ordinaryCostBucketTop(index int) uint64 {
	if index < 16 {
		return uint64(index)
	}
	exponent := index/16 - 1
	mantissa := uint64(index%16 + 16)
	return (mantissa+1)<<exponent - 1
}

func (h *ordinaryCostHistogram) add(d time.Duration) {
	ns := uint64(max(d, 0))
	h.counts[ordinaryCostBucket(ns)]++
	h.total++
	h.max = max(h.max, ns)
}

func (h *ordinaryCostHistogram) merge(other *ordinaryCostHistogram) {
	for i, count := range other.counts {
		h.counts[i] += count
	}
	h.total += other.total
	h.max = max(h.max, other.max)
}

// quantile returns the upper bound of the bucket holding quantile q, in nanoseconds.
func (h *ordinaryCostHistogram) quantile(q float64) uint64 {
	if h.total == 0 {
		return 0
	}
	rank := uint64(math.Ceil(q * float64(h.total)))
	var seen uint64
	for i, count := range h.counts {
		seen += count
		if seen >= rank {
			return min(ordinaryCostBucketTop(i), h.max)
		}
	}
	return h.max
}

type ordinaryCostLatency struct {
	Count uint64  `json:"count"`
	P50US float64 `json:"p50_us"`
	P99US float64 `json:"p99_us"`
	MaxUS float64 `json:"max_us"`
}

func (h *ordinaryCostHistogram) summary() *ordinaryCostLatency {
	return &ordinaryCostLatency{
		Count: h.total,
		P50US: float64(h.quantile(0.50)) / 1e3,
		P99US: float64(h.quantile(0.99)) / 1e3,
		MaxUS: float64(h.max) / 1e3,
	}
}

// ordinaryCostSeries turns cumulative samples, one each second from the window's start,
// into the bytes of each second.
func ordinaryCostSeries(cumulative []uint64) []uint64 {
	series := make([]uint64, 0, max(len(cumulative)-1, 0))
	for i := 1; i < len(cumulative); i++ {
		series = append(series, cumulative[i]-cumulative[i-1])
	}
	return series
}

// ordinaryCostSample runs at each second of the window and returns when it ends. Each
// sample reads the counter at most a scheduling delay late, and a later sample recovers it.
func ordinaryCostSample(line ordinaryCostTimeline, read func() uint64) []uint64 {
	seconds := line.seconds()
	samples := make([]uint64, 0, seconds+1)
	for i := 0; i <= seconds; i++ {
		time.Sleep(time.Until(line.window.Add(time.Duration(i) * time.Second)))
		samples = append(samples, read())
	}
	return samples
}

func ordinaryCostTimeoutClose(err error) bool {
	var idle *IdleTimeoutError
	var handshake *HandshakeTimeoutError
	return errors.As(err, &idle) || errors.As(err, &handshake)
}

func ordinaryCostCloseCause(conn *Conn) (string, bool) {
	err := context.Cause(conn.Context())
	if err == nil {
		return "", false
	}
	return err.Error(), ordinaryCostTimeoutClose(err)
}

type ordinaryCostUsage struct {
	UserCPUNS                  int64 `json:"user_cpu_ns"`
	SystemCPUNS                int64 `json:"system_cpu_ns"`
	VoluntaryContextSwitches   int64 `json:"voluntary_context_switches"`
	InvoluntaryContextSwitches int64 `json:"involuntary_context_switches"`
}

func (usage ordinaryCostUsage) cpu() time.Duration {
	return time.Duration(usage.UserCPUNS + usage.SystemCPUNS)
}

func (usage ordinaryCostUsage) since(start ordinaryCostUsage) ordinaryCostUsage {
	return ordinaryCostUsage{
		UserCPUNS: usage.UserCPUNS - start.UserCPUNS, SystemCPUNS: usage.SystemCPUNS - start.SystemCPUNS,
		VoluntaryContextSwitches:   usage.VoluntaryContextSwitches - start.VoluntaryContextSwitches,
		InvoluntaryContextSwitches: usage.InvoluntaryContextSwitches - start.InvoluntaryContextSwitches,
	}
}

type ordinaryCostWindowRusage struct {
	Start ordinaryCostUsage `json:"start"`
	End   ordinaryCostUsage `json:"end"`
	Delta ordinaryCostUsage `json:"delta"`
}

func ordinaryCostRusage() ordinaryCostUsage {
	var usage syscall.Rusage
	if err := syscall.Getrusage(syscall.RUSAGE_SELF, &usage); err != nil {
		panic(err)
	}
	return ordinaryCostUsage{
		UserCPUNS: usage.Utime.Nano(), SystemCPUNS: usage.Stime.Nano(),
		VoluntaryContextSwitches: usage.Nvcsw, InvoluntaryContextSwitches: usage.Nivcsw,
	}
}

func ordinaryCostHeapInuse() uint64 {
	var stats runtime.MemStats
	runtime.ReadMemStats(&stats)
	return stats.HeapInuse
}

func ordinaryCostConfig(t testing.TB, multipath bool, controller string) *Config {
	t.Helper()
	conf := &Config{
		EnableDatagrams:                true,
		InitialStreamReceiveWindow:     4 << 20,
		MaxStreamReceiveWindow:         16 << 20,
		InitialConnectionReceiveWindow: 8 << 20,
		MaxConnectionReceiveWindow:     24 << 20,
		MaxIdleTimeout:                 30 * time.Second,
	}
	require.NoError(t, conf.SetCongestionControlV1(controller))
	if multipath {
		require.NoError(t, conf.ConfigureMultipathV1(true, 2, "primary-backup"))
	}
	return conf
}

func ordinaryCostServerTLS() *tls.Config {
	conf := testdata.GetTLSConfig()
	conf.NextProtos = []string{ordinaryCostALPN}
	return conf
}

func ordinaryCostClientTLS() *tls.Config {
	return &tls.Config{RootCAs: testdata.GetRootCA(), ServerName: "localhost", NextProtos: []string{ordinaryCostALPN}}
}

func ordinaryCostTransport(t testing.TB, address string, granted bool) *Transport {
	t.Helper()
	addr, err := net.ResolveUDPAddr("udp", address)
	require.NoError(t, err)
	socket, err := net.ListenUDP("udp", addr)
	require.NoError(t, err)
	t.Cleanup(func() { socket.Close() })
	tr := &Transport{Conn: socket, ConnectionIDLength: 4}
	if granted {
		require.NoError(t, ordinaryCostGrant(tr))
	}
	return tr
}

// ordinaryCostRequest is what a client asks of a server stream.
type ordinaryCostRequest struct {
	kind  byte
	label byte
	rate  uint64 // bytes each second; zero offers as much as the sender accepts
}

func (r ordinaryCostRequest) labelName() string {
	if r.label == 0 {
		return ordinaryCostOrdinary
	}
	return ordinaryCostBackground
}

func (r ordinaryCostRequest) encode() []byte {
	b := make([]byte, 10)
	b[0], b[1] = r.kind, r.label
	binary.BigEndian.PutUint64(b[2:], r.rate)
	return b
}

func ordinaryCostDecode(b []byte) ordinaryCostRequest {
	return ordinaryCostRequest{kind: b[0], label: b[1], rate: binary.BigEndian.Uint64(b[2:])}
}

// ordinaryCostPacer holds a sender to its rate; a zero rate never waits.
type ordinaryCostPacer struct {
	rate uint64
	next time.Time
}

func (p *ordinaryCostPacer) spent(bytes int) {
	if p.rate == 0 {
		return
	}
	now := time.Now()
	if p.next.IsZero() {
		p.next = now
	}
	p.next = p.next.Add(time.Duration(uint64(bytes) * uint64(time.Second) / p.rate))
	if wait := p.next.Sub(now); wait > 0 {
		time.Sleep(wait)
	}
}

type ordinaryCostServer struct {
	line ordinaryCostTimeline

	mutex       sync.Mutex
	histograms  map[string]*ordinaryCostHistogram
	writeErrors uint64
	conns       []*ordinaryCostServerConn
	workers     sync.WaitGroup
	gso         atomic.Bool
}

type ordinaryCostServerConn struct {
	conn  *Conn
	label atomic.Value
}

func (s *ordinaryCostServer) record(label string, h *ordinaryCostHistogram, writeErrors uint64) {
	s.mutex.Lock()
	defer s.mutex.Unlock()
	merged, ok := s.histograms[label]
	if !ok {
		merged = &ordinaryCostHistogram{}
		s.histograms[label] = merged
	}
	merged.merge(h)
	s.writeErrors += writeErrors
}

// finished reports that the timeline is over, which explains a later send error.
func (s *ordinaryCostServer) finished() bool { return !time.Now().Before(s.line.end) }

func (s *ordinaryCostServer) bulk(str *Stream, request ordinaryCostRequest) {
	histogram := &ordinaryCostHistogram{}
	var failures uint64
	payload := make([]byte, ordinaryCostChunk)
	pacer := ordinaryCostPacer{rate: request.rate}
	for !s.finished() {
		begun := time.Now()
		_, err := str.Write(payload)
		if s.line.inWindow(begun) {
			histogram.add(time.Since(begun))
		}
		if err != nil {
			if !s.finished() {
				failures++
			}
			break
		}
		pacer.spent(len(payload))
	}
	str.CancelWrite(0)
	s.record(request.labelName(), histogram, failures)
}

func (s *ordinaryCostServer) datagrams(conn *Conn, request ordinaryCostRequest) {
	histogram := &ordinaryCostHistogram{}
	var failures uint64
	payload := make([]byte, ordinaryCostDatagram)
	var sequence uint64
	pacer := ordinaryCostPacer{rate: request.rate}
	for !s.finished() {
		sequence++
		binary.BigEndian.PutUint64(payload, sequence)
		begun := time.Now()
		err := conn.SendDatagram(payload)
		if s.line.inWindow(begun) {
			histogram.add(time.Since(begun))
		}
		if err != nil {
			if !s.finished() {
				failures++
			}
			break
		}
		pacer.spent(len(payload))
	}
	s.record(request.labelName(), histogram, failures)
}

func (s *ordinaryCostServer) echoes(str *Stream) {
	message := make([]byte, ordinaryCostEcho)
	for {
		if _, err := io.ReadFull(str, message); err != nil {
			return
		}
		if _, err := str.Write(message); err != nil {
			return
		}
	}
}

func (s *ordinaryCostServer) handle(entry *ordinaryCostServerConn) {
	defer s.workers.Done()
	for {
		str, err := entry.conn.AcceptStream(context.Background())
		if err != nil {
			return
		}
		header := make([]byte, 10)
		if _, err := io.ReadFull(str, header); err != nil {
			return
		}
		request := ordinaryCostDecode(header)
		entry.label.Store(request.labelName())
		s.workers.Add(1)
		go func() {
			defer s.workers.Done()
			switch request.kind {
			case ordinaryCostStream:
				s.bulk(str, request)
			case ordinaryCostDatagrams:
				s.datagrams(entry.conn, request)
			case ordinaryCostEchoes:
				s.echoes(str)
			}
		}()
	}
}

type ordinaryCostServerConnResult struct {
	Label     string `json:"label"`
	Multipath bool   `json:"multipath_negotiated"`
	// Controller is the connection's own congestion controller.
	Controller  string `json:"controller"`
	PacketsSent uint64 `json:"packets_sent"`
	// PacketsLost is the legacy Reno field; Lost says whether the counter has a producer.
	PacketsLost  *uint64            `json:"packets_lost,omitempty"`
	Lost         ordinaryCostMetric `json:"packets_lost_metric"`
	BytesSent    uint64             `json:"bytes_sent"`
	CloseCause   string             `json:"close_cause"`
	TimeoutClose bool               `json:"timeout_close"`
}

type ordinaryCostServerResult struct {
	Controller          string                   `json:"controller"`
	Go                  string                   `json:"go"`
	Platform            ordinaryCostIdentity     `json:"platform"`
	Granted             bool                     `json:"granted"`
	GrantSeam           string                   `json:"grant_seam,omitempty"`
	MultipathAdvertised bool                     `json:"multipath_advertised"`
	GSOCapable          bool                     `json:"gso_capable"`
	WindowCPU           float64                  `json:"window_cpu_s"`
	WindowRusage        ordinaryCostWindowRusage `json:"window_rusage"`
	SelfCPU             ordinaryCostMetric       `json:"self_cpu"`
	PeakRSSAtSample     ordinaryCostMetric       `json:"peak_rss_at_sample"`
	PeakRSSEnd          ordinaryCostMetric       `json:"peak_rss_end"`
	// The Linux VmHWM readings in kB that the Reno memory threshold reads.
	RSSAt20S                    *uint64                         `json:"rss_kb_at_20s,omitempty"`
	RSSEnd                      *uint64                         `json:"rss_kb_end,omitempty"`
	HeapInuseEnd                uint64                          `json:"heap_inuse_end"`
	WriteErrors                 uint64                          `json:"write_errors"`
	Joined                      bool                            `json:"joined"`
	ApplicationSendCall         map[string]*ordinaryCostLatency `json:"application_send_call"`
	ApplicationSendCallBoundary string                          `json:"application_send_call_boundary"`
	Connections                 []ordinaryCostServerConnResult  `json:"connections"`
}

func ordinaryCostRunServer(t testing.TB, spec ordinaryCostSpec) *ordinaryCostServerResult {
	t.Helper()
	require.NoError(t, spec.validateFor(ordinaryCostHost))
	line := spec.timeline()
	var key StatelessResetKey
	binary.BigEndian.PutUint64(key[:], spec.Seed)
	tr := ordinaryCostTransport(t, spec.Address, spec.granted())
	tr.StatelessResetKey = &key
	// Both controllers advertise where public admission exists, so their workloads match.
	advertised := spec.granted() && ordinaryCostHost.negotiatedMultipath
	listener, err := tr.Listen(ordinaryCostServerTLS(), ordinaryCostConfig(t, advertised, spec.controller()))
	require.NoError(t, err)
	s := &ordinaryCostServer{line: line, histograms: map[string]*ordinaryCostHistogram{}}
	s.workers.Add(1)
	go func() {
		defer s.workers.Done()
		for {
			conn, err := listener.Accept(context.Background())
			if err != nil {
				return
			}
			entry := &ordinaryCostServerConn{conn: conn}
			s.gso.Store(conn.ConnectionState().GSO)
			s.mutex.Lock()
			s.conns = append(s.conns, entry)
			s.mutex.Unlock()
			s.workers.Add(1)
			go s.handle(entry)
		}
	}()

	result := &ordinaryCostServerResult{
		Go: runtime.Version(), Controller: spec.controller(), Platform: ordinaryCostHost.identity(),
		Granted: tr.responses != nil, MultipathAdvertised: advertised, ApplicationSendCall: map[string]*ordinaryCostLatency{},
		ApplicationSendCallBoundary: "elapsed Stream.Write / SendDatagram call time; neither native return nor peer delivery",
	}
	if result.Granted {
		result.GrantSeam = ordinaryCostHost.grantSeam
	}
	time.Sleep(time.Until(line.window))
	usageStart := ordinaryCostRusage()
	sampleAt := min(ordinaryCostMemorySample, line.end.Sub(line.window)/3)
	time.Sleep(time.Until(line.window.Add(sampleAt)))
	result.PeakRSSAtSample, err = ordinaryCostPeakRSS()
	require.NoError(t, err)
	time.Sleep(time.Until(line.end))
	usageEnd := ordinaryCostRusage()
	result.WindowCPU = (usageEnd.cpu() - usageStart.cpu()).Seconds()
	result.WindowRusage = ordinaryCostWindowRusage{Start: usageStart, End: usageEnd, Delta: usageEnd.since(usageStart)}
	result.SelfCPU = ordinaryCostCPUMetric(result.WindowRusage)
	result.PeakRSSEnd, err = ordinaryCostPeakRSS()
	require.NoError(t, err)
	if ordinaryCostHost.legacyRSSKB {
		result.RSSAt20S, result.RSSEnd = result.PeakRSSAtSample.Value, result.PeakRSSEnd.Value
	}
	result.HeapInuseEnd = ordinaryCostHeapInuse()

	// The client holds its connections past the end, so any close seen here is the run's.
	s.mutex.Lock()
	for _, entry := range s.conns {
		require.Equal(t, spec.controller(), entry.conn.CongestionControlV1())
		stats := entry.conn.ConnectionStats()
		cause, timedOut := ordinaryCostCloseCause(entry.conn)
		label, _ := entry.label.Load().(string)
		negotiated, err := entry.conn.MultipathNegotiatedV1()
		require.NoError(t, err)
		lost := ordinaryCostLostMetric(entry.conn.CongestionControlV1(), stats.PacketsLost)
		result.Connections = append(result.Connections, ordinaryCostServerConnResult{
			Label: label, Multipath: negotiated, Controller: entry.conn.CongestionControlV1(),
			PacketsSent: stats.PacketsSent, PacketsLost: lost.Value, Lost: lost, BytesSent: stats.BytesSent,
			CloseCause: cause, TimeoutClose: timedOut,
		})
	}
	conns := len(s.conns)
	s.mutex.Unlock()
	require.NotZero(t, conns, "no connection reached the server")
	result.GSOCapable = s.gso.Load()

	time.Sleep(ordinaryCostDrain)
	require.NoError(t, listener.Close())
	require.NoError(t, tr.Close())
	if spec.granted() {
		ctx, cancel := context.WithTimeout(context.Background(), ordinaryCostStopTimeout)
		defer cancel()
		result.Joined = tr.WaitMultipathIOStoppedV1(ctx) == nil
	}
	s.workers.Wait()
	s.mutex.Lock()
	defer s.mutex.Unlock()
	result.WriteErrors = s.writeErrors
	for label, histogram := range s.histograms {
		result.ApplicationSendCall[label] = histogram.summary()
	}
	return result
}

type ordinaryCostFlowResult struct {
	Label        string               `json:"label"`
	Series       []uint64             `json:"series"`
	UsefulBytes  uint64               `json:"useful_bytes"`
	Control      *ordinaryCostLatency `json:"control"`
	Drops        uint64               `json:"datagram_drops"`
	Unprocessed  uint64               `json:"unprocessed_drops"`
	CloseCause   string               `json:"close_cause"`
	TimeoutClose bool                 `json:"timeout_close"`
	Negotiated   bool                 `json:"multipath_negotiated"`
	Paths        []string             `json:"paths"`
}

type ordinaryCostFloodResult struct {
	Sent   uint64 `json:"sent"`
	Resets uint64 `json:"resets"`
}

type ordinaryCostClientResult struct {
	Controller   string                    `json:"controller"`
	Go           string                    `json:"go"`
	Platform     ordinaryCostIdentity      `json:"platform"`
	WindowCPU    float64                   `json:"window_cpu_s"`
	WindowRusage ordinaryCostWindowRusage  `json:"window_rusage"`
	SelfCPU      ordinaryCostMetric        `json:"self_cpu"`
	UsefulBytes  ordinaryCostMetric        `json:"useful_bytes"`
	Flows        []*ordinaryCostFlowResult `json:"flows"`
	Flood        *ordinaryCostFloodResult  `json:"flood,omitempty"`
}

// ordinaryCostFlow is one client connection's receiving side.
type ordinaryCostFlow struct {
	label  string
	conn   *Conn
	useful atomic.Uint64
	echo   ordinaryCostHistogram
	result *ordinaryCostFlowResult
}

func (f *ordinaryCostFlow) request(t testing.TB, r ordinaryCostRequest) *Stream {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	str, err := f.conn.OpenStreamSync(ctx)
	require.NoError(t, err)
	_, err = str.Write(r.encode())
	require.NoError(t, err)
	return str
}

func (f *ordinaryCostFlow) readBulk(str *Stream) {
	buffer := make([]byte, ordinaryCostChunk)
	for {
		n, err := str.Read(buffer)
		f.useful.Add(uint64(n))
		if err != nil {
			return
		}
	}
}

func (f *ordinaryCostFlow) readDatagrams() {
	for {
		payload, err := f.conn.ReceiveDatagram(context.Background())
		if err != nil {
			return
		}
		f.useful.Add(uint64(len(payload)))
	}
}

// runEcho is a closed loop: the next message waits for the last reply and the next period.
func (f *ordinaryCostFlow) runEcho(line ordinaryCostTimeline, str *Stream) {
	message := make([]byte, ordinaryCostEcho)
	ticker := time.NewTicker(ordinaryCostEchoPeriod)
	defer ticker.Stop()
	for now := time.Now(); now.Before(line.end); now = <-ticker.C {
		begun := time.Now()
		if _, err := str.Write(message); err != nil {
			return
		}
		if _, err := io.ReadFull(str, message); err != nil {
			return
		}
		if line.inWindow(begun) {
			f.echo.add(time.Since(begun))
		}
	}
}

func ordinaryCostDial(t testing.TB, tr *Transport, address *net.UDPAddr, multipath bool, controller string) *Conn {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
	defer cancel()
	conn, err := tr.Dial(ctx, address, ordinaryCostClientTLS(), ordinaryCostConfig(t, multipath, controller))
	require.NoError(t, err)
	require.Equal(t, controller, conn.CongestionControlV1())
	return conn
}

// ordinaryCostFlood sends unknown-CID packets to the server's socket and counts the
// stateless resets that come back, from the shared timeline's start until its end.
func ordinaryCostFlood(t testing.TB, line ordinaryCostTimeline, address *net.UDPAddr, seed uint64) (*ordinaryCostFloodResult, func()) {
	t.Helper()
	socket, err := net.ListenUDP("udp", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	require.NoError(t, err)
	t.Cleanup(func() { socket.Close() })
	result := &ordinaryCostFloodResult{}
	var sent, resets atomic.Uint64
	var wait sync.WaitGroup
	wait.Add(2)
	go func() {
		defer wait.Done()
		buffer := make([]byte, 2048)
		for {
			if _, _, err := socket.ReadFromUDP(buffer); err != nil {
				return
			}
			if line.inWindow(time.Now()) {
				resets.Add(1)
			}
		}
	}()
	go func() {
		defer wait.Done()
		random := rand.New(rand.NewPCG(seed, seed))
		packet := make([]byte, ordinaryCostFloodPacket)
		time.Sleep(time.Until(line.start))
		ticker := time.NewTicker(ordinaryCostFloodPeriod)
		defer ticker.Stop()
		for now := range ticker.C {
			if !now.Before(line.end) {
				return
			}
			for range ordinaryCostFloodBurst {
				for i := 0; i+8 <= len(packet); i += 8 {
					binary.BigEndian.PutUint64(packet[i:], random.Uint64())
				}
				packet[0] = 0x40 | packet[0]&0x3f
				if _, err := socket.WriteToUDP(packet, address); err != nil {
					continue
				}
				if line.inWindow(now) {
					sent.Add(1)
				}
			}
		}
	}()
	return result, func() {
		time.Sleep(time.Until(line.end.Add(ordinaryCostDrain / 2)))
		socket.Close()
		wait.Wait()
		result.Sent, result.Resets = sent.Load(), resets.Load()
	}
}

func ordinaryCostRunClient(t testing.TB, spec ordinaryCostSpec) *ordinaryCostClientResult {
	t.Helper()
	require.NoError(t, spec.validateFor(ordinaryCostHost))
	line := spec.timeline()
	address, err := net.ResolveUDPAddr("udp", spec.Address)
	require.NoError(t, err)
	var transports []*Transport
	dial := func(multipath, granted bool) (*Transport, *Conn) {
		tr := ordinaryCostTransport(t, "127.0.0.1:0", granted)
		transports = append(transports, tr)
		return tr, ordinaryCostDial(t, tr, address, multipath, spec.controller())
	}

	_, ordinaryConn := dial(false, false)
	ordinary := &ordinaryCostFlow{label: ordinaryCostOrdinary, conn: ordinaryConn}
	flows := []*ordinaryCostFlow{ordinary}
	type bulkFlow struct {
		flow *ordinaryCostFlow
		rate uint64
	}
	var bulks []bulkFlow
	var multipathConn *Conn
	var paths []*Path
	switch ordinaryCostWorkload(spec.Cell) {
	case "stream", "pressure":
		bulks = append(bulks, bulkFlow{ordinary, 0})
	case "datagram":
	case "mixed":
		bulks = append(bulks, bulkFlow{ordinary, 0})
		if spec.granted() {
			_, conn := dial(true, true)
			second := ordinaryCostTransport(t, "127.0.0.1:0", true)
			transports = append(transports, second)
			ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
			defer cancel()
			_, err := conn.OpenPathV1(ctx, second, address)
			require.NoError(t, err)
			paths = conn.PathsV1()
			multipathConn = conn
			flow := &ordinaryCostFlow{label: ordinaryCostBackground, conn: conn}
			flows = append(flows, flow)
			bulks = append(bulks, bulkFlow{flow, ordinaryCostBackgroundRate})
		} else {
			// Two independent ordinary connections stand in for the multipath one, on the
			// same socket count, with the same total load.
			for range 2 {
				_, conn := dial(false, false)
				flow := &ordinaryCostFlow{label: ordinaryCostBackground, conn: conn}
				flows = append(flows, flow)
				bulks = append(bulks, bulkFlow{flow, ordinaryCostBackgroundRate / 2})
			}
		}
	default:
		t.Fatalf("unknown cell %q", spec.Cell)
	}
	require.False(t, time.Now().After(line.start), "setup outlasted its budget")
	time.Sleep(time.Until(line.start))

	var wait sync.WaitGroup
	for _, bulk := range bulks {
		label := byte(0)
		if bulk.flow.label == ordinaryCostBackground {
			label = 1
		}
		str := bulk.flow.request(t, ordinaryCostRequest{kind: ordinaryCostStream, label: label, rate: bulk.rate})
		wait.Add(1)
		go func(flow *ordinaryCostFlow) {
			defer wait.Done()
			flow.readBulk(str)
		}(bulk.flow)
	}
	if len(bulks) == 0 {
		ordinary.request(t, ordinaryCostRequest{kind: ordinaryCostDatagrams})
		wait.Add(1)
		go func() {
			defer wait.Done()
			ordinary.readDatagrams()
		}()
	}
	echo := ordinary.request(t, ordinaryCostRequest{kind: ordinaryCostEchoes})
	wait.Add(1)
	go func() {
		defer wait.Done()
		ordinary.runEcho(line, echo)
	}()
	var flood *ordinaryCostFloodResult
	finishFlood := func() {}
	if spec.Cell == "stateless-pressure" {
		flood, finishFlood = ordinaryCostFlood(t, line, address, spec.Seed)
	}

	samples := make([][]uint64, len(flows))
	var sampling sync.WaitGroup
	for i, flow := range flows {
		sampling.Add(1)
		go func() {
			defer sampling.Done()
			samples[i] = ordinaryCostSample(line, flow.useful.Load)
		}()
	}
	time.Sleep(time.Until(line.window))
	usageStart := ordinaryCostRusage()
	sampling.Wait()
	goVersion := runtime.Version()
	usageEnd := ordinaryCostRusage()
	result := &ordinaryCostClientResult{
		Go: goVersion, Controller: spec.controller(), Platform: ordinaryCostHost.identity(),
		WindowCPU:    (usageEnd.cpu() - usageStart.cpu()).Seconds(),
		WindowRusage: ordinaryCostWindowRusage{Start: usageStart, End: usageEnd, Delta: usageEnd.since(usageStart)},
	}
	result.SelfCPU = ordinaryCostCPUMetric(result.WindowRusage)
	var delivered uint64

	// Stay connected through the server's end-of-run reading, then close.
	for i, flow := range flows {
		series := ordinaryCostSeries(samples[i])
		var useful uint64
		for _, bytes := range series {
			useful += bytes
		}
		cause, timedOut := ordinaryCostCloseCause(flow.conn)
		flow.result = &ordinaryCostFlowResult{
			Label: flow.label, Series: series, UsefulBytes: useful,
			Drops: flow.conn.DatagramReceiveDropsV1(), Unprocessed: flow.conn.UnprocessedPacketDropsV1(),
			CloseCause: cause, TimeoutClose: timedOut,
		}
		result.Flows = append(result.Flows, flow.result)
		delivered += useful
		if flow.conn == multipathConn {
			flow.result.Negotiated, err = flow.conn.MultipathNegotiatedV1()
			require.NoError(t, err)
			for _, path := range paths {
				state, err := path.StateV1()
				require.NoError(t, err)
				flow.result.Paths = append(flow.result.Paths, state.Lifecycle)
			}
		}
	}
	result.UsefulBytes = ordinaryCostObserved(delivered, "bytes", "receiver-counted application bytes in the window, every flow")
	time.Sleep(ordinaryCostDrain)
	for _, flow := range flows {
		require.NoError(t, flow.conn.CloseWithError(0, ""))
	}
	wait.Wait()
	ordinary.result.Control = ordinary.echo.summary()
	finishFlood()
	result.Flood = flood
	for _, tr := range transports {
		require.NoError(t, tr.Close())
	}
	return result
}

// TestOrdinaryCostRole runs the one role that ORDINARY_COST_SPEC names.
func TestOrdinaryCostRole(t *testing.T) {
	if os.Getenv("ORDINARY_COST_SPEC") == "" {
		t.Skip("ordinary-cost driver supplies the role specification")
	}
	var spec ordinaryCostSpec
	require.NoError(t, json.Unmarshal([]byte(os.Getenv("ORDINARY_COST_SPEC")), &spec), "the driver supplies the spec")
	var result any
	switch spec.Role {
	case "server":
		result = ordinaryCostRunServer(t, spec)
	case "client":
		result = ordinaryCostRunClient(t, spec)
	default:
		t.Fatalf("unknown role %q", spec.Role)
	}
	data, err := json.MarshalIndent(result, "", "  ")
	require.NoError(t, err)
	require.NoError(t, os.WriteFile(spec.Output, data, 0o644))
}

// TestOrdinaryCostAdmission checks both platform inventories on any host: Reno and BBR
// run the same workloads, and only a platform with public admission negotiates mixed bulk.
func TestOrdinaryCostAdmission(t *testing.T) {
	for _, platform := range []ordinaryCostPlatformProfile{ordinaryCostLinuxAMD64, ordinaryCostDarwinARM64} {
		for _, controller := range []string{"", "reno", "bbrv3"} {
			for _, cell := range platform.cells {
				for _, profile := range []string{"unregistered", "opted-in"} {
					spec := ordinaryCostSpec{Controller: controller, Cell: cell, Profile: profile}
					err := spec.validateFor(platform)
					if cell == "mixed-bulk" && profile == "opted-in" && !platform.negotiatedMultipath {
						require.ErrorContains(t, err, "negotiated multipath", "%s %s", platform.name, cell)
						continue
					}
					require.NoError(t, err, "%s %s %s %s", platform.name, controller, cell, profile)
				}
			}
		}
		require.ErrorContains(t, (ordinaryCostSpec{Controller: "unknown", Cell: "stateless-pressure"}).validateFor(platform), "controller")
		require.ErrorContains(t, (ordinaryCostSpec{Cell: "no-such-cell"}).validateFor(platform), "inventory")
	}
	// Each inventory names its own wirings; neither borrows the other's acceleration arms.
	require.ErrorContains(t, (ordinaryCostSpec{Cell: "stream-gso-on"}).validateFor(ordinaryCostDarwinARM64), "inventory")
	require.ErrorContains(t, (ordinaryCostSpec{Cell: "stream"}).validateFor(ordinaryCostLinuxAMD64), "inventory")
	require.NoError(t, (ordinaryCostSpec{Cell: "mixed-bulk", Profile: "opted-in"}).validateFor(ordinaryCostLinuxAMD64))
	for cell, workload := range map[string]string{
		"stream-gso-on": "stream", "stream-gso-off": "stream", "stream": "stream",
		"datagram-batch-on": "datagram", "datagram-batch-off": "datagram", "datagram": "datagram",
		"mixed-bulk": "mixed", "stateless-pressure": "pressure",
	} {
		require.Equal(t, workload, ordinaryCostWorkload(cell), cell)
	}
	for _, controller := range []string{"", "reno", "bbrv3"} {
		spec := ordinaryCostSpec{Controller: controller}
		require.Equal(t, spec.controller(), ordinaryCostConfig(t, false, spec.controller()).CongestionControlV1())
	}
}

func TestOrdinaryCostMetrics(t *testing.T) {
	window := ordinaryCostWindowRusage{
		Start: ordinaryCostUsage{UserCPUNS: 2e9, SystemCPUNS: 3e9},
		End:   ordinaryCostUsage{UserCPUNS: 5e9, SystemCPUNS: 7e9},
	}
	window.Delta = window.End.since(window.Start)
	cpu := ordinaryCostCPUMetric(window)
	require.True(t, cpu.Available)
	require.Equal(t, uint64(7e9), *cpu.Value, "user and system time over the window")
	require.Equal(t, "ns", cpu.Unit)
	require.NotEmpty(t, cpu.Source)
	backwards := ordinaryCostWindowRusage{Start: window.End, End: window.Start}
	backwards.Delta = backwards.End.since(backwards.Start)
	cpu = ordinaryCostCPUMetric(backwards)
	require.False(t, cpu.Available, "a negative interval is no CPU reading")
	require.Nil(t, cpu.Value)
	require.NotEmpty(t, cpu.Reason)

	kb, err := ordinaryCostRSSMetric(1500, "kB", "VmHWM")
	require.NoError(t, err)
	require.Equal(t, uint64(1500), *kb.Value, "the raw reading is kept")
	require.Equal(t, uint64(1_536_000), *kb.Bytes)
	require.Equal(t, "kB", kb.Unit)
	bytes, err := ordinaryCostRSSMetric(1_536_000, "bytes", "ru_maxrss")
	require.NoError(t, err)
	require.Equal(t, uint64(1_536_000), *bytes.Value)
	require.Equal(t, uint64(1_536_000), *bytes.Bytes)
	_, err = ordinaryCostRSSMetric(1, "pages", "unknown")
	require.Error(t, err)
	_, err = ordinaryCostRSSMetric(math.MaxUint64/1000, "kB", "VmHWM")
	require.Error(t, err, "a reading too large to normalize is refused, not wrapped")

	zero := ordinaryCostLostMetric("reno", 0)
	require.True(t, zero.Available, "Reno's zero is a counted zero")
	require.Equal(t, uint64(0), *zero.Value)
	for _, lost := range []uint64{0, 9} {
		bbr := ordinaryCostLostMetric("bbrv3", lost)
		require.False(t, bbr.Available, "BBR never increments the counter")
		require.Nil(t, bbr.Value)
		require.NotEmpty(t, bbr.Reason)
	}
	encoded, err := json.Marshal(ordinaryCostLostMetric("bbrv3", 0))
	require.NoError(t, err)
	require.Contains(t, string(encoded), `"value":null`, "unavailable is not zero")
}

func TestOrdinaryCostHistogram(t *testing.T) {
	var empty ordinaryCostHistogram
	require.Zero(t, empty.quantile(0.99))

	for _, ns := range []uint64{0, 1, 15, 16, 17, 31, 32, 33, 1000, 123456789, 1 << 40} {
		top := ordinaryCostBucketTop(ordinaryCostBucket(ns))
		require.GreaterOrEqual(t, top, ns, "the bucket of %d holds it", ns)
		require.LessOrEqual(t, float64(top), float64(ns)*1.0625+1, "the bucket of %d stays within 6.25%%", ns)
	}
	require.Less(t, ordinaryCostBucket(math.MaxInt64), 64*16)

	var h ordinaryCostHistogram
	for i := 1; i <= 1000; i++ {
		h.add(time.Duration(i) * time.Microsecond)
	}
	p99 := h.quantile(0.99)
	require.GreaterOrEqual(t, p99, uint64(990_000))
	require.LessOrEqual(t, p99, uint64(1_000_000), "a quantile never reads past the maximum")
	summary := h.summary()
	require.Equal(t, uint64(1000), summary.Count)
	require.Equal(t, 1000.0, summary.MaxUS)

	var merged ordinaryCostHistogram
	merged.merge(&h)
	merged.merge(&h)
	require.Equal(t, uint64(2000), merged.total)
	require.Equal(t, p99, merged.quantile(0.99))
	h.add(-time.Second)
	require.Equal(t, uint64(1), h.counts[0], "a negative duration reads as zero")
}

func TestOrdinaryCostAccounting(t *testing.T) {
	require.Empty(t, ordinaryCostSeries(nil))
	require.Equal(t, []uint64{5, 0, 7}, ordinaryCostSeries([]uint64{10, 15, 15, 22}))
	usageStart := ordinaryCostUsage{UserCPUNS: 2e9, SystemCPUNS: 3e9, VoluntaryContextSwitches: 11, InvoluntaryContextSwitches: 7}
	usageEnd := ordinaryCostUsage{UserCPUNS: 5e9, SystemCPUNS: 7e9, VoluntaryContextSwitches: 17, InvoluntaryContextSwitches: 7}
	window := ordinaryCostWindowRusage{Start: usageStart, End: usageEnd, Delta: usageEnd.since(usageStart)}
	require.Equal(t, ordinaryCostUsage{UserCPUNS: 3e9, SystemCPUNS: 4e9, VoluntaryContextSwitches: 6}, window.Delta)
	require.Equal(t, 7*time.Second, usageEnd.cpu()-usageStart.cpu())
	for _, result := range []any{ordinaryCostServerResult{WindowRusage: window}, ordinaryCostClientResult{WindowRusage: window}} {
		encoded, err := json.Marshal(result)
		require.NoError(t, err)
		var fields map[string]json.RawMessage
		require.NoError(t, json.Unmarshal(encoded, &fields))
		require.JSONEq(t, `{
			"start":{"user_cpu_ns":2000000000,"system_cpu_ns":3000000000,"voluntary_context_switches":11,"involuntary_context_switches":7},
			"end":{"user_cpu_ns":5000000000,"system_cpu_ns":7000000000,"voluntary_context_switches":17,"involuntary_context_switches":7},
			"delta":{"user_cpu_ns":3000000000,"system_cpu_ns":4000000000,"voluntary_context_switches":6,"involuntary_context_switches":0}
		}`, string(fields["window_rusage"]))
	}

	request := ordinaryCostRequest{kind: ordinaryCostStream, label: 1, rate: 1 << 40}
	decoded := ordinaryCostDecode(request.encode())
	require.Equal(t, request, decoded)
	require.Equal(t, ordinaryCostBackground, decoded.labelName())
	require.Equal(t, ordinaryCostOrdinary, ordinaryCostRequest{}.labelName())

	start := time.Now()
	line := ordinaryCostTimeline{start: start, window: start.Add(time.Second), end: start.Add(3 * time.Second)}
	require.False(t, line.inWindow(start))
	require.True(t, line.inWindow(line.window))
	require.False(t, line.inWindow(line.end), "the end belongs to the next phase")
	require.Equal(t, 2, line.seconds())

	unpaced := ordinaryCostPacer{}
	begun := time.Now()
	unpaced.spent(1 << 30)
	require.Less(t, time.Since(begun), time.Second)
	paced := ordinaryCostPacer{rate: 1 << 20}
	begun = time.Now()
	paced.spent(1 << 17)
	require.GreaterOrEqual(t, time.Since(begun), 100*time.Millisecond, "an eighth of a second's bytes")

	require.True(t, ordinaryCostTimeoutClose(&IdleTimeoutError{}))
	require.True(t, ordinaryCostTimeoutClose(&HandshakeTimeoutError{}))
	require.False(t, ordinaryCostTimeoutClose(&ApplicationError{}))
	require.False(t, ordinaryCostTimeoutClose(nil))
}

// TestOrdinaryCostCells runs both roles of every workload wiring in one process for a
// moment, for Reno and BBR on this host's inventory. It checks the wiring and the metric
// records, and its numbers mean nothing: only the driver's separate processes measure.
// BBR skips the acceleration-off arms, which repeat a wiring it already runs.
func TestOrdinaryCostCells(t *testing.T) {
	for _, controller := range []string{"reno", "bbrv3"} {
		for _, profile := range []string{"unregistered", "opted-in"} {
			for _, cell := range ordinaryCostHost.cells {
				off := cell == "stream-gso-off" || cell == "datagram-batch-off"
				name := controller + "/" + profile + "/" + cell
				spec := ordinaryCostSpec{Controller: controller, Cell: cell, Profile: profile, Seed: 1}
				if err := spec.validateFor(ordinaryCostHost); err != nil {
					// Only a refused negotiated workload is absent, never replaced.
					require.True(t, cell == "mixed-bulk" && profile == "opted-in" && !ordinaryCostHost.negotiatedMultipath, name)
					continue
				}
				if controller == "bbrv3" && off {
					continue
				}
				t.Run(name, func(t *testing.T) { ordinaryCostSmoke(t, spec, off) })
			}
		}
	}
}

func ordinaryCostSmoke(t *testing.T, spec ordinaryCostSpec, off bool) {
	if off {
		t.Setenv("QUIC_GO_DISABLE_GSO", "true")
	}
	probe := newUDPConnLocalhost(t)
	spec.Address = probe.LocalAddr().String()
	require.NoError(t, probe.Close())
	spec.StartAt = time.Now().Add(time.Second).UnixNano()
	spec.WarmupNS, spec.WindowNS = int64(200*time.Millisecond), int64(time.Second)
	cell, profile, controller := spec.Cell, spec.Profile, spec.controller()
	servers := make(chan *ordinaryCostServerResult, 1)
	go func() {
		defer close(servers)
		servers <- ordinaryCostRunServer(t, spec)
	}()
	client := ordinaryCostRunClient(t, spec)
	server := <-servers
	require.NotNil(t, server)
	for _, result := range []struct {
		cpu      float64
		usage    ordinaryCostWindowRusage
		self     ordinaryCostMetric
		platform ordinaryCostIdentity
	}{{server.WindowCPU, server.WindowRusage, server.SelfCPU, server.Platform}, {client.WindowCPU, client.WindowRusage, client.SelfCPU, client.Platform}} {
		for _, usage := range []ordinaryCostUsage{result.usage.Start, result.usage.End, result.usage.Delta} {
			require.GreaterOrEqual(t, usage.UserCPUNS, int64(0))
			require.GreaterOrEqual(t, usage.SystemCPUNS, int64(0))
			require.GreaterOrEqual(t, usage.VoluntaryContextSwitches, int64(0))
			require.GreaterOrEqual(t, usage.InvoluntaryContextSwitches, int64(0))
		}
		require.Equal(t, result.usage.End.since(result.usage.Start), result.usage.Delta)
		require.Equal(t, result.cpu, result.usage.Delta.cpu().Seconds())
		require.True(t, result.self.Available)
		require.Equal(t, uint64(result.usage.Delta.cpu()), *result.self.Value)
		require.Equal(t, ordinaryCostIdentity{Profile: ordinaryCostHost.name, GOOS: ordinaryCostHost.goos, GOARCH: ordinaryCostHost.goarch}, result.platform)
	}
	require.Equal(t, controller, server.Controller)
	require.Equal(t, controller, client.Controller)

	granted := profile == "opted-in"
	require.Equal(t, granted, server.Granted)
	require.Equal(t, granted, server.Joined)
	require.Equal(t, granted && ordinaryCostHost.negotiatedMultipath, server.MultipathAdvertised)
	if granted {
		require.Equal(t, ordinaryCostHost.grantSeam, server.GrantSeam)
	}
	require.Equal(t, !off && ordinaryCostHost.gso, server.GSOCapable)
	require.Zero(t, server.WriteErrors)
	require.NotZero(t, server.ApplicationSendCall[ordinaryCostOrdinary].Count)
	require.NotZero(t, server.WindowCPU)
	for _, peak := range []ordinaryCostMetric{server.PeakRSSAtSample, server.PeakRSSEnd} {
		require.True(t, peak.Available)
		require.NotZero(t, *peak.Bytes)
	}
	// No ordering between the two reads is asserted: Linux updates VmHWM lazily from
	// approximate counters, so a later read can be lower.
	if ordinaryCostHost.legacyRSSKB {
		require.Equal(t, "kB", server.PeakRSSEnd.Unit)
		require.Equal(t, server.PeakRSSEnd.Value, server.RSSEnd)
		require.NotZero(t, *server.RSSEnd)
	} else {
		require.Equal(t, "bytes", server.PeakRSSEnd.Unit)
		require.Nil(t, server.RSSEnd, "no Linux counter is fabricated")
	}

	background := 0
	var delivered uint64
	for _, flow := range client.Flows {
		require.Len(t, flow.Series, 1)
		require.NotZero(t, flow.UsefulBytes, flow.Label)
		require.Empty(t, flow.CloseCause)
		delivered += flow.UsefulBytes
		if flow.Label == ordinaryCostOrdinary {
			require.NotZero(t, flow.Control.Count)
			continue
		}
		background++
		if granted {
			require.True(t, flow.Negotiated)
			require.Equal(t, []string{"live", "live"}, flow.Paths)
		}
	}
	require.Equal(t, delivered, *client.UsefulBytes.Value)
	switch {
	case cell != "mixed-bulk":
		require.Zero(t, background)
	case granted:
		require.Equal(t, 1, background)
	default:
		require.Equal(t, 2, background)
	}
	for _, conn := range server.Connections {
		require.Empty(t, conn.CloseCause)
		require.Equal(t, controller, conn.Controller)
		require.Equal(t, controller == "reno", conn.Lost.Available, "only Reno's counter has a producer")
		require.Equal(t, conn.Lost.Value, conn.PacketsLost)
		require.Equal(t, granted && cell == "mixed-bulk" && conn.Label == ordinaryCostBackground, conn.Multipath)
	}
	if cell == "stateless-pressure" {
		require.NotZero(t, client.Flood.Sent)
		require.NotZero(t, client.Flood.Resets, "unknown connection IDs draw stateless resets")
	} else {
		require.Nil(t, client.Flood)
	}
}
