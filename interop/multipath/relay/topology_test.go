package relay

import (
	"net/netip"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

var testServer = netip.MustParseAddrPort("127.0.0.1:4433")

// testConfig returns a valid configuration of kind on ephemeral loopback fronts.
func testConfig(kind Kind) Config {
	front := netip.MustParseAddrPort("127.0.0.1:0")
	delay := int64(10 * time.Millisecond)
	switch kind {
	case KindDisjoint:
		return Config{
			Kind: kind, Server: testServer,
			Queues: []Queue{{RateBPS: 8_000_000, LimitBytes: 20_000}, {RateBPS: 8_000_000, LimitBytes: 20_000}},
			Routes: []Route{{Name: RouteA, Front: front, Queue: 0, DelayNS: delay}, {Name: RouteB, Front: front, Queue: 1, DelayNS: delay}},
		}
	case KindUnequal:
		return Config{
			Kind: kind, Server: testServer,
			Queues: []Queue{{RateBPS: 8_000_000, LimitBytes: 20_000}, {RateBPS: 4_000_000, LimitBytes: 30_000}},
			Routes: []Route{{Name: RouteA, Front: front, Queue: 0, DelayNS: delay}, {Name: RouteB, Front: front, Queue: 1, DelayNS: 3 * delay}},
		}
	case KindShared:
		return Config{
			Kind: kind, Server: testServer,
			Queues: []Queue{{RateBPS: 8_000_000, LimitBytes: 20_000}},
			Routes: []Route{
				{Name: RouteA, Front: front, Queue: 0, DelayNS: delay},
				{Name: RouteB, Front: front, Queue: 0, DelayNS: delay},
				{Name: RouteCompetitor, Front: front, Queue: 0, DelayNS: delay},
			},
		}
	}
	panic("unknown kind " + string(kind))
}

// Each route departs at its own queue's service time plus its own delay. Disjoint
// routes have separate backlogs; shared routes, including the competitor, have one.
func TestTopologySchedule(t *testing.T) {
	now := time.Unix(100, 0)
	// 972 bytes plus 28 of headers take 1 ms at 8 Mbit/s and 2 ms at 4 Mbit/s.
	t.Run("disjoint", func(t *testing.T) {
		top, err := newTopology(testConfig(KindDisjoint))
		require.NoError(t, err)
		at, ok := top.route(RouteA).schedule(now, 972)
		require.True(t, ok)
		require.Equal(t, now.Add(11*time.Millisecond), at)
		at, ok = top.route(RouteB).schedule(now, 972)
		require.True(t, ok)
		require.Equal(t, now.Add(11*time.Millisecond), at, "b's queue is idle despite a's backlog")
	})
	t.Run("unequal", func(t *testing.T) {
		top, err := newTopology(testConfig(KindUnequal))
		require.NoError(t, err)
		at, ok := top.route(RouteA).schedule(now, 972)
		require.True(t, ok)
		require.Equal(t, now.Add(11*time.Millisecond), at)
		at, ok = top.route(RouteB).schedule(now, 972)
		require.True(t, ok)
		require.Equal(t, now.Add(32*time.Millisecond), at, "b has half the rate and three times the delay")
	})
	t.Run("shared", func(t *testing.T) {
		top, err := newTopology(testConfig(KindShared))
		require.NoError(t, err)
		at, ok := top.route(RouteA).schedule(now, 972)
		require.True(t, ok)
		require.Equal(t, now.Add(11*time.Millisecond), at)
		at, ok = top.route(RouteB).schedule(now, 972)
		require.True(t, ok)
		require.Equal(t, now.Add(12*time.Millisecond), at, "b waits behind a's datagram")
		at, ok = top.route(RouteCompetitor).schedule(now, 972)
		require.True(t, ok)
		require.Equal(t, now.Add(13*time.Millisecond), at, "the competitor waits behind both")
	})
}

func TestConfigValidate(t *testing.T) {
	for _, kind := range []Kind{KindDisjoint, KindUnequal, KindShared} {
		require.NoError(t, testConfig(kind).Validate(), kind)
	}
	// Unequal delays with equal rates are also an unequal topology.
	delays := testConfig(KindUnequal)
	delays.Queues[1] = delays.Queues[0]
	require.NoError(t, delays.Validate())

	for _, tc := range []struct {
		name   string
		kind   Kind
		mutate func(*Config)
		want   string
	}{
		{"unknown kind", KindDisjoint, func(c *Config) { c.Kind = "mesh" }, `unknown topology kind "mesh"`},
		{"missing server", KindDisjoint, func(c *Config) { c.Server = netip.AddrPort{} }, "server"},
		{"server port zero", KindDisjoint, func(c *Config) { c.Server = netip.MustParseAddrPort("127.0.0.1:0") }, "server"},
		{"IPv6 server", KindDisjoint, func(c *Config) { c.Server = netip.MustParseAddrPort("[::1]:4433") }, "IPv4"},
		{"IPv6 front", KindDisjoint, func(c *Config) { c.Routes[1].Front = netip.MustParseAddrPort("[::1]:0") }, "IPv4"},
		{"duplicate front", KindDisjoint, func(c *Config) {
			c.Routes[0].Front = netip.MustParseAddrPort("127.0.0.1:5000")
			c.Routes[1].Front = netip.MustParseAddrPort("127.0.0.1:5000")
		}, "duplicate front"},
		{"front is server", KindDisjoint, func(c *Config) { c.Routes[0].Front = testServer }, "server"},
		{"competitor outside shared", KindDisjoint, func(c *Config) {
			c.Routes = append(c.Routes, Route{Name: RouteCompetitor, Front: c.Routes[0].Front})
		}, "routes"},
		{"shared without competitor", KindShared, func(c *Config) { c.Routes = c.Routes[:2] }, "routes"},
		{"routes out of order", KindDisjoint, func(c *Config) { c.Routes[0], c.Routes[1] = c.Routes[1], c.Routes[0] }, "routes"},
		{"wrong queue count", KindShared, func(c *Config) { c.Queues = append(c.Queues, c.Queues[0]) }, "queues"},
		{"queue out of range", KindUnequal, func(c *Config) { c.Routes[1].Queue = 2 }, "queue"},
		{"disjoint routes share a queue", KindDisjoint, func(c *Config) { c.Routes[1].Queue = 0 }, "separate queues"},
		{"disjoint rates differ", KindDisjoint, func(c *Config) { c.Queues[1].RateBPS /= 2 }, "identical"},
		{"disjoint delays differ", KindDisjoint, func(c *Config) { c.Routes[1].DelayNS *= 2 }, "identical"},
		{"unequal without a difference", KindUnequal, func(c *Config) {
			c.Queues[1] = c.Queues[0]
			c.Routes[1].DelayNS = c.Routes[0].DelayNS
		}, "differ"},
		{"rate too low", KindShared, func(c *Config) { c.Queues[0].RateBPS = MinRateBPS - 1 }, "rate"},
		{"rate too high", KindShared, func(c *Config) { c.Queues[0].RateBPS = MaxRateBPS + 1 }, "rate"},
		{"limit too small", KindShared, func(c *Config) { c.Queues[0].LimitBytes = MinLimitBytes - 1 }, "limit"},
		{"limit too large", KindShared, func(c *Config) { c.Queues[0].LimitBytes = MaxLimitBytes + 1 }, "limit"},
		{"negative delay", KindShared, func(c *Config) { c.Routes[0].DelayNS = -1 }, "delay"},
		{"delay too long", KindShared, func(c *Config) { c.Routes[0].DelayNS = int64(MaxDelay) + 1 }, "delay"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			c := testConfig(tc.kind)
			tc.mutate(&c)
			err := c.Validate()
			require.ErrorContains(t, err, tc.want)
			_, err = newTopology(c)
			require.Error(t, err, "the topology refuses what Validate refuses")
		})
	}
}
