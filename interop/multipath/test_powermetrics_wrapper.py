import ast
import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

import powermetrics_wrapper as wrapper

HERE = Path(__file__).parent
# D6 of the execution protocol, written out independently of the wrapper's own tuples.
D6_BOUNDED = ["/usr/bin/powermetrics", "--format", "plist", "--samplers", "cpu_power", "-i", "1000", "-n", "60"]
D6_DRIVER_STOPPED = ["/usr/bin/powermetrics", "--format", "plist", "--samplers", "cpu_power", "-i", "1000"]


def fake_powermetrics(root, payload=b"", exit_code=0, ignore_term=False, linger_s=0.0):
    """A stand-in powermetrics: records its argument vector and pid, writes payload to
    stdout, then lingers (optionally ignoring SIGTERM) before exiting with exit_code."""
    path = root / "powermetrics"
    (root / "payload").write_bytes(payload)
    path.write_text(textwrap.dedent(f"""\
        #!{sys.executable}
        import json, signal, sys, time
        from pathlib import Path
        root = Path({str(root)!r})
        if {ignore_term!r}:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        (root / "invoked.json").write_text(json.dumps({{"argv": sys.argv[1:], "pid": __import__("os").getpid()}}))
        sys.stdout.buffer.write((root / "payload").read_bytes()); sys.stdout.flush()
        time.sleep({linger_s!r})
        sys.exit({exit_code!r})
    """))
    path.chmod(0o755)
    return path


def wrapper_command(fake, argv, patch="pass"):
    """The real wrapper main() in its own process, with only the executable path faked."""
    program = (f"import sys; sys.path.insert(0, {str(HERE)!r}); import powermetrics_wrapper as w; {patch}; "
               f"sys.exit(w.main(sys.argv[1:], powermetrics={str(fake)!r}))")
    return [sys.executable, "-c", program, *argv]


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_gone(pid, limit_s=10.0):
    deadline = time.monotonic() + limit_s
    while alive(pid):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


class WrapperTests(unittest.TestCase):
    def test_modes_are_exactly_the_d6_argument_lists(self):
        self.assertEqual(wrapper.POWERMETRICS, "/usr/bin/powermetrics")
        self.assertEqual({mode: [wrapper.POWERMETRICS, *arguments] for mode, arguments in wrapper.MODES.items()},
                         {"bounded": D6_BOUNDED, "driver-stopped": D6_DRIVER_STOPPED})

    def test_every_other_argument_vector_is_refused_without_launching(self):
        refused = ([], ["unknown"], ["bounded", "extra"], ["driver-stopped", "-o", "/tmp/out.plist"],
                   D6_DRIVER_STOPPED[1:], ["--samplers", "tasks"], ["Bounded"], [""])
        for argv in refused:
            with self.subTest(argv=argv), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fake = fake_powermetrics(root)
                result = subprocess.run(wrapper_command(fake, argv), stdin=subprocess.DEVNULL,
                                        capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 64, result.stderr)
                self.assertEqual(result.stdout, b"")
                self.assertIn(b"usage", result.stderr)
                self.assertFalse((root / "invoked.json").exists(), "a refused vector must launch nothing")

    def test_bounded_mode_passes_output_and_status_through(self):
        payload = b"<plist>first</plist>\0<plist>second</plist>\0"
        for exit_code in (0, 3):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fake = fake_powermetrics(root, payload=payload, exit_code=exit_code)
                # Standard input stays open: the bounded capture ends by itself.
                with subprocess.Popen(wrapper_command(fake, ["bounded"]), stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
                    stdout = process.stdout.read()
                    process.wait(timeout=30)
                self.assertEqual(process.returncode, exit_code)
                self.assertEqual(stdout, payload, "the wrapper adds nothing to the sampler's output")
                self.assertEqual(json.loads((root / "invoked.json").read_text())["argv"], D6_BOUNDED[1:])


    def start_driver_stopped(self, root, ignore_term=True, patch="w.STOP_GRACE_S = 0.3"):
        """A driver-stopped wrapper whose sampler has started and (optionally) ignores SIGTERM."""
        fake = fake_powermetrics(root, payload=b"<plist/>\0", ignore_term=ignore_term, linger_s=60)
        process = subprocess.Popen(wrapper_command(fake, ["driver-stopped"], patch), stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.addCleanup(process.wait)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        self.assertEqual(process.stdout.read(9), b"<plist/>\0", "the sampler started")
        invoked = json.loads((root / "invoked.json").read_text())
        self.addCleanup(lambda: alive(invoked["pid"]) and os.kill(invoked["pid"], signal.SIGKILL))
        self.assertEqual(invoked["argv"], D6_DRIVER_STOPPED[1:])
        return process, invoked["pid"]

    def test_stdin_eof_stops_and_reaps_a_sampler_that_ignores_sigterm(self):
        with tempfile.TemporaryDirectory() as temporary:
            process, pid = self.start_driver_stopped(Path(temporary))
            time.sleep(0.2)
            self.assertIsNone(process.poll(), "an open standard input keeps the sampler running")
            process.stdin.close()
            self.assertEqual(process.wait(timeout=10), 0)
            self.assertFalse(alive(pid), "the wrapper reaps the sampler before it exits")


    def test_a_signaled_wrapper_stops_and_reaps_its_sampler(self):
        for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            with self.subTest(signal=number.name), tempfile.TemporaryDirectory() as temporary:
                process, pid = self.start_driver_stopped(Path(temporary))
                process.send_signal(number)
                self.assertEqual(process.wait(timeout=10), 0)
                self.assertFalse(alive(pid))

    def test_lifetime_backstop_stops_a_sampler_whose_stdin_never_closes(self):
        with tempfile.TemporaryDirectory() as temporary:
            process, pid = self.start_driver_stopped(Path(temporary), patch="w.STOP_GRACE_S = 0.3; w.MAX_LIFETIME_S = 1")
            self.assertEqual(process.wait(timeout=10), 75)
            self.assertFalse(alive(pid))
            self.assertIsNotNone(process.stdin, "standard input was never closed")


    def test_installed_form_runs_isolated_under_the_system_python(self):
        source = Path(wrapper.__file__).read_text()
        self.assertEqual(source.splitlines()[0], "#!/usr/bin/python3 -I")
        # /usr/bin/python3 is the Command Line Tools' Python 3.9 on the venue.
        ast.parse(source, feature_version=(3, 9))
        self.assertLess(wrapper.STOP_GRACE_S, wrapper.MAX_LIFETIME_S)


if __name__ == "__main__":
    unittest.main()
