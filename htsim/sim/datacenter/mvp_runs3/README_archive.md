# Five-figure plotting-data archive

`archive_data/` preserves exactly the data needed to redraw the following figures without simulation output:

| Figure | Archive table(s) | Contents |
| --- | --- | --- |
| `figA_floor_vs_load` | `figA_floor_vs_load.csv` | six mean and population-standard-deviation error-bar points |
| `figC_lb_depends_on_bottleneck` | `figC_lb_depends_on_bottleneck.csv` | four mean and population-standard-deviation bar values |
| `figI2_cc_lb_tuning_coupled` | `figI2_cc_lb_tuning_coupled.csv` | two six-point mean and sample-standard-deviation series |
| `figS1_path_distribution` | `figS1_path_samples.csv`, `figS1_markers.csv` | all 5,089 histogram samples and three vertical-marker positions |
| `figS2_load_sweep` | `figS2_load_sweep.csv` | five floor and average-delay means with standard deviations |

Render only from the archive:

```bash
cd htsim/sim/datacenter/mvp_runs3
python3 archive_fig_data.py --render
```

The command reads only `archive_data/*.csv` and overwrites the five figure PDF/PNG pairs.  It does not inspect path-RTT, sink, queue, idmap, stdout, or traffic-matrix files.  The PDFs embed Type 42 fonts.

`python3 archive_fig_data.py --extract` is retained only as a provenance utility. It requires raw logs, which are no longer kept after this archive cleanup; it is not required for later redraws.

The old raw artifacts shared with `figB_spray_lb_removable` and legacy `figI_cc_lb_tuning_coupled` were deliberately removed after the five CSV archives passed exact redraw verification. Those two legacy figures require a new simulation run before their raw-data-based renderers can be used again.
