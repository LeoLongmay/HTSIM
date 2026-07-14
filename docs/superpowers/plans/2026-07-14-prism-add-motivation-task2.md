# Prism Residual-Spread Motivation Task 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the M1 entropy-quality and M2 redistribution-progress motivation experiments under `htsim/sim/datacenter/add_motivation` without implementing residual recycling or congestion-control handoff.

**Architecture:** Existing behavior-neutral ACK, Legacy REPS token, epoch, path, and link traces remain the simulator boundary. Versioned observation fields and a deterministic fixed-path background source provide the remaining primitive facts; Python validates same-epoch residuals, computes M1 persistence, and replays M2 virtual eight-slot rounds without feeding any result back into the simulator.

**Tech Stack:** C++17, HTSIM UEC/Legacy REPS, Python 3 standard library, NumPy, Matplotlib, Bash, CMake.

---

## Scope Guardrails

- Do not implement entropy invalidation, cache replacement control, recycling, CC handoff, a new cwnd action, or failure-freezing behavior.
- Keep `-load_balancing_algo reps` mapped to `UecMpRepsLegacy`.
- The virtual eight-slot structure exists only in `shadow_replay.py`; never describe it as the real Legacy REPS FIFO.
- M1 and M2 use `T_cc=T_spray=14 us`, `kappa=1`, and `n_min=3` in primary runs.
- Keep ECN enabled. Capacity reduction is named `degraded` or `throttled`, never hard failure.
- Calibration seeds are `101,102,103`; formal seeds are `13,14,15,16,17` after `formal.csv` is locked.
- All smoke, calibration, formal, CSV, figure, and compiled test output stays under `htsim/sim/datacenter/add_motivation`; `/tmp` is limited to existing self-cleaning trace fixtures inside unit tests.
- Preserve unrelated dirty-worktree files.

## Completed Foundation

The following commits are prerequisites and must not be reimplemented:

```text
194159d trace: expose Legacy REPS token lifecycle
21100cc trace: add versioned motivation CSV writer
a3b1ba9 docs: clarify motivation metadata sequencing
5e753fe trace: observe ACK epochs without changing control
de3ad18 fix: correlate probe and retransmission ACK selections
acc8dab trace: record motivation path and link metadata
10d76c8 trace: validate motivation path tracing config
```

Existing tests:

```text
htsim/sim/datacenter/add_motivation/common/tests/test_legacy_reps_trace.cpp
htsim/sim/datacenter/add_motivation/common/tests/test_trace_writer.cpp
htsim/sim/datacenter/add_motivation/common/tests/test_motivation_epoch.cpp
htsim/sim/datacenter/add_motivation/common/tests/test_motivation_path.cpp
```

## File Map

**Observation and scenario C++**

- Modify `htsim/sim/motivation_trace.h`: schema-v2 ACK/epoch counters and background records.
- Modify `htsim/sim/motivation_trace.cpp`: exact v2 headers and background CSV writer.
- Modify `htsim/sim/uec.h`: trace-only cumulative new-data counter.
- Modify `htsim/sim/uec.cpp`: update counter and emit ACK/epoch snapshots.
- Create `htsim/sim/motivation_background.h`: deterministic fixed-path background source and config types.
- Create `htsim/sim/motivation_background.cpp`: strict CSV parser, packet source, sink, and finish accounting.
- Modify `htsim/sim/CMakeLists.txt`: compile `motivation_background.cpp`.
- Modify `htsim/sim/datacenter/fat_tree_topology.h`: validated degraded-link ratio setter.
- Modify `htsim/sim/datacenter/fat_tree_topology.cpp`: use neutral degraded-link diagnostics.
- Modify `htsim/sim/datacenter/main_uec.cpp`: degraded-capacity CLI and background-flow installation.

**Common experiment code**

- Create `htsim/sim/datacenter/add_motivation/common/__init__.py`.
- Create `htsim/sim/datacenter/add_motivation/common/trace_schema.py`: strict versioned CSV loading and causal validation.
- Create `htsim/sim/datacenter/add_motivation/common/residual_join.py`: exact same-epoch residual attachment.
- Create `htsim/sim/datacenter/add_motivation/common/statistics.py`: flow-cluster bootstrap helpers.
- Create `htsim/sim/datacenter/add_motivation/common/shadow_replay.py`: Legacy FIFO reconstruction and virtual rounds.
- Create `htsim/sim/datacenter/add_motivation/common/run_case.py`: one-run execution and manifest creation.

**M1**

- Create `htsim/sim/datacenter/add_motivation/expM1_entropy_quality/{README.md,calibrate.sh,repro.sh,analyze.py,make_figs.py}`.
- Create `htsim/sim/datacenter/add_motivation/expM1_entropy_quality/configs/{calibration.csv,formal.csv}`.
- Create `htsim/sim/datacenter/add_motivation/expM1_entropy_quality/tests/test_analyze.py`.

**M2**

- Create `htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/{README.md,calibrate.sh,repro.sh,analyze.py,make_figs.py}`.
- Create `htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/configs/{calibration.csv,formal.csv}`.
- Create `htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/gen_workload.py`.
- Create `htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/tests/test_analyze.py`.

---

### Task 5: Observation Schema v2 and Byte/Cwnd Snapshots

