#!/usr/bin/env python3
"""Collect all SHACL validation results from ap-relicap-eval/*/validation-report.ttl
into a single table (HTML + CSV).

For each sh:ValidationResult the following columns are produced:
  - sh:focusNode               -> link to the GraphDB resource viewer
  - rsx:shapesGraph
  - sh:resultPath
  - sh:sourceConstraint        -> link to the exact line in the SHACL file on GitHub
  - sh:sourceConstraintComponent
  - sh:resultSeverity
  - sh:resultMessage
  - sh:sourceShape             -> link to the exact line in the SHACL file on GitHub
  - sh:value                   (extra; present on most results)
  - Source profile             (extra; which SHACL file produced the result)

Usage:
    python3 collect-results.py
"""
from __future__ import annotations

import csv
import html
import re
import sys
from pathlib import Path
from urllib.parse import quote

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
EVAL_DIR = Path(__file__).resolve().parent
SHACL_DIR = (EVAL_DIR / ".." / "application-profiles-library" / "CGMES"
             / "CurrentRelease" / "SHACL").resolve()

GITHUB_BLOB = ("https://github.com/nikolatulechki/application-profiles-library"
               "/blob/main/CGMES/CurrentRelease/SHACL")

GRAPHDB_RESOURCE = "https://cim.ontotext.com/graphdb/resource"
GRAPHDB_REPO = "relicapgrid"

# Cap the number of results kept per constraint, where a constraint is keyed by
# (profile, sh:sourceShape, sh:sourceConstraintComponent) -- mirroring GraphDB's
# per-constraint validation cap. Set to None for no limit.
MAX_PER_CONSTRAINT = 100

# Prefixes used only to shorten URIs for display.
DISPLAY_PREFIXES = {
    "https://cim.ucaiug.io/ns#": "cim:",
    "https://cim.ucaiug.io/ns/eu#": "eu:",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#": "rdf:",
    "http://www.w3.org/2000/01/rdf-schema#": "rdfs:",
    "http://www.w3.org/ns/shacl#": "sh:",
    "http://www.w3.org/2001/XMLSchema#": "xsd:",
}


# ---------------------------------------------------------------------------
# Build an index mapping every full subject URI declared in each SHACL file to
# the line number where it is declared. Turtle subjects in these files always
# start at column 0, which makes this reliable.
# ---------------------------------------------------------------------------
def build_shacl_index() -> dict[str, dict[str, int]]:
    """Return {shacl_filename: {full_uri: line_number}}."""
    index: dict[str, dict[str, int]] = {}
    for ttl in sorted(SHACL_DIR.glob("*.ttl")):
        if ttl.name in {"validation-report.ttl", "relicap-val-report.ttl"}:
            continue
        prefixes: dict[str, str] = {}
        base: str | None = None
        uri_to_line: dict[str, int] = {}
        lines = ttl.read_text(encoding="utf-8").splitlines()

        # First pass: collect @prefix / @base directives.
        for line in lines:
            m = re.match(r'\s*@prefix\s+([\w.-]*):\s+<([^>]*)>', line)
            if m:
                prefixes[m.group(1)] = m.group(2)
                continue
            m = re.match(r'\s*@base\s+<([^>]*)>', line)
            if m:
                base = m.group(1)

        # Second pass: find subject declarations (token at column 0).
        for n, line in enumerate(lines, start=1):
            if not line or line[0] in " \t#@":
                continue
            token = line.split(None, 1)[0]
            full = resolve_term(token, prefixes, base)
            if full and full not in uri_to_line:
                uri_to_line[full] = n
        index[ttl.name] = uri_to_line
    return index


def resolve_term(token: str, prefixes: dict[str, str], base: str | None) -> str | None:
    """Resolve a Turtle term (``pfx:local`` or ``<iri>``) to a full URI string."""
    token = token.rstrip(";,.")
    if token.startswith("<") and token.endswith(">"):
        iri = token[1:-1]
        if iri.startswith("http://") or iri.startswith("https://") or iri.startswith("urn:"):
            return iri
        if base is not None:  # relative IRI, e.g. <#foo> or <>
            return base + iri
        return iri
    m = re.match(r'([\w.-]*):(\S*)$', token)
    if m and m.group(1) in prefixes:
        return prefixes[m.group(1)] + m.group(2)
    return None


