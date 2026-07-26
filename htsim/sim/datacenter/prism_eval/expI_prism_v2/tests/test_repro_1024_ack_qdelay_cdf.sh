#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=$(DRYRUN=1 bash "$ROOT/repro_1024_ack_qdelay_cdf.sh")

grep -F -- 'run_lib.sh nscc oblivious 16 fat_tree_1024.topo' <<<"$OUT"
grep -F -- 'run_lib.sh nscc reps 16 fat_tree_1024.topo' <<<"$OUT"
grep -F -- 'run_lib.sh swift reps 16 fat_tree_1024.topo' <<<"$OUT"
grep -F -- 'run_lib.sh mswift reps 16 fat_tree_1024.topo' <<<"$OUT"
grep -F -- 'run_lib.sh mnscc reps 16 fat_tree_1024.topo' <<<"$OUT"
grep -F -- 'run_lib.sh strack reps 16 fat_tree_1024.topo' <<<"$OUT"
grep -F -- 'run_lib.sh prism reps 16 fat_tree_1024.topo' <<<"$OUT"
grep -F -- '-prism_smooth_beta 0.3 -prism_hysteresis 0.25 -prism_engage_spread 28 -prism_disengage_spread 20' <<<"$OUT"
test "$(grep -c 'ACK_QDELAY=' <<<"$OUT")" -eq 35
