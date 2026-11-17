//go:build !darwin && !linux && !freebsd && !windows

package quic

import (
	"net"

	"github.com/GridCastIO/quicquic-go/internal/protocol"
)

func appendExternalECN(oob []byte, _ *net.UDPAddr, _ protocol.ECN) []byte { return oob }