**Files:**
- Modify: `htsim/sim/motivation_trace.h:19-107`
- Modify: `htsim/sim/motivation_trace.cpp:8-162`
- Modify: `htsim/sim/uec.h:261-315,400-570`
- Modify: `htsim/sim/uec.cpp:839-915,1290-1484,3160-3240`
- Modify: `htsim/sim/datacenter/add_motivation/common/tests/test_trace_writer.cpp`
- Modify: `htsim/sim/datacenter/add_motivation/common/tests/test_motivation_epoch.cpp`

- [ ] **Step 1: Extend the writer test with exact schema-v2 headers**

Update the expected ACK and epoch headers and add a background row assertion:

```cpp
assert(lineAt(prefix + ".ack.csv", 1) ==
    "schema_version,run_id,seed,scenario,event_seq,time_ps,flow_id,epoch_id,acked_psn,"
    "entropy,physical_path_id,raw_rtt_ps,base_rtt_ps,qdelay_ps,ecn,genuine_sample,"
    "retransmitted,forward_path_backlog_ps,selection_source,source_token_id,"
    "newly_acked_bytes,new_data_bytes_sent_total,cwnd_bytes");
assert(lineAt(prefix + ".epoch.csv", 1) ==
    "schema_version,run_id,event_seq,flow_id,epoch_id,start_ps,end_ps,sample_count,"
    "raw_floor_ps,raw_spread_ps,smooth_floor_ps,smooth_spread_ps,observed_region,"
    "actual_region,engaged,entropy_coverage,physical_path_coverage,"
    "new_data_bytes_sent_total,acked_bytes_total,cwnd_bytes");
assert(lineAt(prefix + ".background.csv", 1) ==
    "schema_version,run_id,event_seq,time_ps,background_id,operation,src,dst,path_index,"
    "configured_rate_gbps,delivered_bytes,queue_fingerprint");
```

- [ ] **Step 2: Compile to verify the new record fields are absent**

Run from `htsim/sim/datacenter`:

```bash
mkdir -p add_motivation/.test-bin
g++ -std=c++17 -I.. add_motivation/common/tests/test_trace_writer.cpp \
  ../build/libhtsim.a -o add_motivation/.test-bin/test_trace_writer_v2
```

Expected: compilation fails because `MotivationBackgroundRecord` and the v2 fields do not exist.

- [ ] **Step 3: Add exact v2 record fields and writer methods**

Add to `MotivationAckRecord`:

```cpp
uint64_t newly_acked_bytes;
uint64_t new_data_bytes_sent_total;
uint64_t cwnd_bytes;
```

Add to `MotivationEpochRecord`:

```cpp
uint64_t new_data_bytes_sent_total;
uint64_t acked_bytes_total;
uint64_t cwnd_bytes;
```

Add the background record and method:

```cpp
struct MotivationBackgroundRecord {
    uint64_t event_seq;
    uint64_t time_ps;
    uint32_t background_id;
    std::string operation;
    uint32_t src;
    uint32_t dst;
    uint32_t path_index;
    double configured_rate_gbps;
    uint64_t delivered_bytes;
    std::string queue_fingerprint;
};

void logBackground(const MotivationBackgroundRecord& record);
std::ofstream _background;
```

Set `kSchemaVersion=2`, open `<prefix>.background.csv`, write the exact headers from Step 1, emit
the new values, and include all six streams in `close()`.

- [ ] **Step 4: Add trace-only byte snapshots without changing control**

Add a zero-initialized `uint64_t _motivation_new_data_bytes_sent_total` to `UecSrc`. In
`sendNewPacket`, after a new data packet is successfully constructed and before returning its size,
increment the counter only when motivation tracing is enabled for that flow:

```cpp
if (_motivation_trace_writer.enabledFor(flowId())) {
    _motivation_new_data_bytes_sent_total += full_pkt_size;
}
```

Pass `newly_recvd_bytes`, `_motivation_new_data_bytes_sent_total`, and `_cwnd` into
`motivationLogAck`. At epoch logging, snapshot `_motivation_new_data_bytes_sent_total`,
`_received_bytes`, and `_cwnd`. These fields are observations only and must not be read by CC or
multipath code.

- [ ] **Step 5: Rebuild and run all four existing C++ motivation tests**

```bash
cmake --build ../build --target htsim -j2
mkdir -p add_motivation/.test-bin
for t in test_legacy_reps_trace test_trace_writer test_motivation_epoch test_motivation_path; do
  g++ -std=c++17 -I.. "add_motivation/common/tests/${t}.cpp" \
    ../build/libhtsim.a -o "add_motivation/.test-bin/${t}"
  "add_motivation/.test-bin/${t}"
done
```

Expected: all tests exit 0; writer rows use schema version 2.

- [ ] **Step 6: Commit Task 5**

```bash
git add htsim/sim/motivation_trace.h htsim/sim/motivation_trace.cpp \
  htsim/sim/uec.h htsim/sim/uec.cpp \
  htsim/sim/datacenter/add_motivation/common/tests/test_trace_writer.cpp \
  htsim/sim/datacenter/add_motivation/common/tests/test_motivation_epoch.cpp
git commit -m "trace: add motivation byte and cwnd snapshots"
```

---

### Task 6: Strict Trace Loading and Same-Epoch Residual Join

**Files:**
- Create: `htsim/sim/datacenter/add_motivation/common/__init__.py`
- Create: `htsim/sim/datacenter/add_motivation/common/trace_schema.py`
- Create: `htsim/sim/datacenter/add_motivation/common/residual_join.py`
- Create: `htsim/sim/datacenter/add_motivation/common/tests/test_trace_schema.py`
- Create: `htsim/sim/datacenter/add_motivation/common/tests/test_residual_join.py`

