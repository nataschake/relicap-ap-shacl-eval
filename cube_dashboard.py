#!/usr/bin/env python3
"""Repository → family → ontology profile → SHACL shape static dashboard."""
from __future__ import annotations

import hashlib
import html
import importlib.util
import os
import re
import shutil
from pathlib import Path
from urllib.parse import quote

import dashboard_config as dc

ROOT = Path(__file__).resolve().parent
DASH = ROOT / "dashboard"
PAGE_SIZE = 1500
METRICS = ("time_sum", "time_max", "v_count", "dv_count", "w_count", "dw_count", "g_count", "t_count")
VALIDATION_METRICS = ("v_count", "dv_count", "w_count", "dw_count", "g_count", "t_count")
EXECUTION_ERROR_TILE_LEVELS = ("global", "repository", "family")
METRIC_LABEL = {
    "time_sum": "Time total",
    "time_max": "Time max",
    "v_count":  "Errors",
    "dv_count": "Distinct errors",
    "w_count":  "Warnings",
    "dw_count": "Distinct warnings",
    "g_count":  "Good shapes",
    "t_count":  "Total shapes",
    "execution_err": "Validation execution errors",
}
ICON = {
    "Violation": '<span class="icon violation" title="sh:Violation">&#10060;</span>',
    "Warning": '<span class="icon warning" title="sh:Warning">&#9888;</span>',
    "Good": '<span class="icon good" title="good shape">&#128994;</span>',
}
SHAPE_TYPE = re.compile(r"\b(?:a|rdf:type)\s+sh:(PropertyShape|NodeShape)\b")
SEVERITY = re.compile(r"\bsh:severity\s+sh:(Violation|Warning|Info)\b")
CLOSED = re.compile(r"\bsh:closed\s+true\b")
SPARQL = re.compile(r"\bsh:sparql\b")
LABEL = re.compile(r'\brdfs:label\s+"((?:[^"\\]|\\.)*)"')
UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    if spec is None or spec.loader is None:
        raise ImportError(filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cr = _load("cube_collect_results", "collect-results.py")
ct = _load("cube_collect_timings", "collect-timings.py")
INSTANCE_REPO = (dc.load_config().get("data") or {}).get(
    "instance_github_repository", "entsoe/relicapgrid"
)


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def brk(value: object) -> str:
    return re.sub(r"(?<=[/:#._?=-])(?!$)", "<wbr>", esc(value))


def rel(from_dir: Path, target: Path | str) -> str:
    path = target if isinstance(target, Path) else ROOT / target
    return Path(os.path.relpath(path.resolve(), from_dir.resolve())).as_posix()


def css_href(from_dir: Path) -> str:
    stylesheet = ROOT / "dashboard.css"
    version = hashlib.sha1(stylesheet.read_bytes()).hexdigest()[:12]
    return f"{rel(from_dir, stylesheet)}?v={version}"


TABLE_SCRIPT = """
<script>
(function () {
  document.querySelectorAll("table").forEach(function (table) {
    table.querySelectorAll("thead th").forEach(function (th) {
      if (th.colSpan > 1) return;
      var grip = document.createElement("span");
      grip.className = "col-resize";
      th.appendChild(grip);
      grip.addEventListener("mousedown", function (event) {
        event.preventDefault();
        var x = event.pageX, width = th.getBoundingClientRect().width;
        function move(e) { th.style.width = Math.max(36, width + e.pageX - x) + "px"; }
        function up() {
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


def shell(title: str, body: str, out_dir: Path) -> str:
    resolved_dir = out_dir.resolve()
    level_zero_metrics = (DASH / "all").resolve()
    is_level_zero = (
        resolved_dir == ROOT
        or resolved_dir.is_relative_to(level_zero_metrics)
    )
    body_class = ' class="level-zero"' if is_level_zero else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Rubik:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{esc(css_href(out_dir))}">
</head>
<body{body_class}>{body}{TABLE_SCRIPT if "<table" in body else ""}</body>
</html>
"""


def write(path: Path, title: str, body: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(shell(title, body, path.parent), encoding="utf-8")
    return path.relative_to(ROOT).as_posix()


def local_name(uri: str) -> str:
    short = cr.shorten(uri)
    return re.split(r"[/#:]", short)[-1] or short


def shape_slug(source_file: str, uri: str) -> str:
    stem = dc.slug(Path(source_file).stem, "shape-file")[:55]
    name = dc.slug(local_name(uri), "shape")[:55]
    digest = hashlib.sha1(f"{source_file}\0{uri}".encode()).hexdigest()[:9]
    return f"{stem}--{name}--{digest}"


def parse_blocks(path: Path) -> tuple[dict[str, str], str | None, list[tuple[int, str, str]]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    prefixes: dict[str, str] = {}
    base = None
    for line in lines:
        match = re.match(r"\s*(?:@prefix|PREFIX)\s+([\w.-]*):\s+<([^>]*)>", line, re.I)
        if match:
            prefixes[match.group(1)] = match.group(2)
        match = re.match(r"\s*(?:@base|BASE)\s+<([^>]*)>", line, re.I)
        if match:
            base = match.group(1)
    blocks: list[tuple[int, str, str]] = []
    current: list[str] = []
    subject = ""
    start = 1
    for number, line in enumerate(lines, 1):
        is_subject = (
            bool(line) and line[0] not in " \t#@"
            and not line.upper().startswith(("PREFIX ", "BASE "))
        )
        if is_subject:
            if current and subject:
                blocks.append((start, subject, "\n".join(current)))
            token = line.split(None, 1)[0]
            subject = cr.resolve_term(token, prefixes, base) or token
            start = number
            current = [line]
        else:
            current.append(line)
    if current and subject:
        blocks.append((start, subject, "\n".join(current)))
    return prefixes, base, blocks


def parse_shapes(path: Path) -> list[dict]:
    _prefixes, _base, blocks = parse_blocks(path)
    shapes = []
    seen: set[str] = set()
    for line, uri, block in blocks:
        kind_match = SHAPE_TYPE.search(block)
        if not kind_match or uri in seen:
            continue
        kind = kind_match.group(1)
        severity = SEVERITY.search(block)
        if kind == "NodeShape" and not (severity or CLOSED.search(block) or SPARQL.search(block)):
            continue
        label = LABEL.search(block)
        shapes.append({
            "uri": uri,
            "label": (
                label.group(1).encode().decode("unicode_escape")
                if label else local_name(uri)
            ),
            "kind": kind,
            "line": line,
            "declared": True,
        })
        seen.add(uri)
    return shapes


def report_meta(path: Path) -> dict:
    if not path.is_file():
        return {
            "exists": False,
            "turtle": False,
            "conforms": False,
            "truncated": False,
            "execution_error": True,
            "error_text": "(missing validation-report.ttl)",
        }
    head = path.read_text(encoding="utf-8", errors="replace")[:20000]
    is_validation_report = (
        "sh:ValidationReport" in head
        or "http://www.w3.org/ns/shacl#ValidationReport" in head
    )
    error_text = head.strip() if not is_validation_report else ""
    if not is_validation_report and not error_text:
        error_text = "(empty response)"
    return {
        "exists": True,
        "turtle": is_validation_report,
        "conforms": "sh:conforms true" in head,
        "truncated": "rdf4j:truncated true" in head,
        "execution_error": not is_validation_report,
        "error_text": error_text,
    }


def result_iri(result: dict, field: str) -> str:
    term = result.get(field)
    return cr.strip_brackets(term) or (term or "")


def result_item(result: dict, source: dict, index: dict) -> dict:
    severity = cr.shorten(result.get("sh:resultSeverity"))
    severity = severity.rsplit(":", 1)[-1].rsplit("#", 1)[-1] or "Info"
    focus_term = result.get("sh:focusNode")
    focus_display, graphdb_href = cr.graphdb_link(focus_term)
    constraint = result_iri(result, "sh:sourceConstraint")
    source_shape = result_iri(result, "sh:sourceShape")
    _display, source_href = cr.github_link(
        result.get("sh:sourceConstraint") or result.get("sh:sourceShape"),
        source["id"],
        index,
    )
    iri = result_iri(result, "sh:focusNode")
    found = UUID_RE.search(iri)
    query_value = found.group(0) if found else iri
    github_href = (
        "https://github.com/search?q="
        + quote(f"repo:{INSTANCE_REPO} {query_value}")
        + "&type=code"
        if query_value else ""
    )
    return {
        "severity": severity,
        "focus": focus_display,
        "focus_iri": iri,
        "graphdb_href": graphdb_href,
        "github_href": github_href,
        "message": cr.strip_literal(result.get("sh:resultMessage")),
        "constraint_uri": constraint,
        "source_shape_uri": source_shape,
        "source_href": source_href,
        "in_gdb": False,
    }


def unique_focus(items: list[dict]) -> list[dict]:
    seen = set()
    answer = []
    for item in items:
        key = item["focus"]
        if key not in seen:
            seen.add(key)
            answer.append(item)
    return answer


def collect_runs(catalog: dict, index: dict) -> list[dict]:
    timing_by_source = {str(row["source_id"]): row for row in ct.collect_rows()}
    runs = []
    all_items = []
    for source in sorted(catalog["sources"].values(), key=lambda item: item["id"]):
        timing = timing_by_source.get(source["id"], {})
        report = source["result_dir"] / "validation-report.ttl"
        meta = report_meta(report)
        shapes = parse_shapes(source["shacl_path"])
        items = []
        if meta["turtle"]:
            items = [result_item(raw, source, index) for raw in cr.parse_report(report)]
        all_items.extend(items)
        run = {
            **source,
            "duration": timing.get("duration"),
            "duration_disp": timing.get("duration_disp") or "—",
            "http_status": str(timing.get("http_status") or ""),
            "finished_at": str(timing.get("finished_at") or ""),
            "timing_href": str(timing.get("timing_href") or ""),
            "report_href": str(timing.get("report_href") or ""),
            "meta": meta,
            "shapes": shapes,
            "items": items,
        }
        runs.append(run)

    present = cr.iris_present_in_graphdb(
        {item["focus_iri"] for item in all_items if item["focus_iri"]}
    )
    for item in all_items:
        item["in_gdb"] = item["focus_iri"] in present
    return runs


def make_leaf(run: dict, shape: dict, items: list[dict]) -> dict:
    violations = [item for item in items if item["severity"] == "Violation"]
    warnings = [item for item in items if item["severity"] == "Warning"]
    has_error = bool(violations)
    has_warning = bool(warnings)
    duration = run["duration"] if isinstance(run["duration"], (int, float)) else None
    return {
        "id": shape_slug(run["shacl_file"], shape["uri"]),
        "name": shape["label"],
        "uri": shape["uri"],
        "kind": shape["kind"],
        "line": shape["line"],
        "declared": shape.get("declared", False),
        "run": run,
        "runs": {run["id"]: run},
        "v_items": violations,
        "w_items": warnings,
        "v_count": len(unique_focus(violations)),
        "dv_count": 1 if has_error else 0,
        "w_count": len(unique_focus(warnings)),
        "dw_count": 1 if has_warning and not has_error else 0,
        "g_count": 1 if not has_error and not has_warning else 0,
        "t_count": 1,
        "time_sum": duration or 0.0,
        "time_max": duration,
        "http_err": 1 if run["http_status"] not in ("", "200") else 0,
        "truncated": 1 if run["meta"]["truncated"] else 0,
    }


def leaves_for_run(run: dict) -> list[dict]:
    declared = {shape["uri"]: shape for shape in run["shapes"]}
    assigned: dict[str, list[dict]] = {uri: [] for uri in declared}
    synthetic: dict[str, dict] = {}
    for item in run["items"]:
        uri = (
            item["constraint_uri"] if item["constraint_uri"] in declared
            else item["source_shape_uri"] if item["source_shape_uri"] in declared
            else item["constraint_uri"] or item["source_shape_uri"]
        )
        if not uri:
            uri = f"unresolved:{item['severity']}:{item['source_href']}"
        if uri not in assigned:
            synthetic.setdefault(uri, {
                "uri": uri,
                "label": local_name(uri) or "Unresolved result shape",
                "kind": "ResultShape",
                "line": 0,
                "declared": False,
            })
            assigned[uri] = []
        assigned[uri].append(item)
    shapes = list(run["shapes"]) + list(synthetic.values())
    return [make_leaf(run, shape, assigned.get(shape["uri"], [])) for shape in shapes]


def aggregate(children: list[dict], extra_runs: dict[str, dict] | None = None) -> dict:
    runs = dict(extra_runs or {})
    for child in children:
        runs.update(child.get("runs") or {})
    durations = [
        float(run["duration"])
        for run in runs.values()
        if isinstance(run.get("duration"), (int, float))
    ]
    result = {
        key: sum(int(child.get(key) or 0) for child in children)
        for key in VALIDATION_METRICS
    }
    result.update({
        "runs": runs,
        "time_sum": sum(durations),
        "time_max": max(durations) if durations else None,
        "http_err": sum(
            1 for run in runs.values() if str(run.get("http_status") or "") not in ("", "200")
        ),
        "truncated": sum(1 for run in runs.values() if run.get("meta", {}).get("truncated")),
        "execution_err": sum(
            1 for run in runs.values() if run.get("meta", {}).get("execution_error")
        ),
    })
    return result


def node(node_id: str, name: str, children: list[dict], **extra) -> dict:
    return {"id": node_id, "name": name, "children": children, **aggregate(children), **extra}


def build_cube(catalog: dict, runs: list[dict]) -> dict:
    by_repo: dict[str, dict[str, dict[str, list[dict]]]] = {}
    runs_by_profile: dict[tuple[str, str, str], dict[str, dict]] = {}
    for run in runs:
        key = (run["repository_id"], run["family_id"], run["profile_id"])
        runs_by_profile.setdefault(key, {})[run["id"]] = run
        leaves = leaves_for_run(run)
        by_repo.setdefault(run["repository_id"], {}).setdefault(
            run["family_id"], {}
        ).setdefault(run["profile_id"], []).extend(leaves)

    repositories = []
    repo_config = {repo["id"]: repo for repo in catalog["repositories"]}
    for repository_id, families_data in by_repo.items():
        families = []
        config_repo = repo_config[repository_id]
        family_config = {family["id"]: family for family in config_repo["families_index"]}
        for family_id, profiles_data in families_data.items():
            profiles = []
            source_profiles = {
                source["profile_id"]: source
                for source in family_config[family_id]["sources"]
            }
            for profile_id, leaves in profiles_data.items():
                source = source_profiles[profile_id]
                profile = node(
                    profile_id,
                    source["profile_name"],
                    leaves,
                    level="profile",
                    extra_runs=runs_by_profile[(repository_id, family_id, profile_id)],
                    ontology_file=source["ontology_file"],
                    ontology_subpath=source["ontology_subpath"],
                    repo=config_repo,
                )
                # node() aggregates before extra attributes; replace timing with all profile runs.
                profile.update(aggregate(leaves, runs_by_profile[(repository_id, family_id, profile_id)]))
                profiles.append(profile)
            family = node(
                family_id,
                family_config[family_id].get("title") or family_id,
                sorted(profiles, key=lambda item: item["name"].lower()),
                level="family",
            )
            families.append(family)
        repository = node(
            repository_id,
            config_repo.get("title") or repository_id,
            sorted(families, key=lambda item: item["name"].lower()),
            level="repository",
            repo=config_repo,
        )
        repositories.append(repository)
    return node("all", "All configured repositories", repositories, level="global")


def assert_rollups(parent: dict, path: str = "all") -> None:
    children = parent.get("children") or []
    if not children:
        return
    for key in VALIDATION_METRICS:
        actual = sum(int(child[key]) for child in children)
        if actual != int(parent[key]):
            raise AssertionError(f"{path}: {key}={parent[key]}, children sum to {actual}")
    if parent.get("level") != "profile":
        execution_errors = sum(int(child["execution_err"]) for child in children)
        if execution_errors != int(parent["execution_err"]):
            raise AssertionError(
                f"{path}: execution_err={parent['execution_err']}, "
                f"children sum to {execution_errors}"
            )
    expected_runs = set().union(*(set(child["runs"]) for child in children))
    if not expected_runs.issubset(set(parent["runs"])):
        raise AssertionError(f"{path}: child timing runs are missing from parent")
    if parent["dv_count"] + parent["dw_count"] + parent["g_count"] != parent["t_count"]:
        raise AssertionError(f"{path}: distinct error + warning + good != total")
    for child in children:
        assert_rollups(child, f"{path}/{child['id']}")


def crumb(items: list[tuple[str, Path]], out_dir: Path, current: str) -> str:
    links = [
        f'<a href="{esc(rel(out_dir, target))}">{esc(label)}</a>'
        for label, target in items
    ]
    links.append(esc(current))
    return " · ".join(links)


def metric_value(metric: str, value) -> str:
    if metric.startswith("time_"):
        return ct.format_duration(float(value)) if isinstance(value, (int, float)) else "—"
    return str(value) if int(value or 0) > 0 else ""


def scope_metric_target(child: dict, metric: str) -> Path:
    base = child["page"]
    if child.get("children"):
        return base.parent / "m" / metric / "index.html"
    if metric == "v_count" and child["v_count"]:
        return base.parent / "violation" / "index.html"
    if metric == "w_count" and child["w_count"]:
        return base.parent / "warning" / "index.html"
    return base


def cell(child: dict, metric: str, out_dir: Path) -> str:
    display = metric_value(metric, child.get(metric))
    if not display:
        return ""
    return f'<a href="{esc(rel(out_dir, scope_metric_target(child, metric)))}">{esc(display)}</a>'


def summary_tiles(scope: dict, out_dir: Path) -> str:
    tiles = []
    for metric in METRICS:
        value = metric_value(metric, scope.get(metric))
        href = scope["metric_dir"] / metric / "index.html" if scope.get("children") else scope["page"]
        linked = (
            f'<a href="{esc(rel(out_dir, href))}">{esc(value)}</a>'
            if value and value != "—" else esc(value)
        )
        tiles.append(f'<div class="stat"><span>{esc(METRIC_LABEL[metric])}</span><strong>{linked}</strong></div>')
    if scope.get("level") in EXECUTION_ERROR_TILE_LEVELS:
        value = metric_value("execution_err", scope.get("execution_err"))
        href = scope["metric_dir"] / "execution_err" / "index.html"
        linked = (
            f'<a href="{esc(rel(out_dir, href))}">{esc(value)}</a>'
            if value else ""
        )
        tiles.append(
            f'<div class="stat"><span>{esc(METRIC_LABEL["execution_err"])}</span>'
            f"<strong>{linked}</strong></div>"
        )
    return f'<div class="stats-panel"><div class="stats">{"".join(tiles)}</div></div>'


def cube_table(scope: dict, children: list[dict], out_dir: Path, first_label: str) -> str:
    rows = []
    for child in children:
        name = f'<a href="{esc(rel(out_dir, child["page"]))}">{brk(child["name"])}</a>'
        rows.append(
            f"""<tr>
<td class="profile">{name}</td>
<td class="dur">{cell(child, "time_sum", out_dir)}</td>
<td class="dur">{cell(child, "time_max", out_dir)}</td>
<td class="num cell">{cell(child, "v_count", out_dir)}</td>
<td class="num cell">{cell(child, "dv_count", out_dir)}</td>
<td class="num cell">{cell(child, "w_count", out_dir)}</td>
<td class="num cell">{cell(child, "dw_count", out_dir)}</td>
<td class="num cell">{cell(child, "g_count", out_dir)}</td>
<td class="num cell">{cell(child, "t_count", out_dir)}</td>
</tr>"""
        )
    return f"""<div class="table-wrap">
<table class="family-table compact">
<colgroup></colgroup><colgroup span="2"></colgroup>
<colgroup class="errors" span="2"></colgroup>
<colgroup class="warnings" span="2"></colgroup>
<thead>
<tr>
<th class="profile" rowspan="2">{esc(first_label)}</th>
<th class="num" colspan="2">Timing</th>
<th class="num group-err" colspan="2">{ICON["Violation"]} Errors</th>
<th class="num group-warn" colspan="2">{ICON["Warning"]} Warnings</th>
<th class="num" rowspan="2">{ICON["Good"]} Good</th>
<th class="num" rowspan="2">Total</th>
</tr>
<tr>
<th class="num">Sum</th><th class="num">Max</th>
<th class="num group-err">Total</th><th class="num group-err">Distinct</th>
<th class="num group-warn">Total</th><th class="num group-warn">Distinct</th>
</tr>
</thead>
<tbody>{"".join(rows) if rows else '<tr><td colspan="9">No lower-level records.</td></tr>'}</tbody>
</table></div>"""


def ranking_table(children: list[dict], metric: str, out_dir: Path, first_label: str) -> str:
    rows = []
    for child in children:
        display = metric_value(metric, child.get(metric))
        name = f'<a href="{esc(rel(out_dir, child["page"]))}">{brk(child["name"])}</a>'
        value = (
            f'<a href="{esc(rel(out_dir, scope_metric_target(child, metric)))}">{esc(display)}</a>'
            if display else ""
        )
        rows.append(f'<tr><td class="profile">{name}</td><td class="num cell">{value}</td></tr>')
    return f"""<div class="table-wrap"><table class="compact">
<thead><tr><th class="profile">{esc(first_label)}</th><th class="num">{esc(METRIC_LABEL[metric])}</th></tr></thead>
<tbody>{"".join(rows) if rows else '<tr><td colspan="2">No lower-level records.</td></tr>'}</tbody>
</table></div>"""


def pager(page_count: int, current: int) -> str:
    if page_count <= 1:
        return ""
    links = []
    for number in range(1, page_count + 1):
        filename = "index.html" if number == 1 else f"p{number}.html"
        links.append(
            f"<strong>{number}</strong>"
            if number == current else f'<a href="{filename}">{number}</a>'
        )
    return f'<p class="pager">Pages: {" · ".join(links)}</p>'


def write_execution_error_page(
    scope: dict,
    breadcrumbs: list[tuple[str, Path]],
) -> None:
    runs = sorted(
        (
            run for run in scope["runs"].values()
            if run.get("meta", {}).get("execution_error")
        ),
        key=lambda run: (
            str(run.get("family_id") or ""),
            str(run.get("profile_name") or ""),
            str(run.get("shacl_file") or ""),
        ),
    )
    if not runs:
        return
    path = scope["metric_dir"] / "execution_err" / "index.html"
    rows = []
    for run in runs:
        report_href = str(run.get("report_href") or "")
        shacl_file = esc(run.get("shacl_file") or "")
        report = (
            f'<a href="{esc(report_href)}" target="_blank" rel="noopener">{shacl_file}</a>'
            if report_href else shacl_file
        )
        rows.append(
            "<tr>"
            f'<td>{esc(run.get("family_id") or "")}</td>'
            f'<td>{esc(run.get("profile_name") or "")}</td>'
            f"<td>{report}</td>"
            f'<td class="num">{esc(run.get("http_status") or "Unknown")}</td>'
            f'<td><pre class="execution-error">{esc(run["meta"]["error_text"])}</pre></td>'
            "</tr>"
        )
    body = f"""
<p class="crumb">{crumb(breadcrumbs + [(scope["name"], scope["page"])], path.parent, METRIC_LABEL["execution_err"])}</p>
<h1>{esc(scope["name"])} · {esc(METRIC_LABEL["execution_err"])}</h1>
<p class="meta">{len(runs)} validation runs returned non-empty error text instead of a SHACL validation report.</p>
<div class="table-wrap"><table>
<thead><tr><th>Family</th><th>Ontology profile</th><th>SHACL file / response</th><th class="num">HTTP</th><th>Error</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table></div>
"""
    write(path, f'{METRIC_LABEL["execution_err"]} · {scope["name"]}', body)


def write_scope_pages(
    scope: dict,
    breadcrumbs: list[tuple[str, Path]],
    first_label: str,
    meta: str,
) -> None:
    base = scope["page"]
    out_dir = base.parent
    chunks = [
        scope["children"][offset:offset + PAGE_SIZE]
        for offset in range(0, max(len(scope["children"]), 1), PAGE_SIZE)
    ]
    for page_number, chunk in enumerate(chunks, 1):
        page_path = base if page_number == 1 else out_dir / f"p{page_number}.html"
        page_nav = pager(len(chunks), page_number)
        base_body = f"""
<p class="crumb">{crumb(breadcrumbs, page_path.parent, scope["name"])}</p>
<h1>{esc(scope["name"])}</h1>
<p class="meta">{meta}</p>
{summary_tiles(scope, page_path.parent) if page_number == 1 else ""}
{page_nav}
{cube_table(scope, chunk, page_path.parent, first_label)}
{page_nav}
"""
        write(page_path, f"{scope['name']} · SHACL cube", base_body)
    for metric in METRICS:
        ranked = sorted(
            (
                child
                for child in scope["children"]
                if metric_value(metric, child.get(metric))
            ),
            key=lambda child: (
                child.get(metric) is not None,
                float(child.get(metric) or 0),
                child["name"].lower(),
            ),
            reverse=True,
        )
        metric_dir = scope["metric_dir"] / metric
        ranked_chunks = [
            ranked[offset:offset + PAGE_SIZE]
            for offset in range(0, max(len(ranked), 1), PAGE_SIZE)
        ]
        for page_number, chunk in enumerate(ranked_chunks, 1):
            metric_path = metric_dir / ("index.html" if page_number == 1 else f"p{page_number}.html")
            page_nav = pager(len(ranked_chunks), page_number)
            metric_body = f"""
<p class="crumb">{crumb(breadcrumbs + [(scope["name"], base)], metric_path.parent, METRIC_LABEL[metric])}</p>
<h1>{esc(scope["name"])} · {esc(METRIC_LABEL[metric])}</h1>
<p class="meta">Lower-level records ordered by decreasing {esc(METRIC_LABEL[metric].lower())}.</p>
{page_nav}
{ranking_table(chunk, metric, metric_path.parent, first_label)}
{page_nav}
"""
            write(metric_path, f"{METRIC_LABEL[metric]} · {scope['name']}", metric_body)
    if scope.get("level") in EXECUTION_ERROR_TILE_LEVELS:
        write_execution_error_page(scope, breadcrumbs)


def source_link(leaf: dict) -> str:
    run = leaf["run"]
    return dc.github_blob(run["repo"], run["shacl_subpath"], leaf["line"] or None)


def write_focus_page(leaf: dict, severity: str, breadcrumbs: list[tuple[str, Path]]) -> Path:
    folder = "violation" if severity == "Violation" else "warning"
    path = leaf["page"].parent / folder / "index.html"
    items = unique_focus(leaf["v_items"] if severity == "Violation" else leaf["w_items"])
    rows: list[str] = []
    for item in items:
        focus = brk(item["focus"])
        if item["in_gdb"] and item["graphdb_href"]:
            focus = f'<a href="{esc(item["graphdb_href"])}" target="_blank" rel="noopener">{focus}</a>'
        github = (
            f'<a href="{esc(item["github_href"])}" target="_blank" rel="noopener">GitHub</a>'
            if item["github_href"] else ""
        )
        constraint = (
            f'<a href="{esc(item["source_href"])}" target="_blank" rel="noopener">'
            f'{brk(local_name(item["constraint_uri"] or item["source_shape_uri"]))}</a>'
            if item["source_href"] else brk(local_name(item["constraint_uri"] or item["source_shape_uri"]))
        )
        rows.append(
            f"<tr><td class=\"focus\">{focus}</td><td>{github}</td>"
            f"<td class=\"msg\">{esc(item['message'])}</td><td>{constraint}</td></tr>"
        )
    chunks = [
        rows[offset:offset + PAGE_SIZE]
        for offset in range(0, max(len(rows), 1), PAGE_SIZE)
    ]
    for page_number, chunk in enumerate(chunks, 1):
        page_path = path if page_number == 1 else path.parent / f"p{page_number}.html"
        page_nav = pager(len(chunks), page_number)
        body = f"""
<p class="crumb">{crumb(breadcrumbs, page_path.parent, severity)}</p>
<h1>{ICON[severity]} {esc(severity)} · {brk(leaf["name"])}</h1>
<p class="meta">{len(items)} distinct focus nodes for this individual shape.</p>
{page_nav}
<div class="table-wrap"><table>
<thead><tr><th>sh:focusNode</th><th>GitHub</th><th>sh:message</th><th>sh:sourceConstraint</th></tr></thead>
<tbody>{"".join(chunk) if chunk else '<tr><td colspan="4">None.</td></tr>'}</tbody>
</table></div>
{page_nav}"""
        write(page_path, f"{severity} · {leaf['name']}", body)
    return path


def write_shape_page(leaf: dict, breadcrumbs: list[tuple[str, Path]]) -> None:
    out = leaf["page"]
    out_dir = out.parent
    source = source_link(leaf)
    run = leaf["run"]
    status = (
        "Distinct error" if leaf["dv_count"]
        else "Distinct warning" if leaf["dw_count"]
        else "Good shape" if leaf["g_count"]
        else "Result-only shape"
    )
    violation = write_focus_page(leaf, "Violation", breadcrumbs + [(leaf["name"], out)]) if leaf["v_count"] else None
    warning = write_focus_page(leaf, "Warning", breadcrumbs + [(leaf["name"], out)]) if leaf["w_count"] else None

    def leaf_tile(label: str, value: object, href: Path | str) -> str:
        display = str(value)
        if isinstance(href, str) and href.startswith(("http://", "https://")):
            target = href
        else:
            target = rel(out_dir, href)
        linked = f'<a href="{esc(target)}">{esc(display)}</a>' if display not in ("0", "") else ""
        return f'<div class="stat"><span>{esc(label)}</span><strong>{linked}</strong></div>'

    tiles = (
        leaf_tile("File run time", run["duration_disp"], out)
        + leaf_tile("Errors", leaf["v_count"], violation or out)
        + leaf_tile("Distinct errors", leaf["dv_count"], source)
        + leaf_tile("Warnings", leaf["w_count"], warning or out)
        + leaf_tile("Distinct warnings", leaf["dw_count"], source)
        + leaf_tile("Good shape", leaf["g_count"], source)
        + leaf_tile("Total shapes", leaf["t_count"], source)
    )
    source_label = f'{run["shacl_file"]}:L{leaf["line"]}' if leaf["line"] else run["shacl_file"]
    source_html = f'<a id="evidence" href="{esc(source)}" target="_blank" rel="noopener">{esc(source_label)}</a>'
    body = f"""
<p class="crumb">{crumb(breadcrumbs, out_dir, leaf["name"])}</p>
<h1>{brk(leaf["name"])}</h1>
<p class="meta">Shape file {source_html} · {esc(leaf["kind"])} · {esc(status)}.<br>
The SHACL-file run time is repeated as context and is not summed across shape rows.</p>
<div class="stats-panel"><div class="stats">{tiles}</div></div>
<h2>Grounding</h2>
<p class="note">The source declaration grounds the distinct/good/total measures.
Error and warning measures open their focus-node evidence pages.</p>
"""
    write(out, f"{leaf['name']} · SHACL shape", body)


def assign_pages(cube: dict) -> None:
    cube["page"] = ROOT / "index.html"
    cube["metric_dir"] = DASH / "all" / "m"
    for repo in cube["children"]:
        repo["page"] = DASH / "r" / repo["id"] / "index.html"
        repo["metric_dir"] = repo["page"].parent / "m"
        for family in repo["children"]:
            family["page"] = repo["page"].parent / "f" / family["id"] / "index.html"
            family["metric_dir"] = family["page"].parent / "m"
            for profile in family["children"]:
                profile["page"] = family["page"].parent / "p" / profile["id"] / "index.html"
                profile["metric_dir"] = profile["page"].parent / "m"
                for leaf in profile["children"]:
                    leaf["page"] = profile["page"].parent / "s" / leaf["id"] / "index.html"


def build() -> Path:
    config = dc.load_config()
    catalog = dc.build_catalog(config)
    index = cr.build_shacl_index()
    if DASH.exists():
        shutil.rmtree(DASH)
    DASH.mkdir()
    runs = collect_runs(catalog, index)
    cube = build_cube(catalog, runs)
    assign_pages(cube)
    assert_rollups(cube)

    root_meta = (
        "Configured shape repositories. Every measure links to the next level where it is grounded. "
        "Timing sum/max use unique SHACL-file validation runs."
    )
    write_scope_pages(cube, [], "Repository", root_meta)
    for repo in cube["children"]:
        repo_cfg = repo["repo"]
        repo_link = dc.github_tree(repo_cfg)
        repo_meta = (
            f'<a href="{esc(repo_link)}" target="_blank" rel="noopener">'
            f'{esc(repo_cfg["github_repository"])}</a> · aggregation by configured family.'
        )
        repo_crumbs = [("All repositories", cube["page"])]
        write_scope_pages(repo, repo_crumbs, "Family", repo_meta)
        for family in repo["children"]:
            family_crumbs = repo_crumbs + [(repo["name"], repo["page"])]
            write_scope_pages(
                family,
                family_crumbs,
                "Ontology profile",
                "Ontology profiles are resolved from PROF manifests; shared artifacts are counted once.",
            )
            for profile in family["children"]:
                profile_crumbs = family_crumbs + [(family["name"], family["page"])]
                ontology = (
                    f'<a href="{esc(dc.github_blob(profile["repo"], profile["ontology_subpath"]))}" '
                    f'target="_blank" rel="noopener">{esc(profile["ontology_file"])}</a>'
                    if profile["ontology_subpath"] else "No single ontology mapping"
                )
                write_scope_pages(
                    profile,
                    profile_crumbs,
                    "Individual shape",
                    f"Ontology: {ontology}. Timing aggregates unique SHACL-file runs; "
                    "shape rows repeat their containing file-run time.",
                )
                shape_crumbs = profile_crumbs + [(profile["name"], profile["page"])]
                for leaf in profile["children"]:
                    write_shape_page(leaf, shape_crumbs)
    print(
        f"Cube: {len(cube['children'])} repositories, {len(runs)} runs, "
        f"{cube['t_count']} individual shapes"
    )
    return ROOT / "index.html"


if __name__ == "__main__":
    print(f"Dashboard: {build()}")
