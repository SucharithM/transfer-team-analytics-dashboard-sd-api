# sd-transfer-team-analytics

Transfer Team workflow operations dashboard for turning paginated API records into an executive overview of active work, aged backlog, bottlenecks, submitter attribution, case aging, End-step trends, and exceptions.

“Open Cases” includes every package whose normalized workflow step is not `End`. “Backlog” is the subset whose valid case age is strictly greater than the configured threshold (seven days by default). A package exactly seven days old or without a submission timestamp is not counted as backlog; missing submission timestamps are reported as notable observations.

Packages are treated as fully processed only when their normalized workflow step is `End`. Status values such as `Complete` or `Completed` are reported as workflow status, but they do not remove a package from Open Cases unless the package is at the `End` step.

The API's `submissionDate` is the original case submission timestamp, regardless
of the current workflow step. Case age therefore measures elapsed time since
submission. It does not measure time spent in a particular step. The API provides
no explicit completion timestamp. For cases currently at `End`, `lastActivityDate`
is used as the estimated completion time.

Team-specific charts use an explicit roster: `Staff Member A`, `Staff Member B`, `Staff Member C`, `Staff Member D`, and `Staff Member E`. Roster members remain visible when their count is zero. Other named submitters are grouped as `Others`; missing or blank submitters appear as `Not recorded`. All cases are included in staff inventory counts. Dated staff activity includes every case with an eligible case submission date. `Others` is shown in slate gray in the staff bar and donut charts; `Not recorded` is neutral gray. The date heatmap retains one shared count scale.

