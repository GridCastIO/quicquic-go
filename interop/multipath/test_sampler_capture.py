import copy
import hashlib
import json
import plistlib
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import sampler_capture as reader
from test_powermetrics_wrapper import D6_BOUNDED, wrapper_command

FIXTURE = Path(__file__).parent / "testdata" / "powermetrics" / "cpu_power.plist"
SECOND = 10**9
MS = 10**6
LAUNCHED = 1_000 * SECOND


def template():
    first = FIXTURE.read_bytes().split(b"\0")[0]
    return plistlib.loads(first)


def capture(count=60, arrivals=None, elapsed=SECOND, edit=None, terminate_last=True):
    """Producer-shaped records built from the recorded fixture, one read per record at its
    arrival time (ns after launch). Defaults: contiguous 1 s deltas after a 5 s start."""
    records = []
    for index in range(count):
        record = copy.deepcopy(template())
        record["elapsed_ns"] = elapsed
        records.append(record)
    if edit:
        edit(records)
    arrivals = arrivals if arrivals is not None else [5 * SECOND + index * SECOND for index in range(count)]
    payloads = [plistlib.dumps(record) + b"\0" for record in records]
    if payloads and not terminate_last:
        payloads[-1] = payloads[-1][:-1]
    reads = [(LAUNCHED + arrival, len(payload)) for arrival, payload in zip(arrivals, payloads)]
    return b"".join(payloads), reads


def judge(raw, reads, exit=0, reaped=True):
    return reader.judge_capture(raw, reads, LAUNCHED, reads[-1][0] + SECOND if reads else LAUNCHED + SECOND,
                                exit=exit, reaped=reaped)


class JudgeTests(unittest.TestCase):
    def test_contiguous_capture_passes_whatever_its_startup_delay(self):
        jitter = [(0, 20 * MS, -20 * MS)[index % 3] for index in range(60)]
        raw, reads = capture(arrivals=[5 * SECOND + index * SECOND + jitter[index] for index in range(60)])
        result = judge(raw, reads)
        self.assertEqual(result["status"], "passed", result["reasons"])
        self.assertEqual(result["launch_to_first_arrival_ns"], 5 * SECOND)
        self.assertEqual(len(result["records"]), 60)
        self.assertEqual(result["max_gap_deviation_ns"], 40 * MS)

    def test_absolute_first_record_fails(self):
        raw, reads = capture(edit=lambda records: records[0].update(is_delta=False))
        result = judge(raw, reads)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("adapter rejects" in reason for reason in result["reasons"]), result["reasons"])

    def test_interior_gap_fails(self):
        arrivals = [5 * SECOND + index * SECOND + (200 * MS if index >= 30 else 0) for index in range(60)]
        raw, reads = capture(arrivals=arrivals)
        result = judge(raw, reads)
        self.assertEqual(result["status"], "failed")
        self.assertIn("record 30 arrived 1.200 s after record 29, 200.000 ms from its 1.000 s elapsed_ns",
                      result["reasons"])

    def test_sum_mismatch_fails_when_every_gap_is_within_tolerance(self):
        raw, reads = capture(arrivals=[5 * SECOND + index * (SECOND + 3 * MS) for index in range(60)])
        result = judge(raw, reads)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["max_gap_deviation_ns"], 3 * MS)
        self.assertEqual(result["sum_deviation_ns"], -177 * MS)  # deltas short of the interval
        self.assertEqual([reason for reason in result["reasons"] if "gap" in reason or "arrived" in reason], [])
        self.assertTrue(any("sum" in reason for reason in result["reasons"]), result["reasons"])

    def test_rejected_producer_values_still_leave_a_json_receipt(self):
        import datetime
        raw, reads = capture(edit=lambda records: records[3].update(elapsed_ns=datetime.datetime(2026, 11, 19)))
        result = judge(raw, reads)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("adapter rejects" in reason for reason in result["reasons"]), result["reasons"])
        receipt = json.loads(json.dumps(result))
        self.assertIsNone(receipt["records"][3]["elapsed_ns"])
        self.assertEqual(receipt["records"][3]["arrival_ns"], 8 * SECOND)
        self.assertEqual(receipt["records"][2]["elapsed_ns"], SECOND)

    def test_fewer_than_two_deltas_is_inconclusive(self):
        raw, reads = capture(count=1)
        result = judge(raw, reads)
        self.assertEqual(result["status"], "inconclusive")
        self.assertIn("fewer than two complete deltas", result["reasons"])

    def test_fewer_than_sixty_records_fails(self):
        raw, reads = capture(count=59)
        result = judge(raw, reads)
        self.assertEqual(result["status"], "failed")
        self.assertIn("59 records, not 60", result["reasons"])

    def test_failed_exit_or_unconfirmed_stop_fails(self):
        raw, reads = capture()
        result = judge(raw, reads, exit=1)
        self.assertEqual(result["status"], "failed")
        self.assertIn("the capture exited 1", result["reasons"])
        self.assertEqual(result["reaped_after_launch_ns"], reads[-1][0] + SECOND - LAUNCHED)
        result = judge(raw, reads, exit=None, reaped=False)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("not confirmed stopped" in reason for reason in result["reasons"]), result["reasons"])
        self.assertIsNone(result["reaped_after_launch_ns"], "no reap, so no reap time")

    def test_arrival_is_the_read_that_completed_each_record(self):
        raw, _ = capture(count=3, terminate_last=False)
        first_end = raw.index(b"\0") + 1
        # Read 1 ends inside record 1; read 2 completes records 1 and 2, the last unterminated.
        reads = [(LAUNCHED + 2 * SECOND, first_end + 10), (LAUNCHED + 4 * SECOND, len(raw) - first_end - 10)]
        result = judge(raw, reads)
        self.assertEqual([record["arrival_ns"] for record in result["records"]], [2 * SECOND, 4 * SECOND, 4 * SECOND])
        self.assertIn("record 2 arrived 0.000 s after record 1, 1000.000 ms from its 1.000 s elapsed_ns",
                      result["reasons"])

    def test_identity_review_names_keys_without_deciding(self):
        raw, reads = capture()
        review = judge(raw, reads)["identity_review"]
        self.assertEqual(review["other_top_level_keys"], ["kern_bootargs", "kern_boottime", "thermal_pressure", "timestamp"])
        self.assertIn("processor.clusters[].name", review["processor_key_paths"])
        self.assertNotIn("Mac16,6", json.dumps(review), "names only, never values")


