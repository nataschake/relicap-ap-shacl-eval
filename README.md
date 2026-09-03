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
  [`relicapgrid` on cim.ontotext.com](https://cim.ontotext.com/graphdb/).
- **Results** — [dashboard on GitHub Pages](https://nataschake.github.io/relicap-ap-shacl-eval/), with family matrices, timings, and focus-node drill-down pages.

## Layout

```
ap-relicap-eval/
├── <PROFILE-SHACL>/            # one folder per validated SHACL file
│   └── validation-report.ttl   # GraphDB SHACL report (+ timing.txt, etc.)
├── collect-results.py          # CSV export + stub validation-results.html; invokes the dashboard
├── collect-timings.py          # builds timing-results.html with current/previous timings
├── build_dashboard.py          # index.html + dashboard/ family and focus-node pages
├── dashboard.css               # shared styles for the dashboard
├── dashboard/                  # family pages (f/) + focus-node pages (p/, paginated)
├── validation-results.html     # short pointer to the dashboard
├── validation-results.csv      # validation data + raw resolved URLs (capped per constraint)
├── timing-results.html         # per-profile timing table with previous/current durations
├── index.html                  # dashboard: frontmatter stats + links to family pages
├── validate-all.sh             # validate every SHACL file against GraphDB and generate reports
└── continue-validate.sh        # resume a batch, skipping done/slow files
```

Each profile folder is named after its source SHACL file
(`<name>/` ⇄ `…/SHACL/<name>.ttl`).

## The dashboard

`build_dashboard.py` (also run from `collect-results.py`) writes `index.html`:

- **Frontmatter** — one combined block: profiles tested, total/average/max
  check time, conforming and truncated reports, distinct errors/warnings
  (declared shapes), errors/warnings (distinct `sh:focusNode`s), good
  shapes, total shapes, HTTP errors. Distinct errors + Distinct warnings +
  Good = Total shapes. Family and profile tables use the same counters, so
  summing profiles yields the family totals and summing families yields the
  frontmatter. Family names on this page open the family dashboard.
- **Families** — CGMES then NCP. Each family name (section title)
  opens `dashboard/f/<family>/index.html`, which has the family summary
  (sum of check times, average, max, severity totals), a filter/sort row, and one results table in the same grouped style as the
  profile page: profile name, time, Errors (Total / Distinct), Warnings
  (Total / Distinct), good, total. HTTP status sits under the profile name.
  The profile name opens a table of
  `sh:PropertyGroup` rows (`rdfs:label` via `sh:group`). Error and warning
  columns are grouped: Total / Distinct errors, then Total / Distinct
  warnings, then good and total. Distinct (declared-shape) counts open the
  failing-shape list; Total (focus-node) counts open the focus-node list;
  good opens the passing-shape list. Zero counts are left blank.
- **Drill-down** — Violations and warnings list distinct `sh:focusNode`
  values (with `sh:message`). Each focus node opens the ReliCapGrid instance
  file that contains it; `sh:sourceConstraint` opens the matching constraint
  in the profile shape file. Good lists declared shapes that produced no
  violation or warning (shape names open the SHACL file).

`collect-results.py` still writes `validation-results.csv`.
`collect-timings.py` still writes `timing-results.html`.

```bash
python3 build_dashboard.py
```

Links on the drill-down pages:

- `sh:focusNode` → the ReliCapGrid instance file on GitHub that contains that UUID.
- `sh:sourceConstraint` / shape name → the matching constraint in the profile SHACL file (`CGMES/SHACL` or `NCP/SHACL`).

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
saves the Turtle report per profile, and then runs `collect-timings.py` so
both `validation-results.html` and `timing-results.html` are produced in the
same run:

```bash
curl -X POST --header 'Accept: text/turtle' \
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
