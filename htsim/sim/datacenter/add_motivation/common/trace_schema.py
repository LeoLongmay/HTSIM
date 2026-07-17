"""Strict loader for versioned Prism motivation CSV traces."""

from __future__ import annotations

import csv
import dataclasses
import heapq
import math
from pathlib import Path
from typing import Callable


SCHEMA_VERSION = 2


class TraceValidationError(ValueError):
    """Raised when a motivation trace does not satisfy its recorded schema."""


class _TraceRow(dict):
    def __init__(self, values: dict, source_path: Path):
        super().__init__(values)
        self.source_path = source_path


@dataclasses.dataclass(frozen=True, slots=True)
class _CompactSchema:
    names: tuple[str, ...]
    indices: dict[str, int]
    source_path: Path


class _CompactTraceRow:
    """Read-only dict-like row backed by a tuple and a shared file schema."""

    __slots__ = ("_values", "_schema")

    def __init__(self, values: tuple[object, ...], schema: _CompactSchema):
        self._values = values
        self._schema = schema

    @property
    def source_path(self) -> Path:
        return self._schema.source_path

    def __getitem__(self, key: str) -> object:
        return self._values[self._schema.indices[key]]

    def get(self, key: str, default: object = None) -> object:
        index = self._schema.indices.get(key)
        return default if index is None else self._values[index]


@dataclasses.dataclass(frozen=True)
class EventRef:
    event_seq: int
    kind: str
    row: dict


@dataclasses.dataclass(frozen=True, slots=True)
class _CompactEventRef:
    event_seq: int
    kind: str
    row: _CompactTraceRow


@dataclasses.dataclass(frozen=True)
class TraceBundle:
    run_id: str
    ack: tuple[dict, ...]
    token: tuple[dict, ...]
    epoch: tuple[dict, ...]
    pathmap: tuple[dict, ...]
    linkmap: tuple[dict, ...]
    background: tuple[dict, ...]
    coordination: tuple[dict, ...]
    events: tuple[EventRef, ...]


def _parse_bounded_int(value: str, minimum: int, maximum: int) -> int:
    parsed = int(value, 10)
    if not minimum <= parsed <= maximum:
        raise ValueError(f"must be in [{minimum}, {maximum}]")
    return parsed


def _parse_uint32(value: str) -> int:
    return _parse_bounded_int(value, 0, 2**32 - 1)


def _parse_uint64(value: str) -> int:
    return _parse_bounded_int(value, 0, 2**64 - 1)


def _parse_int64(value: str) -> int:
    return _parse_bounded_int(value, -(2**63), 2**63 - 1)


def _parse_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("must be finite")
    return parsed


def _parse_bool(value: str) -> bool:
    if value == "0":
        return False
    if value == "1":
        return True
    raise ValueError("must be 0 or 1")


def _parse_text(value: str) -> str:
    return value


_I64 = _parse_int64
_U32 = _parse_uint32
_U64 = _parse_uint64
_F = _parse_float
_B = _parse_bool
_S = _parse_text

