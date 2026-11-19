package relay

import (
	"bytes"
	"encoding/json"
	"math"
	"net/netip"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

func testRecord() Record {
	cfg := testConfig(KindShared)
	rec := Record{Version: RecordVersion, Go: "go1.27.4", GOOS: "darwin", GOARCH: "arm64", Config: cfg}
	for i, r := range cfg.Routes {
		rec.Routes = append(rec.Routes, RouteRecord{
			Name:    r.Name,
			Front:   netip.AddrPortFrom(r.Front.Addr(), uint16(5000+i)),
			Back:    netip.AddrPortFrom(r.Front.Addr(), uint16(6000+i)),
			Queue:   r.Queue,
			DelayNS: r.DelayNS,
			Forward: Direction{Received: 10, ReceivedBytes: 10_000, Dropped: 2, Overflow: 1, Delivered: 5, DeliveredBytes: 5_000, SendErrors: 1, Abandoned: 1},
			Reverse: Direction{Received: 4, ReceivedBytes: 400, Delivered: 4, DeliveredBytes: 400},
		})
	}
	return rec
}

func TestRecordReadback(t *testing.T) {
	var buf bytes.Buffer
	require.NoError(t, WriteRecord(&buf, testRecord()))
	rec, err := ReadRecord(bytes.NewReader(buf.Bytes()))
	require.NoError(t, err)
	require.Equal(t, testRecord(), rec)

	// Empty datagrams, idle directions and timely sends are records a relay can write.
	idle := testRecord()
	idle.Routes[1].Forward = Direction{Received: 2, Delivered: 2, LateOver1ms: 1, MaxLateNS: int64(2 * time.Millisecond)}
	idle.Routes[1].Reverse = Direction{}
	require.NoError(t, idle.Validate())

	encode := func(rec Record) string {
		b, err := json.Marshal(rec)
		require.NoError(t, err)
		return string(b)
	}
	for _, tc := range []struct {
		name string
		raw  string
		want string
	}{
		{"malformed", `{"version":1,`, "decoding"},
		{"unknown field", strings.Replace(encode(testRecord()), `"version":1`, `"version":1,"extra":true`, 1), "unknown field"},
		{"trailing data", encode(testRecord()) + "{}", "trailing data"},
		{"invalid address", strings.Replace(encode(testRecord()), `"127.0.0.1:5000"`, `"127.0.0.1:x"`, 1), "decoding"},
		{"wrong version", encode(func() Record { r := testRecord(); r.Version = 2; return r }()), "version"},
		{"missing identity", encode(func() Record { r := testRecord(); r.GOOS = ""; return r }()), "identity"},
		{"invalid config", encode(func() Record { r := testRecord(); r.Config.Kind = "mesh"; return r }()), "config"},
		{"missing route", encode(func() Record { r := testRecord(); r.Routes = r.Routes[:2]; return r }()), "routes"},
		{"route mismatch", encode(func() Record { r := testRecord(); r.Routes[1].DelayNS++; return r }()), "does not match"},
		{"unrealized front", encode(func() Record { r := testRecord(); r.Routes[0].Front = netip.MustParseAddrPort("127.0.0.1:0"); return r }()), "front"},
		{"missing back", encode(func() Record { r := testRecord(); r.Routes[0].Back = netip.AddrPort{}; return r }()), "back"},
		{"unaccounted datagram", encode(func() Record { r := testRecord(); r.Routes[0].Forward.Received++; return r }()), "accounted"},
		{"bytes from nowhere", encode(func() Record { r := testRecord(); r.Routes[0].Reverse.DeliveredBytes = 401; return r }()), "bytes"},
		{"wrapped outcomes", encode(func() Record {
			r := testRecord()
			r.Routes[0].Forward = Direction{Dropped: math.MaxUint64, Overflow: 1}
			return r
		}()), "more accounted"},
		{"delivered bytes without a delivery", encode(func() Record {
			r := testRecord()
			r.Routes[0].Reverse = Direction{Received: 1, ReceivedBytes: 400, Abandoned: 1, DeliveredBytes: 400}
			return r
		}()), "do not fit"},
		{"all delivered with fewer bytes", encode(func() Record { r := testRecord(); r.Routes[0].Reverse.DeliveredBytes = 399; return r }()), "do not fit"},
		{"bytes beyond the datagram size", encode(func() Record {
			r := testRecord()
			r.Routes[0].Reverse = Direction{Received: 1, ReceivedBytes: 1 << 16, Delivered: 1, DeliveredBytes: 1 << 16}
			return r
		}()), "do not fit"},
		{"lateness without a send", encode(func() Record {
			r := testRecord()
			r.Routes[2].Forward = Direction{Received: 1, ReceivedBytes: 1, Dropped: 1, MaxLateNS: 5}
			return r
		}()), "lateness"},
		{"more late sends than sends", encode(func() Record {
			r := testRecord()
			r.Routes[0].Reverse.LateOver1ms, r.Routes[0].Reverse.MaxLateNS = 5, int64(2*time.Millisecond)
			return r
		}()), "lateness"},
		{"late count without a late maximum", encode(func() Record { r := testRecord(); r.Routes[0].Reverse.LateOver1ms = 1; return r }()), "lateness"},
		{"duplicate fronts", encode(func() Record { r := testRecord(); r.Routes[1].Front = r.Routes[0].Front; return r }()), "reuses"},
		{"front reused as a back", encode(func() Record { r := testRecord(); r.Routes[1].Back = r.Routes[0].Front; return r }()), "reuses"},
		{"wildcard back", encode(func() Record { r := testRecord(); r.Routes[0].Back = netip.MustParseAddrPort("0.0.0.0:6000"); return r }()), "back socket"},
		{"front at the server", encode(func() Record { r := testRecord(); r.Routes[0].Front = r.Config.Server; return r }()), "server"},
		{"replies without a client", encode(func() Record {
			r := testRecord()
			r.Routes[0].Forward = Direction{}
			return r
		}()), "without a client"},
		{"reply send errors without a client are valid", encode(func() Record {
			r := testRecord()
			r.Routes[0].Forward = Direction{}
			r.Routes[0].Reverse = Direction{Received: 1, ReceivedBytes: 10, SendErrors: 1}
			return r
		}()), ""},
		{"reverse drop", encode(func() Record {
			r := testRecord()
			r.Routes[0].Reverse.Dropped, r.Routes[0].Reverse.Delivered = 1, 3
			return r
		}()), "cannot drop"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			_, err := ReadRecord(strings.NewReader(tc.raw))
			if tc.want == "" {
				require.NoError(t, err)
				return
			}
			require.ErrorContains(t, err, tc.want)
		})
	}
	require.Error(t, WriteRecord(&buf, Record{}), "an invalid record is not written")
}
