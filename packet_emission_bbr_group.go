package quic

import (
	"github.com/quic-go/quic-go/internal/monotime"
	"github.com/quic-go/quic-go/internal/protocol"
)

// groupBoundedNative can append one more ordinary buffer to this call's native
// request. Each buffer retains its own credit and protection plan; the outer
// send's finish seals the request on every exit. No builder crosses a call.
func (e *packetEmission) groupBoundedNative(now monotime.Time, size protocol.ByteCount, first emissionResult) emissionResult {
	if e.local == nil || e.pathCredit != nil || e.route != nil || !first.progress || first.err != nil || first.supplyExhausted || first.deadline != deadlineSendImmediately {
		return first
	}
	if e.policy.emissionClosePending() {
		return first
	}
	if e.policy.emissionReceivePending() {
		first.stop = emissionReceivePending
		return first
	}
	if e.queue.WouldBlock() {
		return emissionResult{progress: true, stop: emissionQueueFull, available: e.queue.Available(), blocked: blockModeHardBlocked}
	}
	mode, allowance := e.selected().(boundedRecovery).SendAllowance(now)
	// The first decision already handled probe/handshake/control intent. Do not
	// consume new intent or execute an exempt second turn here. An immediate
	// continuation gives that decision back to the full connection loop.
	p := e.routePolicy()
	plan := e.planBounded(nil, p, mode, allowance, size, nil, false, true, now)
	if plan.step != stepSend {
		return first
	}
	// Reuse the opportunity timestamp and balance: construction time supplies no
	// additional pacing credit. Only the first call prepares the controller.
	if !e.reserveLocal(plan.request, true, false, now) {
		// A refusal may admit an exempt ACK. Seal the ordinary prefix first, so
		// that control turn keeps its own request and original wakeup semantics.
		e.local.finish()
		if e.queue.WouldBlock() {
			return emissionResult{progress: true, stop: emissionQueueFull, available: e.queue.Available(), blocked: blockModeHardBlocked}
		}
		next := e.waitForReservation(now, true, size, plan.request, true, false)
		next.progress = next.progress || first.progress
		return next
	}
	next := e.boundedDatagrams(now, size, plan.request)
	next.progress = next.progress || first.progress
	return next
}
