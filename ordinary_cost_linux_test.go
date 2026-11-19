//go:build ordinarycost && linux && amd64

package quic

import (
	"errors"
	"os"
	"regexp"
	"strconv"
)

// The Linux profile grants through the public API that its multipath support qualifies.
var ordinaryCostHost = ordinaryCostLinuxAMD64

func ordinaryCostGrant(tr *Transport) error {
	return tr.ConfigureMultipathIOV1(ordinaryCostWriteBudget)
}

var ordinaryCostHWM = regexp.MustCompile(`VmHWM:\s+(\d+) kB`)

// ordinaryCostPeakRSS reads VmHWM, in kB. getrusage's ru_maxrss would also be kB here, but
// Linux carries it across execve, so a role launched from the Python driver would report
// the driver's high-water mark.
func ordinaryCostPeakRSS() (ordinaryCostMetric, error) {
	status, err := os.ReadFile("/proc/self/status")
	if err != nil {
		return ordinaryCostMetric{}, err
	}
	match := ordinaryCostHWM.FindSubmatch(status)
	if match == nil {
		return ordinaryCostMetric{}, errors.New("no VmHWM")
	}
	kb, err := strconv.ParseUint(string(match[1]), 10, 64)
	if err != nil {
		return ordinaryCostMetric{}, err
	}
	return ordinaryCostRSSMetric(kb, "kB", "/proc/self/status VmHWM")
}
