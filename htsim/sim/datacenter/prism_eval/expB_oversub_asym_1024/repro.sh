#!/bin/bash
# expB_oversub_asym_1024: 1024-node 4:1-oversub asymmetric -- three split performance figures
# (goodput/avg_fct/p99_fct), contrasting expB_oversub_asym's 128-node figBa_4os_*. This group does
# NOT run a sweep: it REUSES the expD2_4os data produced by ../expD_scale1024/repro.sh and only
# renders. Regenerate the data with: ( cd ../expD_scale1024 && bash repro.sh ).
#   bash repro.sh            # verify reused data + render
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
EXPD_DATA="$(cd "$HERE/../expD_scale1024" && pwd)/data"

echo "== selftest =="
python3 "$HERE/make_figs.py" --selftest
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )

echo "== verify reused expD2_4os data exists (produced by ../expD_scale1024/repro.sh) =="
miss=0
for arm in ops reps swift mswift mnscc strack prism; do
  for f in 0 1 2 3 4; do for s in 13 14 15 16 17; do
    [ -f "$EXPD_DATA/expD2_4os_${arm}_f${f}_s${s}.flow.txt" ] || { echo "  MISSING expD2_4os_${arm}_f${f}_s${s}.flow.txt"; miss=$((miss+1)); }
  done; done
done
[ "$miss" -eq 0 ] || { echo "ERROR: $miss expD2_4os data files missing -- run ( cd ../expD_scale1024 && bash repro.sh ) first"; exit 1; }
echo "  all 175 expD2_4os data files present"

echo "== render figBb_4os_{goodput,avg_fct,p99_fct} =="
python3 "$HERE/make_figs.py"
echo "== done: figs/figBb_4os_{goodput,avg_fct,p99_fct}.{png,pdf} =="
