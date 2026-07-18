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

if bash "$RUNNER" --replace-laps --unknown >"$TMP/invalid-args.txt" 2>&1; then
  echo "runner accepted an invalid replacement argument combination" >&2
  exit 1
fi
grep -q 'usage:' "$TMP/invalid-args.txt"

data_dir="$TMP/data"
mkdir -p "$data_dir"
touch "$data_dir/m2m.cm" "$data_dir/expA_laps_f0_s13.flow.txt"
stub_dir="$TMP/prism_eval/common"
mkdir -p "$stub_dir"
stub="$stub_dir/run_lib.sh"
cat >"$stub" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'stub was invoked\n' >>"${STUB_MARK:?}"
shared_idmap="$(cd "$(dirname "$0")/../.." && pwd)/idmap.txt"
printf 'generated idmap\n' >"$shared_idmap"
[ ! -e "$9/$8.idmap" ] || {
  echo "stale tagged idmap was not removed: $9/$8.idmap" >&2
  exit 88
}
cp "$shared_idmap" "$9/$8.idmap"
if [ "${STUB_WAIT_FOR_TERM:-0}" = 1 ]; then
  : "${STUB_READY:?}"
  : >"$STUB_READY"
  while :; do sleep 1; done
fi
exit "${STUB_EXIT_CODE:-0}"
EOF
chmod +x "$stub"

replacement_data_dir="$TMP/replacement-data"
replacement_figs_dir="$TMP/replacement-figs"
mkdir -p "$replacement_data_dir" "$replacement_figs_dir"
touch "$replacement_data_dir/m2m.cm"
for failed in 0 2 4 6 8 10 12; do
  for seed in 13 14 15 16 17; do
    tag="expA_laps_f${failed}_s${seed}"
    for suffix in flow.txt stdout idmap dat ascii.tmp; do
      printf 'stale LAPS %s\n' "$suffix" >"$replacement_data_dir/$tag.$suffix"
    done
  done
done
for stem in figA1dd_goodput_laps figA1dd_avg_fct_laps figA1dd_p99_fct_laps figA1dd_legend_laps; do
  for extension in pdf png; do
    printf 'stale LAPS figure %s.%s\n' "$stem" "$extension" >"$replacement_figs_dir/$stem.$extension"
  done
done
printf 'OPS fixture must survive\n' >"$replacement_data_dir/expA_ops_f0_s13.flow.txt"
printf 'original figure must survive\n' >"$replacement_figs_dir/figA1dd_goodput.pdf"
ops_before="$(cksum "$replacement_data_dir/expA_ops_f0_s13.flow.txt")"
original_fig_before="$(cksum "$replacement_figs_dir/figA1dd_goodput.pdf")"

replacement_dry_run="$TMP/replacement-dry-run.txt"
DATA_DIR="$replacement_data_dir" FIGS_DIR="$replacement_figs_dir" RUN_LIB="$stub" \
  STUB_MARK="$TMP/replacement-dry-stub-ran" bash "$RUNNER" --replace-laps --dry-run \
  >"$replacement_dry_run"
replacement_dry_count="$(grep -c '^PATHS=8 END_MS=8 EXTRA_ARGS=-disable_trim bash ' "$replacement_dry_run")"
[ "$replacement_dry_count" -eq 35 ] || {
  echo "expected 35 replacement dry-run commands, got $replacement_dry_count" >&2
  exit 1
}
replacement_dry_tags="$(grep -o 'expA_laps_f[0-9]*_s[0-9]*' "$replacement_dry_run" | sort -u | wc -l | tr -d ' ')"
[ "$replacement_dry_tags" -eq 35 ] || {
  echo "expected 35 replacement dry-run tags, got $replacement_dry_tags" >&2
  exit 1
}
replacement_target_count="$(grep -c '^LAPS replacement target: ' "$replacement_dry_run")"
[ "$replacement_target_count" -eq 183 ] || {
  echo "expected 183 explicitly enumerated replacement targets, got $replacement_target_count" >&2
  exit 1
}
[ "$(find "$replacement_data_dir" -name 'expA_laps_f*_s*' -type f | wc -l | tr -d ' ')" -eq 175 ] || {
  echo "replacement dry-run deleted a LAPS data artifact" >&2
  exit 1
}
[ "$(find "$replacement_figs_dir" -name '*_laps.*' -type f | wc -l | tr -d ' ')" -eq 8 ] || {
  echo "replacement dry-run deleted a LAPS overlay figure" >&2
  exit 1
}
[ "$ops_before" = "$(cksum "$replacement_data_dir/expA_ops_f0_s13.flow.txt")" ]
[ "$original_fig_before" = "$(cksum "$replacement_figs_dir/figA1dd_goodput.pdf")" ]

