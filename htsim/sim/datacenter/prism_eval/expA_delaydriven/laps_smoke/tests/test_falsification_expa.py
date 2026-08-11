#!/usr/bin/env python3
import csv
import importlib.util
import pathlib
import tempfile


HERE = pathlib.Path(__file__).resolve().parents[1]
REPORTER = HERE / "report_falsification_expa.py"


def load_reporter():
    spec = importlib.util.spec_from_file_location("falsification_reporter", REPORTER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> None:
    module = load_reporter()
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        flow = root / "cell.flow.txt"
        flow.write_text(
            "0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 11 Flowsize 1000\n"
            "0.002000000 Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 11 Bytes 1000 Pkts 1\n"
            "0.001000000 Type FLOW_EVENT SrcID 2 Ev START FlowID 22 Flowsize 2000\n",
            encoding="ascii",
        )
        stdout = root / "cell.stdout"
        stdout.write_text(
            "New: 3 Rtx: 1\n"
            "UEC_DELIVERY_SUMMARY flow=11 delivered_bytes=1000\n"
            "UEC_DELIVERY_SUMMARY flow=22 delivered_bytes=400\n",
            encoding="ascii",
        )
        diagnostics = root / "cell.laps.csv"
        fields = list(module.DIAGNOSTIC_FIELDS)
        with diagnostics.open("w", newline="", encoding="ascii") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            base = {field: "" for field in fields}
            writer.writerow({**base, "time_ns": "1", "event_seq": "0", "flow": "11",
                             "event_type": "probe_sent", "pid": "0", "seq": "9",
                             "pit_valid": "1", "pit_selectable": "0",
                             "pit_probe_pending": "1", "pit_updated_at_ns": "1"})
            writer.writerow({**base, "time_ns": "2", "event_seq": "1", "flow": "11",
                             "event_type": "probe_acked", "pid": "0", "seq": "9",
                             "pit_valid": "1", "pit_selectable": "1",
                             "pit_probe_pending": "0", "pit_updated_at_ns": "2",
                             "pit_deadline_ns": "4"})
            writer.writerow({**base, "time_ns": "3", "event_seq": "2", "flow": "11",
                             "event_type": "data_acked", "pid": "1", "seq": "10",
                             "pit_valid": "1", "pit_selectable": "0",
                             "pit_probe_pending": "1", "pit_updated_at_ns": "2"})

        fct_samples = root / "cell.fct.tsv"
        censored = root / "cell.censored.tsv"
        metrics = module.extract_cell_metrics(
            flow, stdout, diagnostics, fct_samples, censored, horizon_s=0.008,
            expected_flows=2,
        )
        assert metrics["completion_count"] == 1
        assert metrics["censored_count"] == 1
        assert metrics["fct_sample_count"] == 1
        assert metrics["fct_mean_us"] == 2000.0
        assert metrics["fct_p50_us"] == 2000.0
        assert metrics["fct_p95_us"] == 2000.0
        assert metrics["delivered_bytes"] == 1400
        assert metrics["goodput_gbps"] == 0.0014
        assert metrics["pit_invariant_violations"] == 1
        assert fct_samples.read_text().splitlines() == [
            "src_id\tflow_id\tstart_s\tfinish_s\tfct_us\tdelivered_bytes",
            "1\t11\t0.000000000\t0.002000000\t2000.000000\t1000",
        ]
        assert censored.read_text().splitlines() == [
            "src_id\tflow_id\tstart_s\tflowsize_bytes\tcensored_at_s",
            "2\t22\t0.001000000\t2000\t0.008000000",
        ]


if __name__ == "__main__":
    main()
