package quic

import (
	"testing"

	"github.com/quic-go/quic-go/internal/handshake"
	"github.com/quic-go/quic-go/internal/monotime"
	"github.com/quic-go/quic-go/internal/protocol"
	"github.com/quic-go/quic-go/internal/wire"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"
)

// This optional setup permits the exact benchmark to run on the pre-discard
// baseline as well. The assertion is outside the measured loop.
func benchmarkDiscardCrypto(tp *testPacketPacker) {
	if d, ok := any(tp.cryptoStreamManager).(interface {
		Drop(protocol.EncryptionLevel)
	}); ok {
		d.Drop(protocol.EncryptionInitial)
		d.Drop(protocol.EncryptionHandshake)
	}
	tp.retransmissionQueue.DropPackets(protocol.EncryptionInitial)
	tp.retransmissionQueue.DropPackets(protocol.EncryptionHandshake)
}

func BenchmarkCryptoDeliveryLimitation(b *testing.B) {
	for _, pending := range []bool{false, true} {
		name := "empty"
		if pending {
			name = "application-pending"
		}
		b.Run(name, func(b *testing.B) {
			tp := newTestPacketPacker(b, gomock.NewController(b), protocol.PerspectiveServer)
			benchmarkDiscardCrypto(tp)
			f := newFramer(nil)
			f.enableDeliveryObservations()
			tp.packer.framer = f
			if pending {
				tp.retransmissionQueue.addAppData(&wire.CryptoFrame{Data: []byte("ticket")})
			}
			b.ReportAllocs()
			for b.Loop() {
				tp.packer.deliveryLimitation()
			}
		})
	}
}

func BenchmarkCryptoPacketPacking(b *testing.B) {
	for _, client := range []bool{false, true} {
		perspective := protocol.PerspectiveServer
		if client {
			perspective = protocol.PerspectiveClient
		}
		b.Run(perspective.String(), func(b *testing.B) {
			ctrl := gomock.NewController(b)
			tp := newTestPacketPacker(b, ctrl, perspective)
			tp.pnManager.EXPECT().PeekPacketNumber(gomock.Any()).Return(protocol.PacketNumber(42), protocol.PacketNumberLen2).AnyTimes()
			tp.pnManager.EXPECT().PopPacketNumber(gomock.Any()).Return(protocol.PacketNumber(42)).AnyTimes()
			tp.sealingManager.EXPECT().GetInitialSealer().Return(newTestLongHeaderSealer(), nil).AnyTimes()
			tp.sealingManager.EXPECT().GetHandshakeSealer().Return(newTestLongHeaderSealer(), nil).AnyTimes()
			tp.sealingManager.EXPECT().Get0RTTSealer().Return(nil, handshake.ErrKeysNotYetAvailable).AnyTimes()
			tp.sealingManager.EXPECT().Get1RTTSealer().Return(nil, handshake.ErrKeysNotYetAvailable).AnyTimes()
			tp.ackFramer.EXPECT().GetAckFrame(gomock.Any(), gomock.Any(), gomock.Any()).Return(nil).AnyTimes()
			initial := []byte("server initial")
			if client {
				var err error
				initial, err = getClientHello("quic-go.net")
				require.NoError(b, err)
			}
			handshakeData := []byte("handshake payload")
			now := monotime.Now()
			b.ReportAllocs()
			for b.Loop() {
				// Reinitialize the stream values so every client iteration scrambles a
				// fresh ClientHello, while construction uses the real packet packer.
				*tp.initialStream = *newInitialCryptoStream(client)
				*tp.handshakeStream = *newCryptoStream()
				if _, err := tp.initialStream.Write(initial); err != nil {
					b.Fatal(err)
				}
				if _, err := tp.handshakeStream.Write(handshakeData); err != nil {
					b.Fatal(err)
				}
				packet, err := tp.packer.PackCoalescedPacket(false, 1452, now, protocol.Version1)
				if err != nil {
					b.Fatal(err)
				}
				if packet == nil {
					b.Fatal("no packet")
				}
				packet.buffer.Release()
			}
		})
	}
}
