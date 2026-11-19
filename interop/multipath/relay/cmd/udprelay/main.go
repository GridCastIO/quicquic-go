// Command udprelay runs one relay.Config as its own process, so a driver can attribute
// the relay's resource use separately from the endpoints it shapes.
//
//	udprelay -config config.json -record record.json
//
// The config is one JSON relay.Config. Once every route is bound, the process writes one
// JSON line to stdout naming the bound fronts. It relays until its stdin reaches end of
// file or it receives an interrupt or termination signal. It then closes the relay,
// joining every worker, publishes the validated record by linking a complete temporary
// file to the -record name, and exits zero. On any failure, including a stdin read
// error or a file that appeared at -record meanwhile, it exits nonzero, describes the
// failure on stderr and publishes no record; it never replaces an existing file.
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
		eof := make(chan error, 1)
		go func() {
			_, err := io.Copy(io.Discard, stdin)
			eof <- err
		}()
		select {
		case err = <-eof:
			if err != nil {
				err = fmt.Errorf("reading stdin: %w", err)
			}
		case <-ctx.Done():
		}
	}
	rec, closeErr := r.Close()
	if err := errors.Join(err, closeErr); err != nil {
		return err
	}
	return writeRecord(*recordPath, rec)
}

// writeRecord publishes a complete record by hard-linking it to path, so a reader never
// sees a partial file under that name and an existing file is never replaced.
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
	if err := os.Link(tmp.Name(), path); err != nil {
		return fmt.Errorf("publishing record: %w", err)
	}
	return nil
}
