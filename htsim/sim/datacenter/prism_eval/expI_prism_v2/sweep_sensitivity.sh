#!/bin/bash
# expI_prism_v2/sweep_sensitivity.sh -- OAT sensitivity sweep for PRISM v2 relative-form gate.
# Sweeps β, h, ρ, m one-at-a-time around the recommended center (β=0.3, h=0.25, m=2, ρ=0.7).
# DRYRUN=1 prints the run matrix without executing.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
OUT="prism_eval/expI_prism_v2/data"; mkdir -p "$OUT"; rm -f "$OUT/.failures"
TOPO=fat_tree_128_1os.topo
SEEDS="13 14 15"
# OAT center config (each sweep below overrides exactly one of these): smooth_beta 0.3,
# hysteresis 0.25, engage_mult 2, disengage_ratio 0.7. (Built inline per-run, not via a shared var.)
MAXP="${MAXP:-6}"; DRYRUN="${DRYRUN:-0}"

end_ms_for() { awk -v n="$1" -v sz="$2" 'BEGIN{d=(n-1)*sz*8/90e9*1000;v=d*1.6+2;iv=int(v);if(iv<v)iv++;if(iv<2)iv=2;print iv}'; }
gate(){ while [ "$(jobs -rp | wc -l)" -ge "$MAXP" ]; do wait -n 2>/dev/null || true; done; }

echo "== workloads =="
gen(){ if [ "$DRYRUN" = "1" ]; then echo "gen $*"; else python3 "$COMMON/gen/$1" "$OUT/$2" ${@:3} >/dev/null; fi; }
[ -f "$OUT/m2m.cm" ]        || gen many2many.py m2m.cm        64 16 pairs 2000000 128 16
[ -f "$OUT/inc_n32_2m.cm" ] || gen incast.py    inc_n32_2m.cm 32 0 2000000 128 16

CMM="$OUT/m2m.cm"; EMM=$(end_ms_for 16 2000000)
CMI="$OUT/inc_n32_2m.cm"; EMI=$(end_ms_for 32 2000000)

# run_sens: run one OAT cell.
# $1=param  $2=val  $3=extra_args  $4=scen(f0|f8|inc)  $5=seed
# scen->cm/end_ms/failed mapping: f0=CMM/EMM/0, f8=CMM/EMM/8, inc=CMI/EMI/8
run_sens() {
  local param="$1" pval="$2" extra="$3" scen="$4" seed="$5"
  local cm end_ms failed
  case "$scen" in
    f0)  cm="$CMM"; end_ms="$EMM"; failed=0 ;;
    f8)  cm="$CMM"; end_ms="$EMM"; failed=8 ;;
    inc) cm="$CMI"; end_ms="$EMI"; failed=8 ;;
    *)   echo "BAD scen $scen" >&2; return 2 ;;
  esac
  local tag="expI_sens_${param}_${pval}_${scen}_s${seed}"
  local cmd="PATHS=8 END_MS=${end_ms} EXTRA_ARGS=\"${extra}\" bash \"$COMMON/run_lib.sh\" prism reps $failed $TOPO $seed \"$cm\" flow $tag \"$OUT\""
  if [ "$DRYRUN" = "1" ]; then echo "$cmd"; else eval "$cmd" >/dev/null 2>&1 || echo "$tag" >> "$OUT/.failures"; fi
}

echo "== OAT sensitivity sweep =="

# ---- β (smooth_beta) ∈ {0.15, 0.3, 0.5} ----
for BVAL in 0.15 0.3 0.5; do
  EXTRA="-disable_trim -prism_smooth_beta $BVAL -prism_hysteresis 0.25 -prism_engage_mult 2 -prism_disengage_ratio 0.7"
  for s in $SEEDS; do
    gate; run_sens beta "$BVAL" "$EXTRA" f0  "$s" &
    gate; run_sens beta "$BVAL" "$EXTRA" f8  "$s" &
    gate; run_sens beta "$BVAL" "$EXTRA" inc "$s" &
  done
done
wait

# ---- h (hysteresis) ∈ {0.15, 0.25, 0.4} ----
for HVAL in 0.15 0.25 0.4; do
  EXTRA="-disable_trim -prism_smooth_beta 0.3 -prism_hysteresis $HVAL -prism_engage_mult 2 -prism_disengage_ratio 0.7"
  for s in $SEEDS; do
    gate; run_sens h "$HVAL" "$EXTRA" f0  "$s" &
    gate; run_sens h "$HVAL" "$EXTRA" f8  "$s" &
    gate; run_sens h "$HVAL" "$EXTRA" inc "$s" &
  done
done
wait

# ---- ρ (disengage_ratio) ∈ {0.6, 0.7, 0.8} ----
for RVAL in 0.6 0.7 0.8; do
  EXTRA="-disable_trim -prism_smooth_beta 0.3 -prism_hysteresis 0.25 -prism_engage_mult 2 -prism_disengage_ratio $RVAL"
  for s in $SEEDS; do
    gate; run_sens rho "$RVAL" "$EXTRA" f0  "$s" &
    gate; run_sens rho "$RVAL" "$EXTRA" f8  "$s" &
    gate; run_sens rho "$RVAL" "$EXTRA" inc "$s" &
  done
done
wait

# ---- m (engage_mult) ∈ {1.7, 2.0, 2.4} ----
for MVAL in 1.7 2.0 2.4; do
  EXTRA="-disable_trim -prism_smooth_beta 0.3 -prism_hysteresis 0.25 -prism_engage_mult $MVAL -prism_disengage_ratio 0.7"
  for s in $SEEDS; do
    gate; run_sens m "$MVAL" "$EXTRA" f0  "$s" &
    gate; run_sens m "$MVAL" "$EXTRA" f8  "$s" &
    gate; run_sens m "$MVAL" "$EXTRA" inc "$s" &
  done
done
wait

if [ "$DRYRUN" = "1" ]; then echo "== DRYRUN done =="; exit 0; fi

if [ -s "$OUT/.failures" ]; then echo "ERROR: $(wc -l < "$OUT/.failures") run(s) failed:"; cat "$OUT/.failures"; exit 1; fi
echo "== completion-rate guard (cr>=0.999) =="
bad=0
for fp in "$OUT"/expI_sens_*.flow.txt; do
  cr=$(python3 -c "import sys;sys.path.insert(0,'$COMMON');import metrics;print(metrics.fct_stats('$fp')['completion_rate'])")
  awk -v c="$cr" 'BEGIN{exit !(c>=0.999)}' || { echo "  cr=$cr  $fp"; bad=1; }
done
[ "$bad" = 0 ] && echo "ok: all cells cr>=0.999" || { echo "ERROR: raise END_MS for the above"; exit 1; }
echo "== render =="; python3 "$HERE/make_figs.py"
echo "== done =="
