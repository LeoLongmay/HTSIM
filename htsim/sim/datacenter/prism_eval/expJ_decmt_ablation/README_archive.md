# Selected ExpJ bar-panel archive

`archive_data/figJ1_failed8_bars.csv` contains precisely the four bar heights
and error bars required by the standalone Avg FCT, Goodput, and P99 FCT
figures.  No seed-level measurements, control-condition values, flow logs, or
simulation output is needed to redraw these three panels.

```bash
python3 archive_fig_data.py --render
```

The archive renderer uses the same publication panel routine and therefore
preserves canvas dimensions, labels, bar width, colours, typography, and Type
42 PDF font embedding.
