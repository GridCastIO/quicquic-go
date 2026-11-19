//go:build darwin

package quic

// multipathKernelMajor reads the Darwin kernel major through the existing platform helper.
func multipathKernelMajor() (int, error) { return getMacOSVersion() }
