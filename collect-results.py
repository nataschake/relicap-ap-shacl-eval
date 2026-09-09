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
import json
import re
import sys
import time
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import dashboard_config as dc

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
EVAL_DIR = Path(__file__).resolve().parent
CONFIG = dc.load_config()
CATALOG = dc.build_catalog(CONFIG)
_PRIMARY_REPO = CATALOG["repositories"][0]
APL_DIR = _PRIMARY_REPO["checkout_path"]  # Backwards-compatible public constant.
GITHUB_REPO_BLOB = (
    f"https://github.com/{_PRIMARY_REPO['github_repository']}/blob/"
    f"{_PRIMARY_REPO.get('github_ref') or 'main'}"
)
SHACL_SOURCES = [
    (family["id"], subpath)
    for family in _PRIMARY_REPO["families_index"]
    for subpath in family.get("shacl_dirs") or []
]

# This repository on GitHub, used to link each row to its source report.
EVAL_REPO_BLOB = "https://github.com/nataschake/relicap-ap-shacl-eval/blob/main"

_DATA_CONFIG = CONFIG.get("data") or {}
GRAPHDB_RESOURCE = _DATA_CONFIG.get("graphdb_resource") or "http://localhost:7200/resource"
GRAPHDB_REPO = _DATA_CONFIG.get("graphdb_repository") or "relicapgrid"
GRAPHDB_SPARQL = (
    _DATA_CONFIG.get("graphdb_sparql")
    or f"http://localhost:7200/repositories/{GRAPHDB_REPO}"
)
GDB_LOOKUP_CHUNK = 100

# Snapshot timestamp of the ReliCapGrid ENTSO-E data that was validated (not
# the latest upstream version).
DATA_TIMESTAMP = _DATA_CONFIG.get("timestamp") or ""

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
    """Return a source-aware subject index, with filename aliases when unique."""
    index: dict[str, dict] = {}
    for source in CATALOG["sources"].values():
        ttl = source["shacl_path"]
        prefixes: dict[str, str] = {}
        base: str | None = None
        uri_to_line: dict[str, int] = {}
        lines = ttl.read_text(encoding="utf-8").splitlines()
        for line in lines:
            m = re.match(r'\s*(?:@prefix|PREFIX)\s+([\w.-]*):\s+<([^>]*)>', line, re.I)
            if m:
                prefixes[m.group(1)] = m.group(2)
                continue
            m = re.match(r'\s*(?:@base|BASE)\s+<([^>]*)>', line, re.I)
            if m:
                base = m.group(1)
        for n, line in enumerate(lines, start=1):
            if not line or line[0] in " \t#@":
                continue
            if line.upper().startswith(("PREFIX ", "BASE ")):
                continue
            token = line.split(None, 1)[0]
            full = resolve_term(token, prefixes, base)
            if full and full not in uri_to_line:
                uri_to_line[full] = n
        entry = {
            **source,
            "family": source["family_id"],
            "subpath": source["shacl_subpath"].rsplit("/", 1)[0],
            "blob_base": (
                f"https://github.com/{source['repo']['github_repository']}/blob/"
                f"{source['repo'].get('github_ref') or 'main'}"
            ),
            "lines": uri_to_line,
        }
        index[source["id"]] = entry
        if len(CATALOG["by_filename"].get(ttl.name, [])) == 1:
            index[ttl.name] = entry
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
    href = (f"{GRAPHDB_RESOURCE}?uri={quote(iri, safe=':/')}"
            f"&repositoryId={GRAPHDB_REPO}&role=all")
    return (iri, href)


def _sparql_iri(iri: str) -> str:
    return "<" + iri.replace("\\", "\\\\").replace(">", "\\>") + ">"


def iris_present_in_graphdb(iris: set[str], chunk: int = GDB_LOOKUP_CHUNK) -> set[str]:
    """Return the subset of IRIs that appear in relicapgrid as s/p/o/graph."""
    found: set[str] = set()
    ordered = [i for i in iris if i and not i.startswith("_:")]
    if not ordered:
        return found
    total = (len(ordered) + chunk - 1) // chunk
    for n, start in enumerate(range(0, len(ordered), chunk), start=1):
        batch = ordered[start:start + chunk]
        values = " ".join(_sparql_iri(u) for u in batch)
        query = (
            "SELECT DISTINCT ?iri WHERE {\n"
            f"  VALUES ?iri {{ {values} }}\n"
            "  FILTER(\n"
            "    EXISTS { ?iri ?p ?o }\n"
            "    || EXISTS { ?s ?iri ?o }\n"
            "    || EXISTS { ?s ?p ?iri }\n"
            "    || EXISTS { GRAPH ?iri { ?s ?p ?o } }\n"
            "  )\n"
            "}"
        )
        req = Request(
            GRAPHDB_SPARQL,
            data=urlencode({"query": query}).encode(),
            headers={
                "Accept": "application/sparql-results+json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        payload = None
        for attempt in range(2):
            try:
                with urlopen(req, timeout=120) as resp:
                    payload = json.loads(resp.read().decode())
                break
            except (URLError, HTTPError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                if isinstance(exc, URLError) and isinstance(exc.reason, ConnectionRefusedError):
                    print(f"GraphDB presence lookup batch {n}/{total} failed: {exc}", file=sys.stderr)
                    print("GraphDB endpoint is unavailable; skipping remaining presence batches.", file=sys.stderr)
                    return found
                if attempt == 0:
                    print(
                        f"GraphDB presence lookup batch {n}/{total} failed: {exc}; retrying",
                        file=sys.stderr,
                    )
                    time.sleep(0.25)
                else:
                    print(f"GraphDB presence lookup batch {n}/{total} failed: {exc}", file=sys.stderr)
        if payload is None:
            if len(batch) > 1:
                split_size = max(1, len(batch) // 2)
                print(
                    f"Splitting failed GraphDB batch {n}/{total} into chunks of {split_size}.",
                    file=sys.stderr,
                )
                found.update(iris_present_in_graphdb(set(batch), chunk=split_size))
            continue
        for binding in payload.get("results", {}).get("bindings", []):
            val = binding.get("iri", {}).get("value")
            if val:
                found.add(val)
        print(f"GraphDB presence lookup {n}/{total} ({len(found)} found so far)", file=sys.stderr)
    return found


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
                    f"{entry.get('blob_base') or GITHUB_REPO_BLOB}/"
                    f"{entry['subpath']}/{entry.get('shacl_file') or fname}#L{line}")
    return (shorten(term), "")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
COLUMNS = [
    "Repository",
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
    report_sources = [
        (source, source["result_dir"])
        for source in CATALOG["sources"].values()
        if (source["result_dir"] / "validation-report.ttl").is_file()
    ]
    report_sources.sort(key=lambda pair: pair[0]["id"])
    report_dirs = [directory for _, directory in report_sources]

    rows: list[dict] = []
    for source, d in report_sources:
        profile = Path(source["shacl_file"]).stem
        shacl_file = source["id"]
        family = source["family_id"]
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
                "repository": source["repository_id"],
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
                r["repository"], r["family"], r["profile"], r["report_href"], r["focus_disp"],
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
