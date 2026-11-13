# Metric reference

## Core definitions

- **Case:** One evaluation package, identified by Package ID. A student can have
  multiple cases.
- **Open / completed:** Cases at normalized workflow step `End` are completed;
  all others are open. A `Complete` or `Completed` status alone does not close a case.
- **Backlog:** Open cases with a valid age strictly above the configured threshold
  (seven days by default). Exactly seven days and missing ages do not qualify.
- **Age / idle time:** Elapsed time since `submissionDate` / last activity.
  Age includes inactivity; it is neither time in a step nor active work time.
- **Completion date:** Estimated from `lastActivityDate` for cases currently at
  `End`; the API has no explicit completion timestamp. Later updates can change it.
- **Median:** The middle value, suppressed below the required valid-data coverage.
- **Timezone:** Reports use `America/New_York`, including daylight saving.
  Zone-less API timestamps use this zone; normalized CSV timestamps remain UTC.

## Staff attribution and compatibility

Staff charts attribute cases to submitters, not current assignees. All cases
contribute to inventory counts. Configured roster members retain zero counts
when data is available; other named submitters become `Others`, and blank or
missing names become `Not recorded`. The date heatmap groups current cases by
submission date, not a complete submission-event history.

Presentation wording does not rename workbook sheets, CSV columns, stored metric
keys, source statuses, or environment variables.

## Historical trend definitions

Saved snapshots are scoped by a metric-definition hash covering source, workflow
and status filters, included workflows, thresholds, roster, and timezone. Only
matching definitions are combined, so population or formula changes start a
separate series. Charts show the latest saved run per Eastern calendar day;
SQLite and workbook history retain every eligible run.

Changes to populations or formulas must increment `METRIC_DEFINITION_VERSION`
in `workflow_dashboard/history.py`. Presentation changes and application versions
do not split trends. Schema versions are independent; incompatible databases are
rejected without mutation and must be archived before running the new version.

## Numeric precision

Analytics, history, and normalized CSV retain full numeric precision. Displayed
durations and averages use one decimal place with half-up rounding
(`23.05` becomes `23.1`). CSV strings with spreadsheet formula prefixes receive a
leading apostrophe; workbook source strings are stored as literal text.

Negative durations are retained in normalized data. Future submission/activity
timestamps and activity before submission are reported as observations. Invalid
timing is excluded from affected medians, maxima, aging charts, completeness
counts, and dated activity statistics, but not inventory counts. A negative
submission-to-activity interval excludes completion duration without removing an
otherwise valid inferred completion date from completion counts.

## Median completeness

Open-age and idle medians use all open cases as their denominator. Age requires
a valid non-negative duration. Idle time requires a parsed, non-future activity
timestamp that is not before a present submission date. Below the default 95%
coverage, the median shows `—` with a valid/total warning; otherwise coverage is
available in help and the audit workbook.

`WORKFLOW_MIN_WAIT_COMPLETENESS`, `WORKFLOW_MIN_IDLE_COMPLETENESS`, and
`WORKFLOW_MIN_COMPLETION_COMPLETENESS` accept values from 0 to 1. Age coverage is
also checked independently per workflow step; under-covered steps remain visible
with unavailable medians and valid/total counts in **Age By Step**.

Monthly completion volume includes every eligible End-step case. Completion-time
medians require both timestamps and a non-negative interval; insufficient coverage
hides the median, not the volume or coverage. Snapshot history stores age coverage,
and monthly history stores completion coverage; both appear in the workbook.

## Aging and action groups

The workflow aging matrix uses lower-inclusive bands `[0, 3)`, `[3, 7)`,
`[7, 14)`, `[14, 30)`, `[30, 60)`, and `[60, infinity)` days. Missing and invalid
ages remain in step totals but are excluded from bands and disclosed in hover
information. Bands are independent of backlog: exactly seven days belongs to
7–14 days but is not backlog at the default threshold.

The age × idle-time matrix uses backlog, aged-case, and stale thresholds (defaults:
7, 14, and 3 days). Active means a recent recorded update; idle means the inactivity
threshold has been reached. Axes use a square-root scale with values in actual
days. Invalid timing is excluded and disclosed in the coverage line. Its plot and
drilldown show no student names; drilldown fields are Package ID, step, age, idle
time, and the last-activity timestamp in Eastern time.

## Evaluation-type summary

Labels must contain three nonempty pipe-delimited values:
`evaluation type | person | institution`. The summary uses the first value,
removing a trailing `Transcript Evaluation` suffix; malformed labels become
`Unclassified`. Person and institution are excluded from this summary, but full
labels remain in Case Observations and exports; see [Security](../SECURITY.md).

The table reports total, open, and completed cases. Completion rate is completed
divided by total. Median open age is report time minus submission; median
completion time is activity minus submission for End-step cases with a valid
interval ending no later than report time. Completeness thresholds apply
independently within each type; insufficient coverage suppresses that median.
