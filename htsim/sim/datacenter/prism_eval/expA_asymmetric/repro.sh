#!/bin/bash
# Experiment A (asymmetric fabric, 128 nodes): PRISM vs OPS+NSCC vs REPS+NSCC.
# many2many (64 senders outside pod0 -> 16 pod0 receivers), sweep -failed {0,2,4,8,12}, 5 seeds.
# Run from anywhere; paths are resolved relative to this script.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"            # .../prism_eval/expA_asymmetric
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"                  # .../sim/datacenter
REL="prism_eval/expA_asymmetric"                 # relative to DC, for run_lib OUTDIR/CM
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"; FAILEDS="0 2 4 8 12"; TOPO=fat_tree_128_1os.topo

echo "== self-test analysis =="
python3 "$HERE/make_figs.py" --selftest
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )

echo "== generate workload (many2many: 64 -> 16 pod0, 2MB) =="
python3 "$COMMON/gen/many2many.py" "$REL/data/m2m.cm" 64 16 pairs 2000000 128 16

# NOTE: env vars (PATHS/END_MS/PRISM_EPOCH/PRISM_PATHRTT) are placed directly as a prefix on the
# `bash run_lib.sh` command (NOT on a wrapper function) so they export into run_lib -> htsim_uec
# (getenv). This mirrors mvp_runs3/run_one.sh. CM/OUTDIR are relative to the datacenter dir.
CM="$REL/data/m2m.cm"; OUT="$REL/data"

echo "== main sweep: 3 baselines x failed{0,2,4,8,12} x 5 seeds =="
for f in $FAILEDS; do for s in $SEEDS; do
  PATHS=8 END_MS=2 bash "$COMMON/run_lib.sh" nscc oblivious "$f" "$TOPO" "$s" "$CM" flow "expA_ops_f${f}_s${s}" "$OUT"
  PATHS=8 END_MS=2 bash "$COMMON/run_lib.sh" nscc reps      "$f" "$TOPO" "$s" "$CM" flow "expA_reps_f${f}_s${s}" "$OUT"
  PATHS=8 END_MS=2 PRISM_EPOCH="$OUT/expA_prism_f${f}_s${s}.epoch.csv" \
    bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow "expA_prism_f${f}_s${s}" "$OUT"
done; done

echo "== mechanism condition: failed=8, seed=13, all 3 with PRISM_PATHRTT =="
PATHS=8 END_MS=2 PRISM_PATHRTT="$OUT/expA_ops_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" nscc oblivious 8 "$TOPO" 13 "$CM" flow expA_ops_mech "$OUT"
PATHS=8 END_MS=2 PRISM_PATHRTT="$OUT/expA_reps_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" nscc reps 8 "$TOPO" 13 "$CM" flow expA_reps_mech "$OUT"
PATHS=8 END_MS=2 PRISM_EPOCH="$OUT/expA_prism_mech.epoch.csv" PRISM_PATHRTT="$OUT/expA_prism_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" prism reps 8 "$TOPO" 13 "$CM" flow expA_prism_mech "$OUT"

echo "== render Fig1 + Fig2 =="
python3 "$HERE/make_figs.py"
echo "== done: figs/figA1_main_perf.{png,pdf} figs/figA2_mechanism.{png,pdf} =="
