#!/usr/bin/env python3
"""Build a static dashboard of SHACL timings and validation results.

Landing page: combined stats and links to family pages. Each family page has
one results table (profile, errors, warnings, good, total shapes).
A profile name opens a table of sh:PropertyGroup rows (rdfs:label via sh:group).
Counts open focus-node / good-shape pages so the dashboard stays small.
"""
from __future__ import annotations

import html
import importlib.util
import re
import shutil
import sys
import os
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

EVAL_DIR = Path(__file__).resolve().parent


def _load(mod_name: str, filename: str):
    path = EVAL_DIR / filename
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cr = _load("collect_results", "collect-results.py")
ct = _load("collect_timings", "collect-timings.py")
DASH_DIR = EVAL_DIR / "dashboard"
DETAIL_PAGE_SIZE = 1500
FAMILIES = ("CGMES", "NCP")
RELICAP_SEARCH = "https://github.com/search?q=repo%3Aentsoe%2Frelicapgrid+{q}&type=code"
APL_BLOB = cr.GITHUB_REPO_BLOB  # …/application-profiles-library/blob/main
UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
SHAPE_TYPE = re.compile(r"\b(?:a|rdf:type)\s+sh:(PropertyShape|NodeShape)\b")
GROUP_TYPE = re.compile(r"\b(?:a|rdf:type)\s+sh:PropertyGroup\b")
GROUP_PRED = re.compile(r"\bsh:group\s+(\S+)")
RDFS_LABEL = re.compile(r'\brdfs:label\s+"((?:[^"\\]|\\.)*)"')
SH_ORDER = re.compile(r"\bsh:order\s+(\d+(?:\.\d+)?)")
SEV_IN_BLOCK = re.compile(r"\bsh:severity\s+sh:(Violation|Warning|Info)\b")
CLOSED_IN_BLOCK = re.compile(r"\bsh:closed\s+true\b")
SPARQL_IN_BLOCK = re.compile(r"\bsh:sparql\b")
TARGET_CLASS = re.compile(r"\bsh:targetClass\s+(.+?)(?:;|\.)", re.DOTALL)
UNGROUPED_URI = ""
UNGROUPED_LABEL = "Ungrouped"

ICON = {
    "Violation": '<span class="icon violation" title="sh:Violation">&#9679;</span>',
    "Warning": '<span class="icon warning" title="sh:Warning">&#9650;</span>',
    "Good": '<span class="icon good" title="good shape">&#9679;</span>',
    "Info": '<span class="icon info" title="sh:Info">&#9679;</span>',
}


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def brk(text: str) -> str:
    return re.sub(r"(?<=[/:#._?=-])(?!$)", "<wbr>", esc(text))


def normalize_severity(raw: str | None) -> str:
    term = cr.shorten(raw) if raw else ""
    if term.startswith("sh:"):
        term = term[3:]
    if "#" in term:
        term = term.rsplit("#", 1)[-1]
    return term or "Info"


def constraint_key(result: dict[str, str]) -> str:
    for field in ("sh:sourceConstraint", "sh:sourceShape", "sh:sourceConstraintComponent"):
        val = result.get(field)
        if val:
            return val
    return ""


def iri_of(term: str | None) -> str:
    if not term:
        return ""
    stripped = cr.strip_brackets(term)
    return stripped or term


def local_name(uri: str) -> str:
    short = cr.shorten(uri)
    if "#" in short:
        short = short.rsplit("#", 1)[-1]
    elif ":" in short:
        short = short.split(":", 1)[-1]
    return short or uri


def css_href(from_dir: Path) -> str:
    depth = len(from_dir.relative_to(EVAL_DIR).parts)
    return "/".join([".."] * depth + ["dashboard.css"]) if depth else "dashboard.css"


def rel_href(from_dir: Path, target: str | None) -> str | None:
    if not target:
        return None
    dest = (EVAL_DIR / target).resolve()
    return Path(os.path.relpath(dest, from_dir)).as_posix()


def family_page_rel(family: str) -> str:
    return f"dashboard/f/{family}/index.html"


TABLE_RESIZE_SCRIPT = """
<script>
(function () {
  document.querySelectorAll("table").forEach(function (table) {
    table.querySelectorAll("thead th").forEach(function (th) {
      if (th.colSpan > 1) return;
      var grip = document.createElement("span");
      grip.className = "col-resize";
      grip.title = "Drag to resize column";
      th.appendChild(grip);
      grip.addEventListener("mousedown", function (e) {
        e.preventDefault();
        e.stopPropagation();
        var startX = e.pageX;
        var startW = th.getBoundingClientRect().width;
        table.classList.add("resizing");
        function move(ev) {
          th.style.width = Math.max(36, startW + (ev.pageX - startX)) + "px";
        }
        function up() {
          table.classList.remove("resizing");
          document.removeEventListener("mousemove", move);
          document.removeEventListener("mouseup", up);
        }
        document.addEventListener("mousemove", move);
        document.addEventListener("mouseup", up);
      });
    });
  });
})();
</script>
"""


