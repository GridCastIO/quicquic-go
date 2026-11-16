package quic

import (
	"fmt"
	"testing"

	"github.com/quic-go/quic-go/internal/protocol"
	"github.com/stretchr/testify/require"
)

// Inspect actual chunk invariants only as a supplement to the byte, phase,
// Peek and callback results exercised through the sorter below.
func requireSorterChunks(t *testing.T, s *frameSorter) {
	t.Helper()
	var count int
	var previousEnd protocol.ByteCount
	for i, chunk := range s.gaps {
		require.NotEmpty(t, chunk)
		require.LessOrEqual(t, len(chunk), maxGapChunkLen)
		if i > 0 {
			require.Greater(t, len(s.gaps[i-1])+len(chunk), maxGapChunkLen/2)
		}
		for _, gap := range chunk {
			require.Less(t, gap.Start, gap.End)
			require.GreaterOrEqual(t, gap.Start, previousEnd)
			previousEnd = gap.End
			count++
		}
	}
	require.Equal(t, s.numGaps, count)
	require.Equal(t, protocol.MaxByteCount, previousEnd)
}

func TestFrameSorterChunkBoundaries(t *testing.T) {
	for _, n := range []int{maxGapChunkLen/2 - 1, maxGapChunkLen / 2, maxGapChunkLen/2 + 1, maxGapChunkLen - 1, maxGapChunkLen, maxGapChunkLen + 1, 3 * maxGapChunkLen} {
		for _, repair := range []string{"front", "back", "spanning"} {
			t.Run(fmt.Sprintf("frames=%d/%s", n, repair), func(t *testing.T) {
				s := newFrameSorter()
				releases := make([]int, 0, 2*n+2)
				push := func(start, end int) {
					id := len(releases)
					releases = append(releases, 0)
					require.NoError(t, s.Push(streamBytes(protocol.ByteCount(start), protocol.ByteCount(end)), protocol.ByteCount(start), func() { releases[id]++ }))
					requireSorterChunks(t, s)
				}
				for i := range n {
					push(4*i+2, 4*i+4)
				}
				s.openPhase()
				// A duplicate opening cannot replace the first-reception snapshot.
				s.openPhase()
				if repair == "spanning" {
					push(1, 4*n-1) // overlap replacing data across several chunks
					push(0, 4*n)
				} else {
					for j := range n {
						i := j
						if repair == "back" {
							i = n - 1 - j
						}
						push(4*i, 4*i+2)
					}
				}
				got := make([]byte, 4*n)
				require.NoError(t, s.Peek(0, got))
				require.Equal(t, streamBytes(0, protocol.ByteCount(4*n)), got)
				for pos := 0; pos < 4*n; pos++ {
					phase, end := s.phaseAt(protocol.ByteCount(pos))
					want := closedReceivePhaseNumber
					if pos%4 < 2 {
						want = openReceivePhaseNumber
					}
					require.Equal(t, want, phase, "offset %d", pos)
					require.Greater(t, end, protocol.ByteCount(pos))
				}
				var read []byte
				for {
					offset, data, done := s.Pop()
					if data == nil {
						break
					}
					require.Equal(t, protocol.ByteCount(len(read)), offset)
					read = append(read, data...)
					if done != nil {
						done()
					}
				}
				require.Equal(t, got, read)
				require.False(t, s.HasMoreData())
				s.discard()
				s.discard()
				require.Nil(t, s.gaps)
				require.Nil(t, s.openGaps)
				_, empty, done := s.Pop()
				require.Nil(t, empty)
				require.Nil(t, done)
				for i, n := range releases {
					require.Equal(t, 1, n, "callback %d", i)
				}
			})
		}
	}
}

func TestFrameSorterChunkLimitCleanup(t *testing.T) {
	s := newFrameSorter()
	releases := make([]int, protocol.MaxStreamFrameSorterGaps)
	for i := 0; i < protocol.MaxStreamFrameSorterGaps-1; i++ {
		require.NoError(t, s.Push([]byte{1}, protocol.ByteCount(2*i+1), func() { releases[i]++ }))
	}
	s.openPhase()
	rejected := len(releases) - 1
	require.EqualError(t, s.Push([]byte{1}, protocol.ByteCount(2*rejected+1), func() { releases[rejected]++ }), "too many gaps in received data")
	require.Equal(t, 1, releases[rejected])
	s.discard()
	s.discard()
	for i, n := range releases {
		require.Equal(t, 1, n, "callback %d", i)
	}
	require.Nil(t, s.openGaps)
	require.Nil(t, s.gaps)
}

func TestReceivePhaseStreamFragmentedReplacement(t *testing.T) {
	const count = 3 * maxGapChunkLen
	s := newPhasedStream(t)
	for i := range count {
		s.frame(t, protocol.ByteCount(4*i+2), protocol.ByteCount(4*i+4), false)
	}
	s.open(t)
	s.frame(t, 0, 4*count, false)
	want := make([]phaseSegment, 0, 2*count)
	for i := range count {
		want = append(want, phaseSegment{openReceivePhaseNumber, streamBytes(protocol.ByteCount(4*i), protocol.ByteCount(4*i+2))}, phaseSegment{closedReceivePhaseNumber, streamBytes(protocol.ByteCount(4*i+2), protocol.ByteCount(4*i+4))})
	}
	s.requireSegments(t, want)
	s.str.CancelRead(7)
	require.Nil(t, s.str.frameQueue.openGaps)
	require.Nil(t, s.str.frameQueue.gaps)
}
