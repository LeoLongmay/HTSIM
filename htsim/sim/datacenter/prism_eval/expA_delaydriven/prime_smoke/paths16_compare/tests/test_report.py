import csv
import importlib.util
import pathlib
import unittest


HERE = pathlib.Path(__file__).resolve().parent
REPORT = HERE.parent / "report.py"
SPEC = importlib.util.spec_from_file_location("prime_paths16_report", REPORT)
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


def write_trace(directory, tuples):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "run.prime.tsv").open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("time_ps", "flow", "event", "entropy", "tuple", "reason",
                        "feedback", "penalty_before", "penalty_after"),
            delimiter="\t",
        )
        writer.writeheader()
        for entropy, tuple_text in enumerate(tuples):
            writer.writerow({"time_ps": "0", "flow": "1", "event": "selection",
                             "entropy": str(entropy), "tuple": tuple_text,
                             "reason": "initial", "feedback": "",
                             "penalty_before": "0/0", "penalty_after": "0/0"})


class PrimePaths16ReportTest(unittest.TestCase):
    def test_requires_all_24_cells_and_keeps_path_domains_separate(self):
        """Removing a PATHS=16 cell must fail instead of borrowing PATHS=8 data."""
        with self.assertRaisesRegex(RuntimeError, "missing required cell"):
            report.read_paths16_matrix(self._tmp_path())

    def test_prime_paths16_uses_all_four_source_uplinks(self):
        """A trace missing a source ToR uplink must not pass the PATHS=16 report."""
        directory = self._tmp_path()
        write_trace(directory, tuples=["0/0", "1/0", "2/0", "3/0"])
        self.assertEqual(report.source_uplink_coverage(directory), {0, 1, 2, 3})

    def _tmp_path(self):
        import tempfile
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmpdir, ignore_errors=True))
        self.tmpdir = pathlib.Path(tempfile.mkdtemp())
        return self.tmpdir


if __name__ == "__main__":
    unittest.main()