def page_shell(title: str, body: str, from_dir: Path) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Rubik:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{esc(css_href(from_dir))}">
</head>
<body>
{body}
{TABLE_RESIZE_SCRIPT}
</body>
</html>
"""


def parse_report_meta(path: Path) -> dict[str, object]:
    head = path.read_text(encoding="utf-8", errors="replace")[:4000]
    return {
        "conforms": "sh:conforms true" in head,
        "truncated": "rdf4j:truncated true" in head,
        "is_turtle": head.lstrip().startswith("@prefix") or "sh:ValidationReport" in head,
    }


def focus_file_href(focus_term: str | None) -> str:
    """Link a focus node to the ReliCapGrid file that mentions it (GitHub search)."""
    iri = iri_of(focus_term) or (focus_term or "")
    found = UUID_RE.search(iri)
    q = found.group(0) if found else iri
    if not q:
        return ""
    return RELICAP_SEARCH.format(q=quote(q))


def assign_focus_hrefs(data: dict) -> tuple[int, int]:
    """Set focus_href to GraphDB when the IRI exists there, else the instance file."""
    items: list[dict] = []
    iris: set[str] = set()
    for rec in data.get("profiles", {}).values():
        for sev_items in rec.get("by_sev", {}).values():
            for item in sev_items:
                iri = item.get("focus_iri") or ""
                if iri:
                    iris.add(iri)
                items.append(item)
    present = cr.iris_present_in_graphdb(iris)
    in_gdb = missing = 0
    seen: set[str] = set()
    for item in items:
        iri = item.get("focus_iri") or ""
        gdb_href = item.get("gdb_href") or ""
        if iri and iri in present and gdb_href:
            item["focus_href"] = gdb_href
            if iri not in seen:
                in_gdb += 1
                seen.add(iri)
        else:
            item["focus_href"] = item.get("file_href") or ""
            if iri and iri not in seen:
                missing += 1
                seen.add(iri)
    return in_gdb, missing


def group_slug(group_uri: str) -> str:
    if not group_uri:
        return "ungrouped"
    loc = local_name(group_uri)
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", loc).strip("-._")
    return (slug or "group")[:80]


def shacl_href(uri: str, shacl_file: str, index: dict[str, dict]) -> str:
    if not uri:
        entry = index.get(shacl_file)
        if entry:
            return f"{APL_BLOB}/{entry['subpath']}/{shacl_file}"
        return ""
    candidates = [shacl_file] + [f for f in index if f != shacl_file]
    for fname in candidates:
        entry = index.get(fname)
        if entry and uri in entry.get("lines", {}):
            line = entry["lines"][uri]
            return f"{APL_BLOB}/{entry['subpath']}/{fname}#L{line}"
    entry = index.get(shacl_file)
    if entry:
        return f"{APL_BLOB}/{entry['subpath']}/{shacl_file}"
    return ""


def ungrouped_meta() -> dict:
    return {"uri": UNGROUPED_URI, "label": UNGROUPED_LABEL, "order": 10**9, "line": 0}


def parse_ttl_blocks(ttl_path: Path) -> tuple[dict[str, str], str | None, list[tuple[int, str, str]]]:
    text = ttl_path.read_text(encoding="utf-8", errors="replace")
    prefixes: dict[str, str] = {}
    base: str | None = None
    prefix_re = re.compile(r"\s*(?:@prefix|PREFIX)\s+([\w.-]*):\s+<([^>]*)>", re.I)
    base_re = re.compile(r"\s*(?:@base|BASE)\s+<([^>]*)>", re.I)
    for line in text.splitlines():
        m = prefix_re.match(line)
        if m:
            prefixes[m.group(1)] = m.group(2)
            continue
        m = base_re.match(line)
        if m:
            base = m.group(1)

    blocks: list[tuple[int, str, str]] = []
    current: list[str] = []
    current_subj = ""
    current_line = 1
    for n, line in enumerate(text.splitlines(), start=1):
        if line and line[0] not in " \t#@" and not line.lower().startswith("@prefix") and not line.lower().startswith("@base") and not line.upper().startswith("PREFIX ") and not line.upper().startswith("BASE "):
            if current and current_subj:
                blocks.append((current_line, current_subj, "\n".join(current)))
            token = line.split(None, 1)[0]
            current_subj = cr.resolve_term(token, prefixes, base) or token
            current_line = n
            current = [line]
        else:
            current.append(line)
    if current and current_subj:
        blocks.append((current_line, current_subj, "\n".join(current)))
    return prefixes, base, blocks


def parse_shacl(ttl_path: Path) -> tuple[list[dict], dict[str, dict]]:
    """Property/Node shapes plus sh:PropertyGroup map (uri → label/order)."""
    prefixes, base, blocks = parse_ttl_blocks(ttl_path)
    groups: dict[str, dict] = {}
    for line_no, uri, block in blocks:
        if not GROUP_TYPE.search(block):
            continue
        lm = RDFS_LABEL.search(block)
        om = SH_ORDER.search(block)
        groups[uri] = {
            "uri": uri,
            "label": (lm.group(1).encode().decode("unicode_escape") if lm else local_name(uri)),
            "order": float(om.group(1)) if om else 0,
            "line": line_no,
        }

    shapes: list[dict] = []
    for line_no, uri, block in blocks:
        tm = SHAPE_TYPE.search(block)
        if not tm:
            continue
        kind = tm.group(1)
        sev_m = SEV_IN_BLOCK.search(block)
        closed = bool(CLOSED_IN_BLOCK.search(block))
        sparql = bool(SPARQL_IN_BLOCK.search(block))
        if kind == "NodeShape" and not (sev_m or closed or sparql):
            continue
        targets: list[str] = []
        tm2 = TARGET_CLASS.search(block)
        if tm2:
            for tok in re.findall(r"[^\s,;]+", tm2.group(1)):
                resolved = cr.resolve_term(tok.rstrip(",;."), prefixes, base)
                if resolved:
                    targets.append(resolved)
        gtok = GROUP_PRED.search(block)
        group_uri = ""
        if gtok:
            group_uri = cr.resolve_term(gtok.group(1).rstrip(",;."), prefixes, base) or ""
            if group_uri and group_uri not in groups:
                groups[group_uri] = {
                    "uri": group_uri,
                    "label": local_name(group_uri),
                    "order": 0,
                    "line": 0,
                }
        gmeta = groups.get(group_uri) if group_uri else None
        shapes.append({
            "uri": uri,
            "kind": kind,
            "line": line_no,
            "severity": sev_m.group(1) if sev_m else ("Info" if closed else "Violation"),
            "targets": targets,
            "label": local_name(uri),
            "group_uri": group_uri,
            "group_label": gmeta["label"] if gmeta else UNGROUPED_LABEL,
        })
    return shapes, groups


def collect_validation(index: dict[str, dict], timings: dict[str, dict]) -> dict:
    profiles: dict[str, dict] = {}
    totals = defaultdict(int)
    truncated_profiles: list[str] = []
    conforming = 0
    reports = 0
    http_errors: list[dict] = []

    for d in sorted(p for p in EVAL_DIR.iterdir() if p.is_dir()):
        report = d / "validation-report.ttl"
        profile = d.name
        timing = timings.get(profile, {})
        family = index.get(f"{profile}.ttl", {}).get("family") or ct.infer_family(profile)
        if not report.exists():
            continue
        reports += 1
        shacl_file = f"{profile}.ttl"
        shacl_meta = index.get(shacl_file, {})
        shacl_path = cr.APL_DIR / shacl_meta["subpath"] / shacl_file if shacl_meta else None
        declared, groups = parse_shacl(shacl_path) if shacl_path and shacl_path.is_file() else ([], {})
        shape_group = {s["uri"]: s.get("group_uri") or "" for s in declared}

        rec = {
            "profile": profile,
            "family": family,
            "truncated": False,
            "declared": declared,
            "groups": groups,
            "shape_group": shape_group,
            "by_sev": {"Violation": [], "Warning": [], "Info": []},
            "failed_uris": set(),
        }
        profiles[profile] = rec

        meta = parse_report_meta(report)
        if not meta["is_turtle"]:
            err_text = report.read_text(encoding="utf-8", errors="replace")
            http_errors.append({
                "profile": profile,
                "family": family,
                "http_status": str(timing.get("http_status") or "500"),
                "duration": timing.get("duration"),
                "duration_disp": ct.format_duration(
                    float(timing["duration"]) if isinstance(timing.get("duration"), (int, float)) else None
                ),
                "message": err_text.strip(),
                "report_href": f"{cr.EVAL_REPO_BLOB}/{profile}/validation-report.ttl",
            })
            continue
        if meta["conforms"]:
            conforming += 1
        if meta["truncated"]:
            truncated_profiles.append(profile)
            rec["truncated"] = True

        for result in cr.parse_report(report):
            severity = normalize_severity(result.get("sh:resultSeverity"))
            key = constraint_key(result)
            if severity in ("Violation", "Warning"):
                rec["failed_uris"].add(iri_of(result.get("sh:sourceConstraint")))
                rec["failed_uris"].add(iri_of(result.get("sh:sourceShape")))
                rec["failed_uris"].discard("")
            focus_term = result.get("sh:focusNode")
            focus_disp, gdb_href = cr.graphdb_link(focus_term)
            constraint_uri = iri_of(result.get("sh:sourceConstraint"))
            source_shape_uri = iri_of(result.get("sh:sourceShape"))
            group_uri = shape_group.get(constraint_uri) or shape_group.get(source_shape_uri) or ""
            gmeta = groups.get(group_uri) if group_uri else None
            shape_uri = constraint_uri or source_shape_uri
            rec["by_sev"].setdefault(severity, []).append({
                "focus_disp": focus_disp,
                "focus_iri": iri_of(focus_term),
                "gdb_href": gdb_href,
                "file_href": focus_file_href(focus_term),
                "focus_href": gdb_href,
                "shacl_href": shacl_href(shape_uri, shacl_file, index),
                "message": cr.strip_literal(result.get("sh:resultMessage")),
                "severity": severity,
                "shape": local_name(iri_of(key)),
                "constraint_uri": constraint_uri,
                "source_shape_uri": source_shape_uri,
                "group_uri": group_uri,
                "group_label": gmeta["label"] if gmeta else UNGROUPED_LABEL,
            })
            totals[severity] += 1
            totals["results"] += 1

    return {
        "profiles": profiles,
        "totals": totals,
        "truncated_profiles": truncated_profiles,
        "conforming": conforming,
        "reports": reports,
        "http_errors": http_errors,
    }


def unique_focus(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        key = item["focus_disp"]
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def unique_focus_count(items: list[dict]) -> int:
    return len(unique_focus(items))


def unique_shape_count(items: list[dict]) -> int:
    return len({item.get("shape") or item.get("focus_disp") for item in items})


def result_shape_uris(item: dict) -> set[str]:
    return {u for u in (item.get("constraint_uri"), item.get("source_shape_uri")) if u}


def partition_declared(declared: list[dict], v_items: list[dict], w_items: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Split declared shapes into violation / warning / good. Each shape is in exactly one bucket."""
    v_uris: set[str] = set()
    for item in v_items:
        v_uris |= result_shape_uris(item)
    w_uris: set[str] = set()
    for item in w_items:
        w_uris |= result_shape_uris(item)
    errors, warnings, goods = [], [], []
    for shape in declared:
        if shape["uri"] in v_uris:
            errors.append(shape)
        elif shape["uri"] in w_uris:
            warnings.append(shape)
        else:
            goods.append(shape)
    return errors, warnings, goods


