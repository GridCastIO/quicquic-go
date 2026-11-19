//go:build ordinarycost && darwin && arm64

package quic

import "syscall"

// The Darwin profile grants through the private native seam: public multipath admission
// is closed here, so these ordinary workloads never claim negotiated multipath.
var ordinaryCostHost = ordinaryCostDarwinARM64

func ordinaryCostGrant(tr *Transport) error {
	return tr.configureNativeIO(ordinaryCostWriteBudget)
}

// ordinaryCostPeakRSS reads ru_maxrss, which Darwin reports in bytes and does not carry
// across exec or spawn.
func ordinaryCostPeakRSS() (ordinaryCostMetric, error) {
	var usage syscall.Rusage
	if err := syscall.Getrusage(syscall.RUSAGE_SELF, &usage); err != nil {
		return ordinaryCostMetric{}, err
	}
	return ordinaryCostRSSMetric(uint64(usage.Maxrss), "bytes", "getrusage(RUSAGE_SELF).ru_maxrss")
}
