#!/usr/bin/env python3
"""Collect SHACL validation timings from configured timing.txt files.

The dashboard imports this module for timing rows and duration formatting.
Running it directly refreshes .timing-history.json without producing HTML.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import dashboard_config as dc

EVAL_DIR = Path(__file__).resolve().parent
EVAL_REPO_BLOB = "https://github.com/nataschake/relicap-ap-shacl-eval/blob/main"
TIMING_HISTORY_PATH = EVAL_DIR / ".timing-history.json"
CONFIG = dc.load_config()
CATALOG = dc.build_catalog(CONFIG)


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
    matches = CATALOG["by_filename"].get(f"{profile}.ttl") or []
    if not matches:
        return ""
    source = next((item for item in matches if item["family_id"] == family), matches[0])
    return dc.github_blob(source["repo"], source["shacl_subpath"])


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

    sources = sorted(CATALOG["sources"].values(), key=lambda source: source["id"])
    for source in sources:
        timing_path = source["result_dir"] / "timing.txt"
        if not timing_path.is_file():
            continue
        profile = Path(source["shacl_file"]).stem
        raw = parse_timing(timing_path)
        duration_raw = raw.get("duration_seconds")
        duration = float(duration_raw) if duration_raw else None
        http_status = raw.get("http_status") or raw.get("status", "")

        previous_key = source["id"] if source["id"] in previous_timings else profile
        previous = (
            previous_timings.get(previous_key, {})
            if isinstance(previous_timings.get(previous_key), dict) else {}
        )
        previous_duration_raw = previous.get("duration")
        previous_duration = float(previous_duration_raw) if previous_duration_raw not in (None, "") else None

        family = source["family_id"]
        rows.append(
            {
                "source_id": source["id"],
                "repository": source["repository_id"],
                "profile": profile,
                "family": family,
                "ontology_profile": source["profile_id"],
                "ontology_file": source["ontology_file"],
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
                "shape_href": dc.github_blob(source["repo"], source["shacl_subpath"]),
            }
        )

    def duration_value(row: dict[str, object]) -> float:
        value = row["duration"]
        if isinstance(value, (int, float)):
            return float(value)
        return 0.0

    rows.sort(key=lambda row: (row["duration"] is None, -duration_value(row), str(row["profile"])))
    return rows


def write_timing_history(rows: list[dict[str, object]]) -> None:
    history_payload = {
        str(row["source_id"]): {
            "duration": row["duration"],
            "http_status": row["http_status"],
            "finished_at": row["finished_at"],
        }
        for row in rows
    }
    TIMING_HISTORY_PATH.write_text(json.dumps(history_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    rows = collect_rows()
    write_timing_history(rows)
    print(f"Collected {len(rows)} timing records.")
    print(f"  History: {TIMING_HISTORY_PATH}")
    if rows and isinstance(rows[0]["duration"], (int, float)):
        print(f"  Slowest: {rows[0]['profile']} ({rows[0]['duration_disp']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
