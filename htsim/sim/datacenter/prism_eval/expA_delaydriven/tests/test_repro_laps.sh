#!/usr/bin/env bash
# Contract test for the additive, fail-closed LAPS ExpA sweep.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
RUNNER="$HERE/../repro_laps.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

dry_run="$TMP/dry-run.txt"
bash "$RUNNER" --dry-run >"$dry_run"

command_count="$(grep -c '^PATHS=8 END_MS=8 EXTRA_ARGS=-disable_trim bash ' "$dry_run")"
[ "$command_count" -eq 35 ] || {
  echo "expected 35 dry-run commands, got $command_count" >&2
  exit 1
}

tag_count="$(grep -o 'expA_laps_f[0-9]*_s[0-9]*' "$dry_run" | sort -u | wc -l | tr -d ' ')"
[ "$tag_count" -eq 35 ] || {
  echo "expected 35 unique LAPS tags, got $tag_count" >&2
  exit 1
}

awk '
  NF != 14 { exit 1 }
  $1 != "PATHS=8" || $2 != "END_MS=8" || $3 != "EXTRA_ARGS=-disable_trim" { exit 1 }
  $4 != "bash" || $6 != "laps" || $7 != "laps" { exit 1 }
  $8 !~ /^(0|2|4|6|8|10|12)$/ || $9 != "fat_tree_128_1os.topo" { exit 1 }
  $10 !~ /^(13|14|15|16|17)$/ || $11 !~ /m2m\.cm$/ || $12 != "flow" { exit 1 }
  $13 !~ /^expA_laps_f(0|2|4|6|8|10|12)_s(13|14|15|16|17)$/ { exit 1 }
  $14 !~ /data$/ { exit 1 }
' "$dry_run" || {
  echo "dry-run command matrix is not the fixed LAPS ExpA matrix" >&2
  exit 1
}

data_dir="$TMP/data"
mkdir -p "$data_dir"
touch "$data_dir/m2m.cm" "$data_dir/expA_laps_f0_s13.flow.txt"
stub="$TMP/run_lib_stub.sh"
cat >"$stub" <<'EOF'
#!/usr/bin/env bash
printf 'stub was invoked\n' >>"${STUB_MARK:?}"
EOF
chmod +x "$stub"

if DATA_DIR="$data_dir" RUN_LIB="$stub" STUB_MARK="$TMP/stub-ran" bash "$RUNNER" >"$TMP/real-run.txt" 2>&1; then
  echo "runner accepted an existing LAPS artifact" >&2
  exit 1
fi
[ ! -e "$TMP/stub-ran" ] || {
  echo "runner invoked run_lib after detecting a collision" >&2
  exit 1
}
grep -q 'collision' "$TMP/real-run.txt"

for suffix in idmap dat; do
  collision_data_dir="$TMP/data-$suffix"
  mkdir -p "$collision_data_dir"
  touch "$collision_data_dir/m2m.cm" "$collision_data_dir/expA_laps_f0_s13.$suffix"
  stub_marker="$TMP/$suffix-stub-ran"

  if DATA_DIR="$collision_data_dir" RUN_LIB="$stub" STUB_MARK="$stub_marker" bash "$RUNNER" \
    >"$TMP/$suffix-real-run.txt" 2>&1; then
    echo "runner accepted an existing LAPS .$suffix artifact" >&2
    exit 1
  fi
  [ ! -e "$stub_marker" ] || {
    echo "runner invoked run_lib after detecting an .$suffix collision" >&2
    exit 1
  }
  grep -q 'collision' "$TMP/$suffix-real-run.txt"
done

echo "ok: 35 LAPS dry-run cells and collision refusal"
