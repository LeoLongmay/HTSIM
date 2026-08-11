#!/usr/bin/env python3
import csv
import importlib.util
import pathlib
import subprocess
import tempfile

HERE = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = HERE / "analyze_laps_diag.py"


def load_module():
    spec = importlib.util.spec_from_file_location("analyze_laps_diag", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_trace(path):
    header = "time_ns,event_seq,flow,event_type,pid,seq,bytes,rate_bps,target_rate_bps,all_paths_high,target_delay_ns,min_delay_ns,one_way_delay_ns,recovery_cause,timer_deadline_ns,is_retransmission,outstanding_probes,pit_valid,pit_selectable,pit_probe_pending,pit_updated_at_ns,pit_deadline_ns".split(",")
    rows = [
        ["1", "0", "1", "rate_update", "", "", "", "100", "100", "0", "10", "5", "", "", "", ""],
        ["2", "1", "1", "rate_update", "", "", "", "1", "10", "1", "10", "5", "", "", "", ""],
        ["3", "2", "1", "probe_sent", "0", "9", "64", "", "", "", "", "", "", "", "", "1"],
        ["4", "3", "1", "data_sent", "0", "1", "4150", "1", "10", "", "", "", "", "", "0", ""],
        ["5", "4", "1", "data_sent", "0", "2", "4150", "1", "10", "", "", "", "", "", "0", ""],
        ["6", "5", "1", "data_sent", "0", "3", "4150", "1", "10", "", "", "", "", "", "0", ""],
        ["7", "6", "1", "data_sent", "0", "4", "4150", "1", "10", "", "", "", "", "", "0", ""],
        ["8", "7", "1", "data_sent", "1", "5", "4150", "1", "10", "", "", "", "", "", "0", ""],
    ]
    rows += [[str(9 + i), str(8 + i), "1", "recovery", "0", str(i), "4150", "", "", "", "", "", "", "ack_gap", "", ""] for i in range(7)]
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream); writer.writerow(header); writer.writerows(rows)


def main():
    module = load_module()
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        trace = root / "trace.csv"; write_trace(trace)
        events = module.read_trace(trace)
        summary = module.summarize("degraded", events, {"completed": 62, "total": 64})
        assert summary["completion_rate"] == 0.96875
        assert summary["min_rate_bps"] == 1
        assert summary["pid_data_share_max"] == 0.8
        assert summary["ack_gap_recovery"] == 7
        malformed = root / "bad.csv"; malformed.write_text("wrong\n")
        try:
            module.read_trace(malformed)
        except ValueError:
            pass
        else:
            raise AssertionError("malformed header accepted")
    output = subprocess.check_output([HERE / "repro_diagnostics.sh", "--dry-run"], text=True)
    assert output.count("LAPS_DIAG=") == 2
    assert "failed=0" in output and "seed=13" in output
    assert "failed=8" in output and "seed=14" in output
    source = (HERE.parents[3] / "uec.cpp").read_text()
    assert 'event.event_type = "data_acked"' in source
    assert '"recovery_timer_armed"' in source
    assert '"recovery_timeout_fired"' in source
    print("ok: strict LAPS diagnostic analysis contracts")


if __name__ == "__main__":
    main()
