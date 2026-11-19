// Package relay is a userspace UDP relay that places explicit client-facing routes in
// front of one server and shapes them as one of three closed topologies: two disjoint
// equal routes, two disjoint unequal routes, or two routes and a competitor through
// one shared bottleneck.
//
// It is maintained multipath test infrastructure, the successor to the queue design of
// the archived B11 comparison (8c34fbac874adf55f096b6c67d51244160169422). The relay
// owns its queues only; the transport under test keeps its own pacing and congestion
// decisions. It needs no privileges and changes no host network configuration. It
// forwards UDP payloads only, so ECN marks and other IP metadata are not carried. Its
// tests demonstrate queue, routing, accounting and cleanup semantics, not timing
// fidelity at measurement load.
package relay

import (
	"errors"
	"fmt"
	"net"
	"net/netip"
	"runtime"
	"slices"
	"sync"
	"sync/atomic"
	"time"
)

const (
	// backlogPackets bounds each direction's datagrams awaiting delivery, as in B11. It
	// is a memory bound, not part of the topology: a nonzero Overflow in a record means
	// the offered traffic exceeded it.
	backlogPackets = 1 << 16
	socketBuffer   = 2 << 20
	maxDatagram    = 1<<16 - 1
)

type packet struct {
	due  time.Time
	data []byte
}

// link forwards one route: front faces the client, back is connected to the server.
type link struct {
	plan        routePlan
	front, back *net.UDPConn
	frontAddr   netip.AddrPort
	backAddr    netip.AddrPort
	// client is the latest source seen on front; replies go there.
	client           atomic.Pointer[netip.AddrPort]
	forward, reverse chan packet

	mu           sync.Mutex
	forwardStats Direction
	reverseStats Direction
}

// Relay is a running relay. Close it to join its workers and obtain its record.
type Relay struct {
	cfg        Config
	links      []*link
	stopping   chan struct{}
	readers    sync.WaitGroup
	deliverers sync.WaitGroup

	closeMu sync.Mutex
	closed  bool
}

func unmapped(ap netip.AddrPort) netip.AddrPort {
	return netip.AddrPortFrom(ap.Addr().Unmap(), ap.Port())
}

func openLink(plan routePlan, front, server netip.AddrPort) (*link, error) {
	l := &link{
		plan:    plan,
		forward: make(chan packet, backlogPackets),
		reverse: make(chan packet, backlogPackets),
	}
	var err error
	if l.front, err = net.ListenUDP("udp4", net.UDPAddrFromAddrPort(front)); err != nil {
		return nil, err
	}
	if l.back, err = net.DialUDP("udp4", nil, net.UDPAddrFromAddrPort(server)); err != nil {
		l.front.Close()
		return nil, err
	}
	for _, c := range []*net.UDPConn{l.front, l.back} {
		err := c.SetReadBuffer(socketBuffer)
		if err == nil {
			err = c.SetWriteBuffer(socketBuffer)
		}
		if err != nil {
			l.closeSockets()
			return nil, err
		}
	}
	l.frontAddr = unmapped(l.front.LocalAddr().(*net.UDPAddr).AddrPort())
	l.backAddr = unmapped(l.back.LocalAddr().(*net.UDPAddr).AddrPort())
	if err := realized(front, server, l.frontAddr, l.backAddr); err != nil {
		l.closeSockets()
		return nil, err
	}
	return l, nil
}

// realized reports whether the bound sockets are the explicit endpoints the
// configuration asked for. A platform may bind some requested addresses differently,
// and a port-zero front can land on the server's port while the server is unbound.
func realized(front, server, boundFront, boundBack netip.AddrPort) error {
	if boundFront.Addr() != front.Addr() || (front.Port() != 0 && boundFront.Port() != front.Port()) {
		return fmt.Errorf("front %s was bound as %s", front, boundFront)
	}
	if boundFront == server {
		return fmt.Errorf("front was bound at the server address %s", server)
	}
	if !explicitUnicast4(boundBack.Addr()) {
		return fmt.Errorf("back socket was bound as %s", boundBack)
	}
	return nil
}

func (l *link) closeSockets() {
	l.front.Close()
	l.back.Close()
}

// Start validates cfg, binds every route's sockets and starts forwarding. On error it
// has released every socket it opened.
func Start(cfg Config) (*Relay, error) {
	top, err := newTopology(cfg)
	if err != nil {
		return nil, err
	}
	r := &Relay{cfg: cfg, stopping: make(chan struct{})}
	r.cfg.Queues = slices.Clone(cfg.Queues)
	r.cfg.Routes = slices.Clone(cfg.Routes)
	for i, route := range cfg.Routes {
		l, err := openLink(top.routes[i], route.Front, cfg.Server)
		if err != nil {
			for _, opened := range r.links {
				opened.closeSockets()
			}
			return nil, fmt.Errorf("route %s: %w", route.Name, err)
		}
		r.links = append(r.links, l)
	}
	for _, l := range r.links {
		r.readers.Add(2)
		r.deliverers.Add(2)
		go r.readForward(l)
		go r.readReverse(l)
		go r.deliver(l, l.forward, &l.forwardStats, func(b []byte) error {
			_, err := l.back.Write(b)
			return err
		})
		go r.deliver(l, l.reverse, &l.reverseStats, func(b []byte) error {
			client := l.client.Load()
			if client == nil {
				return errors.New("no client has sent on this route")
			}
			_, err := l.front.WriteToUDPAddrPort(b, *client)
			return err
		})
	}
	return r, nil
}

// Fronts returns each route's bound client-facing address.
func (r *Relay) Fronts() map[RouteName]netip.AddrPort {
	m := make(map[RouteName]netip.AddrPort, len(r.links))
	for _, l := range r.links {
		m[l.plan.name] = l.frontAddr
	}
	return m
}

