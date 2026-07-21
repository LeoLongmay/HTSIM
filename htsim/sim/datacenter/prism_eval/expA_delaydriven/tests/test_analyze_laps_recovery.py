import csv
import importlib.util
import pathlib
import tempfile
import unittest


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "analyze_laps_recovery.py"
SPEC = importlib.util.spec_from_file_location("analyze_laps_recovery", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AnalyzeLapsRecoveryTest(unittest.TestCase):
    def test_aggregates_only_summary_records(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            (root / "expA_laps_diag_f4_s13.stdout").write_text(
                "noise\nLAPS_RECOVERY_SUMMARY flow=1 acked=3 stale_ack=1 "
                "ack_gap_events=2 ack_gap_records=4 timeout_events=1 timeout_records=5 "
                "nack=0 stale_nack=0 retired=3 stale_retire=0 "
                "source_ack_gap_rtx=4 source_timeout_rtx=5\n"
            )
            (root / "expA_laps_diag_f4_s17.stdout").write_text(
                "LAPS_RECOVERY_SUMMARY flow=2 acked=7 stale_ack=2 "
                "ack_gap_events=3 ack_gap_records=6 timeout_events=2 timeout_records=8 "
                "nack=1 stale_nack=1 retired=7 stale_retire=1 "
                "source_ack_gap_rtx=6 source_timeout_rtx=8\n"
            )
            output = root / "summary.csv"
            MODULE.write_summary(root, output)
            with output.open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["failed"], "4")
            self.assertEqual(rows[0]["runs"], "2")
            self.assertEqual(rows[0]["ack_gap_records"], "10")
            self.assertEqual(rows[0]["timeout_records"], "13")
            self.assertEqual(rows[0]["nack"], "1")
            self.assertEqual(rows[0]["stale_ack"], "3")


if __name__ == "__main__":
    unittest.main()
