# ReliCapGrid ENTSO-E × Application-Profiles SHACL evaluation

SHACL validation of the **ReliCapGrid ENTSO-E** test data against the CGMES
and NCP (Network Code Profiles) Application-Profiles shapes, with a script
that gathers every `sh:ValidationResult` from all the per-profile reports
into one browsable table.

**[View the results table →](https://nikolatulechki.github.io/relicap-ap-shacl-eval/)**

## Links

- **Shapes** — [`nikolatulechki/application-profiles-library`](https://github.com/nikolatulechki/application-profiles-library/tree/main)
  (working copy of ENTSO-E's
  [`entsoe/application-profiles-library`](https://github.com/entsoe/application-profiles-library)),
  specifically [`CGMES/CurrentRelease/SHACL/`](https://github.com/nikolatulechki/application-profiles-library/tree/main/CGMES/CurrentRelease/SHACL)
  and [`NCP/CurrentRelease/SHACL/`](https://github.com/nikolatulechki/application-profiles-library/tree/main/NCP/CurrentRelease/SHACL).
- **Data** — [`entsoe/relicapgrid`](https://github.com/entsoe/relicapgrid),
  loaded into the GraphDB repository
  [`relicapgrid` on cim.ontotext.com](https://cim.ontotext.com/graphdb/).
- **Results** — [results table on GitHub Pages](https://nikolatulechki.github.io/relicap-ap-shacl-eval/).

## Layout

```
ap-relicap-eval/
├── <PROFILE-SHACL>/            # one folder per validated SHACL file
│   └── validation-report.ttl   # GraphDB SHACL report (+ timing.txt, etc.)
├── collect-results.py          # builds the combined table (HTML + CSV)
├── validation-results.html     # combined table, clickable links + filter box
├── validation-results.csv      # same data + raw resolved URLs
├── index.html                  # redirect to the table (for GitHub Pages)
├── validate-all.sh             # validate every SHACL file against GraphDB
└── continue-validate.sh        # resume a batch, skipping done/slow files
```

Each profile folder is named after its source SHACL file
(`<name>/` ⇄ `…/SHACL/<name>.ttl`).

## The combined table

`collect-results.py` parses all `*/validation-report.ttl` and writes one
row per `sh:ValidationResult` to `validation-results.html` / `.csv`, with
columns: `Family` (CGMES or NCP), `Profile`, `Report`, `sh:focusNode`,
`sh:resultPath`, `sh:sourceConstraint`, `sh:sourceConstraintComponent`,
`sh:resultSeverity`, `sh:resultMessage`, `sh:sourceShape`, `sh:value`.

Links in the table:

- `sh:focusNode` → the [GraphDB resource viewer](https://cim.ontotext.com/graphdb/) for `relicapgrid`.
- `sh:sourceShape` / `sh:sourceConstraint` → the exact line in the shape's `.ttl` on GitHub.
- `Report` → that profile's `validation-report.ttl` in this repo.

Run it (Python 3 standard library only):

```bash
python3 collect-results.py
```

Results are capped **per constraint** — keyed by
`(Profile, sh:sourceShape, sh:sourceConstraintComponent)`. Change the cap
at the top of the script:

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

`validate-all.sh` POSTs each SHACL file to the GraphDB validation endpoint
and saves the Turtle report per profile:

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
