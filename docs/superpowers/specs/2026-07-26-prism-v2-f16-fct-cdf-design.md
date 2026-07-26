# Prism v2 f=16 FCT CDF design

## Goal

Render a directly comparable `failed=16` flow-completion-time CDF from the
already completed 1024-node double-evidence sweep, without rerunning a
simulation.

## Design

Parameterize the FCT-CDF endpoint in the existing double-evidence renderer.
The command-line interface accepts one explicit FCT-CDF failure level, defaulting
to the existing value `32` to preserve current sweep reproduction. The selected
level must be included in `--failures`; the renderer reads the corresponding
`double_{arm}_f{level}_s{seed}.flow.txt` files and writes a distinct
`figI_1024_f{level}_fct_cdf.{png,pdf}` pair.

For `level=16`, the figure uses the exact existing arms, seeds `13..17`, one
seed-local FCT ECDF per seed, equal average across those ECDFs, FCT in microseconds,
and the same labels, colors, and layout as f=32. Its title explicitly reads
`Failure=16; seed-local FCT ECDFs equally weighted`.

## Scope and verification

Only the renderer, its Python tests, the existing runner's render call, README,
and the two f=16 artefacts may change. The ignored raw logs remain untouched;
the 100-run simulation is not rerun. Tests assert that f=16 writes the required
PNG/PDF pair and that the unchanged default still writes the existing f=32 pair.
