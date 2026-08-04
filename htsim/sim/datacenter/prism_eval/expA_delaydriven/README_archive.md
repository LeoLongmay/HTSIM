# Six-panel plotting-data archive

`archive_data/figA1dd_failed_sweep.csv` stores all 49 displayed failure-sweep points and their population-standard-deviation error bars. `archive_data/figA3dd_load_sweep.csv` stores the corresponding 35 load-sweep points. Each row retains goodput, average FCT, P99 FCT, their standard deviations, and the five-seed sample count.

Redraw the six panels without simulation logs:

```bash
cd htsim/sim/datacenter/prism_eval/expA_delaydriven
python3 archive_fig_data.py --render
```

The command only reads `archive_data/*.csv`, preserves the current panel styles and Type 42 PDF embedding, and overwrites the six selected PDF/PNG files. The historical `data/` directory is intentionally removed after archive validation; `--extract` requires restoring or rerunning those raw logs and is not required to redraw these panels.
