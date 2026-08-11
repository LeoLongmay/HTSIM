"""FCT figure for the isolated equal-path-domain PATHS=16 comparison."""
import math
import statistics


ARMS = ("OPS", "REPS", "DecMT", "Prime")
FAILEDS = (0, 8)


def _aggregate(rows, arm, failed):
    group = [row for row in rows if row["arm"] == arm and row["failed"] == failed]
    fcts = sorted(sample for row in group for sample in row["_fct_samples_us"])
    return (statistics.mean(fcts) if fcts else math.nan,
            sum(row["completion_count"] for row in group),
            sum(row["censored_count"] for row in group))


def render(rows, output_dir):
    import matplotlib.pyplot as plt

    output_dir.mkdir(parents=True, exist_ok=True)
    figure, axes = plt.subplots(1, 2, figsize=(9, 3.6), sharey=True)
    for axis, failed in zip(axes, FAILEDS):
        values, annotations = [], []
        for arm in ARMS:
            mean, complete, censored = _aggregate(rows, arm, failed)
            values.append(0 if not math.isfinite(mean) else mean)
            annotations.append(f"{complete} done\n{censored} cens.")
        axis.bar(range(len(ARMS)), values, color=("#4477aa", "#66ccee", "#228833", "#cc6677"))
        for position, value, annotation in zip(range(len(ARMS)), values, annotations):
            axis.annotate(annotation, (position, value), xytext=(0, 3), textcoords="offset points",
                          ha="center", va="bottom", fontsize=7)
        axis.set_title(f"PATHS=16, failed={failed}")
        axis.set_xticks(range(len(ARMS)), ARMS, fontsize=9)
        axis.margins(y=0.16)
        axis.grid(axis="y", alpha=0.3)
    axes[0].set_ylabel("Mean completed FCT (us)")
    figure.suptitle("Equal path-domain comparison (PATHS=16)", fontsize=11)
    figure.tight_layout()
    figure.savefig(output_dir / "fig_prime_paths16_fct.png", dpi=160)
    plt.close(figure)
