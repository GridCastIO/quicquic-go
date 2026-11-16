package quic

import (
	"context"
	"io"
	"os"
	"testing"
	"testing/synctest"
	"time"

	"github.com/quic-go/quic-go/internal/monotime"
	"github.com/quic-go/quic-go/internal/protocol"
	"github.com/quic-go/quic-go/internal/wire"

	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"
)

func TestStreamDeadlines(t *testing.T) {
	const streamID protocol.StreamID = 1337
	mockCtrl := gomock.NewController(t)
	mockSender := NewMockStreamSender(mockCtrl)
	fc := newTestStreamFlowControllerWithSendWindow(streamID, protocol.MaxByteCount)
	str := newStream(context.Background(), streamID, mockSender, fc, false)

	// SetDeadline sets both read and write deadlines
	str.SetDeadline(time.Now().Add(-time.Second))
	n, err := (&writerWithTimeout{Writer: str, Timeout: time.Second}).Write([]byte("foobar"))
	require.ErrorIs(t, err, os.ErrDeadlineExceeded)
	require.Zero(t, n)

	require.NoError(t, str.handleStreamFrame(&wire.StreamFrame{Data: []byte("foobar")}, monotime.Now()))
	n, err = (&readerWithTimeout{Reader: str, Timeout: time.Second}).Read(make([]byte, 6))
	require.ErrorIs(t, err, os.ErrDeadlineExceeded)
	require.Zero(t, n)
}

func TestStreamReceiveFinalSizeCallback(t *testing.T) {
	const streamID protocol.StreamID = 1337
	mockCtrl := gomock.NewController(t)
	mockSender := NewMockStreamSender(mockCtrl)
	fc := newTestStreamFlowControllerWithSendWindow(streamID, protocol.MaxByteCount)
	str := newStream(context.Background(), streamID, mockSender, fc, false)

	require.NoError(t, str.handleStreamFrame(&wire.StreamFrame{Data: []byte("foobar"), Fin: true}, monotime.Now()))

	var size int64
	str.SetReceiveFinalSizeCallback(func(s int64) { size = s })
	require.EqualValues(t, 6, size)
}

func TestStreamCompletion(t *testing.T) {
	completeReadSide := func(
		t *testing.T,
		str *Stream,
		mockCtrl *gomock.Controller,
	) {
		t.Helper()
		require.NoError(t, str.handleStreamFrame(&wire.StreamFrame{
			StreamID: str.StreamID(),
			Data:     []byte("foobar"),
			Fin:      true,
		}, monotime.Now()))
		_, err := (&readerWithTimeout{Reader: str, Timeout: time.Second}).Read(make([]byte, 6))
		require.ErrorIs(t, err, io.EOF)
		require.True(t, mockCtrl.Satisfied())
	}

	completeWriteSide := func(
		t *testing.T,
		str *Stream,
		mockCtrl *gomock.Controller,
		mockSender *MockStreamSender,
	) {
		t.Helper()
		mockSender.EXPECT().onHasStreamData(str.StreamID(), gomock.Any()).Times(2)
		_, err := (&writerWithTimeout{Writer: str, Timeout: time.Second}).Write([]byte("foobar"))
		require.NoError(t, err)
		require.NoError(t, str.Close())
		f, _, _ := str.popStreamFrame(protocol.MaxByteCount, protocol.Version1)
		require.NotNil(t, f.Frame)
		require.True(t, f.Frame.Fin)
		f.Handler.OnAcked(f.Frame)
		require.True(t, mockCtrl.Satisfied())
	}

	const streamID protocol.StreamID = 1337

	t.Run("first read, then write", func(t *testing.T) {
		mockCtrl := gomock.NewController(t)
		mockSender := NewMockStreamSender(mockCtrl)
		fc := newTestStreamFlowControllerWithSendWindow(streamID, protocol.MaxByteCount)
		str := newStream(context.Background(), streamID, mockSender, fc, false)

		completeReadSide(t, str, mockCtrl)
		mockSender.EXPECT().onStreamCompleted(streamID)
		completeWriteSide(t, str, mockCtrl, mockSender)
	})

	t.Run("first write, then read", func(t *testing.T) {
		mockCtrl := gomock.NewController(t)
		mockSender := NewMockStreamSender(mockCtrl)
		fc := newTestStreamFlowControllerWithSendWindow(streamID, protocol.MaxByteCount)
		str := newStream(context.Background(), streamID, mockSender, fc, false)

		completeWriteSide(t, str, mockCtrl, mockSender)
		mockSender.EXPECT().onStreamCompleted(streamID)
		completeReadSide(t, str, mockCtrl)
	})
}

func TestStreamBlockedWriteResetReturnsCredit(t *testing.T) {
	for _, remote := range []bool{false, true} {
		name := "CancelWrite"
		if remote {
			name = "STOP_SENDING"
		}
		t.Run(name, func(t *testing.T) {
			synctest.Test(t, func(t *testing.T) {
				const streamID protocol.StreamID = 0 // client-initiated bidirectional stream
				ctrl := gomock.NewController(t)
				sender := NewMockStreamSender(ctrl)
				var credits []wire.Frame
				streams := newIncomingStreamsMap(protocol.StreamTypeBidi, func(id protocol.StreamID) *Stream {
					return newStream(context.Background(), id, sender, newTestStreamFlowControllerWithSendWindow(id, protocol.MaxByteCount), false)
				}, 1, func(f wire.Frame) { credits = append(credits, f) }, protocol.PerspectiveServer)
				str, err := streams.GetOrOpenStream(streamID)
				require.NoError(t, err)
				accepted, err := streams.AcceptStream(context.Background())
				require.NoError(t, err)
				require.Same(t, str, accepted)
				require.NoError(t, str.handleStreamFrame(&wire.StreamFrame{StreamID: streamID, Fin: true}, monotime.Now()))
				_, err = str.Read(make([]byte, 1))
				require.ErrorIs(t, err, io.EOF)
				sender.EXPECT().onHasStreamData(streamID, str.sendStr).Times(2)
				_, err = str.Write([]byte("prefix"))
				require.NoError(t, err)
				type result struct {
					n   int
					err error
				}
				results := make(chan result, 1)
				go func() {
					n, err := str.Write(make([]byte, protocol.MaxPacketBufferSize))
					results <- result{n, err}
				}()
				synctest.Wait()
				require.Empty(t, results)
				sender.EXPECT().onHasStreamControlFrame(streamID, str)
				if remote {
					str.handleStopSendingFrame(&wire.StopSendingFrame{StreamID: streamID, ErrorCode: 123})
				} else {
					str.CancelWrite(123)
				}
				synctest.Wait()
				r := <-results
				require.Zero(t, r.n)
				require.ErrorIs(t, r.err, &StreamError{StreamID: streamID, ErrorCode: 123, Remote: remote})
				require.Empty(t, credits, "reset must be acknowledged before credit is returned")
				reset, ok, _ := str.getControlFrame(monotime.Now())
				require.True(t, ok)
				sender.EXPECT().onStreamCompleted(streamID).Do(func(id protocol.StreamID) {
					require.NoError(t, streams.DeleteStream(id))
				})
				reset.Handler.OnAcked(reset.Frame)
				require.Equal(t, []wire.Frame{&wire.MaxStreamsFrame{Type: protocol.StreamTypeBidi, MaxStreamNum: 2}}, credits)
				str.CancelWrite(456)
				_, err = str.Write([]byte("later"))
				require.Same(t, r.err, err)
				_, err = streams.GetOrOpenStream(4)
				require.NoError(t, err, "returned credit must admit the next stream")
			})
		})
	}
}
