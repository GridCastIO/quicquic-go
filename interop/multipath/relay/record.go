package relay

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/bits"
	"net/netip"
	"time"
)

// RecordVersion is the version of Record this package writes and reads.
const RecordVersion = 1

// Direction counts one direction of one route. Every received datagram ends in exactly
// one of Dropped, Overflow, Delivered, SendErrors or Abandoned.
type Direction struct {
	Received      uint64 `json:"received"`
	ReceivedBytes uint64 `json:"received_bytes"`
	// Dropped datagrams would have pushed the queue's backlog past its limit. Only the
	// client-to-server direction passes through a queue.
	Dropped uint64 `json:"dropped"`
	// Overflow datagrams found the route's bounded delivery backlog full. They are
	// refused before the queue, take no queue service and are not queue drops.
	Overflow       uint64 `json:"overflow"`
	Delivered      uint64 `json:"delivered"`
	DeliveredBytes uint64 `json:"delivered_bytes"`
	SendErrors     uint64 `json:"send_errors"`
	// Abandoned datagrams were still waiting for delivery when the relay closed.
	Abandoned uint64 `json:"abandoned"`
	// ReadErrors are socket read errors other than close; the reader continues.
	ReadErrors uint64 `json:"read_errors"`
	// LateOver1ms and MaxLateNS describe how far actual sends trailed their schedule.
	LateOver1ms uint64 `json:"late_over_1ms"`
	MaxLateNS   int64  `json:"max_late_ns"`
}

// RouteRecord is the realized record of one route.
type RouteRecord struct {
	Name RouteName `json:"name"`
	// Front is the bound client-facing address; Back is the local address of the
	// route's socket connected to the server.
	Front   netip.AddrPort `json:"front"`
	Back    netip.AddrPort `json:"back"`
	Queue   int            `json:"queue"`
	DelayNS int64          `json:"delay_ns"`
	// Forward is client to server; Reverse is server to client.
	Forward Direction `json:"forward"`
	Reverse Direction `json:"reverse"`
}

// Record is the relay's realized delivery record, written once after every worker has
// been joined. Its Config is the requested configuration.
type Record struct {
	Version int           `json:"version"`
	Go      string        `json:"go"`
	GOOS    string        `json:"goos"`
	GOARCH  string        `json:"goarch"`
	Config  Config        `json:"config"`
	Routes  []RouteRecord `json:"routes"`
}

// fitsDatagrams reports whether bytes can be the payload total of n datagrams.
func fitsDatagrams(bytes, n uint64) bool {
	hi, lo := bits.Mul64(n, maxIPv4UDPPayload)
	return hi != 0 || bytes <= lo
}

// validate applies the record's declared direction checks: every received datagram
// has exactly one outcome, byte totals fit the IPv4 UDP payload bound of their datagram
// counts, and lateness describes only sends. They do not prove that a relay run
// produced d.
func (d Direction) validate(queued bool) error {
	remaining := d.Received
	for _, n := range []uint64{d.Dropped, d.Overflow, d.Delivered, d.SendErrors, d.Abandoned} {
		if n > remaining {
			return fmt.Errorf("%d datagrams received but more accounted for", d.Received)
		}
		remaining -= n
	}
	if remaining != 0 {
		return fmt.Errorf("%d datagrams received but %d unaccounted for", d.Received, remaining)
	}
	if !queued && d.Dropped != 0 {
		return errors.New("a direction without a queue cannot drop")
	}
	if d.DeliveredBytes > d.ReceivedBytes {
		return fmt.Errorf("%d bytes delivered but only %d received", d.DeliveredBytes, d.ReceivedBytes)
	}
	if !fitsDatagrams(d.DeliveredBytes, d.Delivered) || !fitsDatagrams(d.ReceivedBytes-d.DeliveredBytes, d.Received-d.Delivered) {
		return fmt.Errorf("byte totals %d received and %d delivered do not fit %d received and %d delivered datagrams",
			d.ReceivedBytes, d.DeliveredBytes, d.Received, d.Delivered)
	}
	sends := d.Delivered + d.SendErrors
	if d.LateOver1ms > sends || d.MaxLateNS < 0 || (sends == 0 && d.MaxLateNS != 0) ||
		(d.LateOver1ms > 0) != (d.MaxLateNS > int64(time.Millisecond)) {
		return fmt.Errorf("lateness (%d over 1 ms, max %d ns) does not describe %d sends", d.LateOver1ms, d.MaxLateNS, sends)
	}
	return nil
}

