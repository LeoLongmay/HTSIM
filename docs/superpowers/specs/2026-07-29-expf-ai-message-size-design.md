# ExpF AI-ring message-size CCT-slowdown figure

## Goal

Add a standalone figure that evaluates the existing 128-node AI-ring collective while
sweeping per-flow message size.  It must not change or overwrite the existing
failed-link sweep (`figF1_cct_bars`).

## Experiment

- Keep the ExpF fabric and workload structure: 128-node 100-Gbps fat tree, the
  AI-ring generator, delay-driven transport, and the seven existing arms.
- Fix `failed=8` and use seeds 13--17.
- Sweep message sizes 16 KiB, 64 KiB, 256 KiB, 1 MiB, and 4 MiB.
- Write generated workloads and logs using an `expFmsg_` prefix, separate from the
  existing `expF_` failed-link-sweep files.

## Metric and plot

For every message-size and seed, compute each arm's collective makespan, divide it
by the smallest makespan among all seven arms for that same seed, then take the
geometric mean across seeds.  Thus `CCT slowdown` is at least 1.0 and 1.0 denotes
the fastest observed arm for the matched seed.  Geometric-SEM intervals are shown
as asymmetric error bars.

The new grouped-bar figure uses `Message size` on the x-axis and `CCT slowdown` on
the y-axis, and is saved as `figF3_ai_msgsize.{pdf,png}`.  It reuses the ExpG2
message-size plotting helper to preserve the definition and visual convention.

## Verification

Run the common generator/metric self-tests, check that all 175 result cells exist
and complete, and verify the generated PDF labels and that its values are all at
least 1.0.
