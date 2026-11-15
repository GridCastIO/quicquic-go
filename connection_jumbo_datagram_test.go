package quic

import (
	"bytes"
	"fmt"
	"testing"

	"github.com/quic-go/quic-go/internal/monotime"
	"github.com/quic-go/quic-go/internal/protocol"
	"github.com/quic-go/quic-go/internal/wire"
	"github.com/quic-go/quic-go/qlog"
	"github.com/quic-go/quic-go/testutils/events"

	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"
)

func TestJumboDatagramAdmissionBeforeAck(t *testing.T) {
	for _, early := range []bool{false, true} {
		for _, payloadSize := range []int{1, 1099} {
			t.Run(fmt.Sprintf("early=%t/payload=%d", early, payloadSize), func(t *testing.T) {
				ctrl := gomock.NewController(t)
				unpacker := NewMockUnpacker(ctrl)
				var recorder events.Recorder
				var tc *testConnection
				if early {
					tc = newServerTestConnection(t, ctrl, &Config{EnableDatagrams: true}, false, connectionOptUnpacker(unpacker), connectionOptTracer(&recorder))
				} else {
					tc = newClientTestConnection(t, ctrl, &Config{EnableDatagrams: true}, false, connectionOptUnpacker(unpacker), connectionOptHandshakeConfirmed(), connectionOptTracer(&recorder))
				}
				tc.conn.packetCeiling = 8972
				pushReceivedDatagrams(t, tc, 1020)
				var data []byte
				for i := range 8 {
					var err error
					data, err = (&wire.DatagramFrame{DataLenPresent: true, Data: bytes.Repeat([]byte{byte(i)}, payloadSize)}).Append(data, protocol.Version1)
					require.NoError(t, err)
				}
				receive := func(pn protocol.PacketNumber) bool {
					buf := getPacketBufferForCeiling(8972)
					buf.Data = append(buf.Data, make([]byte, 8957)...)
					buf.Data[0] = 0x40
					if early {
						buf.Data[0] = 0xc0
					}
					checksum := qlog.CalculateDatagramPayloadChecksum(buf.Data)
					// Unpacking mutates backing bytes; the handler must retain the captured
					// identity of the original UDP datagram, including trailing 1-RTT.
					buf.Data[len(buf.Data)-1] ^= 1
					p := receivedPacket{buffer: buf, data: buf.Data, remoteAddr: tc.remoteAddr, rcvTime: monotime.Now()}
					var processed bool
					var err error
					if early {
						hdr := &wire.Header{Type: protocol.PacketType0RTT, DestConnectionID: tc.conn.handshakeDestConnID}
						unpacker.EXPECT().UnpackLongHeader(hdr, gomock.Any()).Return(&unpackedPacket{hdr: &wire.ExtendedHeader{Header: *hdr, PacketNumber: pn, PacketNumberLen: protocol.PacketNumberLen2}, encryptionLevel: protocol.Encryption0RTT, data: data}, nil)
						processed, err = tc.conn.handleLongHeaderPacket(p, hdr, checksum)
					} else {
						unpacker.EXPECT().UnpackShortHeader(protocol.PathID(0), gomock.Any(), gomock.Any()).Return(pn, protocol.PacketNumberLen2, protocol.KeyPhaseZero, data, nil)
						processed, err = tc.conn.handleShortHeaderPacket(p, true, checksum)
					}
					require.NoError(t, err)
					require.Zero(t, buf.refCount)
					if !processed {
						drops := recorder.Events(qlog.PacketDropped{})
						require.Len(t, drops, 1)
						require.Equal(t, checksum, drops[0].(qlog.PacketDropped).DatagramPayloadChecksum)
					}
					return processed
				}
				require.False(t, receive(10), "a packed packet must be refused before any payload or ACK is published")
				require.Equal(t, 1020, tc.conn.datagramQueue.receiveQueueLen())
				require.EqualValues(t, 1, tc.conn.UnprocessedPacketDropsV1())
				require.Zero(t, tc.conn.DatagramReceiveDropsV1(), "no acknowledged payload is discarded")
				require.Nil(t, tc.conn.receivedPacketHandler.GetAckFrame(protocol.Encryption1RTT, monotime.Now(), false))
				for range 4 {
					_, err := tc.conn.ReceiveDatagram(t.Context())
					require.NoError(t, err)
				}
				require.True(t, receive(11))
				require.Equal(t, 1024, tc.conn.datagramQueue.receiveQueueLen())
				ack := tc.conn.receivedPacketHandler.GetAckFrame(protocol.Encryption1RTT, monotime.Now(), false)
				require.NotNil(t, ack)
				require.True(t, ack.AcksPacket(11))
				require.False(t, ack.AcksPacket(10))
				require.Zero(t, tc.conn.DatagramReceiveDropsV1())
			})
		}
	}
}