- [ ] **Step 1: Write failing schema and residual tests**

Use `tempfile.TemporaryDirectory()` and `csv.DictWriter` to create one valid run. The tests must
assert:

```python
bundle = load_trace(prefix)
assert bundle.run_id == "fixture"
assert [event.event_seq for event in bundle.events] == [0, 1, 2]

joined = attach_same_epoch_residuals(bundle)
assert [row.residual_ps for row in joined] == [0, 12_000_000]
assert joined[1].high_residual is True
```

Additional tests create: schema version `1`, duplicate `event_seq`, mismatched `run_id`, an ACK
whose `epoch_id` is absent, and an epoch whose recorded raw extrema disagree with genuine ACKs.
Each must raise `TraceValidationError` with the offending filename and key.

- [ ] **Step 2: Run tests to verify imports fail**

```bash
python3 -m unittest discover -s htsim/sim/datacenter/add_motivation/common/tests \
  -p 'test_*join.py' -v
python3 -m unittest discover -s htsim/sim/datacenter/add_motivation/common/tests \
  -p 'test_trace_schema.py' -v
```

Expected: `ModuleNotFoundError` for the new modules.

- [ ] **Step 3: Implement exact schema loading**

Define:

```python
SCHEMA_VERSION = 2

class TraceValidationError(ValueError):
    pass

@dataclasses.dataclass(frozen=True)
class EventRef:
    event_seq: int
    kind: str
    row: dict

@dataclasses.dataclass(frozen=True)
class TraceBundle:
    run_id: str
    ack: tuple[dict, ...]
    token: tuple[dict, ...]
    epoch: tuple[dict, ...]
    pathmap: tuple[dict, ...]
    linkmap: tuple[dict, ...]
    background: tuple[dict, ...]
    events: tuple[EventRef, ...]

def load_trace(prefix: pathlib.Path | str) -> TraceBundle:
    ...
```

Load with `csv.DictReader`, require exact headers, parse integer/float/bool fields explicitly, and
reject extra columns. Merge ACK/token/epoch/background rows by `event_seq`; require uniqueness and
strict monotonic order. Static metadata does not enter the event stream. Require one run ID across
all nonempty files.

- [ ] **Step 4: Implement same-epoch residual attachment**

Define:

```python
@dataclasses.dataclass(frozen=True)
class ResidualAck:
    row: dict
    floor_ps: int
    spread_ps: int
    residual_ps: int
    high_residual: bool

def attach_same_epoch_residuals(bundle, threshold_ps=14_000_000):
    ...
```

Index epochs by `(flow_id, epoch_id)`. Include only `genuine_sample=1`. For every closed epoch,
recompute `min(qdelay_ps)` and `max-min` from joined genuine ACKs and require exact equality with
`raw_floor_ps` and `raw_spread_ps`. Compute `max(qdelay-floor, 0)` and never read smooth fields.

- [ ] **Step 5: Run common Python tests**

```bash
python3 -m unittest discover -s htsim/sim/datacenter/add_motivation/common/tests \
  -p 'test_*.py' -v
```

Expected: all schema and join tests pass.

- [ ] **Step 6: Commit Task 6**

```bash
git add htsim/sim/datacenter/add_motivation/common
git commit -m "analysis: validate motivation traces and residual joins"
```

---

### Task 7: M1 Degraded-Capacity Scenario and Reproducible Runner

**Files:**
- Modify: `htsim/sim/datacenter/fat_tree_topology.h:60-75`
- Modify: `htsim/sim/datacenter/fat_tree_topology.cpp:900-1045,1160-1200`
- Modify: `htsim/sim/datacenter/main_uec.cpp:80-150,540-565,850-865`
- Create: `htsim/sim/datacenter/add_motivation/common/run_case.py`
- Create: `htsim/sim/datacenter/add_motivation/common/tests/one_flow.cm`
- Create: `htsim/sim/datacenter/add_motivation/common/tests/test_degraded_cli.sh`
- Create: `htsim/sim/datacenter/add_motivation/common/tests/test_run_case.py`
- Create: `htsim/sim/datacenter/add_motivation/expM1_entropy_quality/configs/calibration.csv`
- Create: `htsim/sim/datacenter/add_motivation/expM1_entropy_quality/configs/formal.csv`
- Create: `htsim/sim/datacenter/add_motivation/expM1_entropy_quality/calibrate.sh`
- Create: `htsim/sim/datacenter/add_motivation/expM1_entropy_quality/repro.sh`

- [ ] **Step 1: Write the failing degraded-capacity CLI smoke test**

The fixture is:

```text
Nodes 128
Connections 1
16->0 start 1 size 1000000
```

The shell test runs `htsim_uec` with:

```bash
-degraded_links 2 -degraded_capacity_gbps 50
```

and requires stdout to contain `degraded_links 2`, `degraded_capacity_gbps 50`, and a topology
diagnostic containing `Degraded:`. It rejects `Unknown parameter`.

- [ ] **Step 2: Run the smoke test to verify the CLI is absent**

```bash
bash htsim/sim/datacenter/add_motivation/common/tests/test_degraded_cli.sh
```

Expected: nonzero exit with `Unknown parameter -degraded_links`.

- [ ] **Step 3: Add validated degraded-link aliases**

Add to `FatTreeTopologyCfg`:

```cpp
void set_degraded_link_ratio(double ratio) {
    if (!(ratio > 0.0 && ratio <= 1.0))
        throw std::invalid_argument("degraded link ratio must be in (0,1]");
    _failed_link_ratio = ratio;
}
```

Parse `-degraded_links <count>` and `-degraded_capacity_gbps <rate>` in `main_uec.cpp`. Preserve
`-failed` as a compatibility alias. Before topology construction, require the degraded rate to be
in `(0, normal_rate]`, call `set_failed_links(count)`, and set ratio to
`degraded_rate/normal_rate`. Change topology diagnostics from `Failure:` to `Degraded:` without
changing queue rate, queue size, or ECN scaling behavior.

- [ ] **Step 4: Implement one-run execution and manifest writing**

`run_case.py` accepts explicit arguments rather than a free-form command string:

```python
def run_case(*, experiment, phase, run_id, cc, seed, topology, traffic,
             out_dir, trace_prefix, degraded_links=0,
             degraded_capacity_gbps=100.0, background_config=None):
    ...
```

Build a `subprocess.run([...], check=True)` argv for `htsim_uec` with Legacy REPS, paths 8, MTU
4150 bytes, `-q 211` (875,650 bytes, the nearest packet-granular representation of 875 KB),
`-disable_trim`, ECN defaults, 14 us thresholds, `kappa=1`, `n_min=3`, and motivation tracing.
Write `<run_id>.manifest.json` atomically after completion with commit, argv, seed, topology,
traffic SHA-256, exact queue bytes, config values, schema version, phase, and output filenames.
Never invoke a shell.

- [ ] **Step 5: Add the exact M1 calibration matrix and runners**

`calibration.csv` columns are:

```text
scenario_id,degraded_links,degraded_capacity_gbps,offered_load,seed
```

Rows contain all products of capacities `{75,50,25}`, link counts `{2,4,8}`, loads
`{0.3,0.5,0.7}`, and seeds `{101,102,103}`, plus the zero-degraded symmetric control at every load
and seed. `formal.csv` contains only the header until calibration selection writes one symmetric
and one gray scenario for seeds `13..17`.

Generate 8 MB Poisson many-to-many traffic with the existing `poisson_load.py`, 64 senders, 16
receivers, 8 ms arrival window, and 1600 Gbps reference capacity. `calibrate.sh` writes only under
`data/calibration`; `repro.sh smoke|full` writes under `data/smoke` or `data/formal`.

- [ ] **Step 6: Run unit and CLI tests**

```bash
cmake --build htsim/sim/build --target htsim_uec -j2
bash htsim/sim/datacenter/add_motivation/common/tests/test_degraded_cli.sh
python3 -m unittest discover -s htsim/sim/datacenter/add_motivation/common/tests \
  -p 'test_run_case.py' -v
bash -n htsim/sim/datacenter/add_motivation/expM1_entropy_quality/calibrate.sh
bash -n htsim/sim/datacenter/add_motivation/expM1_entropy_quality/repro.sh
```

Expected: all commands exit 0 and no output appears outside `add_motivation`.

- [ ] **Step 7: Commit Task 7**

```bash
git add htsim/sim/datacenter/fat_tree_topology.h \
  htsim/sim/datacenter/fat_tree_topology.cpp htsim/sim/datacenter/main_uec.cpp \
  htsim/sim/datacenter/add_motivation/common/run_case.py \
  htsim/sim/datacenter/add_motivation/common/tests \
  htsim/sim/datacenter/add_motivation/expM1_entropy_quality
git commit -m "experiment: add M1 degraded-capacity runner"
```

---

### Task 8: M1 Persistence Analysis, Selection, and Figure

**Files:**
- Create: `htsim/sim/datacenter/add_motivation/common/statistics.py`
- Create: `htsim/sim/datacenter/add_motivation/common/tests/test_statistics.py`
- Create: `htsim/sim/datacenter/add_motivation/expM1_entropy_quality/analyze.py`
- Create: `htsim/sim/datacenter/add_motivation/expM1_entropy_quality/make_figs.py`
- Create: `htsim/sim/datacenter/add_motivation/expM1_entropy_quality/tests/test_analyze.py`
- Create: `htsim/sim/datacenter/add_motivation/expM1_entropy_quality/README.md`

- [ ] **Step 1: Write failing M1 metric tests**

Construct `ResidualAck` fixtures for two flows and repeated entropies. Assert:

```python
summary = summarize_run(bundle, threshold_ps=14_000_000)
assert summary.unmarked_high_ratio == 2 / 5
assert summary.next_high_given_current_high == 1.0
assert summary.next_high_given_current_low == 0.25
assert summary.risk_ratio == 4.0
assert summary.unmatched_next_use == 1
```

Add a token fixture where an `enqueue_good_ack` points to a high-residual unmarked ACK, the token is
later dequeued, and its selected packet returns high residual. Assert both shadow-rejection exposure
and rejected-token future-high rate. Duplicate entropy values with different token IDs must not
collide.

- [ ] **Step 2: Run tests to verify the analyzer is absent**

```bash
python3 -m unittest discover \
  -s htsim/sim/datacenter/add_motivation/expM1_entropy_quality/tests -v
```

Expected: import failure for `analyze`.

- [ ] **Step 3: Implement flow-cluster bootstrap**

In `statistics.py`, implement:

```python
def cluster_bootstrap(rows, cluster_key, statistic, *, samples=10_000, seed=20260714):
    clusters = sorted({cluster_key(row) for row in rows})
    rng = random.Random(seed)
    estimates = []
    for _ in range(samples):
        selected = [rng.choice(clusters) for _ in clusters]
        sample = [row for cluster in selected for row in rows
                  if cluster_key(row) == cluster]
        estimates.append(statistic(sample))
    estimates.sort()
    return estimates[int(.025 * samples)], estimates[int(.975 * samples)]
```

Reject empty clusters and non-finite statistics with explicit `ValueError` messages.

- [ ] **Step 4: Implement M1 metrics and next-use matching**

Sort ACKs by `(flow_id,event_seq)`. For each genuine unmarked ACK, match the next genuine ACK with
the same `(flow_id,entropy)`; the matched ACK retains its own attached epoch residual. Report match
interval in ps and epochs. Do not impose a hidden maximum interval.

Join `enqueue_good_ack.related_ack_event_seq` to ACK classification. Join later
`dequeue_recycle.token_id` and ACK `source_token_id` by exact token identity. Compute entropy and
deduplicated physical-path direction checks, coverage, completion rate, goodput, and P99 FCT.

For formal results, require gray phi above the load-matched control in every seed, a 10,000-sample
flow-cluster bootstrap 95% lower confidence bound for risk ratio above one, nontrivial absolute
future-high probability, and matching entropy/path direction. Emit `accepted=0` with explicit
failed predicates when any requirement is false.

- [ ] **Step 5: Implement calibration-only formal selection**

Require every seed in a candidate cell to satisfy completion `>=0.99`, nonzero unmarked
denominator, at least 75% of flows with entropy coverage `>=6` and path coverage `>=2`, gray phi
above load-matched control, and risk-ratio direction `>1`. Rank by the minimum-over-seeds phi
increase, then lower degraded-link count, then higher capacity. Write the selected control and gray
rows for exactly seeds `13..17` to `configs/formal.csv` using atomic replacement.

Formal analysis never writes or changes `formal.csv`.

- [ ] **Step 6: Implement the three-panel M1 figure**

Reuse `prism_eval/common/plot_style.py`. Read only generated aggregate CSV files. Render:

1. symmetric/gray ECDF of unmarked residual with a 14 us vertical line;
2. next-use future-high probability for current-low/current-high with flow-cluster 95% CIs;
3. shadow-rejection exposure and rejected-token future-high rate.

Save exactly:

```text
figs/m1_entropy_quality.png
figs/m1_entropy_quality.pdf
```

- [ ] **Step 7: Run M1 unit tests and plot self-test**

```bash
python3 -m unittest discover \
  -s htsim/sim/datacenter/add_motivation/expM1_entropy_quality/tests -v
python3 htsim/sim/datacenter/add_motivation/expM1_entropy_quality/make_figs.py --selftest
```

Expected: tests pass; self-test creates project-local synthetic PNG/PDF and removes its synthetic
CSV fixture.

- [ ] **Step 8: Commit Task 8**

```bash
git add htsim/sim/datacenter/add_motivation/common/statistics.py \
  htsim/sim/datacenter/add_motivation/common/tests/test_statistics.py \
  htsim/sim/datacenter/add_motivation/expM1_entropy_quality
git commit -m "analysis: add M1 entropy-quality evidence"
```

---

### Task 9: Deterministic Fixed-Path M2 Background Traffic

**Files:**
- Create: `htsim/sim/motivation_background.h`
- Create: `htsim/sim/motivation_background.cpp`
- Modify: `htsim/sim/CMakeLists.txt:53-131`
- Modify: `htsim/sim/datacenter/main_uec.cpp:70-150,250-280,930-960,1038-1260`
- Modify: `htsim/sim/datacenter/add_motivation/common/tests/test_trace_writer.cpp`
- Create: `htsim/sim/datacenter/add_motivation/common/tests/test_motivation_background.cpp`

- [ ] **Step 1: Write a failing deterministic-source test**

The test writes this strict config:

```text
background_id,src,dst,path_index,rate_gbps,start_ps,stop_ps
0,16,0,3,25,200000000,1200000000
```

It asserts parser values, rejects duplicate IDs and `stop_ps<=start_ps`, then connects a source to a
direct test route and checks packet count over a fixed interval. Seed `random()`, run an
absent-background fixture, and assert the next random value is unchanged.

- [ ] **Step 2: Compile to verify the source is absent**

```bash
cd htsim/sim/datacenter
mkdir -p add_motivation/.test-bin
g++ -std=c++17 -I.. add_motivation/common/tests/test_motivation_background.cpp \
  ../build/libhtsim.a -o add_motivation/.test-bin/test_motivation_background
```

Expected: `motivation_background.h` is missing.

- [ ] **Step 3: Implement strict config parsing and a no-RNG source**

Define:

```cpp
struct MotivationBackgroundSpec {
    uint32_t background_id;
    uint32_t src;
    uint32_t dst;
    uint32_t path_index;
    linkspeed_bps rate;
    simtime_picosec start_ps;
    simtime_picosec stop_ps;
};

std::vector<MotivationBackgroundSpec>
loadMotivationBackgroundConfig(const std::string& path);
```

The parser requires the exact header, decimal integer fields, finite positive rate, unique IDs,
`src!=dst`, and `start<stop`. It rejects whitespace-surrounded values rather than guessing.

Implement `MotivationBackgroundSrc` using `CbrPacket` with a fixed 1500-byte packet and period
`ceil(1500*8e12/rate)`. It schedules from `start_ps` through but not including `stop_ps`, calls no
RNG API, and exposes sent bytes. Implement `MotivationBackgroundSink` with delivered-byte count.

