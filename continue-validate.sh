#!/usr/bin/env bash
set -euo pipefail

SKIP_LIST=(
  "61970-456_Topology-AP-Con-Complex-NotSolvedMAS-SHACL"
  "61970-600-2_IdentifiedObjectCommon_AP-Con-Complex-SHACL"
)

SHACL_DIR="$(cd "$(dirname "$0")/../application-profiles-library/CGMES/CurrentRelease/SHACL" && pwd)"
OUT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_URL="http://localhost:7200/rest/repositories/relicapgrid/validate/file"
LOG="$OUT_DIR/batch.log"

is_skipped() {
  local name="$1"
  for s in "${SKIP_LIST[@]}"; do
    [[ "$name" == "$s" ]] && return 0
  done
  return 1
}

mark_skip() {
  local name="$1"
  mkdir -p "$OUT_DIR/$name"
  cat > "$OUT_DIR/$name/timing.txt" <<EOF
file: ${name}.ttl
repository: relicapgrid
status: skipped
reason: validation hung or timed out; skipped per user request
skipped_at: $(date -Iseconds)
EOF
  echo "[$(date -Iseconds)] SKIP $name (user request)" >> "$LOG"
}

done_count=0
fail_count=0
skip_count=0

for skip in "${SKIP_LIST[@]}"; do
  if [[ ! -f "$OUT_DIR/$skip/timing.txt" ]]; then
    mark_skip "$skip"
    ((skip_count++)) || true
  fi
done

for file in "$SHACL_DIR"/*.ttl; do
  base=$(basename "$file")
  name="${base%.ttl}"
  [[ "$base" == "validation-report.ttl" || "$base" == "relicap-val-report.ttl" ]] && continue
  is_skipped "$name" && continue
  [[ -f "$OUT_DIR/$name/timing.txt" ]] && continue

  out_subdir="$OUT_DIR/$name"
  mkdir -p "$out_subdir"

  echo "[$(date -Iseconds)] START $name" >> "$LOG"
  start=$(python3 -c 'import time; print(time.perf_counter())')
  http_code=$(curl -s --max-time 300 -X POST --header 'Accept: text/turtle' \
    "$REPO_URL" \
    -F "file=@$file;type=text/turtle" \
    -o "$out_subdir/validation-report.ttl" \
    -w "%{http_code}")
  end=$(python3 -c 'import time; print(time.perf_counter())')
  duration=$(python3 -c "print(f'{$end - $start:.3f}')")

  cat > "$out_subdir/timing.txt" <<EOF
file: $base
repository: relicapgrid
http_status: $http_code
duration_seconds: $duration
finished_at: $(date -Iseconds)
EOF

  if [[ "$http_code" != "200" ]]; then
    echo "[$(date -Iseconds)] FAIL $name (HTTP $http_code, ${duration}s)" >> "$LOG"
    ((fail_count++)) || true
  else
    echo "[$(date -Iseconds)] DONE $name (${duration}s)" >> "$LOG"
    ((done_count++)) || true
  fi
done

echo "[$(date -Iseconds)] BATCH COMPLETE: $done_count succeeded, $fail_count failed, $skip_count newly skipped" >> "$LOG"
