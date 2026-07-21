#!/bin/bash
# expC2_incast_asym: asymmetric structured incast (-failed) on fat_tree_128_1os, delay-driven.
# Does PRISM (esp. @B = -prism_t_spray 7 -target_q_delay 10 -prism_kappa 2) win when the incast
# has reroutable fabric structure? 6 arms x {failed-slice, fan-in-slice, msg-size, T_spray} + time-series.
# DRYRUN=1 prints the planned commands (matrix check) without running. NO C++/controller change.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
OUT="prism_eval/expC2_incast_asym/data"; mkdir -p "$OUT"
rm -f "$OUT/.failures"
TOPO=fat_tree_128_1os.topo
SEEDS="13 14 15 16 17"; MSG_SEEDS="13 14 15"
FAILEDS="0 2 4 8 12"; FANINS="8 32 64"; CN=32; CF=8
SIZE=2000000
MSG_LABELS="128k 512k 2m 8m"; MSG_BYTES_128k=128000; MSG_BYTES_512k=512000; MSG_BYTES_2m=2000000; MSG_BYTES_8m=8000000
TSPRAY="5 7 10 14 20 28"
MAXP="${MAXP:-6}"; DRYRUN="${DRYRUN:-0}"

end_ms_for() {  # $1=fan-in N  $2=size_bytes -> END_MS (ceil(drain*1.6+2), >=2), 90Gbps conservative
  awk -v n="$1" -v sz="$2" 'BEGIN{ d=(n-1)*sz*8/90e9*1000; v=d*1.6+2; iv=int(v); if(iv<v)iv++; if(iv<2)iv=2; print iv }'
}

run_arm() {  # $1=arm $2=failed $3=seed $4=cm $5=logspec $6=tag $7=end_ms [$8=extra_env_prefix]
  local arm="$1" cc lb extra=""
  case "$arm" in
    ops)       cc=nscc;   lb=oblivious;;
    reps)      cc=nscc;   lb=reps;;
    mnscc)     cc=mnscc;  lb=reps;;
    strack)    cc=strack; lb=reps;;
    prism_def) cc=prism;  lb=reps;;
    prism_b)   cc=prism;  lb=reps; extra=" -prism_t_spray 7 -target_q_delay 10 -prism_kappa 2";;
    *) echo "BAD arm $arm" >&2; return 2;;
  esac
  local cmd="PATHS=8 END_MS=$7 ${8:-} EXTRA_ARGS=\"-disable_trim${extra}\" bash \"$COMMON/run_lib.sh\" $cc $lb $2 $TOPO $3 \"$4\" $5 $6 \"$OUT\""
  if [ "$DRYRUN" = "1" ]; then echo "$cmd"; else eval "$cmd" >/dev/null 2>&1 || echo "$6" >> "$OUT/.failures"; fi
}

gate(){ while [ "$(jobs -rp | wc -l)" -ge "$MAXP" ]; do wait -n 2>/dev/null || true; done; }

