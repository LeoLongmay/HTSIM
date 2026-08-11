# PRIME penalty lifecycle

`analyze.py` consumes one `PRIME_DIAG` TSV or a tree of ExpA run directories:

```bash
python3 analyze.py --input ../runs/expa_paths8_final --output .
```

It writes `prime_penalty_lifecycle.tsv`, with one row for every ECN, NACK, or
timeout feedback episode.  Later selections are considered only within the
same flow.  The first selection of the failed tuple resolves an episode;
episodes still open at the end of a trace are explicitly marked `censored`.
`distinct_tuples_before_reselect` excludes the resolving tuple itself.

`prime_penalty_lifecycle_summary.tsv` groups episodes by failed-path count and
feedback type.  Its p50/p95 reselect metrics use resolved episodes only, while
the companion figure separates resolved and censored counts. The current
ten-column diagnostic schema is, in order: `event_seq`, `time_ps`, `flow`,
`event`, `entropy`, `tuple`, `reason`, `feedback`, `penalty_before`,
`penalty_after`. The analyzer also accepts the former nine-column schema
(everything after `event_seq`); legacy rows preserve trace-file order.

## Archived evidence and censoring rule

Keep the run tree ignored; commit only the per-episode TSV and companion figure:

```bash
cp ../prime_penalty_lifecycle.tsv ../archive_data/prime_penalty_lifecycle.tsv
cp ../fig_prime_penalty_lifecycle.png ../figs/fig_prime_penalty_lifecycle.png
test -s ../archive_data/prime_penalty_lifecycle.tsv
test -s ../figs/fig_prime_penalty_lifecycle.png
```

An episode belongs to one flow. It resolves only when that flow later selects
the identical tuple, and is censored if no such selection occurs by trace end.
Report p50/p95 reselection metrics only for resolved episodes while retaining
resolved and censored counts. These are observation-only feedback-to-reselection
intervals; they do not claim that Prime is fixed, that controller behavior
changed, or that the paper is reproduced.
