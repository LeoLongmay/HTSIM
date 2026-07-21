#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../../../../" && pwd)"
DATA_ROOT="$HERE/data/outcome_recycle"

cmake --build "$HERE/../../../build" --target htsim_uec -j2
rm -rf "$DATA_ROOT"
cd "$REPO_ROOT"
python3 -u -m htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.run_outcome_recycle
python3 -u -m htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.analyze_outcome_recycle
python3 -u -m htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.analyze_cache_path_groups
python3 -u -m htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.make_outcome_recycle_fig
