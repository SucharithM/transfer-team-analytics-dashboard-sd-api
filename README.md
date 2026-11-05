# sd-transfer-team-analytics

Transfer Team workflow dashboard for turning paginated API records into an
executive overview of active work, aged backlog, bottlenecks, submitter activity,
completion trends, and exceptions.

## Setup

Python 3.13 is the tested development version. The checked-in fixture, staff
roster, and tenant URL are synthetic examples.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-bootstrap.txt
python -m pip install -r requirements-dev.txt
```

For live use, copy [`.env.example`](.env.example) to the ignored `.env` file and
configure an HTTPS endpoint you are authorized to access. Browser sign-in is the
default; keep credentials out of this file when using browser sign-in.

`WORKFLOW_FILTER` selects one workflow by an exact, case-insensitive name match
after surrounding whitespace is removed; internal whitespace is preserved.
Other workflows and records without a workflow name are excluded. A filter that
matches no records aborts the run. Without a filter, a nonempty source must
contain only one named workflow. `WORKFLOW_DASHBOARD_TITLE` sets the visible label
independently.

## Commands

Inspect the fixture shape, then generate local dashboard outputs:

```bash
python -m workflow_dashboard inspect --source fixture
python -m workflow_dashboard run --source fixture
```

For the live API, complete SSO in the separate Edge window:

```bash
python -m workflow_dashboard inspect --source api
python -m workflow_dashboard run --source api
```

`inspect` checks one API page and prints field names and counts without record
values. It writes no files or history. `run` fetches every page and validates the
workflow and data completeness before producing outputs.

Explicit bearer-token authentication remains available for existing integrations:

```bash
python -m workflow_dashboard run --source api --auth env
```

Only this explicit mode loads the saved token. Remove token entries from `.env`
when switching to browser sign-in. Never include `.env` in a release.

## Desktop sign-in and generation

On Windows with Microsoft Edge installed, launch:

```bash
python -m workflow_dashboard desktop
```

Click **Generate Dashboard**, choose an output folder, complete Microsoft sign-in
and MFA, and open the eTrieve workflow dashboard if it does not open automatically.
The folder chooser appears on every generation, starting at your last selected
folder. First use starts in Documents, or your home folder if Documents is absent.
Cancelling the chooser starts no work. A validated folder choice is remembered
even if sign-in is later cancelled; a save failure shows a warning but permits
generation to continue.

Desktop defaults are in
[`workflow_dashboard/desktop_settings.toml`](workflow_dashboard/desktop_settings.toml).
Use `python -m workflow_dashboard desktop --settings /path/to/settings.toml` to
customize them. Keep organization-specific settings in ignored local files.
Desktop settings do not accept credentials or custom request headers. The desktop
app does not load `.env`; CLI commands use it for local configuration.

The desktop app serves only the configured workflow. A missing workflow stops
generation without creating files or history. Each attempt uses fresh browser
sign-in; it does not use your usual browser profile or retain sign-in state.
Validate post-login navigation and workplace browser policy in an interactive
pilot before distribution. If policy prevents browser control, use an
IT-supported OAuth integration. See [Security](SECURITY.md) for authentication
and data-handling rules.

Sign-in times out after ten minutes. API calls default to a thirty-second timeout,
with a thirty-minute overall fetch budget. A `401` requires fresh sign-in and a
full restart; a `403` reports missing permissions. Cancellation, failed sign-in,
or incomplete fetching produces no new output or history; existing files and
history are preserved.

The window shows **Sign in**, **Fetch records**, and **Create dashboard** stages.
**Cancel** is available during sign-in and fetching; file generation finishes
before the app closes. A successful dashboard opens automatically. **Open Dashboard**
reopens the last successful HTML. **Open Output Folder** opens that run's dated
folder, or the remembered destination before the first successful run.

After an error or warning, **Send Error Logs** opens diagnostics; use **Copy Logs**
to paste them into a support message. Earlier affected attempts remain selectable
for the session. Diagnostics stay in memory and are not saved or transmitted.
See [Security](SECURITY.md) for the exact contents and limits.

Desktop exports go into a dated subfolder of your selected folder. History and
preferences stay per Windows user regardless of export destination:

```text
%LOCALAPPDATA%\WorkflowTransferDashboard\history\workflow_history.sqlite
%LOCALAPPDATA%\WorkflowTransferDashboard\preferences.json  (output path only)
%LOCALAPPDATA%\WorkflowTransferDashboard\settings.toml  (optional)
```

Mac development uses `~/Library/Application Support/WorkflowTransferDashboard`
for these files. With installed Chrome, use:

```bash
python -m workflow_dashboard desktop --browser-channel chrome
python -m workflow_dashboard inspect --source api --auth browser --browser-channel chrome
```

## Outputs

CLI runs write timestamped files into a Boston-dated folder such as
`outputs/2026-07-10_Friday/`:

- `transfer_credit_executive_overview_2026-07-10_13-40-15-123456_EDT.html`
- `transfer_credit_executive_overview_2026-07-10_13-40-15-123456_EDT.xlsx`
- `normalized_records_2026-07-10_13-40-15-123456_EDT.csv`

CLI history defaults to `outputs/history/workflow_history.sqlite`. Previous
exports are retained. Upgrades reuse the local history location; incompatible
history databases must be archived before running the new version. See the
[history rules](docs/metrics.md#historical-trend-definitions).

Generated HTML, workbook, CSV, and history files contain workflow data. Case
Observations includes complete package labels, including student names and
institutions, in HTML and printed/PDF reports. Keep exports private and handle
them with the same care as source records; see [Security](SECURITY.md).

Use arrow keys to move between report tabs and Enter or Space to select one.
Hover, focus, or tap to open help; press Escape or tap outside to dismiss it.

### Print / PDF

Open the HTML report and select **Print / PDF** beside its generation time.
The report prepares its charts locally, then opens the browser print dialog.
If preparation fails, retry with the same button.

Choose **Save as PDF** (or your system's PDF printer), a filename, and a destination.
The default layout is US Letter landscape with 10 mm margins; browser settings
can override it. Turn off browser headers and footers to omit the local file URL.
PDF export works offline in Chrome and Edge and creates no additional file during
normal dashboard generation.

The PDF includes all report sections, every case observation, and any currently
open case drilldown. Saving or cancelling returns to the interactive report with
the same selected tabs. Previously generated HTML files do not gain this feature
automatically; generate a new report to use it.

## Metric definitions

- **Case:** One workflow evaluation package, identified by Package ID. A student
  can have multiple cases.
- **Open Cases:** Every case whose normalized workflow step is not `End`.
  Statuses such as `Complete` or `Completed` alone do not remove it from open work.
- **Backlog:** Open cases with a valid age strictly above the configured threshold
  (seven days by default). Exactly seven days or a missing submission date does
  not count as backlog; missing dates are reported as observations.
- **Case age / idle time:** Elapsed time since `submissionDate` / last activity.
  Case age includes waiting and inactivity; it does not measure time in a step
  or active work time.
- **Completed:** Cases currently at `End`. The API has no explicit completion
  timestamp, so `lastActivityDate` estimates completion; later updates can affect it.
- **Staff activity:** Submitter attribution, not current assignment. The date
  heatmap groups current cases by submission date, not a complete event history.
- **Median:** The middle value. Medians are hidden when valid data falls below
  the configured completeness threshold (95% by default).
- **Timezone:** Dashboard and workbook times use `America/New_York`, including
  daylight-saving changes. API timestamps without a timezone use this zone;
  normalized CSV timestamps remain UTC.

See the [metric reference](docs/metrics.md) for formulas, coverage rules, invalid
dates, aging bands, evaluation types, numeric precision, and trend compatibility.

## Windows executable build

Build on Windows using a Python 3.12+ virtual environment (3.13 is tested) with
Git available on PATH, even when building from a source ZIP:

```powershell
.\packaging\build_windows.ps1
```

The script installs build dependencies, runs tests, and builds
`dist/WorkflowTransferDashboard/WorkflowTransferDashboard.exe`. Tests clear
`build/pytest-temp` on each build; do not store other files there.

Distribute the entire `dist/WorkflowTransferDashboard` folder, including
`_internal`. Zip it for sharing and extract the whole folder to a local drive
before launching; the executable cannot run alone. Users need installed Edge,
but no Python or console. The bundle excludes `.env`, records, outputs, and
history. A Windows executable cannot be built or validated on a Mac.

For test commands and dependency maintenance, see [Development](docs/development.md).

## Publication

The public source contains synthetic records and generic tenant/staff defaults.
Live data, generated reports, local settings, credentials, and private backups
are ignored. Never upload the whole development directory or private backups
as a release archive.

Before pushing, run:

```bash
python tools/check_publication.py --working-tree
```

The checker scans staged contents, tracked working files, eligible untracked
files, and reachable Git history for private paths and supported secret patterns
without printing matched values. Use `--all-objects` to include unreachable blobs
when reviewing a local repository. Review the staged diff and follow the
[security checklist](SECURITY.md) before publication.
