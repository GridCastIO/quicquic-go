//go:build ordinarycost && ((linux && amd64) || (darwin && arm64))

package quic

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"runtime"
	"runtime/metrics"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

// MP-MAC C2 (#1491) observes memory at three states of a real negotiated path lifecycle:
// negotiated idle on path zero, a validated backup path, and that same path ID after
// retirement. Only the public multipath interfaces drive it, so it runs where public
// admission exists and refuses elsewhere. interop/multipath/ordinary_cost.py
// --lifecycle-memory runs the two roles as separate processes and reads the record back.
const (
	ordinaryCostIdle    = "negotiated-idle"
	ordinaryCostBackup  = "validated-backup"
	ordinaryCostRetired = "retired"

	// ordinaryCostLifecycleFormat versions both role records; readback admits only it.
	ordinaryCostLifecycleFormat = "mp-mac-c2-lifecycle-memory/1"

	ordinaryCostHeapSource   = "runtime/metrics /gc/heap/live:bytes after a forced runtime.GC()"
	ordinaryCostDetachSource = "Conn.WaitTransportDetachedV1"
	ordinaryCostJoinSource   = "Transport.WaitMultipathIOStoppedV1 after Transport.Close"
	// ordinaryCostLifecycleTimeout bounds one role when the driver supplies no timeout.
	ordinaryCostLifecycleTimeout = 30 * time.Second
)

// ordinaryCostPhases are the samples of one lifecycle record, in order. There is no fourth.
var ordinaryCostPhases = []string{ordinaryCostIdle, ordinaryCostBackup, ordinaryCostRetired}

var errOrdinaryCostUnnegotiated = errors.New("multipath was not negotiated: an ordinary connection is no lifecycle or backup control")

type ordinaryCostLifecycleSpec struct {
	Controller string `json:"controller"`
	Role       string `json:"role"`
	Address    string `json:"address"`
	// Retired is the one qualifying retirement state, retained or closed, that Q1 binds
	// for both sides of a comparison.
	Retired   string `json:"retired_lifecycle"`
	Output    string `json:"output"`
	TimeoutNS int64  `json:"timeout_ns"`
}

func (s ordinaryCostLifecycleSpec) validateFor(platform ordinaryCostPlatformProfile) error {
	switch s.Controller {
	case "reno", "bbrv3":
	default:
		return fmt.Errorf("unknown lifecycle controller %q", s.Controller)
	}
	if s.Retired != "retained" && s.Retired != "closed" {
		return fmt.Errorf("the retirement state is retained or closed, not %q", s.Retired)
	}
	if !platform.negotiatedMultipath {
		return fmt.Errorf("negotiated lifecycle memory needs public multipath admission, which %s does not have until Q2", platform.name)
	}
	return nil
}

func (s ordinaryCostLifecycleSpec) timeout() time.Duration {
	if s.TimeoutNS <= 0 {
		return ordinaryCostLifecycleTimeout
	}
	return time.Duration(s.TimeoutNS)
}

// ordinaryCostPathState is the part of one StateV1 observation that identifies a phase.
type ordinaryCostPathState struct {
	WireID          uint32 `json:"wire_id"`
	TupleGeneration uint64 `json:"tuple_generation"`
	Lifecycle       string `json:"lifecycle"`
	LocalUse        string `json:"local_use"`
	Primary         bool   `json:"primary"`
	Validated       bool   `json:"validated"`
}

func ordinaryCostPathStateOf(s MultipathPathStateV1) ordinaryCostPathState {
	return ordinaryCostPathState{
		WireID: s.WireID, TupleGeneration: s.TupleGeneration, Lifecycle: s.Lifecycle,
		LocalUse: s.LocalUse, Primary: s.Primary, Validated: s.Validated,
	}
}

// ordinaryCostPhaseAdmits reports whether an observed state of the sampled path is the
// phase. A requested transition counts only once StateV1 shows it.
func ordinaryCostPhaseAdmits(phase string, id uint32, state ordinaryCostPathState, retired string) error {
	if state.WireID != id {
		return fmt.Errorf("%s: the observation is of path %d, not the sampled path %d", phase, state.WireID, id)
	}
	switch phase {
	case ordinaryCostIdle:
		if id != 0 || state.Lifecycle != "live" || !state.Validated || !state.Primary || state.LocalUse != "active" {
			return fmt.Errorf("%s needs live, validated, primary path zero, not path %d %+v", phase, id, state)
		}
	case ordinaryCostBackup:
		if id == 0 || state.Lifecycle != "live" || !state.Validated || state.Primary || state.LocalUse != "backup" {
			return fmt.Errorf("%s needs a live, validated backup path besides path zero, not path %d %+v", phase, id, state)
		}
	case ordinaryCostRetired:
		if id == 0 {
			return fmt.Errorf("%s samples the retired backup path, not path zero", phase)
		}
		// A live path is not retired, even once a same-ID migration detached its old
		// transport, and retiring has not yet signaled its abandonment.
		if state.Lifecycle != retired {
			return fmt.Errorf("%s needs path %d %s, not %s", phase, id, retired, state.Lifecycle)
		}
	default:
		return fmt.Errorf("unknown lifecycle phase %q", phase)
	}
	return nil
}

