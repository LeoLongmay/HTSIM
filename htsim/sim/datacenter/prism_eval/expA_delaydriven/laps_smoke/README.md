# ExpA strict-LAPS smoke evaluation

This legacy exploratory measurement compares OPS, REPS, DecMT, and strict LAPS in 24
ExpA delay-driven cells: `failed={0,8}` and `seed={13,14,15}`. All runs use
the 128-node 64-to-16 2 MiB workload, 8 paths, an 8 ms horizon, and
`-disable_trim`.

```bash
bash repro.sh --dry-run
bash repro.sh
MPLCONFIGDIR=/tmp/mpl-laps-smoke python3 make_figs.py
```

These `repro.sh`/`make_figs.py` artifacts are not falsification-ladder evidence;
use `README-falsification.md` for the gated runner with observed FCT samples,
explicit censoring, exact delivered bytes, and PIT checks. DecMT is labelled `DecMT` in outputs but uses the binary compatibility flag
`prism`. LAPS is strict `laps + laps`, not `laps_control`. The analyzer refuses
to render any incomplete cell so reported FCTs are never silently conditioned
on a partial workload. If LAPS trails OPS, run the separate recovery diagnostic
before changing the transport implementation.
# Strict-LAPS smoke and diagnostics

`repro.sh` runs the four-arm performance smoke matrix. `repro_diagnostics.sh`
is a separate, opt-in strict-LAPS observation run: it records only the paired
ExpA cells `(failed=0, seed=13)` and `(failed=8, seed=14)` using `LAPS_DIAG`.

Run it with:

```bash
bash repro_diagnostics.sh
```

It writes raw CSV traces and an evidence-only `analysis/summary.csv` plus
`analysis/diagnosis.md` under `data_diagnostics/`. It does not alter LAPS
rates, probes, PID selection, routing, recovery, or experiment parameters.
