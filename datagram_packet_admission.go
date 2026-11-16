package quic

import (
	"io"

	"github.com/quic-go/quic-go/internal/protocol"
)

// admitDatagramPacket runs after authentication and duplicate detection, before
// any frame handling or acknowledgment. The connection goroutine is the only
// receive-queue producer; concurrent application reads can only make more room.
// The encrypted backlog's one-payload estimate is insufficient for packed jumbo
// packets, so weigh those packets by their actual DATAGRAM count here.
func (c *Conn) admitDatagramPacket(data []byte, encLevel protocol.EncryptionLevel) (bool, error) {
	if !c.config.EnableDatagrams || c.packetCeiling.size() <= protocol.MaxPacketBufferSize ||
		(encLevel != protocol.Encryption0RTT && encLevel != protocol.Encryption1RTT) {
		return true, nil
	}
	room := maxDatagramRcvQueueLen - c.datagramQueue.receiveQueueLen()
	// Even an empty DATAGRAM consumes a type byte. Avoid a second parse when
	// the remaining capacity can hold every possible frame in this payload.
	if len(data) <= room {
		return true, nil
	}
	count := 0
	for len(data) > 0 {
		typ, n, err := c.frameParser.ParseType(data, encLevel)
		if err == io.EOF {
			break
		}
		if err != nil {
			return false, err
		}
		data = data[n:]
		switch {
		case typ.IsDatagramFrameType():
			_, n, err = c.frameParser.ParseDatagramFrame(typ, data, c.version)
			count++
		case typ.IsStreamFrameType():
			n, err = c.frameParser.SkipStreamFrame(typ, data, c.version)
		case typ.IsAckFrameType():
			_, n, err = c.frameParser.ParseAckFrame(typ, data, encLevel, c.version)
		default:
			_, n, err = c.frameParser.ParseLessCommonFrame(typ, data, c.version)
		}
		if err != nil {
			return false, err
		}
		data = data[n:]
	}
	return count <= room, nil
}
