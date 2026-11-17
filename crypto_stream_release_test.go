package quic

import (
	"bytes"
	"fmt"
	"runtime"
	"testing"
	"testing/synctest"
	"weak"

	"github.com/GridCastIO/quicquic-go/internal/congestion"
	"github.com/GridCastIO/quicquic-go/internal/mocks"
	"github.com/GridCastIO/quicquic-go/internal/monotime"
	"github.com/GridCastIO/quicquic-go/internal/protocol"
	"github.com/GridCastIO/quicquic-go/internal/wire"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"
)

func TestConnectionDiscardCryptoStorage(t *testing.T) {
	for _, level := range []protocol.EncryptionLevel{protocol.EncryptionInitial, protocol.EncryptionHandshake} {
		t.Run(level.String(), func(t *testing.T) {
			ctrl := gomock.NewController(t)
			cs := mocks.NewMockCryptoSetup(ctrl)
			cs.EXPECT().DiscardInitialKeys().AnyTimes()
			c := newServerTestConnection(t, ctrl, nil, false, connectionOptCryptoSetup(cs)).conn
			retained := discardCryptoWithFrameOwner(t, c, level)
			runtime.GC()
			require.Nil(t, retained.Value(), "discarded stream must not retain the drained write allocation after the frame owner ends")
			runtime.KeepAlive(c)
		})
	}
}

//go:noinline
func discardCryptoWithFrameOwner(t *testing.T, c *Conn, level protocol.EncryptionLevel) weak.Pointer[byte] {
	t.Helper()
	data := bytes.Repeat([]byte{0xa5}, 4096)
	var frame *wire.CryptoFrame
	if level == protocol.EncryptionInitial {
		_, err := c.cryptoStreamManager.initialStream.Write(data)
		require.NoError(t, err)
		frame = c.cryptoStreamManager.initialStream.PopCryptoFrame(protocol.MaxByteCount)
	} else {
		_, err := c.cryptoStreamManager.handshakeStream.Write(data)
		require.NoError(t, err)
		frame = c.cryptoStreamManager.handshakeStream.PopCryptoFrame(protocol.MaxByteCount)
	}
	retained := weak.Make(&frame.Data[0])
	require.NoError(t, c.cryptoStreamManager.Finish(level))
	c.dropEncryptionLevel(level, monotime.Now())
	c.dropEncryptionLevel(level, monotime.Now())
	runtime.GC()
	require.Equal(t, data, frame.Data, "discard must preserve an outstanding frame's bytes")
	runtime.KeepAlive(frame)
	return retained
}

func TestConnectionDiscardCryptoRetransmissions(t *testing.T) {
	for _, level := range []protocol.EncryptionLevel{protocol.EncryptionInitial, protocol.EncryptionHandshake} {
		t.Run(level.String(), func(t *testing.T) {
			ctrl := gomock.NewController(t)
			cs := mocks.NewMockCryptoSetup(ctrl)
			cs.EXPECT().DiscardInitialKeys().AnyTimes()
			c := newServerTestConnection(t, ctrl, nil, false, connectionOptCryptoSetup(cs)).conn
			handler := c.retransmissionQueue.AckHandler(level)
			frame := &wire.CryptoFrame{Data: []byte("handshake retransmission")}
			handler.OnLost(frame)
			require.True(t, c.retransmissionQueue.HasData(level))
			c.dropEncryptionLevel(level, monotime.Now())
			require.False(t, c.retransmissionQueue.HasData(level))
			handler.OnLost(frame)
			handler.OnLost(&wire.PingFrame{})
			require.False(t, c.retransmissionQueue.HasData(level))
			require.Nil(t, c.retransmissionQueue.GetFrame(level, protocol.MaxByteCount, protocol.Version1))
			c.retransmissionQueue.AckHandler(protocol.Encryption1RTT).OnLost(frame)
			require.True(t, c.retransmissionQueue.HasData(protocol.Encryption1RTT), "application recovery survives handshake discard")
		})
	}
}

func TestCryptoStreamManagerDiscardAvailability(t *testing.T) {
	m := newCryptoStreamManager(protocol.PerspectiveServer)
	require.NoError(t, m.Write(protocol.Encryption1RTT, []byte("ticket")))
	for _, level := range []protocol.EncryptionLevel{protocol.EncryptionInitial, protocol.EncryptionHandshake} {
		require.NoError(t, m.Write(level, []byte("handshake")))
		require.True(t, m.HasData(level))
		m.Drop(level)
		m.Drop(level)
		require.False(t, m.HasData(level))
		require.Nil(t, m.PopCryptoFrame(level, protocol.MaxByteCount))
	}
	require.Equal(t, []byte("ticket"), m.GetPostHandshakeData(protocol.MaxByteCount).Data)
}

