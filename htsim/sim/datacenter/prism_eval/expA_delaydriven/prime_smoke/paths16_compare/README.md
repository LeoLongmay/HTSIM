# Equal path-domain PRIME ExpA comparison (`PATHS=16`)

This is a separate 24-cell comparison: OPS (`nscc/oblivious`), REPS
(`nscc/reps`), DecMT (`prism/reps_actual`), and Prime (`nscc/prime`) crossed with
`failed={0,8}` and `seed={13,14,15}`. Every arm uses `PATHS=16`, `-disable_trim`,
and an 8 ms horizon. It does not read, modify, or reinterpret the fixed `PATHS=8`
smoke archive.

```bash
bash repro.sh --out ../runs/paths16_compare
python3 report.py --input ../runs/paths16_compare --output ..
```

The reporter requires all 24 cells. Every Prime cell must contain a `PRIME_DIAG`
trace with selection events from all four source-ToR uplinks (`0,1,2,3`), otherwise
it fails. `prime_paths16_compare.tsv` retains completed-flow FCT metrics, censored
flow counts, exact sink-delivered bytes, and delivered goodput over the fixed 8 ms
horizon. `fig_prime_paths16_fct.png` is separately labelled `PATHS=16`.

## Archived evidence and interpretation boundary

Keep `runs/paths16_compare` ignored. Commit only the generated summary and
figure at these fixed locations, then require both to be nonempty:

```bash
cp ../prime_paths16_compare.tsv ../archive_data/prime_paths16_compare.tsv
cp ../fig_prime_paths16_fct.png ../figs/fig_prime_paths16_fct.png
test -s ../archive_data/prime_paths16_compare.tsv
test -s ../figs/fig_prime_paths16_fct.png
```

Before archiving, require exactly 24 cell rows and source-uplink coverage
`0,1,2,3` in all six Prime cells:

```bash
awk -F '\t' 'NR>1 && $1=="cell" {n++} END {exit n!=24}' ../prime_paths16_compare.tsv
awk -F '\t' 'NR>1 && $1=="cell" && $2=="Prime" {sub(/\r$/, "", $NF); if ($NF=="0,1,2,3") n++} END {exit n!=6}' ../prime_paths16_compare.tsv
```

This equal-domain comparison is evidence about a `PATHS=16` condition only. It
does not alter the fixed `PATHS=8` archive, establish a Prime performance win,
or reproduce the paper.
