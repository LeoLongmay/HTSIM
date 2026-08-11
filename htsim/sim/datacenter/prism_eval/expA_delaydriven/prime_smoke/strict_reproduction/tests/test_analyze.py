import pathlib
import sys
import tempfile
import unittest


THIS_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))

from analyze import analyze_run, analyze_trace, read_trace


HEADER = (
    "event_seq\ttime_ps\tflow\tevent\tentropy\ttuple\treason\tfeedback"
    "\tpenalty_before\tpenalty_after\n"
)


def trace(*rows):
    return HEADER + "".join("\t".join(map(str, row)) + "\n" for row in rows)


class StrictReproductionAnalyzerTests(unittest.TestCase):
    def test_counts_feedback_classes_without_relabeling_timeout(self):
        events = read_trace(trace(
            (1, 10, 1, "feedback", 0, "0/0", "", "ecn", "0/0", "1/1"),
            (2, 11, 1, "feedback", 0, "0/0", "", "nack", "1/1", "4/4"),
            (3, 12, 1, "feedback", 0, "0/0", "", "timeout", "4/4", "4/4"),
        ).splitlines())
        summary = analyze_trace(events)
        self.assertEqual(3, summary["event_rows"])
        self.assertEqual(1, summary["ecn_feedback"])
        self.assertEqual(1, summary["nack_feedback"])
        self.assertEqual(1, summary["timeout_feedback"])

    def test_rejects_noncontiguous_event_sequence(self):
        malformed = trace(
            (1, 10, 1, "selection", 0, "0/0", "clear", "", "0/0", "0/0"),
            (3, 11, 1, "selection", 0, "0/0", "clear", "", "0/0", "0/0"),
        ).splitlines()
        with self.assertRaisesRegex(ValueError, "contiguous"):
            read_trace(malformed)

    def test_rejects_a_non_ten_column_trace(self):
        with self.assertRaisesRegex(ValueError, "ten columns"):
            read_trace(["event_seq\ttime_ps\n", "1\t10\n"])

    def test_rejects_manifest_without_exactly_one_of_each_failed_cell(self):
        with tempfile.TemporaryDirectory(dir=THIS_DIR) as temporary:
            root = pathlib.Path(temporary)
            (root / "run_manifest.tsv").write_text(
                "trace\tfailed\tseed\ttopology\tpaths\tend_ms\tdisable_trim\tuec_delivery_summary\tprime_diag\n"
                "prime_strict_f0_s13/run.prime.tsv\t0\t13\tfat_tree_128_1os.topo\t16\t8\t1\t1\t1\n"
                "prime_strict_f0_s13/run.prime.tsv\t0\t13\tfat_tree_128_1os.topo\t16\t8\t1\t1\t1\n",
                encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "exactly one f0 and one f8"):
                analyze_run(root)

    def test_rejects_manifest_trace_name_outside_fixed_contract(self):
        with tempfile.TemporaryDirectory(dir=THIS_DIR) as temporary:
            root = pathlib.Path(temporary)
            (root / "alternate").mkdir()
            (root / "alternate" / "run.prime.tsv").write_text(HEADER, encoding="utf-8")
            (root / "prime_strict_f8_s13").mkdir()
            (root / "prime_strict_f8_s13" / "run.prime.tsv").write_text(HEADER, encoding="utf-8")
            (root / "run_manifest.tsv").write_text(
                "trace\tfailed\tseed\ttopology\tpaths\tend_ms\tdisable_trim\tuec_delivery_summary\tprime_diag\n"
                "alternate/run.prime.tsv\t0\t13\tfat_tree_128_1os.topo\t16\t8\t1\t1\t1\n"
                "prime_strict_f8_s13/run.prime.tsv\t8\t13\tfat_tree_128_1os.topo\t16\t8\t1\t1\t1\n",
                encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "trace contract"):
                analyze_run(root)

    def test_rejects_a_non_fixed_seed_even_with_two_expected_cells(self):
        with tempfile.TemporaryDirectory(dir=THIS_DIR) as temporary:
            root = pathlib.Path(temporary)
            (root / "run_manifest.tsv").write_text(
                "trace\tfailed\tseed\ttopology\tpaths\tend_ms\tdisable_trim\tuec_delivery_summary\tprime_diag\n"
                "prime_strict_f0_s13/run.prime.tsv\t0\t14\tfat_tree_128_1os.topo\t16\t8\t1\t1\t1\n"
                "prime_strict_f8_s13/run.prime.tsv\t8\t13\tfat_tree_128_1os.topo\t16\t8\t1\t1\t1\n",
                encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "non-fixed flags"):
                analyze_run(root)


if __name__ == "__main__":
    unittest.main()
