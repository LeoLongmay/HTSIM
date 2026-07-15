"""Offline Legacy REPS FIFO reconstruction and virtual validation rounds."""

from __future__ import annotations

import dataclasses
import enum
from collections import deque
from typing import Optional

from .residual_join import ResidualAck, attach_same_epoch_residuals
from .trace_schema import TraceBundle


SHADOW_SLOTS = 8
RESIDUAL_THRESHOLD_PS = 14_000_000


class ReplayError(ValueError):
    """Raised when trace events cannot support an exact shadow replay."""


@dataclasses.dataclass(frozen=True)
class LegacyToken:
    token_id: int
    entropy: int


class LegacyFifo:
    """Exact reconstruction of one flow's real Legacy REPS FIFO."""

    _NON_MUTATING_OPERATIONS = frozenset({"select_first_window", "select_random_empty"})

    def __init__(self) -> None:
        self._flow_id: Optional[int] = None
        self._tokens: deque[LegacyToken] = deque()
        self._active_token_ids: set[int] = set()

    def apply(self, token_event: dict) -> None:
        flow_id = token_event["flow_id"]
        if self._flow_id is None:
            self._flow_id = flow_id
        elif flow_id != self._flow_id:
            raise ReplayError(
                f"Legacy FIFO for flow {self._flow_id} received event for flow {flow_id}"
            )

        operation = token_event["operation"]
        if operation in self._NON_MUTATING_OPERATIONS:
            return

        token = LegacyToken(token_event["token_id"], token_event["entropy"])
        if operation == "enqueue_good_ack":
            if token.token_id in self._active_token_ids:
                raise ReplayError(
                    f"flow {flow_id} enqueued duplicate active token_id {token.token_id}"
                )
            self._tokens.append(token)
            self._active_token_ids.add(token.token_id)
            return

        if operation == "dequeue_recycle":
            if not self._tokens:
                raise ReplayError(
                    f"flow {flow_id} dequeued token {token.token_id} from an empty FIFO"
                )
            front = self._tokens[0]
            if front != token:
                raise ReplayError(
                    f"flow {flow_id} dequeue expected FIFO front "
                    f"(token_id={front.token_id}, entropy={front.entropy}), got "
                    f"(token_id={token.token_id}, entropy={token.entropy})"
                )
            self._tokens.popleft()
            self._active_token_ids.remove(token.token_id)
            return

        raise ReplayError(f"flow {flow_id} has unknown token operation {operation!r}")

    def snapshot(self, limit: int = SHADOW_SLOTS) -> tuple[LegacyToken, ...]:
        return tuple(list(self._tokens)[:limit])

    @property
    def depth(self) -> int:
        return len(self._tokens)


class SlotState(str, enum.Enum):
    SEEDED = "SEEDED"
    PENDING = "PENDING"
    COMPLETE = "COMPLETE"


@dataclasses.dataclass
class ShadowSlot:
    index: int
    state: SlotState
    seed_token: Optional[LegacyToken] = None
    completion_event_seq: Optional[int] = None
    completion_source: Optional[str] = None


@dataclasses.dataclass
class ShadowRound:
    flow_id: int
    round_index: int
    start_event_seq: int
    start_epoch_id: int
    start_ps: int
    s_ref_ps: int
    fifo_depth_at_start: int
    slots: tuple[ShadowSlot, ...]
    slot_completion_event_seq: Optional[int] = None
    slot_completion_ps: Optional[int] = None
    end_event_seq: Optional[int] = None
    end_epoch_id: Optional[int] = None
    end_ps: Optional[int] = None
    s_end_ps: Optional[int] = None
    delta_s: Optional[float] = None
    complete: bool = False
    censored: bool = False
    censor_reason: Optional[str] = None
    seeded_pass_count: int = 0
    seeded_fail_count: int = 0
    replacement_count: int = 0
    admission_pass_count: int = 0
    admission_fail_count: int = 0

    @property
    def no_progress(self) -> bool:
        return bool(self.complete and self.delta_s is not None and self.delta_s <= 0.0)


@dataclasses.dataclass
class _ActiveRound:
    result: ShadowRound
    seeded_slot_by_token_id: dict[int, int]
    selected_seed_token_ids: set[int] = dataclasses.field(default_factory=set)
    consumed_seed_ack_event_seqs: set[int] = dataclasses.field(default_factory=set)
    classified_enqueue_ack_event_seqs: set[int] = dataclasses.field(default_factory=set)
    waiting_for_end_epoch: bool = False


def _admitted(residual: Optional[ResidualAck], threshold_ps: int) -> bool:
    return bool(
        residual is not None
        and not residual.row["ecn"]
        and residual.residual_ps < threshold_ps
    )


