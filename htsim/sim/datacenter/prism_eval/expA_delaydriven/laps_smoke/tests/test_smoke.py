#!/usr/bin/env python3
"""Contract tests for the isolated ExpA strict-LAPS smoke evaluation."""
import importlib.util
import os
import pathlib
import subprocess
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "repro.sh"
PLOTTER = ROOT / "make_figs.py"


def load_plotter():
    spec = importlib.util.spec_from_file_location("laps_smoke_figs", PLOTTER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def flow_text(finish_seconds: float = 0.001) -> str:
    return (
        "0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 1000\n"
        f"{finish_seconds:.9f} Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 1 Bytes 1000 Pkts 1\n"
        "0.000000000 Type FLOW_EVENT SrcID 2 Ev START FlowID 2 Flowsize 1000\n"
        f"{finish_seconds * 2:.9f} Type FLOW_EVENT SrcID 2 Ev FINISH FlowID 2 Bytes 1000 Pkts 1\n"
    )


def write_complete_matrix(data_dir: pathlib.Path) -> None:
    for arm in ("ops", "reps", "decmt", "laps"):
        for failed in (0, 8):
            for seed in (13, 14, 15):
                (data_dir / f"expA_smoke_{arm}_f{failed}_s{seed}.flow.txt").write_text(flow_text())


def test_dry_run_matrix() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            ["bash", str(RUNNER), "--dry-run"],
            text=True,
            capture_output=True,
            env={**os.environ, "DATA_DIR": str(pathlib.Path(tmp) / "data")},
            check=False,
        )
    assert result.returncode == 0, result.stderr
    commands = [line for line in result.stdout.splitlines() if line.startswith("PATHS=8 END_MS=8")]
    assert len(commands) == 24, commands
    tags = {part for line in commands for part in line.split() if part.startswith("expA_smoke_")}
    assert len(tags) == 24, tags
    assert any(" nscc oblivious 0 fat_tree_128_1os.topo 13 " in f" {line} " for line in commands)
    assert any(" nscc reps 8 fat_tree_128_1os.topo 15 " in f" {line} " for line in commands)
    assert any(" prism reps 8 fat_tree_128_1os.topo 15 " in f" {line} " for line in commands)
    assert any(" laps laps 0 fat_tree_128_1os.topo 13 " in f" {line} " for line in commands)


def test_complete_matrix_exports_summary_and_figure() -> None:
    module = load_plotter()
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = pathlib.Path(tmp) / "data"
        figs_dir = pathlib.Path(tmp) / "figs"
        data_dir.mkdir()
        write_complete_matrix(data_dir)
        rows = module.require_complete_matrix(data_dir)
        assert len(rows) == 24
        assert {row["arm"] for row in rows} == {"ops", "reps", "decmt", "laps"}
        module.write_summary(rows, data_dir / "summary.csv")
        module.render(rows, figs_dir)
        assert (data_dir / "summary.csv").is_file()
        assert (figs_dir / "expA_laps_smoke_performance.png").is_file()
        assert (figs_dir / "expA_laps_smoke_performance.pdf").is_file()


def test_missing_or_incomplete_cell_is_rejected() -> None:
    module = load_plotter()
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = pathlib.Path(tmp)
        write_complete_matrix(data_dir)
        missing = data_dir / "expA_smoke_laps_f8_s15.flow.txt"
        missing.unlink()
        try:
            module.require_complete_matrix(data_dir)
        except RuntimeError as exc:
            assert "expA_smoke_laps_f8_s15" in str(exc)
        else:
            raise AssertionError("missing cell was accepted")

        missing.write_text("0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 1000\n")
        try:
            module.require_complete_matrix(data_dir)
        except RuntimeError as exc:
            assert "expA_smoke_laps_f8_s15" in str(exc)
            assert "completion_rate" in str(exc)
        else:
            raise AssertionError("incomplete cell was accepted")


if __name__ == "__main__":
    test_dry_run_matrix()
    test_complete_matrix_exports_summary_and_figure()
    test_missing_or_incomplete_cell_is_rejected()
    print("ok: ExpA strict-LAPS smoke contracts")