def count_bundle(declared: list[dict], v_items: list[dict], w_items: list[dict]) -> dict:
    """Additive shape counts: distinct_v + distinct_w + good == total."""
    if declared:
        err_shapes, warn_shapes, goods = partition_declared(declared, v_items, w_items)
        dv, dw, g_n = len(err_shapes), len(warn_shapes), len(goods)
        t_n = dv + dw + g_n
    else:
        err_shapes, warn_shapes, goods = [], [], []
        dv, dw = unique_shape_count(v_items), unique_shape_count(w_items)
        g_n = 0
        t_n = dv + dw
    return {
        "dv_count": dv,
        "dw_count": dw,
        "v_count": unique_focus_count(v_items),
        "w_count": unique_focus_count(w_items),
        "g_count": g_n,
        "t_count": t_n,
        "err_shapes": err_shapes,
        "warn_shapes": warn_shapes,
        "goods": goods,
    }


def write_paged_table(
    out_dir: Path,
    title: str,
    heading: str,
    crumb: str,
    meta: str,
    headers: list[str],
    rows: list[str],
    from_dir: Path,
) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = [rows[i:i + DETAIL_PAGE_SIZE] for i in range(0, max(len(rows), 1), DETAIL_PAGE_SIZE)] or [[]]
    for page_i, chunk in enumerate(pages, start=1):
        pager = ""
        if len(pages) > 1:
            links = []
            for n in range(1, len(pages) + 1):
                name = "index.html" if n == 1 else f"p{n}.html"
                if n == page_i:
                    links.append(f"<strong>{n}</strong>")
                else:
                    links.append(f'<a href="{name}">{n}</a>')
            pager = f'<p class="pager">Pages: {" · ".join(links)}</p>'
        header_html = "".join(f"<th>{esc(h)}</th>" for h in headers)
        body = f"""
<p class="crumb">{crumb}</p>
<h1>{heading}</h1>
<p class="meta">{meta}</p>
{pager}
<div class="table-wrap">
<table>
  <thead><tr>{header_html}</tr></thead>
  <tbody>
    {''.join(chunk) if chunk else '<tr><td colspan="' + str(len(headers)) + '">None.</td></tr>'}
  </tbody>
</table>
</div>
{pager}
"""
        name = "index.html" if page_i == 1 else f"p{page_i}.html"
        (out_dir / name).write_text(page_shell(title, body, from_dir), encoding="utf-8")
    return (out_dir / "index.html").relative_to(EVAL_DIR).as_posix()


