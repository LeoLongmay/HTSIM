# ExpA gated falsification runner

`run_falsification_expa.sh` runs ExpA only after the focused deterministic
LAPS CTest gate passes. That gate includes the paired legacy/paperack probe
trace and the one-/eight-path source→sink→source ACK fixtures. The experiment
parameters remain FatTree128, `data/m2m.cm`, 128 nodes, MTU 4150, eight paths,
`-disable_trim`, and an 8 ms horizon.

```bash
out=$(mktemp -d /tmp/laps-expa-fixed.XXXXXX)
./run_falsification_expa.sh /tmp/htsim-laps-tests/datacenter/htsim_uec \
  /tmp/htsim-laps-tests "$out" fixed

out=$(mktemp -d /tmp/laps-expa-matrix.XXXXXX)
./run_falsification_expa.sh /tmp/htsim-laps-tests/datacenter/htsim_uec \
  /tmp/htsim-laps-tests "$out" matrix
```

The output directory must be empty and is never overwritten. Each cell keeps
the raw `.dat`, `.stdout`, decoded `.flow.txt`, observed completed-flow
`.fct.tsv`, and explicit `.censored.tsv`. LAPS cells also keep `.laps.csv`.

FCT mean/p50/p95 are calculated only from real START/FINISH pairs; incomplete
flows are never zero-filled. Delivered goodput is `sum(sink application
bytes) × 8 / 8 ms`, using exact per-sink bytes emitted after the event loop,
not `New × MTU`. `pit_invariant_violations` is derived from immutable post-event
PIT fields in `data_acked`, `probe_sent`, and `probe_acked` diagnostics.

The older `data_fixed`, `data_pacing_liveness`, `/tmp/laps-expa-fixed.rc29Pm`,
and `/tmp/laps-expa-matrix.taMNCt` outputs are exploratory: they use injected
packet estimates and do not carry admissible FCT/censoring/PIT evidence.