All dashboard and workbook times use Boston local time (`America/New_York`), including daylight-saving changes. API timestamps that do not include a timezone are interpreted as Boston local time; normalized CSV timestamps remain in UTC for interchange.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-bootstrap.txt
python -m pip install -r requirements-dev.txt
```

The checked-in fixture, staff roster and tenant URL are synthetic examples. Python 3.13 is the tested development version. For live use, configure only an endpoint you are authorized to access.

Copy `.env.example` to the ignored `.env` file for nonsecret live API settings (browser sign-in is the default):

```bash
WORKFLOW_API_URL=https://tenant.example.test/flow/api/user-dashboard/packages
WORKFLOW_API_TAKE=100
WORKFLOW_STATUS_FILTERS=NeedsReview,InProgress,Completed
WORKFLOW_FILTER=Example  Transcript Evaluation Form
WORKFLOW_DASHBOARD_TITLE=Transfer Credit Executive Overview
WORKFLOW_MIN_WAIT_COMPLETENESS=0.95
WORKFLOW_MIN_IDLE_COMPLETENESS=0.95
WORKFLOW_MIN_COMPLETION_COMPLETENESS=0.95
```

`.env` is ignored by git.

## Commands

Inspect the fixture shape:

```bash
python -m workflow_dashboard inspect --source fixture
```

Generate local dashboard outputs from the fixture:

```bash
python -m workflow_dashboard run --source fixture
```

Generate from the live API after configuring nonsecret settings. Complete SSO in the separate Edge window:

```bash
python -m workflow_dashboard inspect --source api
python -m workflow_dashboard run --source api
```

## Desktop sign-in and generation

On Windows with Microsoft Edge installed, launch:

```bash
python -m workflow_dashboard desktop
```

Click **Generate Dashboard**, choose an output folder, complete your normal
Microsoft sign-in and MFA, and open the eTrieve workflow dashboard if it does not
open automatically. The folder chooser appears on every generation, starting
at your last selected folder. First use starts in Documents (or your home folder
if Documents does not exist).
The app observes only the bearer header sent to the exact configured HTTPS API
endpoint. The sign-in page opens at that endpoint's origin. It does not fill in passwords, read your usual browser profile, save
sign-in state, or collect Microsoft tokens. No registered desktop OAuth client
or custom callback is used: this integration observes the existing web session.

Validate post-login navigation and workplace browser policy in an interactive
pilot before distribution. If policy prevents browser control, use an
IT-supported OAuth integration.

For development on a Mac with installed Chrome:

```bash
python -m workflow_dashboard desktop --browser-channel chrome
python -m workflow_dashboard inspect --source api --auth browser --browser-channel chrome
```

`inspect` checks one API page and prints field names and counts, without record values; it does
not generate files or write history. `run` fetches every page and applies the
existing completeness and workflow checks before producing outputs.

Desktop reporting defaults are provided in workflow_dashboard/desktop_settings.toml. To customize them, use desktop --settings /path/to/settings.toml. Keep organization-specific settings in ignored local files. Credentials and custom request headers are not accepted. Browser sign-in requires an authorized HTTPS endpoint. The desktop app does not load .env; CLI commands use it for local configuration.

The desktop window serves the configured transcript evaluation workflow only;
there is no workflow picker or automatic fallback to another workflow. Exact
matching is preserved, including internal whitespace. A missing workflow stops
generation with an access/configuration message and creates no files or history.
Each retry starts a fresh sign-in and complete fetch.

Folder access is checked in a background thread before sign-in. Cancelling the
folder chooser starts no work. A validated selection is saved immediately, even
if sign-in is later cancelled. Only the absolute output path is stored in
`preferences.json`, using atomic replacement. Missing/corrupt preferences fall
back safely; an unavailable remembered folder requires another selection. If the
preference cannot be saved, generation can continue with a visible warning.

The window shows **Sign in**, **Fetch records**, and **Create dashboard** stages.
The animated progress indicator appears only while work is active. **Cancel** is
available during sign-in/fetching and waits for safe process termination; file
generation finishes before the app closes. A successful dashboard opens
automatically. **Open Dashboard** reopens the last successful HTML, and **Open
Output Folder** opens that run's dated folder. Before the first successful run,
the folder action opens the remembered destination if available.

Browser/file-manager opening happens off the UI thread. Opening failures appear
separately from generation status, and delayed notifications from earlier runs
are ignored. The destination path supports text selection and copying.

After an error or warning, **Send Error Logs** opens technical diagnostics with
**Copy Logs** for pasting into a support message. Earlier affected attempts remain
selectable during the session, including after a successful retry. The button is
disabled while generation is active. Settings-load failures retain a small window
with the same copy action. Reports include stage outcomes, versions, approved
error categories, and numeric error codes; they exclude credentials, workflow
records, settings, and personal/system paths. Diagnostics are kept only in memory;
the app does not save or transmit log files. See SECURITY.md for the exact rules.

Desktop HTML, workbook, and CSV exports are written to a dated subfolder inside
the selected folder. Reporting history stays per Windows user regardless of
export destination:

```text
%LOCALAPPDATA%\WorkflowTransferDashboard\history\workflow_history.sqlite
%LOCALAPPDATA%\WorkflowTransferDashboard\preferences.json  (output path only)
%LOCALAPPDATA%\WorkflowTransferDashboard\settings.toml  (optional)
```

Mac development uses `~/Library/Application Support/WorkflowTransferDashboard`
for history, preferences, and optional settings. Existing exports are not moved.
Each generated HTML, workbook, and normalized CSV contains workflow data and
should be handled with the same care as the source records. Upgrades reuse the
local history location; incompatible history schemas are rejected according to
the existing migration policy.

### Credential lifetime and failure behavior

Each generation launches a fresh, nonpersistent browser context in a dedicated
spawned process. After capturing the API bearer, the browser context, browser,
and Playwright driver close before API fetching begins. The worker passes the
token directly to the API client, closes each HTTP response, and validates all
pages. Only records and count metadata cross the process pipe. An API response
that echoes the captured token is rejected, and raw exceptions, headers, cookies,
and browser state are never forwarded. The parent waits for a successful worker
exit and closes its process supervisor before rendering any files.

Sign-in times out after ten minutes; API calls retain the configured timeout
(default thirty seconds), with a thirty-minute overall fetch budget. A `401`
requires fresh sign-in and a full restart; a `403` reports missing permissions.
Cancellation, sign-in failure, or incomplete fetching produces no new output or
history. Existing files and history are preserved. There is no automatic token
refresh or session reuse between runs.

Remove saved token entries from `.env` when switching to browser sign-in.
Explicit bearer-token authentication remains available for existing integrations:

```bash
python -m workflow_dashboard run --source api --auth env
```

Only this explicit mode loads the legacy token. `.env` parsing no longer copies
settings or tokens into the process environment. Do not include `.env` in a
release.

### Windows executable build

Use Python 3.12 or newer on Windows (Python 3.13 is the tested version), with Git
available on the build machine's command-line PATH (`git --version` must work).
The publication-check tests require Git even when the source was downloaded as
a ZIP. No browser binary is bundled; the desktop user
needs installed Edge but does not need Python or a console. Build from a Windows virtual environment:

```powershell
.\packaging\build_windows.ps1
```

The script installs build dependencies, runs the test suite, and builds
`dist/WorkflowTransferDashboard.exe` as a single-file windowed executable. It bundles
the Playwright driver, Plotly assets, and nonsecret desktop defaults. It does not
bundle `.env`, records, generated outputs, or history. The multiprocessing entry
point calls `freeze_support()` before importing the GUI, avoiding recursive
frozen-app launches. A Windows executable cannot be built or validated on a
Mac.

Synthetic tests cover credential containment, fixed error messages, exact-origin
matching, response redirects, real spawned-worker cancellation and exit ordering,
Windows Job Object API contracts, and existing analytics/publication behavior.

`WORKFLOW_FILTER` selects one workflow by an exact, case-insensitive name
match after surrounding whitespace is removed. Records from other workflows,
including records without a workflow name, are excluded before analytics and
exports are built. A configured filter that matches no records aborts the run.

When `WORKFLOW_FILTER` is omitted, a nonempty source is accepted only when
every record has the same named workflow. Mixed or unnamed populations abort
the run rather than being aggregated under an inferred label. The dashboard's
visible label is configured independently with `WORKFLOW_DASHBOARD_TITLE`.

## Historical trend definitions

Every saved snapshot is linked to a canonical metric definition and its SHA-256
hash. The definition records the source identity, API status filters, workflow
filter, workflow names actually included, backlog threshold, terminal steps,
team roster, median-completeness thresholds, exception thresholds, and
dashboard timezone. Trend queries only load snapshots with the current
definition hash, so a population or formula change starts a separate series
instead of appearing as an operational change.

Dashboard charts based on saved-run history show only the latest run from each calendar day.
The SQLite history and workbook history sheets continue
to retain every eligible run for audit.

The SQLite schema version is tracked independently from metric semantics. The
application version is recorded on every snapshot for audit, but application
releases do not split trends by themselves. Any code change that alters a
population or metric formula must increment `METRIC_DEFINITION_VERSION` in
`workflow_dashboard/history.py`.

History schemas are intentionally not migrated while the product is under
development. Archive or remove a database created by an earlier schema before
running the new version; incompatible databases are rejected without mutation.

## Numeric precision

Age, idle-time, completion-time, and rolling-average calculations retain their
full precision through analytics and history storage. The normalized CSV also
keeps raw numeric values for interchange; strings with spreadsheet formula prefixes receive a leading apostrophe. This may affect consumers expecting byte-for-byte string values. Desktop user-facing KPI,
chart, HTML table, and workbook values display one decimal place using decimal
half-up rounding, so a value such as `23.05` is shown consistently as `23.1`.

Negative age and idle durations are retained in normalized data rather than
being changed to zero. A submission or last-activity timestamp after report
generation, or last activity before submission, is reported as a data-quality
observation for open and finished cases. Invalid durations are excluded from
the affected medians, maxima, aging charts, completeness counts, and dated
activity statistics while the case remains in inventory and workload counts.
Negative submission-to-last-activity durations are excluded from completion-time medians but do
not remove an otherwise valid inferred completion timestamp from inferred completion counts.

## Median completeness

Median Open Age uses all open cases as its denominator and includes cases
with a valid, non-negative case age in its median. Typical Time Since Last Activity
also uses all open cases as its denominator and includes cases with a valid
parsed, non-future last-activity timestamp that is not before a present
submission timestamp. Healthy KPI cards show only the median, such as `2.0d`;
their exact valid/total coverage is available from the information control and
audit workbook. Below the configured threshold, the median is suppressed and
the card shows `—` with a compact warning such as
`18/20 valid · below 95%`.

The age-by-step chart applies the age-completeness threshold independently to every step
and keeps under-covered steps visible with an unavailable median. Per-step
valid/total samples remain available in the audit workbook. The wait and idle
thresholds can be set from 0 through 1 with `WORKFLOW_MIN_WAIT_COMPLETENESS`
and `WORKFLOW_MIN_IDLE_COMPLETENESS`.

The workflow aging matrix counts open cases in the lower-inclusive aging bands
`[0, 3)`, `[3, 7)`, `[7, 14)`, `[14, 30)`, `[30, 60)`, and `[60, infinity)`
days. Its rows remain in case-flow order even when a standard workflow step has
no open cases. Unrecognized steps follow in alphabetical order, and cases
without a step appear last. Cell labels and row totals show queue volume while
the band colors progress from younger to more severely aged work. Missing and
negative ages remain in each step total but are excluded from the six bands and
reported as case age unavailable in hover details.

The age × idle-time action matrix plots open cases by time since case submission and time since last activity. It uses the configured
backlog, aged-case, and stale thresholds, currently seven, fourteen, and three
days. Quadrant counts distinguish young/recent, young/stale, backlog/recent,
and backlog/stale work. The axes use a square-root transformation so long-tail
cases remain visible without compressing the action thresholds; ticks,
tooltips, and drilldown values remain labeled in actual days. The executive
view contains no student names. Selecting a quadrant or point reveals only
Package ID, workflow step, case age, idle time, and the exact last-activity timestamp
in Eastern time. Packages with missing or invalid timing remain in open
inventory but are excluded from the plot and disclosed in its coverage line.

Monthly inferred completion volume includes every eligible End-step record. Its completion-time
median includes only cases with both timestamps and a non-negative submission-to-last-activity
duration. The median is suppressed below
`WORKFLOW_MIN_COMPLETION_COMPLETENESS`, while the completion bar and valid/total
coverage remain visible. Each run stores wait coverage in snapshot history and
monthly completion coverage in a run/month history table; both are exported
to the workbook for audit.

## Evaluation-type summary

The package label is expected to contain three pipe-delimited values:
`evaluation type | person | institution`. Dashboard analytics use only the
first value, with a trailing `Transcript Evaluation` suffix removed. Labels
that do not contain three nonempty values are retained as `Unclassified`;
person and institution are not added to the summary table or dashboard HTML.
The normalized CSV retains the package label, except that spreadsheet formula prefixes are escaped for safe spreadsheet import. The workbook stores source strings as literal text.

The Evaluation Cases by Evaluation Type table reports total, Open Cases, and Completed
cases for each type. Open Cases means every case not at the End step;
Completed means every End-step case. Completion rate is Completed divided
by total cases. Backlog is the count of Open Cases in the existing
configured backlog. Types with no open or completed cases remain visible with
unavailable rates or medians.

Median Open Age uses report time minus case `submissionDate` for
non-End packages with valid non-negative ages. Median Completion Time uses
`lastActivityDate - submissionDate` for End-step packages with valid
non-negative intervals. This estimates elapsed time from case submission to completion; later updates may affect the estimate. The existing wait and completion completeness thresholds are
applied independently within each evaluation type. Below a threshold, the
affected median is suppressed; validity counts remain internal and are not
displayed in the dashboard table.

Repeated workflow steps, statuses, and staff labels use stable semantic colors
elsewhere in the dashboard. `Staff Member E` is pinned to soft light pink
(`#F48FB1`) in category-colored staff charts based on their personal request; the staff-by-date heatmap retains
its shared blue intensity scale.

