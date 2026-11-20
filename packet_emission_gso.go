package quic

import (
	"os"
	"runtime"
	"strconv"

	"github.com/GridCastIO/quicquic-go/internal/ackhandler"
	"github.com/GridCastIO/quicquic-go/internal/protocol"
	"github.com/GridCastIO/quicquic-go/internal/wire"
)

// maxGSOSegments bounds the packets in one segmented send. Linux before 6.9
// rejects more than 64 (UDP_MAX_SEGMENTS) with EINVAL.
const maxGSOSegments = 64

// The IPv4 UDP payload bound also keeps IPv6 segmented sends conservative.
const maxGSOUDPPayload = 65507

// largeNativeBBRGSO uses the current packet size, including a jumbo-configured
// path still sending standard packets. Active jumbo paths keep their old tier.
func (e *packetEmission) largeNativeBBRGSO(route *pathRoute, size protocol.ByteCount) bool {
	return e.bbr != nil && e.local != nil && e.queue == e.local && e.pathCredit == nil && route == nil && size <= protocol.MaxPacketBufferSize
}

// softwareBBRSegmentsOn reports whether an ordinary BBR plan on route builds
// largeNativeBBRGSO's multi-packet member as software segments: the platform
// has none of the wire GSO that boundedGSOOn requires. The member keeps the
// same pacing budget, whole-packet credit range, single handoff and deferred
// writer protection. The writer submits each segment as its own datagram, or
// several per call through #1589's sendmsg_x batch where private syscalls are
// built in.
func (e *packetEmission) softwareBBRSegmentsOn(route *pathRoute, size protocol.ByteCount) bool {
	return e.softwareBBRSegments && e.largeNativeBBRGSO(route, size) && !e.opportunityCapabilities().GSO
}

// boundedSegmentsOn reports whether a BBR opportunity on route may build more
// than one size-byte packet into its member: segmented by wire GSO, or by
// Darwin's software segments (#1590). The plan, the packing loop and the
// protected-buffer tier all read this one predicate.
func (e *packetEmission) boundedSegmentsOn(route *pathRoute, size protocol.ByteCount) bool {
	return e.boundedGSOOn(route) || e.softwareBBRSegmentsOn(route, size)
}

func (e *packetEmission) boundedGSOSendLimit(route *pathRoute, size protocol.ByteCount) protocol.ByteCount {
	if e.largeNativeBBRGSO(route, size) {
		return maxGSOUDPPayload
	}
	return gsoPacketSendLimit(size)
}

// gsoPacketBufferSize keeps standard-size batches at the existing limit.
// Only Linux jumbo segments use the existing 64 KiB tier.
func gsoPacketBufferSize(size protocol.ByteCount) protocol.ByteCount {
	if runtime.GOOS == "linux" && size > protocol.MaxPacketBufferSize {
		return protocol.MaxCoalescedPacketBufferSize
	}
	return protocol.MaxLargePacketBufferSize
}

// gsoPacketSendLimit separates usable UDP payload from storage capacity.
// Linux IPv4 leaves 20 bytes for IP and 8 for UDP in the 65535-byte limit;
// using that bound for IPv6 too keeps the shared send path conservative.
func gsoPacketSendLimit(size protocol.ByteCount) protocol.ByteCount {
	capacity := gsoPacketBufferSize(size)
	if capacity == protocol.MaxCoalescedPacketBufferSize {
		return maxGSOUDPPayload
	}
	return capacity
}

func getGSOPacketBuffer(size protocol.ByteCount) *packetBuffer {
	if gsoPacketBufferSize(size) == protocol.MaxCoalescedPacketBufferSize {
		return getCoalescedPacketBuffer()
	}
	return getLargePacketBuffer()
}

// disableShortGSOSegmentsEnv names the switch that turns off equal-size
// batching of short DATAGRAM packets, keeping segmented send at the maximum
// packet size only.
const disableShortGSOSegmentsEnv = "QUIC_GO_DISABLE_SHORT_GSO_SEGMENTS"

// shortGSOSegmentsEnabled reports whether a short DATAGRAM packet may set a
// batch's segment size; QUIC_GO_DISABLE_SHORT_GSO_SEGMENTS=true turns it off.
func shortGSOSegmentsEnabled() bool {
	disabled, err := strconv.ParseBool(os.Getenv(disableShortGSOSegmentsEnv))
	return err != nil || !disabled
}

// gsoBatch decides how one segmented-send buffer grows. Linux GSO and Windows
// USO cut the buffer into equal segments, where only the last may be shorter,
// so every packet is packed with the segment size as its limit before it is
// appended.
//
// The first packet, packed at the maximum size, sets the segment size. After a
// full-size first packet the batch continues with ordinary packets while they
// come out full size. After a shorter one that carries a DATAGRAM frame, it
// continues with packets that each carry only the next DATAGRAM frame, while
// they come out exactly the segment size. Stream data and control frames are
// therefore never packed at a short size: they start the next batch.
type gsoBatch struct {
	maxSize protocol.ByteCount
	short   bool // a short DATAGRAM packet may set the segment size
	segment protocol.ByteCount
	packets int
}

func newGSOBatch(maxSize protocol.ByteCount, short bool) gsoBatch {
	return gsoBatch{maxSize: maxSize, short: short}
}

// next returns the size limit for the next packet and whether that packet must
// carry only a DATAGRAM frame.
func (b *gsoBatch) next() (protocol.ByteCount, bool) {
	if b.packets == 0 {
		return b.maxSize, false
	}
	return b.segment, b.segment < b.maxSize
}

// add records a packed packet and reports whether another may follow it.
func (b *gsoBatch) add(size protocol.ByteCount, frames []ackhandler.Frame) bool {
	b.packets++
	if b.packets >= maxGSOSegments {
		return false
	}
	if b.packets > 1 {
		return size == b.segment
	}
	b.segment = size
	return size == b.maxSize || b.short && carriesDatagram(frames)
}

// fits reports whether a packet of the segment size fits after used bytes
// within limit.
func (b *gsoBatch) fits(used, limit protocol.ByteCount) bool {
	return used+b.segment <= limit
}

// gsoSize is the segment size for the handoff. A lone packet takes the
// ordinary socket path, without a segment size.
func (b *gsoBatch) gsoSize() uint16 {
	if b.packets < 2 {
		return 0
	}
	return uint16(b.segment)
}

func carriesDatagram(frames []ackhandler.Frame) bool {
	for _, f := range frames {
		if _, ok := f.Frame.(*wire.DatagramFrame); ok {
			return true
		}
	}
	return false
}
