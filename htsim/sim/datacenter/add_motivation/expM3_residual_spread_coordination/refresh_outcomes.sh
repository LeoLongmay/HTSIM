#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../../../../" && pwd)"
DATA_ROOT="$HERE/data/distribution"
AGGREGATE_ROOT="$DATA_ROOT/aggregate"

cd "$REPO_ROOT"
python3 -c '
from pathlib import Path
import sys
from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.analyze_refresh_outcomes import analyze_refresh_outcomes

analyze_refresh_outcomes(Path(sys.argv[1]), Path(sys.argv[2]))
' "$DATA_ROOT" "$AGGREGATE_ROOT"
python3 -c '
from pathlib import Path
import sys
from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.make_refresh_outcome_fig import render_refresh_outcome_figure

render_refresh_outcome_figure(Path(sys.argv[1]), Path(sys.argv[2]))
' "$AGGREGATE_ROOT" "$HERE/figs"
