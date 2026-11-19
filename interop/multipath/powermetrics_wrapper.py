#!/usr/bin/python3 -I
"""Owner-installed privileged powermetrics wrapper for the MP-MAC host sampler (D6 A).

Reference source: the owner reviews it and installs it root-owned at
/usr/local/libexec/quicquic-powermetrics, with a sudoers entry for that path and these
two modes only (see interop/multipath/README.md). It runs exactly one of the protocol's
two powermetrics argument lists, writing to standard output, and nothing else.
"""

import os
import select
import signal
import subprocess
import sys
import time

POWERMETRICS = "/usr/bin/powermetrics"
_BASE = ("--format", "plist", "--samplers", "cpu_power", "-i", "1000")
MODES = {
    "bounded": _BASE + ("-n", "60"),  # X3: one bounded capture
    "driver-stopped": _BASE,  # X11: stopped when the driver closes standard input
}
EXIT_USAGE = 64
EXIT_LIFETIME = 75
# A backstop if standard input never reaches EOF, far above any X11 observation (at most 135 s).
MAX_LIFETIME_S = 600
STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
POLL_S = 0.1
STOP_GRACE_S = 3  # below the driver's SAMPLER_STOP_S, which waits for this wrapper


def main(argv, powermetrics=POWERMETRICS):
    """Run one mode. powermetrics is a parameter only for tests that import this module;
    the installed command has no way to change the executable or its arguments."""
    if len(argv) != 1 or argv[0] not in MODES:
        note(f"usage: quicquic-powermetrics {{{'|'.join(MODES)}}}")
        return EXIT_USAGE
    # A stop signal before or during the launch is honored as soon as the loop starts.
    requested = []
    for number in STOP_SIGNALS:
        signal.signal(number, lambda number, frame: requested.append(number))
    # Standard output and error are inherited, so the plist bytes reach the caller untouched;
    # the wrapper itself never writes to standard output.
    child = subprocess.Popen([powermetrics, *MODES[argv[0]]], stdin=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + MAX_LIFETIME_S
        while child.poll() is None:
            if requested or stdin_closed():
                return stop(child, 0)
            if time.monotonic() > deadline:
                stop(child, EXIT_LIFETIME)
                note(f"quicquic-powermetrics: stopped at the {MAX_LIFETIME_S} s lifetime bound")
                return EXIT_LIFETIME
        return status(child.returncode)
    finally:
        if child.returncode is None:  # any other way out still stops and reaps the sampler
            stop(child, 0)


def note(message):
    """Best-effort diagnostic, unbuffered, so an unwritable stderr can neither skip a stop
    nor change the exit status at interpreter shutdown."""
    try:
        os.write(2, (message + "\n").encode())
    except OSError:
        pass


def stdin_closed():
    """Waits up to POLL_S for standard input; true at EOF. Other input is discarded."""
    try:
        if not select.select([0], [], [], POLL_S)[0]:
            return False
        return not os.read(0, 4096)
    except OSError:  # no usable standard input: nothing can keep the sampler alive
        return True


def stop(child, code):
    """Stop and reap the sampler: SIGTERM, a grace period, then SIGKILL. The wrapper is the
    sampler's parent, so it always reaps it before exiting."""
    child.terminate()
    try:
        child.wait(timeout=STOP_GRACE_S)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()
    return code


def status(code):
    """The sampler's own exit, as a shell would report it."""
    return code if code >= 0 else 128 - code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
