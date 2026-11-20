//go:build darwin

package http3

import (
	"strconv"
	"strings"
	"syscall"
	"testing"

	"github.com/stretchr/testify/require"
)

// testDarwinKernelMajor reads kern.osrelease through sysctl, independently of the quic
// package's uname reader.
func testDarwinKernelMajor(t *testing.T) int {
	t.Helper()
	release, err := syscall.Sysctl("kern.osrelease")
	require.NoError(t, err)
	major, _, _ := strings.Cut(release, ".")
	n, err := strconv.Atoi(major)
	require.NoError(t, err, "kern.osrelease %q", release)
	return n
}