# ---------------------------------------------------------------------------
# Parse a single validation-report.ttl into a list of result dicts.
# ---------------------------------------------------------------------------
RESULT_SPLIT = re.compile(r'\[\s*a\s+sh:ValidationResult\b')
PRED_LINE = re.compile(r'\s*((?:sh|rsx):\w+)\s+(.*)$')


def parse_report(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    chunks = RESULT_SPLIT.split(text)[1:]  # drop header before first result
    results: list[dict[str, str]] = []
    for chunk in chunks:
        d: dict[str, str] = {}
        for line in chunk.splitlines():
            # Stop scanning a chunk once the blank node closes; this keeps the
            # trailing shape definitions (in the final chunk) out of the result.
            stripped = line.lstrip()
            if stripped.startswith("]"):
                break
            m = PRED_LINE.match(line)
            if not m:
                continue
            key, val = m.group(1), m.group(2).rstrip()
            val = re.sub(r'\s*[;.]\s*$', '', val).strip()
            d.setdefault(key, val)
        if d:
            results.append(d)
    return results


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def shorten(term: str | None) -> str:
    if not term:
        return ""
    if term.startswith("<") and term.endswith(">"):
        iri = term[1:-1]
        for ns, pfx in DISPLAY_PREFIXES.items():
            if iri.startswith(ns):
                return pfx + iri[len(ns):]
        return iri
    return term


def strip_brackets(term: str | None) -> str | None:
    if term and term.startswith("<") and term.endswith(">"):
        return term[1:-1]
    return None


def strip_literal(term: str | None) -> str:
    if not term:
        return ""
    m = re.match(r'^"((?:[^"\\]|\\.)*)"', term)
    if m:
        return m.group(1).encode().decode("unicode_escape")
    return term


def graphdb_link(focus_term: str | None) -> tuple[str, str]:
    """Return (display, href) for a focus node."""
    iri = strip_brackets(focus_term)
    if iri is None:
        return (shorten(focus_term), "")
    href = (f"{GRAPHDB_RESOURCE}?uri={quote(iri, safe='')}"
            f"&repositoryId={GRAPHDB_REPO}&role=subject")
    return (iri, href)


def github_link(term: str | None, shacl_file: str,
                index: dict[str, dict[str, int]]) -> tuple[str, str]:
    """Return (display, href) for a shape/constraint, linking to its GitHub line."""
    iri = strip_brackets(term)
    if iri is None:
        return (shorten(term), "")
    # Prefer the SHACL file matching this report; fall back to any file.
    candidates = [shacl_file] + [f for f in index if f != shacl_file]
    for fname in candidates:
        line = index.get(fname, {}).get(iri)
        if line is not None:
            return (shorten(term), f"{GITHUB_BLOB}/{fname}#L{line}")
    return (shorten(term), "")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
COLUMNS = [
    "Profile",
    "sh:focusNode",
    "rsx:shapesGraph",
    "sh:resultPath",
    "sh:sourceConstraint",
    "sh:sourceConstraintComponent",
    "sh:resultSeverity",
    "sh:resultMessage",
    "sh:sourceShape",
    "sh:value",
]


def main() -> int:
    index = build_shacl_index()

    report_dirs = sorted(p for p in EVAL_DIR.iterdir()
                         if p.is_dir() and (p / "validation-report.ttl").exists())

    rows: list[dict] = []
    for d in report_dirs:
        profile = d.name
        shacl_file = f"{profile}.ttl"
        per_constraint: dict[tuple[str, str], int] = {}
        for r in parse_report(d / "validation-report.ttl"):
            if MAX_PER_CONSTRAINT is not None:
                key = (r.get("sh:sourceShape", ""), r.get("sh:sourceConstraintComponent", ""))
                per_constraint[key] = per_constraint.get(key, 0) + 1
                if per_constraint[key] > MAX_PER_CONSTRAINT:
                    continue
            focus_disp, focus_href = graphdb_link(r.get("sh:focusNode"))
            sc_disp, sc_href = github_link(r.get("sh:sourceConstraint"), shacl_file, index)
            ss_disp, ss_href = github_link(r.get("sh:sourceShape"), shacl_file, index)
            rows.append({
                "profile": profile,
                "focus_disp": focus_disp, "focus_href": focus_href,
                "shapes_graph": shorten(r.get("rsx:shapesGraph")),
                "result_path": shorten(r.get("sh:resultPath")),
                "sc_disp": sc_disp, "sc_href": sc_href,
                "scc": shorten(r.get("sh:sourceConstraintComponent")),
                "severity": shorten(r.get("sh:resultSeverity")),
                "message": strip_literal(r.get("sh:resultMessage")),
                "ss_disp": ss_disp, "ss_href": ss_href,
                "value": shorten(r.get("sh:value")),
            })

    write_csv(rows, EVAL_DIR / "validation-results.csv")
    write_html(rows, report_dirs, EVAL_DIR / "validation-results.html")

    print(f"Parsed {len(report_dirs)} reports, {len(rows)} validation results.")
    print(f"  CSV : {EVAL_DIR / 'validation-results.csv'}")
    print(f"  HTML: {EVAL_DIR / 'validation-results.html'}")
    return 0


def write_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS + ["focusNode URL", "sourceConstraint URL", "sourceShape URL"])
        for r in rows:
            w.writerow([
                r["profile"], r["focus_disp"], r["shapes_graph"], r["result_path"],
                r["sc_disp"], r["scc"], r["severity"], r["message"], r["ss_disp"],
                r["value"], r["focus_href"], r["sc_href"], r["ss_href"],
            ])


