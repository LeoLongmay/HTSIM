# Three-panel 4:1 oversubscription archive

`archive_data/figBa_4os_sweep.csv` stores all 28 plotted cells: four requested throttled-link values times seven algorithms, each with goodput, average FCT, P99 FCT, population-standard-deviation error bars, and five seeds.

Redraw without simulation output:

```bash
cd htsim/sim/datacenter/prism_eval/expB_oversub_asym
python3 archive_fig_data.py --render
```

The historical `data/` directory is removed after validation. `--extract` is a provenance utility that requires restored raw flow logs.
