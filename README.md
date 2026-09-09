# ReliCapGrid ENTSO-E × Application-Profiles SHACL evaluation

SHACL validation of the **ReliCapGrid ENTSO-E** test data against the CGMES
and NCP (Network Code Profiles) Application-Profiles shapes, with a script
that gathers every `sh:ValidationResult` from all the per-profile reports
into one browsable table.

**[View the dashboard →](https://nataschake.github.io/relicap-ap-shacl-eval/)**

## Links

- **Shapes** — [`entsoe/application-profiles-library`](https://github.com/entsoe/application-profiles-library/tree/main), specifically [`CGMES/CurrentRelease/SHACL/`](https://github.com/entsoe/application-profiles-library/tree/main/CGMES/CurrentRelease/SHACL) and [`NCP/CurrentRelease/SHACL/`](https://github.com/entsoe/application-profiles-library/tree/main/NCP/CurrentRelease/SHACL).
- **Data** — [`entsoe/relicapgrid`](https://github.com/entsoe/relicapgrid),
  loaded into the GraphDB repository
  [`relicapgrid` on a local GraphDB instance](http://localhost:7200/).
- **Results** — [dashboard on GitHub Pages](https://nataschake.github.io/relicap-ap-shacl-eval/), with family matrices, timings, and focus-node drill-down pages.

## Layout

```
ap-relicap-eval/
├── <PROFILE-SHACL>/            # one folder per validated SHACL file
│   └── validation-report.ttl   # GraphDB SHACL report (+ timing.txt, etc.)
├── collect-results.py          # CSV export + stub validation-results.html; invokes the dashboard
├── collect-timings.py          # timing parser/formatter + timing-history refresh
├── dashboard-config.json       # repositories, families, local paths, GitHub links
├── dashboard_config.py         # validated config + PROF source catalog
├── build_dashboard.py          # stable dashboard entry point
├── cube_dashboard.py           # cube construction and static page generation
├── dashboard.css               # shared styles for the dashboard
├── dashboard/r/                # repository/family/profile/shape pages
├── validation-results.html     # short pointer to the dashboard
├── validation-results.csv      # validation data + raw resolved URLs (capped per constraint)
├── index.html                  # dashboard: frontmatter stats + links to family pages
├── validate-all.sh             # validate every SHACL file against GraphDB and generate reports
└── continue-validate.sh        # resume a batch, skipping done/slow files
```

Each profile folder is named after its source SHACL file
(`<name>/` ⇄ `…/SHACL/<name>.ttl`).

## The dashboard

`build_dashboard.py` (also run from `collect-results.py`) writes a four-dimensional
static cube:

```
all repositories → repository → family → ontology profile → individual SHACL shape
```

- `index.html` contains one aggregation row per configured shapes repository.
- `dashboard/r/<repository>/index.html` aggregates its configured families.
- `dashboard/r/<repository>/f/<family>/index.html` aggregates ontology profiles.
- `dashboard/r/<repository>/f/<family>/p/<profile>/index.html` shows individual
  shapes. The frontmatter links to the profile's RDFS ontology on GitHub.
- `.../s/<shape>/index.html` grounds one shape. Its frontmatter links to the exact
  SHACL declaration line; error and warning counts open focus-node evidence.

Every level uses the same measures: timing sum/max, errors, warnings, distinct
errors, distinct warnings, good shapes, and total shapes. Validation measures
are additive, and the build checks every rollup. A shape is classified in exactly
one bucket (error takes precedence over warning), so:

```
distinct errors + distinct warnings + good shapes = total shapes
```

Errors and warnings count distinct focus nodes **per individual shape** and are
summed upward. Timing uses unique SHACL-file validation runs, so a run is counted
once at profile/family/repository levels. Until per-shape timings are queried
from GraphDB, each shape repeats its containing file's run time as non-additive
context.

All non-zero measures are links. Aggregate links open lower-level rows ordered
by that measure. Shape-level error/warning links open paginated evidence with
`sh:focusNode`, GitHub, `sh:message`, and `sh:sourceConstraint` columns.

`collect-results.py` still writes `validation-results.csv`.
`collect-timings.py` refreshes `.timing-history.json`; timing pages are part of
the main dashboard hierarchy.

```bash
python3 build_dashboard.py
```

Links on the drill-down pages:

- `sh:focusNode` → GraphDB resource explorer when the IRI is in `relicapgrid`; otherwise unlinked text.
- GitHub → code search in `entsoe/relicapgrid` for the same IRI.
- `sh:sourceConstraint` / shape name → the matching constraint in the profile SHACL file (`CGMES/SHACL` or `NCP/SHACL`).

### Configuration

`dashboard-config.json` is the source of repository/family configuration. A
repository defines its checkout, upstream GitHub repository/ref, evaluation
results root, and an extensible family list. Each family defines SHACL, RDFS,
and PROF directories plus optional `profile_overrides`.

PROF manifests provide the SHACL-to-ontology mapping, including CGMES
many-SHACL-to-one-RDFS mappings. Artifacts referenced by multiple profiles are
counted once under `Shared constraints (no single ontology)`. An explicit
override maps a SHACL filename to a PROF-derived profile ID.

The CSV from `collect-results.py` is capped **per constraint** — keyed by
`(Profile, sh:sourceShape, sh:sourceConstraintComponent)`. Dashboard counts
are not capped (they still cannot exceed GraphDB’s own report limits).
Change the CSV cap at the top of `collect-results.py`:

```python
MAX_PER_CONSTRAINT = 100   # set to None for no limit
```

## Truncation in the source reports

GraphDB caps each report at **1,000 results per constraint component** and
**10,000 per report**. When a cap is hit the report carries
`rdf4j:truncated true` and that profile's count is a **lower bound**.
Re-run with higher `validationResultsLimitPerConstraint` /
`validationResultsLimitTotal` for exact counts.

## How the reports were produced

`validate-all.sh` POSTs each SHACL file to the GraphDB validation endpoint,
saves the Turtle report per profile, refreshes timing history, and generates
the dashboard and `validation-results.html` in the same run. Validation runs
against the `relicapgrid` repository on a local
GraphDB instance at [localhost:7200](http://localhost:7200/), which requires
authentication. Export `GDBUSER` / `GDBPASS` before running the script:

```bash
export GDBUSER=<username>
export GDBPASS=<password>
./validate-all.sh
```

The script logs in to obtain a bearer token, then validates each file:

```bash
# authenticate and extract the bearer token
auth_header=$(curl -s 'http://localhost:7200/rest/login/<username>' \
  -X POST -H 'X-GraphDB-Password: <password>' -I | grep -i "authorization:")
token=${auth_header#*: }

# validate a shape file using the token
curl -X POST --header 'Accept: text/turtle' \
  -H "Authorization: Bearer ${token%$'\r'}" \
  'http://localhost:7200/rest/repositories/relicapgrid/validate/file' \
  -F 'file=@<shape>.ttl;type=text/turtle'
```

`continue-validate.sh` resumes a partial batch, skipping profiles that
already have a report and a configurable skip-list of shapes whose
validation hangs. Both scripts iterate over the CGMES and NCP SHACL
folders.

If a shape file has a syntax error GraphDB returns HTTP 500; that
folder then holds the parser error instead of a report and contributes
no rows (check `timing.txt` / `batch.log` for the HTTP status).