_SCHEMAS: dict[str, tuple[tuple[str, Callable[[str], object]], ...]] = {
    "ack": (
        ("schema_version", _U32), ("run_id", _S), ("seed", _U32), ("scenario", _S),
        ("event_seq", _U64), ("time_ps", _U64), ("flow_id", _U64),
        ("epoch_id", _U64), ("acked_psn", _U64), ("entropy", _U32),
        ("physical_path_id", _U64), ("raw_rtt_ps", _U64), ("base_rtt_ps", _U64),
        ("qdelay_ps", _I64), ("ecn", _B),
        ("genuine_sample", _B), ("retransmitted", _B),
        ("forward_path_backlog_ps", _U64), ("selection_source", _S),
        ("source_token_id", _U64), ("newly_acked_bytes", _U64),
        ("new_data_bytes_sent_total", _U64), ("cwnd_bytes", _U64),
    ),
    "token": (
        ("schema_version", _U32), ("run_id", _S), ("event_seq", _U64),
        ("time_ps", _U64), ("flow_id", _U64), ("operation", _S), ("reason", _S),
        ("token_id", _U64), ("entropy", _U32), ("queue_depth_before", _U32),
        ("queue_depth_after", _U32), ("related_ack_event_seq", _U64),
    ),
    "epoch": (
        ("schema_version", _U32), ("run_id", _S), ("event_seq", _U64),
        ("flow_id", _U64), ("epoch_id", _U64), ("start_ps", _U64), ("end_ps", _U64),
        ("sample_count", _U32), ("raw_floor_ps", _U64), ("raw_spread_ps", _U64),
        ("smooth_floor_ps", _U64), ("smooth_spread_ps", _U64),
        ("observed_region", _S), ("actual_region", _S), ("engaged", _B),
        ("entropy_coverage", _U32), ("physical_path_coverage", _U32),
        ("new_data_bytes_sent_total", _U64), ("acked_bytes_total", _U64),
        ("cwnd_bytes", _U64),
    ),
    "background": (
        ("schema_version", _U32), ("run_id", _S), ("event_seq", _U64),
        ("time_ps", _U64), ("background_id", _U32), ("operation", _S),
        ("src", _U32), ("dst", _U32), ("path_index", _U32),
        ("configured_rate_gbps", _F), ("delivered_bytes", _U64),
        ("queue_fingerprint", _S),
    ),
    "pathmap": (
        ("schema_version", _U32), ("run_id", _S), ("flow_id", _U64),
        ("entropy", _U32), ("physical_path_id", _U64), ("resolution_status", _S),
        ("queue_fingerprint", _S), ("bottleneck_rate_gbps", _F),
        ("contains_reduced_link", _B), ("ordered_queue_ids", _S),
    ),
    "linkmap": (
        ("schema_version", _U32), ("run_id", _S), ("queue_id", _U64),
        ("queue_name", _S), ("rate_gbps", _F), ("reduced_speed", _B),
    ),
    "coordination": (
        ("schema_version", _U32), ("run_id", _S), ("event_seq", _U64),
        ("time_ps", _U64), ("flow_id", _U64), ("epoch_id", _U64),
        ("round_id", _U64), ("cache_slot", _U32), ("cache_generation", _U64),
        ("floor_ps", _U64), ("spread_ps", _U64), ("spread_ref_ps", _U64),
        ("residual_ps", _U64), ("action", _S), ("reason", _S),
        ("refresh_complete", _B), ("progress", _B), ("handoff", _B),
        ("cwnd_bytes", _U64), ("control_state", _S),
    ),
}

_EVENT_KINDS = ("ack", "token", "epoch", "background", "coordination")
_COORDINATION_ACTIONS = frozenset({
    "retain",
    "invalidate",
    "pending",
    "round_complete_progress",
    "round_complete_handoff",
})


def _error(path: Path, key: str, detail: str) -> TraceValidationError:
    return TraceValidationError(f"{path}: {key}: {detail}")


def _validate_coordination_row(path: Path, row: dict) -> None:
    if row["action"] not in _COORDINATION_ACTIONS:
        raise _error(path, "action", f"unknown coordination action {row['action']!r}")
    if row["action"] == "invalidate" and row["refresh_complete"]:
        raise _error(path, "refresh_complete", "invalidate action cannot mark refresh complete")
    if row["handoff"] and row["action"] != "round_complete_handoff":
        raise _error(path, "action", "handoff requires round_complete_handoff action")
    if row["action"] == "round_complete_handoff" and not row["handoff"]:
        raise _error(path, "handoff", "round_complete_handoff action requires handoff")
    if row["action"] == "round_complete_progress" and not row["progress"]:
        raise _error(path, "progress", "round_complete_progress action requires progress")
    if row["progress"] and row["action"] != "round_complete_progress":
        raise _error(path, "action", "progress requires round_complete_progress action")


def _load_file(prefix: Path, kind: str) -> tuple[dict, ...]:
    path = Path(f"{prefix}.{kind}.csv")
    schema = _SCHEMAS[kind]
    expected_header = [name for name, _ in schema]
    try:
        stream = path.open("r", newline="", encoding="utf-8")
    except OSError as exc:
        raise _error(path, "file", str(exc)) from exc

    with stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != expected_header:
            raise _error(
                path,
                "header",
                f"expected {expected_header!r}, got {reader.fieldnames!r}",
            )

        parsed_rows = []
        previous_event_seq = None
        for line_number, raw_row in enumerate(reader, start=2):
            if set(raw_row) != set(expected_header) or any(
                raw_row[name] is None for name in expected_header
            ):
                raise _error(path, "header", f"row {line_number} has missing or extra columns")

            parsed = {}
            for key, parser in schema:
                value = raw_row[key]
                try:
                    parsed[key] = parser(value)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise _error(
                        path,
                        key,
                        f"row {line_number} has invalid value {value!r}",
                    ) from exc

            if parsed["schema_version"] != SCHEMA_VERSION:
                raise _error(
                    path,
                    "schema_version",
                    f"expected {SCHEMA_VERSION}, got {parsed['schema_version']}",
                )

            if kind == "coordination":
                _validate_coordination_row(path, parsed)

            if kind in _EVENT_KINDS:
                event_seq = parsed["event_seq"]
                if previous_event_seq is not None and event_seq <= previous_event_seq:
                    raise _error(
                        path,
                        "event_seq",
                        f"row {line_number} value {event_seq} is not strictly increasing",
                    )
                previous_event_seq = event_seq

            parsed_rows.append(_TraceRow(parsed, path))

    return tuple(parsed_rows)