func (r *Relay) readForward(l *link) {
	defer r.readers.Done()
	buf := make([]byte, maxDatagram)
	for {
		n, from, err := l.front.ReadFromUDPAddrPort(buf)
		if err != nil {
			if errors.Is(err, net.ErrClosed) {
				return
			}
			l.mu.Lock()
			l.forwardStats.ReadErrors++
			l.mu.Unlock()
			continue
		}
		now := time.Now()
		from = unmapped(from)
		l.client.Store(&from)
		l.acceptForward(now, buf[:n])
	}
}

func (r *Relay) readReverse(l *link) {
	defer r.readers.Done()
	buf := make([]byte, maxDatagram)
	for {
		n, err := l.back.Read(buf)
		if err != nil {
			if errors.Is(err, net.ErrClosed) {
				return
			}
			// A connected socket reports an earlier ICMP error, for example while the
			// server is not yet listening.
			l.mu.Lock()
			l.reverseStats.ReadErrors++
			l.mu.Unlock()
			continue
		}
		l.acceptReverse(time.Now(), buf[:n])
	}
}

// receive counts a datagram and reports whether ch, which only this direction's reader
// sends on, has room for it. Because no other goroutine sends on ch, room seen here is
// still there when the reader sends. A full backlog is the relay's memory bound, not a
// queue decision, and is counted as Overflow.
func (l *link) receive(ch chan packet, stats *Direction, size int) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	stats.Received++
	stats.ReceivedBytes += uint64(size)
	if len(ch) == cap(ch) {
		stats.Overflow++
		return false
	}
	return true
}

// acceptForward handles one client-to-server datagram arriving at now. The backlog is
// checked before the queue, so an overflowed datagram takes no queue service and the
// queue alone decides every admission and drop it charges.
func (l *link) acceptForward(now time.Time, data []byte) {
	if !l.receive(l.forward, &l.forwardStats, len(data)) {
		return
	}
	due, ok := l.plan.schedule(now, len(data))
	if !ok {
		l.mu.Lock()
		l.forwardStats.Dropped++
		l.mu.Unlock()
		return
	}
	l.forward <- packet{due: due, data: slices.Clone(data)}
}

// acceptReverse handles one server-to-client datagram arriving at now; it is delayed but
// not queued.
func (l *link) acceptReverse(now time.Time, data []byte) {
	if l.receive(l.reverse, &l.reverseStats, len(data)) {
		l.reverse <- packet{due: now.Add(l.plan.delay), data: slices.Clone(data)}
	}
}

// deliver sends each packet at its due time. A direction's packets arrive in due
// order: its queue's departures are monotonic and its delay is constant. After Close
// begins, waiting packets are abandoned rather than sent.
func (r *Relay) deliver(l *link, ch <-chan packet, stats *Direction, send func([]byte) error) {
	defer r.deliverers.Done()
	timer := time.NewTimer(time.Hour)
	timer.Stop()
	abandon := func() {
		l.mu.Lock()
		stats.Abandoned++
		l.mu.Unlock()
	}
	for p := range ch {
		if wait := time.Until(p.due); wait > 0 {
			timer.Reset(wait)
			select {
			case <-timer.C:
			case <-r.stopping:
				timer.Stop()
				abandon()
				continue
			}
		}
		select {
		case <-r.stopping:
			abandon()
			continue
		default:
		}
		late := time.Since(p.due)
		err := send(p.data)
		if errors.Is(err, net.ErrClosed) {
			abandon() // Close won the race with this send.
			continue
		}
		l.mu.Lock()
		if err != nil {
			stats.SendErrors++
		} else {
			stats.Delivered++
			stats.DeliveredBytes += uint64(len(p.data))
		}
		if late > time.Millisecond {
			stats.LateOver1ms++
		}
		if late > time.Duration(stats.MaxLateNS) {
			stats.MaxLateNS = int64(late)
		}
		l.mu.Unlock()
	}
}

// Snapshot returns each route's counts so far. Until Close, datagrams awaiting delivery
// are not yet accounted for, so a snapshot is not a record.
func (r *Relay) Snapshot() []RouteRecord {
	routes := make([]RouteRecord, len(r.links))
	for i, l := range r.links {
		l.mu.Lock()
		routes[i] = RouteRecord{
			Name: l.plan.name, Front: l.frontAddr, Back: l.backAddr,
			Queue: r.cfg.Routes[i].Queue, DelayNS: r.cfg.Routes[i].DelayNS,
			Forward: l.forwardStats, Reverse: l.reverseStats,
		}
		l.mu.Unlock()
	}
	return routes
}

// Close stops the relay and returns its record. It closes every socket, joins the
// readers, closes the delivery backlogs and joins the deliverers before reading the
// counts, so the record accounts for every datagram the relay received. Datagrams
// still awaiting delivery are abandoned. A second Close returns net.ErrClosed.
func (r *Relay) Close() (Record, error) {
	r.closeMu.Lock()
	if r.closed {
		r.closeMu.Unlock()
		return Record{}, fmt.Errorf("relay: %w", net.ErrClosed)
	}
	r.closed = true
	r.closeMu.Unlock()

	close(r.stopping)
	for _, l := range r.links {
		l.closeSockets()
	}
	r.readers.Wait()
	for _, l := range r.links {
		close(l.forward)
		close(l.reverse)
	}
	r.deliverers.Wait()
	rec := Record{
		Version: RecordVersion,
		Go:      runtime.Version(),
		GOOS:    runtime.GOOS,
		GOARCH:  runtime.GOARCH,
		Config:  r.cfg,
		Routes:  r.Snapshot(),
	}
	return rec, rec.Validate()
}