// ordinaryCostLifecycleSample is one memory reading of the sampled path's phase, with the
// observation that preceded it and the one that followed it.
type ordinaryCostLifecycleSample struct {
	Phase      string `json:"phase"`
	Role       string `json:"role"`
	PathID     uint32 `json:"path_id"`
	Negotiated bool   `json:"multipath_negotiated"`
	// Baseline names the matched comparison phase of this connection; the negotiated idle
	// sample is the baseline and has none.
	Baseline   *string               `json:"baseline"`
	Before     ordinaryCostPathState `json:"state_before"`
	After      ordinaryCostPathState `json:"state_after"`
	GoHeapLive ordinaryCostMetric    `json:"go_heap_live"`
	// PeakRSS is the process's lifetime peak at the sample, not memory held at the phase.
	PeakRSS ordinaryCostMetric `json:"peak_rss"`
}

// ordinaryCostLifecycleMemory forces a collection and reads the heap it marked live, then
// the C1 peak-RSS collector. Go heap is not resident memory.
func ordinaryCostLifecycleMemory() (heap, rss ordinaryCostMetric, err error) {
	runtime.GC()
	sample := []metrics.Sample{{Name: "/gc/heap/live:bytes"}}
	metrics.Read(sample)
	if sample[0].Value.Kind() == metrics.KindUint64 {
		heap = ordinaryCostObserved(sample[0].Value.Uint64(), "bytes", ordinaryCostHeapSource)
	} else {
		heap = ordinaryCostUnavailable("bytes", ordinaryCostHeapSource, "this runtime does not report /gc/heap/live:bytes")
	}
	rss, err = ordinaryCostPeakRSS()
	return heap, rss, err
}

// ordinaryCostSampleAt takes one phase sample of path id. The phase must be observed before
// the memory reading and still hold after it; otherwise the reading is stale.
func ordinaryCostSampleAt(phase, role string, negotiated bool, id uint32, retired string,
	state func() (MultipathPathStateV1, error),
	memory func() (ordinaryCostMetric, ordinaryCostMetric, error),
) (ordinaryCostLifecycleSample, error) {
	if !negotiated {
		return ordinaryCostLifecycleSample{}, fmt.Errorf("%s: %w", phase, errOrdinaryCostUnnegotiated)
	}
	observed, err := state()
	if err != nil {
		return ordinaryCostLifecycleSample{}, err
	}
	before := ordinaryCostPathStateOf(observed)
	if err := ordinaryCostPhaseAdmits(phase, id, before, retired); err != nil {
		return ordinaryCostLifecycleSample{}, err
	}
	heap, rss, err := memory()
	if err != nil {
		return ordinaryCostLifecycleSample{}, err
	}
	if observed, err = state(); err != nil {
		return ordinaryCostLifecycleSample{}, err
	}
	after := ordinaryCostPathStateOf(observed)
	if after != before {
		return ordinaryCostLifecycleSample{}, fmt.Errorf("%s: stale sample, path %d changed from %+v to %+v during the reading", phase, id, before, after)
	}
	sample := ordinaryCostLifecycleSample{
		Phase: phase, Role: role, PathID: id, Negotiated: negotiated,
		Before: before, After: after, GoHeapLive: heap, PeakRSS: rss,
	}
	if phase != ordinaryCostIdle {
		baseline := ordinaryCostIdle
		sample.Baseline = &baseline
	}
	return sample, nil
}

// ordinaryCostAwaitLifecycle waits until StateV1 shows path at lifecycle, or fails if the
// path passed it: retained comes before closed.
func ordinaryCostAwaitLifecycle(ctx context.Context, path *Path, lifecycle string) error {
	ticker := time.NewTicker(time.Millisecond)
	defer ticker.Stop()
	for {
		state, err := path.StateV1()
		if err != nil {
			return err
		}
		switch {
		case state.Lifecycle == lifecycle:
			return nil
		case lifecycle == "retained" && state.Lifecycle == "closed":
			return errors.New("the path closed before a retained state was observed")
		}
		select {
		case <-ctx.Done():
			return fmt.Errorf("waiting for %s, last %s: %w", lifecycle, state.Lifecycle, ctx.Err())
		case <-ticker.C:
		}
	}
}