def _load_file_compact(prefix: Path, kind: str) -> tuple[_CompactTraceRow, ...]:
    path = Path(f"{prefix}.{kind}.csv")
    schema = _SCHEMAS[kind]
    expected_header = [name for name, _ in schema]
    compact_schema = _CompactSchema(
        tuple(expected_header),
        {name: index for index, name in enumerate(expected_header)},
        path,
    )
    text_cache: dict[str, str] = {}
    try:
        stream = path.open("r", newline="", encoding="utf-8")
    except OSError as exc:
        raise _error(path, "file", str(exc)) from exc

    with stream:
        reader = csv.reader(stream)
        try:
            header = next(reader)
        except StopIteration:
            header = None
        if header != expected_header:
            raise _error(
                path,
                "header",
                f"expected {expected_header!r}, got {header!r}",
            )

        parsed_rows = []
        previous_event_seq = None
        nonempty_rows = (raw_values for raw_values in reader if raw_values)
        for line_number, raw_values in enumerate(nonempty_rows, start=2):
            if len(raw_values) != len(expected_header):
                raise _error(path, "header", f"row {line_number} has missing or extra columns")

            parsed_values = []
            for (key, parser), value in zip(schema, raw_values):
                try:
                    parsed = parser(value)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise _error(
                        path,
                        key,
                        f"row {line_number} has invalid value {value!r}",
                    ) from exc
                if parser is _S:
                    parsed = text_cache.setdefault(parsed, parsed)
                parsed_values.append(parsed)

            row = _CompactTraceRow(tuple(parsed_values), compact_schema)
            if row["schema_version"] != SCHEMA_VERSION:
                raise _error(
                    path,
                    "schema_version",
                    f"expected {SCHEMA_VERSION}, got {row['schema_version']}",
                )

            if kind == "coordination":
                _validate_coordination_row(path, row)

            if kind in _EVENT_KINDS:
                event_seq = row["event_seq"]
                if previous_event_seq is not None and event_seq <= previous_event_seq:
                    raise _error(
                        path,
                        "event_seq",
                        f"row {line_number} value {event_seq} is not strictly increasing",
                    )
                previous_event_seq = event_seq

            parsed_rows.append(row)

    return tuple(parsed_rows)


def _compact_events(loaded: dict[str, tuple]) -> tuple[_CompactEventRef, ...]:
    def event_stream(kind: str):
        return (
            _CompactEventRef(row["event_seq"], kind, row)
            for row in loaded[kind]
        )

    streams = (event_stream(kind) for kind in _EVENT_KINDS)
    events = tuple(heapq.merge(*streams, key=lambda event: event.event_seq))
    previous = None
    for event in events:
        if previous is not None and event.event_seq == previous.event_seq:
            raise _error(
                event.row.source_path,
                "event_seq",
                f"duplicate {event.event_seq}; first seen in {previous.row.source_path}",
            )
        previous = event
    return events


def _find_ack_by_event_seq(rows: tuple, event_seq: int):
    low = 0
    high = len(rows)
    while low < high:
        middle = (low + high) // 2
        candidate = rows[middle]["event_seq"]
        if candidate < event_seq:
            low = middle + 1
        else:
            high = middle
    if low < len(rows) and rows[low]["event_seq"] == event_seq:
        return rows[low]
    return None


