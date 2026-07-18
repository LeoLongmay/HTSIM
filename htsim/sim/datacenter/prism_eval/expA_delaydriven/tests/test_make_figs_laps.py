#!/usr/bin/env python3
"""Focused contract checks for the opt-in ExpA LAPS overlay figures."""
import importlib.util
import os


HERE = os.path.dirname(os.path.abspath(__file__))
EXP_A_DIR = os.path.dirname(HERE)
MAKE_FIGS = os.path.join(EXP_A_DIR, "make_figs.py")


def _load_make_figs():
    spec = importlib.util.spec_from_file_location("expA_delaydriven_make_figs", MAKE_FIGS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_baseline_contract(module):
    assert [item[0] for item in module.BASELINES] == [
        "ops", "reps", "swift", "mswift", "mnscc", "strack", "prism",
    ]
    assert [item[0] for item in module.LAPS_BASELINES] == [
        "ops", "reps", "swift", "mswift", "mnscc", "strack", "laps", "prism",
    ]
    assert module.perf_figs.plot_style.COLORS["laps"] == "tab:purple"
    assert module.perf_figs.plot_style.COLORS["prism"] == "tab:green"


def test_performance_suffix_contract(module):
    perf_figs = module.perf_figs
    original_aggregate = perf_figs.aggregate
    original_save = perf_figs.plot_style.save
    saved = []
    try:
        perf_figs.aggregate = lambda *_args, **_kwargs: {
            0: {"goodput": (1.0, 0.0), "avg_fct": (1000.0, 0.0),
                "p99_fct": (2000.0, 0.0), "cr": (1.0, 0.0)}
        }
        perf_figs.plot_style.save = lambda _fig, stem, _outdir: saved.append(stem)
        args = ("unused", "unused", "expA", [("ops", "OPS+NSCC", "ops")],
                [0], [13], "figA1dd", "Number of failed links")
        perf_figs.render_main_perf_split(*args)
        assert saved == ["figA1dd_goodput", "figA1dd_avg_fct", "figA1dd_p99_fct"]

        saved.clear()
        perf_figs.render_main_perf_split(*args, output_suffix="_laps")
        assert saved == ["figA1dd_goodput_laps", "figA1dd_avg_fct_laps", "figA1dd_p99_fct_laps"]
    finally:
        perf_figs.aggregate = original_aggregate
        perf_figs.plot_style.save = original_save


def test_laps_overlay_requests_only_performance_and_legend(module):
    calls = []
    original = {}
    for name in ("render_main_perf_split", "render_legend", "render_fairness",
                 "render_mechanism_split", "render_decomposition"):
        original[name] = getattr(module.perf_figs, name)
        setattr(module.perf_figs, name,
                lambda *args, _name=name, **kwargs: calls.append((_name, args, kwargs)))
    try:
        module.render_laps_overlay()
    finally:
        for name, value in original.items():
            setattr(module.perf_figs, name, value)

    assert [name for name, _args, _kwargs in calls] == [
        "render_main_perf_split", "render_legend",
    ]
    perf_name, perf_args, perf_kwargs = calls[0]
    assert perf_name == "render_main_perf_split"
    assert perf_args[3] == module.LAPS_BASELINES
    assert perf_args[6] == "figA1dd"
    assert perf_kwargs == {"goodput_tbps": True, "output_suffix": "_laps"}
    legend_name, legend_args, legend_kwargs = calls[1]
    assert legend_name == "render_legend"
    assert legend_args == (module.FIGS, module.LAPS_BASELINES, "figA1dd_legend_laps")
    assert legend_kwargs == {"row_counts": [4, 4]}


def main():
    module = _load_make_figs()
    test_baseline_contract(module)
    test_performance_suffix_contract(module)
    test_laps_overlay_requests_only_performance_and_legend(module)
    print("ok ExpA LAPS overlay plotting contract")


if __name__ == "__main__":
    main()
