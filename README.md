# sd-transfer-team-analytics

Transfer Team dashboard for open cases, backlog, workflow aging, completions,
submitter activity, and case observations.

## Setup

Python 3.13 is tested. Bundled records, staff names, and tenant URLs are synthetic.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-bootstrap.txt
python -m pip install -r requirements-dev.txt
```

For live CLI use, copy [`.env.example`](.env.example) to `.env` and configure an
HTTPS endpoint you are authorized to access. Browser sign-in is the default;
keep credentials out of `.env` when using it.

`WORKFLOW_FILTER` matches one workflow case-insensitively, trimming outer
whitespace only. A missing match aborts generation. Without a filter, a nonempty
source must contain only one named workflow. `WORKFLOW_DASHBOARD_TITLE` sets the
display title separately.

## Commands

Generate a report from the bundled fixture:

```bash
python -m workflow_dashboard inspect --source fixture
python -m workflow_dashboard run --source fixture
```

For live records, complete SSO in the separate Edge window:

```bash
python -m workflow_dashboard inspect --source api
python -m workflow_dashboard run --source api
```

`inspect` checks one page and prints field names and counts without record values
or writing files. `run` fetches all pages and validates completeness before
creating outputs. Existing bearer-token integrations can explicitly use
`--auth env`; only that mode loads saved credentials.

For larger fictional datasets and multi-year history, see
[synthetic UI previews](docs/development.md#synthetic-ui-previews).

## Desktop sign-in and generation

On Windows with Edge installed:

```bash
python -m workflow_dashboard desktop
```

Select **Generate Dashboard**, choose an output folder, complete sign-in and MFA,
and open the eTrieve workflow dashboard if needed. Each generation asks for a
folder, starting from the last selection. A successful report opens automatically.

Copy [`desktop_settings.toml.example`](workflow_dashboard/desktop_settings.toml.example)
to an ignored `settings.toml` and customize it. Load it with
`desktop --settings /path/to/settings.toml`, or place it in the per-user location
below. Desktop settings accept no credentials or custom headers; the app does
not load `.env`.

Each attempt uses fresh browser sign-in without your usual browser profile or
saved sessions. Sign-in times out after ten minutes; API requests default to
30 seconds with a 30-minute overall fetch budget. A `401` requires a fresh run;
a `403` indicates missing permissions. Cancelled or incomplete fetches leave
existing outputs and history intact. Cancellation is available during sign-in
and fetching; file generation finishes before the app closes.

Pilot sign-in and workplace browser policy before distribution. If policy blocks
browser control, use an IT-supported OAuth integration.

After an error, **Send Error Logs** opens a preview; **Copy Logs** copies it for
manual sharing. Nothing is uploaded automatically. See [Security](SECURITY.md).

Exports go into a dated subfolder of the chosen destination. History and settings
stay per user:

```text
%LOCALAPPDATA%\WorkflowTransferDashboard\history\workflow_history.sqlite
%LOCALAPPDATA%\WorkflowTransferDashboard\preferences.json
%LOCALAPPDATA%\WorkflowTransferDashboard\settings.toml
```

On macOS, these files use `~/Library/Application Support/WorkflowTransferDashboard`.
Append `--browser-channel chrome` to desktop or API commands for local Chrome testing.

## Outputs

CLI runs create timestamped HTML, Excel, and normalized CSV files under
`outputs/YYYY-MM-DD_Weekday/`. History defaults to
`outputs/history/workflow_history.sqlite`. Previous exports are retained;
regenerate reports to apply application updates. See the
[history compatibility rules](docs/metrics.md#historical-trend-definitions).

**Exports contain workflow data, including student names and institutions in
Case Observations.** Keep reports and history private; follow [Security](SECURITY.md).

Use arrow keys to move between report tabs and Enter or Space to select one.
Hover, focus, or tap for help; Escape or an outside tap dismisses it.

### Print / PDF

Select **Print / PDF** in the HTML report, then choose your browser's PDF printer.
Charts are prepared locally; Chrome and Edge work offline. The default is US
Letter landscape with 10 mm margins. Turn off browser headers and footers to
omit the local file URL.

Printing includes all sections, all case observations, and any open drilldown.
Year-filtered charts use their selected periods. Saving or cancelling preserves
the interactive report's selections. Normal generation does not create a PDF.

## Metric definitions

See the [metric reference](docs/metrics.md) for case and completion definitions,
timezone rules, completeness thresholds, aging bands, and history semantics.

## Windows executable build

From a Windows Python 3.12+ virtual environment (3.13 tested), with Git on PATH:

```powershell
.\packaging\build_windows.ps1
```

The script installs dependencies, runs tests, and builds
`dist/WorkflowTransferDashboard/WorkflowTransferDashboard.exe`.
Distribute the entire folder, including `_internal`, and extract it to a local
drive before launching. Users need Edge but not Python. Builds exclude local
configuration, records, reports, and history; Windows builds require Windows.

See [Development](docs/development.md) for test and dependency maintenance commands.

## Publication

Publish only source or the packaged build, never the development directory or
private backups. Follow the [publication checklist](SECURITY.md#before-publishing).
