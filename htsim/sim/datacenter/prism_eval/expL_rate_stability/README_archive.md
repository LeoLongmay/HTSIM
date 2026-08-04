# FigL1 split-panel archive

`archive_data/figL1_rate_panels.csv` contains exactly the aggregate trajectories
and five DecMT seed trajectories used to draw the standalone symmetric and
asymmetric FigL1 panels.  It excludes the beta-sensitivity data, raw sink
traces, simulator logs, manifests, and unplotted analysis fields.

Redraw both panels without simulation data:

```bash
python3 archive_fig_data.py --render
```

The renderer delegates to the publication panel routine, preserving its Type
42 PDF embedding, figure size, labels, limits, DecMT IQR band, and style.