if [ "$DRYRUN" != "1" ]; then
  echo "== self-tests =="
  python3 "$HERE/make_figs.py" --selftest
  ( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok metrics selftest" )
fi

echo "== generate incast workloads =="
gen_cm() {  # $1=N $2=size $3=outfile
  if [ "$DRYRUN" = "1" ]; then echo "incast.py $3 $1 0 $2 128 16"; \
  else python3 "$COMMON/gen/incast.py" "$OUT/$3" "$1" 0 "$2" 128 16 >/dev/null; fi
}
for N in $FANINS; do gen_cm "$N" "$SIZE" "incast_n${N}_2m.cm"; done
gen_cm "$CN" "$MSG_BYTES_128k" "incast_n${CN}_128k.cm"
gen_cm "$CN" "$MSG_BYTES_512k" "incast_n${CN}_512k.cm"
gen_cm "$CN" "$MSG_BYTES_8m"   "incast_n${CN}_8m.cm"

echo "== slice 1: failed sweep (fan-in $CN, 2MB) =="
CMC="$OUT/incast_n${CN}_2m.cm"; EMC=$(end_ms_for "$CN" "$SIZE")
for F in $FAILEDS; do for arm in ops reps mnscc strack prism_def prism_b; do for s in $SEEDS; do
  gate; run_arm "$arm" "$F" "$s" "$CMC" flow "expC2_${arm}_f${F}_n${CN}_s${s}" "$EMC" &
done; done; done
wait

echo "== slice 2: fan-in sweep (failed $CF, 2MB; N=$CN already done in slice 1) =="
for N in 8 64; do
  CM="$OUT/incast_n${N}_2m.cm"; EM=$(end_ms_for "$N" "$SIZE")
  for arm in ops reps mnscc strack prism_def prism_b; do for s in $SEEDS; do
    gate; run_arm "$arm" "$CF" "$s" "$CM" flow "expC2_${arm}_f${CF}_n${N}_s${s}" "$EM" &
  done; done
done
wait

echo "== msg-size sweep (fan-in $CN, failed $CF) =="
for L in $MSG_LABELS; do
  eval "B=\$MSG_BYTES_${L}"; CM="$OUT/incast_n${CN}_${L}.cm"; [ "$L" = "2m" ] && CM="$CMC"
  EM=$(end_ms_for "$CN" "$B")
  for arm in ops reps mnscc strack prism_def prism_b; do for s in $MSG_SEEDS; do
    gate; run_arm "$arm" "$CF" "$s" "$CM" flow "expC2_${arm}_msg${L}_s${s}" "$EM" &
  done; done
done
wait

echo "== T_spray micro-sweep (PRISM, fan-in $CN, failed $CF) =="
for TS in $TSPRAY; do for s in $SEEDS; do
  gate
  cmd="PATHS=8 END_MS=$EMC EXTRA_ARGS=\"-disable_trim -prism_t_spray $TS\" bash \"$COMMON/run_lib.sh\" prism reps $CF $TOPO $s \"$CMC\" flow expC2_tspray${TS}_s${s} \"$OUT\""
  if [ "$DRYRUN" = "1" ]; then echo "$cmd"; else { eval "$cmd" >/dev/null 2>&1 || echo "expC2_tspray${TS}_s${s}" >> "$OUT/.failures"; } & fi
done; done
wait

echo "== time-series runs (PRISM@B & REPS center w/ sink+queue+pathrtt; PRISM@B n8/n64) =="
# NOTE: these run SEQUENTIALLY (no &) on purpose. run_lib copies the binary's single shared
# idmap.txt to <tag>.idmap; figC2c's queue-delay parser reads it. Correctness relies on the idmap
# being identical across runs (true here: same topo + -nodes 128 -> deterministic object order).
# If you ever parallelize idmap-consuming runs, give each its own idmap or they may race.
# center: full logging for figC2c (queue+pathrtt) & figC2e (sink)
run_arm prism_b "$CF" 13 "$CMC" flow,sink,queue expC2_ts_prismb_center "$EMC" "PRISM_PATHRTT=\"$OUT/expC2_ts_prismb_center.pathrtt.csv\""
run_arm reps    "$CF" 13 "$CMC" flow,sink,queue expC2_ts_reps_center   "$EMC" "PRISM_PATHRTT=\"$OUT/expC2_ts_reps_center.pathrtt.csv\""
# fan-in n8/n64 for figC2d (pathrtt only)
for N in 8 64; do
  CM="$OUT/incast_n${N}_2m.cm"; EM=$(end_ms_for "$N" "$SIZE")
  run_arm prism_b "$CF" 13 "$CM" flow expC2_ts_prismb_n${N} "$EM" "PRISM_PATHRTT=\"$OUT/expC2_ts_prismb_n${N}.pathrtt.csv\""
done

if [ "$DRYRUN" = "1" ]; then echo "== DRYRUN done =="; exit 0; fi

if [ -s "$OUT/.failures" ]; then echo "ERROR: $(wc -l < "$OUT/.failures") background run(s) failed:"; cat "$OUT/.failures"; exit 1; fi
echo "== completion-rate guard (cr>=0.999 for every main-matrix flow.txt) =="
bad=0
for fp in "$OUT"/expC2_*.flow.txt; do
  cr=$(python3 -c "import sys; sys.path.insert(0,'$COMMON'); import metrics; print(metrics.fct_stats('$fp')['completion_rate'])")
  awk -v c="$cr" 'BEGIN{exit !(c>=0.999)}' || { echo "  cr=$cr  $fp"; bad=1; }
done
[ "$bad" = 0 ] && echo "ok: all cells cr>=0.999" || { echo "ERROR: some cells incomplete -- raise END_MS for those"; exit 1; }

echo "== render figC2a-g =="
python3 "$HERE/make_figs.py"
echo "== done =="