def _event_time(kind: str, row: dict) -> int:
    return row["end_ps"] if kind == "epoch" else row["time_ps"]


def _start_round(
    flow_id: int,
    epoch: dict,
    fifo: LegacyFifo,
    round_index: int,
) -> _ActiveRound:
    s_ref_ps = epoch["raw_spread_ps"]
    if s_ref_ps <= 0:
        raise ReplayError(
            f"flow {flow_id} HOLD epoch {epoch['epoch_id']} has nonpositive raw S_ref"
        )

    seeded = fifo.snapshot(limit=SHADOW_SLOTS)
    slots = tuple(
        ShadowSlot(
            index=index,
            state=SlotState.SEEDED if index < len(seeded) else SlotState.PENDING,
            seed_token=seeded[index] if index < len(seeded) else None,
        )
        for index in range(SHADOW_SLOTS)
    )
    seeded_slot_by_token_id = {
        token.token_id: index for index, token in enumerate(seeded)
    }
    if len(seeded_slot_by_token_id) != len(seeded):
        raise ReplayError(f"flow {flow_id} FIFO snapshot contains duplicate token identity")

    result = ShadowRound(
        flow_id=flow_id,
        round_index=round_index,
        start_event_seq=epoch["event_seq"],
        start_epoch_id=epoch["epoch_id"],
        start_ps=epoch["end_ps"],
        s_ref_ps=s_ref_ps,
        fifo_depth_at_start=fifo.depth,
        slots=slots,
    )
    return _ActiveRound(result=result, seeded_slot_by_token_id=seeded_slot_by_token_id)


def _mark_slot_complete(
    slot: ShadowSlot,
    event_seq: int,
    source: str,
) -> None:
    slot.state = SlotState.COMPLETE
    slot.completion_event_seq = event_seq
    slot.completion_source = source


def _check_slot_completion(active: _ActiveRound, kind: str, row: dict) -> None:
    if active.waiting_for_end_epoch:
        return
    if not all(slot.state is SlotState.COMPLETE for slot in active.result.slots):
        return
    active.waiting_for_end_epoch = True
    active.result.slot_completion_event_seq = row["event_seq"]
    active.result.slot_completion_ps = _event_time(kind, row)


def _handle_seeded_ack(
    active: _ActiveRound,
    ack: dict,
    residual_by_event_seq: dict[int, ResidualAck],
    threshold_ps: int,
) -> None:
    if active.waiting_for_end_epoch:
        return
    token_id = ack.get("source_token_id")
    slot_index = active.seeded_slot_by_token_id.get(token_id)
    if slot_index is None or token_id not in active.selected_seed_token_ids:
        return

    slot = active.result.slots[slot_index]
    if slot.state is not SlotState.SEEDED:
        return

    event_seq = ack["event_seq"]
    residual = residual_by_event_seq.get(event_seq)
    if _admitted(residual, threshold_ps):
        _mark_slot_complete(slot, event_seq, "seeded_ack")
        active.result.seeded_pass_count += 1
    else:
        slot.state = SlotState.PENDING
        active.result.seeded_fail_count += 1
    active.consumed_seed_ack_event_seqs.add(event_seq)
    _check_slot_completion(active, "ack", ack)


def _handle_enqueue_admission(
    active: _ActiveRound,
    token: dict,
    residual_by_event_seq: dict[int, ResidualAck],
    threshold_ps: int,
) -> None:
    if active.waiting_for_end_epoch:
        return
    ack_event_seq = token["related_ack_event_seq"]
    if ack_event_seq in active.consumed_seed_ack_event_seqs:
        return
    if ack_event_seq in active.classified_enqueue_ack_event_seqs:
        raise ReplayError(
            f"flow {token['flow_id']} ACK event {ack_event_seq} produced multiple enqueues"
        )
    active.classified_enqueue_ack_event_seqs.add(ack_event_seq)

    residual = residual_by_event_seq.get(ack_event_seq)
    valid = bool(
        _admitted(residual, threshold_ps)
        and residual is not None
        and residual.row["flow_id"] == token["flow_id"]
        and residual.row["entropy"] == token["entropy"]
    )
    if not valid:
        active.result.admission_fail_count += 1
        return

    active.result.admission_pass_count += 1
    pending = next(
        (slot for slot in active.result.slots if slot.state is SlotState.PENDING),
        None,
    )
    if pending is None:
        return
    _mark_slot_complete(pending, token["event_seq"], "linked_enqueue")
    active.result.replacement_count += 1
    _check_slot_completion(active, "token", token)


