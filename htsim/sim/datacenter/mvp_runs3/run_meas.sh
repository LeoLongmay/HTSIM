#!/bin/bash
# Measurement run for fig1 (goodput/underutilization) and fig2 (bottleneck queue / late reaction).
# Uses ONLY existing logging flags -- no C++ behavior change:
#   -log sink          -> UEC_SINK RATE records (receiver goodput, bits/s)  -> $TAG.sink.txt
#   -log tor_downqueue -> QUEUE_APPROX RANGE records (LastQ bytes per ToR->host downlink) -> $TAG.q.txt
# Separate from run_one.sh so the figA-F pathrtt runs stay byte-identical.
#
# Args:  LB  FAILED  TAG  CM  [LOGSPEC=both]   (LOGSPEC in sink|queue|both)
# Env:   SEED(13)  END(2 ms)  LOGTIME(2 us)  KEEPDAT(unset=delete .dat after decode)
set -euo pipefail
DC="$(cd "$(dirname "$0")/.." && pwd)"   # .../sim/datacenter
cd "$DC"
LB="$1"; FAILED="$2"; TAG="$3"; CM="$4"; LOGSPEC="${5:-both}"
SEED="${SEED:-13}"; END="${END:-2}"; LOGTIME="${LOGTIME:-2}"
TQD_ARG=""           # NSCC target_q_delay (us); only passed when TQD env is set (default = binary's 6us)
[ -n "${TQD:-}" ] && TQD_ARG="-target_q_delay ${TQD}"
OUT=mvp_runs3
case "$LOGSPEC" in
  sink)  LOGARGS="-log sink";;
  queue) LOGARGS="-log tor_downqueue";;
  both)  LOGARGS="-log sink -log tor_downqueue";;
  *) echo "bad LOGSPEC $LOGSPEC"; exit 2;;
esac
echo "[meas] lb=$LB failed=$FAILED tag=$TAG cm=$CM log=$LOGSPEC seed=$SEED end=$END logtime=${LOGTIME}us${TQD:+ tqd=$TQD}"
./htsim_uec -topo topologies/fat_tree_128_1os.topo -tm "$CM" -nodes 128 \
    -sender_cc_algo nscc -load_balancing_algo "$LB" -failed "$FAILED" -mtu 4150 \
    -paths 8 -seed "$SEED" $TQD_ARG $LOGARGS -logtime_us "$LOGTIME" -end "$END" \
    -o "$OUT/$TAG.dat" > "$OUT/$TAG.stdout" 2>&1
cp idmap.txt "$OUT/$TAG.idmap"
if [ "$LOGSPEC" = sink ] || [ "$LOGSPEC" = both ]; then
    ../build/parse_output "$OUT/$TAG.dat" -ascii 2>/dev/null | grep ' UEC_SINK ' > "$OUT/$TAG.sink.txt" || true
fi
if [ "$LOGSPEC" = queue ] || [ "$LOGSPEC" = both ]; then
    ../build/parse_output "$OUT/$TAG.dat" -ascii 2>/dev/null | grep ' QUEUE_APPROX ' | grep ' RANGE ' > "$OUT/$TAG.q.txt" || true
fi
[ -n "${KEEPDAT:-}" ] || rm -f "$OUT/$TAG.dat"
echo "[meas] done $TAG: $(grep -m1 'Load balancing algorithm set to' "$OUT/$TAG.stdout" || true)"
