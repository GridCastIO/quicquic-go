package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/netip"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"github.com/GridCastIO/quicquic-go/interop/multipath/relay"

	"github.com/stretchr/testify/require"
)

const processEnv = "UDPRELAY_TEST_PROCESS"

// TestMain lets the tests run this binary as the relay process.
func TestMain(m *testing.M) {
	if os.Getenv(processEnv) == "1" {
		os.Exit(main1())
	}
	os.Exit(m.Run())
}

type relayProcess struct {
	cmd    *exec.Cmd
	stdin  io.WriteCloser
	stdout *bufio.Reader
	stderr *os.File
}

func startProcess(t *testing.T, args ...string) *relayProcess {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	t.Cleanup(cancel)
	cmd := exec.CommandContext(ctx, os.Args[0], args...)
	cmd.Env = append(os.Environ(), processEnv+"=1")
	stderr, err := os.Create(filepath.Join(t.TempDir(), "stderr"))
	require.NoError(t, err)
	t.Cleanup(func() { stderr.Close() })
	cmd.Stderr = stderr
	stdin, err := cmd.StdinPipe()
	require.NoError(t, err)
	stdout, err := cmd.StdoutPipe()
	require.NoError(t, err)
	require.NoError(t, cmd.Start())
	// The context kills a process the test leaves running; Wait reaps it.
	t.Cleanup(func() {
		stdin.Close()
		cmd.Wait()
	})
	return &relayProcess{cmd: cmd, stdin: stdin, stdout: bufio.NewReader(stdout), stderr: stderr}
}

func (p *relayProcess) stderrText(t *testing.T) string {
	t.Helper()
	b, err := os.ReadFile(p.stderr.Name())
	require.NoError(t, err)
	return string(b)
}

func writeConfig(t *testing.T, cfg any) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "config.json")
	b, err := json.Marshal(cfg)
	require.NoError(t, err)
	require.NoError(t, os.WriteFile(path, b, 0o644))
	return path
}

func disjointConfig(server netip.AddrPort) relay.Config {
	front := netip.MustParseAddrPort("127.0.0.1:0")
	q := relay.Queue{RateBPS: 8_000_000, LimitBytes: 20_000}
	return relay.Config{
		Kind: relay.KindDisjoint, Server: server,
		Queues: []relay.Queue{q, q},
		Routes: []relay.Route{
			{Name: relay.RouteA, Front: front, Queue: 0, DelayNS: int64(time.Millisecond)},
			{Name: relay.RouteB, Front: front, Queue: 1, DelayNS: int64(time.Millisecond)},
		},
	}
}

// The process reports its bound fronts, relays until its stdin closes, joins its
// workers, writes a record that reads back, and exits zero.
func TestProcessRelaysAndWritesRecord(t *testing.T) {
	server, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	require.NoError(t, err)
	t.Cleanup(func() { server.Close() })
	serverAddr := server.LocalAddr().(*net.UDPAddr).AddrPort()
	recordPath := filepath.Join(t.TempDir(), "relay.json")
	p := startProcess(t, "-config", writeConfig(t, disjointConfig(serverAddr)), "-record", recordPath)

	line, err := p.stdout.ReadBytes('\n')
	require.NoError(t, err, p.stderrText(t))
	var ready readyLine
	require.NoError(t, json.Unmarshal(line, &ready))
	require.Equal(t, relay.RecordVersion, ready.Version)
	require.Len(t, ready.Fronts, 2)

	client, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	require.NoError(t, err)
	t.Cleanup(func() { client.Close() })
	_, err = client.WriteToUDPAddrPort([]byte("hello"), ready.Fronts[relay.RouteA])
	require.NoError(t, err)
	require.NoError(t, server.SetReadDeadline(time.Now().Add(5*time.Second)))
	buf := make([]byte, 16)
	n, _, err := server.ReadFromUDP(buf)
	require.NoError(t, err)
	require.Equal(t, "hello", string(buf[:n]))

	require.NoError(t, p.stdin.Close())
	require.NoError(t, p.cmd.Wait(), p.stderrText(t))
	f, err := os.Open(recordPath)
	require.NoError(t, err)
	defer f.Close()
	rec, err := relay.ReadRecord(f)
	require.NoError(t, err)
	require.Equal(t, ready.Fronts[relay.RouteA], rec.Routes[0].Front)
	require.Equal(t, uint64(1), rec.Routes[0].Forward.Delivered)
	for _, front := range ready.Fronts {
		conn, err := net.ListenUDP("udp4", net.UDPAddrFromAddrPort(front))
		require.NoError(t, err, "the exited process released its fronts")
		conn.Close()
	}
}