def write_focus_list(
    profile: str,
    family: str,
    severity: str,
    items: list[dict],
    profile_time: str,
    *,
    group_label: str | None = None,
    group_uri: str = "",
    extra_crumb: str = "",
) -> str:
    if group_label:
        out_dir = DASH_DIR / "p" / profile / "g" / group_slug(group_uri) / severity.lower()
    else:
        out_dir = DASH_DIR / "p" / profile / severity.lower()
    icon = ICON.get(severity, ICON["Violation"])
    uniq = unique_focus(items)
    rows = []
    for item in uniq:
        href = item.get("focus_href") or ""
        focus = (
            f'<a href="{esc(href)}" target="_blank" rel="noopener">{brk(item["focus_disp"])}</a>'
            if href else brk(item["focus_disp"])
        )
        shape_disp = esc(item.get("shape", "") or "—")
        shacl_href_val = item.get("shacl_href") or ""
        constraint = (
            f'<a href="{esc(shacl_href_val)}" target="_blank" rel="noopener">{shape_disp}</a>'
            if shacl_href_val else shape_disp
        )
        rows.append(
            "<tr>"
            f"<td>{focus}</td>"
            f'<td class="msg">{esc(item["message"])}</td>'
            f"<td>{constraint}</td>"
            "</tr>"
        )
    profile_page = f"dashboard/p/{profile}/index.html"
    crumb = (
        f'<a href="{esc(rel_href(out_dir, "index.html"))}">Dashboard</a> · '
        f'<a href="{esc(rel_href(out_dir, family_page_rel(family)))}">{esc(family)}</a> · '
        f'<a href="{esc(rel_href(out_dir, profile_page))}">{brk(profile)}</a>'
    )
    if extra_crumb:
        crumb += f" · {extra_crumb}"
    elif group_label:
        crumb += f" · {esc(group_label)}"
    heading_extra = f" · {esc(group_label)}" if group_label else ""
    meta = (
        f"Check time <strong>{esc(profile_time)}</strong> · "
        f"{len(uniq)} distinct sh:focusNode values. "
        f"IRIs present in GraphDB <code>{esc(cr.GRAPHDB_REPO)}</code> open the resource there; "
        f"others open the ReliCapGrid instance file (GitHub search). "
        f"<code>sh:sourceConstraint</code> opens the profile shape file."
    )
    return write_paged_table(
        out_dir,
        f"{severity} · {profile}",
        f"{icon} {esc(severity)}{heading_extra} · {brk(profile)}",
        crumb,
        meta,
        ["sh:focusNode", "sh:message", "sh:sourceConstraint"],
        rows,
        out_dir,
    )


def write_shape_list(
    profile: str,
    family: str,
    shapes: list[dict],
    shacl_meta: dict,
    profile_time: str,
    *,
    folder: str,
    title_kind: str,
    icon_html: str,
    meta: str,
    group_label: str | None = None,
    group_uri: str = "",
) -> str:
    if group_label:
        out_dir = DASH_DIR / "p" / profile / "g" / group_slug(group_uri) / folder
    else:
        out_dir = DASH_DIR / "p" / profile / folder
    rows = []
    subpath = shacl_meta.get("subpath", "")
    shacl_file = f"{profile}.ttl"
    for shape in sorted(shapes, key=lambda s: s["label"]):
        shacl_link = ""
        if subpath:
            shacl_link = f"{APL_BLOB}/{subpath}/{shacl_file}#L{shape['line']}"
        name = (
            f'<a href="{esc(shacl_link)}" target="_blank" rel="noopener">{brk(shape["label"])}</a>'
            if shacl_link else brk(shape["label"])
        )
        rows.append(
            "<tr>"
            f"<td>{name}</td>"
            f"<td>{esc(shape['kind'])}</td>"
            "</tr>"
        )
    profile_page = f"dashboard/p/{profile}/index.html"
    crumb = (
        f'<a href="{esc(rel_href(out_dir, "index.html"))}">Dashboard</a> · '
        f'<a href="{esc(rel_href(out_dir, family_page_rel(family)))}">{esc(family)}</a> · '
        f'<a href="{esc(rel_href(out_dir, profile_page))}">{brk(profile)}</a>'
    )
    if group_label:
        crumb += f" · {esc(group_label)}"
    heading_extra = f" · {esc(group_label)}" if group_label else ""
    return write_paged_table(
        out_dir,
        f"{title_kind} · {profile}",
        f"{icon_html} {esc(title_kind)}{heading_extra} · {brk(profile)}",
        crumb,
        meta,
        ["shape", "kind"],
        rows,
        out_dir,
    )


def write_good_list(
    profile: str,
    family: str,
    shapes: list[dict],
    shacl_meta: dict,
    profile_time: str,
    *,
    group_label: str | None = None,
    group_uri: str = "",
) -> str:
    return write_shape_list(
        profile, family, shapes, shacl_meta, profile_time,
        folder="good",
        title_kind="Good shapes",
        icon_html=ICON["Good"],
        meta=(
            f"Check time <strong>{esc(profile_time)}</strong> · "
            f"{len(shapes)} declared shapes with no sh:Violation or sh:Warning. "
            f"Shape names open the profile SHACL file."
        ),
        group_label=group_label,
        group_uri=group_uri,
    )


