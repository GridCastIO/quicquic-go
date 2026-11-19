//go:build picoquic

package quic

import (
	"testing"

	"github.com/stretchr/testify/require"
)

// These fixture-semantic cases exercise the aggregate DATAGRAM ingress
// witness's accounting with recorded peer receipts. They make no live
// scheduling or platform claim.
func TestPicoquicMatrixIngressWitness(t *testing.T) {
	nonce := [8]byte{1, 2, 3, 4, 5, 6, 7, 8}
	record := func(path uint64, payload []byte) string { return matrixIngressRecordLine(path, payload) }
	echo := record(0, []byte{0, 'R', '1', '7', 0, 'R', '1', '7', 0, 'R', '1', '7', 0, 'R', '1', '7', 0})
	both := map[uint64]uint64{0: 64, 1: 64}

	// phase builds a witness whose receipt cursor starts after the given
	// pre-activation records and offers two rounds of two payloads.
	phase := func(pre int, eligible ...bool) (*matrixIngressWitness, [][]byte) {
		w := newMatrixIngressWitness(nonce, pre, 2)
		var offered [][]byte
		for _, ok := range eligible[:len(eligible)-1] {
			offered = append(offered, w.offerRound(ok)...)
		}
		w.finish(eligible[len(eligible)-1])
		return w, offered
	}

	t.Run("fresh matching receipts on both paths pass", func(t *testing.T) {
		w, offered := phase(1, true, true, true)
		result, err := w.accept([]string{echo, record(0, offered[0]), record(1, offered[1]), record(1, offered[3])}, both)
		require.NoError(t, err)
		require.Equal(t, map[uint64]int{0: 1, 1: 2}, result.Fresh)
		require.Equal(t, 1, result.Excluded, "the pre-activation echo is not a receipt")
		require.Equal(t, both, result.SenderDelta)
	})

	t.Run("pre-activation and wrong-phase receipts fail", func(t *testing.T) {
		stale := newMatrixIngressWitness([8]byte{9}, 0, 2).offerRound(true)
		w, offered := phase(2, true, true, true)
		// Member payloads read before the activation cursor, an earlier phase's
		// nonce and an echo payload all fail to count.
		_, err := w.accept([]string{record(0, offered[0]), record(1, offered[1]), record(0, stale[0]), record(1, stale[1]), echo}, both)
		require.ErrorContains(t, err, "no fresh receipt on path 0")

		for name, eligible := range map[string][]bool{
			"path inactive in an offer round": {true, false, true},
			"path inactive at phase end":      {true, true, false},
		} {
			t.Run(name, func(t *testing.T) {
				w, offered := phase(0, eligible...)
				_, err := w.accept([]string{record(0, offered[0]), record(1, offered[1]), record(0, offered[2]), record(1, offered[3])}, both)
				require.ErrorContains(t, err, "live/active")
			})
		}
	})

	t.Run("duplicates do not count as new receipts", func(t *testing.T) {
		w, offered := phase(0, true, true, true)
		result, err := w.accept([]string{record(0, offered[0]), record(0, offered[0]), record(1, offered[0])}, both)
		require.ErrorContains(t, err, "no fresh receipt on path 1")
		require.Equal(t, 2, result.Duplicates)
	})

	t.Run("one-path-only delivery fails", func(t *testing.T) {
		w, offered := phase(0, true, true, true)
		_, err := w.accept([]string{record(0, offered[0]), record(0, offered[1]), record(0, offered[2]), record(0, offered[3])}, both)
		require.ErrorContains(t, err, "no fresh receipt on path 1")
	})

	t.Run("sender-only progress fails", func(t *testing.T) {
		w, _ := phase(1, true, true, true)
		result, err := w.accept([]string{echo}, both)
		require.ErrorContains(t, err, "no fresh receipt on path 0")
		require.Equal(t, both, result.SenderDelta, "sender deltas stay scheduling evidence")
	})
}

// The witness reads only the explicitly emitted record shape. Unknown or
// malformed records fail rather than count as evidence.
func TestPicoquicMatrixIngressRecord(t *testing.T) {
	payload := []byte("W0123456789abcdefghij")
	line := matrixIngressRecordLine(1, payload)
	require.Equal(t, "ingress v1 datagram path 1 length 21 head 57303132333435363738396162636465", line)
	receipt, err := parseMatrixIngressRecord(line)
	require.NoError(t, err)
	require.Equal(t, matrixIngressReceipt{Path: 1, Length: 21, Head: payload[:16]}, receipt)
	short, err := parseMatrixIngressRecord("ingress v1 datagram path 0 length 2 head 0052")
	require.NoError(t, err)
	require.Equal(t, []byte{0, 'R'}, short.Head)

	for _, malformed := range []string{
		"ingress v2 datagram path 1 length 21 head 57",
		"ingress v1 stream path 1 length 21 head 57",
		"ingress v1 datagram path 1 length 21",
		"ingress v1 datagram path -1 length 2 head 0052",
		"ingress v1 datagram path 1 length 0 head 00",
		"ingress v1 datagram path 1 length 2 head zz52",
		"ingress v1 datagram path 1 length 3 head 0052",
		"ingress v1 datagram path 1 length 2 head 0052 extra",
	} {
		_, err := parseMatrixIngressRecord(malformed)
		require.Error(t, err, malformed)
	}
	w := newMatrixIngressWitness([8]byte{}, 0, 1)
	w.offerRound(true)
	w.finish(true)
	_, err = w.accept([]string{"ingress v1 datagram path 1 length 2 head 0052 extra"}, nil)
	require.ErrorContains(t, err, "record 0")
	// A current-nonce payload that this phase never offered is not evidence.
	other := newMatrixIngressWitness([8]byte{}, 0, 2)
	unoffered := other.offerRound(true)[1]
	_, err = w.accept([]string{matrixIngressRecordLine(0, unoffered)}, nil)
	require.ErrorContains(t, err, "never offered")
}