The thresholds and formulas used by saved-history trends are part of the
persisted metric definition. A definition-version change starts a new
compatible trend series, while older snapshots remain retained for audit.

## Outputs

Each run writes a new timestamped set of files to a Boston-dated directory such as `outputs/2026-07-10_Friday/`:

- `transfer_credit_executive_overview_2026-07-10_13-40-15-123456_EDT.html`
- `transfer_credit_executive_overview_2026-07-10_13-40-15-123456_EDT.xlsx`
- `normalized_records_2026-07-10_13-40-15-123456_EDT.csv`
- `outputs/history/workflow_history.sqlite`

The date, weekday, timestamp, and timezone in these paths all use Boston local time. Previous run files are retained.

To save a PDF, open the HTML report and select **Save as PDF** in its header.
The report prepares its charts locally, then opens the browser print dialog.
Choose **Save as PDF** (or your system's PDF printer), a filename, and a destination.
The print layout defaults to US Letter landscape with 10 mm margins; browser
settings can override these defaults. Turn off browser headers and footers to
omit the local file URL. PDF export works offline in Chrome and Edge and creates
no additional file during normal audit generation.

The PDF includes all report sections, the observations already displayed in the
HTML (up to 100, with the existing count notice), and any currently open case
drilldown. Save or cancel the dialog to return to the interactive report. If
chart preparation fails, the report shows a retry message. Previously generated
HTML files do not receive this feature automatically.

Real browser PDF checks are opt-in and require an installed Chrome or Edge.
Run `python -m pytest -q tests/test_dashboard_pdf.py` with
`DASHBOARD_PDF_BROWSER=chrome` or `DASHBOARD_PDF_BROWSER=msedge` set in the
environment. Optionally set `DASHBOARD_PDF_ARTIFACT_DIR` to retain the synthetic
HTML and PDF samples for visual inspection. Without the browser variable, the
normal test suite skips these four browser checks.

## Presentation terminology and compatibility

A case is one workflow evaluation package; Package ID is its Softdocs identifier.
A student can have multiple cases. Case age includes all elapsed calendar
time, including waiting and inactivity; it does not measure active work time.
Idle time measures time since last recorded activity. Completion dates are
inferred from last activity for cases currently at the End step.

Staff views use the configured roster and retain zero-count members when chart
data is available. The internal `owner` field contains submitter attribution,
not current assignment. The staff date heatmap groups current report cases by
case submission date; it is not a complete submission-event history.
Aging bands are independent of the strict backlog threshold: a case exactly
seven days old is in the 7–14 day band but is not backlog at the default threshold.

HTML and workbook summary copy use the operational terminology above. Audit
sheet names (including In The Works, Daily Closures, and Closed By Month),
raw source statuses, CSV columns, stored metric keys, environment variables,
and historical metric definitions retain their existing names and meanings.
Presentation-only changes do not start a new historical series. Including previously excluded submitters is a population change: metric definition version 9 records `roster_plus_others_and_not_recorded` and starts a new compatible history series. Existing snapshots remain retained for audit; the database schema is unchanged.

All date boundaries still use
America/New_York. “Median” means the middle value. “Median Completion Time”
measures last activity minus case submission for cases currently at End, using
last activity as an estimate of completion. Action groups use the configured day boundary
(e.g., “Up to 7 Days · Active” and “Over 7 Days · Idle”). Active means a recent
recorded update; idle means the configured inactivity period has been reached.

## Publication

The public source includes only synthetic records and generic tenant/staff defaults. Live datasets, generated reports, local settings, credentials and private backups are ignored. Never upload the whole development directory or its private backups as a release archive.

Run `python tools/check_publication.py --working-tree` before pushing. The checker scans staged contents, tracked working files, eligible untracked files, and reachable Git history. It rejects private artifact paths and reports supported secret-pattern matches without printing their values. Use `--all-objects` to include unreachable blobs when reviewing a local repository. Review the staged diff before pushing.

For tests, install `requirements-dev.txt`. Runtime and development versions are pinned with `constraints.txt`; Windows build dependencies use `packaging/requirements-build.txt`. Upgrade the installer using `requirements-bootstrap.txt` first. Dependency advisories must be rechecked when pins change.