def write_distinct_shape_list(
    profile: str,
    family: str,
    shapes: list[dict],
    shacl_meta: dict,
    profile_time: str,
    severity: str,
    *,
    group_label: str | None = None,
    group_uri: str = "",
) -> str:
    folder = "distinct-violation" if severity == "Violation" else "distinct-warning"
    title = "Distinct errors" if severity == "Violation" else "Distinct warnings"
    icon = ICON["Violation"] if severity == "Violation" else ICON["Warning"]
    return write_shape_list(
        profile, family, shapes, shacl_meta, profile_time,
        folder=folder,
        title_kind=title,
        icon_html=icon,
        meta=(
            f"Check time <strong>{esc(profile_time)}</strong> · "
            f"{len(shapes)} declared shapes that produced at least one "
            f"<code>sh:{esc(severity)}</code>. Shape names open the profile SHACL file."
        ),
        group_label=group_label,
        group_uri=group_uri,
    )


def write_http_page(err: dict) -> str:
    out = DASH_DIR / "http" / f"{err['profile']}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    body = f"""
<p class="crumb"><a href="../../index.html">Dashboard</a> ·
<a href="../f/{esc(err["family"])}/index.html">{esc(err["family"])}</a></p>
<h1>HTTP {esc(err["http_status"])} · {brk(err["profile"])}</h1>
<p class="meta">Check time <strong>{esc(err["duration_disp"])}</strong> ·
<a href="{esc(err["report_href"])}" target="_blank" rel="noopener">error body</a></p>
<pre class="msg">{esc(err["message"])}</pre>
"""
    out.write_text(page_shell(f"HTTP {err['http_status']} · {err['profile']}", body, out.parent), encoding="utf-8")
    return out.relative_to(EVAL_DIR).as_posix()


def groups_for_profile(rec: dict) -> list[dict]:
    groups = dict(rec.get("groups") or {})
    rows = list(groups.values())
    used_ungrouped = any(not (s.get("group_uri") or "") for s in rec.get("declared") or [])
    if not used_ungrouped:
        for items in (rec.get("by_sev") or {}).values():
            if any(not (it.get("group_uri") or "") for it in items):
                used_ungrouped = True
                break
    if used_ungrouped:
        rows.append(ungrouped_meta())
    if not rows and rec.get("declared"):
        rows.append(ungrouped_meta())
    rows.sort(key=lambda g: (float(g.get("order") or 0), str(g.get("label") or "")))
    counts = defaultdict(int)
    for g in rows:
        counts[g.get("label") or ""] += 1
    for g in rows:
        label = g.get("label") or UNGROUPED_LABEL
        if counts[label] > 1 and g.get("uri"):
            g["label"] = f"{label} ({local_name(g['uri'])})"
    return rows


def write_profile_page(
    profile: str,
    family: str,
    rec: dict,
    row: dict,
    shacl_meta: dict,
    group_rows: list[dict],
) -> str:
    out_dir = DASH_DIR / "p" / profile
    out_dir.mkdir(parents=True, exist_ok=True)
    shacl_file = f"{profile}.ttl"
    file_href = ""
    if shacl_meta.get("subpath"):
        file_href = f"{APL_BLOB}/{shacl_meta['subpath']}/{shacl_file}"
    rows_html = []
    for grow in group_rows:
        label = grow["label"]
        v_n, w_n, g_n, t_n = grow["v_count"], grow["w_count"], grow["g_count"], grow["t_count"]
        dv_n, dw_n = grow["dv_count"], grow["dw_count"]
        rows_html.append(
            f"""<tr>
  <td class="profile">{esc(label)}</td>
  <td class="num cell">{count_cell(v_n, rel_href(out_dir, grow.get("v_href")))}</td>
  <td class="num cell">{count_cell(dv_n, rel_href(out_dir, grow.get("dv_href")))}</td>
  <td class="num cell">{count_cell(w_n, rel_href(out_dir, grow.get("w_href")))}</td>
  <td class="num cell">{count_cell(dw_n, rel_href(out_dir, grow.get("dw_href")))}</td>
  <td class="num cell">{count_cell(g_n, rel_href(out_dir, grow.get("g_href")))}</td>
  <td class="num">{count_cell(t_n, None)}</td>
</tr>"""
        )
    shacl_note = (
        f'<a href="{esc(file_href)}" target="_blank" rel="noopener">{esc(shacl_file)}</a>'
        if file_href else esc(shacl_file)
    )
    body = f"""
<p class="crumb"><a href="{esc(rel_href(out_dir, "index.html"))}">Dashboard</a> ·
<a href="{esc(rel_href(out_dir, family_page_rel(family)))}">{esc(family)}</a></p>
<h1>{brk(profile)}</h1>
<p class="meta">Check time <strong>{esc(row["duration_disp"])}</strong> ·
HTTP {esc(str(row["http_status"]))} · shape file {shacl_note}.</p>
<div class="table-wrap">
<table class="family-table compact">
  <colgroup></colgroup>
  <colgroup class="errors" span="2"></colgroup>
  <colgroup class="warnings" span="2"></colgroup>
  <thead>
    <tr>
      <th class="profile" rowspan="2">Property group</th>
      <th class="num group-err" colspan="2">{ICON["Violation"]} Errors</th>
      <th class="num group-warn" colspan="2">{ICON["Warning"]} Warnings</th>
      <th class="num" rowspan="2">{ICON["Good"]} Good</th>
      <th class="num" rowspan="2">Total</th>
    </tr>
    <tr>
      <th class="num group-err">Total</th>
      <th class="num group-err">Distinct</th>
      <th class="num group-warn">Total</th>
      <th class="num group-warn">Distinct</th>
    </tr>
  </thead>
  <tbody>
{"".join(rows_html) if rows_html else '<tr><td colspan="7">No property groups declared.</td></tr>'}
  </tbody>
