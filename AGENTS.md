# AGENTS.md — ReliCapGrid SHACL evaluation dashboard

This repository holds SHACL validation reports for **ReliCapGrid ENTSO-E** test data
against CGMES and NCP Application-Profile shapes, plus scripts that turn those
reports into a static HTML dashboard.

Agents working here should read this file first, then `README.md` for user-facing
documentation.

## Technical stack

| Layer | Technology |
|-------|------------|
| Validation | GraphDB SHACL validation API (`relicapgrid` on localhost:7200) |
| Report format | Turtle (`validation-report.ttl` per profile folder) |
| Build language | Python 3.10+ (stdlib only — no `requirements.txt`) |
| Batch orchestration | Bash (`validate-all.sh`, `continue-validate.sh`) |
| Dashboard output | Static HTML + CSS + small inline JavaScript |
| Styling | `dashboard.css` — Prime/Bootstrap design tokens, Rubik font, gray ground, white cards |
| Hosting | GitHub Pages (`index.html` at repo root) |
| External repos | [`entsoe/application-profiles-library`](https://github.com/entsoe/application-profiles-library) (SHACL shapes), [`entsoe/relicapgrid`](https://github.com/entsoe/relicapgrid) (instance data) |
| GraphDB links | Resource explorer + SPARQL presence lookup; GraphDB link omitted when IRI absent |

There is no test suite. Correctness is verified by rebuilding the dashboard and
spot-checking generated HTML.

## Repository layout

```
relicap-ap-shacl-eval/
├── <PROFILE-SHACL>/              # one folder per validated SHACL file
│   ├── validation-report.ttl     # GraphDB SHACL report (or parser error text)
│   └── timing.txt                # http_status, duration_seconds, finished_at
├── dashboard-config.json         # source repositories/families and link config
├── dashboard_config.py           # config validation + PROF catalog
├── build_dashboard.py            # stable dashboard entry point
├── cube_dashboard.py             # cube metrics + page generator
├── collect-results.py            # CSV export + calls build_dashboard
├── collect-timings.py            # timing parsing/formatting + history refresh
├── dashboard.css                 # shared styles (referenced with relative paths)
├── dashboard/                    # generated drill-down pages (safe to delete/rebuild)
│   └── r/<REPOSITORY>/
│       ├── m/<METRIC>/           # family ranking for one measure
│       └── f/<FAMILY>/
│           ├── m/<METRIC>/       # ontology-profile ranking
│           └── p/<PROFILE>/
│               ├── m/<METRIC>/   # individual-shape ranking
│               └── s/<SHAPE>/    # source grounding + focus-node evidence
├── index.html                    # landing dashboard (generated)
├── validation-results.csv        # flat export (capped per constraint)
├── validation-results.html       # redirect stub → index.html
├── validate-all.sh               # full batch validation + report generation
├── continue-validate.sh          # resume partial batch
└── batch.log                     # validation run log
```

Each profile folder name matches its SHACL filename without extension
(`Equipment-AP-Con-Simple-SHACL/` ⇄ `…/SHACL/Equipment-AP-Con-Simple-SHACL.ttl`).

Source checkouts and evaluation-result roots are declared in
`dashboard-config.json`; paths are resolved relative to this repository.

## Architecture patterns

### Static site generation

The dashboard is fully pre-rendered HTML. There is no server-side runtime.
`build_dashboard.py` delegates to `cube_dashboard.py`, which:

1. Deletes and recreates `dashboard/`.
2. Loads configured repositories/families and PROF-derived profile mappings.
3. Parses each validation report and each declared SHACL shape.
4. Builds individual-shape leaves and rolls them up through ontology profile,
   family, repository, and global scopes.
5. Asserts validation sums and unique timing-run identities at every boundary.
6. Queries GraphDB (SPARQL) to decide focus-node link targets and writes pages.

Keep pages small: paginate large evidence tables at 1,500 rows.

### Module loading

`cube_dashboard.py` loads sibling scripts by filename (not package import):

```python
cr = _load("collect_results", "collect-results.py")
ct = _load("collect_timings", "collect-timings.py")
```

Reuse helpers from `collect-results.py` and `collect-timings.py` rather than
duplicating parsing or link logic.

### Hierarchical navigation

```
index.html
  └── dashboard/r/<REPOSITORY>/index.html
        └── f/<FAMILY>/index.html
              └── p/<ONTOLOGY-PROFILE>/index.html
                    └── s/<INDIVIDUAL-SHAPE>/index.html
```

- Each non-zero aggregate measure links to `m/<METRIC>/index.html`, where the
  next-level rows are sorted by that measure.
- Ontology-profile frontmatter links the mapped RDFS artifact on GitHub.
- Individual-shape frontmatter links the exact SHACL declaration line.
- Shape error/warning counts link to focus-node evidence; distinct/good/total
  counts link to source grounding.

### Metrics model (additive, reproducible)

The canonical leaf is one declared SHACL shape in one SHACL file:

| Column | Meaning |
|--------|---------|
| **Errors** (Total) | Distinct `sh:focusNode` values with `sh:Violation`, per shape |
| **Distinct errors** | Shapes that produced at least one violation |
| **Warnings** (Total) | Distinct `sh:focusNode` values with `sh:Warning`, per shape |
| **Distinct warnings** | Warning shapes with no violation |
| **Good** | Declared shapes with neither violation nor warning |
| **Total** | Distinct errors + Distinct warnings + Good |

All validation measures are sums of leaves. Error precedence keeps shape buckets
exclusive. Timing sum/max uses the set of unique SHACL-file runs attached to a
scope, so shared shapes never multiply runtime. Shape pages repeat the containing
file-run time as non-additive context until per-shape SPARQL timings are available.

### Focus-node link resolution

During `build()`, `assign_focus_gdb_presence()` batch-queries GraphDB and sets
`in_gdb` on each result item:

- **GraphDB** — `sh:focusNode` column links to resource explorer (`…/resource?uri=…&repositoryId=relicapgrid&role=all`) when the IRI is present in the repository; the cell is plain text otherwise.
- **GitHub** — separate column: code search in `entsoe/relicapgrid` (UUID substring or full IRI) when a search query can be formed.

Always use `role=all`, not `role=subject`. Presence check uses SPARQL batched in
chunks of 100 (`GDB_LOOKUP_CHUNK` in `collect-results.py`). Network failure logs
to stderr and omits GraphDB links for that batch.

### SHACL shape indexing

`build_shacl_index()` maps every subject URI in each SHACL file to its line
number. Turtle subjects start at column 0 in these files — rely on that for
GitHub `#L` links. Search order: current profile file first, then other indexed
files.

PROF RDF/XML manifests map constraint artifacts to vocabulary artifacts.
If an artifact appears in several manifests, keep one synthetic shared profile;
never duplicate its validation measures across ontology profiles.

## Build commands

### Regenerate dashboard only (most common for agents)

Requires network access to GraphDB for focus-node presence lookup:

```bash
python3 build_dashboard.py
```

Or via the collect pipeline (also refreshes CSV):

```bash
python3 collect-results.py
```

Refresh timing history only:

```bash
python3 collect-timings.py
```

### Full validation batch (requires GraphDB credentials)

```bash
export GDBUSER=<username>
export GDBPASS=<password>
./validate-all.sh
```

This validates every SHACL file, writes per-profile reports, refreshes timing
history, then runs `collect-results.py` and `build_dashboard.py`.

Resume a partial batch:

```bash
./continue-validate.sh
```

### Local preview

Serve over HTTP (not `file://` — browser security blocks local navigation):

```bash
python3 -m http.server 8765 --bind 127.0.0.1
# open http://127.0.0.1:8765/index.html
```

## Coding rules and constraints

### HTML generation

- Escape all dynamic text with `esc()` (`html.escape(..., quote=True)`).
- Long IRIs use `brk()` for `<wbr>` break opportunities.
- Relative links: compute with `rel_href(from_dir, target)` so nested pages resolve
  correctly.
- CSS href: `css_href(from_dir)` — depth-relative path to root `dashboard.css`.
- Wrap tables in `<div class="table-wrap">` for resize support.
- **Zero counts render as empty cells**, not `"0"` (`count_cell()`).
- **Icons in column headers only** (red circle = Violation, yellow triangle =
  Warning, green circle = Good). Cells contain clickable numbers, not icons.
- **Column alignment**: numeric columns centered (`.num.cell`); repository,
  family, profile, and shape columns left-aligned.

### Table column order

**All aggregation tables** (`cube_table`):

Next-level member · Timing (Sum / Max) · Errors (Total / Distinct) ·
Warnings (Total / Distinct) · Good · Total

**Drill-down focus-node lists**:

`sh:focusNode` · GitHub · `sh:message` · `sh:sourceConstraint` (no separate severity or
SHACL columns — severity is implied by the page path). The focus-node IRI links to
GraphDB when present; GitHub is a separate column.

### Client-side behaviour

`TABLE_SCRIPT` adds column drag handles on `.table-wrap`. Metric ordering is
pre-rendered into `m/<METRIC>/index.html` rather than relying on JavaScript.

### Configuration

Edit `dashboard-config.json` for shape repositories, local checkouts, GitHub
repository/ref, evaluation-result roots, families, SHACL/RDFS/PROF directories,
and optional SHACL-file-to-profile overrides. Families and repositories are
extensible lists. Data snapshot, GraphDB, and instance GitHub settings live in
the top-level `data` object.

`MAX_PER_CONSTRAINT` in `collect-results.py` only controls the CSV row cap;
dashboard counts are not capped by it.

### Source report limits

GraphDB caps reports at **1,000 results per constraint component** and
**10,000 per report**. Truncated reports carry `rdf4j:truncated true`; dashboard
counts for those profiles are lower bounds. Do not silently treat truncated counts
as exact.

### HTTP errors

Non-200 validation responses store error text in `validation-report.ttl`.
`collect_validation()` routes these to `http_errors` and generates
`dashboard/http/<profile>.html`. They contribute no validation rows.

### Do not

- Commit secrets (`GDBUSER`, `GDBPASS`).
- Add third-party Python dependencies without explicit user request (project uses
  stdlib only).
- Link focus nodes only to GraphDB — always offer GraphDB (when present) and GitHub links separately.
- Link shapes or constraints to RDFS vocabulary files — link to the profile SHACL
  file on GitHub.
- Duplicate family listings on the index page (family name in section title is
  the link; no separate “Open X results table” links).
- Show “reports parsed” in frontmatter (removed intentionally).
- Use full-width layout — dashboard content stays in a constrained card width
  (`max-width` in CSS).

## File ownership

| Task | Primary file |
|------|----------------|
| Dashboard structure, pages, metrics | `build_dashboard.py` |
| Report parsing, CSV, GraphDB SPARQL lookup, GitHub shape links | `collect-results.py` |
| Timing parsing, history, duration formatting | `collect-timings.py` |
| Visual theme, table layout, icons | `dashboard.css` |
| Batch validation | `validate-all.sh` |

When changing link behaviour, update both the implementation and the meta text on
`index.html` / drill-down pages / `README.md`.

## CI

`.github/workflows/dashboard.yml` checks out this repository and
`entsoe/application-profiles-library`, rebuilds the complete dashboard on push
to `main`, stages the entry points, CSS, CSV, and complete `dashboard/` tree,
then deploys that tree to GitHub Pages. It does not rerun SHACL validation.
