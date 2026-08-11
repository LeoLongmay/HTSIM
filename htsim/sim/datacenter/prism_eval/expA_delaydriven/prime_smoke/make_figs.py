"""Figures for the fixed PRIME ExpA report."""
import math
import re
import statistics


ARMS = ("OPS", "REPS", "DecMT", "Prime")
FAILEDS = (0, 8)
HOST_ONLY_NOTE = ("Host-only whole-path mapping; path feedback is source-aggregate, "
                  "not switch-local/per-hop forwarding or congestion localization.")


def _aggregate(rows, arm, failed):
    group = [r for r in rows if r["arm"] == arm and r["failed"] == failed]
    fcts = sorted(sample for row in group for sample in row.get("_fct_samples_us", []))
    return (statistics.mean(fcts) if fcts else math.nan,
            sum(r["completion_count"] for r in group),
            sum(r["censored_count"] for r in group))


def tier_numbers(rows):
    """Tuple tiers represented by selection-share columns, in tuple order."""
    result = set()
    for row in rows:
        for key in row:
            match = re.fullmatch(r"tier(\d+)_share_\d+", key)
            if match:
                result.add(int(match.group(1)))
    return sorted(result)


def weighted_tier_share(rows, tier, port):
    selections = sum(row["selection_count"] for row in rows)
    if not selections:
        return math.nan
    return sum(row.get(f"tier{tier}_share_{port}", 0.0) * row["selection_count"]
               for row in rows) / selections


def render(rows, output_dir):
    import matplotlib.pyplot as plt

    output_dir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6), sharey=True)
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
        axis.set_title(f"failed={failed}")
        axis.set_xticks(range(len(ARMS)), ARMS, fontsize=9)
        axis.margins(y=0.16)
        axis.grid(axis="y", alpha=0.3)
    axes[0].set_ylabel("Mean completed FCT (us)")
    fig.text(0.5, 0.035, HOST_ONLY_NOTE, ha="center", va="bottom", fontsize=8)
    fig.tight_layout(rect=(0, 0.12, 1, 1))
    fig.savefig(output_dir / "fig_prime_fct.png", dpi=160)
    plt.close(fig)

    prime_rows = [r for r in rows if r["arm"] == "Prime"]
    tiers = tier_numbers(prime_rows)
    fig, axes = plt.subplots(1, max(1, len(tiers)), figsize=(4.2 * max(1, len(tiers)), 3.6),
                             sharey=True, squeeze=False)
    axes = axes[0]
    for axis, tier in zip(axes, tiers):
        ports = sorted({int(key.rsplit("_", 1)[1]) for row in prime_rows for key in row
                        if re.fullmatch(rf"tier{tier}_share_\d+", key)})
        positions = list(range(len(ports)))
        width = 0.35
        for offset, failed in enumerate(FAILEDS):
            group = [r for r in prime_rows if r["failed"] == failed]
            values = [weighted_tier_share(group, tier, port) for port in ports]
            shift = (offset - (len(FAILEDS) - 1) / 2) * width
            axis.bar([position + shift for position in positions], values, width=width,
                     label=f"failed={failed}")
        axis.set_title(f"Prime tuple tier {tier}")
        axis.set_xticks(positions, ports)
        axis.set_xlabel(f"tier-{tier} port")
        axis.grid(axis="y", alpha=0.3)
        axis.legend(fontsize=8)
    if not tiers:
        axes[0].set_visible(False)
    axes[0].set_ylabel("Selection share")
    fig.text(0.5, 0.035, HOST_ONLY_NOTE, ha="center", va="bottom", fontsize=8)
    fig.tight_layout(rect=(0, 0.12, 1, 1))
    fig.savefig(output_dir / "fig_prime_tier_share.png", dpi=160)
    plt.close(fig)
