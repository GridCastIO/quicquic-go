package relay

import (
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

// A queue serves bytes at its IPv4 rate, charging 28 bytes of IP and UDP headers per
// datagram, and drops a datagram whose service would push its backlog past the limit.
func TestQueueAdmission(t *testing.T) {
	q := newQueue(Queue{RateBPS: 8_000_000, LimitBytes: 3_000})
	now := time.Unix(100, 0)
	// 972 bytes plus 28 of headers take 1 ms at 8 Mbit/s.
	first, ok := q.admit(now, 972)
	require.True(t, ok)
	require.Equal(t, now.Add(time.Millisecond), first)
	second, ok := q.admit(now, 972)
	require.True(t, ok)
	require.Equal(t, now.Add(2*time.Millisecond), second, "service follows the backlog")
	third, ok := q.admit(now, 972)
	require.True(t, ok)
	require.Equal(t, now.Add(3*time.Millisecond), third, "the limit admits exactly its bytes")
	_, ok = q.admit(now, 1)
	require.False(t, ok, "past the limit, the tail drops")
	// Half of the backlog has drained 1.5 ms later, so 1,500 bytes fit again.
	mid := now.Add(1500 * time.Microsecond)
	fourth, ok := q.admit(mid, 1472)
	require.True(t, ok)
	require.Equal(t, now.Add(4500*time.Microsecond), fourth, "a drained backlog admits again")
	later := now.Add(10 * time.Millisecond)
	leaves, ok := q.admit(later, 972)
	require.True(t, ok)
	require.Equal(t, later.Add(time.Millisecond), leaves, "an idle queue starts service at arrival")
}