invalid_replace_root="$TMP/invalid-replace-idmap-root"
invalid_replace_stub_dir="$invalid_replace_root/prism_eval/common"
invalid_replace_data_dir="$TMP/invalid-replace-idmap-data"
invalid_replace_figs_dir="$TMP/invalid-replace-idmap-figs"
mkdir -p "$invalid_replace_stub_dir" "$invalid_replace_data_dir" "$invalid_replace_figs_dir"
cp "$stub" "$invalid_replace_stub_dir/run_lib.sh"
cp -a "$replacement_data_dir/." "$invalid_replace_data_dir/"
cp -a "$replacement_figs_dir/." "$invalid_replace_figs_dir/"
invalid_replace_data_before="$TMP/invalid-replace-data-before.cksum"
invalid_replace_figs_before="$TMP/invalid-replace-figs-before.cksum"
(cd "$invalid_replace_data_dir" && find . -name 'expA_laps_f*_s*' -type f -print0 | sort -z | xargs -0 cksum) >"$invalid_replace_data_before"
(cd "$invalid_replace_figs_dir" && find . -name '*_laps.*' -type f -print0 | sort -z | xargs -0 cksum) >"$invalid_replace_figs_before"
invalid_replace_shared_idmap="$invalid_replace_root/idmap.txt"
invalid_replace_target="$TMP/invalid-replace-idmap-target"
ln -s "$invalid_replace_target" "$invalid_replace_shared_idmap"
invalid_replace_marker="$TMP/invalid-replace-idmap-stub-ran"
if DATA_DIR="$invalid_replace_data_dir" FIGS_DIR="$invalid_replace_figs_dir" \
  RUN_LIB="$invalid_replace_stub_dir/run_lib.sh" STUB_MARK="$invalid_replace_marker" \
  bash "$RUNNER" --replace-laps >"$TMP/invalid-replace-idmap-run.txt" 2>&1; then
  echo "runner accepted a dangling shared-idmap symlink during LAPS replacement" >&2
  exit 1
fi
[ -L "$invalid_replace_shared_idmap" ] || {
  echo "runner removed the dangling shared-idmap symlink during LAPS replacement" >&2
  exit 1
}
[ ! -e "$invalid_replace_marker" ] || {
  echo "runner invoked run_lib with an invalid shared-idmap during LAPS replacement" >&2
  exit 1
}
(cd "$invalid_replace_data_dir" && find . -name 'expA_laps_f*_s*' -type f -print0 | sort -z | xargs -0 cksum) >"$TMP/invalid-replace-data-after.cksum"
(cd "$invalid_replace_figs_dir" && find . -name '*_laps.*' -type f -print0 | sort -z | xargs -0 cksum) >"$TMP/invalid-replace-figs-after.cksum"
cmp -s "$invalid_replace_data_before" "$TMP/invalid-replace-data-after.cksum" || {
  echo "runner deleted a LAPS data artifact before rejecting an invalid shared idmap" >&2
  exit 1
}
cmp -s "$invalid_replace_figs_before" "$TMP/invalid-replace-figs-after.cksum" || {
  echo "runner deleted a LAPS overlay before rejecting an invalid shared idmap" >&2
  exit 1
}

