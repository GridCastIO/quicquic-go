//go:build !darwin

package quic

// multipathKernelMajor has no meaning off Darwin: the platform partition admits Linux amd64
// without a kernel release.
func multipathKernelMajor() (int, error) { return 0, nil }