// ordinaryCostLease owns every transport a lifecycle role opens and the role's connection.
// Each return path closes them and joins each grant, success or failure.
type ordinaryCostLease struct {
	conn       *Conn
	transports []ordinaryCostLeased
}

type ordinaryCostLeased struct {
	name   string
	tr     *Transport
	socket *net.UDPConn
}

// open grants a fresh socket through the public interface, the only lifecycle seam.
func (l *ordinaryCostLease) open(name, address string) (*Transport, error) {
	addr, err := net.ResolveUDPAddr("udp", address)
	if err != nil {
		return nil, err
	}
	socket, err := net.ListenUDP("udp", addr)
	if err != nil {
		return nil, err
	}
	tr := &Transport{Conn: socket, ConnectionIDLength: 4}
	if err := tr.ConfigureMultipathIOV1(ordinaryCostWriteBudget); err != nil {
		return nil, errors.Join(err, socket.Close())
	}
	l.transports = append(l.transports, ordinaryCostLeased{name: name, tr: tr, socket: socket})
	return tr, nil
}

// release closes the connection, then each transport, and records each grant's join
// separately from any transport detachment.
func (l *ordinaryCostLease) release(joins map[string]bool) error {
	if l.conn != nil {
		_ = l.conn.CloseWithError(0, "")
	}
	var errs []error
	for _, leased := range l.transports {
		errs = append(errs, leased.tr.Close())
		ctx, cancel := context.WithTimeout(context.Background(), ordinaryCostStopTimeout)
		err := leased.tr.WaitMultipathIOStoppedV1(ctx)
		cancel()
		joins[leased.name] = err == nil
		errs = append(errs, err, leased.socket.Close())
	}
	return errors.Join(errs...)
}

type ordinaryCostDetachment struct {
	Transport string `json:"transport"`
	Detached  bool   `json:"detached"`
	Source    string `json:"source"`
}

// ordinaryCostEstablishedController observes the congestion controller an established
// connection runs. A requested controller becomes the record's only once the connection
// runs it.
func ordinaryCostEstablishedController(conn *Conn, requested string) (string, error) {
	observed := conn.CongestionControlV1()
	if observed != requested {
		return observed, fmt.Errorf("the established connection runs %s, not the requested %s", observed, requested)
	}
	return observed, nil
}

// ordinaryCostLifecycleClientResult is one role's record. Its Controller is observed on the
// established connection, and is empty if there was none.
type ordinaryCostLifecycleClientResult struct {
	Format           string                        `json:"format"`
	Role             string                        `json:"role"`
	Controller       string                        `json:"controller"`
	Go               string                        `json:"go"`
	Platform         ordinaryCostIdentity          `json:"platform"`
	RetiredLifecycle string                        `json:"retired_lifecycle"`
	Negotiated       bool                          `json:"multipath_negotiated"`
	Samples          []ordinaryCostLifecycleSample `json:"samples"`
	Detachment       ordinaryCostDetachment        `json:"transport_detachment"`
	GrantJoins       map[string]bool               `json:"grant_joins"`
	JoinSource       string                        `json:"grant_join_source"`
}

// ordinaryCostLifecycleServerResult is one role's record. Its Controller is observed on the
// accepted connection, and is empty if there was none.
type ordinaryCostLifecycleServerResult struct {
	Format     string               `json:"format"`
	Role       string               `json:"role"`
	Controller string               `json:"controller"`
	Go         string               `json:"go"`
	Platform   ordinaryCostIdentity `json:"platform"`
	Negotiated bool                 `json:"multipath_negotiated"`
	PeerClosed bool                 `json:"peer_closed"`
	CloseCause string               `json:"close_cause"`
	GrantJoins map[string]bool      `json:"grant_joins"`
	JoinSource string               `json:"grant_join_source"`
}