func TestConnectionDiscardCryptoPendingSend(t *testing.T) {
	for _, client := range []bool{false, true} {
		t.Run(fmt.Sprintf("client=%t", client), func(t *testing.T) {
			synctest.Test(t, func(t *testing.T) {
				tc := newHandshakeEmissionConnection(t, client)
				c := tc.conn
				initial := []byte("server initial")
				if client {
					var err error
					initial, err = getClientHello("quic-go.net")
					require.NoError(t, err)
				}
				require.NoError(t, c.cryptoStreamManager.Write(protocol.EncryptionInitial, initial))
				require.NoError(t, c.cryptoStreamManager.Write(protocol.EncryptionHandshake, []byte("handshake payload")))
				require.NoError(t, c.triggerSending(monotime.Now()).err)
				q := c.emission.queue.(*sendQueue)
				require.Len(t, q.queue, 1)
				started, release := make(chan struct{}), make(chan struct{})
				tc.sendConn.EXPECT().Write(gomock.Any(), gomock.Any(), gomock.Any()).DoAndReturn(func(data []byte, _ uint16, _ protocol.ECN) error {
					want := bytes.Clone(data)
					close(started)
					<-release
					require.Equal(t, want, data, "discard and shutdown cannot modify bytes borrowed by the send worker")
					hdrs, more := parsePacket(t, data)
					require.Len(t, hdrs, 2)
					require.Empty(t, more)
					return nil
				})
				done := make(chan error, 1)
				go func() { done <- q.Run() }()
				<-started
				c.dropEncryptionLevel(protocol.EncryptionInitial, monotime.Now())
				c.dropEncryptionLevel(protocol.EncryptionHandshake, monotime.Now())
				runtime.GC()
				closed := make(chan struct{})
				go func() { q.Close(); close(closed) }()
				synctest.Wait()
				select {
				case <-closed:
					t.Fatal("shutdown returned with borrowed send bytes outstanding")
				default:
				}
				close(release)
				<-closed
				require.NoError(t, <-done)
			})
		})
	}
}

func TestConnectionDiscardCryptoReceiveStorage(t *testing.T) {
	for _, level := range []protocol.EncryptionLevel{protocol.EncryptionInitial, protocol.EncryptionHandshake} {
		t.Run(level.String(), func(t *testing.T) {
			ctrl := gomock.NewController(t)
			cs := mocks.NewMockCryptoSetup(ctrl)
			cs.EXPECT().DiscardInitialKeys().AnyTimes()
			c := newServerTestConnection(t, ctrl, nil, false, connectionOptCryptoSetup(cs)).conn
			retained := queueCryptoReceiveStorage(t, c, level)
			c.dropEncryptionLevel(level, monotime.Now())
			runtime.GC()
			require.Nil(t, retained.Value(), "discard releases unread receive storage as well as outgoing storage")
			runtime.KeepAlive(c)
		})
	}
}

//go:noinline
func queueCryptoReceiveStorage(t *testing.T, c *Conn, level protocol.EncryptionLevel) weak.Pointer[byte] {
	t.Helper()
	data := bytes.Repeat([]byte{0x5a}, 4096)
	require.NoError(t, c.cryptoStreamManager.HandleCryptoFrame(&wire.CryptoFrame{Offset: 8, Data: data}, level))
	return weak.Make(&data[0])
}

func TestDiscardedCryptoDeliveryLimitation(t *testing.T) {
	c := newHandshakeEmissionConnection(t, true).conn
	c.framer.enableDeliveryObservations()
	for _, level := range []protocol.EncryptionLevel{protocol.EncryptionInitial, protocol.EncryptionHandshake} {
		c.dropEncryptionLevel(level, monotime.Now())
	}
	require.Equal(t, congestion.SendApplicationLimited, c.emission.packer.deliveryLimitation())
	c.retransmissionQueue.AckHandler(protocol.Encryption1RTT).OnLost(&wire.CryptoFrame{Data: []byte("ticket")})
	require.Equal(t, congestion.SendUnknown, c.emission.packer.deliveryLimitation())
}
