package relay

import (
	"errors"
	"fmt"
	"net/netip"
	"slices"
	"time"
)

// Configuration bounds. They keep the queue arithmetic in range and reject
// configurations that cannot carry a full-size datagram.
const (
	MinRateBPS    = 1_000_000
	MaxRateBPS    = 100_000_000_000
	MinLimitBytes = 1500
	MaxLimitBytes = 1 << 30
	MaxDelay      = 10 * time.Second
)

// Kind is one of the three closed topologies. It is not a graph language: each kind
// fixes its routes and how they map to queues.
type Kind string

const (
	// KindDisjoint gives routes a and b separate, identically configured queues and
	// equal delays.
	KindDisjoint Kind = "disjoint"
	// KindUnequal gives routes a and b separate queues whose rates or delays differ.
	KindUnequal Kind = "unequal"
	// KindShared puts routes a, b and the competitor through one shared queue.
	KindShared Kind = "shared"
)

// RouteName identifies a route through the relay.
type RouteName string

const (
	RouteA          RouteName = "a"
	RouteB          RouteName = "b"
	RouteCompetitor RouteName = "competitor"
)

// Route is one path through the relay. Front is the client-facing IPv4 address the
// relay listens on; port zero binds an ephemeral port, reported by Relay.Fronts and
// the record. Client-to-server datagrams pass through the named queue and then wait
// DelayNS; server-to-client datagrams wait DelayNS only.
type Route struct {
	Name    RouteName      `json:"name"`
	Front   netip.AddrPort `json:"front"`
	Queue   int            `json:"queue"`
	DelayNS int64          `json:"delay_ns"`
}

// Config is the relay's explicit tuple and topology interface. Each route forwards
// between its front address and Server through its own connected socket, so the server
// sees a distinct source tuple per route.
type Config struct {
	Kind   Kind           `json:"kind"`
	Server netip.AddrPort `json:"server"`
	Queues []Queue        `json:"queues"`
	Routes []Route        `json:"routes"`
}

// explicitUnicast4 reports whether a names one IPv4 unicast endpoint: not IPv6 or
// IPv4-mapped IPv6, the unspecified wildcard, a multicast group or the limited
// broadcast address. netip owns the address syntax and classification. Subnet-directed
// broadcast addresses need interface knowledge and are outside this check; the
// relay's bind still has to realize the exact requested address.
func explicitUnicast4(a netip.Addr) bool {
	return a.Is4() && !a.IsUnspecified() && !a.IsMulticast() && a != netip.AddrFrom4([4]byte{255, 255, 255, 255})
}

// routeNames returns the routes kind requires, in their canonical order.
func (k Kind) routeNames() ([]RouteName, int, error) {
	switch k {
	case KindDisjoint, KindUnequal:
		return []RouteName{RouteA, RouteB}, 2, nil
	case KindShared:
		return []RouteName{RouteA, RouteB, RouteCompetitor}, 1, nil
	}
	return nil, 0, fmt.Errorf("unknown topology kind %q", k)
}

// Validate reports whether c is one of the three closed topologies with explicit IPv4
// tuples and in-range queues and delays.
func (c Config) Validate() error {
	names, queueCount, err := c.Kind.routeNames()
	if err != nil {
		return err
	}
	if !explicitUnicast4(c.Server.Addr()) || c.Server.Port() == 0 {
		return fmt.Errorf("server %q must be an explicit IPv4 unicast address and port", c.Server)
	}
	if len(c.Queues) != queueCount {
		return fmt.Errorf("%s topology needs %d queues, got %d", c.Kind, queueCount, len(c.Queues))
	}
	for i, q := range c.Queues {
		if q.RateBPS < MinRateBPS || q.RateBPS > MaxRateBPS {
			return fmt.Errorf("queue %d rate %d bit/s is outside [%d, %d]", i, q.RateBPS, MinRateBPS, MaxRateBPS)
		}
		if q.LimitBytes < MinLimitBytes || q.LimitBytes > MaxLimitBytes {
			return fmt.Errorf("queue %d limit %d bytes is outside [%d, %d]", i, q.LimitBytes, MinLimitBytes, MaxLimitBytes)
		}
	}
	got := make([]RouteName, len(c.Routes))
	for i, r := range c.Routes {
		got[i] = r.Name
	}
	if !slices.Equal(got, names) {
		return fmt.Errorf("%s topology needs routes %v in that order, got %v", c.Kind, names, got)
	}
	fronts := make(map[netip.AddrPort]bool)
	for _, r := range c.Routes {
		if !explicitUnicast4(r.Front.Addr()) {
			return fmt.Errorf("route %s front %q must be an explicit IPv4 unicast address", r.Name, r.Front)
		}
		if r.Front == c.Server {
			return fmt.Errorf("route %s front is the server address %s", r.Name, c.Server)
		}
		if r.Front.Port() != 0 {
			if fronts[r.Front] {
				return fmt.Errorf("route %s has a duplicate front %s", r.Name, r.Front)
			}
			fronts[r.Front] = true
		}
		if r.Queue < 0 || r.Queue >= len(c.Queues) {
			return fmt.Errorf("route %s names queue %d of %d", r.Name, r.Queue, len(c.Queues))
		}
		if r.DelayNS < 0 || r.DelayNS > int64(MaxDelay) {
			return fmt.Errorf("route %s delay %v is outside [0, %v]", r.Name, time.Duration(r.DelayNS), MaxDelay)
		}
	}
	a, b := c.Routes[0], c.Routes[1]
	switch c.Kind {
	case KindDisjoint:
		if a.Queue == b.Queue {
			return errors.New("disjoint routes need separate queues")
		}
		if c.Queues[a.Queue] != c.Queues[b.Queue] || a.DelayNS != b.DelayNS {
			return errors.New("disjoint routes need identical queues and delays; use the unequal topology")
		}
	case KindUnequal:
		if a.Queue == b.Queue {
			return errors.New("unequal routes need separate queues")
		}
		if c.Queues[a.Queue].RateBPS == c.Queues[b.Queue].RateBPS && a.DelayNS == b.DelayNS {
			return errors.New("unequal routes need rates or delays that differ")
		}
	case KindShared:
		// Every route names queue 0, the only one.
	}
	return nil
}

type routePlan struct {
	name  RouteName
	queue *queue
	delay time.Duration
}

// topology binds each route to its queue owner. Routes that name the same queue index
// share one *queue.
type topology struct {
	routes []routePlan
}

func newTopology(c Config) (*topology, error) {
	if err := c.Validate(); err != nil {
		return nil, err
	}
	queues := make([]*queue, len(c.Queues))
	for i, q := range c.Queues {
		queues[i] = newQueue(q)
	}
	t := &topology{}
	for _, r := range c.Routes {
		t.routes = append(t.routes, routePlan{name: r.Name, queue: queues[r.Queue], delay: time.Duration(r.DelayNS)})
	}
	return t, nil
}

func (t *topology) route(name RouteName) *routePlan {
	for i := range t.routes {
		if t.routes[i].name == name {
			return &t.routes[i]
		}
	}
	return nil
}

// schedule admits a client-to-server datagram of size payload bytes arriving at now and
// returns when it should be delivered, or false when its queue drops it.
func (r *routePlan) schedule(now time.Time, size int) (time.Time, bool) {
	leaves, ok := r.queue.admit(now, size)
	if !ok {
		return time.Time{}, false
	}
	return leaves.Add(r.delay), true
}