// Validate reports whether rec is a complete version-1 record of its configuration.
func (rec Record) Validate() error {
	if rec.Version != RecordVersion {
		return fmt.Errorf("record version %d, want %d", rec.Version, RecordVersion)
	}
	if rec.Go == "" || rec.GOOS == "" || rec.GOARCH == "" {
		return errors.New("record lacks its toolchain and platform identity")
	}
	if err := rec.Config.Validate(); err != nil {
		return fmt.Errorf("record config: %w", err)
	}
	if len(rec.Routes) != len(rec.Config.Routes) {
		return fmt.Errorf("record has %d routes, config has %d", len(rec.Routes), len(rec.Config.Routes))
	}
	for i, r := range rec.Routes {
		want := rec.Config.Routes[i]
		if r.Name != want.Name || r.Queue != want.Queue || r.DelayNS != want.DelayNS {
			return fmt.Errorf("record route %d (%s) does not match its configuration", i, r.Name)
		}
	}
	if err := validateEndpoints(rec.Config, rec.Routes); err != nil {
		return err
	}
	for _, r := range rec.Routes {
		if err := r.Forward.validate(true); err != nil {
			return fmt.Errorf("route %s forward: %w", r.Name, err)
		}
		if err := r.Reverse.validate(false); err != nil {
			return fmt.Errorf("route %s reverse: %w", r.Name, err)
		}
		// A reply is delivered only to a client that has sent on the route; without
		// one, the reply is a send error.
		if r.Reverse.Delivered > 0 && r.Forward.Received == 0 {
			return fmt.Errorf("route %s delivered replies without a client", r.Name)
		}
	}
	return nil
}

// validateEndpoints is the one rule for realized socket identities, applied by Start
// before readiness and by Record.Validate. Each route's front is bound exactly as cfg
// requested, each back is an explicit IPv4 unicast endpoint, and all fronts, backs and
// the server are distinct tuples. A platform can bind some requested addresses
// differently, and a port-zero socket can land on the server's port while the server
// is unbound. routes must name cfg's routes in order.
func validateEndpoints(cfg Config, routes []RouteRecord) error {
	seen := map[netip.AddrPort]string{cfg.Server: "the server"}
	for i, r := range routes {
		want := cfg.Routes[i].Front
		if r.Front.Port() == 0 || r.Front.Addr() != want.Addr() || (want.Port() != 0 && r.Front.Port() != want.Port()) {
			return fmt.Errorf("route %s front %s was bound as %s", r.Name, want, r.Front)
		}
		if !explicitUnicast4(r.Back.Addr()) || r.Back.Port() == 0 {
			return fmt.Errorf("route %s back socket was bound as %s", r.Name, r.Back)
		}
		for _, e := range []struct {
			name string
			addr netip.AddrPort
		}{{"front", r.Front}, {"back", r.Back}} {
			if other, ok := seen[e.addr]; ok {
				return fmt.Errorf("route %s %s %s is also %s", r.Name, e.name, e.addr, other)
			}
			seen[e.addr] = fmt.Sprintf("route %s's %s", r.Name, e.name)
		}
	}
	return nil
}

// ReadRecord decodes exactly one record and validates it. Unknown fields, trailing
// data and incomplete accounting are errors.
func ReadRecord(r io.Reader) (Record, error) {
	dec := json.NewDecoder(r)
	dec.DisallowUnknownFields()
	var rec Record
	if err := dec.Decode(&rec); err != nil {
		return Record{}, fmt.Errorf("decoding relay record: %w", err)
	}
	if _, err := dec.Token(); !errors.Is(err, io.EOF) {
		return Record{}, errors.New("decoding relay record: trailing data")
	}
	if err := rec.Validate(); err != nil {
		return Record{}, err
	}
	return rec, nil
}

// WriteRecord validates rec and writes it as indented JSON.
func WriteRecord(w io.Writer, rec Record) error {
	if err := rec.Validate(); err != nil {
		return err
	}
	b, err := json.MarshalIndent(rec, "", "  ")
	if err != nil {
		return err
	}
	_, err = io.Copy(w, bytes.NewReader(append(b, '\n')))
	return err
}
