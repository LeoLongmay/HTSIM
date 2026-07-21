#!/bin/bash
# expI_prism_v2: validate PRISM v2 (A1 smooth + A2 hysteresis + C engage-gate) recovers the f0/incast
# cost and stabilizes the queue while keeping the asymmetric-f8 win. DRYRUN=1 prints the matrix.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
OUT="prism_eval/expI_prism_v2/data"; mkdir -p "$OUT"; rm -f "$OUT/.failures"
TOPO=fat_tree_128_1os.topo
SEEDS="13 14 15 16 17"
DD="-disable_trim"
V2="$DD -prism_smooth_beta 0.3 -prism_hysteresis 0.25 -prism_engage_spread 28 -prism_disengage_spread 20"
A1="$DD -prism_smooth_beta 0.3"
A1A2="$DD -prism_smooth_beta 0.3 -prism_hysteresis 0.25"
BOLD="$DD -prism_t_spray 7 -target_q_delay 10 -prism_kappa 2"   # old always-on PRISM@B
MAXP="${MAXP:-6}"; DRYRUN="${DRYRUN:-0}"

end_ms_for() { awk -v n="$1" -v sz="$2" 'BEGIN{d=(n-1)*sz*8/90e9*1000;v=d*1.6+2;iv=int(v);if(iv<v)iv++;if(iv<2)iv=2;print iv}'; }
gate(){ while [ "$(jobs -rp | wc -l)" -ge "$MAXP" ]; do wait -n 2>/dev/null || true; done; }

# arm -> (cc lb extra_args).  ref=REPS+NSCC; bold=old PRISM@B; v2/a1/a1a2 = PRISM ablations.
run() {  # $1=arm $2=failed $3=seed $4=cm $5=logspec $6=tag $7=end_ms [$8=env_prefix]
  local arm="$1" cc lb extra
  case "$arm" in
    ref)   cc=nscc;  lb=reps; extra="$DD";;
    bold)  cc=prism; lb=reps; extra="$BOLD";;
    a1)    cc=prism; lb=reps; extra="$A1";;
    a1a2)  cc=prism; lb=reps; extra="$A1A2";;
    v2)    cc=prism; lb=reps; extra="$V2";;
    *) echo "BAD arm $arm" >&2; return 2;;
  esac
  local cmd="PATHS=8 END_MS=$7 ${8:-} EXTRA_ARGS=\"$extra\" bash \"$COMMON/run_lib.sh\" $cc $lb $2 $TOPO $3 \"$4\" $5 $6 \"$OUT\""
  if [ "$DRYRUN" = "1" ]; then echo "$cmd"; else eval "$cmd" >/dev/null 2>&1 || echo "$6" >> "$OUT/.failures"; fi
}

