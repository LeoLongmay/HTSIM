#!/usr/bin/env bash
# Reproduce the supported controlled M2 figures from an empty data directory.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

case "${1:-all}" in
    smoke)
        bash "$HERE/repro.sh" smoke
        ;;
    all)
        bash "$HERE/repro.sh" smoke
        bash "$HERE/calibrate.sh" coarse
        python3 "$HERE/analyze.py" --coarse --select-confirmation
        python3 "$HERE/make_figs.py" --render-calibration
        bash "$HERE/calibrate.sh" confirm
        python3 "$HERE/analyze.py" --confirmation
        python3 "$HERE/make_figs.py" --render-confirmation
        python3 "$HERE/threshold_diagnostic.py"
        python3 "$HERE/run_trajectory.py"
        python3 "$HERE/plot_trajectory.py"
        python3 "$HERE/run_reps_motivation.py"
        python3 "$HERE/plot_reps_motivation.py"
        python3 "$HERE/run_intervention.py"
        python3 "$HERE/analyze_intervention.py"
        ;;
    *)
        echo "usage: $0 [smoke|all]" >&2
        exit 2
        ;;
esac
