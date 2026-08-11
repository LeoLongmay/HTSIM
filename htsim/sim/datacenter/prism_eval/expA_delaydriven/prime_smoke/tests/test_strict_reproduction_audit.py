import unittest
from pathlib import Path
import subprocess


AUDIT = Path(__file__).resolve().parents[1] / "strict_reproduction_audit.md"
SMOKE = AUDIT.parent


class StrictReproductionAuditTest(unittest.TestCase):
    def test_audit_has_all_required_topics_and_verdicts(self):
        text = AUDIT.read_text(encoding="utf-8")
        for topic in (
            "Penalty values and decay",
            "Feedback identity and semantics",
            "ACK coalescing",
            "Congestion-history granularity",
            "ExpA failure semantics",
        ):
            self.assertIn(topic, text)
        self.assertIn("P_NACK >> P_ECN", text)
        self.assertIn("unspecified by paper", text)
        self.assertIn("PATHS=16", text)
        self.assertIn("/tmp", text)
        self.assertIn("must not", text)
        lines = text.splitlines()
        header = "| topic | paper evidence | repository evidence | test/trace | verdict | scope boundary |"
        self.assertIn(header, lines)
        for line in lines:
            if line.startswith("| ") and not line.startswith("| ---") and line != header:
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                self.assertEqual(6, len(cells))
                self.assertIn(cells[4], {"aligned", "deviation", "unspecified by paper"})

    def test_runners_reject_output_outside_prime_smoke(self):
        for runner in ("repro.sh", "validate_paths16.sh"):
            result = subprocess.run(
                ["bash", str(SMOKE / runner), "--out", "/prime-audit-outside"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(2, result.returncode, result.stderr)
            self.assertIn("must be below", result.stderr)

    def test_audit_records_one_strict_terminal_decision(self):
        text = AUDIT.read_text(encoding="utf-8")
        decision = "**Terminal decision: paper underspecified/no strict-controller change.**"
        self.assertEqual(1, text.count(decision))
        self.assertIn("paper provides no numeric P", text)
        self.assertIn("failed=8", text)
        self.assertIn("0 NACK", text)
        self.assertIn("2995 timeout", text)
        self.assertIn("does not claim performance reproduction", text)


if __name__ == "__main__":
    unittest.main()
