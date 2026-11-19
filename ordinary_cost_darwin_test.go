//go:build ordinarycost && darwin && arm64

package quic

import "syscall"

// The Darwin profile grants through the public API that its Darwin 27 arm64 support
// admits. On a Darwin release outside that support the public grant refuses.
var ordinaryCostHost = ordinaryCostDarwinARM64

func ordinaryCostGrant(tr *Transport) error {
	return tr.ConfigureMultipathIOV1(ordinaryCostWriteBudget)
}

const ordinaryCostRSSSource = "getrusage(RUSAGE_SELF).ru_maxrss"

// ordinaryCostPeakRSS reads ru_maxrss, which Darwin reports in bytes and does not carry
// across exec or spawn.
func ordinaryCostPeakRSS() (ordinaryCostMetric, error) {
	var usage syscall.Rusage
	if err := syscall.Getrusage(syscall.RUSAGE_SELF, &usage); err != nil {
		return ordinaryCostMetric{}, err
	}
	return ordinaryCostRSSMetric(uint64(usage.Maxrss), "bytes", ordinaryCostRSSSource)
}
