#!/bin/bash
# End-to-end smoke: 1-flow run -> FCT in a plausible band, completion_rate==1.0.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"           # common/tests
COMMON="$(cd "$HERE/.." && pwd)"                # common
DC="$(cd "$COMMON/.." && pwd)"                  # prism_eval
DATA="$DC/_smoke"                               # under prism_eval (gitignored)
REL="prism_eval/_smoke"                         # path relative to datacenter for run_lib
mkdir -p "$DATA"
# 1 sender outside pod0 -> host0, 4 MB (incast.py floors start to 1 ns, so START is logged)
python3 "$COMMON/gen/incast.py" "$DATA/smoke.cm" 1 0 4000000 128 16
END_MS=2 PATHS=8 bash "$COMMON/run_lib.sh" nscc reps 0 fat_tree_128_1os.topo 13 \
    "$REL/smoke.cm" flow,sink smoke "$REL"
python3 - "$DATA/smoke.flow.txt" "$COMMON/metrics.py" <<'PY'
import sys, importlib.util as u
flow_path, metrics_path = sys.argv[1], sys.argv[2]
spec = u.spec_from_file_location("metrics", metrics_path)
metrics = u.module_from_spec(spec)
spec.loader.exec_module(metrics)
s = metrics.fct_stats(flow_path)
print("FCT stats:", s)
assert s["completed"] == 1, s
assert abs(s["completion_rate"] - 1.0) < 1e-9, s
assert 0.0002 < s["avg_s"] < 0.002, ("FCT out of sane band", s)
print("ok smoke_fct")
PY
echo "SMOKE PASS"
