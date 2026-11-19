package relay

import (
	"bytes"
	"encoding/json"
	"net/netip"
	"strings"
	"testing"

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
		{"reverse drop", encode(func() Record {
			r := testRecord()
			r.Routes[0].Reverse.Dropped, r.Routes[0].Reverse.Delivered = 1, 3
			return r
		}()), "cannot drop"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			_, err := ReadRecord(strings.NewReader(tc.raw))
			require.ErrorContains(t, err, tc.want)
		})
	}
	require.Error(t, WriteRecord(&buf, Record{}), "an invalid record is not written")
}