</table>
</div>
"""
    out = out_dir / "index.html"
    out.write_text(page_shell(f"{profile} · property groups", body, out_dir), encoding="utf-8")
    return out.relative_to(EVAL_DIR).as_posix()


def count_cell(n: int, href: str | None) -> str:
    if n <= 0:
        return ""
    if not href:
        return str(n)
    return f'<a href="{esc(href)}">{n}</a>'


def family_aggregates(profile_rows: list[dict]) -> dict:
    timed = [
        float(r["duration"])
        for r in profile_rows
        if isinstance(r.get("duration"), (int, float))
    ]
    total = sum(timed)
    avg = total / len(timed) if timed else 0.0
    slowest = max(timed) if timed else None
    return {
        "profiles": len(profile_rows),
        "timed": len(timed),
        "total": total,
        "avg": avg,
        "slowest": slowest,
        "distinct_v": sum(int(r["dv_count"]) for r in profile_rows),
        "distinct_w": sum(int(r["dw_count"]) for r in profile_rows),
        "violations": sum(int(r["v_count"]) for r in profile_rows),
        "warnings": sum(int(r["w_count"]) for r in profile_rows),
        "good": sum(int(r["g_count"]) for r in profile_rows),
        "shapes": sum(int(r["t_count"]) for r in profile_rows),
        "http_err": sum(1 for r in profile_rows if str(r.get("http_status") or "") not in ("", "200")),
    }


FILTER_SORT_SCRIPT = """
<script>
(function () {
  function sortFamily(section, key, dir) {
    var wrap = section.querySelector("tbody.family-profiles");
    if (!wrap) return;
    var blocks = Array.prototype.slice.call(wrap.querySelectorAll("tr.profile-block"));
    var desc = dir !== "asc";
    blocks.sort(function (a, b) {
      var av = parseFloat(a.getAttribute("data-" + key) || "-1");
      var bv = parseFloat(b.getAttribute("data-" + key) || "-1");
      if (av === bv) {
        return (a.getAttribute("data-profile") || "").localeCompare(b.getAttribute("data-profile") || "");
      }
      return desc ? bv - av : av - bv;
    });
    blocks.forEach(function (el) { wrap.appendChild(el); });
  }
  document.querySelectorAll("section[data-family]").forEach(function (section) {
    var filter = section.querySelector(".family-filter");
    if (filter) {
      filter.addEventListener("input", function () {
        var q = this.value.toLowerCase();
        section.querySelectorAll(".profile-block").forEach(function (el) {
          var name = el.getAttribute("data-profile") || "";
          el.classList.toggle("hidden", q && name.toLowerCase().indexOf(q) === -1);
        });
      });
    }
    section.querySelectorAll(".sort-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var key = btn.getAttribute("data-sort");
        var dir = btn.getAttribute("data-dir") || "desc";
        if (btn.classList.contains("active")) {
          dir = dir === "desc" ? "asc" : "desc";
          btn.setAttribute("data-dir", dir);
        }
        section.querySelectorAll(".sort-btn").forEach(function (other) { other.classList.remove("active"); });
        btn.classList.add("active");
        sortFamily(section, key, dir);
      });
    });
  });
})();
</script>
"""


def family_stats_html(agg: dict) -> str:
    slowest = ct.format_duration(agg["slowest"]) if agg["slowest"] is not None else "—"
    return f"""  <div class="stats">
    <div class="stat"><span>Profiles</span><strong>{agg["profiles"]}</strong></div>
    <div class="stat"><span>Family check time</span><strong>{esc(ct.format_duration(agg["total"]))}</strong></div>
    <div class="stat"><span>Average</span><strong>{esc(ct.format_duration(agg["avg"]))}</strong></div>
    <div class="stat"><span>Max</span><strong>{esc(slowest)}</strong></div>
    <div class="stat"><span>Distinct errors</span><strong>{agg["distinct_v"]}</strong></div>
    <div class="stat"><span>Distinct warnings</span><strong>{agg["distinct_w"]}</strong></div>
    <div class="stat"><span>Errors</span><strong>{agg["violations"]}</strong></div>
    <div class="stat"><span>Warnings</span><strong>{agg["warnings"]}</strong></div>
    <div class="stat"><span>Good shapes</span><strong>{agg["good"]}</strong></div>
    <div class="stat"><span>Total shapes</span><strong>{agg["shapes"]}</strong></div>
    <div class="stat"><span>Non-200 HTTP</span><strong>{agg["http_err"]}</strong></div>
  </div>"""


def family_table(family: str, profile_rows: list[dict], from_dir: Path, *, with_toolbar: bool) -> str:
    rows_html = []
    for row in profile_rows:
        profile = row["profile"]
        duration = row["duration"]
        dur_cls = "dur"
        http_cls = "sub"
        if row["http_status"] not in ("", "200"):
            dur_cls += " bad"
            http_cls += " bad"
        elif isinstance(duration, (int, float)) and duration >= 60:
            dur_cls += " slow"
        http_raw = str(row["http_status"])
        http_rel = rel_href(from_dir, row.get("http_href"))
        http_cell = f'<a href="{esc(http_rel)}">{esc(http_raw)}</a>' if http_rel else esc(http_raw)
        v_n, w_n, g_n, t_n = row["v_count"], row["w_count"], row["g_count"], row["t_count"]
        dv_n, dw_n = row["dv_count"], row["dw_count"]
        time_attr = f"{duration:.6f}" if isinstance(duration, (int, float)) else "-1"
        p_rel = rel_href(from_dir, row.get("p_href"))
        profile_cell = (
            f'<a href="{esc(p_rel)}">{brk(profile)}</a>' if p_rel else brk(profile)
        )
        rows_html.append(
            f"""<tr class="profile-block" data-profile="{esc(profile)}" data-v="{v_n}" data-dv="{dv_n}" data-time="{time_attr}">
  <td class="profile">{profile_cell}
    <div class="sub"><span class="{http_cls}">HTTP {http_cell}</span></div>
  </td>
  <td class="{dur_cls}">{esc(row["duration_disp"])}</td>
  <td class="num cell">{count_cell(v_n, rel_href(from_dir, row.get("v_href")))}</td>
  <td class="num cell">{count_cell(dv_n, rel_href(from_dir, row.get("dv_href")))}</td>
  <td class="num cell">{count_cell(w_n, rel_href(from_dir, row.get("w_href")))}</td>
  <td class="num cell">{count_cell(dw_n, rel_href(from_dir, row.get("dw_href")))}</td>
  <td class="num cell">{count_cell(g_n, rel_href(from_dir, row.get("g_href")))}</td>
  <td class="num">{count_cell(t_n, None)}</td>
