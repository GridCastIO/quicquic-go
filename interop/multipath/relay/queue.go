package relay

import (
	"math/bits"
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
//
// The backlog is kept exactly, in bits scaled by one second in nanoseconds, so the
// remaining service time at the reference instant is backlog/rate nanoseconds. The
// limit compares exact charged bits; only the returned departure time is rounded.
type queue struct {
	rate  uint64
	limit uint64 // LimitBytes in the backlog's units

	mu      sync.Mutex
	at      time.Time // reference instant of backlog
	backlog uint64
}

// newQueue expects a validated Queue, whose bounds keep this arithmetic in range.
func newQueue(q Queue) *queue {
	return &queue{rate: q.RateBPS, limit: scaledBits(q.LimitBytes)}
}

func scaledBits(bytes uint64) uint64 {
	return bytes * 8 * uint64(time.Second)
}

// admit returns when a datagram of size payload bytes arriving at now finishes service,
// or false when its charge would push the backlog past the queue's limit.
func (q *queue) admit(now time.Time, size int) (time.Time, bool) {
	charge := scaledBits(uint64(size) + ipv4UDPOverhead)
	q.mu.Lock()
	defer q.mu.Unlock()
	if d := now.Sub(q.at); d > 0 {
		// Service drains rate scaled units per nanosecond.
		if elapsed := uint64(d); elapsed > q.backlog/q.rate {
			q.backlog = 0
		} else {
			q.backlog -= elapsed * q.rate
		}
		q.at = now
	}
	// Readers sharing a queue can arrive with now slightly behind the reference
	// instant; the backlog they see includes service not yet drained at now.
	ahead := q.backlog
	if d := q.at.Sub(now); d > 0 {
		hi, lo := bits.Mul64(uint64(d), q.rate)
		sum, carry := bits.Add64(lo, ahead, 0)
		if hi != 0 || carry != 0 {
			return time.Time{}, false
		}
		ahead = sum
	}
	if ahead > q.limit || charge > q.limit-ahead {
		return time.Time{}, false
	}
	q.backlog += charge
	return q.at.Add(time.Duration(q.backlog / q.rate)), true
}
