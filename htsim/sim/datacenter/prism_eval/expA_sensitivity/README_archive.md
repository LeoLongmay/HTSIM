# Selected FigK queueing-delay archive

`archive_data/figK_qd_panels.csv` contains the exact plotted parameter values,
five-seed mean goodput, and five-seed mean end-to-end queueing delay for the
three selected queueing-delay panels.  It is sufficient to redraw them without
path-RTT traces, flow logs, or other sensitivity data.

```bash
python3 archive_fig_data.py --render
```