- [ ] **Step 4: Install background routes without touching foreground multipath**

Parse:

```text
-motivation_background_config <csv>
```

After all foreground UEC flows and FIBs are installed, call
`topo[0]->get_bidir_paths(src,dst,false)`, validate `path_index`, clone that one route, append the
background sink, and connect the deterministic source. Enumerate `BaseQueue` elements in the route
to construct a pipe-delimited `queue_fingerprint`.

Log one `start` record at `start_ps` and one `finish` record at `stop_ps` with configured rate and
delivered bytes. Both consume the shared motivation `event_seq`. A missing background config must
allocate no sources and call no RNG.

- [ ] **Step 5: Rebuild and run background plus writer tests**

```bash
cmake --build htsim/sim/build --target htsim_uec -j2
cd htsim/sim/datacenter
mkdir -p add_motivation/.test-bin
for t in test_trace_writer test_motivation_background; do
  g++ -std=c++17 -I.. "add_motivation/common/tests/${t}.cpp" \
    ../build/libhtsim.a -o "add_motivation/.test-bin/${t}"
  "add_motivation/.test-bin/${t}"
done
```

Expected: both tests exit 0; the source emits the exact deterministic byte count.

- [ ] **Step 6: Commit Task 9**

```bash
git add htsim/sim/motivation_background.h htsim/sim/motivation_background.cpp \
  htsim/sim/CMakeLists.txt htsim/sim/datacenter/main_uec.cpp \
  htsim/sim/datacenter/add_motivation/common/tests/test_trace_writer.cpp \
  htsim/sim/datacenter/add_motivation/common/tests/test_motivation_background.cpp
git commit -m "experiment: add deterministic motivation background traffic"
```

---

### Task 10: Legacy FIFO Reconstruction and Eight-Slot Shadow Rounds

**Files:**
- Create: `htsim/sim/datacenter/add_motivation/common/shadow_replay.py`
- Create: `htsim/sim/datacenter/add_motivation/common/tests/test_shadow_replay.py`

- [ ] **Step 1: Write failing hand-authored replay tests**

Create event fixtures covering:

- FIFO enqueue/dequeue order and duplicate entropy values with distinct token IDs;
- HOLD entry with fewer than eight queued tokens;
- seeded low-residual ACK completion;
- high residual and ECN invalidation leaving a slot pending;
- invalidation alone not completing a slot;
- low-residual replacement ACK plus linked enqueue completing one pending slot;
- flow finish and HOLD exit right-censoring;
- round completion followed by next-epoch `S_end`;
- normalized `delta_S=(S_ref-S_end)/S_ref` direction.

The core positive fixture asserts:

```python
rounds = replay_shadow(bundle, slots=8, threshold_ps=14_000_000)
assert rounds[0].complete is True
assert rounds[0].s_ref_ps == 20_000_000
assert rounds[0].s_end_ps == 12_000_000
assert rounds[0].delta_s == 0.4
```

- [ ] **Step 2: Run the test to verify the module is absent**

```bash
python3 -m unittest discover -s htsim/sim/datacenter/add_motivation/common/tests \
  -p 'test_shadow_replay.py' -v
```

Expected: import failure for `shadow_replay`.

- [ ] **Step 3: Implement exact FIFO reconstruction**

Define:

```python
@dataclasses.dataclass
class LegacyToken:
    token_id: int
    entropy: int

class LegacyFifo:
    def apply(self, token_event): ...
    def snapshot(self, limit=8): ...
```

`enqueue_good_ack` appends. `dequeue_recycle` must match and remove the current front token;
otherwise raise `ReplayError`. First-window and random-empty selections do not mutate the FIFO.

- [ ] **Step 4: Implement virtual slot and round state**

Define states `SEEDED`, `PENDING`, and `COMPLETE`, keyed by slot index. Seed from the first eight FIFO
tokens at the first post-injection epoch whose `observed_region` is `hold`; missing tokens are
pending. Associate seeded sends/ACKs through `source_token_id`, not entropy.

On ACK, store admission by its ACK `event_seq`. On a linked enqueue:

- if its ACK is genuine, unmarked, and residual `<14 us`, use it to complete the first pending slot;
- otherwise leave all pending slots unchanged.

A seeded token completes only after its selected packet returns a genuine admitted ACK. A rejected
seed becomes pending. Complete the round only when all eight slots are complete. Record `S_end` at
the next epoch boundary. Censor on HOLD exit or end-of-trace before that boundary.

- [ ] **Step 5: Run replay and common tests**

```bash
python3 -m unittest discover -s htsim/sim/datacenter/add_motivation/common/tests \
  -p 'test_*.py' -v
```

Expected: all tests pass, including duplicate-entropy token isolation and censoring.

- [ ] **Step 6: Commit Task 10**

```bash
git add htsim/sim/datacenter/add_motivation/common/shadow_replay.py \
  htsim/sim/datacenter/add_motivation/common/tests/test_shadow_replay.py
git commit -m "analysis: replay motivation shadow validation rounds"
```

---

### Task 11: M2 Workload, Capacity Witness, Selection, and Figure

**Files:**
- Create: `htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/gen_workload.py`
- Create: `htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/configs/calibration.csv`
- Create: `htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/configs/formal.csv`
- Create: `htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/analyze.py`
- Create: `htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/make_figs.py`
- Create: `htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/tests/test_analyze.py`