</tr>"""
        )
    toolbar = ""
    if with_toolbar:
        toolbar = f"""  <div class="family-toolbar">
    <input class="filter family-filter" type="search" placeholder="Filter {esc(family)} profiles…">
    <span>Order:</span>
    <button type="button" class="sort-btn" data-sort="time" data-dir="desc">Check time</button>
    <button type="button" class="sort-btn" data-sort="v" data-dir="desc">Errors</button>
    <button type="button" class="sort-btn" data-sort="dv" data-dir="desc">Distinct errors</button>
  </div>"""
    return f"""{toolbar}
<div class="table-wrap">
<table class="family-table compact">
  <colgroup></colgroup>
  <colgroup></colgroup>
  <colgroup class="errors" span="2"></colgroup>
  <colgroup class="warnings" span="2"></colgroup>
  <thead>
    <tr>
      <th class="profile" rowspan="2">Profile</th>
      <th class="dur" rowspan="2">Time</th>
      <th class="num group-err" colspan="2">{ICON["Violation"]} Errors</th>
      <th class="num group-warn" colspan="2">{ICON["Warning"]} Warnings</th>
      <th class="num" rowspan="2">{ICON["Good"]} Good</th>
      <th class="num" rowspan="2">Total</th>
    </tr>
    <tr>
      <th class="num group-err">Total</th>
      <th class="num group-err">Distinct</th>
      <th class="num group-warn">Total</th>
      <th class="num group-warn">Distinct</th>
    </tr>
  </thead>
  <tbody class="family-profiles">
{"".join(rows_html)}
  </tbody>
</table>
</div>"""


def family_index_card(family: str, profile_rows: list[dict]) -> str:
    agg = family_aggregates(profile_rows)
    href = family_page_rel(family)
    return f"""<section id="family-{esc(family)}">
<div class="family-head">
  <h2><a href="{esc(href)}">{esc(family)}</a></h2>
{family_stats_html(agg)}
</div>
</section>"""


def write_family_page(family: str, profile_rows: list[dict]) -> str:
    out_dir = DASH_DIR / "f" / family
    out_dir.mkdir(parents=True, exist_ok=True)
    agg = family_aggregates(profile_rows)
    body = f"""
<p class="crumb"><a href="../../../index.html">Dashboard</a></p>
<section data-family="{esc(family)}">
<div class="family-head">
  <h2>{esc(family)}</h2>
{family_stats_html(agg)}
</div>
{family_table(family, profile_rows, out_dir, with_toolbar=True)}
</section>
{FILTER_SORT_SCRIPT}
"""
    out = out_dir / "index.html"
    out.write_text(page_shell(f"{family} · SHACL evaluation", body, out_dir), encoding="utf-8")
    return out.relative_to(EVAL_DIR).as_posix()


def build() -> Path:
    if DASH_DIR.exists():
        shutil.rmtree(DASH_DIR)
    DASH_DIR.mkdir()

    index = cr.build_shacl_index()
    timing_rows = ct.collect_rows()
    timings = {str(r["profile"]): r for r in timing_rows}
    data = collect_validation(index, timings)
    in_gdb, missing = assign_focus_hrefs(data)
    print(f"Focus nodes in GraphDB: {in_gdb}; missing (file link): {missing}")

    http_hrefs: dict[str, str] = {}
    for err in data["http_errors"]:
        http_hrefs[err["profile"]] = write_http_page(err)

    family_profiles: dict[str, list[dict]] = {fam: [] for fam in FAMILIES}
    for row in timing_rows:
        family = str(row["family"]) if row["family"] in FAMILIES else ct.infer_family(str(row["profile"]))
        profile = str(row["profile"])
        rec = data["profiles"].get(profile, {})
        v_items = rec.get("by_sev", {}).get("Violation", [])
        w_items = rec.get("by_sev", {}).get("Warning", [])
        counts = count_bundle(rec.get("declared") or [], v_items, w_items)
        goods = counts["goods"]
        err_shapes = counts["err_shapes"]
        warn_shapes = counts["warn_shapes"]
        v_href = w_href = g_href = dv_href = dw_href = None
        time_disp = str(row.get("duration_disp") or "—")
        shacl_meta = index.get(f"{profile}.ttl", {})
        if v_items:
            v_href = write_focus_list(profile, family, "Violation", v_items, time_disp)
        if w_items:
            w_href = write_focus_list(profile, family, "Warning", w_items, time_disp)
        if err_shapes:
            dv_href = write_distinct_shape_list(
                profile, family, err_shapes, shacl_meta, time_disp, "Violation"
            )
        if warn_shapes:
            dw_href = write_distinct_shape_list(
                profile, family, warn_shapes, shacl_meta, time_disp, "Warning"
            )
        if goods:
            g_href = write_good_list(profile, family, goods, shacl_meta, time_disp)
        group_rows = []
        for gmeta in groups_for_profile(rec) if rec else []:
            guri = gmeta.get("uri") or ""
            gv = [it for it in v_items if (it.get("group_uri") or "") == guri]
            gw = [it for it in w_items if (it.get("group_uri") or "") == guri]
            gd = [s for s in (rec.get("declared") or []) if (s.get("group_uri") or "") == guri]
            gc = count_bundle(gd, gv, gw)
            gv_href = gw_href = gg_href = gdv_href = gdw_href = None
            if gv:
                gv_href = write_focus_list(
                    profile, family, "Violation", gv, time_disp,
                    group_label=gmeta["label"], group_uri=guri,
                )
            if gw:
                gw_href = write_focus_list(
                    profile, family, "Warning", gw, time_disp,
                    group_label=gmeta["label"], group_uri=guri,
                )
            if gc["err_shapes"]:
                gdv_href = write_distinct_shape_list(
                    profile, family, gc["err_shapes"], shacl_meta, time_disp, "Violation",
                    group_label=gmeta["label"], group_uri=guri,
                )
            if gc["warn_shapes"]:
                gdw_href = write_distinct_shape_list(
                    profile, family, gc["warn_shapes"], shacl_meta, time_disp, "Warning",
                    group_label=gmeta["label"], group_uri=guri,
                )
            if gc["goods"]:
                gg_href = write_good_list(
                    profile, family, gc["goods"], shacl_meta, time_disp,
                    group_label=gmeta["label"], group_uri=guri,
                )
            group_rows.append({
                **gmeta,
                **{k: gc[k] for k in ("dv_count", "dw_count", "v_count", "w_count", "g_count", "t_count")},
                "v_href": gv_href,
                "w_href": gw_href,
                "g_href": gg_href,
                "dv_href": gdv_href,
                "dw_href": gdw_href,
            })
        summary = {
            "profile": profile,
            "duration": row["duration"],
            "duration_disp": row["duration_disp"],
            "http_status": row["http_status"],
            "http_href": http_hrefs.get(profile),
            "dv_count": counts["dv_count"],
            "dw_count": counts["dw_count"],
            "v_count": counts["v_count"],
            "w_count": counts["w_count"],
            "g_count": counts["g_count"],
            "t_count": counts["t_count"],
            "v_href": v_href,
            "w_href": w_href,
            "g_href": g_href,
            "dv_href": dv_href,
            "dw_href": dw_href,
        }
        summary["p_href"] = write_profile_page(profile, family, rec, summary, shacl_meta, group_rows)
        family_profiles.setdefault(family, []).append(summary)

    timed = [r for r in timing_rows if r["duration"] is not None]
    total_seconds = sum(float(r["duration"]) for r in timed if isinstance(r["duration"], (int, float)))
    avg_seconds = total_seconds / len(timed) if timed else 0.0
    failed = [r for r in timing_rows if r["http_status"] not in ("", "200")]
    slowest = (
        ct.format_duration(float(timed[0]["duration"]))
        if timed and isinstance(timed[0]["duration"], (int, float)) else "—"
    )
    repo_url = cr.EVAL_REPO_BLOB.rsplit("/blob/", 1)[0]

    cards = []
    for family in FAMILIES:
        rows = family_profiles.get(family, [])
        if not rows:
            continue
        write_family_page(family, rows)
        cards.append(family_index_card(family, rows))

    overall_rows = [r for fam in family_profiles for r in family_profiles[fam]]
    overall = family_aggregates(overall_rows)

    body = f"""
