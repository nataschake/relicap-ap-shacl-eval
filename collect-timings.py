#!/usr/bin/env python3
"""Collect SHACL validation timings from */timing.txt into a browsable HTML table.

Each run reads the current timing files, compares them with the previous run
stored in .timing-history.json, and writes timing-results.html.
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
EVAL_REPO_BLOB = "https://github.com/nataschake/relicap-ap-shacl-eval/blob/main"
SHAPES_REPO_BLOB = "https://github.com/entsoe/application-profiles-library/blob/main"
TIMING_HISTORY_PATH = EVAL_DIR / ".timing-history.json"


def parse_timing(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def infer_family(profile: str) -> str:
    if profile.startswith(("61970-", "61968-")):
        return "CGMES"
    return "NCP"


def shape_href(profile: str, family: str) -> str:
    shape_dir = "CGMES/SHACL" if family == "CGMES" else "NCP/SHACL"
    return f"{SHAPES_REPO_BLOB}/{shape_dir}/{profile}.ttl"


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds >= 3600:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours}h {minutes}m {secs:.1f}s"
    if seconds >= 60:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.1f}s"
    return f"{seconds:.3f}s"


def load_previous_timings(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def collect_rows() -> list[dict[str, object]]:
    previous_timings = load_previous_timings(TIMING_HISTORY_PATH)
    rows: list[dict[str, object]] = []

    timing_paths = sorted(path for path in EVAL_DIR.glob("*/timing.txt") if path.is_file())
    for timing_path in timing_paths:
        profile = timing_path.parent.name
        raw = parse_timing(timing_path)
        duration_raw = raw.get("duration_seconds")
        duration = float(duration_raw) if duration_raw else None
        http_status = raw.get("http_status") or raw.get("status", "")

        previous = previous_timings.get(profile, {}) if isinstance(previous_timings.get(profile), dict) else {}
        previous_duration_raw = previous.get("duration")
        previous_duration = float(previous_duration_raw) if previous_duration_raw not in (None, "") else None

        family = infer_family(profile)
        rows.append(
            {
                "profile": profile,
                "family": family,
                "duration": duration,
                "duration_disp": format_duration(duration),
                "previous_duration": previous_duration,
                "previous_duration_disp": format_duration(previous_duration),
                "http_status": http_status,
                "finished_at": raw.get("finished_at") or raw.get("skipped_at", ""),
                "reason": raw.get("reason", ""),
                "timing_href": f"{EVAL_REPO_BLOB}/{profile}/timing.txt",
                "report_href": (
                    f"{EVAL_REPO_BLOB}/{profile}/validation-report.ttl"
                    if (timing_path.parent / "validation-report.ttl").exists()
                    else ""
                ),
                "shape_href": shape_href(profile, family),
            }
        )

    def duration_value(row: dict[str, object]) -> float:
        value = row["duration"]
        if isinstance(value, (int, float)):
            return float(value)
        return 0.0

    rows.sort(key=lambda row: (row["duration"] is None, -duration_value(row), str(row["profile"])))
    return rows


def write_html(rows: list[dict[str, object]], path: Path) -> None:
    def brk(text: str) -> str:
        return re.sub(r"(?<=[/:#._?=-])(?!$)", "<wbr>", html.escape(text))

    def cell(text: str) -> str:
        return html.escape(text)

    def link_cell(label: str, href: str) -> str:
        if href:
            return (f'<a href="{html.escape(href)}" target="_blank" '
                    f'rel="noopener">{html.escape(label)}</a>')
        return cell(label)

    def profile_cell(profile: str, href: str) -> str:
        if href:
            return (f'<a href="{html.escape(href)}" target="_blank" '
                    f'rel="noopener">{brk(profile)}</a>')
        return brk(profile)

    body_rows: list[str] = []
    for rank, row in enumerate(rows, start=1):
        duration = row["duration"]
        current_classes = ["num", "dur"]
        http_classes = ["num"]
        if row["http_status"] not in ("", "200"):
            current_classes.append("bad")
            http_classes.append("bad")
        elif isinstance(duration, (int, float)) and duration >= 60:
            current_classes.append("slow")
            http_classes.append("slow")

        notes = str(row.get("reason", ""))
        if row["http_status"] == "000":
            notes = notes or "Request timed out (HTTP 000)"

        body_rows.append(
            "<tr>"
            f"<td class='num'>{rank}</td>"
            f"<td>{cell(str(row['family']))}</td>"
            f"<td>{profile_cell(str(row['profile']), str(row['shape_href']))}</td>"
            f"<td class='num dur'>{cell(str(row['previous_duration_disp']))}</td>"
            f"<td class=\"{' '.join(current_classes)}\">{cell(str(row['duration_disp']))}</td>"
            f"<td class=\"{' '.join(http_classes)}\">{cell(str(row['http_status']))}</td>"
            f"<td>{cell(str(row['finished_at']))}</td>"
            f"<td>{link_cell('timing', str(row['timing_href']))}</td>"
            f"<td>{link_cell('report', str(row['report_href'])) if row['report_href'] else '—'}</td>"
            f"<td class='notes'>{cell(notes)}</td>"
            "</tr>"
        )

    history_payload = {
        str(row["profile"]): {
            "duration": row["duration"],
            "http_status": row["http_status"],
            "finished_at": row["finished_at"],
        }
        for row in rows
    }
    TIMING_HISTORY_PATH.write_text(json.dumps(history_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    timed = [row for row in rows if row["duration"] is not None]
    total_seconds = sum(float(row["duration"]) for row in timed if isinstance(row["duration"], (int, float)))
    avg_seconds = total_seconds / len(timed) if timed else 0.0
    failed = [row for row in rows if row["http_status"] not in ("", "200")]
    skipped = [row for row in rows if row["duration"] is None]

    repo_url = EVAL_REPO_BLOB.rsplit("/blob/", 1)[0]
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ReliCapGrid SHACL validation timings</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; margin: 1.5rem; color: #1b1b1b; }}
  h1 {{ font-size: 1.4rem; }}
  .meta {{ color: #555; margin-bottom: 1rem; line-height: 1.5; }}
  .stats {{ display: flex; flex-wrap: wrap; gap: 1rem 2rem; margin: 1rem 0; }}
  .stat {{ min-width: 10rem; }}
  .stat strong {{ display: block; font-size: 1.1rem; }}
  #filter {{ padding: .4rem .6rem; width: 22rem; font-size: .95rem; margin: .3rem 0 1rem; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .82rem; }}
  th, td {{ border: 1px solid #ddd; padding: .35rem .5rem; vertical-align: top; text-align: left; }}
  thead th {{ position: sticky; top: 0; background: #f4f4f4; z-index: 2; }}
  tbody tr:nth-child(even) {{ background: #fafafa; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.dur {{ white-space: nowrap; }}
  td.notes {{ max-width: 18rem; color: #666; }}
  td.bad {{ color: #b00020; font-weight: 600; }}
  td.slow {{ color: #8a4b00; }}
  a {{ color: #0b5fff; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<h1>ReliCapGrid SHACL validation timings</h1>
<div class="meta">
  {len(rows)} profiles sorted by decreasing validation time &middot;
  <a href="{repo_url}" target="_blank" rel="noopener">repository on GitHub</a> &middot;
  <a href="validation-results.html">validation results table</a> &middot;
  previous vs current timing comparison
</div>

<div class="stats">
  <div class="stat"><span>Profiles timed</span><strong>{len(timed)}</strong></div>
  <div class="stat"><span>Total wall time</span><strong>{format_duration(total_seconds)}</strong></div>
  <div class="stat"><span>Average per profile</span><strong>{format_duration(avg_seconds)}</strong></div>
  <div class="stat"><span>Slowest</span><strong>{format_duration(float(timed[0]['duration']) if timed and isinstance(timed[0]['duration'], (int, float)) else None)}</strong></div>
  <div class="stat"><span>Non-200 HTTP</span><strong>{len(failed)}</strong></div>
  <div class="stat"><span>Skipped / no duration</span><strong>{len(skipped)}</strong></div>
</div>

<input id="filter" type="text" placeholder="Filter rows (substring match)..." oninput="filterRows(this.value)">

<table id="results">
  <thead>
    <tr>
      <th>#</th>
      <th>Family</th>
      <th>Profile</th>
      <th>Current</th>
      <th>Previous</th>
      <th>HTTP</th>
      <th>Finished</th>
      <th>Timing</th>
      <th>Report</th>
      <th>Notes</th>
    </tr>
  </thead>
  <tbody>
    {''.join(body_rows)}
  </tbody>
</table>

<script>
function filterRows(q) {{
  q = q.toLowerCase();
  for (const row of document.querySelectorAll('#results tbody tr')) {{
    row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
  }}
}}
</script>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")


def main() -> int:
    rows = collect_rows()
    out = EVAL_DIR / "timing-results.html"
    write_html(rows, out)
    print(f"Collected {len(rows)} timing records.")
    print(f"  HTML: {out}")
    if rows and isinstance(rows[0]["duration"], (int, float)):
        print(f"  Slowest: {rows[0]['profile']} ({rows[0]['duration_disp']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
