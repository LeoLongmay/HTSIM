"""Shared matplotlib style + helpers for all prism_eval figures.
Keeps fonts/colors consistent across the paper. Agg backend (headless)."""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# One palette for the whole evaluation. Keys are the baselines / signals.
COLORS = {
    "ops": "tab:gray",
    "reps": "tab:blue",
    "strack": "tab:orange",
    "prism": "tab:green",
    "mnscc": "tab:brown",  # median@NSCC (Gerstein et al. 2026) competitor
    "swift": "tab:pink",  # Swift (Kumar et al. 2020) delay-AIMD baseline
    "ccc": "tab:red",      # C_cc / floor
    "spray": "tab:orange",  # C_spray / spread band
    "target": "gray",
}

def apply_style(font_size=12):
    """Apply the shared rcParams. Call once at the top of each make_figs.py."""
    plt.rcParams.update({
        "font.size": font_size,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "figure.dpi": 140,
    })

def save(fig, stem, outdir):
    """Save a figure as both PNG and PDF under outdir, tightly cropped."""
    os.makedirs(outdir, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(outdir, f"{stem}.{ext}"),
                    bbox_inches="tight", pad_inches=0.04)
