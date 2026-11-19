// Command udprelay runs one relay.Config as its own process, so a driver can attribute
// the relay's resource use separately from the endpoints it shapes.
//
//	udprelay -config config.json -record record.json
//
// The config is one JSON relay.Config. Once every route is bound, the process writes one
// JSON line to stdout naming the bound fronts. It relays until its stdin reaches end of
// file or it receives an interrupt or termination signal. It then closes the relay,
// joining every worker, writes the validated record to -record by renaming a complete
// temporary file, and exits zero. On any failure it exits nonzero, describes the
// failure on stderr and leaves no record. It refuses to start when -record exists.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/netip"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"

	"github.com/GridCastIO/quicquic-go/interop/multipath/relay"
)

// readyLine is the single stdout line written once the relay is bound.
type readyLine struct {
	Version int                                `json:"version"`
	Fronts  map[relay.RouteName]netip.AddrPort `json:"fronts"`
}

func main() {
	os.Exit(main1())
}

func main1() int {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := run(ctx, os.Args[1:], os.Stdin, os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, "udprelay:", err)
		return 1
	}
	return 0
}

func readConfig(path string) (relay.Config, error) {
	f, err := os.Open(path)
	if err != nil {
		return relay.Config{}, err
	}
	defer f.Close()
	dec := json.NewDecoder(f)
	dec.DisallowUnknownFields()
	var cfg relay.Config
	if err := dec.Decode(&cfg); err != nil {
		return relay.Config{}, fmt.Errorf("decoding config: %w", err)
	}
	if _, err := dec.Token(); !errors.Is(err, io.EOF) {
		return relay.Config{}, errors.New("decoding config: trailing data")
	}
	return cfg, cfg.Validate()
}

func run(ctx context.Context, args []string, stdin io.Reader, stdout io.Writer) error {
	flags := flag.NewFlagSet("udprelay", flag.ContinueOnError)
	configPath := flags.String("config", "", "relay configuration JSON")
	recordPath := flags.String("record", "", "where to write the relay record")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if *configPath == "" || *recordPath == "" || flags.NArg() != 0 {
		return errors.New("-config and -record are required, and nothing else")
	}
	switch _, err := os.Lstat(*recordPath); {
	case err == nil:
		return fmt.Errorf("record %s already exists", *recordPath)
	case !errors.Is(err, os.ErrNotExist):
		return fmt.Errorf("checking record %s: %w", *recordPath, err)
	}
	cfg, err := readConfig(*configPath)
	if err != nil {
		return err
	}
	r, err := relay.Start(cfg)
	if err != nil {
		return err
	}
	ready, err := json.Marshal(readyLine{Version: relay.RecordVersion, Fronts: r.Fronts()})
	if err == nil {
		_, err = fmt.Fprintf(stdout, "%s\n", ready)
	}
	if err == nil {
		eof := make(chan struct{})
		go func() {
			io.Copy(io.Discard, stdin)
			close(eof)
		}()
		select {
		case <-eof:
		case <-ctx.Done():
		}
	}
	rec, closeErr := r.Close()
	if err := errors.Join(err, closeErr); err != nil {
		return err
	}
	return writeRecord(*recordPath, rec)
}

// writeRecord publishes a complete record by rename, so a reader never sees a partial
// file under the record's name.
func writeRecord(path string, rec relay.Record) error {
	tmp, err := os.CreateTemp(filepath.Dir(path), ".udprelay-*.json")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if err := relay.WriteRecord(tmp, rec); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), path)
}
