#!/usr/bin/env python3
"""Contract test for the four-arm PaperACK acceptance runner."""
import csv
import pathlib
import subprocess
import tempfile


HERE = pathlib.Path(__file__).resolve().parents[1]
RUNNER = HERE / "run_paperack_compare.sh"


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        simulator = root / "simulator"
        simulator.write_text(
            """#!/usr/bin/env bash
set -euo pipefail
for ((index = 1; index <= $#; ++index)); do
    if [[ ${!index} == -o ]]; then
        next=$((index + 1))
        result=${!next}
    fi
done
printf '# numrecords=66\\n' >"$result"
printf 'New: 10 Rtx: 2\\n'
if [[ -n ${LAPS_DIAG:-} ]]; then
    printf 'time_ns,event_seq,flow,event_type,pid,seq,bytes,rate_bps,target_rate_bps,all_paths_high,target_delay_ns,min_delay_ns,one_way_delay_ns,recovery_cause,timer_deadline_ns,is_retransmission,outstanding_probes\\n' >"$LAPS_DIAG"
    printf '1,0,1,probe_sent,0,1,,,,,,,,,,,,\\n2,1,1,probe_acked,0,1,,,,,,,,,,,,\\n' >>"$LAPS_DIAG"
fi
"""
        )
        simulator.chmod(0o755)
        output = root / "output"
        completed = subprocess.run(
            [str(RUNNER), str(simulator), str(output)], text=True, capture_output=True, check=False
        )
        assert completed.returncode == 0, completed.stderr
        with (output / "summary.tsv").open(newline="") as stream:
            rows = list(csv.DictReader(stream, delimiter="\t"))
        assert len(rows) == 4
        assert all(row["completion_count"] == "2" for row in rows)
        assert rows[0]["arm"] == "OPS"
        assert rows[0]["probe_sent"] == rows[0]["probe_acked"] == "0"
        assert rows[0]["diagnostics"] == "not-applicable"
        assert all(row["probe_sent"] == row["probe_acked"] == "1" for row in rows[1:])
        assert all(row["diagnostic_events"] == "2" for row in rows[1:])


if __name__ == "__main__":
    main()
