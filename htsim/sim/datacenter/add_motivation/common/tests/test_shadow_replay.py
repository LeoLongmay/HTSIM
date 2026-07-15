import unittest
from collections import defaultdict

from htsim.sim.datacenter.add_motivation.common.shadow_replay import (
    LegacyFifo,
    ReplayError,
    SlotState,
    replay_shadow,
)
from htsim.sim.datacenter.add_motivation.common.trace_schema import EventRef, TraceBundle


UINT64_MAX = 2**64 - 1


class BundleBuilder:
    def __init__(self):
        self.sequence = 0
        self.rows = {kind: [] for kind in ("ack", "token", "epoch", "background")}
        self.events = []
        self.epoch_ids = defaultdict(int)
        self.epoch_starts = defaultdict(int)

    def _event(self, kind, row):
        row = dict(row, event_seq=self.sequence)
        self.rows[kind].append(row)
        self.events.append(EventRef(self.sequence, kind, row))
        self.sequence += 1
        return row

    def background_start(self, time_ps=None):
        return self._event("background", {
            "time_ps": self.sequence if time_ps is None else time_ps,
            "operation": "start",
        })

    def ack(
        self,
        flow_id,
        qdelay_ps,
        *,
        entropy=1,
        source_token_id=UINT64_MAX,
        selection_source="random_empty",
        genuine=True,
        ecn=False,
    ):
        return self._event("ack", {
            "time_ps": self.sequence,
            "flow_id": flow_id,
            "epoch_id": self.epoch_ids[flow_id],
            "qdelay_ps": qdelay_ps,
            "entropy": entropy,
            "source_token_id": source_token_id,
            "selection_source": selection_source,
            "genuine_sample": genuine,
            "ecn": ecn,
        })

    def token(
        self,
        flow_id,
        operation,
        token_id,
        entropy,
        *,
        related_ack_event_seq=UINT64_MAX,
    ):
        return self._event("token", {
            "time_ps": self.sequence,
            "flow_id": flow_id,
            "operation": operation,
            "token_id": token_id,
            "entropy": entropy,
            "related_ack_event_seq": related_ack_event_seq,
        })

    def close_epoch(self, flow_id, *, observed="hold", actual="hold"):
        epoch_id = self.epoch_ids[flow_id]
        genuine = [
            row for row in self.rows["ack"]
            if row["flow_id"] == flow_id
            and row["epoch_id"] == epoch_id
            and row["genuine_sample"]
        ]
        if not genuine:
            self.ack(flow_id, 0)
            genuine = [self.rows["ack"][-1]]
        delays = [row["qdelay_ps"] for row in genuine]
        floor_ps = min(delays)
        end_ps = self.sequence
        row = self._event("epoch", {
            "flow_id": flow_id,
            "epoch_id": epoch_id,
            "start_ps": self.epoch_starts[flow_id],
            "end_ps": end_ps,
            "sample_count": len(genuine),
            "raw_floor_ps": floor_ps,
            "raw_spread_ps": max(delays) - floor_ps,
            "smooth_floor_ps": 777_000_000,
            "smooth_spread_ps": 888_000_000,
            "observed_region": observed,
            "actual_region": actual,
        })
        self.epoch_ids[flow_id] += 1
        self.epoch_starts[flow_id] = end_ps
        return row

    def bundle(self):
        return TraceBundle(
            run_id="shadow-fixture",
            ack=tuple(self.rows["ack"]),
            token=tuple(self.rows["token"]),
            epoch=tuple(self.rows["epoch"]),
            pathmap=(),
            linkmap=(),
            background=tuple(self.rows["background"]),
            events=tuple(self.events),
        )


def seed_fifo(builder, count=8, *, flow_id=7, s_ref_ps=20_000_000, first_token_id=0):
    for index in range(count):
        qdelay_ps = s_ref_ps if index == 1 else 0
        token_id = first_token_id + index
        ack = builder.ack(flow_id, qdelay_ps, entropy=index % 3)
        builder.token(
            flow_id,
            "enqueue_good_ack",
            token_id,
            index % 3,
            related_ack_event_seq=ack["event_seq"],
        )
    if count < 2:
        builder.ack(flow_id, s_ref_ps, entropy=99)
    return builder.close_epoch(flow_id)