replacement_marker="$TMP/replacement-stub-ran"
DATA_DIR="$replacement_data_dir" FIGS_DIR="$replacement_figs_dir" RUN_LIB="$stub" \
  STUB_MARK="$replacement_marker" bash "$RUNNER" --replace-laps >"$TMP/replacement-run.txt"
[ "$(wc -l <"$replacement_marker" | tr -d ' ')" -eq 35 ] || {
  echo "expected 35 replacement stub runs" >&2
  exit 1
}
for failed in 0 2 4 6 8 10 12; do
  for seed in 13 14 15 16 17; do
    tag="expA_laps_f${failed}_s${seed}"
    for suffix in flow.txt stdout dat ascii.tmp; do
      [ ! -e "$replacement_data_dir/$tag.$suffix" ] || {
        echo "replacement retained stale LAPS artifact: $tag.$suffix" >&2
        exit 1
      }
    done
    [ -f "$replacement_data_dir/$tag.idmap" ] || {
      echo "replacement did not run LAPS cell: $tag" >&2
      exit 1
    }
  done
done
[ "$(find "$replacement_figs_dir" -name '*_laps.*' -type f | wc -l | tr -d ' ')" -eq 0 ] || {
  echo "replacement retained a stale LAPS overlay figure" >&2
  exit 1
}
[ "$ops_before" = "$(cksum "$replacement_data_dir/expA_ops_f0_s13.flow.txt")" ] || {
  echo "replacement modified an OPS artifact" >&2
  exit 1
}
[ "$original_fig_before" = "$(cksum "$replacement_figs_dir/figA1dd_goodput.pdf")" ] || {
  echo "replacement modified an original figure" >&2
  exit 1
}

if DATA_DIR="$data_dir" RUN_LIB="$stub" STUB_MARK="$TMP/stub-ran" bash "$RUNNER" >"$TMP/real-run.txt" 2>&1; then
  echo "runner accepted an existing LAPS artifact" >&2
  exit 1
fi
[ ! -e "$TMP/stub-ran" ] || {
  echo "runner invoked run_lib after detecting a collision" >&2
  exit 1
}
grep -q 'collision' "$TMP/real-run.txt"

for suffix in idmap dat stdout ascii.tmp; do
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

shared_data_dir="$TMP/shared-idmap-data"
mkdir -p "$shared_data_dir"
touch "$shared_data_dir/m2m.cm"
shared_idmap="$TMP/idmap.txt"
sentinel_idmap="$TMP/original-idmap.txt"
printf 'original shared idmap sentinel\n' >"$sentinel_idmap"
cp "$sentinel_idmap" "$shared_idmap"
shared_marker="$TMP/shared-idmap-stub-ran"

DATA_DIR="$shared_data_dir" RUN_LIB="$stub" STUB_MARK="$shared_marker" bash "$RUNNER"
cmp -s "$sentinel_idmap" "$shared_idmap" || {
  echo "runner did not restore the shared idmap sentinel" >&2
  exit 1
}
shared_runs="$(wc -l <"$shared_marker" | tr -d ' ')"
[ "$shared_runs" -eq 35 ] || {
  echo "expected 35 stubbed LAPS runs, got $shared_runs" >&2
  exit 1
}
shared_tagged_idmaps="$(find "$shared_data_dir" -name 'expA_laps_f*_s*.idmap' -type f | wc -l | tr -d ' ')"
[ "$shared_tagged_idmaps" -eq 35 ] || {
  echo "expected 35 tagged idmaps, got $shared_tagged_idmaps" >&2
  exit 1
}

failed_data_dir="$TMP/failed-idmap-data"
mkdir -p "$failed_data_dir"
touch "$failed_data_dir/m2m.cm"
cp "$sentinel_idmap" "$shared_idmap"
if DATA_DIR="$failed_data_dir" RUN_LIB="$stub" STUB_MARK="$TMP/failed-idmap-stub-ran" \
  STUB_EXIT_CODE=7 bash "$RUNNER" >"$TMP/failed-idmap-run.txt" 2>&1; then
  echo "runner accepted a failing run_lib stub" >&2
  exit 1
