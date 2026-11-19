//go:build darwin && nativepressure

package quic

import (
	"testing"
	"time"
)

// nativeDarwinPressureLoad is the bounded offered load of the socket-pressure
// observation: every participant fills its lanes with full scalar batches.
var nativeDarwinPressureLoad = nativeDarwinLoad{
	participants: 16, requests: 64, members: endpointBatch, payload: 1200, budget: time.Second, window: 20 * time.Second,
}

// TestNativeDarwinPressure is MP-MAC E3's bounded socket-pressure observation
// mode. It builds only with the nativepressure tag, so default development tests
// never launch it; interop/multipath/native_darwin.py --profile pressure runs its
// one case. It offers the bounded load once on a real loopback socket and records
// what it observed. A pressure wait may or may not occur: an absent wait in a
// complete observation is a valid negative, an incomplete or interrupted one says
// unknown, and nothing retries. Actual pressure attempts belong to the protocol
// that Q1 binds.
func TestNativeDarwinPressure(t *testing.T) {
	nativeDarwinCase(t, "socket-pressure", func(t *testing.T, facts map[string]any) {
		observation := observeNativeDarwinLoopback(t, nativeDarwinPressureLoad)
		observation.requireSettled(t)
		observation.facts(facts)
	})
}