class CaptureTests(unittest.TestCase):
    def test_capture_holds_stdin_open_until_the_bounded_sampler_ends(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record = plistlib.dumps(template()) + b"\0"
            fake = root / "powermetrics"
            fake.write_text(textwrap.dedent(f"""\
                #!{sys.executable}
                import json, sys, time
                assert sys.argv[1:] == {D6_BOUNDED[1:]!r}, sys.argv
                for _ in range(3):
                    sys.stdout.buffer.write({record!r}); sys.stdout.flush()
                    time.sleep(0.3)
            """))
            fake.chmod(0o755)
            command = wrapper_command(fake, ["bounded"], "w.STOP_GRACE_S = 0.3")
            output = root / "x3"
            output.mkdir()
            with self.assertRaises(FileExistsError):
                reader.capture(output, command=command)
            output = root / "x3-a1"
            result = reader.capture(output, command=command)
            self.assertEqual(result["exit"], 0, (output / "capture.log").read_text())
            self.assertTrue(result["reaped"])
            self.assertEqual(len(result["records"]), 3, "every record arrived before stdin closed")
            arrivals = [entry["arrival_ns"] for entry in result["records"]]
            self.assertEqual(arrivals, sorted(arrivals))
            self.assertGreater(arrivals[2] - arrivals[0], 400 * MS)
            raw = (output / "capture.plist").read_bytes()
            self.assertEqual(raw, record * 3)
            self.assertEqual(result["raw"]["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(json.loads((output / "capture.json").read_text()), result)
            self.assertEqual(result["status"], "failed")
            self.assertIn("3 records, not 60", result["reasons"])


if __name__ == "__main__":
    unittest.main()