- [ ] **Step 1: Write failing workload and capacity tests**

Assert `gen_workload.py` creates deterministic foreground `.cm` and background CSV files for
`foreground_flows=16`, `hot_path_groups=4`, `background_utilization=0.5`, and a fixed seed. Starts
must be 1 ps for foreground and `20E` for background; stops must be `120E`. The test passes an
explicit `base_rtt_ps` and verifies those two epoch conversions exactly.

Build path/link/background fixtures with duplicate queue appearances and assert:

```python
witness = capacity_witness(bundle, round_start_ps, round_end_ps)
assert witness.c_healthy_gbps == 400
assert witness.c_hot_residual_gbps == 100
assert witness.c_effective_residual_gbps == 500
assert witness.classify(l_foreground_gbps=350) == "recoverable"
assert witness.classify(l_foreground_gbps=450) == "persistent"
```

The test must fail if a background fingerprint lacks exactly one target-pod cut queue matching
`^CS[0-9]+->US[0-9]+\([0-9]+\)$`.

- [ ] **Step 2: Run tests to verify M2 modules are absent**

```bash
python3 -m unittest discover \
  -s htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/tests -v
```

Expected: import failure for `analyze` and `gen_workload`.

- [ ] **Step 3: Implement deterministic M2 workload generation**

Before calibration, run one traced no-background cross-pod flow and take the minimum positive
`base_rtt_ps` over its genuine ACKs; require at least 95% of genuine ACKs to equal that minimum.
Store it in `configs/base_rtt_ps.txt` and retain the preflight manifest. `gen_workload.py` requires
this value and refuses a missing or nonpositive value.

Generate cross-pod 256 MB foreground flows with explicit flow IDs, start at 1 ps, and duration
longer than `120E`. Generate background specs with distinct route indices and aggregate each hot
group's configured rate to `utilization*100 Gbps`. Use local `random.Random(seed)` only for endpoint
pairing; sorted output must be byte-identical at the same seed.

The coarse grid is:

```text
foreground_flows        8,16,32
hot_path_groups         2,4,6
background_utilization  0.25,0.50,0.75
seed                    101
```

Confirmation uses seeds `101,102,103` for the best three recoverable and best three persistent
coarse cells. `formal.csv` remains header-only until confirmation selection.

- [ ] **Step 4: Implement capacity and offered-load evidence**

Deduplicate target-pod cut links by queue name from `pathmap`, `linkmap`, and background
fingerprints. Compute background load per hot cut link from configured start records and verify it
against finish delivery within 5%.

For each round, compute foreground new-data offered rate from differences in
`new_data_bytes_sent_total` between bracketing epoch records, divided by elapsed simulation time.
Do not substitute sink throughput. Compute `C_healthy`, `C_hot_residual`, and
`C_effective_residual` exactly as the spec defines.

- [ ] **Step 5: Implement M2 summaries and deterministic pair selection**

Summarize episode occupancy, completion, censoring, round duration, `F/S/S_ref/S_end/delta_S`,
HOLD duration, cwnd, FIFO depth, virtual replacement counts, admission counts, background delivery,
capacity, offered load, queueing delay, and coverage. Report literal no-progress plus diagnostic
tolerances of 1, 2, and 4 us without changing primary classification.

Recoverable confirmation requires every calibration seed to satisfy the recoverable capacity
relation and median `delta_S>0`. Persistent confirmation requires every seed to satisfy the
persistent capacity relation and majority literal no-progress, with at least 80% of round epochs
below `T_cc`.

Rank by minimum outcome margin, then minimum capacity-boundary margin, then lower background rate.
Write exactly one recoverable and one persistent configuration for seeds `13..17` atomically.

For formal acceptance, recoverable requires median `delta_S>0` in at least four seeds and a
10,000-sample flow-cluster bootstrap 95% lower bound above zero. Persistent requires majority
literal no-progress in at least four seeds, the capacity relation in every valid round, at least
80% low-floor epochs, no tolerance-direction reversal, and completed rounds distributed across at
least half of traced foreground flows. Emit every failed predicate in `summary.csv`.

- [ ] **Step 6: Implement the two-column M2 figure**

Read aggregate CSV only. For recoverable and persistent columns, render event-aligned raw `F`, `S`,
and `S_ref`, the 14 us threshold, round completion markers, actual cwnd, and actual Prism state with
HOLD shading. Add compact five-seed `delta_S`, completion, and censoring insets. Save:

```text
figs/m2_redistribution_progress.png
figs/m2_redistribution_progress.pdf
```

Labels must say `shadow validation round`; they must not say shadow recycling caused the observed
spread.

- [ ] **Step 7: Run M2 unit and plot tests**

```bash
python3 -m unittest discover \
  -s htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/tests -v
python3 htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/make_figs.py --selftest
```

Expected: all tests pass and project-local self-test figures are generated.

- [ ] **Step 8: Commit Task 11**

```bash
git add htsim/sim/datacenter/add_motivation/expM2_redistribution_progress
git commit -m "analysis: add M2 redistribution progress evidence"
```

---

### Task 12: M2 Runners, Documentation, and End-to-End Verification

**Files:**
- Create: `htsim/sim/datacenter/add_motivation/README.md`
- Create: `htsim/sim/datacenter/add_motivation/.gitignore`
- Create: `htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/calibrate.sh`
- Create: `htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/repro.sh`
- Create: `htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/README.md`
- Create: `htsim/sim/datacenter/add_motivation/expM1_entropy_quality/.gitignore`
- Create: `htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/.gitignore`

