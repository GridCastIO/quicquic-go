package relay

import (
	"net"
	"net/netip"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

// listenLoopback returns a test-owned UDP socket on an ephemeral loopback port.
func listenLoopback(t *testing.T) *net.UDPConn {
	t.Helper()
	conn, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	require.NoError(t, err)
	t.Cleanup(func() { conn.Close() })
	return conn
}

func addrPort(t *testing.T, a net.Addr) netip.AddrPort {
	t.Helper()
	ap := a.(*net.UDPAddr).AddrPort()
	return netip.AddrPortFrom(ap.Addr().Unmap(), ap.Port())
}

// startRelay starts cfg towards server and closes the relay at cleanup if the test did
// not.
func startRelay(t *testing.T, cfg Config, server *net.UDPConn) *Relay {
	t.Helper()
	cfg.Server = addrPort(t, server.LocalAddr())
	r, err := Start(cfg)
	require.NoError(t, err)
	t.Cleanup(func() { r.Close() })
	return r
}

func readWithin(t *testing.T, conn *net.UDPConn, d time.Duration) ([]byte, netip.AddrPort) {
	t.Helper()
	require.NoError(t, conn.SetReadDeadline(time.Now().Add(d)))
	buf := make([]byte, 2048)
	n, from, err := conn.ReadFromUDPAddrPort(buf)
	require.NoError(t, err)
	return buf[:n], netip.AddrPortFrom(from.Addr().Unmap(), from.Port())
}

func routeRecord(t *testing.T, rec Record, name RouteName) RouteRecord {
	t.Helper()
	for _, r := range rec.Routes {
		if r.Name == name {
			return r
		}
	}
	t.Fatalf("no route %s in record", name)
	return RouteRecord{}
}

// Each route forwards between its own front and the server through its own back
// tuple, and replies return to the client that last sent on that route.
func TestRelayRoutesRealUDP(t *testing.T) {
	server := listenLoopback(t)
	cfg := testConfig(KindDisjoint)
	for i := range cfg.Routes {
		cfg.Routes[i].DelayNS = int64(time.Millisecond)
	}
	r := startRelay(t, cfg, server)
	fronts := r.Fronts()
	require.Len(t, fronts, 2)

	clients := map[RouteName]*net.UDPConn{RouteA: listenLoopback(t), RouteB: listenLoopback(t)}
	for name, c := range clients {
		front := fronts[name]
		require.NotZero(t, front.Port())
		_, err := c.WriteToUDPAddrPort([]byte("to server via "+string(name)), front)
		require.NoError(t, err)
	}
	sources := make(map[string]netip.AddrPort)
	for range 2 {
		data, from := readWithin(t, server, 5*time.Second)
		sources[string(data)] = from
		_, err := server.WriteToUDPAddrPort(append([]byte("reply "), data...), from)
		require.NoError(t, err)
	}
	require.NotEqual(t, sources["to server via a"], sources["to server via b"], "each route has its own back tuple")
	for name, c := range clients {
		data, from := readWithin(t, c, 5*time.Second)
		require.Equal(t, "reply to server via "+string(name), string(data))
		require.Equal(t, fronts[name], from, "the reply leaves the route's front")
	}

	rec, err := r.Close()
	require.NoError(t, err)
	require.NoError(t, rec.Validate())
	require.Equal(t, RecordVersion, rec.Version)
	require.Equal(t, cfg.Kind, rec.Config.Kind)
	for _, name := range []RouteName{RouteA, RouteB} {
		route := routeRecord(t, rec, name)
		require.Equal(t, fronts[name], route.Front)
		require.Equal(t, sources["to server via "+string(name)], route.Back)
		payload := uint64(len("to server via " + string(name)))
		require.Equal(t, Direction{Received: 1, ReceivedBytes: payload, Delivered: 1, DeliveredBytes: payload}, route.Forward.counts())
		require.Equal(t, Direction{Received: 1, ReceivedBytes: payload + 6, Delivered: 1, DeliveredBytes: payload + 6}, route.Reverse.counts())
	}

	_, err = r.Close()
	require.ErrorIs(t, err, net.ErrClosed, "a relay closes once")
	// Close released the front sockets.
	for _, front := range fronts {
		conn, err := net.ListenUDP("udp4", net.UDPAddrFromAddrPort(front))
		require.NoError(t, err)
		conn.Close()
	}
}

// counts drops the lateness observations, which depend on scheduling.
func (d Direction) counts() Direction {
	d.LateOver1ms, d.MaxLateNS = 0, 0
	return d
}

// A burst into a shared bottleneck that holds one datagram's service time overflows its
// limit, and the record still accounts for every received datagram.
func TestRelaySharedQueueDropsRealUDP(t *testing.T) {
	server := listenLoopback(t)
	cfg := testConfig(KindShared)
	// 1000 bytes plus 28 of headers take 8.2 ms at 1 Mbit/s; the limit holds 12 ms.
	cfg.Queues[0] = Queue{RateBPS: MinRateBPS, LimitBytes: MinLimitBytes}
	for i := range cfg.Routes {
		cfg.Routes[i].DelayNS = 0
	}
	r := startRelay(t, cfg, server)
	fronts := r.Fronts()
	payload := make([]byte, 1000)
	for _, name := range []RouteName{RouteA, RouteCompetitor} {
		c := listenLoopback(t)
		for range 25 {
			_, err := c.WriteToUDPAddrPort(payload, fronts[name])
			require.NoError(t, err)
		}
	}
	readWithin(t, server, 5*time.Second)

	rec, err := r.Close()
	require.NoError(t, err)
	var dropped, delivered uint64
	for _, route := range rec.Routes {
		dropped += route.Forward.Dropped
		delivered += route.Forward.Delivered
	}
	require.NotZero(t, dropped, "the shared tail drops")
	require.NotZero(t, delivered)
	require.Zero(t, routeRecord(t, rec, RouteB).Forward.Received, "b carried nothing")
}

// Close does not wait out pending delays: it abandons waiting datagrams, joins every
// worker and still accounts for them.
func TestRelayCloseAbandonsPendingDeliveries(t *testing.T) {
	server := listenLoopback(t)
	cfg := testConfig(KindDisjoint)
	for i := range cfg.Routes {
		cfg.Routes[i].DelayNS = int64(MaxDelay)
	}
	r := startRelay(t, cfg, server)
	client := listenLoopback(t)
	for range 3 {
		_, err := client.WriteToUDPAddrPort([]byte("late"), r.Fronts()[RouteA])
		require.NoError(t, err)
	}
	require.Eventually(t, func() bool {
		return r.Snapshot()[0].Forward.Received == 3
	}, 5*time.Second, time.Millisecond)

	start := time.Now()
	rec, err := r.Close()
	require.NoError(t, err)
	require.Less(t, time.Since(start), MaxDelay/2, "Close interrupts pending delays")
	a := routeRecord(t, rec, RouteA)
	require.Equal(t, Direction{Received: 3, ReceivedBytes: 12, Abandoned: 3}, a.Forward.counts())
	require.NoError(t, server.SetReadDeadline(time.Now().Add(50*time.Millisecond)))
	_, _, err = server.ReadFromUDP(make([]byte, 16))
	require.Error(t, err, "nothing abandoned reaches the server")
}

// A Start that fails on a later route releases the sockets of the routes it opened.
func TestRelayStartFailureReleasesSockets(t *testing.T) {
	server := listenLoopback(t)
	occupied := listenLoopback(t)
	// Reserve a free port for route a by binding and releasing it.
	probe := listenLoopback(t)
	free := addrPort(t, probe.LocalAddr())
	probe.Close()

	cfg := testConfig(KindDisjoint)
	cfg.Server = addrPort(t, server.LocalAddr())
	cfg.Routes[0].Front = free
	cfg.Routes[1].Front = addrPort(t, occupied.LocalAddr())
	_, err := Start(cfg)
	require.ErrorContains(t, err, "route b")

	conn, err := net.ListenUDP("udp4", net.UDPAddrFromAddrPort(free))
	require.NoError(t, err, "route a's front was released")
	conn.Close()

	_, err = Start(Config{Kind: "mesh"})
	require.ErrorContains(t, err, "unknown topology kind")
}