def _finish_round(active: _ActiveRound, epoch: dict) -> None:
    result = active.result
    result.end_event_seq = epoch["event_seq"]
    result.end_epoch_id = epoch["epoch_id"]
    result.end_ps = epoch["end_ps"]
    result.s_end_ps = epoch["raw_spread_ps"]
    result.delta_s = (result.s_ref_ps - result.s_end_ps) / result.s_ref_ps
    result.complete = True


def _censor(active: _ActiveRound, reason: str) -> None:
    active.result.censored = True
    active.result.censor_reason = reason


def replay_shadow(
    bundle: TraceBundle,
    slots: int = SHADOW_SLOTS,
    threshold_ps: int = RESIDUAL_THRESHOLD_PS,
    injection_time_ps: Optional[int] = None,
) -> tuple[ShadowRound, ...]:
    """Replay real FIFOs and observational eight-slot rounds in global event order."""

    if slots != SHADOW_SLOTS:
        raise ValueError(f"shadow replay requires exactly {SHADOW_SLOTS} slots")
    if threshold_ps != RESIDUAL_THRESHOLD_PS:
        raise ValueError(
            f"shadow replay requires threshold_ps={RESIDUAL_THRESHOLD_PS}"
        )

    starts = [row for row in bundle.background if row.get("operation") == "start"]
    if starts:
        injection = min(starts, key=lambda row: (row["time_ps"], row["event_seq"]))
        injection_event_seq: Optional[int] = injection["event_seq"]
        injection_time = injection["time_ps"]
        if not any(
            event.kind == "background" and event.event_seq == injection_event_seq
            for event in bundle.events
        ):
            raise ReplayError("earliest background start is absent from merged events")
    elif injection_time_ps is not None:
        if injection_time_ps < 0:
            raise ValueError("injection_time_ps must be nonnegative")
        injection_event_seq = None
        injection_time = injection_time_ps
    else:
        raise ReplayError(
            "production shadow replay requires a background start event; "
            "unit fixtures may pass injection_time_ps"
        )

    attached = attach_same_epoch_residuals(bundle, threshold_ps=threshold_ps)
    residual_by_event_seq = {item.row["event_seq"]: item for item in attached}

    fifos: dict[int, LegacyFifo] = {}
    active_by_flow: dict[int, _ActiveRound] = {}
    next_round_index: dict[int, int] = {}
    rounds: list[ShadowRound] = []

    def after_injection(event_seq: int, effective_time: int) -> bool:
        if injection_event_seq is not None:
            return event_seq > injection_event_seq
        return effective_time >= injection_time

    for event in bundle.events:
        row = event.row

        if event.kind == "token":
            flow_id = row["flow_id"]
            fifo = fifos.setdefault(flow_id, LegacyFifo())
            fifo.apply(row)
            active = active_by_flow.get(flow_id)
            if active is None:
                continue
            if row["operation"] == "dequeue_recycle":
                token_id = row["token_id"]
                slot_index = active.seeded_slot_by_token_id.get(token_id)
                if (
                    not active.waiting_for_end_epoch
                    and slot_index is not None
                    and active.result.slots[slot_index].state is SlotState.SEEDED
                ):
                    active.selected_seed_token_ids.add(token_id)
            elif row["operation"] == "enqueue_good_ack":
                _handle_enqueue_admission(
                    active,
                    row,
                    residual_by_event_seq,
                    threshold_ps,
                )
            continue

        if event.kind == "ack":
            active = active_by_flow.get(row["flow_id"])
            if active is not None:
                _handle_seeded_ack(
                    active,
                    row,
                    residual_by_event_seq,
                    threshold_ps,
                )
            continue

        if event.kind != "epoch":
            continue

        flow_id = row["flow_id"]
        active = active_by_flow.get(flow_id)
        if active is not None:
            if active.waiting_for_end_epoch:
                _finish_round(active, row)
                del active_by_flow[flow_id]
            elif row["actual_region"] != "hold":
                _censor(active, "hold_exit_before_slot_completion")
                del active_by_flow[flow_id]

        if flow_id in active_by_flow:
            continue
        if not after_injection(event.event_seq, row["end_ps"]):
            continue
        if row["actual_region"] != "hold" or row["observed_region"] != "hold":
            continue

        fifo = fifos.setdefault(flow_id, LegacyFifo())
        round_index = next_round_index.get(flow_id, 0)
        new_active = _start_round(flow_id, row, fifo, round_index)
        next_round_index[flow_id] = round_index + 1
        active_by_flow[flow_id] = new_active
        rounds.append(new_active.result)

    for active in active_by_flow.values():
        reason = (
            "trace_end_before_post_completion_epoch"
            if active.waiting_for_end_epoch
            else "trace_end_before_slot_completion"
        )
        _censor(active, reason)

    return tuple(rounds)
