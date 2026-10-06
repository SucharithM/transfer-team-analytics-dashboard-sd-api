"""Centralized user-facing copy for dashboard and workbook outputs."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping

KpiKey = Literal[
    "total_records",
    "in_the_works",
    "cases_closed_today",
    "total_cases_closed",
    "typical_wait_time",
    "typical_idle_time",
    "notable_observations",
]

ChartKey = Literal[
    "in_the_works_by_step",
    "status_mix",
    "aging_by_step",
    "workflow_aging_matrix",
    "age_idle_action_matrix",
    "owner_workload",
    "submitted_by_workload",
    "submitted_by_date_activity",
    "closed_by_month",
    "backlog_trend",
    "daily_closures",
    "age_trend",
    "recent_closures",
]


@dataclass(frozen=True)
class KpiContent:
    """Display copy for one KPI."""

    label: str
    help_template: str

    def format_help(self, **values: object) -> str:
        """Render dynamic help text with named values."""

        return self.help_template.format(**values)


@dataclass(frozen=True)
class PresentationContext:
    """Thresholds for display copy; does not alter metric definitions."""

    backlog_age_days: float = 7.0
    old_age_days: float = 14.0
    stale_idle_days: float = 3.0

    def format(self, text: str) -> str:
        return text.format(
            backlog_age_days=self.backlog_age_days,
            old_age_days=self.old_age_days,
            stale_idle_days=self.stale_idle_days,
        )


@dataclass(frozen=True)
class ChartContent:
    """Display copy for one chart card."""

    title: str
    help_text: str

    def formatted(self, context: PresentationContext) -> "ChartContent":
        return ChartContent(context.format(self.title), context.format(self.help_text))


@dataclass(frozen=True)
class SectionContent:
    """Display copy for one dashboard section."""

    eyebrow: str
    title: str
    description: str | None = None


@dataclass(frozen=True)
class LegendItemContent:
    """One item in the workflow process guide."""

    title: str
    description: str


@dataclass(frozen=True)
class LegendContent:
    """Display copy for the workflow process guide."""

    eyebrow: str
    title: str
    description: str
    items: tuple[LegendItemContent, ...]


@dataclass(frozen=True)
class PageContent:
    """Top-level and navigational dashboard copy."""

    team_eyebrow: str
    prototype_label: str
    generated_prefix: str
    authorship_prefix: str
    author_name: str
    intro_paragraphs: tuple[str, ...]
    jump_to_top: str
    save_pdf: str
    save_pdf_hint: str
    preparing_pdf: str
    pdf_error: str
    save_pdf: str
    save_pdf_hint: str
    preparing_pdf: str
    pdf_error: str


@dataclass(frozen=True)
class CommonContent:
    """Short labels shared across dashboard components."""

    about_label_template: str
    empty_figure: str
    missing_value: str
    no_submitters: str
    no_step: str
    no_status: str
    unclassified_evaluation_type: str
    other_statuses_template: str
    month_to_date_suffix: str
    view_list: str
    valid_count_template: str


@dataclass(frozen=True)
class ChartLabels:
    """Human-readable chart axis, series, and hover labels."""

    age_unavailable: str
    age_since_step_submission: str
    action_group: str
    aging_band: str
    backlog: str
    cases_closed: str
    close_date: str
    closed_cases: str
    close_month: str
    completion_coverage: str
    coverage: str
    daily_closures: str
    date: str
    days: str
    median_age: str
    median_completion: str
    idle_time: str
    last_activity: str
    open_cases: str
    package_id: str
    records: str
    seven_day_average: str
    share: str
    staff: str
    status: str
    step_total: str
    submissions: str
    submitted_date: str
    submitter: str
    workflow_step: str


@dataclass(frozen=True)
class ObservationTableContent:
    """Display copy for the notable-observations table."""

    title: str
    help_text: str
    empty_message: str
    summary_template: str
    header_labels: Mapping[str, str]


@dataclass(frozen=True)
class EvaluationTypeTableContent:
    """Display copy for the evaluation-type summary table."""

    title: str
    help_text: str
    empty_message: str
    header_labels: Mapping[str, str]


@dataclass(frozen=True)
class WorkbookContent:
    """Copy used by the audit workbook."""

    recent_trends_heading: str
    empty_trends_message: str
    sheet_names: Mapping[str, str]


PAGE = PageContent(
    team_eyebrow="Transfer Credits Team",
    prototype_label="(Prototype)",
    generated_prefix="Generated",
    authorship_prefix="Developed by",
    author_name="Sucharith Madhusoodana",
    intro_paragraphs=(
        "This custom dashboard leverages Softdocs Etrieve Central Submissions data to monitor the end-to-end "
        "Transfer Credit Evaluation process. A student may have one or more evaluation cases, including No-Rule, "
        "International, Military, and Continuing Student evaluation types. The dashboard provides interactive charts, "
        "visualizations, and key operational metrics for workflow status, submission and evaluation volumes, "
        "processing times, aging, pending evaluations, completed requests, and workload distribution. "
        "These analytics enable the Registrar’s Office to monitor operational performance across the different evaluation types, "
        "identify workflow bottlenecks, balance evaluator workloads, ensure timely processing, and "
        "support data-driven decisions for resource planning and continuous process improvement.",
    ),
    jump_to_top="Jump to top",
    save_pdf="Print / PDF",
    save_pdf_hint="Opens the print dialog. Choose Save as PDF.",
    preparing_pdf="Preparing…",
    pdf_error="Couldn’t prepare the report. Please try again.",
)

COMMON = CommonContent(
    about_label_template="About {label}",
    empty_figure="No data available",
    missing_value="Missing",
    no_submitters="No submitters",
    no_step="No step",
    no_status="No status",
    unclassified_evaluation_type="Unclassified",
    other_statuses_template="Other ({count} statuses)",
    month_to_date_suffix=" (MTD)",
    view_list="View list",
    valid_count_template="{valid}/{total} valid",
)

CHART_LABELS = ChartLabels(
    age_unavailable="Age unavailable",
    age_since_step_submission="Case Age (Days)",
    action_group="Action group",
    aging_band="Aging band",
    backlog="Backlog Cases",
    cases_closed="Completed Cases",
    close_date="Estimated Completion Date",
    closed_cases="Completed Cases",
    close_month="Estimated Completion Month",
    completion_coverage="Cases with Usable Dates",
    coverage="Coverage",
    daily_closures="Daily Completed Cases",
    date="Date",
    days="Days",
    median_age="Median Case-Open Age",
    median_completion="Median Completion Time",
    idle_time="Days Since Last Activity",
    last_activity="Last activity",
    open_cases="Open cases",
    package_id="Package ID",
    records="Cases",
    seven_day_average="7-day average",
    share="Share",
    staff="Staff",
    status="Status",
    step_total="Step total",
    submissions="Cases",
    submitted_date="Case Submission Date",
    submitter="Submitter",
    workflow_step="Workflow step",
)

KPI_CONTENT: Mapping[KpiKey, KpiContent] = MappingProxyType(
    {
        "total_records": KpiContent(
            label="Total Evaluation Cases",
            help_template=(
                "Every workflow case included in this report, whether it is "
                "still being worked on or already finished."
            ),
        ),
        "in_the_works": KpiContent(
            label="Open Cases",
            help_template=(
                "Cases still moving through the workflow. A case counts as completed when it reaches "
                "the End step."
            ),
        ),
        "cases_closed_today": KpiContent(
            label="Cases Completed Today",
            help_template=(
                "Completed cases with a last update today. That update is our best available estimate "
                "of when each case finished."
            ),
        ),
        "total_cases_closed": KpiContent(
            label="Total Completed Cases",
            help_template=(
                "Cases in this report that have reached the End step of the workflow."
            ),
        ),
        "typical_wait_time": KpiContent(
            label="Median Case-Open Age",
            help_template=(
                "How long cases have been open since submission, including time without "
                "activity. Median means the middle value. Based on {valid_count} of {total_count} "
                "cases; shown when at least {minimum_completeness} have usable dates."
            ),
        ),
        "typical_idle_time": KpiContent(
            label="Typical Idle Time",
            help_template=(
                "How long open cases have gone without an update. Typical means the middle value. "
                "Based on {valid_count} of {total_count} cases; shown when at least "
                "{minimum_completeness} have usable dates."
            ),
        ),
        "notable_observations": KpiContent(
            label="Notable Observations",
            help_template=(
                "Cases worth reviewing because they have been open or inactive for a long time, or "
                "have missing or inconsistent information."
            ),
        ),
    }
)

CHART_CONTENT: Mapping[ChartKey, ChartContent] = MappingProxyType(
    {
        "in_the_works_by_step": ChartContent(
            title="Current Open Cases",
            help_text=(
                "Where open cases are in the evaluation process. Larger slices mean more cases at "
                "that step."
            ),
        ),
        "status_mix": ChartContent(
            title="Cases by Status",
            help_text=(
                "How cases are divided across their current statuses. Cases that have reached End "
                "appear as Completed. Less common statuses may be grouped as Other."
            ),
        ),
        "aging_by_step": ChartContent(
            title="Median Open-Case Age by Workflow Step",
            help_text=(
                "The median age since submission of open cases grouped by their current workflow step. Time without "
                "activity is included. Steps with older cases appear first; a "
                "dash means there are not enough usable dates."
            ),
        ),
        "workflow_aging_matrix": ChartContent(
            title="Progress and Aging of Open Cases",
            help_text=(
                "Counts open cases by workflow step and submission age. Cell labels and row totals "
                "show volume; colors progress from lower-risk recently opened cases to higher-risk "
                "aged / older cases, with color intensity scaled consistently across the matrix. "
                "Cases with missing or negative ages are excluded from the bands and reported as "
                "Age unavailable in hover details. Backlog means open for more than "
                "{backlog_age_days:g} days since submission."
            ),
        ),
        "age_idle_action_matrix": ChartContent(
            title="Open Cases Risk and Action Overview",
            help_text=(
                "See which cases have been open longer since submission and which have had no "
                "recent activity. Backlog means open for over {backlog_age_days:g} days since submission; idle "
                "means no update for {stale_idle_days:g} days or more. The {old_age_days:g}-day "
                "marker highlights longer-running cases. Select a group or dot to see its cases."
            ),
        ),
        "owner_workload": ChartContent(
            title="Open Cases by Submitter",
            help_text=(
                "Open cases grouped by the person who submitted them. Others combines submitters "
                "outside the tranfer team; Not recorded means the submitter is missing. This shows who "
                "submitted each case, not who is working on it now."
            ),
        ),
        "submitted_by_workload": ChartContent(
            title="Submission Volume by Staff",
            help_text=(
                "Open and completed cases grouped by who submitted them. Others combines submitters "
                "outside the named team; Not recorded means the submitter is missing. These counts "
                "cover the cases in this report."
            ),
        ),
        "submitted_by_date_activity": ChartContent(
            title="Cases Submitted by Staff and Date",
            help_text=(
                "When the cases in this report were submitted, grouped by submitter. "
                "Darker cells mean more cases. Others combines submitters outside the named team; Not "
                "recorded means the submitter is missing. Cases without usable dates are left out."
            ),
        ),
        "closed_by_month": ChartContent(
            title="Cases Completed by Month",
            help_text=(
                "Completed cases by month, using their last update as the estimated completion date. "
                "The current month shows progress so far. Hover for the median time from case submission "
                "to estimated completion, using the last update for cases at End."
            ),
        ),
        "backlog_trend": ChartContent(
            title="Backlog Trend — Open Cases Over {backlog_age_days:g} Days Old",
            help_text=(
                "How many cases have been open for more than {backlog_age_days:g} days since "
                "submission. Each point uses the last report saved that day. Cases at exactly "
                "{backlog_age_days:g} days are not yet backlog."
            ),
        ),
        "daily_closures": ChartContent(
            title="Daily Completed Cases",
            help_text=(
                "Daily completions through yesterday. The line shows the seven-day average once a "
                "full week is available. See Cases Completed Today for today's progress."
            ),
        ),
        "age_trend": ChartContent(
            title="Median Open-Case Age Trend",
            help_text=(
                "The median age of open cases since submission, based on the last report "
                "saved each day. Median means the middle value; time without activity is included."
            ),
        ),
        "recent_closures": ChartContent(
            title="Cases Completed — Last 7 Days",
            help_text=(
                "Completions over the seven days ending yesterday. A zero means no completions that "
                "day; today is shown separately in Cases Completed Today."
            ),
        ),
    }
)

SECTION_CONTENT: Mapping[str, SectionContent] = MappingProxyType(
    {
        "overview": SectionContent(
            eyebrow="Current snapshot",
            title="Cases Overview",
        ),
        "operations": SectionContent(
            eyebrow="Current snapshot",
            title="Operational Workload",
            description=(
                "Where open cases are concentrated and how long they have been open since submission."
            ),
        ),
        "evaluation_types": SectionContent(
            eyebrow="Case Overview",
            title="Evaluation Cases by Evaluation Type",
            description=(
                "See open and completed cases, backlog, and median age and completion time for each evaluation type."
            ),
        ),
        "staff": SectionContent(
            eyebrow="Staff activity",
            title="Submission Activity by Staff",
            description=(
                "Submission volume and dates by staff member for the cases in this report."
            ),
        ),
        "trends": SectionContent(
            eyebrow="Historical view",
            title="Workflow Trends",
            description=("How completions, backlog, and open case age are changing."),
        ),
        "exceptions": SectionContent(
            eyebrow="Review queue",
            title=KPI_CONTENT["notable_observations"].label,
        ),
    }
)

WORKFLOW_STEP_ORDER = (
    "Transcript Evaluator",
    "Faculty Evaluator - Initial Review",
    "Transcript Evaluator - Post-Faculty Review",
    "Transcript Evaluator - Pending Student Syllabi",
    "Faculty Evaluator - Second Review",
    "Transcript Evaluator - Final Review",
)

WORKFLOW_LEGEND = LegendContent(
    eyebrow="Process Guide",
    title="Transcript Evaluation Workflow Legend",
    description="A guide to the workflow steps represented throughout this dashboard.",
    items=(
        LegendItemContent(
            title="Transcript Evaluator",
            description=(
                "The Transfer Credit Team performs the initial transcript "
                "review and identifies courses requiring faculty evaluation."
            ),
        ),
        LegendItemContent(
            title="Faculty Evaluator – Initial Review",
            description=("Evaluation cases sent to faculty by the Registrar’s Office."),
        ),
        LegendItemContent(
            title="Transcript Evaluator – Post-Faculty Review",
            description=(
                "Forms returned to the Transfer Credit Team; they may be ready "
                "for entry into the Dictionary or returned to faculty if "
                "information is missing."
            ),
        ),
        LegendItemContent(
            title="Transcript Evaluator – Pending Student Syllabi",
            description=(
                "Cases placed on hold after the student has been emailed "
                "through Salesforce."
            ),
        ),
        LegendItemContent(
            title="Faculty Evaluator – Second Review",
            description=(
                "Cases returned to faculty after the student supplies a "
                "requested syllabus or course description."
            ),
        ),
        LegendItemContent(
            title="Transcript Evaluator – Final Review",
            description=(
                "Forms returned to the Transfer Credit Team for final review "
                "before entry into the Dictionary."
            ),
        ),
    ),
)

EVALUATION_TYPE_TABLE = EvaluationTypeTableContent(
    title="Evaluation Progress",
    help_text=(
        "Compare progress across evaluation types. Completed cases have reached End; backlog "
        "means open for more than {backlog_age_days:g} days since submission. Median means the "
        "middle value. Open age runs from case submission to this report. Completion time runs "
        "from case submission to the last recorded update for completed cases; that update is "
        "our estimate of completion. Both include waiting and inactivity. A dash means there "
        "are not enough usable dates."
    ),
    empty_message="No evaluation-type cases were identified for this run.",
    header_labels=MappingProxyType(
        {
            "evaluation_type": "Evaluation Type",
            "total_count": "Total Cases",
            "in_progress_count": "Open Cases",
            "completed_count": "Completed",
            "completion_rate": "% Completed",
            "backlog_summary": "Backlog",
            "median_open_age_summary": "Median Case-Open Age",
            "median_completion_summary": "Median Completion Time",
        }
    ),
)

OBSERVATION_TABLE = ObservationTableContent(
    title="Case Observations",
    help_text=(
        "Up to 100 cases that may need attention because of long waits, inactivity, "
        "or missing or inconsistent information. Completed cases may appear if their information needs review."
    ),
    empty_message="No case observations were identified for this run.",
    summary_template="Showing {shown:,} of {total:,} case observations.",
    header_labels=MappingProxyType(
        {
            "record_id": "Package ID",
            "submitted_at": "Case Submitted",
            "owner": "Submitter",
            "step_name": "Workflow Step",
            "age_days": "Case Age (Days)",
            "idle_days": "Days Since Last Activity",
            "last_activity_at": "Last Activity",
        }
    ),
)

EXCEPTION_REASON_TEXT: Mapping[str, str] = MappingProxyType(
    {
        "submitted_after_report": "Case submission after report generation",
        "activity_after_report": "Last activity after report generation",
        "activity_before_submission": "Last activity before case submission",
        "missing_activity": "Missing last activity",
        "idle_at_least_days": "Idle >= {days} days",
        "age_at_least_days": "Case age >= {days} days",
        "missing_submission": "Missing case submission date",
        "missing_owner": "Missing submitter",
        "missing_status": "Missing status",
        "missing_step": "Missing step",
    }
)

WORKBOOK = WorkbookContent(
    recent_trends_heading="Recent trend snapshots",
    empty_trends_message="Trend history starts after the first run.",
    sheet_names=MappingProxyType(
        {
            "summary": "Summary",
            "normalized_records": "Normalized Records",
            "in_the_works": "In The Works",
            "backlog": "Backlog",
            "submitted_by_activity": "Submitted By Activity",
            "daily_closures": "Daily Closures",
            "closed_by_month": "Closed By Month",
            "exceptions": "Exceptions",
            "history_trends": "History Trends",
            "owner_history": "Owner History",
            "completion_history": "Completion History",
        }
    ),
)

COMPLETION_DATE_NOTE = "Completion dates are estimated from the last recorded update."

OTHER_SUBMITTERS = "Others"
MISSING_SUBMITTER = "Not recorded"


def action_bucket_labels(backlog_days: float) -> dict[str, str]:
    """Use the actual day boundary rather than an unexplained age threshold."""
    return {
        "young_active": f"Up to {backlog_days:g} Days · Active",
        "young_stale": f"Up to {backlog_days:g} Days · Idle",
        "backlog_active": f"Over {backlog_days:g} Days · Active",
        "backlog_stale": f"Over {backlog_days:g} Days · Idle",
    }
