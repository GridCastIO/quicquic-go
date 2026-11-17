// Package http3 implements HTTP/3 (RFC 9114), including QPACK (RFC 9204) and
// HTTP Datagrams (RFC 9297), on the QUIC transport of quicquic-go, an
// independently maintained QUIC and HTTP/3 implementation in Go, focused on
// transport performance and practical application integration.
//
// Its import path is github.com/GridCastIO/quicquic-go/http3. Applications
// that inspect errors should use errors.As and errors.Is with *Error, as the
// package README describes.
package http3
