#!/usr/bin/env python3
"""Contract checks for the isolated four-arm lossless preview renderer."""
import importlib.util
import os
import tempfile


HERE = os.path.dirname(os.path.abspath(__file__))
MAKE_FIGS = os.path.join(os.path.dirname(HERE), "make_figs.py")


def main():
    spec = importlib.util.spec_from_file_location("expL_laps_lossless_make_figs", MAKE_FIGS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.DATA.endswith("expL_laps_lossless/data")
    assert module.FIGS.endswith("expL_laps_lossless/figs")
    assert [x[0] for x in module.PREVIEW_BASELINES] == ["ops", "reps", "laps_control", "prism"]
    assert module.PREVIEW_BASELINES[-1] == ("prism", "Prism", "prism")
    assert module.perf_figs.plot_style.COLORS["prism"] == "tab:green"

    with tempfile.TemporaryDirectory() as tmpdir:
        for label, _display, _color in module.PREVIEW_BASELINES:
            path = os.path.join(tmpdir, f"expL_{label}_f0_s13.flow.txt")
            with open(path, "w") as fh:
                fh.write("0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 1000\n")
                fh.write("0.001000000 Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 1 Bytes 1000 Pkts 1\n")
        with open(os.path.join(tmpdir, "expL_laps_control_f0_s13.flow.txt"), "w") as fh:
            fh.write("0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 1000\n")
        try:
            module.require_complete_cells(tmpdir, "expL", module.PREVIEW_BASELINES, [0], [13])
        except RuntimeError as exc:
            assert "expL_laps_control_f0_s13" in str(exc)
            assert "completion_rate" in str(exc)
        else:
            raise AssertionError("incomplete ExpL cell was accepted")
    print("ok lossless/PFC preview figure contract")


if __name__ == "__main__":
    main()
