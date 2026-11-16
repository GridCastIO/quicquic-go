// Command heap is the bounded retained-server-heap experiment for issue #1411.
package main

import (
	"bufio"
	"context"
	"crypto/tls"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"runtime"
	"runtime/pprof"
	"time"

	quic "github.com/quic-go/quic-go"
	"github.com/quic-go/quic-go/internal/testdata"
)

func check(err error) {
	if err != nil {
		panic(err)
	}
}

func snapshot() runtime.MemStats {
	runtime.GC()
	runtime.GC()
	var m runtime.MemStats
	runtime.ReadMemStats(&m)
	return m
}

func main() {
	count := flag.Int("connections", 1000, "persistent connections")
	peer := flag.String("peer", "", "client subprocess target")
	profile := flag.String("profile", "", "server heap profile")
	flag.Parse()
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Minute)
	defer cancel()
	config := &quic.Config{MaxIdleTimeout: 2 * time.Minute, DisablePathMTUDiscovery: true}
	if *peer != "" {
		client(ctx, *peer, *count, config)
		return
	}
	tlsConfig := testdata.GetTLSConfig()
	tlsConfig.NextProtos = []string{"crypto-stream-1411"}
	listener, err := quic.ListenAddr("127.0.0.1:0", tlsConfig, config)
	check(err)
	defer listener.Close()
	executable, err := os.Executable()
	check(err)
	child := exec.CommandContext(ctx, executable, "-peer", listener.Addr().String(), "-connections", fmt.Sprint(*count))
	child.Stderr = os.Stderr
	input, err := child.StdinPipe()
	check(err)
	output, err := child.StdoutPipe()
	check(err)
	check(child.Start())
	childDone := make(chan error, 1)
	go func() {
		err := child.Wait()
		childDone <- err
		if err != nil {
			cancel()
		}
	}()
	scanner := bufio.NewScanner(output)
	if !scanner.Scan() || scanner.Text() != "waiting" {
		panic("client did not start")
	}
	empty := snapshot()
	_, err = fmt.Fprintln(input, "start")
	check(err)
	connections := make([]*quic.Conn, 0, *count)
	for range *count {
		c, err := listener.Accept(ctx)
		check(err)
		connections = append(connections, c)
		stream, err := c.AcceptStream(ctx)
		check(err)
		data, err := io.ReadAll(stream)
		check(err)
		if string(data) != "ping" {
			panic("incorrect request")
		}
		_, err = stream.Write([]byte("pong"))
		check(err)
		check(stream.Close())
	}
	if !scanner.Scan() || scanner.Text() != "ready" {
		panic("client did not finish exchanges")
	}
	time.Sleep(5 * time.Second)
	for _, c := range connections {
		check(context.Cause(c.Context()))
	}
	full := snapshot()
	check(json.NewEncoder(os.Stdout).Encode(map[string]any{
		"connections": *count, "go": runtime.Version(), "os": runtime.GOOS, "arch": runtime.GOARCH,
		"empty_heap": empty.HeapAlloc, "retained_heap": full.HeapAlloc,
		"connection_heap": int64(full.HeapAlloc) - int64(empty.HeapAlloc),
		"empty_objects":   empty.HeapObjects, "retained_objects": full.HeapObjects,
	}))
	if *profile != "" {
		f, err := os.Create(*profile)
		check(err)
		check(pprof.WriteHeapProfile(f))
		check(f.Close())
	}
	runtime.KeepAlive(connections)
	_, err = fmt.Fprintln(input, "stop")
	check(err)
	check(<-childDone)
	for _, c := range connections {
		check(c.CloseWithError(0, "done"))
	}
}

func client(ctx context.Context, addr string, count int, config *quic.Config) {
	scanner := bufio.NewScanner(os.Stdin)
	fmt.Println("waiting")
	if !scanner.Scan() || scanner.Text() != "start" {
		panic("missing start")
	}
	socket, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	check(err)
	defer socket.Close()
	transport := &quic.Transport{Conn: socket}
	defer transport.Close()
	remote, err := net.ResolveUDPAddr("udp4", addr)
	check(err)
	tlsConfig := &tls.Config{RootCAs: testdata.GetRootCA(), ServerName: "localhost", NextProtos: []string{"crypto-stream-1411"}, MinVersion: tls.VersionTLS13}
	connections := make([]*quic.Conn, 0, count)
	for range count {
		c, err := transport.Dial(ctx, remote, tlsConfig, config)
		check(err)
		connections = append(connections, c)
		stream, err := c.OpenStreamSync(ctx)
		check(err)
		_, err = stream.Write([]byte("ping"))
		check(err)
		check(stream.Close())
		response, err := io.ReadAll(stream)
		check(err)
		if string(response) != "pong" {
			panic("incorrect response")
		}
	}
	fmt.Println("ready")
	if !scanner.Scan() || scanner.Text() != "stop" {
		panic("missing stop")
	}
	runtime.KeepAlive(connections)
	for _, c := range connections {
		check(c.CloseWithError(0, "done"))
	}
}