if [ "$DRYRUN" != "1" ]; then
  echo "== self-tests =="; python3 "$HERE/make_figs.py" --selftest
  ( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok metrics selftest" )
fi

echo "== workloads =="
gen(){ if [ "$DRYRUN" = "1" ]; then echo "gen $*"; else python3 "$COMMON/gen/$1" "$OUT/$2" ${@:3} >/dev/null; fi; }
gen incast.py     inc_n8_2m.cm   8  0 2000000 128 16
gen incast.py     inc_n32_2m.cm  32 0 2000000 128 16
gen incast.py     inc_n64_2m.cm  64 0 2000000 128 16
gen many2many.py  m2m.cm         64 16 pairs 2000000 128 16

ARMS="ref bold a1 a1a2 v2"

echo "== A) incast (n=32, failed sweep 0/8) x arms x seeds =="
CMI="$OUT/inc_n32_2m.cm"; EMI=$(end_ms_for 32 2000000)
for f in 0 8; do for arm in $ARMS; do for s in $SEEDS; do
  gate; run "$arm" "$f" "$s" "$CMI" flow "expI_incN32_f${f}_${arm}_s${s}" "$EMI" & done; done; done
wait

echo "== B) incast fan-in {8,64} @ failed 8 x arms x seeds =="
for N in 8 64; do CM="$OUT/inc_n${N}_2m.cm"; EM=$(end_ms_for "$N" 2000000)
  for arm in $ARMS; do for s in $SEEDS; do
    gate; run "$arm" 8 "$s" "$CM" flow "expI_incN${N}_f8_${arm}_s${s}" "$EM" & done; done
done
wait

echo "== C) many2many f0 and f8 (the headline do-no-harm + keep-win) x arms x seeds =="
CMM="$OUT/m2m.cm"; EMM=$(end_ms_for 16 2000000)   # 64->16, conservative drain by receiver fan-in 4? use n=16
for f in 0 8; do for arm in $ARMS; do for s in $SEEDS; do
  gate; run "$arm" "$f" "$s" "$CMM" flow "expI_m2m_f${f}_${arm}_s${s}" "$EMM" & done; done; done
wait

echo "== D) threshold/beta/hysteresis mini-sweeps (PRISM v2 base, incast n32 f8 + m2m f8) =="
for E in 24 28 34; do for s in $SEEDS; do gate
  cmd1="PATHS=8 END_MS=$EMI EXTRA_ARGS=\"$DD -prism_smooth_beta 0.3 -prism_hysteresis 0.25 -prism_engage_spread $E -prism_disengage_spread 20\" bash \"$COMMON/run_lib.sh\" prism reps 8 $TOPO $s \"$CMI\" flow expI_sw_eng${E}_inc_s${s} \"$OUT\""
  cmd2="PATHS=8 END_MS=$EMM EXTRA_ARGS=\"$DD -prism_smooth_beta 0.3 -prism_hysteresis 0.25 -prism_engage_spread $E -prism_disengage_spread 20\" bash \"$COMMON/run_lib.sh\" prism reps 8 $TOPO $s \"$CMM\" flow expI_sw_eng${E}_m2m_s${s} \"$OUT\""
  if [ "$DRYRUN" = "1" ]; then echo "$cmd1"; echo "$cmd2"; else { eval "$cmd1" >/dev/null 2>&1 || echo eng${E}_inc_s${s} >> "$OUT/.failures"; eval "$cmd2" >/dev/null 2>&1 || echo eng${E}_m2m_s${s} >> "$OUT/.failures"; } & fi
done; done
for B in 0.15 0.3 0.5; do for s in $SEEDS; do gate
  cmd="PATHS=8 END_MS=$EMI EXTRA_ARGS=\"$DD -prism_smooth_beta $B -prism_hysteresis 0.25 -prism_engage_spread 28 -prism_disengage_spread 20\" bash \"$COMMON/run_lib.sh\" prism reps 8 $TOPO $s \"$CMI\" flow expI_sw_beta${B}_inc_s${s} \"$OUT\""
  if [ "$DRYRUN" = "1" ]; then echo "$cmd"; else { eval "$cmd" >/dev/null 2>&1 || echo beta${B}_inc_s${s} >> "$OUT/.failures"; } & fi
done; done
for EB in 0.1 0.2 0.3; do for s in $SEEDS; do gate
  cmd1="PATHS=8 END_MS=$EMI EXTRA_ARGS=\"$DD -prism_smooth_beta 0.3 -prism_hysteresis 0.25 -prism_engage_spread 28 -prism_disengage_spread 20 -prism_engage_beta $EB\" bash \"$COMMON/run_lib.sh\" prism reps 8 $TOPO $s \"$CMI\" flow expI_sw_ebeta${EB}_inc_s${s} \"$OUT\""
  cmd2="PATHS=8 END_MS=$EMM EXTRA_ARGS=\"$DD -prism_smooth_beta 0.3 -prism_hysteresis 0.25 -prism_engage_spread 28 -prism_disengage_spread 20 -prism_engage_beta $EB\" bash \"$COMMON/run_lib.sh\" prism reps 8 $TOPO $s \"$CMM\" flow expI_sw_ebeta${EB}_m2m_s${s} \"$OUT\""
  if [ "$DRYRUN" = "1" ]; then echo "$cmd1"; echo "$cmd2"; else { eval "$cmd1" >/dev/null 2>&1 || echo ebeta${EB}_inc_s${s} >> "$OUT/.failures"; eval "$cmd2" >/dev/null 2>&1 || echo ebeta${EB}_m2m_s${s} >> "$OUT/.failures"; } & fi
done; done
# Do-no-harm FRONTIER check on f0: the incast/m2m-f8 sweeps above suggest more-aggressive engage
# points (engage_spread 24, or engage_beta 0.2) capture more of the f8 win. Re-run those two points
# on many2many failed=0 to see whether they still hold f0 do-no-harm (the headline default is the
# conservative 28/0.1; this characterizes the cost of leaning aggressive).
for s in $SEEDS; do gate
  c1="PATHS=8 END_MS=$EMM EXTRA_ARGS=\"$DD -prism_smooth_beta 0.3 -prism_hysteresis 0.25 -prism_engage_spread 24 -prism_disengage_spread 20\" bash \"$COMMON/run_lib.sh\" prism reps 0 $TOPO $s \"$CMM\" flow expI_chk_eng24_m2mf0_s${s} \"$OUT\""
  c2="PATHS=8 END_MS=$EMM EXTRA_ARGS=\"$DD -prism_smooth_beta 0.3 -prism_hysteresis 0.25 -prism_engage_spread 28 -prism_disengage_spread 20 -prism_engage_beta 0.2\" bash \"$COMMON/run_lib.sh\" prism reps 0 $TOPO $s \"$CMM\" flow expI_chk_ebeta02_m2mf0_s${s} \"$OUT\""
  if [ "$DRYRUN" = "1" ]; then echo "$c1"; echo "$c2"; else { eval "$c1" >/dev/null 2>&1 || echo chk_eng24_s${s} >> "$OUT/.failures"; eval "$c2" >/dev/null 2>&1 || echo chk_ebeta02_s${s} >> "$OUT/.failures"; } & fi
done
wait

echo "== E) time-series (incast f8 + m2m f8): ref vs bold vs v2, with epoch+queue+pathrtt =="
# SEQUENTIAL on purpose: run_lib copies the shared idmap.txt to <tag>.idmap; identical across runs
# (same topo + -nodes 128 -> deterministic object order). Do NOT parallelize idmap-consuming runs.
for cond in inc m2m; do
  if [ "$cond" = inc ]; then CM="$CMI"; EM="$EMI"; else CM="$CMM"; EM="$EMM"; fi
  run ref  8 13 "$CM" flow,queue        "expI_ts_ref_${cond}"  "$EM" "PRISM_PATHRTT=\"$OUT/expI_ts_ref_${cond}.pathrtt.csv\""
  run bold 8 13 "$CM" flow,queue        "expI_ts_bold_${cond}" "$EM" "PRISM_EPOCH=\"$OUT/expI_ts_bold_${cond}.epoch.csv\" PRISM_PATHRTT=\"$OUT/expI_ts_bold_${cond}.pathrtt.csv\""
  run v2   8 13 "$CM" flow,queue        "expI_ts_v2_${cond}"   "$EM" "PRISM_EPOCH=\"$OUT/expI_ts_v2_${cond}.epoch.csv\" PRISM_PATHRTT=\"$OUT/expI_ts_v2_${cond}.pathrtt.csv\""
done

if [ "$DRYRUN" = "1" ]; then echo "== DRYRUN done =="; exit 0; fi

if [ -s "$OUT/.failures" ]; then echo "ERROR: $(wc -l < "$OUT/.failures") run(s) failed:"; cat "$OUT/.failures"; exit 1; fi
echo "== completion-rate guard (cr>=0.999) =="
bad=0
for fp in "$OUT"/expI_*.flow.txt; do
  cr=$(python3 -c "import sys;sys.path.insert(0,'$COMMON');import metrics;print(metrics.fct_stats('$fp')['completion_rate'])")
  awk -v c="$cr" 'BEGIN{exit !(c>=0.999)}' || { echo "  cr=$cr  $fp"; bad=1; }
done
[ "$bad" = 0 ] && echo "ok: all cells cr>=0.999" || { echo "ERROR: raise END_MS for the above"; exit 1; }
echo "== render =="; python3 "$HERE/make_figs.py"
echo "== done =="
