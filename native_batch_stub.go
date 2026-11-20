//go:build unix && (!darwin || ios || quic_go_no_private_syscalls)

package quic

// Stub half of the native_batch_darwin.go pair: builds without the private
// sendmsg_x path have no batch hook, so the granted writer stays scalar.
type nativeSegmentBatch struct{}

func newNativeSegmentBatch(endpointNativeIO) *nativeSegmentBatch { return nil }

func (*nativeSegmentBatch) writeSegments(_ *endpointToken, _ endpointMember, data []byte, _ int, _ *endpointMemberResult) (rest []byte, again, stop bool) {
	return data, false, false
}
