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
import re
import sys
from pathlib import Path
from urllib.parse import quote

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
EVAL_DIR = Path(__file__).resolve().parent
APL_DIR = (EVAL_DIR / ".." / "application-profiles-library").resolve()

GITHUB_REPO_BLOB = ("https://github.com/nataschake/application-profiles-library"
                    "/blob/main")

# SHACL source folders (repo-relative), each tagged with a profile family for
# the "Family" column. The order also sets link-resolution preference.
SHACL_SOURCES = [
    ("CGMES", "CGMES/CurrentRelease/SHACL"),
    ("CGMES", "CGMES/SHACL"),
    ("NCP", "NCP/CurrentRelease/SHACL"),
    ("NCP", "NCP/SHACL"),
]

# This repository on GitHub, used to link each row to its source report.
EVAL_REPO_BLOB = "https://github.com/nataschake/relicap-ap-shacl-eval/blob/main"

GRAPHDB_RESOURCE = "https://cim.ontotext.com/graphdb/resource"
GRAPHDB_REPO = "relicapgrid"

# Snapshot timestamp of the ReliCapGrid ENTSO-E data that was validated (not
# the latest upstream version).
DATA_TIMESTAMP = "2025-06-15T22:30:00Z"

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
def build_shacl_index() -> dict[str, dict]:
    """Return {shacl_filename: {"family", "subpath", "lines": {uri: line}}}."""
    index: dict[str, dict] = {}
    for family, subpath in SHACL_SOURCES:
        for ttl in sorted((APL_DIR / subpath).glob("*.ttl")):
            if ttl.name in {"validation-report.ttl", "relicap-val-report.ttl"}:
                continue
            if ttl.name in index:
                continue
            prefixes: dict[str, str] = {}
            base: str | None = None
            uri_to_line: dict[str, int] = {}
            lines = ttl.read_text(encoding="utf-8").splitlines()

            # First pass: collect @prefix/@base and SPARQL PREFIX/BASE directives.
            for line in lines:
                m = re.match(r'\s*(?:@prefix|PREFIX)\s+([\w.-]*):\s+<([^>]*)>', line, re.I)
                if m:
                    prefixes[m.group(1)] = m.group(2)
                    continue
                m = re.match(r'\s*(?:@base|BASE)\s+<([^>]*)>', line, re.I)
                if m:
                    base = m.group(1)

            # Second pass: find subject declarations (token at column 0).
            for n, line in enumerate(lines, start=1):
                if not line or line[0] in " \t#@":
                    continue
                if line.upper().startswith("PREFIX ") or line.upper().startswith("BASE "):
                    continue
                token = line.split(None, 1)[0]
                full = resolve_term(token, prefixes, base)
                if full and full not in uri_to_line:
                    uri_to_line[full] = n
            index[ttl.name] = {"family": family, "subpath": subpath,
                               "lines": uri_to_line}
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
    text = path.read_text(encoding="utf-8", errors="replace")
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
                index: dict[str, dict]) -> tuple[str, str]:
    """Return (display, href) for a shape/constraint, linking to its GitHub line."""
    iri = strip_brackets(term)
    if iri is None:
        return (shorten(term), "")
    # Prefer the SHACL file matching this report; fall back to any file.
    candidates = [shacl_file] + [f for f in index if f != shacl_file]
    for fname in candidates:
        entry = index.get(fname)
        if entry and iri in entry["lines"]:
            line = entry["lines"][iri]
            return (shorten(term),
                    f"{GITHUB_REPO_BLOB}/{entry['subpath']}/{fname}#L{line}")
    return (shorten(term), "")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
COLUMNS = [
    "Family",
    "Profile",
    "Report",
    "sh:focusNode",
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
        family = index.get(shacl_file, {}).get("family", "")
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
                "family": family,
                "profile": profile,
                "report_href": f"{EVAL_REPO_BLOB}/{profile}/validation-report.ttl",
                "focus_disp": focus_disp, "focus_href": focus_href,
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

    from build_dashboard import build as build_dashboard
    dash_index = build_dashboard()

    print(f"Parsed {len(report_dirs)} reports, {len(rows)} validation results.")
    print(f"  CSV : {EVAL_DIR / 'validation-results.csv'}")
    print(f"  HTML: {EVAL_DIR / 'validation-results.html'}")
    print(f"  Dashboard: {dash_index}")
    return 0


def write_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS + ["focusNode URL", "sourceConstraint URL", "sourceShape URL"])
        for r in rows:
            w.writerow([
                r["family"], r["profile"], r["report_href"], r["focus_disp"],
                r["result_path"], r["sc_disp"], r["scc"], r["severity"], r["message"],
                r["ss_disp"], r["value"], r["focus_href"], r["sc_href"], r["ss_href"],
            ])


def write_html(rows: list[dict], report_dirs: list[Path], path: Path) -> None:
    """Stub page: the browsable UI lives in the dashboard (index.html)."""
    repo_url = EVAL_REPO_BLOB.rsplit("/blob/", 1)[0]
    cap_note = (
        f"CSV export is capped at {MAX_PER_CONSTRAINT} results per constraint "
        "(per <code>sh:sourceShape</code> + <code>sh:sourceConstraintComponent</code>)."
        if MAX_PER_CONSTRAINT is not None else "No per-constraint cap applied to the CSV export."
    )
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="0; url=index.html">
<title>ReliCapGrid ENTSO-E SHACL validation results</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; margin: 1.5rem; color: #1b1b1b; }}
  a {{ color: #0b5fff; }}
  .meta {{ color: #555; line-height: 1.5; }}
</style>
</head>
<body>
<h1>Validation results moved to the dashboard</h1>
<p class="meta">{len(rows)} validation results from {len(report_dirs)} profiles
are summarised on the <a href="index.html">dashboard</a>
(focus-node lists open from the count links).
<a href="{repo_url}">repository on GitHub</a>.<br>
{cap_note}<br>
<strong>Note:</strong> the ReliCapGrid ENTSO-E data is a snapshot
(<time datetime="{DATA_TIMESTAMP}">{DATA_TIMESTAMP}</time>) and is not the
latest upstream version.</p>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
