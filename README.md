# ReliCapGrid × Application-Profiles SHACL evaluation

SHACL validation of the **ReliCapGrid** test data against the CGMES
"Complex" (and related) SHACL shapes, plus a script that collects every
`sh:ValidationResult` from all the per-profile reports into a single
browsable table.

## Where the SHACL shapes come from

The shapes validated here are the `*.ttl` files in
**[`nikolatulechki/application-profiles-library`](https://github.com/nikolatulechki/application-profiles-library/tree/main)**,
specifically
[`CGMES/CurrentRelease/SHACL/`](https://github.com/nikolatulechki/application-profiles-library/tree/main/CGMES/CurrentRelease/SHACL)
(a working copy of ENTSO-E's
[`entsoe/application-profiles-library`](https://github.com/entsoe/application-profiles-library)).

Every `sh:sourceShape` / `sh:sourceConstraint` in the generated table
links back to the exact line of its defining `.ttl` on GitHub, e.g.
`…/blob/main/CGMES/CurrentRelease/SHACL/<file>.ttl#L<line>`.

The data being validated is **ReliCapGrid** (ENTSO-E's reliability +
capacity test models for 9 fictional TSOs), loaded into a GraphDB
repository named `relicapgrid`.

## Repository layout

```
ap-relicap-eval/
├── <PROFILE-SHACL>/            # one folder per validated SHACL file
│   ├── validation-report.ttl   # GraphDB SHACL report (rdf4j ValidationReport)
│   ├── timing.txt              # file, HTTP status, duration, finished_at
│   ├── run-status.txt          # present for some runs
│   └── sparql-queries.txt      # present for some runs
├── collect-results.py          # builds the combined table (HTML + CSV)
├── validation-results.html     # combined table, clickable links + filter box
├── validation-results.csv      # same data + raw resolved URLs
├── validate-all.sh             # validate every SHACL file against GraphDB
├── continue-validate.sh        # resume a batch, skipping done/slow files
└── batch.log                   # batch run log
```

Each profile folder is named after its source SHACL file (folder
`<name>` ⇄ `…/SHACL/<name>.ttl`).

## The combined table (`collect-results.py`)

Parses all `*/validation-report.ttl` and emits one row per
`sh:ValidationResult` with these columns:

| Column | Notes |
| --- | --- |
| `Profile` | source SHACL file the result came from |
| `sh:focusNode` | links to the GraphDB resource viewer for `relicapgrid` |
| `rsx:shapesGraph` | |
| `sh:resultPath` | |
| `sh:sourceConstraint` | links to the exact line in the SHACL file on GitHub (SPARQL constraints only) |
| `sh:sourceConstraintComponent` | |
| `sh:resultSeverity` | |
| `sh:resultMessage` | |
| `sh:sourceShape` | links to the exact line in the SHACL file on GitHub |
| `sh:value` | present on most results |

Run it (no dependencies beyond the Python 3 standard library):

```bash
python3 collect-results.py
```

### Per-constraint cap

Results are capped **per constraint** — keyed by
`(Profile, sh:sourceShape, sh:sourceConstraintComponent)` — to keep the
table to a manageable size. Change the cap at the top of the script:

```python
MAX_PER_CONSTRAINT = 100   # set to None for no limit
```

## A note on truncation in the source reports

GraphDB's SHACL validator applies two hard caps to each report:

- **1,000 per constraint component** — a single shape/component stops
  emitting after 1,000 violations.
- **10,000 per report** — the whole report stops once the total reaches
  10,000.

When either cap is hit the report carries `rdf4j:truncated true`, and the
result count for that profile is a **lower bound**, not the true number
of violations. Profiles flagged this way: re-run validation with higher
`validationResultsLimitPerConstraint` / `validationResultsLimitTotal` for
exact counts.

## How the reports were produced

`validate-all.sh` POSTs each SHACL file to a local GraphDB SHACL
validation endpoint and saves the Turtle report per profile:

```bash
curl -X POST --header 'Accept: text/turtle' \
  'http://localhost:7200/rest/repositories/relicapgrid/validate/file' \
  -F 'file=@<shape>.ttl;type=text/turtle'
```

`continue-validate.sh` resumes a partial batch, skipping profiles that
already have a `timing.txt` and a configurable skip-list of shapes whose
validation hangs/times out.