def write_html(rows: list[dict], report_dirs: list[Path], path: Path) -> None:
    def cell(text: str) -> str:
        return html.escape(text)

    def link_cell(disp: str, href: str) -> str:
        if href:
            return f'<a href="{html.escape(href)}" target="_blank" rel="noopener">{html.escape(disp)}</a>'
        return html.escape(disp)

    counts = {}
    for r in rows:
        counts[r["profile"]] = counts.get(r["profile"], 0) + 1

    summary_rows = "".join(
        f"<tr><td>{cell(p)}</td><td class='num'>{counts.get(p, 0)}</td></tr>"
        for p in sorted(counts)
    )

    body_rows = []
    for r in rows:
        body_rows.append(
            "<tr>"
            f"<td>{cell(r['profile'])}</td>"
            f"<td>{link_cell(r['focus_disp'], r['focus_href'])}</td>"
            f"<td>{cell(r['shapes_graph'])}</td>"
            f"<td>{cell(r['result_path'])}</td>"
            f"<td>{link_cell(r['sc_disp'], r['sc_href'])}</td>"
            f"<td>{cell(r['scc'])}</td>"
            f"<td>{cell(r['severity'])}</td>"
            f"<td class='msg'>{cell(r['message'])}</td>"
            f"<td>{link_cell(r['ss_disp'], r['ss_href'])}</td>"
            f"<td>{cell(r['value'])}</td>"
            "</tr>"
        )

    header_cells = "".join(f"<th>{cell(c)}</th>" for c in COLUMNS)

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>RELICAP SHACL validation results</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; margin: 1.5rem; color: #1b1b1b; }}
  h1 {{ font-size: 1.4rem; }}
  .meta {{ color: #555; margin-bottom: 1rem; }}
  #filter {{ padding: .4rem .6rem; width: 22rem; font-size: .95rem; margin: .3rem 0 1rem; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .82rem; }}
  th, td {{ border: 1px solid #ddd; padding: .35rem .5rem; vertical-align: top; text-align: left; }}
  thead th {{ position: sticky; top: 0; background: #f4f4f4; z-index: 2; }}
  tbody tr:nth-child(even) {{ background: #fafafa; }}
  td.msg {{ max-width: 32rem; }}
  td.num {{ text-align: right; }}
  a {{ color: #0b5fff; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  details {{ margin-bottom: 1.2rem; }}
  summary {{ cursor: pointer; font-weight: 600; }}
  .summary-table {{ width: auto; margin-top: .5rem; }}
</style>
</head>
<body>
<h1>RELICAP SHACL validation results</h1>
<div class="meta">{len(rows)} validation results from {len(report_dirs)} profiles.
Focus nodes link to the GraphDB <code>{GRAPHDB_REPO}</code> resource viewer;
source shapes/constraints link to the exact line in the SHACL file on GitHub.</div>

<details>
  <summary>Per-profile result counts</summary>
  <table class="summary-table">
    <thead><tr><th>Profile</th><th>Results</th></tr></thead>
    <tbody>{summary_rows}</tbody>
  </table>
</details>

<input id="filter" type="text" placeholder="Filter rows (substring match)..." oninput="filterRows(this.value)">

<table id="results">
  <thead><tr>{header_cells}</tr></thead>
  <tbody>
    {''.join(body_rows)}
  </tbody>
</table>

<script>
function filterRows(q) {{
  q = q.toLowerCase();
  const rows = document.querySelectorAll('#results tbody tr');
  for (const row of rows) {{
    row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
  }}
}}
</script>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
