# Development and testing

Follow the [README setup](../README.md#setup) to install development dependencies.
Run the normal test suite with:

```bash
python -m pytest -q
```

## Windows test directory

The [Windows build script](../packaging/build_windows.ps1) uses `build/pytest-temp`
instead of the shared Windows pytest temp folder to avoid permission errors.
Pytest clears this dedicated directory on each build; do not store other files
there. To run tests separately with the same setting, create the parent directory
first:

```powershell
New-Item -ItemType Directory -Force -Path build | Out-Null
python -m pytest -q --basetemp=build/pytest-temp
```

## Browser checks

Real browser PDF, navigation, and interaction checks are opt-in and require an
installed Chrome or Edge. Set `DASHBOARD_PDF_BROWSER=chrome` or
`DASHBOARD_PDF_BROWSER=msedge` in the environment, then run:

```bash
python -m pytest -q tests/test_dashboard_pdf.py tests/test_dashboard_navigation.py tests/test_dashboard_interactions.py
```

Optionally set `DASHBOARD_PDF_ARTIFACT_DIR` to retain synthetic HTML and PDF samples
for visual inspection. Without the browser variable, the normal test suite skips
these checks.

## Dependencies and publication

Runtime and development versions are pinned with `constraints.txt`; Windows build
dependencies use `packaging/requirements-build.txt`. Upgrade the installer using
`requirements-bootstrap.txt` first. Recheck dependency advisories when pins change.

Before pushing, follow the [publication instructions](../README.md#publication)
and [security checklist](../SECURITY.md).

## Synthetic UI previews

Generate a standalone preview without API access or local configuration:

```bash
.venv/bin/python -m tools.synthetic_preview
.venv/bin/python -m tools.synthetic_preview --records 10000 --scenario edge
.venv/bin/python -m tools.synthetic_preview --scenario empty
```

The default is 5,000 records, `mixed`, seed `42`, and the current UTC minute.
Use `--seed 123 --as-of 2026-11-12T17:00:00Z` to reproduce the same data.
`--as-of` requires an explicit timezone. `--records` accepts zero; `empty`
always generates zero records regardless of the count.

Each run creates a fresh folder under the ignored `outputs/synthetic-preview`
(or `--output-dir`) with an API-shaped JSON fixture, isolated SQLite history,
and the standard HTML, Excel, and CSV exports. The command prints parameters and
paths; open the printed HTML file directly in a browser. It never reads `.env`,
desktop settings, saved reports, or live records; the roster and title are fictional.

`mixed` covers uneven workloads, age bands, action buckets, and recent and older
completions with valid timestamps. `edge` adds long Unicode/HTML-sensitive labels,
extra categories, missing fields, invalid chronology, and completeness warnings.
Populated runs include 30 daily snapshots; empty runs contain only the current
zero snapshot. Intake varies by weekday and over the season; processing durations
and activity cadences vary by case. Historical snapshots use those same cases:
submissions retain their dates and cases become completed at their closure time,
so arrivals and closures reconcile with open-case counts. Interim workflow steps
are approximate, not an event-log simulation; deliberately invalid edge timing is
preserved in earlier snapshots. Only the final snapshot is exported. Record data
is reproducible; run IDs and output folders vary.

Run `python -m pytest -q tests/test_synthetic_preview.py` for generator and isolation
checks. With `DASHBOARD_PDF_BROWSER=chrome` (or `msedge`), this also checks 10,000-record
mixed and edge dashboards offline at desktop and narrow widths. Set
`DASHBOARD_PDF_ARTIFACT_DIR` to retain previews and screenshots. Large scatterplots
and observation tables may reveal rendering limits; the tool does not change the
production dashboard or simulate real business accuracy.
