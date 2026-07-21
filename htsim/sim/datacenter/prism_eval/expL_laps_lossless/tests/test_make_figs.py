#!/usr/bin/env python3
"""Contract checks for the isolated four-arm lossless preview renderer."""
import importlib.util
import os


HERE = os.path.dirname(os.path.abspath(__file__))
MAKE_FIGS = os.path.join(os.path.dirname(HERE), "make_figs.py")


def main():
    spec = importlib.util.spec_from_file_location("expL_laps_lossless_make_figs", MAKE_FIGS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.DATA.endswith("expL_laps_lossless/data")
    assert module.FIGS.endswith("expL_laps_lossless/figs")
    assert [x[0] for x in module.PREVIEW_BASELINES] == ["ops", "reps", "laps", "prism"]
    assert module.PREVIEW_BASELINES[-1] == ("prism", "Prism", "prism")
    assert module.perf_figs.plot_style.COLORS["prism"] == "tab:green"
    print("ok lossless/PFC preview figure contract")


if __name__ == "__main__":
    main()
