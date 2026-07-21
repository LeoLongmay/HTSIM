#!/bin/bash
# Re-run ONLY the Prism line with PRISM v2 (relative gate, recommended m=2) on expA_delaydriven's
# many2many failed-sweep. Writes DISTINCT tags expA_prismv2_f{F}_s{S} -- baselines and the original
# default-Prism (expA_prism_*) data are NOT touched (no pollution). Then renders figA1dd_v2_* via
# make_figs_v2.py (does NOT overwrite the original figA1dd_* figures).
# DRYRUN=1 prints the matrix. Reuses the existing data/m2m.cm workload.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
OUT="prism_eval/expA_delaydriven/data"
TOPO=fat_tree_128_1os.topo
CM="$OUT/m2m.cm"
[ -f "$CM" ] || { echo "ERROR: $CM missing -- run expA_delaydriven/repro.sh first"; exit 1; }
SEEDS="13 14 15 16 17"; FAILEDS="0 2 4 6 8 10 12"; ENDV="${EXP_END:-8}"
DD="-disable_trim"
# PRISM v2 recommended config: A1 smooth + A2 hysteresis + C relative gate (engage = 2*T_cc).
V2="$DD -prism_smooth_beta 0.3 -prism_hysteresis 0.25 -prism_engage_mult 2 -prism_disengage_ratio 0.7"
MAXP="${MAXP:-6}"; DRYRUN="${DRYRUN:-0}"
rm -f "$OUT/.failures_v2"
gate(){ while [ "$(jobs -rp | wc -l)" -ge "$MAXP" ]; do wait -n 2>/dev/null || true; done; }

echo "== re-run Prism v2 (7 failed x 5 seeds = 35 cells; tag expA_prismv2_*) =="
for f in $FAILEDS; do for s in $SEEDS; do gate
  cmd="PATHS=8 END_MS=$ENDV EXTRA_ARGS=\"$V2\" bash \"$COMMON/run_lib.sh\" prism reps $f $TOPO $s \"$CM\" flow expA_prismv2_f${f}_s${s} \"$OUT\""
  if [ "$DRYRUN" = "1" ]; then echo "$cmd"; else { eval "$cmd" >/dev/null 2>&1 || echo "prismv2_f${f}_s${s}" >> "$OUT/.failures_v2"; } & fi
done; done
wait
[ "$DRYRUN" = "1" ] && { echo "== DRYRUN done =="; exit 0; }

[ -s "$OUT/.failures_v2" ] && { echo "ERROR: failed cells:"; cat "$OUT/.failures_v2"; exit 1; }
echo "== cr-guard (prismv2 cells only) =="
bad=0
for fp in "$OUT"/expA_prismv2_f*_s*.flow.txt; do
  cr=$(python3 -c "import sys;sys.path.insert(0,'$COMMON');import metrics;print(metrics.fct_stats('$fp')['completion_rate'])")
  awk -v c="$cr" 'BEGIN{exit !(c>=0.999)}' || { echo "  cr=$cr  $fp"; bad=1; }
done
[ "$bad" = 0 ] && echo "ok: all prismv2 cells cr>=0.999" || { echo "ERROR: raise END_MS"; exit 1; }

echo "== render figA1dd_v2_{goodput,avg_fct,p99_fct} (originals untouched) =="
python3 "$HERE/make_figs_v2.py"
echo "== done =="
