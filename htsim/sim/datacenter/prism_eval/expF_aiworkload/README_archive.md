# Selected ExpF figure archive

`archive_data/figF3_ai_msgsize.csv` retains only the geometric-mean bar values,
geometric-SEM error bars, and completion markers plotted in `figF3_ai_msgsize`.
It is sufficient for exact replotting without flow logs or per-seed simulator
output.

The original `figF1_cct_bars` flow bundle is not present in this workspace: it
was replaced by the later message-size sweep.  The README table rounds its
values and therefore cannot serve as an exact plotting archive.

```bash
python3 archive_fig_data.py --render
```
