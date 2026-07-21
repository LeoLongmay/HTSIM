"""Contract tests for the Hold-episode summary figure."""
import csv
import importlib.util
from pathlib import Path


HERE = Path(__file__).resolve().parent
MAKE_FIGS = HERE.parent / "make_figs.py"


def _load_make_figs():
    spec = importlib.util.spec_from_file_location("expK_hold_episode_make_figs", MAKE_FIGS)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_aggregate(input_dir: Path) -> None:
    fields = [
        "scenario", "status", "outcome", "f_entry_ns", "s_entry_ns",
        "pre_low_support", "post1_low_support", "post2_low_support",
        "pre_high_tail", "post1_high_tail", "post2_high_tail",
        "pre_ack_rate_bps", "post1_ack_rate_bps", "post2_ack_rate_bps",
    ]
    _write_csv(input_dir / "episode_rows.csv", fields, [
        {
            "scenario": "f0", "status": "complete", "outcome": "recovered",
            "f_entry_ns": 14, "s_entry_ns": 14,
            "pre_low_support": 0.25, "post1_low_support": 0.5,
            "post2_low_support": 0.75, "pre_high_tail": 0.75,
            "post1_high_tail": 0.5, "post2_high_tail": 0.25,
            "pre_ack_rate_bps": 80_000_000, "post1_ack_rate_bps": 90_000_000,
            "post2_ack_rate_bps": 100_000_000,
        },
        {
            "scenario": "f0", "status": "complete", "outcome": "ineffective",
            "f_entry_ns": 28, "s_entry_ns": 14,
            "pre_low_support": 0.5, "post1_low_support": 0.25,
            "post2_low_support": 0.25, "pre_high_tail": 0.25,
            "post1_high_tail": 0.5, "post2_high_tail": 0.75,
            "pre_ack_rate_bps": 100_000_000, "post1_ack_rate_bps": 90_000_000,
            "post2_ack_rate_bps": 80_000_000,
        },
        {
            "scenario": "f0", "status": "incomplete", "outcome": "incomplete",
            "f_entry_ns": 14, "s_entry_ns": 28,
            "pre_low_support": "", "post1_low_support": "", "post2_low_support": "",
            "pre_high_tail": "", "post1_high_tail": "", "post2_high_tail": "",
            "pre_ack_rate_bps": 0, "post1_ack_rate_bps": 0, "post2_ack_rate_bps": 0,
        },
    ])
    _write_csv(input_dir / "scenario_summary.csv", [
        "scenario", "complete_episodes", "incomplete_episodes", "recovered_episodes",
        "ineffective_episodes", "mixed_episodes",
    ], [
        {
            "scenario": "f0", "complete_episodes": 2, "incomplete_episodes": 1,
            "recovered_episodes": 1, "ineffective_episodes": 1, "mixed_episodes": 0,
        },
        {
            "scenario": "incast", "complete_episodes": 0, "incomplete_episodes": 0,
            "recovered_episodes": 0, "ineffective_episodes": 0, "mixed_episodes": 0,
        },
    ])
    _write_csv(input_dir / "seed_summary.csv", [
        "scenario", "seed", "episodes", "complete", "incomplete", "recovered",
        "ineffective", "mixed",
    ], [
        {
            "scenario": "f0", "seed": 13, "episodes": 2, "complete": 2,
            "incomplete": 0, "recovered": 1, "ineffective": 1, "mixed": 0,
        },
        {
            "scenario": "f0", "seed": 14, "episodes": 0, "complete": 0,
            "incomplete": 0, "recovered": 0, "ineffective": 0, "mixed": 0,
        },
        {
            "scenario": "incast", "seed": 13, "episodes": 0, "complete": 0,
            "incomplete": 0, "recovered": 0, "ineffective": 0, "mixed": 0,
        },
    ])


def test_render_creates_pdf_png_and_coverage_annotation(tmp_path, monkeypatch):
    _write_aggregate(tmp_path)
    annotations = []

    import matplotlib.axes

    original_text = matplotlib.axes.Axes.text

    def capture_text(self, *args, **kwargs):
        annotations.append(args[2] if len(args) > 2 else kwargs.get("s"))
        return original_text(self, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "text", capture_text)
    make_figs = _load_make_figs()
    out = tmp_path / "hold_episode.pdf"

    make_figs.render(tmp_path, out)

    assert out.exists() and out.stat().st_size > 0
    assert out.with_suffix(".png").exists()
    assert any("incast: insufficient complete Hold episodes" == text
               for text in annotations)
    assert any("f0 (seed 14): insufficient complete Hold episodes" == text
               for text in annotations)
    assert "insufficient complete Hold episodes" in MAKE_FIGS.read_text()


def test_entry_scatter_annotates_missing_outcome_category(monkeypatch):
    annotations = []

    import matplotlib.axes
    import matplotlib.pyplot as plt

    original_text = matplotlib.axes.Axes.text

    def capture_text(self, *args, **kwargs):
        annotations.append(args[2] if len(args) > 2 else kwargs.get("s"))
        return original_text(self, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "text", capture_text)
    make_figs = _load_make_figs()
    fig, ax = plt.subplots()
    make_figs._plot_entry_scatter(ax, ["f0"], [{
        "scenario": "f0", "outcome": "recovered", "f_entry_ns": "14", "s_entry_ns": "28",
    }])
    plt.close(fig)

    assert "ineffective: insufficient complete Hold episodes" in annotations