fi
cmp -s "$sentinel_idmap" "$shared_idmap" || {
  echo "runner did not restore shared idmap after a failing run" >&2
  exit 1
}

absent_root="$TMP/absent-idmap-root"
absent_stub_dir="$absent_root/prism_eval/common"
absent_data_dir="$TMP/absent-idmap-data"
mkdir -p "$absent_stub_dir" "$absent_data_dir"
touch "$absent_data_dir/m2m.cm"
cp "$stub" "$absent_stub_dir/run_lib.sh"
absent_shared_idmap="$absent_root/idmap.txt"
[ ! -e "$absent_shared_idmap" ] || {
  echo "absent shared-idmap fixture already exists" >&2
  exit 1
}
DATA_DIR="$absent_data_dir" RUN_LIB="$absent_stub_dir/run_lib.sh" STUB_MARK="$TMP/absent-idmap-stub-ran" \
  bash "$RUNNER"
[ ! -e "$absent_shared_idmap" ] || {
  echo "runner did not remove a generated shared idmap that was initially absent" >&2
  exit 1
}

dangling_root="$TMP/dangling-idmap-root"
dangling_stub_dir="$dangling_root/prism_eval/common"
dangling_data_dir="$TMP/dangling-idmap-data"
mkdir -p "$dangling_stub_dir" "$dangling_data_dir"
touch "$dangling_data_dir/m2m.cm"
cp "$stub" "$dangling_stub_dir/run_lib.sh"
dangling_shared_idmap="$dangling_root/idmap.txt"
dangling_target="$TMP/dangling-idmap-target"
ln -s "$dangling_target" "$dangling_shared_idmap"
if DATA_DIR="$dangling_data_dir" RUN_LIB="$dangling_stub_dir/run_lib.sh" \
  STUB_MARK="$TMP/dangling-idmap-stub-ran" bash "$RUNNER" >"$TMP/dangling-idmap-run.txt" 2>&1; then
  echo "runner accepted a dangling shared-idmap symlink" >&2
  exit 1
fi
[ -L "$dangling_shared_idmap" ] || {
  echo "runner removed the dangling shared-idmap symlink" >&2
  exit 1
}
[ ! -e "$dangling_target" ] || {
  echo "runner wrote through the dangling shared-idmap symlink" >&2
  exit 1
}
[ ! -e "$TMP/dangling-idmap-stub-ran" ] || {
  echo "runner invoked run_lib with a dangling shared-idmap symlink" >&2
  exit 1
}

term_root="$TMP/term-idmap-root"
term_stub_dir="$term_root/prism_eval/common"
term_data_dir="$TMP/term-idmap-data"
mkdir -p "$term_stub_dir" "$term_data_dir"
touch "$term_data_dir/m2m.cm"
cp "$stub" "$term_stub_dir/run_lib.sh"
term_shared_idmap="$term_root/idmap.txt"
cp "$sentinel_idmap" "$term_shared_idmap"
term_ready="$TMP/term-idmap-ready"
setsid env DATA_DIR="$term_data_dir" RUN_LIB="$term_stub_dir/run_lib.sh" \
  STUB_MARK="$TMP/term-idmap-stub-ran" STUB_WAIT_FOR_TERM=1 STUB_READY="$term_ready" \
  bash "$RUNNER" >"$TMP/term-idmap-run.txt" 2>&1 &
term_pid=$!
for _ in $(seq 1 50); do
  [ -e "$term_ready" ] && break
  sleep 0.1
done
[ -e "$term_ready" ] || {
  kill -TERM -- "-$term_pid" 2>/dev/null || true
  wait "$term_pid" 2>/dev/null || true
  echo "timed out waiting for the term-test stub" >&2
  exit 1
}
kill -TERM -- "-$term_pid"
if wait "$term_pid"; then
  echo "runner survived TERM" >&2
  exit 1
fi
cmp -s "$sentinel_idmap" "$term_shared_idmap" || {
  echo "runner did not restore shared idmap after TERM" >&2
  exit 1
}

echo "ok: 35 LAPS dry-run cells and collision refusal"
