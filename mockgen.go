//go:build gomock || generate

package quic

//go:generate sh -c "go tool mockgen -typed -build_flags=\"-tags=gomock\" -package quic -self_package github.com/GridCastIO/quicquic-go -destination mock_send_conn_test.go github.com/GridCastIO/quicquic-go SendConn"
type SendConn = sendConn

//go:generate sh -c "go tool mockgen -typed -build_flags=\"-tags=gomock\" -package quic -self_package github.com/GridCastIO/quicquic-go -destination mock_raw_conn_test.go github.com/GridCastIO/quicquic-go RawConn"
type RawConn = rawConn

//go:generate sh -c "go tool mockgen -typed -build_flags=\"-tags=gomock\" -package quic -self_package github.com/GridCastIO/quicquic-go -destination mock_sender_test.go github.com/GridCastIO/quicquic-go Sender"
type Sender = sender

//go:generate sh -c "go tool mockgen -typed -build_flags=\"-tags=gomock\" -package quic -self_package github.com/GridCastIO/quicquic-go -destination mock_stream_sender_test.go github.com/GridCastIO/quicquic-go StreamSender"
type StreamSender = streamSender

//go:generate sh -c "go tool mockgen -typed -build_flags=\"-tags=gomock\" -package quic -self_package github.com/GridCastIO/quicquic-go -destination mock_stream_control_frame_getter_test.go github.com/GridCastIO/quicquic-go StreamControlFrameGetter"
type StreamControlFrameGetter = streamControlFrameGetter

//go:generate sh -c "go tool mockgen -typed -build_flags=\"-tags=gomock\" -package quic -self_package github.com/GridCastIO/quicquic-go -destination mock_stream_frame_getter_test.go github.com/GridCastIO/quicquic-go StreamFrameGetter"
type StreamFrameGetter = streamFrameGetter

//go:generate sh -c "go tool mockgen -typed -build_flags=\"-tags=gomock\" -package quic -self_package github.com/GridCastIO/quicquic-go -destination mock_frame_source_test.go github.com/GridCastIO/quicquic-go FrameSource"
type FrameSource = frameSource

//go:generate sh -c "go tool mockgen -typed -build_flags=\"-tags=gomock\" -package quic -self_package github.com/GridCastIO/quicquic-go -destination mock_ack_frame_source_test.go github.com/GridCastIO/quicquic-go AckFrameSource"
type AckFrameSource = ackFrameSource

//go:generate sh -c "go tool mockgen -typed -build_flags=\"-tags=gomock\" -package quic -self_package github.com/GridCastIO/quicquic-go -destination mock_sealing_manager_test.go github.com/GridCastIO/quicquic-go SealingManager"
type SealingManager = sealingManager

//go:generate sh -c "go tool mockgen -typed -build_flags=\"-tags=gomock\" -package quic -self_package github.com/GridCastIO/quicquic-go -destination mock_unpacker_test.go github.com/GridCastIO/quicquic-go Unpacker"
type Unpacker = unpacker

//go:generate sh -c "go tool mockgen -typed -build_flags=\"-tags=gomock\" -package quic -self_package github.com/GridCastIO/quicquic-go -destination mock_conn_runner_test.go github.com/GridCastIO/quicquic-go ConnRunner"
type ConnRunner = connRunner

//go:generate sh -c "go tool mockgen -typed -package quic -self_package github.com/GridCastIO/quicquic-go -self_package github.com/GridCastIO/quicquic-go -destination mock_packetconn_test.go net PacketConn"
