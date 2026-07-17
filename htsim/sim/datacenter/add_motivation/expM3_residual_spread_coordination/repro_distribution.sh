#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../../../../" && pwd)"
DATA_ROOT="$HERE/data/distribution"
AGGREGATE_ROOT="$DATA_ROOT/aggregate"

cmake --build "$HERE/../../../build" --target htsim_uec -j2
rm -rf "$DATA_ROOT"
rm -f "$HERE/figs/distribution.pdf" "$HERE/figs/distribution.png"
cd "$REPO_ROOT"
python3 -u -c '
from htsim.sim.datacenter.add_motivation.common import run_case
from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination import run_distribution

# Task 1 owns this phase label; retain the allowance inside this distribution-only process.
run_case.VALID_PHASES.add("distribution")
raise SystemExit(run_distribution.main())
'
python3 -c '
from pathlib import Path
import sys
from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.analyze_distribution import analyze_distribution

analyze_distribution(Path(sys.argv[1]), Path(sys.argv[2]))
' "$DATA_ROOT" "$AGGREGATE_ROOT"
python3 "$HERE/make_distribution_fig.py"
