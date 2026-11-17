package quic

import (
	"bytes"
	"fmt"
	"testing"

	"github.com/GridCastIO/quicquic-go/internal/protocol"
	"github.com/stretchr/testify/require"
)

// This is a stream-input loss model, not a network trace. Two frames in each
// ten-frame group arrive late. The 14.4 MB span assumes a window of at least
// that size (the upstream report used 1 GiB). Recovery is a second receive pass.
func TestFrameSorterAccumulatedLossRecovery(t *testing.T) {
	const size, count = 1200, 12000
	for _, mode := range []string{"in_order", "bounded_reordering", "delayed_recovery"} {
		t.Run(mode, func(t *testing.T) {
			s := newFrameSorter()
			releases := make([]int, count)
			submitted := make([]bool, count)
			defer func() {
				s.discard()
				s.discard()
				for i, n := range releases {
					if submitted[i] && n != 1 {
						t.Errorf("frame %d released %d times", i, n)
					}
				}
			}()
			delivered := 0
			push := func(i int) {
				submitted[i] = true
				data := bytes.Repeat([]byte{byte(i)}, size)
				err := s.Push(data, protocol.ByteCount(i*size), func() { releases[i]++ })
				require.NoError(t, err, "frame=%d offset=%d delivered=%d", i, i*size, delivered)
				for {
					offset, out, done := s.Pop()
					if out == nil {
						break
					}
					require.Equal(t, protocol.ByteCount(delivered*size), offset)
					require.Equal(t, bytes.Repeat([]byte{byte(delivered)}, size), out)
					done()
					delivered++
				}
			}
			for i := range count {
				if mode != "in_order" && i%10 < 2 {
					continue
				}
				push(i)
				if mode == "bounded_reordering" && i%10 == 9 {
					push(i - 9)
					push(i - 8)
				}
			}
			if mode == "delayed_recovery" {
				for i := range count {
					if i%10 < 2 {
						push(i)
					}
				}
			}
			require.Equal(t, count, delivered)
			for i, n := range releases {
				require.Equal(t, 1, n, fmt.Sprintf("frame %d", i))
			}
		})
	}
}