// A process that cannot start the relay exits nonzero before reporting ready and
// leaves no record.
func TestProcessRefusesWithoutRecord(t *testing.T) {
	server := netip.MustParseAddrPort("127.0.0.1:4433")
	invalid := disjointConfig(server)
	invalid.Routes[1].Queue = 0
	existing := filepath.Join(t.TempDir(), "existing.json")
	require.NoError(t, os.WriteFile(existing, []byte("{}"), 0o644))

	for _, tc := range []struct {
		name   string
		args   func(record string) []string
		want   string
		record string
	}{
		{"invalid config", func(record string) []string {
			return []string{"-config", writeConfig(t, invalid), "-record", record}
		}, "separate queues", ""},
		{"unknown config field", func(record string) []string {
			return []string{"-config", writeConfig(t, map[string]any{"kind": "shared", "extra": 1}), "-record", record}
		}, "unknown field", ""},
		{"existing record", func(string) []string {
			return []string{"-config", writeConfig(t, disjointConfig(server)), "-record", existing}
		}, "already exists", existing},
		{"missing flags", func(string) []string { return nil }, "-config and -record are required", ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			record := filepath.Join(t.TempDir(), "relay.json")
			p := startProcess(t, tc.args(record)...)
			out, err := io.ReadAll(p.stdout)
			require.NoError(t, err)
			require.Empty(t, out, "no ready line")
			err = p.cmd.Wait()
			var exit *exec.ExitError
			require.ErrorAs(t, err, &exit)
			require.NotZero(t, exit.ExitCode())
			require.Contains(t, p.stderrText(t), tc.want)
			if tc.record == "" {
				require.NoFileExists(t, record)
			} else {
				b, err := os.ReadFile(tc.record)
				require.NoError(t, err)
				require.Equal(t, "{}", string(b), "an existing record is left alone")
			}
		})
	}
}

// A record that appears at the destination while the relay runs survives: publication
// fails, the process exits nonzero and leaves no temporary file.
func TestProcessKeepsRecordThatAppeared(t *testing.T) {
	dir := t.TempDir()
	recordPath := filepath.Join(dir, "relay.json")
	p := startProcess(t, "-config", writeConfig(t, disjointConfig(netip.MustParseAddrPort("127.0.0.1:4433"))), "-record", recordPath)
	_, err := p.stdout.ReadBytes('\n')
	require.NoError(t, err, p.stderrText(t))
	require.NoError(t, os.WriteFile(recordPath, []byte("sentinel"), 0o644))

	require.NoError(t, p.stdin.Close())
	var exit *exec.ExitError
	require.ErrorAs(t, p.cmd.Wait(), &exit)
	require.Contains(t, p.stderrText(t), "publishing record")
	b, err := os.ReadFile(recordPath)
	require.NoError(t, err)
	require.Equal(t, "sentinel", string(b))
	entries, err := os.ReadDir(dir)
	require.NoError(t, err)
	require.Len(t, entries, 1, "no temporary record remains")
}

type failingReader struct{}

func (failingReader) Read([]byte) (int, error) { return 0, errors.New("stdin broke") }

// A stdin read error is not a stop request: the relay is closed and joined, the error
// is returned and no record is published.
func TestRunStdinErrorPublishesNothing(t *testing.T) {
	recordPath := filepath.Join(t.TempDir(), "relay.json")
	var stdout bytes.Buffer
	err := run(context.Background(), []string{
		"-config", writeConfig(t, disjointConfig(netip.MustParseAddrPort("127.0.0.1:4433"))), "-record", recordPath,
	}, failingReader{}, &stdout)
	require.ErrorContains(t, err, "stdin broke")
	require.NoFileExists(t, recordPath)
	var ready readyLine
	require.NoError(t, json.Unmarshal(stdout.Bytes(), &ready))
	for _, front := range ready.Fronts {
		conn, err := net.ListenUDP("udp4", net.UDPAddrFromAddrPort(front))
		require.NoError(t, err, "the relay was closed")
		conn.Close()
	}
}
