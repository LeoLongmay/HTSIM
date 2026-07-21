#!/bin/bash
# Re-run for figC2a/b/c with the adopted "original Prism + A1" (default params + smooth_beta 0.3) and
# an added MSwift line. DISTINCT tags expC2_prisma1_* / expC2_mswift_* / expC2_ts_prisma1_center --
# baselines and the old prism_def/prism_b data are NOT touched (no pollution; data/ is gitignored).
# Then re-renders figC2a/b/c via rerun_figs_v2.py (OVERWRITES those 3; leaves figC2d-g + make_figs.py alone).
# DRYRUN=1 prints the matrix. Reuses existing data/incast_n{8,32,64}_2m.cm + expC2_ts_reps_center.*
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
OUT="prism_eval/expC2_incast_asym/data"
TOPO=fat_tree_128_1os.topo
SEEDS="13 14 15 16 17"; FAILEDS="0 2 4 8 12"; CN=32; CF=8; SIZE=2000000
MAXP="${MAXP:-6}"; DRYRUN="${DRYRUN:-0}"
end_ms_for(){ awk -v n="$1" -v sz="$2" 'BEGIN{ d=(n-1)*sz*8/90e9*1000; v=d*1.6+2; iv=int(v); if(iv<v)iv++; if(iv<2)iv=2; print iv }'; }
rm -f "$OUT/.failures_v2"
gate(){ while [ "$(jobs -rp | wc -l)" -ge "$MAXP" ]; do wait -n 2>/dev/null || true; done; }

run2(){  # $1=arm $2=failed $3=seed $4=cm $5=tag $6=end_ms
  local cc extra
  case "$1" in
    prisma1) cc=prism;  extra=" -prism_smooth_beta 0.3";;   # original Prism (default params) + A1
    mswift)  cc=mswift; extra="";;
    swift)   cc=swift;  extra="";;
    *) echo "bad arm $1" >&2; return 2;;
  esac
  local cmd="PATHS=8 END_MS=$6 EXTRA_ARGS=\"-disable_trim${extra}\" bash \"$COMMON/run_lib.sh\" $cc reps $2 $TOPO $3 \"$4\" flow $5 \"$OUT\""
  if [ "$DRYRUN" = "1" ]; then echo "$cmd"; else { eval "$cmd" >/dev/null 2>&1 || echo "$5" >> "$OUT/.failures_v2"; } & fi
}

echo "== slice 1: failed sweep (fan-in $CN) x {prisma1,mswift} x seeds =="
CMC="$OUT/incast_n${CN}_2m.cm"; EMC=$(end_ms_for "$CN" "$SIZE")
for F in $FAILEDS; do for arm in prisma1 mswift; do for s in $SEEDS; do
  gate; run2 "$arm" "$F" "$s" "$CMC" "expC2_${arm}_f${F}_n${CN}_s${s}" "$EMC"
done; done; done
wait

echo "== slice 2: fan-in sweep (failed $CF; N=8,64) x {prisma1,mswift} x seeds =="
for N in 8 64; do CM="$OUT/incast_n${N}_2m.cm"; EM=$(end_ms_for "$N" "$SIZE")
  for arm in prisma1 mswift; do for s in $SEEDS; do
    gate; run2 "$arm" "$CF" "$s" "$CM" "expC2_${arm}_f${CF}_n${N}_s${s}" "$EM"
done; done; done
wait

echo "== slice 2b: swift fan-in (failed $CF; N=8,32,64) for figC2b (swift not in slice 1) =="
for N in 8 32 64; do CM="$OUT/incast_n${N}_2m.cm"; EM=$(end_ms_for "$N" "$SIZE")
  for s in $SEEDS; do
    gate; run2 swift "$CF" "$s" "$CM" "expC2_swift_f${CF}_n${N}_s${s}" "$EM"
done; done
wait

echo "== time-series: prisma1 center (queue+pathrtt) for figC2c =="
if [ "$DRYRUN" = "1" ]; then
  echo "PATHS=8 END_MS=$EMC EXTRA_ARGS=\"-disable_trim -prism_smooth_beta 0.3\" PRISM_PATHRTT=... run_lib.sh prism reps $CF ... expC2_ts_prisma1_center"
  echo "== DRYRUN done =="; exit 0
fi
PATHS=8 END_MS=$EMC EXTRA_ARGS="-disable_trim -prism_smooth_beta 0.3" PRISM_PATHRTT="$OUT/expC2_ts_prisma1_center.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" prism reps $CF $TOPO 13 "$CMC" flow,sink,queue expC2_ts_prisma1_center "$OUT" >/dev/null 2>&1 \
  || echo "ts_prisma1_center" >> "$OUT/.failures_v2"

[ -s "$OUT/.failures_v2" ] && { echo "ERROR: failed cells:"; cat "$OUT/.failures_v2"; exit 1; }
echo "== cr-guard (new cells only) =="
bad=0
for fp in "$OUT"/expC2_prisma1_f*_n*_s*.flow.txt "$OUT"/expC2_mswift_f*_n*_s*.flow.txt; do
  [ -f "$fp" ] || continue
  cr=$(python3 -c "import sys;sys.path.insert(0,'$COMMON');import metrics;print(metrics.fct_stats('$fp')['completion_rate'])")
  awk -v c="$cr" 'BEGIN{exit !(c>=0.999)}' || { echo "  cr=$cr  $fp"; bad=1; }
done
[ "$bad" = 0 ] && echo "ok: all new cells cr>=0.999" || { echo "ERROR: raise END_MS"; exit 1; }

echo "== re-render figC2a/b/c (OVERWRITE; d-g untouched) =="
python3 "$HERE/rerun_figs_v2.py"
echo "== done =="
