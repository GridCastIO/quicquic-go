package relay

import (
	"sync"
	"time"
)

// ipv4UDPOverhead is charged with each datagram, so a queue's rate is an IPv4 rate.
const ipv4UDPOverhead = 28

// Queue is one bottleneck: an IPv4 rate in bits per second and a drop-tail backlog
// limit in bytes, both counting 28 bytes of IP and UDP headers per datagram.
type Queue struct {
	RateBPS    uint64 `json:"rate_bps"`
	LimitBytes uint64 `json:"limit_bytes"`
}

// queue is the single owner of one bottleneck's backlog. Every route that names the
// queue admits through it, so a shared queue's routes compete for the same backlog.
type queue struct {
	rate  uint64
	limit time.Duration

	mu   sync.Mutex
	busy time.Time // when the last admitted datagram finishes service
}

// newQueue expects a validated Queue, whose bounds keep this arithmetic in range.
func newQueue(q Queue) *queue {
	return &queue{rate: q.RateBPS, limit: serviceTime(q.LimitBytes, q.RateBPS)}
}

func serviceTime(bytes, rateBPS uint64) time.Duration {
	return time.Duration(bytes * 8 * uint64(time.Second) / rateBPS)
}

// admit returns when a datagram of size payload bytes arriving at now finishes service,
// or false when its service would push the backlog past the queue's limit.
func (q *queue) admit(now time.Time, size int) (time.Time, bool) {
	service := serviceTime(uint64(size)+ipv4UDPOverhead, q.rate)
	q.mu.Lock()
	defer q.mu.Unlock()
	if q.busy.Before(now) {
		q.busy = now
	}
	if q.busy.Sub(now)+service > q.limit {
		return time.Time{}, false
	}
	q.busy = q.busy.Add(service)
	return q.busy, true
}
