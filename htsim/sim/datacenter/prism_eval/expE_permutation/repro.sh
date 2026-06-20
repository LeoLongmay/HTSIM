#!/bin/bash
# expE_permutation: permutation traffic x failed-links. Tests whether PRISM's delay-driven
# asymmetric-fabric advantage (shown on incast-style many2many in expA/expD) generalizes to a
# uniform random permutation (the STrack/MSwift LB benchmark; no incast, no receiver oversub).
# Two scales: P1=128 (fat_tree_128_1os), P2=1024 (fat_tree_1024). delay-driven, flow-only logging.
#   bash repro.sh            # full sweep + render
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expE_permutation"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"
DD="-disable_trim"
ENDV="${EXP_END:-8}"
OUT="$REL/data"
FAILED_128="0 2 4 6 8 10 12"
FAILED_1024="0 8 16 24 32 40 48"
ARMS_CC=(nscc nscc prism strack mnscc swift mswift)
ARMS_LB=(oblivious reps reps reps reps reps reps)
ARMS_TAG=(ops reps prism strack mnscc swift mswift)

echo "== self-test analysis =="
python3 "$HERE/make_figs.py" --selftest
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_strack_cc.cpp -o /tmp/test_strack_cc && /tmp/test_strack_cc )
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_mnscc_median.cpp -o /tmp/test_mnscc_median && /tmp/test_mnscc_median )
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_swift_cc.cpp -o /tmp/test_swift_cc && /tmp/test_swift_cc )

run_arm() { # scale_tag nodes topo failed seed cm
  local pfx="$1" nodes="$2" topo="$3" f="$4" s="$5" cm="$6" i tag epoch
  for i in "${!ARMS_TAG[@]}"; do
    tag="${pfx}_${ARMS_TAG[$i]}_f${f}_s${s}"
    epoch=""
    [ "${ARMS_TAG[$i]}" = prism ] && epoch="PRISM_EPOCH=$OUT/${tag}.epoch.csv"
    env $epoch PATHS=8 NODES="$nodes" END_MS="$ENDV" EXTRA_ARGS="$DD" \
      bash "$COMMON/run_lib.sh" "${ARMS_CC[$i]}" "${ARMS_LB[$i]}" "$f" "$topo" "$s" "$cm" flow "$tag" "$OUT"
  done
}

echo "== P1: 128-node permutation x failed{$FAILED_128} x 7 arms x 5 seeds =="
for s in $SEEDS; do python3 "$COMMON/gen/permutation.py" "$OUT/perm128_s${s}.cm" 1.0 2000000 128 "$s"; done
for f in $FAILED_128; do for s in $SEEDS; do
  run_arm expEp128 128 fat_tree_128_1os.topo "$f" "$s" "$OUT/perm128_s${s}.cm"
done; done

echo "== P2: 1024-node permutation x failed{$FAILED_1024} x 7 arms x 5 seeds (sequential; shared idmap) =="
for s in $SEEDS; do python3 "$COMMON/gen/permutation.py" "$OUT/perm1024_s${s}.cm" 1.0 2000000 1024 "$s"; done
for f in $FAILED_1024; do for s in $SEEDS; do
  run_arm expEp1024 1024 fat_tree_1024.topo "$f" "$s" "$OUT/perm1024_s${s}.cm"
done; done

echo "== render figE_p128_* + figE_p1024_* =="
python3 "$HERE/make_figs.py"
echo "== done: figs/figE_p128_*.{png,pdf} figs/figE_p1024_*.{png,pdf} =="
