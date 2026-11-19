//go:build darwin && !nativequal

package quic

// Ordinary Darwin test builds omit the forced-traversal blocked-writer cases.
const nativeDarwinTraversal = false
