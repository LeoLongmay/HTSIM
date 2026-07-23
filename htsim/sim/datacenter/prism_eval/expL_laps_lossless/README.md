# LAPS lossless/PFC preview

This is an isolated lossless/PFC comparison for OPS, REPS, LAPS-Control, and
Prism.  LAPS-Control shares UEC ACK/reliability/PFC semantics with the other
arms and evaluates LAPS-style latency-aware path/rate control; it is not a
claim of a faithful reproduction of the original LAPS transport.
It does not reuse, overwrite, or reinterpret Experiment A's delay-driven
results; all generated outputs stay in this directory's `data/` and `figs/`
trees.

## Preview matrix

The default command runs 140 cells: four arms (`ops`, `reps`, `laps_control`,
`prism`) × failures `{0,2,4,6,8,10,12}` × seeds `{13,14,15,16,17}`. Prism is
last in both the runner's arm ordering and the figures' green legend entry.

```bash
bash repro.sh
python3 make_figs.py
```

`repro.sh` uses an 80 ms simulation end time by default. It can be overridden
for diagnostics with `END_MS=<milliseconds> bash repro.sh`; 80 ms came from the
pre-scan recovery diagnostic, not from an algorithm-specific tuning parameter.
Before producing any performance figure, `make_figs.py` rejects every missing
or incomplete flow cell (`completion_rate != 1.0`) so partial results cannot be
reported as performance data.

`--all-baselines` is an explicit future expansion to 280 cells. It adds
Swift, MSwift, MNSCC, and STrack, while retaining the same topology, workload,
failure scan, and lossless configuration.

```bash
bash repro.sh --all-baselines
python3 make_figs.py --all-baselines
```

Use `bash repro.sh --dry-run` to inspect the 140 exact commands without
building or running the simulator.

## Fixed setup

Every run uses `fat_tree_128_1os.topo` and the existing many-to-many workload:
64 senders to 16 receivers in pod 0, 2 MB per transfer. Every invocation uses
the byte-exact lossless/PFC flags below and deliberately never uses
`-disable_trim`:

```text
-queue_type lossless_input
-queue_size_bytes 150000
-pfc_high_bytes 122880
-pfc_low_bytes 92160
-shared_buffer_bytes 33554432
```

The values configure a 150,000-byte data egress queue, 120 KiB PFC pause,
90 KiB PFC resume, and a 32 MiB shared buffer for each FatTree switch.

## Repository policy

Do not commit generated `.cm`, simulator logs, data files, or PDF/PNG figures.
They belong only under this experiment's ignored `data/` and `figs/` trees.