// ordinaryCostRunLifecycleClient drives the sampled lifecycle: idle on path zero, a backup
// path opened from a second granted transport, then that path abandoned, observed at the
// qualifying state, and its transport detached. conf is the C1 multipath Config.
func ordinaryCostRunLifecycleClient(ctx context.Context, spec ordinaryCostLifecycleSpec, conf *Config) (result *ordinaryCostLifecycleClientResult, err error) {
	result = &ordinaryCostLifecycleClientResult{
		Format: ordinaryCostLifecycleFormat, Role: "client", Go: runtime.Version(), Platform: ordinaryCostHost.identity(),
		RetiredLifecycle: spec.Retired, Samples: []ordinaryCostLifecycleSample{}, GrantJoins: map[string]bool{},
		JoinSource: ordinaryCostJoinSource,
		Detachment: ordinaryCostDetachment{Transport: "backup", Source: ordinaryCostDetachSource},
	}
	ctx, cancel := context.WithTimeout(ctx, spec.timeout())
	defer cancel()
	lease := &ordinaryCostLease{}
	defer func() { err = errors.Join(err, lease.release(result.GrantJoins)) }()

	server, err := net.ResolveUDPAddr("udp", spec.Address)
	if err != nil {
		return result, err
	}
	origin, err := lease.open("origin", "127.0.0.1:0")
	if err != nil {
		return result, err
	}
	if lease.conn, err = origin.Dial(ctx, server, ordinaryCostClientTLS(), conf); err != nil {
		return result, err
	}
	if result.Controller, err = ordinaryCostEstablishedController(lease.conn, spec.Controller); err != nil {
		return result, err
	}
	if result.Negotiated, err = lease.conn.MultipathNegotiatedV1(); err != nil {
		return result, err
	}
	if !result.Negotiated {
		return result, errOrdinaryCostUnnegotiated
	}
	sample := func(phase string, path *Path) error {
		id, err := path.PathIDV1()
		if err != nil {
			return err
		}
		taken, err := ordinaryCostSampleAt(phase, result.Role, result.Negotiated, id, spec.Retired, path.StateV1, ordinaryCostLifecycleMemory)
		if err != nil {
			return err
		}
		result.Samples = append(result.Samples, taken)
		return nil
	}
	paths := lease.conn.PathsV1()
	if len(paths) != 1 {
		return result, fmt.Errorf("negotiated idle has %d paths, not path zero alone", len(paths))
	}
	if err := sample(ordinaryCostIdle, paths[0]); err != nil {
		return result, err
	}
	second, err := lease.open("backup", "127.0.0.1:0")
	if err != nil {
		return result, err
	}
	path, err := lease.conn.OpenPathV1(ctx, second, server)
	if err != nil {
		return result, err
	}
	if err := sample(ordinaryCostBackup, path); err != nil {
		return result, err
	}
	if err := path.AbandonV1(0); err != nil {
		return result, err
	}
	if err := ordinaryCostAwaitLifecycle(ctx, path, spec.Retired); err != nil {
		return result, err
	}
	if err := sample(ordinaryCostRetired, path); err != nil {
		return result, err
	}
	if err := lease.conn.WaitTransportDetachedV1(ctx, second); err != nil {
		return result, err
	}
	result.Detachment.Detached = true
	return result, nil
}

// ordinaryCostRunLifecycleServer is the unsampled negotiated peer. It holds one connection
// until the client closes it.
func ordinaryCostRunLifecycleServer(ctx context.Context, spec ordinaryCostLifecycleSpec, conf *Config) (result *ordinaryCostLifecycleServerResult, err error) {
	result = &ordinaryCostLifecycleServerResult{
		Format: ordinaryCostLifecycleFormat, Role: "server", Go: runtime.Version(), Platform: ordinaryCostHost.identity(),
		GrantJoins: map[string]bool{}, JoinSource: ordinaryCostJoinSource,
	}
	ctx, cancel := context.WithTimeout(ctx, spec.timeout())
	defer cancel()
	lease := &ordinaryCostLease{}
	defer func() { err = errors.Join(err, lease.release(result.GrantJoins)) }()

	tr, err := lease.open("origin", spec.Address)
	if err != nil {
		return result, err
	}
	listener, err := tr.Listen(ordinaryCostServerTLS(), conf)
	if err != nil {
		return result, err
	}
	defer listener.Close()
	if lease.conn, err = listener.Accept(ctx); err != nil {
		return result, err
	}
	if result.Controller, err = ordinaryCostEstablishedController(lease.conn, spec.Controller); err != nil {
		return result, err
	}
	if result.Negotiated, err = lease.conn.MultipathNegotiatedV1(); err != nil {
		return result, err
	}
	select {
	case <-lease.conn.Context().Done():
	case <-ctx.Done():
		return result, fmt.Errorf("the client did not close: %w", ctx.Err())
	}
	cause := context.Cause(lease.conn.Context())
	result.CloseCause = cause.Error()
	var appErr *ApplicationError
	result.PeerClosed = errors.As(cause, &appErr) && appErr.Remote && appErr.ErrorCode == 0
	if !result.PeerClosed {
		return result, fmt.Errorf("the connection ended without the client's close: %w", cause)
	}
	return result, nil
}

