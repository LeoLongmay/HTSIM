#!/bin/bash
# expD_scale1024 -- 1024-node scale verification of the two PRISM headlines.
# D1: 1:1 delay-driven (scales expA_delaydriven); D2: oversub asym (scales expB_oversub_asym).
# All runs: NODES=1024, -disable_trim, PATHS=8. Sequential only (run_lib writes shared idmap.txt).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expD_scale1024"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"
DD="-disable_trim"
END_D1="${EXP_END:-8}"      # D1 + 4:1 all cr=1.00 at 8 ms (probed)
END_8OS="${EXP_END_8OS:-12}" # 8:1 saturates; give it the 128-protocol 12 ms before declaring saturation
OUT="$REL/data"

echo "== self-tests =="
python3 "$HERE/make_figs.py" --selftest
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_strack_cc.cpp -o /tmp/test_strack_cc && /tmp/test_strack_cc )
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_swift_cc.cpp -o /tmp/test_swift_cc && /tmp/test_swift_cc )
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_mnscc_median.cpp -o /tmp/test_mnscc_median && /tmp/test_mnscc_median )

echo "== generate 100G 4:1 topology (decision A: keep 100G/14us calibration) =="
# Stock fat_tree_1024_4os.topo is 200G -> would change BDP/target. Generate a 100G copy.
SRC=topologies/fat_tree_1024_4os.topo
DST=topologies/fat_tree_1024_4os_100g.topo
if [ ! -f "$DST" ]; then
  sed 's/Downlink_speed_Gbps 200/Downlink_speed_Gbps 100/' "$SRC" > "$DST"
  echo "  wrote $DST"
fi
grep -q "200" "$DST" && { echo "ERROR: $DST still has 200G links"; exit 1; } || echo "  $DST is 100G (verified)"

echo "== generate workloads (many2many 256->64 pod0, 1024 nodes, hpp=64) =="
python3 "$COMMON/gen/many2many.py" "$OUT/m2m256.cm"      256 64 pairs 2000000 1024 64
python3 "$COMMON/gen/many2many.py" "$OUT/m2m256_mech.cm" 256 64 pairs 4000000 1024 64
CM="$OUT/m2m256.cm"; CM_MECH="$OUT/m2m256_mech.cm"

run() { # cc lb failed topo end seed cm logspec tag  [extra env applied by caller]
  PATHS=8 NODES=1024 EXTRA_ARGS="$DD" END_MS="$5" \
    bash "$COMMON/run_lib.sh" "$1" "$2" "$3" "$4" "$6" "$7" "$8" "$9" "$OUT"
}

echo "== D1 sweep: 1:1, -failed {0,8,16,24,32,48} x 7 arms x 5 seeds =="
for f in 0 8 16 24 32 40 48; do for s in $SEEDS; do
  run nscc   oblivious "$f" fat_tree_1024.topo "$END_D1" "$s" "$CM" flow,sink "expD1_ops_f${f}_s${s}"
  run nscc   reps      "$f" fat_tree_1024.topo "$END_D1" "$s" "$CM" flow,sink "expD1_reps_f${f}_s${s}"
  PRISM_EPOCH="$OUT/expD1_prism_f${f}_s${s}.epoch.csv" \
    run prism reps     "$f" fat_tree_1024.topo "$END_D1" "$s" "$CM" flow,sink "expD1_prism_f${f}_s${s}"
  run strack reps      "$f" fat_tree_1024.topo "$END_D1" "$s" "$CM" flow,sink "expD1_strack_f${f}_s${s}"
  run swift  reps      "$f" fat_tree_1024.topo "$END_D1" "$s" "$CM" flow,sink "expD1_swift_f${f}_s${s}"
  run mswift reps      "$f" fat_tree_1024.topo "$END_D1" "$s" "$CM" flow,sink "expD1_mswift_f${f}_s${s}"
  run mnscc  reps      "$f" fat_tree_1024.topo "$END_D1" "$s" "$CM" flow,sink "expD1_mnscc_f${f}_s${s}"
done; done

echo "== D1 mechanism: 1:1 failed=32, seed 13, 4MB, all 4 arms w/ PRISM_PATHRTT =="
PRISM_PATHRTT="$OUT/expD1_ops_mech.pathrtt.csv" \
  run nscc oblivious 32 fat_tree_1024.topo "$END_D1" 13 "$CM_MECH" flow,sink expD1_ops_mech
PRISM_PATHRTT="$OUT/expD1_reps_mech.pathrtt.csv" \
  run nscc reps 32 fat_tree_1024.topo "$END_D1" 13 "$CM_MECH" flow,sink expD1_reps_mech
PRISM_EPOCH="$OUT/expD1_prism_mech.epoch.csv" PRISM_PATHRTT="$OUT/expD1_prism_mech.pathrtt.csv" \
  run prism reps 32 fat_tree_1024.topo "$END_D1" 13 "$CM_MECH" flow,sink expD1_prism_mech