def _build_bundle(trace_prefix: Path, loaded: dict[str, tuple], *, compact: bool) -> TraceBundle:
    run_id = None
    for kind, rows in loaded.items():
        path = Path(f"{trace_prefix}.{kind}.csv")
        for row in rows:
            if run_id is None:
                run_id = row["run_id"]
            elif row["run_id"] != run_id:
                raise _error(
                    path,
                    "run_id",
                    f"expected {run_id!r}, got {row['run_id']!r}",
                )

    if compact:
        events = _compact_events(loaded)
    else:
        event_list = []
        sequence_sources: dict[int, Path] = {}
        for kind in _EVENT_KINDS:
            for row in loaded[kind]:
                event_seq = row["event_seq"]
                if event_seq in sequence_sources:
                    raise _error(
                        row.source_path,
                        "event_seq",
                        f"duplicate {event_seq}; first seen in {sequence_sources[event_seq]}",
                    )
                sequence_sources[event_seq] = row.source_path
                event_list.append(EventRef(event_seq, kind, row))
        event_list.sort(key=lambda event: event.event_seq)
        events = tuple(event_list)

    previous_time = None
    previous_event_seq = None
    for event in events:
        time_key = "end_ps" if event.kind == "epoch" else "time_ps"
        effective_time = event.row[time_key]
        if previous_time is not None and effective_time < previous_time:
            raise _error(
                event.row.source_path,
                time_key,
                f"effective time {effective_time} at event_seq {event.event_seq} "
                f"precedes time {previous_time} at event_seq {previous_event_seq}",
            )
        previous_time = effective_time
        previous_event_seq = event.event_seq

    ack_by_event_seq = None if compact else {
        row["event_seq"]: row for row in loaded["ack"]
    }
    admission_ack_event_seqs = set()
    residual_reject_ack_event_seqs = set()
    for token in loaded["token"]:
        operation = token["operation"]
        if operation not in ("enqueue_good_ack", "overwrite_good_ack", "reject_high_residual"):
            continue
        related_event_seq = token["related_ack_event_seq"]
        ack = (
            _find_ack_by_event_seq(loaded["ack"], related_event_seq)
            if compact else ack_by_event_seq.get(related_event_seq)
        )
        if ack is None:
            raise _error(
                token.source_path,
                "related_ack_event_seq",
                f"ACK event {related_event_seq} does not exist",
            )
        if ack["event_seq"] >= token["event_seq"]:
            raise _error(
                token.source_path,
                "related_ack_event_seq",
                f"ACK event {related_event_seq} is not earlier than token event",
            )
        if ack["flow_id"] != token["flow_id"]:
            raise _error(
                token.source_path,
                "related_ack_event_seq",
                f"ACK flow {ack['flow_id']} differs from token flow {token['flow_id']}",
            )
        if token["entropy"] != ack["entropy"]:
            raise _error(
                token.source_path,
                "entropy",
                f"value {token['entropy']} differs from ACK entropy {ack['entropy']}",
            )
        if ack["ecn"]:
            raise _error(
                token.source_path,
                "related_ack_event_seq",
                f"ACK event {related_event_seq} is ECN marked",
            )
        if operation in ("enqueue_good_ack", "overwrite_good_ack") and related_event_seq in admission_ack_event_seqs:
            raise _error(
                token.source_path,
                "related_ack_event_seq",
                f"ACK event {related_event_seq} already produced an admission",
            )
        if operation in ("enqueue_good_ack", "overwrite_good_ack"):
            admission_ack_event_seqs.add(related_event_seq)
        else:
            if not ack["genuine_sample"]:
                raise _error(
                    token.source_path,
                    "related_ack_event_seq",
                    f"residual reject references non-genuine ACK event {related_event_seq}",
                )
            if related_event_seq in residual_reject_ack_event_seqs:
                raise _error(
                    token.source_path,
                    "related_ack_event_seq",
                    f"ACK event {related_event_seq} already produced a residual reject",
                )
            residual_reject_ack_event_seqs.add(related_event_seq)

    last_ack_event_by_epoch = {}
    for ack in loaded["ack"]:
        identity = (ack["flow_id"], ack["epoch_id"])
        last_ack_event_by_epoch[identity] = max(
            ack["event_seq"],
            last_ack_event_by_epoch.get(identity, 0),
        )
    for epoch in loaded["epoch"]:
        identity = (epoch["flow_id"], epoch["epoch_id"])
        last_ack_event = last_ack_event_by_epoch.get(identity)
        if last_ack_event is not None and epoch["event_seq"] <= last_ack_event:
            raise _error(
                epoch.source_path,
                "event_seq",
                f"epoch closes at {epoch['event_seq']} before ACK event {last_ack_event}",
            )

    return TraceBundle(
        run_id="" if run_id is None else run_id,
        ack=loaded["ack"],
        token=loaded["token"],
        epoch=loaded["epoch"],
        pathmap=loaded["pathmap"],
        linkmap=loaded["linkmap"],
        background=loaded["background"],
        coordination=loaded["coordination"],
        events=events,
    )


def load_trace(prefix: Path | str) -> TraceBundle:
    """Load and validate the seven CSV files emitted for one trace prefix."""

    trace_prefix = Path(prefix)
    loaded = {kind: _load_file(trace_prefix, kind) for kind in _SCHEMAS}
    return _build_bundle(trace_prefix, loaded, compact=False)


def load_trace_compact(prefix: Path | str) -> TraceBundle:
    """Load an equivalent trace using compact read-only rows for M2 analysis."""

    trace_prefix = Path(prefix)
    loaded = {kind: _load_file_compact(trace_prefix, kind) for kind in _SCHEMAS}
    return _build_bundle(trace_prefix, loaded, compact=True)
