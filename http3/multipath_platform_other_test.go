//go:build linux || freebsd

package http3

import "testing"

func testDarwinKernelMajor(t *testing.T) int {
	t.Helper()
	t.Fatal("no Darwin kernel off Darwin")
	return 0
}