- [ ] **Step 1: Add exact M2 run modes**

`calibrate.sh` supports `coarse` and `confirm`. `repro.sh` supports `smoke` and `full`.

Every M2 run invokes:

```text
sender CC             prism
load balancing        reps
paths                  8
T_cc/T_spray           14 us
kappa/n_min            1/3
smooth/hysteresis      1/0
engage thresholds      0/0
background config      generated project-local CSV
trace prefix           project-local run prefix
```

`confirm` refuses to run until coarse summaries exist. `full` refuses to run unless `formal.csv`
contains one recoverable and one persistent row for all five formal seeds.

- [ ] **Step 2: Add ignore rules that preserve final artifacts**

Ignore raw `.dat`, `.stdout`, decoded temporary logs, generated traffic matrices, per-event raw
traces, smoke self-test files, and `add_motivation/.test-bin/`. Do not ignore:

```text
configs/*.csv
data/formal/summary.csv
data/formal/rounds.csv
figs/*.png
figs/*.pdf
README.md
```

- [ ] **Step 3: Document commands, fields, and claim boundaries**

The top README links M1 and M2 and states that Task 1 is excluded. Each experiment README contains
exact build, smoke, calibration, selection, formal, analysis, and plotting commands; project-local
output paths; CSV field definitions; negative-result handling; and the distinction between observed
facts, shadow results, capacity inference, and future mechanism claims.

- [ ] **Step 4: Run syntax, unit, build, and behavior-neutrality gates**

```bash
bash -n htsim/sim/datacenter/add_motivation/expM1_entropy_quality/calibrate.sh
bash -n htsim/sim/datacenter/add_motivation/expM1_entropy_quality/repro.sh
bash -n htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/calibrate.sh
bash -n htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/repro.sh
python3 -m unittest discover -s htsim/sim/datacenter/add_motivation -p 'test_*.py' -v
cmake --build htsim/sim/build --target htsim_uec parse_output -j2
```

Run one no-background seed with tracing disabled and enabled. Hash decoded foreground flow/sink
output, entropy sequence, actual Prism epoch output, and cwnd output. Expected: hashes match exactly.

- [ ] **Step 5: Run project-local smoke experiments**

```bash
cd htsim/sim/datacenter
bash add_motivation/expM1_entropy_quality/repro.sh smoke
bash add_motivation/expM2_redistribution_progress/repro.sh smoke
```

Expected: each produces valid schema-v2 traces, a manifest, aggregate CSV, and PNG/PDF under its
own `data/smoke` and `figs` paths.

- [ ] **Step 6: Run calibration and lock formal configurations**

```bash
cd htsim/sim/datacenter
bash add_motivation/expM1_entropy_quality/calibrate.sh
python3 add_motivation/expM1_entropy_quality/analyze.py --calibration --select-formal
bash add_motivation/expM2_redistribution_progress/calibrate.sh coarse
python3 add_motivation/expM2_redistribution_progress/analyze.py --coarse --select-confirmation
bash add_motivation/expM2_redistribution_progress/calibrate.sh confirm
python3 add_motivation/expM2_redistribution_progress/analyze.py --confirmation --select-formal
```

Expected: M1 has one symmetric/gray pair and M2 one recoverable/persistent pair, or the scripts
write a project-local negative calibration report and refuse formal execution without weakening
criteria.

- [ ] **Step 7: Run all formal seeds and render final artifacts**

If both calibrations lock valid configurations:

```bash
cd htsim/sim/datacenter
bash add_motivation/expM1_entropy_quality/repro.sh full
python3 add_motivation/expM1_entropy_quality/analyze.py --formal
python3 add_motivation/expM1_entropy_quality/make_figs.py --render
bash add_motivation/expM2_redistribution_progress/repro.sh full
python3 add_motivation/expM2_redistribution_progress/analyze.py --formal
python3 add_motivation/expM2_redistribution_progress/make_figs.py --render
```

Verify these exact files exist and are nonempty:

```text
add_motivation/expM1_entropy_quality/data/formal/summary.csv
add_motivation/expM1_entropy_quality/figs/m1_entropy_quality.pdf
add_motivation/expM1_entropy_quality/figs/m1_entropy_quality.png
add_motivation/expM2_redistribution_progress/data/formal/rounds.csv
add_motivation/expM2_redistribution_progress/data/formal/summary.csv
add_motivation/expM2_redistribution_progress/figs/m2_redistribution_progress.pdf
add_motivation/expM2_redistribution_progress/figs/m2_redistribution_progress.png
```

- [ ] **Step 8: Commit Task 12**

```bash
git add htsim/sim/datacenter/add_motivation/README.md \
  htsim/sim/datacenter/add_motivation/.gitignore \
  htsim/sim/datacenter/add_motivation/expM1_entropy_quality \
  htsim/sim/datacenter/add_motivation/expM2_redistribution_progress
git commit -m "experiment: complete Prism motivation task 2"
```

## Completion Report Requirements

The final report is short and artifact-focused. It states:

- build and test commands with pass/fail status;
- selected calibration cells or the exact negative calibration reason;
- formal acceptance status for M1 and both M2 scenarios;
- paths to final CSV, PDF, and PNG files;
- confirmation that no recycling or handoff control behavior was implemented;
- confirmation that no output was written outside the project except self-cleaning test fixtures.