def select_and_ack(
    builder,
    token_id,
    entropy,
    qdelay_ps,
    *,
    flow_id=7,
    genuine=True,
    ecn=False,
    enqueue=True,
):
    builder.token(flow_id, "dequeue_recycle", token_id, entropy)
    ack = builder.ack(
        flow_id,
        qdelay_ps,
        entropy=entropy,
        source_token_id=token_id,
        selection_source="recycled",
        genuine=genuine,
        ecn=ecn,
    )
    if enqueue:
        builder.token(
            flow_id,
            "enqueue_good_ack",
            token_id + 1000,
            entropy,
            related_ack_event_seq=ack["event_seq"],
        )
    return ack


class LegacyFifoTests(unittest.TestCase):
    def test_fifo_removes_only_the_exact_front(self):
        fifo = LegacyFifo()
        fifo.apply({"flow_id": 3, "operation": "enqueue_good_ack", "token_id": 10, "entropy": 4})
        fifo.apply({"flow_id": 3, "operation": "enqueue_good_ack", "token_id": 11, "entropy": 5})

        with self.assertRaises(ReplayError):
            fifo.apply({"flow_id": 3, "operation": "dequeue_recycle", "token_id": 11, "entropy": 5})
        self.assertEqual([item.token_id for item in fifo.snapshot()], [10, 11])

        fifo.apply({"flow_id": 3, "operation": "dequeue_recycle", "token_id": 10, "entropy": 4})
        self.assertEqual([item.token_id for item in fifo.snapshot()], [11])

    def test_duplicate_entropy_tokens_keep_distinct_identity(self):
        fifo = LegacyFifo()
        for token_id in (21, 22):
            fifo.apply({
                "flow_id": 3,
                "operation": "enqueue_good_ack",
                "token_id": token_id,
                "entropy": 9,
            })
        fifo.apply({"flow_id": 3, "operation": "dequeue_recycle", "token_id": 21, "entropy": 9})
        self.assertEqual([(item.token_id, item.entropy) for item in fifo.snapshot()], [(22, 9)])

    def test_underflow_and_entropy_mismatch_raise_without_mutating(self):
        fifo = LegacyFifo()
        with self.assertRaises(ReplayError):
            fifo.apply({"flow_id": 3, "operation": "dequeue_recycle", "token_id": 0, "entropy": 1})
        fifo.apply({"flow_id": 3, "operation": "enqueue_good_ack", "token_id": 0, "entropy": 1})
        fifo.apply({"flow_id": 3, "operation": "select_random_empty", "token_id": 99, "entropy": 7})
        with self.assertRaises(ReplayError):
            fifo.apply({"flow_id": 3, "operation": "dequeue_recycle", "token_id": 0, "entropy": 2})
        self.assertEqual(fifo.snapshot()[0].token_id, 0)