PRISM_PATHRTT="$OUT/expD1_strack_mech.pathrtt.csv" \
  run strack reps 32 fat_tree_1024.topo "$END_D1" 13 "$CM_MECH" flow,sink expD1_strack_mech

echo "== D2 4:1 sweep: fat_tree_1024_4os_100g, -failed {0,1,2,3,4} x 7 arms x 5 seeds =="
for f in 0 1 2 3 4; do for s in $SEEDS; do
  run nscc   oblivious "$f" fat_tree_1024_4os_100g.topo "$END_D1" "$s" "$CM" flow,sink "expD2_4os_ops_f${f}_s${s}"
  run nscc   reps      "$f" fat_tree_1024_4os_100g.topo "$END_D1" "$s" "$CM" flow,sink "expD2_4os_reps_f${f}_s${s}"
  PRISM_EPOCH="$OUT/expD2_4os_prism_f${f}_s${s}.epoch.csv" \
    run prism reps     "$f" fat_tree_1024_4os_100g.topo "$END_D1" "$s" "$CM" flow,sink "expD2_4os_prism_f${f}_s${s}"
  run strack reps      "$f" fat_tree_1024_4os_100g.topo "$END_D1" "$s" "$CM" flow,sink "expD2_4os_strack_f${f}_s${s}"
  run swift  reps      "$f" fat_tree_1024_4os_100g.topo "$END_D1" "$s" "$CM" flow,sink "expD2_4os_swift_f${f}_s${s}"
  run mswift reps      "$f" fat_tree_1024_4os_100g.topo "$END_D1" "$s" "$CM" flow,sink "expD2_4os_mswift_f${f}_s${s}"
  run mnscc  reps      "$f" fat_tree_1024_4os_100g.topo "$END_D1" "$s" "$CM" flow,sink "expD2_4os_mnscc_f${f}_s${s}"
done; done

echo "== D2 8:1 sweep: fat_tree_1024_8os, -failed {0,1,2,4} x 7 arms x 5 seeds (END=$END_8OS) =="
for f in 0 1 2 4; do for s in $SEEDS; do
  run nscc   oblivious "$f" fat_tree_1024_8os.topo "$END_8OS" "$s" "$CM" flow,sink "expD2_8os_ops_f${f}_s${s}"
  run nscc   reps      "$f" fat_tree_1024_8os.topo "$END_8OS" "$s" "$CM" flow,sink "expD2_8os_reps_f${f}_s${s}"
  PRISM_EPOCH="$OUT/expD2_8os_prism_f${f}_s${s}.epoch.csv" \
    run prism reps     "$f" fat_tree_1024_8os.topo "$END_8OS" "$s" "$CM" flow,sink "expD2_8os_prism_f${f}_s${s}"
  run strack reps      "$f" fat_tree_1024_8os.topo "$END_8OS" "$s" "$CM" flow,sink "expD2_8os_strack_f${f}_s${s}"
  run swift  reps      "$f" fat_tree_1024_8os.topo "$END_8OS" "$s" "$CM" flow,sink "expD2_8os_swift_f${f}_s${s}"
  run mswift reps      "$f" fat_tree_1024_8os.topo "$END_8OS" "$s" "$CM" flow,sink "expD2_8os_mswift_f${f}_s${s}"
  run mnscc  reps      "$f" fat_tree_1024_8os.topo "$END_8OS" "$s" "$CM" flow,sink "expD2_8os_mnscc_f${f}_s${s}"
done; done

echo "== D2 mechanism: 4:1 failed=4, seed 13, 2MB, all 4 arms w/ PRISM_PATHRTT =="
PRISM_PATHRTT="$OUT/expD2_4os_ops_mech.pathrtt.csv" \
  run nscc oblivious 4 fat_tree_1024_4os_100g.topo "$END_D1" 13 "$CM" flow,sink expD2_4os_ops_mech
PRISM_PATHRTT="$OUT/expD2_4os_reps_mech.pathrtt.csv" \
  run nscc reps 4 fat_tree_1024_4os_100g.topo "$END_D1" 13 "$CM" flow,sink expD2_4os_reps_mech
PRISM_EPOCH="$OUT/expD2_4os_prism_mech.epoch.csv" PRISM_PATHRTT="$OUT/expD2_4os_prism_mech.pathrtt.csv" \
  run prism reps 4 fat_tree_1024_4os_100g.topo "$END_D1" 13 "$CM" flow,sink expD2_4os_prism_mech
PRISM_PATHRTT="$OUT/expD2_4os_strack_mech.pathrtt.csv" \
  run strack reps 4 fat_tree_1024_4os_100g.topo "$END_D1" 13 "$CM" flow,sink expD2_4os_strack_mech

echo "== render figures =="
python3 "$HERE/make_figs.py"
echo "== done: figs/figD1_*.{png,pdf} figs/figD2_*.{png,pdf} =="
