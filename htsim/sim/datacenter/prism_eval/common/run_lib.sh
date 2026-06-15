#!/bin/bash
# common/run_lib.sh -- unified htsim_uec runner for prism_eval.
# Runs ONE simulation, decodes the .dat trace ONCE, and extracts the requested text
# logs. flow_events (FCT) is on by default in the binary; sink/queue need -log flags.
# Per-path RTT is emitted directly by the binary when env PRISM_PATHRTT is set.
#
# Usage:
#   bash common/run_lib.sh CC LB FAILED TOPO SEED CM LOGSPEC TAG OUTDIR
# Positional args:
#   CC       sender_cc_algo: nscc|dctcp|constant|prism|strack
#   LB       load_balancing_algo: reps|oblivious|ecmp|...
#   FAILED   # degraded core->agg downlinks (0 = none)
#   TOPO     topology filename under topologies/ (e.g. fat_tree_128_1os.topo)
#   SEED     RNG seed (int)
#   CM       traffic matrix .cm path, relative to the datacenter dir
#   LOGSPEC  comma list subset of {flow,sink,queue}; include 'flow' for FCT
#   TAG      output basename
#   OUTDIR   output dir, relative to the datacenter dir (created if absent)
# Env knobs: PATHS(8) END_MS(2) MTU(4150) NODES(128) TQD(unset) KEEPDAT(unset)
#            PRISM_PATHRTT(unset -> path "$OUTDIR/$TAG.pathrtt.csv" if you export it)
set -euo pipefail
[ "$#" -eq 9 ] || { echo "usage: run_lib.sh CC LB FAILED TOPO SEED CM LOGSPEC TAG OUTDIR" >&2; exit 2; }
CC="$1"; LB="$2"; FAILED="$3"; TOPO="$4"; SEED="$5"; CM="$6"; LOGSPEC="$7"; TAG="$8"; OUTDIR="$9"
DC="$(cd "$(dirname "$0")/../.." && pwd)"   # common -> prism_eval -> datacenter
cd "$DC"
PATHS="${PATHS:-8}"; END_MS="${END_MS:-2}"; MTU="${MTU:-4150}"; NODES="${NODES:-128}"
BIN=./htsim_uec
DECODER=../build/parse_output
[ -x "$BIN" ] || { echo "ERROR: $BIN missing -- build htsim_uec first"; exit 1; }
[ -x "$DECODER" ] || { echo "ERROR: $DECODER missing -- build it first"; exit 1; }
mkdir -p "$OUTDIR"
TQD_ARG=""; [ -n "${TQD:-}" ] && TQD_ARG="-target_q_delay ${TQD}"
LOGARGS=""
case ",$LOGSPEC," in *,sink,*)  LOGARGS="$LOGARGS -log sink";; esac
case ",$LOGSPEC," in *,queue,*) LOGARGS="$LOGARGS -log tor_downqueue";; esac
echo "[run_lib] cc=$CC lb=$LB failed=$FAILED topo=$TOPO seed=$SEED cm=$CM log=$LOGSPEC tag=$TAG"
$BIN -topo "topologies/$TOPO" -tm "$CM" -nodes "$NODES" \
     -sender_cc_algo "$CC" -load_balancing_algo "$LB" -failed "$FAILED" -mtu "$MTU" \
     -paths "$PATHS" -seed "$SEED" $TQD_ARG $LOGARGS -end "$END_MS" \
     -o "$OUTDIR/$TAG.dat" > "$OUTDIR/$TAG.stdout" 2>&1
ASCII="$OUTDIR/$TAG.ascii.tmp"
"$DECODER" "$OUTDIR/$TAG.dat" -ascii > "$ASCII" 2>/dev/null || true
case ",$LOGSPEC," in *,flow,*)  grep ' FLOW_EVENT ' "$ASCII" > "$OUTDIR/$TAG.flow.txt" || true;; esac
case ",$LOGSPEC," in *,sink,*)  grep ' UEC_SINK ' "$ASCII" > "$OUTDIR/$TAG.sink.txt" || true;; esac
case ",$LOGSPEC," in *,queue,*) grep ' QUEUE_APPROX ' "$ASCII" | grep ' RANGE ' > "$OUTDIR/$TAG.q.txt" || true;; esac
cp idmap.txt "$OUTDIR/$TAG.idmap" 2>/dev/null || true
rm -f "$ASCII"
[ -n "${KEEPDAT:-}" ] || rm -f "$OUTDIR/$TAG.dat"
echo "[run_lib] done $TAG"
