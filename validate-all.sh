#!/usr/bin/env bash
set -euo pipefail

APL="$(cd "$(dirname "$0")/../application-profiles-library" && pwd)"
echo "Application Profiles Library: $APL"
SHACL_DIRS=(
  "$APL/CGMES/SHACL"
  "$APL/NCP/SHACL"
)
echo "SHACL Directories: ${SHACL_DIRS[*]}"
OUT_DIR="$(cd "$(dirname "$0")" && pwd)"
#REPO_URL="https://cim.ontotext.com/graphdb/rest/repositories/relicapgrid/validate/file"
REPO_URL="http://localhost:7200/rest/repositories/relicapgrid/validate/file"

LOG="$OUT_DIR/batch.log"

mkdir -p "$OUT_DIR"
: > "$LOG"

done_count=0
fail_count=0

for dir in "${SHACL_DIRS[@]}"; do
  for file in "$dir"/*.ttl; do
    base=$(basename "$file")
    [[ "$base" == "validation-report.ttl" || "$base" == "relicap-val-report.ttl" ]] && continue

    name="${base%.ttl}"
    out_subdir="$OUT_DIR/$name"
    mkdir -p "$out_subdir"

    echo "[$(date -Iseconds)] START $name" | tee -a "$LOG"
    start=$(python3 -c 'import time; print(time.perf_counter())')
    http_code=$(curl -s -X POST --header 'Accept: text/turtle' \
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
      echo "[$(date -Iseconds)] FAIL $name (HTTP $http_code, ${duration}s)" | tee -a "$LOG"
      ((fail_count++)) || true
    else
      echo "[$(date -Iseconds)] DONE $name (${duration}s)" | tee -a "$LOG"
      ((done_count++)) || true
    fi
  done
done

echo "[$(date -Iseconds)] BATCH COMPLETE: $done_count succeeded, $fail_count failed" | tee -a "$LOG"
echo "[$(date -Iseconds)] GENERATING TIMING SUMMARY" | tee -a "$LOG"
python3 "$OUT_DIR/collect-timings.py" | tee -a "$LOG"
echo "[$(date -Iseconds)] GENERATING VALIDATION DASHBOARD" | tee -a "$LOG"
python3 "$OUT_DIR/collect-results.py" | tee -a "$LOG"
