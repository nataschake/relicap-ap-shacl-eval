#!/usr/bin/env bash
set -euo pipefail

SHACL_DIR="$(cd "$(dirname "$0")/../application-profiles-library/CGMES/CurrentRelease/SHACL" && pwd)"
OUT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_URL="http://localhost:7200/rest/repositories/relicapgrid/validate/file"
LOG="$OUT_DIR/batch.log"

mkdir -p "$OUT_DIR"
: > "$LOG"

done_count=0
fail_count=0

for file in "$SHACL_DIR"/*.ttl; do
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

echo "[$(date -Iseconds)] BATCH COMPLETE: $done_count succeeded, $fail_count failed" | tee -a "$LOG"