// TestOrdinaryCostLifecycleRole runs the one lifecycle role that
// ORDINARY_COST_LIFECYCLE_SPEC names.
func TestOrdinaryCostLifecycleRole(t *testing.T) {
	if os.Getenv("ORDINARY_COST_LIFECYCLE_SPEC") == "" {
		t.Skip("ordinary-cost driver supplies the lifecycle role specification")
	}
	var spec ordinaryCostLifecycleSpec
	require.NoError(t, json.Unmarshal([]byte(os.Getenv("ORDINARY_COST_LIFECYCLE_SPEC")), &spec), "the driver supplies the spec")
	require.NoError(t, spec.validateFor(ordinaryCostHost))
	conf := ordinaryCostConfig(t, true, spec.Controller)
	var result any
	var err error
	switch spec.Role {
	case "server":
		result, err = ordinaryCostRunLifecycleServer(t.Context(), spec, conf)
	case "client":
		result, err = ordinaryCostRunLifecycleClient(t.Context(), spec, conf)
	default:
		t.Fatalf("unknown role %q", spec.Role)
	}
	require.NoError(t, err)
	data, err := json.MarshalIndent(result, "", "  ")
	require.NoError(t, err)
	require.NoError(t, os.WriteFile(spec.Output, data, 0o644))
}

// TestOrdinaryCostLifecyclePhases checks phase admission and sample consistency on any
// host, with recorded states rather than a connection.
func TestOrdinaryCostLifecyclePhases(t *testing.T) {
	idle := ordinaryCostPathState{WireID: 0, Lifecycle: "live", LocalUse: "active", Primary: true, Validated: true}
	backup := ordinaryCostPathState{WireID: 1, TupleGeneration: 1, Lifecycle: "live", LocalUse: "backup", Validated: true}
	retired := func(lifecycle string) ordinaryCostPathState {
		state := backup
		state.Lifecycle = lifecycle
		return state
	}
	require.NoError(t, ordinaryCostPhaseAdmits(ordinaryCostIdle, 0, idle, "closed"))
	require.NoError(t, ordinaryCostPhaseAdmits(ordinaryCostBackup, 1, backup, "closed"))
	for _, want := range []string{"retained", "closed"} {
		require.NoError(t, ordinaryCostPhaseAdmits(ordinaryCostRetired, 1, retired(want), want))
	}
	// The two qualifying states are distinct: each admits only itself.
	require.Error(t, ordinaryCostPhaseAdmits(ordinaryCostRetired, 1, retired("retained"), "closed"))
	require.Error(t, ordinaryCostPhaseAdmits(ordinaryCostRetired, 1, retired("closed"), "retained"))
	for name, bad := range map[string]struct {
		phase string
		id    uint32
		state ordinaryCostPathState
	}{
		"idle on a backup path":           {ordinaryCostIdle, 1, backup},
		"idle before validation":          {ordinaryCostIdle, 0, func() ordinaryCostPathState { s := idle; s.Lifecycle, s.Validated = "validating", false; return s }()},
		"backup still validating":         {ordinaryCostBackup, 1, func() ordinaryCostPathState { s := backup; s.Lifecycle, s.Validated = "validating", false; return s }()},
		"backup in active use":            {ordinaryCostBackup, 1, func() ordinaryCostPathState { s := backup; s.LocalUse, s.Primary = "active", true; return s }()},
		"backup on path zero":             {ordinaryCostBackup, 0, func() ordinaryCostPathState { s := backup; s.WireID = 0; return s }()},
		"retiring is not retired":         {ordinaryCostRetired, 1, retired("retiring")},
		"a live path is not retired":      {ordinaryCostRetired, 1, backup},
		"retired path zero":               {ordinaryCostRetired, 0, func() ordinaryCostPathState { s := retired("closed"); s.WireID = 0; return s }()},
		"an observation of another path":  {ordinaryCostBackup, 2, backup},
		"an unknown phase":                {"post-close", 1, retired("closed")},
		"a suspect path is not a backup":  {ordinaryCostBackup, 1, func() ordinaryCostPathState { s := backup; s.Lifecycle = "suspect"; return s }()},
		"a closed path is not idle state": {ordinaryCostIdle, 0, func() ordinaryCostPathState { s := idle; s.Lifecycle = "closed"; return s }()},
	} {
		require.Error(t, ordinaryCostPhaseAdmits(bad.phase, bad.id, bad.state, "closed"), name)
	}

	memory := func() (ordinaryCostMetric, ordinaryCostMetric, error) {
		rss, err := ordinaryCostRSSMetric(1000, "kB", "fixture")
		return ordinaryCostObserved(4096, "bytes", ordinaryCostHeapSource), rss, err
	}
	states := func(seq ...ordinaryCostPathState) func() (MultipathPathStateV1, error) {
		return func() (MultipathPathStateV1, error) {
			s := seq[0]
			if len(seq) > 1 {
				seq = seq[1:]
			}
			return MultipathPathStateV1{WireID: s.WireID, TupleGeneration: s.TupleGeneration, Lifecycle: s.Lifecycle, LocalUse: s.LocalUse, Primary: s.Primary, Validated: s.Validated}, nil
		}
	}
	sample, err := ordinaryCostSampleAt(ordinaryCostBackup, "client", true, 1, "closed", states(backup), memory)
	require.NoError(t, err)
	require.Equal(t, ordinaryCostIdle, *sample.Baseline, "a backup is compared with this connection's negotiated idle")
	require.Equal(t, backup, sample.Before)
	require.Equal(t, sample.Before, sample.After)
	sample, err = ordinaryCostSampleAt(ordinaryCostIdle, "client", true, 0, "closed", states(idle), memory)
	require.NoError(t, err)
	require.Nil(t, sample.Baseline, "negotiated idle is the baseline")
	encoded, err := json.Marshal(sample)
	require.NoError(t, err)
	require.Contains(t, string(encoded), `"baseline":null`)

	_, err = ordinaryCostSampleAt(ordinaryCostBackup, "client", false, 1, "closed", states(backup), memory)
	require.ErrorIs(t, err, errOrdinaryCostUnnegotiated, "an unnegotiated connection is no backup control")
	_, err = ordinaryCostSampleAt(ordinaryCostRetired, "client", true, 1, "retained", states(retired("retained"), retired("closed")), memory)
	require.ErrorContains(t, err, "stale", "the path left the phase during the reading")
	_, err = ordinaryCostSampleAt(ordinaryCostRetired, "client", true, 1, "closed", states(retired("retiring")), memory)
	require.Error(t, err, "a requested retirement is not an observed one")

	for _, platform := range []ordinaryCostPlatformProfile{ordinaryCostLinuxAMD64, ordinaryCostDarwinARM64} {
		for _, controller := range []string{"reno", "bbrv3"} {
			for _, retired := range []string{"retained", "closed"} {
				err := ordinaryCostLifecycleSpec{Controller: controller, Retired: retired}.validateFor(platform)
				if platform.negotiatedMultipath {
					require.NoError(t, err)
				} else {
					require.ErrorContains(t, err, "public multipath admission", platform.name)
				}
			}
		}
		require.ErrorContains(t, ordinaryCostLifecycleSpec{Controller: "cubic", Retired: "closed"}.validateFor(platform), "controller")
		require.ErrorContains(t, ordinaryCostLifecycleSpec{Controller: "reno", Retired: "retiring"}.validateFor(platform), "retained or closed")
	}
}

