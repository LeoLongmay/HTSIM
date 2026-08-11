import pathlib
import sys
import unittest


THIS_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))

from analyze import analyze_events


def event(flow, time_ps, kind, tuple_text, **extra):
    return {
        "event_seq": extra.pop("event_seq", time_ps),
        "time_ps": time_ps,
        "flow": flow,
        "event": kind,
        "tuple": tuple_text,
        "reason": extra.pop("reason", ""),
        "feedback": extra.pop("feedback", ""),
        "penalty_before": extra.pop("before", "0/0"),
        "penalty_after": extra.pop("after", "0/0"),
        **extra,
    }


class PenaltyLifecycleTests(unittest.TestCase):
    def test_interleaved_flows_and_censored_episodes(self):
        """A flow-local reselect must not count another flow's selection."""
        rows = analyze_events([
            event(1, 10, "feedback", "0/0", feedback="ecn", after="1/1"),
            event(2, 11, "selection", "0/0", reason="clear"),
            event(1, 12, "selection", "1/0", reason="clear"),
            event(1, 13, "selection", "0/0", reason="clear"),
            event(1, 14, "feedback", "1/1", feedback="timeout", after="4/4"),
        ])
        self.assertEqual(rows[0]["selections_until_reselect"], 2)
        self.assertEqual(rows[0]["time_until_reselect_ps"], 3)
        self.assertTrue(rows[1]["censored"])


if __name__ == "__main__":
    unittest.main()
