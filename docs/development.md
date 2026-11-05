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
