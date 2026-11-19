//go:build picoquic

package quic

import (
	"bytes"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"strconv"
	"strings"
)

// The independent peer's DATAGRAM callback owns actual ingress facts: it emits
// one finite record per callback, carrying picoquic's callback path rather than
// any requested or echoed path. The aggregate witness below owns phase and
// payload membership and acceptance. Go sender counters stay separate
// scheduling evidence and never stand in for a receipt.
const (
	matrixIngressPrefix = "ingress "
	matrixIngressHead   = 16 // payload bytes the peer reports
	matrixWitnessLength = 32
)

// matrixWitnessTag fills each witness payload after its marker, nonce and
// sequence. The echo payloads start with a path byte, never 'W'.
var matrixWitnessTag = []byte("Wqgf-p2-ingress-witness-payload!")

type matrixIngressReceipt struct {
	Path   uint64
	Length int
	Head   []byte
}

// matrixIngressRecordLine is the record peer.c emits for payload received on path.
func matrixIngressRecordLine(path uint64, payload []byte) string {
	return fmt.Sprintf("ingress v1 datagram path %d length %d head %x", path, len(payload), payload[:min(len(payload), matrixIngressHead)])
}

// parseMatrixIngressRecord reads exactly the shape matrixIngressRecordLine
// produces. Standard parsers own the number and hex syntax.
func parseMatrixIngressRecord(line string) (matrixIngressReceipt, error) {
	fields := strings.Split(line, " ")
	if len(fields) != 9 || fields[0] != "ingress" || fields[1] != "v1" || fields[2] != "datagram" ||
		fields[3] != "path" || fields[5] != "length" || fields[7] != "head" {
		return matrixIngressReceipt{}, fmt.Errorf("unknown ingress record %q", line)
	}
	path, err := strconv.ParseUint(fields[4], 10, 64)
	if err != nil {
		return matrixIngressReceipt{}, fmt.Errorf("ingress record path: %w", err)
	}
	length, err := strconv.Atoi(fields[6])
	if err != nil || length <= 0 {
		return matrixIngressReceipt{}, fmt.Errorf("ingress record length %q", fields[6])
	}
	head, err := hex.DecodeString(fields[8])
	if err != nil {
		return matrixIngressReceipt{}, fmt.Errorf("ingress record head: %w", err)
	}
	if len(head) != min(length, matrixIngressHead) {
		return matrixIngressReceipt{}, fmt.Errorf("ingress record head has %d bytes for length %d", len(head), length)
	}
	return matrixIngressReceipt{Path: path, Length: length, Head: head}, nil
}

// matrixIngressWitness is one aggregate phase: a fresh nonce, the peer record
// cursor at activation, the bounded offer rounds with their observed path
// eligibility, and the phase-end observation.
type matrixIngressWitness struct {
	nonce       [8]byte
	start       int
	perRound    int
	offered     map[uint16]int // sequence → offer round
	rounds      []bool         // both paths live/active when the round was offered
	finished    bool
	endEligible bool
}

func newMatrixIngressWitness(nonce [8]byte, start, perRound int) *matrixIngressWitness {
	return &matrixIngressWitness{nonce: nonce, start: start, perRound: perRound, offered: make(map[uint16]int)}
}

func (w *matrixIngressWitness) payload(seq uint16) []byte {
	payload := bytes.Clone(matrixWitnessTag)
	copy(payload[1:9], w.nonce[:])
	binary.BigEndian.PutUint16(payload[9:11], seq)
	return payload
}

// offerRound records whether both paths were live and active and returns the
// round's fresh payloads. Callers bound the rounds well below 2^16 payloads.
func (w *matrixIngressWitness) offerRound(eligible bool) [][]byte {
	round := len(w.rounds)
	w.rounds = append(w.rounds, eligible)
	payloads := make([][]byte, w.perRound)
	for i := range payloads {
		seq := uint16(len(w.offered))
		w.offered[seq] = round
		payloads[i] = w.payload(seq)
	}
	return payloads
}

// finish records the phase-end eligibility observation.
func (w *matrixIngressWitness) finish(eligible bool) {
	w.finished, w.endEligible = true, eligible
}

type matrixIngressResult struct {
	Fresh       map[uint64]int // distinct fresh receipts by actual ingress path
	Duplicates  int            // repeated receipts of an already counted payload
	Excluded    int            // pre-activation, other-phase or non-witness receipts
	SenderDelta map[uint64]uint64
}

// member reports a receipt's sequence when it carries this phase's nonce. A
// current-nonce receipt that does not match an offered payload is an error.
func (w *matrixIngressWitness) member(r matrixIngressReceipt) (uint16, bool, error) {
	if len(r.Head) < 11 || r.Head[0] != matrixWitnessTag[0] || !bytes.Equal(r.Head[1:9], w.nonce[:]) {
		return 0, false, nil
	}
	seq := binary.BigEndian.Uint16(r.Head[9:11])
	if _, ok := w.offered[seq]; !ok {
		return 0, false, fmt.Errorf("witness sequence %d was never offered", seq)
	}
	if r.Length != matrixWitnessLength || !bytes.Equal(r.Head, w.payload(seq)[:matrixIngressHead]) {
		return 0, false, fmt.Errorf("witness sequence %d has a different payload", seq)
	}
	return seq, true, nil
}

// tally counts the peer's records. Each offered payload counts once, on the
// path of its first receipt.
func (w *matrixIngressWitness) tally(records []string) (matrixIngressResult, error) {
	result := matrixIngressResult{Fresh: make(map[uint64]int)}
	counted := make(map[uint16]bool)
	for i, line := range records {
		receipt, err := parseMatrixIngressRecord(line)
		if err != nil {
			return result, fmt.Errorf("record %d: %w", i, err)
		}
		if i < w.start {
			result.Excluded++
			continue
		}
		seq, member, err := w.member(receipt)
		if err != nil {
			return result, fmt.Errorf("record %d: %w", i, err)
		}
		switch {
		case !member:
			result.Excluded++
		case counted[seq]:
			result.Duplicates++
		default:
			counted[seq] = true
			result.Fresh[receipt.Path]++
		}
	}
	return result, nil
}

// accept requires both paths live and active in every offer round and at
// phase end, and a fresh receipt on each of paths zero and one. Sender deltas
// are reported but cannot satisfy acceptance.
func (w *matrixIngressWitness) accept(records []string, senderDelta map[uint64]uint64) (matrixIngressResult, error) {
	result, err := w.tally(records)
	result.SenderDelta = senderDelta
	if err != nil {
		return result, err
	}
	for round, eligible := range w.rounds {
		if !eligible {
			return result, fmt.Errorf("offer round %d lacked two live/active paths", round)
		}
	}
	if !w.finished || !w.endEligible {
		return result, errors.New("phase end lacked two live/active paths")
	}
	for _, id := range []uint64{0, 1} {
		if result.Fresh[id] == 0 {
			return result, fmt.Errorf("no fresh receipt on path %d (sender DATAGRAM delta %d bytes)", id, senderDelta[id])
		}
	}
	return result, nil
}
