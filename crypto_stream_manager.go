package quic

import (
	"fmt"

	"github.com/quic-go/quic-go/internal/protocol"
	"github.com/quic-go/quic-go/internal/wire"
)

type cryptoStreamManager struct {
	initialStream   *initialCryptoStream
	handshakeStream *cryptoStream
	oneRTTStream    *cryptoStream
}

func newCryptoStreamManager(perspective protocol.Perspective) *cryptoStreamManager {
	return &cryptoStreamManager{
		initialStream:   newInitialCryptoStream(perspective == protocol.PerspectiveClient),
		handshakeStream: newCryptoStream(),
		oneRTTStream:    newCryptoStream(),
	}
}

func (m *cryptoStreamManager) HandleCryptoFrame(frame *wire.CryptoFrame, encLevel protocol.EncryptionLevel) error {
	//nolint:exhaustive // CRYPTO frames cannot be sent in 0-RTT packets.
	switch encLevel {
	case protocol.EncryptionInitial:
		return m.initialStream.HandleCryptoFrame(frame)
	case protocol.EncryptionHandshake:
		return m.handshakeStream.HandleCryptoFrame(frame)
	case protocol.Encryption1RTT:
		return m.oneRTTStream.HandleCryptoFrame(frame)
	default:
		return fmt.Errorf("received CRYPTO frame with unexpected encryption level: %s", encLevel)
	}
}

func (m *cryptoStreamManager) GetCryptoData(encLevel protocol.EncryptionLevel) []byte {
	//nolint:exhaustive // CRYPTO frames cannot be sent in 0-RTT packets.
	switch encLevel {
	case protocol.EncryptionInitial:
		return m.initialStream.GetCryptoData()
	case protocol.EncryptionHandshake:
		return m.handshakeStream.GetCryptoData()
	case protocol.Encryption1RTT:
		return m.oneRTTStream.GetCryptoData()
	default:
		panic(fmt.Sprintf("received CRYPTO frame with unexpected encryption level: %s", encLevel))
	}
}

func (m *cryptoStreamManager) GetPostHandshakeData(maxSize protocol.ByteCount) *wire.CryptoFrame {
	if !m.oneRTTStream.HasData() {
		return nil
	}
	return m.oneRTTStream.PopCryptoFrame(maxSize)
}

func (m *cryptoStreamManager) Finish(encLevel protocol.EncryptionLevel) error {
	//nolint:exhaustive // The 1-RTT CRYPTO stream is never finished.
	switch encLevel {
	case protocol.EncryptionInitial:
		return m.initialStream.Finish()
	case protocol.EncryptionHandshake:
		return m.handshakeStream.Finish()
	default:
		panic(fmt.Sprintf("finished unexpected encryption level: %s", encLevel))
	}
}

// Write queues outgoing CRYPTO data. TLS writes precede discard of their level.
func (m *cryptoStreamManager) Write(level protocol.EncryptionLevel, data []byte) error {
	var err error
	//nolint:exhaustive // CRYPTO frames cannot be sent in 0-RTT packets.
	switch level {
	case protocol.EncryptionInitial:
		_, err = m.initialStream.Write(data)
	case protocol.EncryptionHandshake:
		_, err = m.handshakeStream.Write(data)
	case protocol.Encryption1RTT:
		_, err = m.oneRTTStream.Write(data)
	default:
		panic(fmt.Sprintf("wrote CRYPTO data with unexpected encryption level: %s", level))
	}
	return err
}

// HasData returns false for discarded encryption levels.
func (m *cryptoStreamManager) HasData(level protocol.EncryptionLevel) bool {
	//nolint:exhaustive // CRYPTO frames cannot be sent in 0-RTT packets.
	switch level {
	case protocol.EncryptionInitial:
		return m.initialStream != nil && m.initialStream.HasData()
	case protocol.EncryptionHandshake:
		return m.handshakeStream != nil && m.handshakeStream.HasData()
	case protocol.Encryption1RTT:
		return m.oneRTTStream.HasData()
	default:
		return false
	}
}

// PopCryptoFrame returns nil for discarded encryption levels.
func (m *cryptoStreamManager) PopCryptoFrame(level protocol.EncryptionLevel, maxLen protocol.ByteCount) *wire.CryptoFrame {
	//nolint:exhaustive // CRYPTO frames cannot be sent in 0-RTT packets.
	switch level {
	case protocol.EncryptionInitial:
		if m.initialStream != nil {
			return m.initialStream.PopCryptoFrame(maxLen)
		}
	case protocol.EncryptionHandshake:
		if m.handshakeStream != nil {
			return m.handshakeStream.PopCryptoFrame(maxLen)
		}
	case protocol.Encryption1RTT:
		return m.oneRTTStream.PopCryptoFrame(maxLen)
	}
	return nil
}

// Drop releases stream ownership, not storage still owned by an outgoing frame.
// Finish remains the earlier receive-validation transition.
func (m *cryptoStreamManager) Drop(level protocol.EncryptionLevel) {
	//nolint:exhaustive // Only Initial and Handshake streams are discarded.
	switch level {
	case protocol.EncryptionInitial:
		m.initialStream = nil
	case protocol.EncryptionHandshake:
		m.handshakeStream = nil
	default:
		panic(fmt.Sprintf("dropped unexpected encryption level: %s", level))
	}
}
