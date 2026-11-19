//go:build darwin && nativequal

package quic

// nativeDarwinTraversal registers the forced-traversal blocked-writer cases. Only the
// nativequal tag, which the case runner's blocked-writer profile selects, builds them.
const nativeDarwinTraversal = true
