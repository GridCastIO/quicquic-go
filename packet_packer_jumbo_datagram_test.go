package quic

import (
	"bytes"
	"fmt"
	"testing"

	"github.com/quic-go/quic-go/internal/ackhandler"
	"github.com/quic-go/quic-go/internal/monotime"
	"github.com/quic-go/quic-go/internal/protocol"
	"github.com/quic-go/quic-go/internal/wire"

	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"
)

func TestPackJumboDatagrams(t *testing.T) {
	for _, datagramOnly := range []bool{false, true} {
		for _, size := range []protocol.ByteCount{1452, 8957} {
			for _, payloadSize := range []int{100, 1099} {
				t.Run(fmt.Sprintf("datagramOnly=%t/size=%d/payload=%d", datagramOnly, size, payloadSize), func(t *testing.T) {
					ctrl := gomock.NewController(t)
					tp := newTestPacketPacker(t, ctrl, protocol.PerspectiveServer)
					tp.pnManager.EXPECT().PeekPacketNumber(protocol.Encryption1RTT).Return(protocol.PacketNumber(42), protocol.PacketNumberLen2)
					tp.pnManager.EXPECT().PopPacketNumber(protocol.Encryption1RTT).Return(protocol.PacketNumber(42))
					tp.sealingManager.EXPECT().Get1RTTSealer().Return(newMockShortHeaderSealer(ctrl), nil)
					if !datagramOnly {
						tp.ackFramer.EXPECT().GetAckFrame(protocol.Encryption1RTT, gomock.Any(), true)
						tp.framer.EXPECT().HasData().Return(false)
					}
					for i := range 9 {
						require.NoError(t, tp.datagramQueue.Add(&wire.DatagramFrame{DataLenPresent: true, Data: bytes.Repeat([]byte{byte(i)}, payloadSize)}))
					}
					buf := getPacketBufferForCeiling(8972)
					defer buf.Release()
					var packet shortHeaderPacket
					var err error
					if datagramOnly {
						packet, err = tp.packer.AppendDatagramPacket(nil, buf, size, protocol.Version1)
					} else {
						packet, err = tp.packer.AppendPacket(buf, size, monotime.Now(), protocol.Version1)
					}
					require.NoError(t, err)
					want := 1
					if size == 8957 {
						want = 8
						if payloadSize == 100 {
							want = 9
						}
					}
					require.Len(t, packet.Frames, want)
					require.LessOrEqual(t, packet.Length, size)
					seen := make(map[byte]bool)
					for _, frame := range packet.Frames {
						d := frame.Frame.(*wire.DatagramFrame)
						require.Len(t, d.Data, payloadSize)
						require.False(t, seen[d.Data[0]])
						seen[d.Data[0]] = true
					}
					if want == 9 {
						require.Nil(t, tp.datagramQueue.Peek())
					} else {
						require.Equal(t, byte(want), tp.datagramQueue.Peek().Data[0], "the next non-fitting frame remains queued")
					}
				})
			}
		}
	}
}

func TestPackJumboDatagramsPreservesStreamProgress(t *testing.T) {
	ctrl := gomock.NewController(t)
	tp := newTestPacketPacker(t, ctrl, protocol.PerspectiveServer)
	tp.pnManager.EXPECT().PeekPacketNumber(protocol.Encryption1RTT).Return(protocol.PacketNumber(42), protocol.PacketNumberLen2)
	tp.pnManager.EXPECT().PopPacketNumber(protocol.Encryption1RTT).Return(protocol.PacketNumber(42))
	tp.sealingManager.EXPECT().Get1RTTSealer().Return(newMockShortHeaderSealer(ctrl), nil)
	tp.ackFramer.EXPECT().GetAckFrame(protocol.Encryption1RTT, gomock.Any(), false)
	tp.framer.EXPECT().HasData().Return(true)
	stream := &wire.StreamFrame{StreamID: 4, DataLenPresent: true, Data: bytes.Repeat([]byte{'s'}, 1024)}
	expectAppendFrames(tp.framer, nil, []ackhandler.StreamFrame{{Frame: stream}})
	for range maxDatagramSendQueueLen {
		require.NoError(t, tp.datagramQueue.Add(&wire.DatagramFrame{DataLenPresent: true, Data: bytes.Repeat([]byte{'d'}, 1099)}))
	}
	buf := getPacketBufferForCeiling(8972)
	defer buf.Release()
	packet, err := tp.packer.AppendPacket(buf, 8957, monotime.Now(), protocol.Version1)
	require.NoError(t, err)
	require.Len(t, packet.StreamFrames, 1)
	require.Equal(t, stream.Data, packet.StreamFrames[0].Frame.Data)
	require.Len(t, packet.Frames, 7)
	require.LessOrEqual(t, packet.Length, protocol.ByteCount(8957))
}
