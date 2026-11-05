# Metric reference

See the [README](../README.md#metric-definitions) for core definitions and timezone rules.

## Staff attribution and compatibility

Staff views use the configured roster and retain zero-count members when chart
data is available. Other named submitters are grouped as `Others`; missing or
blank submitters appear as `Not recorded`. All cases are included in staff
inventory counts. The internal `owner` field contains submitter attribution,
not current assignment. The staff date heatmap groups current report cases by
case submission date; it is not a complete submission-event history.

Audit sheet names (including In The Works, Daily Closures, and Closed By Month),
raw source statuses, CSV columns, stored metric keys, and environment variables
retain their existing names and meanings when presentation copy changes.

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
application version is recorded on every snapshot for audit, but releases and
presentation-only changes do not split trends by themselves. Any code change that alters a
population or metric formula must increment `METRIC_DEFINITION_VERSION` in
`workflow_dashboard/history.py`.

History schemas are intentionally not migrated while the product is under
development. Archive a database created by an earlier schema before
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
valid/total samples are available in the audit workbook's **Age By Step** sheet,
alongside each step's median (blank when unavailable). The wait and idle
thresholds can be set from 0 through 1 with `WORKFLOW_MIN_WAIT_COMPLETENESS`
and `WORKFLOW_MIN_IDLE_COMPLETENESS`.

Monthly inferred completion volume includes every eligible End-step record. Its completion-time
median includes only cases with both timestamps and a non-negative submission-to-last-activity
duration. The median is suppressed below
`WORKFLOW_MIN_COMPLETION_COMPLETENESS`, while the completion bar and valid/total
coverage remain visible. Each run stores wait coverage in snapshot history and
monthly completion coverage in a run/month history table; both are exported
to the workbook for audit.

## Aging and action groups

The workflow aging matrix counts open cases in the lower-inclusive aging bands
`[0, 3)`, `[3, 7)`, `[7, 14)`, `[14, 30)`, `[30, 60)`, and `[60, infinity)`
days. Missing and negative ages remain in each step total but are excluded from the
six bands and reported as case age unavailable in hover details.
Aging bands are independent of backlog: a case exactly seven days old is in the
7–14 day band but is not backlog at the default threshold.

The age × idle-time action matrix plots open cases by time since case submission and time since last activity. It uses the configured
backlog, aged-case, and stale thresholds, currently seven, fourteen, and three
days. Quadrant counts distinguish young/recent, young/stale, backlog/recent,
and backlog/stale work. Axes use a square-root scale, with ticks, tooltips, and drilldown values in
actual days. The plot and its drilldown contain no student names. Selecting a quadrant or point reveals only
Package ID, workflow step, case age, idle time, and the exact last-activity timestamp
in Eastern time. Packages with missing or invalid timing remain in open
inventory but are excluded from the plot and disclosed in its coverage line.
Action group labels use the configured day boundaries. Active means a recent
recorded update; idle means the configured inactivity period has been reached.

## Evaluation-type summary

The package label is expected to contain three pipe-delimited values:
`evaluation type | person | institution`. The evaluation-type summary uses only the
first value, with a trailing `Transcript Evaluation` suffix removed. Labels
that do not contain three nonempty values are retained as `Unclassified`;
person and institution are not added to the summary table. Case Observations
intentionally retains the complete package label, including student names and
institutions, in the dashboard HTML and printed/PDF reports.
The normalized CSV retains the package label, except that spreadsheet formula prefixes are escaped for safe spreadsheet import. The workbook stores source strings as literal text.

The Evaluation Cases by Evaluation Type table reports total, Open Cases, and
Completed cases for each type, using the [README definitions](../README.md#metric-definitions).
Completion rate is Completed divided by total cases. Backlog uses the configured
backlog threshold. Types with no open or completed cases remain visible with
unavailable rates or medians.

Median Open Age uses report time minus case `submissionDate` for
non-End packages with valid non-negative ages. Median Completion Time uses
`lastActivityDate - submissionDate` for End-step packages with valid
non-negative intervals ending no later than report time. This estimates elapsed time from case submission to completion; later updates may affect the estimate. The existing wait and completion completeness thresholds are
applied independently within each evaluation type. Below a threshold, the
affected median is suppressed; validity counts remain internal and are not
displayed in the dashboard table.
