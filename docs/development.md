# Development and testing

Install dependencies using the [README setup](../README.md#setup), then run:

```bash
python -m pytest -q
```

## Windows test directory

The [build script](../packaging/build_windows.ps1) uses `build/pytest-temp` to avoid
shared temp-folder permission errors. Pytest clears this directory on each build;
do not store other files there. To use it manually:

```powershell
New-Item -ItemType Directory -Force -Path build | Out-Null
python -m pytest -q --basetemp=build/pytest-temp
```

## Browser checks

Set `DASHBOARD_PDF_BROWSER=chrome` or `msedge` before running the suite to include
PDF, navigation, interaction, year-selector, and large-preview checks. The browser
must be installed; these checks are otherwise skipped.

Set `DASHBOARD_PDF_ARTIFACT_DIR` to retain HTML, PDF, and screenshot artifacts.

## Dependencies and publication

Versions are pinned in `constraints.txt`; build dependencies are in
`packaging/requirements-build.txt`. Install `requirements-bootstrap.txt` before
upgrading dependencies and recheck advisories when pins change.

Follow the [publication checklist](../SECURITY.md#before-publishing) before pushing.

## Styling

[`workflow_dashboard/styles.css`](../workflow_dashboard/styles.css) is the single
source for authored CSS and presentation values. Its first `:root` block holds
the palette, font stacks, typography sizes, chart settings, observation column
widths, Excel settings, and native launcher measurements. Screen, navigation,
tooltip, responsive, and print rules follow it in the same file.

Edit the existing variables in that first block. For example:

```css
--font-ui: Arial;
--primary: #6d28d9;
--category-1: var(--primary);
--featured-background: linear-gradient(125deg, var(--primary-soft), var(--surface));
```

`--page-background`, `--card-background`, `--masthead-background`, and
`--featured-background` accept colors or gradients. Their CSS variable references
update normally in the browser, so future theme selectors or scripts can change
gradient stops without replacing component rules. Keep foreground contrast
readable when changing backgrounds. Reduced-motion and print rules remain in
the stylesheet.

Plotly, Excel, and Tk do not read CSS themselves. The small adapter in
[`theme.py`](../workflow_dashboard/theme.py) resolves literals and `var(--name)`
references from the first `:root` block when the Python process starts. Keep
tokens used by those renderers as concrete values: unitless chart sizes,
six-digit hex colors for Excel, and whitespace-separated integer lists for
margins and native padding pairs. Chart margins use CSS order: top, right,
bottom, left. Browser-only backgrounds may use ordinary CSS expressions such
as gradients or `color-mix()`. Native controls retain the operating system's
appearance; their explicit fonts, sizes, and spacing use the `--native-*` tokens.

Restart the launcher/CLI and regenerate outputs after editing the file. HTML
embeds the complete stylesheet, and charts and Excel embed their resolved
values; existing exports are snapshots. Live browser variable changes update
CSS presentation, while chart styling and workbook styling apply on generation.
JavaScript still measures tooltip positions and tab heights at runtime. Those
measurements depend on content and viewport size.

The Windows build bundles the stylesheet, and build fingerprints include it.
No CSS framework, external font download, or separate export asset is required.

## Synthetic UI previews

```bash
python -m tools.synthetic_preview
python -m tools.synthetic_preview --records 10000 --scenario edge
python -m tools.synthetic_preview --scenario empty
```

Defaults: 5,000 records, `mixed`, seed `42`, and the current UTC minute. Use
`--seed 123 --as-of 2026-11-12T17:00:00Z` for reproducible records; `--as-of`
requires a timezone. `empty` produces no cases.

Each run writes a fixture, isolated SQLite history, HTML, Excel, and CSV into a
fresh `outputs/synthetic-preview` folder, or `--output-dir`. Open the printed HTML
path. The tool uses fictional data without loading local settings or accessing
live records.

`mixed` includes the current and previous two calendar years, with most intake
in the last 210 days. Older snapshots are monthly; the latest 30 days are daily.
`edge` adds missing/invalid timing, long labels, and extra categories. Empty runs
contain only the current zero snapshot. History uses the same cases and closure
dates; interim workflow steps are approximate, not an event-log simulation.

Run `python -m pytest -q tests/test_synthetic_preview.py` for generator checks.
With the browser variable set, this also checks 10,000-case mixed and edge
previews at desktop and phone widths.
