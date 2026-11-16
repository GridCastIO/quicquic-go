package quic

// Workloads adapted from upstream commit 8d34dbcccc219375fa9fbaa9b7b22caeebd7d49d.
import (
	"fmt"
	"github.com/quic-go/quic-go/internal/protocol"
	"github.com/stretchr/testify/require"
	"testing"
)

var frameSorterBenchmarkGaps = []int{2, 10, 32, 33, 64, 65, 100, 999, 1000, 4095, 4096}

// Frames arrive in order. This is the common case.
func BenchmarkFrameSorterInOrder(b *testing.B) {
	b.ReportAllocs()
	const frameSize protocol.ByteCount = 1200
	data := make([]byte, frameSize)
	s := newFrameSorter()

	var offset protocol.ByteCount
	for b.Loop() {
		if err := s.Push(data, offset, nil); err != nil {
			b.Fatal(err)
		}
		s.Pop()
		offset += frameSize
	}
}

// Every other frame is lost, and its retransmission arrives a fixed number of frames later.
// New frames open gaps at the end, and retransmissions fill the first gap.
func BenchmarkFrameSorterLossy(b *testing.B) {
	const frameSize protocol.ByteCount = 1200

	for _, numGaps := range frameSorterBenchmarkGaps {
		b.Run(fmt.Sprintf("gaps=%d", numGaps), func(b *testing.B) {
			b.ReportAllocs()
			if numGaps > protocol.MaxStreamFrameSorterGaps {
				b.Skip("unsupported gap count")
			}
			data := make([]byte, frameSize)
			s := newFrameSorter()
			// Receive numGaps-1 frames, each with a gap in front of it.
			// Together with the last gap, these are numGaps gaps.
			var next protocol.ByteCount // the end of the received data
			for range numGaps - 1 {
				require.NoError(b, s.Push(data, next+frameSize, nil))
				next += 2 * frameSize
			}

			var lost protocol.ByteCount // the start of the first gap
			for b.Loop() {
				// the retransmission fills the first gap
				if err := s.Push(data, lost, nil); err != nil {
					b.Fatal(err)
				}
				// a new frame arrives, with a gap in front of it
				if err := s.Push(data, next+frameSize, nil); err != nil {
					b.Fatal(err)
				}
				// read the retransmitted frame and the frame after it
				s.Pop()
				s.Pop()
				lost += 2 * frameSize
				next += 2 * frameSize
			}
		})
	}
}

// Every other frame is lost, and the last frame is received again.
// This is the worst case for a list of gaps that is searched from the front.
func BenchmarkFrameSorterDuplicate(b *testing.B) {
	const frameSize protocol.ByteCount = 1200

	for _, numGaps := range frameSorterBenchmarkGaps {
		b.Run(fmt.Sprintf("gaps=%d", numGaps), func(b *testing.B) {
			b.ReportAllocs()
			if numGaps > protocol.MaxStreamFrameSorterGaps {
				b.Skip("unsupported gap count")
			}
			data := make([]byte, frameSize)
			s := newFrameSorter()
			// Receive numGaps-1 frames, each with a gap in front of it.
			// Together with the last gap, these are numGaps gaps.
			var next protocol.ByteCount // the end of the received data
			for range numGaps - 1 {
				require.NoError(b, s.Push(data, next+frameSize, nil))
				next += 2 * frameSize
			}
			last := next - frameSize

			for b.Loop() {
				if err := s.Push(data, last, nil); err != nil {
					b.Fatal(err)
				}
			}
		})
	}
}

// Frames arrive reordered in pairs (1, 0, 3, 2, ...), while there are many gaps further ahead.
// The second frame of each pair splits the first gap, and the first frame fills the gap in front of it.
// This is the worst case for a slice of gaps, which moves all gaps when the first gap changes.
func BenchmarkFrameSorterReordered(b *testing.B) {
	const frameSize protocol.ByteCount = 1200

	for _, numGaps := range frameSorterBenchmarkGaps {
		b.Run(fmt.Sprintf("gaps=%d", numGaps), func(b *testing.B) {
			b.ReportAllocs()
			if numGaps > protocol.MaxStreamFrameSorterGaps {
				b.Skip("unsupported gap count")
			}
			data := make([]byte, frameSize)
			s := newFrameSorter()
			// Receive numGaps-2 frames far ahead, with a gap between each two.
			// Together with the gap in front of them and the last gap, these are numGaps-1 gaps.
			far := protocol.ByteCount(1 << 40)
			for range numGaps - 2 {
				require.NoError(b, s.Push(data, far, nil))
				far += 2 * frameSize
			}

			var pair protocol.ByteCount // the start of the first gap
			for b.Loop() {
				// the second frame splits the first gap, which makes it numGaps gaps
				if err := s.Push(data, pair+frameSize, nil); err != nil {
					b.Fatal(err)
				}
				// the first frame fills the gap in front of it
				if err := s.Push(data, pair, nil); err != nil {
					b.Fatal(err)
				}
				// read both frames
				s.Pop()
				s.Pop()
				pair += 2 * frameSize
			}
		})
	}
}