// TestOrdinaryCostLifecycle runs both lifecycle roles in one process for Reno and BBR where
// public admission exists. It checks the wiring and the record; its memory numbers mean
// nothing, since only the driver's separate processes attribute memory to one role.
// Elsewhere the public gate must refuse: that refusal is the readiness evidence there.
func TestOrdinaryCostLifecycle(t *testing.T) {
	address := func() string {
		probe := newUDPConnLocalhost(t)
		defer probe.Close()
		return probe.LocalAddr().String()
	}
	t.Run("a role with no connection observed no controller", func(t *testing.T) {
		spec := ordinaryCostLifecycleSpec{Controller: "reno", Retired: "closed", Address: "not-an-address", TimeoutNS: int64(5 * time.Second)}
		client, err := ordinaryCostRunLifecycleClient(t.Context(), spec, ordinaryCostConfig(t, true, "reno"))
		require.Error(t, err)
		require.Empty(t, client.Controller, "the requested controller is not an observed one")
		spec.Address = newUDPConnLocalhost(t).LocalAddr().String()
		server, err := ordinaryCostRunLifecycleServer(t.Context(), spec, ordinaryCostConfig(t, true, "reno"))
		require.Error(t, err, "the address is taken")
		require.Empty(t, server.Controller)
	})
	if !ordinaryCostHost.negotiatedMultipath {
		spec := ordinaryCostLifecycleSpec{Controller: "reno", Retired: "closed", Address: address(), TimeoutNS: int64(5 * time.Second)}
		require.ErrorContains(t, spec.validateFor(ordinaryCostHost), "public multipath admission")
		client, err := ordinaryCostRunLifecycleClient(t.Context(), spec, ordinaryCostConfig(t, true, "reno"))
		require.ErrorIs(t, err, ErrMultipathUnsupportedV1, "the public grant refuses")
		require.Empty(t, client.Samples)
		require.False(t, client.Negotiated)
		require.Empty(t, client.Controller)
		server, err := ordinaryCostRunLifecycleServer(t.Context(), spec, ordinaryCostConfig(t, true, "reno"))
		require.ErrorIs(t, err, ErrMultipathUnsupportedV1)
		require.False(t, server.Negotiated)
		require.Empty(t, server.Controller)
		return
	}

	for _, controller := range []string{"reno", "bbrv3"} {
		t.Run(controller, func(t *testing.T) {
			spec := ordinaryCostLifecycleSpec{Controller: controller, Retired: "closed", Address: address(), TimeoutNS: int64(20 * time.Second)}
			require.NoError(t, spec.validateFor(ordinaryCostHost))
			type served struct {
				result *ordinaryCostLifecycleServerResult
				err    error
			}
			servers := make(chan served, 1)
			serverConf := ordinaryCostConfig(t, true, controller)
			// A failed client ends the test's context, which stops a server still accepting;
			// cleanup then joins it, so its socket and grant never outlive the subtest.
			go func() {
				result, err := ordinaryCostRunLifecycleServer(t.Context(), spec, serverConf)
				servers <- served{result, err}
			}()
			joinServer := sync.OnceValue(func() served { return <-servers })
			t.Cleanup(func() { joinServer() })
			client, err := ordinaryCostRunLifecycleClient(t.Context(), spec, ordinaryCostConfig(t, true, controller))
			require.NoError(t, err)
			server := joinServer()
			require.NoError(t, server.err)
			require.Equal(t, ordinaryCostLifecycleFormat, client.Format)
			require.Equal(t, ordinaryCostLifecycleFormat, server.result.Format)

			require.True(t, client.Negotiated)
			require.Equal(t, controller, client.Controller)
			require.Equal(t, "closed", client.RetiredLifecycle)
			phases := make([]string, 0, len(client.Samples))
			for _, sample := range client.Samples {
				phases = append(phases, sample.Phase)
				require.Equal(t, "client", sample.Role)
				require.True(t, sample.Negotiated)
				require.Equal(t, sample.Before, sample.After)
				require.NoError(t, ordinaryCostPhaseAdmits(sample.Phase, sample.PathID, sample.Before, client.RetiredLifecycle))
				require.True(t, sample.GoHeapLive.Available)
				require.NotZero(t, *sample.GoHeapLive.Value)
				require.Equal(t, ordinaryCostHeapSource, sample.GoHeapLive.Source)
				require.True(t, sample.PeakRSS.Available)
				require.NotZero(t, *sample.PeakRSS.Bytes)
			}
			require.Equal(t, ordinaryCostPhases, phases)
			require.Zero(t, client.Samples[0].PathID)
			require.Nil(t, client.Samples[0].Baseline)
			require.Equal(t, client.Samples[1].PathID, client.Samples[2].PathID, "retirement samples the backup's path ID")
			require.NotZero(t, client.Samples[1].PathID)
			for _, sample := range client.Samples[1:] {
				require.Equal(t, ordinaryCostIdle, *sample.Baseline)
			}
			require.Equal(t, "closed", client.Samples[2].Before.Lifecycle)
			require.Equal(t, ordinaryCostDetachment{Transport: "backup", Detached: true, Source: ordinaryCostDetachSource}, client.Detachment)
			require.Equal(t, map[string]bool{"origin": true, "backup": true}, client.GrantJoins)
			require.True(t, server.result.Negotiated)
			require.Equal(t, controller, server.result.Controller)
			require.True(t, server.result.PeerClosed, server.result.CloseCause)
			require.Equal(t, map[string]bool{"origin": true}, server.result.GrantJoins)
		})
	}

	// A test-local Config makes one role's connection run bbrv3 where the run requested reno.
	// Each role's peer is an ordinary test-local endpoint on a socket held from the start, so
	// no address is released before it is bound and no peer role can finish first.
	t.Run("a client whose connection runs another controller fails", func(t *testing.T) {
		ordinary := &Transport{Conn: newUDPConnLocalhost(t)}
		t.Cleanup(func() { ordinary.Close() })
		ln, err := ordinary.Listen(ordinaryCostServerTLS(), ordinaryCostConfig(t, false, "reno"))
		require.NoError(t, err)
		t.Cleanup(func() { ln.Close() })
		go func() {
			if conn, err := ln.Accept(context.Background()); err == nil {
				<-conn.Context().Done()
			}
		}()
		spec := ordinaryCostLifecycleSpec{Controller: "reno", Retired: "closed", Address: ordinary.Conn.LocalAddr().String(), TimeoutNS: int64(10 * time.Second)}
		client, err := ordinaryCostRunLifecycleClient(t.Context(), spec, ordinaryCostConfig(t, true, "bbrv3"))
		require.ErrorContains(t, err, "runs bbrv3, not the requested reno")
		require.Equal(t, "bbrv3", client.Controller, "the result names what the connection ran")
		require.Empty(t, client.Samples)
	})

	t.Run("a server whose connection runs another controller fails", func(t *testing.T) {
		peer := &Transport{Conn: newUDPConnLocalhost(t)}
		t.Cleanup(func() { peer.Close() })
		spec := ordinaryCostLifecycleSpec{Controller: "reno", Retired: "closed", Address: address(), TimeoutNS: int64(10 * time.Second)}
		type served struct {
			result *ordinaryCostLifecycleServerResult
			err    error
		}
		servers := make(chan served, 1)
		serverConf := ordinaryCostConfig(t, true, "bbrv3")
		go func() {
			result, err := ordinaryCostRunLifecycleServer(t.Context(), spec, serverConf)
			servers <- served{result, err}
		}()
		joinServer := sync.OnceValue(func() served { return <-servers })
		t.Cleanup(func() { joinServer() })
		addr, err := net.ResolveUDPAddr("udp", spec.Address)
		require.NoError(t, err)
		ctx, cancel := context.WithTimeout(t.Context(), 10*time.Second)
		defer cancel()
		conn, err := peer.Dial(ctx, addr, ordinaryCostClientTLS(), ordinaryCostConfig(t, false, "reno"))
		require.NoError(t, err)
		select {
		case <-conn.Context().Done():
		case <-ctx.Done():
			t.Fatal("the mismatched server never closed the connection")
		}
		var appErr *ApplicationError
		require.ErrorAs(t, context.Cause(conn.Context()), &appErr)
		require.True(t, appErr.Remote, "the server role closed the connection")
		server := joinServer()
		require.ErrorContains(t, server.err, "runs bbrv3, not the requested reno")
		require.Equal(t, "bbrv3", server.result.Controller)
	})

	t.Run("an unnegotiated connection is no control", func(t *testing.T) {
		ordinary := &Transport{Conn: newUDPConnLocalhost(t)}
		t.Cleanup(func() { ordinary.Close() })
		ln, err := ordinary.Listen(ordinaryCostServerTLS(), ordinaryCostConfig(t, false, "reno"))
		require.NoError(t, err)
		t.Cleanup(func() { ln.Close() })
		go func() {
			if conn, err := ln.Accept(context.Background()); err == nil {
				<-conn.Context().Done()
			}
		}()
		spec := ordinaryCostLifecycleSpec{Controller: "reno", Retired: "closed", Address: ordinary.Conn.LocalAddr().String(), TimeoutNS: int64(10 * time.Second)}
		client, err := ordinaryCostRunLifecycleClient(t.Context(), spec, ordinaryCostConfig(t, true, "reno"))
		require.ErrorIs(t, err, errOrdinaryCostUnnegotiated)
		require.False(t, client.Negotiated)
		require.Empty(t, client.Samples, "no phase is sampled")
		require.Equal(t, map[string]bool{"origin": true}, client.GrantJoins, "the partial run still returned its grant")
	})

	t.Run("requested and detached states are not retirement", func(t *testing.T) {
		p := newMultipathPair(t)
		ctx, cancel := context.WithTimeout(t.Context(), 20*time.Second)
		defer cancel()
		second := grantedTransport(t)
		path, err := p.client.OpenPathV1(ctx, second, p.serverAddr)
		require.NoError(t, err)
		third := grantedTransport(t)
		require.NoError(t, path.MigrateV1(ctx, third))
		require.NoError(t, p.client.WaitTransportDetachedV1(ctx, second), "the old transport detached")
		id, err := path.PathIDV1()
		require.NoError(t, err)
		state, err := path.StateV1()
		require.NoError(t, err)
		require.Equal(t, "live", state.Lifecycle, "same-ID migration keeps the path live")
		for _, retired := range []string{"retained", "closed"} {
			require.Error(t, ordinaryCostPhaseAdmits(ordinaryCostRetired, id, ordinaryCostPathStateOf(state), retired), "detachment cannot satisfy the third sample")
		}

		require.NoError(t, path.AbandonV1(0))
		state, err = path.StateV1()
		require.NoError(t, err)
		// AbandonV1 returns once the connection accepts the retirement. Reclamation can
		// still publish closed before this read, which then rightly qualifies.
		switch state.Lifecycle {
		case "retiring", "retained":
			require.Error(t, ordinaryCostPhaseAdmits(ordinaryCostRetired, id, ordinaryCostPathStateOf(state), "closed"), "the returned command is not the observed state")
		case "closed":
			require.NoError(t, ordinaryCostPhaseAdmits(ordinaryCostRetired, id, ordinaryCostPathStateOf(state), "closed"))
		default:
			t.Fatalf("unexpected lifecycle %q after AbandonV1", state.Lifecycle)
		}
		require.NoError(t, ordinaryCostAwaitLifecycle(ctx, path, "closed"))
		state, err = path.StateV1()
		require.NoError(t, err)
		require.NoError(t, ordinaryCostPhaseAdmits(ordinaryCostRetired, id, ordinaryCostPathStateOf(state), "closed"))
		require.Error(t, ordinaryCostAwaitLifecycle(ctx, path, "retained"), "a closed path has passed retained")
	})
}