<h1>ReliCapGrid SHACL evaluation dashboard</h1>
<p class="meta">
  <a href="{esc(repo_url)}" target="_blank" rel="noopener">repository on GitHub</a>
  <br>
  Focus nodes present in GraphDB open
  <a href="https://cim.ontotext.com/graphdb/" target="_blank" rel="noopener"><code>{esc(cr.GRAPHDB_REPO)}</code></a>;
  focus nodes missing from GraphDB open the ReliCapGrid instance file.
  Shape names and <code>sh:sourceConstraint</code> open the profile shape file.
  Click a profile name for its <code>sh:PropertyGroup</code> table.<br>
  <strong>Note:</strong> the ReliCapGrid ENTSO-E data is a snapshot
  (<time datetime="{esc(cr.DATA_TIMESTAMP)}">{esc(cr.DATA_TIMESTAMP)}</time>)
  and is not the latest upstream version.
</p>

<div class="stats">
  <div class="stat"><span>Profiles tested</span><strong>{len(timing_rows)}</strong></div>
  <div class="stat"><span>Total check time</span><strong>{esc(ct.format_duration(total_seconds))}</strong></div>
  <div class="stat"><span>Average / max</span><strong>{esc(ct.format_duration(avg_seconds))} / {esc(slowest)}</strong></div>
  <div class="stat"><span>Conforming</span><strong>{data["conforming"]}</strong></div>
  <div class="stat"><span>Truncated</span><strong>{len(data["truncated_profiles"])}</strong></div>
  <div class="stat"><span>Distinct errors</span><strong>{overall["distinct_v"]}</strong></div>
  <div class="stat"><span>Distinct warnings</span><strong>{overall["distinct_w"]}</strong></div>
  <div class="stat"><span>Errors</span><strong>{overall["violations"]}</strong></div>
  <div class="stat"><span>Warnings</span><strong>{overall["warnings"]}</strong></div>
  <div class="stat"><span>Good shapes</span><strong>{overall["good"]}</strong></div>
  <div class="stat"><span>Total shapes</span><strong>{overall["shapes"]}</strong></div>
  <div class="stat"><span>Non-200 HTTP</span><strong>{len(failed)}</strong></div>
</div>
<p class="note">Truncated GraphDB reports are lower bounds
({len(data["truncated_profiles"])} profiles).
<strong>Distinct errors / Distinct warnings</strong> count declared shapes that
produced at least one <code>sh:Violation</code> / <code>sh:Warning</code>.
<strong>Errors / Warnings</strong> count distinct <code>sh:focusNode</code> values.
<strong>Good</strong> is declared shapes with neither.
Distinct errors + Distinct warnings + Good = Total shapes, at profile, family,
and dashboard level (family figures sum the profiles; the frontmatter sums
the families). Click a family name for its results table. Click a profile name
for property groups. Click a count for the matching list.
Family check time is the sum of per-profile GraphDB durations.</p>

{"".join(cards)}
"""
    out = EVAL_DIR / "index.html"
    out.write_text(page_shell("ReliCapGrid SHACL evaluation dashboard", body, EVAL_DIR), encoding="utf-8")
    return out


def main() -> int:
    out = build()
    print(f"Dashboard: {out}")
    print(f"  Details: {DASH_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
