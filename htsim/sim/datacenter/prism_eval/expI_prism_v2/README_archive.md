# Selected 1024-node CDF archive

`archive_data/` holds the exact ECDF coordinates submitted to Matplotlib for the
six selected 1024-node CDF figures.  It is sufficient to redraw their main
curves and the queueing-delay tail inset without flow logs, ACK traces, seed
metadata, or simulator output.

To redraw the figures from archive-only data:

```bash
python3 archive_fig_data.py --render
```

To create the archive from raw logs before cleanup:

```bash
python3 archive_fig_data.py --extract
```

The source CSVs contain full-precision decimal representations of the plotted
coordinates.  The renderer preserves the published canvas, inset placement,
line widths, and Type 42 PDF embedding configuration.