class ShadowReplayTests(unittest.TestCase):
    def new_builder(self):
        builder = BundleBuilder()
        builder.background_start()
        return builder

    def test_fewer_than_eight_tokens_leave_pending_slots(self):
        builder = self.new_builder()
        seed_fifo(builder, count=2)

        round_ = replay_shadow(builder.bundle())[0]

        self.assertEqual([slot.state for slot in round_.slots[:2]], [SlotState.SEEDED] * 2)
        self.assertEqual([slot.state for slot in round_.slots[2:]], [SlotState.PENDING] * 6)
        self.assertTrue(round_.censored)
        self.assertEqual(round_.fifo_depth_at_start, 2)

    def test_seeded_tokens_complete_by_token_id_including_zero(self):
        builder = self.new_builder()
        seed_fifo(builder)
        for token_id in range(8):
            select_and_ack(builder, token_id, token_id % 3, token_id * 1_000_000)
        builder.close_epoch(7)

        round_ = replay_shadow(builder.bundle())[0]

        self.assertTrue(round_.complete)
        self.assertTrue(all(slot.state is SlotState.COMPLETE for slot in round_.slots))
        self.assertEqual(round_.seeded_pass_count, 8)

    def test_duplicate_entropy_ack_completes_only_matching_token_id(self):
        builder = self.new_builder()
        seed_fifo(builder, count=2, first_token_id=41)
        builder.rows["ack"][1]["entropy"] = 0
        builder.rows["token"][1]["entropy"] = 0
        builder.token(7, "dequeue_recycle", 41, 0)
        builder.ack(
            7,
            0,
            entropy=0,
            source_token_id=42,
            selection_source="recycled",
        )
        builder.close_epoch(7)

        round_ = replay_shadow(builder.bundle())[0]

        self.assertEqual(round_.slots[0].state, SlotState.SEEDED)
        self.assertEqual(round_.slots[1].state, SlotState.SEEDED)

    def test_high_residual_and_ecn_seeded_acks_become_pending(self):
        builder = self.new_builder()
        seed_fifo(builder, count=3)
        select_and_ack(builder, 0, 0, 14_000_000, enqueue=False)
        select_and_ack(builder, 1, 1, 0, ecn=True, enqueue=False)
        select_and_ack(builder, 2, 2, 0, genuine=False, enqueue=False)
        builder.ack(7, 0, entropy=90)
        builder.close_epoch(7)

        round_ = replay_shadow(builder.bundle())[0]

        self.assertEqual([slot.state for slot in round_.slots[:3]], [SlotState.PENDING] * 3)
        self.assertEqual(round_.seeded_fail_count, 3)
        self.assertFalse(round_.complete)

    def test_invalidation_alone_never_completes_a_slot(self):
        builder = self.new_builder()
        seed_fifo(builder, count=1)
        select_and_ack(builder, 0, 0, 20_000_000, enqueue=False)
        builder.ack(7, 0)
        builder.close_epoch(7)

        round_ = replay_shadow(builder.bundle())[0]

        self.assertEqual(round_.slots[0].state, SlotState.PENDING)
        self.assertTrue(round_.censored)

    def test_linked_low_replacements_complete_first_pending_slot_only(self):
        builder = self.new_builder()
        seed_fifo(builder, count=1)
        select_and_ack(builder, 0, 0, 0)
        enqueue_event_seqs = []
        for index in range(7):
            ack = builder.ack(7, index + 1, entropy=20 + index)
            enqueue = builder.token(
                7,
                "enqueue_good_ack",
                100 + index,
                20 + index,
                related_ack_event_seq=ack["event_seq"],
            )
            enqueue_event_seqs.append(enqueue["event_seq"])
        builder.close_epoch(7)

        round_ = replay_shadow(builder.bundle())[0]

        self.assertTrue(round_.complete)
        self.assertEqual(round_.replacement_count, 7)
        self.assertEqual(round_.admission_pass_count, 7)
        self.assertEqual(round_.admission_fail_count, 0)
        self.assertEqual(
            [slot.completion_event_seq for slot in round_.slots[1:]],
            enqueue_event_seqs,
        )

    def test_unlinked_ack_and_non_genuine_linked_enqueue_do_not_replace(self):
        builder = self.new_builder()
        seed_fifo(builder, count=1)
        builder.ack(7, 0, entropy=30)
        rejected = builder.ack(7, 0, entropy=31, genuine=False)
        builder.token(
            7,
            "enqueue_good_ack",
            101,
            31,
            related_ack_event_seq=rejected["event_seq"],
        )
        builder.close_epoch(7)

        round_ = replay_shadow(builder.bundle())[0]

        self.assertEqual(round_.replacement_count, 0)
        self.assertEqual(round_.admission_pass_count, 0)
        self.assertEqual(round_.admission_fail_count, 1)
        self.assertEqual(round_.slots[1].state, SlotState.PENDING)

    def test_actual_hold_exit_censors_without_no_progress_classification(self):
        builder = self.new_builder()
        seed_fifo(builder, count=2)
        builder.ack(7, 0)
        builder.close_epoch(7, observed="decrease", actual="decrease")

        round_ = replay_shadow(builder.bundle())[0]

        self.assertTrue(round_.censored)
        self.assertEqual(round_.censor_reason, "hold_exit_before_slot_completion")
        self.assertIsNone(round_.delta_s)
        self.assertFalse(round_.no_progress)

    def test_slot_completion_at_trace_end_is_right_censored(self):
        builder = self.new_builder()
        seed_fifo(builder)
        for token_id in range(8):
            select_and_ack(builder, token_id, token_id % 3, 0, enqueue=False)
        builder.close_epoch(7)
        builder.events.pop()

        round_ = replay_shadow(builder.bundle())[0]

        self.assertTrue(round_.censored)
        self.assertEqual(round_.censor_reason, "trace_end_before_post_completion_epoch")
        self.assertFalse(round_.complete)
        self.assertTrue(all(slot.state is SlotState.COMPLETE for slot in round_.slots))

    def test_completion_uses_next_raw_epoch_spread_and_delta_direction(self):
        builder = self.new_builder()
        seed_fifo(builder, s_ref_ps=20_000_000)
        for token_id in range(8):
            qdelay_ps = 12_000_000 if token_id == 7 else token_id * 1_000_000
            select_and_ack(builder, token_id, token_id % 3, qdelay_ps)
        builder.close_epoch(7)

        rounds = replay_shadow(builder.bundle(), slots=8, threshold_ps=14_000_000)

        self.assertTrue(rounds[0].complete)
        self.assertEqual(rounds[0].s_ref_ps, 20_000_000)
        self.assertEqual(rounds[0].s_end_ps, 12_000_000)
        self.assertEqual(rounds[0].delta_s, 0.4)
        self.assertFalse(rounds[0].no_progress)
        self.assertEqual(len(rounds), 2)
        self.assertEqual(rounds[1].round_index, 1)
        self.assertEqual(rounds[1].start_epoch_id, rounds[0].end_epoch_id)
        self.assertEqual(rounds[1].s_ref_ps, rounds[0].s_end_ps)
        self.assertTrue(rounds[1].censored)

    def test_missing_background_requires_explicit_fixture_injection_time(self):
        builder = BundleBuilder()
        seed_fifo(builder, count=2)
        with self.assertRaises(ReplayError):
            replay_shadow(builder.bundle())
        self.assertEqual(len(replay_shadow(builder.bundle(), injection_time_ps=0)), 1)

    def test_non_hold_epoch_does_not_start_and_later_hold_starts_new_episode(self):
        builder = self.new_builder()
        seed_fifo(builder, count=2)
        builder.rows["epoch"][-1]["observed_region"] = "increase"
        builder.rows["epoch"][-1]["actual_region"] = "increase"
        builder.ack(7, 0)
        builder.ack(7, 1_000_000)
        builder.close_epoch(7)

        rounds = replay_shadow(builder.bundle())

        self.assertEqual(len(rounds), 1)
        self.assertEqual(rounds[0].start_epoch_id, 1)

    def test_rejects_non_eight_slots_and_noncanonical_threshold(self):
        builder = self.new_builder()
        seed_fifo(builder, count=2)
        with self.assertRaises(ValueError):
            replay_shadow(builder.bundle(), slots=7)
        with self.assertRaises(ValueError):
            replay_shadow(builder.bundle(), threshold_ps=13_999_999)

    def test_rejects_nonpositive_raw_s_ref_at_hold_entry(self):
        builder = self.new_builder()
        builder.ack(7, 5_000_000)
        builder.close_epoch(7)
        with self.assertRaises(ReplayError):
            replay_shadow(builder.bundle())


if __name__ == "__main__":
    unittest.main()
