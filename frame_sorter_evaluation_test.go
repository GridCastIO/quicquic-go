package quic

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"runtime"
	"strconv"
	"testing"

	"github.com/quic-go/quic-go/internal/monotime"
	"github.com/quic-go/quic-go/internal/protocol"
	"github.com/quic-go/quic-go/internal/wire"
	"github.com/stretchr/testify/require"
)

func BenchmarkFrameSorterConstruct(b *testing.B) {
	data := make([]byte, 1200)
	b.ReportAllocs()
	for b.Loop() {
		s := newFrameSorter()
		if err := s.Push(data, 0, nil); err != nil {
			b.Fatal(err)
		}
		s.Pop()
		s.discard()
	}
}

// Replacement spans the fragmented queue; construction and drain are included.
func BenchmarkFrameSorterOverlap(b *testing.B) {
	for _, gaps := range []int{10, 100, 1000, 4096} {
		b.Run(fmt.Sprintf("gaps=%d", gaps), func(b *testing.B) {
			if gaps > protocol.MaxStreamFrameSorterGaps {
				b.Skip("unsupported gap count")
			}
			data := make([]byte, 2*gaps*1200)
			b.ReportAllocs()
			for b.Loop() {
				s := newFrameSorter()
				for i := 0; i < gaps-1; i++ {
					if err := s.Push(data[(2*i+1)*1200:(2*i+2)*1200], protocol.ByteCount((2*i+1)*1200), nil); err != nil {
						b.Fatal(err)
					}
				}
				if err := s.Push(data, 0, nil); err != nil {
					b.Fatal(err)
				}
				s.Pop()
				s.discard()
			}
		})
	}
}

// The live stream path includes synchronization, flow accounting, copies and
// phase-aware reads. Pair reordering is measured with a fixed distant backlog.
func BenchmarkFrameSorterReceiveStream(b *testing.B) {
	for _, phase := range []bool{false, true} {
		for _, gaps := range []int{0, 10, 1000, 4096} {
			b.Run(fmt.Sprintf("phase=%t/gaps=%d", phase, gaps), func(b *testing.B) {
				if gaps > protocol.MaxStreamFrameSorterGaps {
					b.Skip("unsupported gap count")
				}
				s := newReceiveStream(42, nil, newTestStreamFlowController(42))
				defer s.frameQueue.discard()
				data, out := make([]byte, 1200), make([]byte, 1200)
				now := monotime.Now()
				push := func(offset protocol.ByteCount) {
					if err := s.handleStreamFrame(&wire.StreamFrame{StreamID: 42, Offset: offset, Data: data}, now); err != nil {
						b.Fatal(err)
					}
				}
				for i := 0; i < gaps-2; i++ {
					push(1<<40 + protocol.ByteCount(i*2400))
				}
				if phase {
					p := newReceivePhase()
					s.gateReceivePhase(p)
					req, err := p.request(context.Background())
					require.NoError(b, err)
					p.apply(func() {})
					<-req.done
				}
				read := func() {
					var n int
					var err error
					if phase {
						n, _, err = s.ReadReceivePhaseV1(out)
					} else {
						n, err = s.Read(out)
					}
					if err != nil || n != len(out) {
						b.Fatalf("read %d: %v", n, err)
					}
				}
				var offset protocol.ByteCount
				b.ReportAllocs()
				for b.Loop() {
					if gaps == 0 {
						push(offset)
						read()
						offset += 1200
					} else {
						push(offset + 1200)
						push(offset)
						read()
						read()
						offset += 2400
					}
				}
			})
		}
	}
}

// An opt-in, process-isolated retained-heap probe. Payload backing storage is
// deliberately larger than the 1200-byte frame; the callback pins the owner.
// Each invocation measures 16 live sorters and reports one lifecycle stage.
func TestFrameSorterRetainedHeap(t *testing.T) {
	stage := os.Getenv("SORTER_HEAP_STAGE")
	if stage == "" {
		t.Skip("evaluation-only retained heap probe")
	}
	gaps, err := strconv.Atoi(os.Getenv("SORTER_HEAP_GAPS"))
	require.NoError(t, err)
	if gaps > protocol.MaxStreamFrameSorterGaps {
		t.Skip("unsupported gap count")
	}
	require.Contains(t, []string{"fragmented", "partial", "drained", "discarded"}, stage)
	phase := os.Getenv("SORTER_HEAP_PHASE") == "true"
	const instances = 16
	runtime.GC()
	runtime.GC()
	var before, after runtime.MemStats
	runtime.ReadMemStats(&before)
	sorters := make([]*frameSorter, instances)
	var releases int
	push := func(s *frameSorter, offset int) {
		backing := make([]byte, 2048)
		require.NoError(t, s.Push(backing[:1200], protocol.ByteCount(offset), func() { runtime.KeepAlive(backing); releases++ }))
	}
	for i := range sorters {
		s := newFrameSorter()
		sorters[i] = s
		for j := 0; j < gaps-1; j++ {
			push(s, (2*j+1)*1200)
		}
		if phase {
			s.openPhase()
		}
		if stage == "partial" || stage == "drained" {
			n := (gaps - 1) / 2
			if stage == "drained" {
				n = gaps - 1
			}
			for j := 0; j < n; j++ {
				push(s, 2*j*1200)
				for range 2 {
					offset, data, done := s.Pop()
					require.Len(t, data, 1200)
					if phase {
						s.phaseAt(offset)
					}
					done()
				}
			}
		}
		if stage == "discarded" {
			s.discard()
		}
	}
	var queued, backingBytes, snapshotCap int
	for _, s := range sorters {
		queued += len(s.queue)
		snapshotCap += cap(s.openGaps) * 16
		for _, e := range s.queue {
			backingBytes += cap(e.Data)
		}
	}
	runtime.GC()
	runtime.GC()
	runtime.ReadMemStats(&after)
	runtime.KeepAlive(sorters)
	report := map[string]any{"stage": stage, "gaps": gaps, "phase": phase, "instances": instances, "heap_bytes_per_sorter": float64(int64(after.HeapAlloc)-int64(before.HeapAlloc)) / instances, "heap_objects_per_sorter": float64(int64(after.HeapObjects)-int64(before.HeapObjects)) / instances, "queued_frames_per_sorter": queued / instances, "queued_backing_bytes_per_sorter": backingBytes / instances, "snapshot_remaining_capacity_bytes_per_sorter": snapshotCap / instances, "released_callbacks_per_sorter": releases / instances}
	encoded, err := json.Marshal(report)
	require.NoError(t, err)
	fmt.Println(string(encoded))
	for _, s := range sorters {
		s.discard()
	}
}

var evaluationPhaseSnapshot []byteInterval

func BenchmarkFrameSorterPhaseSnapshot(b *testing.B) {
	for _, gaps := range []int{10, 100, 1000, 4096} {
		b.Run(fmt.Sprintf("gaps=%d", gaps), func(b *testing.B) {
			if gaps > protocol.MaxStreamFrameSorterGaps {
				b.Skip("unsupported gap count")
			}
			s := newFrameSorter()
			data := make([]byte, 1200)
			for i := 0; i < gaps-1; i++ {
				require.NoError(b, s.Push(data, protocol.ByteCount((2*i+1)*1200), nil))
			}
			defer s.discard()
			b.ReportAllocs()
			for b.Loop() {
				snapshot := *s // independent phase state; openPhase must only read the shared gaps
				snapshot.openPhase()
				evaluationPhaseSnapshot = snapshot.openGaps
			}
			evaluationPhaseSnapshot = nil
		})
	}
}
