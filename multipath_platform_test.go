package quic

import (
	"errors"
	"runtime"
	"testing"

	"github.com/stretchr/testify/require"
)

// expectedMultipathProfile states the qualified public profile independently of the
// production gate: Linux amd64, and Darwin arm64 running Darwin 27 (macOS 27). The Darwin
// kernel release comes from sysctl, not from the production uname reader, so a wrong gate
// fails these tests instead of skipping them.
func expectedMultipathProfile(t *testing.T) bool {
	t.Helper()
	switch runtime.GOOS + "/" + runtime.GOARCH {
	case "linux/amd64":
		return true
	case "darwin/arm64":
		return testDarwinKernelMajor(t) == 27
	default:
		return false
	}
}

// The partition is complete for its declared semantic classes: each admitted tuple, each
// neighbor that differs in one coordinate, iOS, unknown majors and an unreadable kernel.
func TestMultipathPlatformAdmission(t *testing.T) {
	unreadable := errors.New("uname failed")
	for _, tc := range []struct {
		name           string
		goos, goarch   string
		major          int
		err            error
		expectAdmitted bool
	}{
		{"linux amd64", "linux", "amd64", 0, nil, true},
		{"linux amd64 ignores the kernel reader", "linux", "amd64", 6, unreadable, true},
		{"linux arm64", "linux", "arm64", 0, nil, false},
		{"linux 386", "linux", "386", 0, nil, false},
		{"darwin 27 arm64", "darwin", "arm64", 27, nil, true},
		{"darwin 26 arm64", "darwin", "arm64", 26, nil, false},
		{"darwin 25 arm64", "darwin", "arm64", 25, nil, false},
		{"darwin 28 arm64", "darwin", "arm64", 28, nil, false},
		{"darwin unparsed release", "darwin", "arm64", 0, nil, false},
		{"darwin unreadable kernel", "darwin", "arm64", 27, unreadable, false},
		{"darwin 27 amd64", "darwin", "amd64", 27, nil, false},
		{"ios 27 arm64", "ios", "arm64", 27, nil, false},
		{"freebsd amd64", "freebsd", "amd64", 0, nil, false},
		{"windows amd64", "windows", "amd64", 0, nil, false},
		{"android arm64", "android", "arm64", 0, nil, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			require.Equal(t, tc.expectAdmitted, multipathPlatformAdmitted(tc.goos, tc.goarch, tc.major, tc.err))
		})
	}
}

// The production gate on this process agrees with the independent statement above.
func TestMultipathPlatformMatchesExpectation(t *testing.T) {
	require.Equal(t, expectedMultipathProfile(t), multipathProfileSupported(),
		"%s/%s: production admission differs from the qualified profile", runtime.GOOS, runtime.GOARCH)
}
