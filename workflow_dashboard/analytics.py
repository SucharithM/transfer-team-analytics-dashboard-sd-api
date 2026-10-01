"""Analytical summaries for workflow operations dashboard outputs."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .config import DashboardConfig
from .dashboard_content import (
    COMMON,
    EXCEPTION_REASON_TEXT,
    KPI_CONTENT,
    KpiKey,
    MISSING_SUBMITTER,
    OTHER_SUBMITTERS,
    PresentationContext,
    WORKFLOW_STEP_ORDER,
    action_bucket_labels,
)
from .number_format import format_one_decimal
from .time_utils import dashboard_time_series, dashboard_timestamp

AGING_BANDS: tuple[tuple[str, float, float | None], ...] = (
    ("0–3d", 0.0, 3.0),
    ("3–7d", 3.0, 7.0),
    ("7–14d", 7.0, 14.0),
    ("14–30d", 14.0, 30.0),
    ("30–60d", 30.0, 60.0),
    ("60d+", 60.0, None),
)
AGING_BAND_LABELS = tuple(label for label, _, _ in AGING_BANDS)
ACTION_BUCKET_LABELS = action_bucket_labels(7.0)
ACTION_BUCKETS: tuple[tuple[str, str, int], ...] = tuple(
    (key, label, order)
    for order, (key, label) in enumerate(ACTION_BUCKET_LABELS.items())
)
ACTION_BUCKET_ORDERS = {key: order for key, _, order in ACTION_BUCKETS}
_STEP_DASH_PATTERN = re.compile(r"\s*[-‐‑‒–—−]\s*")
_EVALUATION_TYPE_SUFFIX = re.compile(
    r"\s+Transcript\s+Evaluation\s*$",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class Kpi:
    key: KpiKey
    value: str
    help_text: str
    warning_caption: str | None = None

    @property
    def label(self) -> str:
        """Resolve display copy without using it as the KPI's identity."""

        return KPI_CONTENT[self.key].label


@dataclass(frozen=True)
class AnalyticsBundle:
    dashboard_title: str
    team_members: tuple[str, ...]
    generated_at: pd.Timestamp
    kpis: list[Kpi]
    in_the_works: pd.DataFrame
    backlog: pd.DataFrame
    exceptions: pd.DataFrame
    exception_counts: pd.DataFrame
    chart_tables: dict[str, pd.DataFrame]
    snapshot_metrics: dict[str, Any]
    presentation: PresentationContext = PresentationContext()


def _fmt_count(value: int | float | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{int(value):,}"


def _fmt_days(value: float | None) -> str:
    return format_one_decimal(value, suffix="d")


def _fmt_percentage(value: float) -> str:
    return f"{value * 100:.12g}%"


def _build_kpi(
    key: KpiKey,
    value: str,
    *,
    warning_caption: str | None = None,
    **help_values: object,
) -> Kpi:
    content = KPI_CONTENT[key]
    return Kpi(
        key=key,
        value=value,
        help_text=content.format_help(**help_values),
        warning_caption=warning_caption,
    )


def _median_kpi_display(
    median_value: float | None,
    *,
    valid_count: int,
    total_count: int,
    minimum_completeness: float,
) -> tuple[str, str | None]:
    coverage = COMMON.valid_count_template.format(
        valid=valid_count,
        total=total_count,
    )
    if total_count == 0:
        return "—", coverage
    if valid_count / total_count < minimum_completeness:
        return "—", (f"{coverage} · below " f"{_fmt_percentage(minimum_completeness)}")
    if median_value is None or pd.isna(median_value):
        return "—", coverage
    return _fmt_days(median_value), None


def _is_today(series: pd.Series, generated_at: pd.Timestamp) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=bool)
    generated_timestamp = dashboard_timestamp(generated_at)
    timestamps = dashboard_time_series(series)
    return (
        timestamps.notna()
        & (timestamps <= generated_timestamp)
        & (timestamps.dt.date == generated_timestamp.date())
    )


def _duration_values(df: pd.DataFrame, column: str) -> pd.Series:
    """Return numeric duration values aligned to a frame's index."""

    if column not in df.columns:
        return pd.Series(float("nan"), index=df.index, dtype=float)
    return pd.to_numeric(df[column], errors="coerce")


def _valid_duration_mask(df: pd.DataFrame, column: str) -> pd.Series:
    """Identify present, non-negative durations eligible for statistics."""

    values = _duration_values(df, column)
    return values.notna() & values.ge(0)


def _valid_idle_mask(df: pd.DataFrame, generated_at: pd.Timestamp) -> pd.Series:
    """Identify idle durations with valid values and timestamp chronology."""

    valid_duration = _valid_duration_mask(df, "idle_days")
    if "last_activity_at" not in df.columns:
        return pd.Series(False, index=df.index, dtype=bool)

    last_activity_at = pd.to_datetime(
        df["last_activity_at"], errors="coerce", utc=True, format="mixed"
    )
    generated_timestamp = pd.Timestamp(generated_at)
    if generated_timestamp.tzinfo is None:
        generated_timestamp = generated_timestamp.tz_localize("UTC")
    else:
        generated_timestamp = generated_timestamp.tz_convert("UTC")

    valid_chronology = last_activity_at.notna() & last_activity_at.le(
        generated_timestamp
    )
    if "submitted_at" in df.columns:
        submitted_at = pd.to_datetime(
            df["submitted_at"], errors="coerce", utc=True, format="mixed"
        )
        valid_chronology &= submitted_at.isna() | last_activity_at.ge(submitted_at)

    return valid_duration & valid_chronology


def _step_display(value: object) -> str:
    """Return a cleaned source label without changing its punctuation."""

    if value is None or pd.isna(value):
        return COMMON.no_step
    text = " ".join(str(value).split())
    return text or COMMON.no_step


def _step_key(value: object) -> str:
    """Build a comparison key that tolerates whitespace and dash variants."""

    display = _step_display(value)
    normalized = _STEP_DASH_PATTERN.sub(" - ", display)
    return " ".join(normalized.split()).casefold()


def _preferred_step_label(values: pd.Series, fallback: str) -> str:
    """Choose a deterministic observed label while preserving source wording."""

    if values.empty:
        return fallback
    counts = values.value_counts()
    highest_count = int(counts.max())
    candidates = [
        str(value) for value, count in counts.items() if int(count) == highest_count
    ]
    return min(candidates, key=lambda value: (value.casefold(), value))


def _workflow_aging_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Count open cases by ordered workflow step and lower-inclusive age band."""

    columns = [
        "step_name",
        "step_order",
        "aging_band",
        "band_order",
        "count",
        "step_total",
        "excluded_age_count",
    ]
    metric = df.copy()
    if "step_name" not in metric.columns:
        metric["step_name"] = COMMON.no_step
    metric["_step_display"] = metric["step_name"].map(_step_display)
    metric["_step_key"] = metric["_step_display"].map(_step_key)

    canonical_keys = {
        _step_key(step_name): step_name for step_name in WORKFLOW_STEP_ORDER
    }
    no_step_key = _step_key(COMMON.no_step)
    ordered_steps: list[tuple[str, str]] = []
    for step_name in WORKFLOW_STEP_ORDER:
        key = _step_key(step_name)
        observed = metric.loc[metric["_step_key"].eq(key), "_step_display"]
        ordered_steps.append((key, _preferred_step_label(observed, step_name)))

    observed_keys = set(metric["_step_key"])
    unknown_steps = []
    for key in observed_keys - set(canonical_keys) - {no_step_key}:
        observed = metric.loc[metric["_step_key"].eq(key), "_step_display"]
        unknown_steps.append(
            (key, _preferred_step_label(observed, COMMON.missing_value))
        )
    ordered_steps.extend(
        sorted(
            unknown_steps,
            key=lambda item: (item[1].casefold(), item[1]),
        )
    )
    if no_step_key in observed_keys:
        ordered_steps.append((no_step_key, COMMON.no_step))

    age_values = _duration_values(metric, "age_days")
    valid_age = age_values.notna() & age_values.ge(0)
    metric["_aging_band"] = pd.Series(pd.NA, index=metric.index, dtype="object")
    for label, lower, upper in AGING_BANDS:
        in_band = valid_age & age_values.ge(lower)
        if upper is not None:
            in_band &= age_values.lt(upper)
        metric.loc[in_band, "_aging_band"] = label

    totals = metric["_step_key"].value_counts().to_dict()
    valid_counts = (
        metric.loc[metric["_aging_band"].notna(), "_step_key"].value_counts().to_dict()
    )
    cell_counts = (
        metric.loc[metric["_aging_band"].notna()]
        .groupby(["_step_key", "_aging_band"], observed=True)
        .size()
        .to_dict()
    )

    rows: list[dict[str, object]] = []
    for step_order, (step_key, step_name) in enumerate(ordered_steps):
        step_total = int(totals.get(step_key, 0))
        excluded_age_count = step_total - int(valid_counts.get(step_key, 0))
        for band_order, band_label in enumerate(AGING_BAND_LABELS):
            rows.append(
                {
                    "step_name": step_name,
                    "step_order": step_order,
                    "aging_band": band_label,
                    "band_order": band_order,
                    "count": int(cell_counts.get((step_key, band_label), 0)),
                    "step_total": step_total,
                    "excluded_age_count": excluded_age_count,
                }
            )
    return pd.DataFrame(rows, columns=columns)


def _age_idle_action_matrix(
    df: pd.DataFrame,
    *,
    config: DashboardConfig,
    generated_at: pd.Timestamp,
    valid_idle_mask: pd.Series | None = None,
) -> pd.DataFrame:
    """Build privacy-limited point data for open-package action triage."""

    columns = [
        "record_id",
        "step_name",
        "age_days",
        "idle_days",
        "last_activity_at",
        "action_bucket",
        "action_order",
    ]
    if df.empty:
        table = pd.DataFrame(columns=columns)
        table.attrs["total_open_count"] = 0
        table.attrs["backlog_age_days"] = float(config.backlog_age_days)
        table.attrs["old_age_days"] = float(config.old_age_days)
        table.attrs["stale_idle_days"] = float(config.stale_idle_days)
        return table

    age_days = _duration_values(df, "age_days")
    idle_days = _duration_values(df, "idle_days")
    valid_age = _valid_duration_mask(df, "age_days")
    valid_idle = (
        valid_idle_mask.reindex(df.index, fill_value=False)
        if valid_idle_mask is not None
        else _valid_idle_mask(df, generated_at)
    )

    if "submitted_at" in df.columns:
        submitted_at = pd.to_datetime(
            df["submitted_at"], errors="coerce", utc=True, format="mixed"
        )
        generated_timestamp = pd.Timestamp(generated_at)
        if generated_timestamp.tzinfo is None:
            generated_timestamp = generated_timestamp.tz_localize("UTC")
        else:
            generated_timestamp = generated_timestamp.tz_convert("UTC")
        valid_age &= submitted_at.notna() & submitted_at.le(generated_timestamp)

    eligible = valid_age & valid_idle
    table = df.loc[eligible].copy()
    table["age_days"] = age_days.loc[eligible].astype(float)
    table["idle_days"] = idle_days.loc[eligible].astype(float)
    table["step_name"] = table.get(
        "step_name", pd.Series(index=table.index, dtype=object)
    ).map(_step_display)
    if "record_id" not in table.columns:
        table["record_id"] = COMMON.missing_value
    table["record_id"] = table["record_id"].map(
        lambda value: (
            COMMON.missing_value
            if value is None or pd.isna(value) or not str(value).strip()
            else str(value).strip()
        )
    )

    backlog = table["age_days"].gt(config.backlog_age_days)
    stale = table["idle_days"].ge(config.stale_idle_days)
    table["action_bucket"] = "young_active"
    table.loc[~backlog & stale, "action_bucket"] = "young_stale"
    table.loc[backlog & ~stale, "action_bucket"] = "backlog_active"
    table.loc[backlog & stale, "action_bucket"] = "backlog_stale"
    table["action_order"] = table["action_bucket"].map(ACTION_BUCKET_ORDERS).astype(int)

    canonical_order = {
        _step_key(step_name): order
        for order, step_name in enumerate(WORKFLOW_STEP_ORDER)
    }
    unknown_keys = sorted(
        {
            _step_key(value)
            for value in table["step_name"]
            if _step_key(value) not in canonical_order
            and _step_key(value) != _step_key(COMMON.no_step)
        }
    )
    step_order = dict(canonical_order)
    step_order.update(
        {key: len(canonical_order) + order for order, key in enumerate(unknown_keys)}
    )
    step_order[_step_key(COMMON.no_step)] = len(canonical_order) + len(unknown_keys)
    table["_step_order"] = table["step_name"].map(
        lambda value: step_order[_step_key(value)]
    )
    table["_record_sort"] = table["record_id"].str.casefold()
    table = (
        table.sort_values(
            ["_step_order", "_record_sort"],
            kind="stable",
        )
        .drop(columns=["_step_order", "_record_sort"])
        .reset_index(drop=True)
    )
    table = table[columns]
    table.attrs["total_open_count"] = int(len(df))
    table.attrs["backlog_age_days"] = float(config.backlog_age_days)
    table.attrs["old_age_days"] = float(config.old_age_days)
    table.attrs["stale_idle_days"] = float(config.stale_idle_days)
    return table


def _completion_days(df: pd.DataFrame) -> pd.Series:
    """Calculate raw completion durations without hiding negative values."""

    if not {"submitted_at", "last_activity_at"}.issubset(df.columns):
        return pd.Series(float("nan"), index=df.index, dtype=float)
    submitted_at = pd.to_datetime(
        df["submitted_at"], errors="coerce", utc=True, format="mixed"
    )
    last_activity_at = pd.to_datetime(
        df["last_activity_at"], errors="coerce", utc=True, format="mixed"
    )
    return (last_activity_at - submitted_at).dt.total_seconds() / 86400


def _evaluation_type(value: object) -> str:
    """Parse the non-PII evaluation type from a package label."""

    if value is None or pd.isna(value):
        return COMMON.unclassified_evaluation_type
    parts = [part.strip() for part in str(value).split("|")]
    if len(parts) != 3 or any(not part for part in parts):
        return COMMON.unclassified_evaluation_type
    evaluation_type = _EVALUATION_TYPE_SUFFIX.sub("", parts[0]).strip()
    return evaluation_type or COMMON.unclassified_evaluation_type


def _evaluation_type_summary(
    df: pd.DataFrame,
    *,
    in_the_works: pd.DataFrame,
    backlog: pd.DataFrame,
    fully_processed: pd.DataFrame,
    minimum_wait_completeness: float,
    minimum_completion_completeness: float,
) -> pd.DataFrame:
    """Summarize inventory, backlog, and timing by evaluation type."""

    columns = [
        "evaluation_type",
        "total_count",
        "in_progress_count",
        "completed_count",
        "completion_rate",
        "backlog_count",
        "open_age_valid_count",
        "median_open_age_days",
        "completion_valid_count",
        "median_completion_days",
    ]
    if df.empty:
        return pd.DataFrame(columns=columns)

    metric = df.copy()
    metric["evaluation_type"] = metric.get(
        "item_label",
        pd.Series(pd.NA, index=metric.index, dtype="object"),
    ).map(_evaluation_type)
    open_types = in_the_works.get(
        "item_label",
        pd.Series(pd.NA, index=in_the_works.index, dtype="object"),
    ).map(_evaluation_type)
    open_packages = in_the_works.copy()
    open_packages["evaluation_type"] = open_types
    open_packages["_open_age_days"] = _duration_values(
        open_packages,
        "age_days",
    )
    open_packages["_valid_open_age"] = (
        open_packages["_open_age_days"].notna()
        & open_packages["_open_age_days"].ge(0)
    )
    open_packages.loc[
        ~open_packages["_valid_open_age"],
        "_open_age_days",
    ] = pd.NA
    backlog_types = backlog.get(
        "item_label",
        pd.Series(pd.NA, index=backlog.index, dtype="object"),
    ).map(_evaluation_type)

    completed = fully_processed.copy()
    completed["evaluation_type"] = completed.get(
        "item_label",
        pd.Series(pd.NA, index=completed.index, dtype="object"),
    ).map(_evaluation_type)
    completed["completion_days"] = _completion_days(completed)
    completed["_valid_completion"] = (
        completed["completion_days"].notna()
        & completed["completion_days"].ge(0)
    )
    completed.loc[~completed["_valid_completion"], "completion_days"] = pd.NA

    total_counts = metric["evaluation_type"].value_counts()
    open_counts = open_types.value_counts()
    backlog_counts = backlog_types.value_counts()
    completed_counts = completed["evaluation_type"].value_counts()
    open_age_valid_counts = (
        open_packages.loc[
            open_packages["_valid_open_age"],
            "evaluation_type",
        ].value_counts()
    )
    completion_valid_counts = (
        completed.loc[completed["_valid_completion"], "evaluation_type"]
        .value_counts()
    )

    rows: list[dict[str, object]] = []
    for evaluation_type, total_count in total_counts.items():
        in_progress_count = int(open_counts.get(evaluation_type, 0))
        backlog_count = int(backlog_counts.get(evaluation_type, 0))
        completed_count = int(completed_counts.get(evaluation_type, 0))
        open_age_valid_count = int(
            open_age_valid_counts.get(evaluation_type, 0)
        )
        completion_valid_count = int(
            completion_valid_counts.get(evaluation_type, 0)
        )
        median_open_age_days: object = pd.NA
        open_age_coverage = (
            open_age_valid_count / in_progress_count
            if in_progress_count
            else None
        )
        if (
            open_age_valid_count
            and open_age_coverage is not None
            and open_age_coverage >= minimum_wait_completeness
        ):
            valid_open_ages = open_packages.loc[
                open_packages["evaluation_type"].eq(evaluation_type)
                & open_packages["_valid_open_age"],
                "_open_age_days",
            ]
            median_open_age_days = float(valid_open_ages.median())

        median_completion_days: object = pd.NA
        completion_coverage = (
            completion_valid_count / completed_count
            if completed_count
            else None
        )
        if (
            completion_valid_count
            and completion_coverage is not None
            and completion_coverage >= minimum_completion_completeness
        ):
            valid_completion_days = completed.loc[
                completed["evaluation_type"].eq(evaluation_type)
                & completed["_valid_completion"],
                "completion_days",
            ]
            median_completion_days = float(valid_completion_days.median())
        rows.append(
            {
                "evaluation_type": evaluation_type,
                "total_count": int(total_count),
                "in_progress_count": in_progress_count,
                "completed_count": completed_count,
                "completion_rate": (
                    completed_count / int(total_count)
                    if total_count
                    else pd.NA
                ),
                "backlog_count": backlog_count,
                "open_age_valid_count": open_age_valid_count,
                "median_open_age_days": median_open_age_days,
                "completion_valid_count": completion_valid_count,
                "median_completion_days": median_completion_days,
            }
        )

    table = pd.DataFrame(rows, columns=columns)
    table["_sort_label"] = table["evaluation_type"].astype(str).str.casefold()
    table = (
        table.sort_values(
            ["total_count", "_sort_label"],
            ascending=[False, True],
            kind="stable",
        )
        .drop(columns="_sort_label")
        .reset_index(drop=True)
    )
    for column in [
        "completion_rate",
        "median_open_age_days",
        "median_completion_days",
    ]:
        table[column] = table[column].astype("Float64")
    return table


def _ranked_count(
    df: pd.DataFrame,
    column: str,
    *,
    top_n: int | None = None,
    label: str = COMMON.missing_value,
    other_label: str | None = None,
    pinned_labels: tuple[str, ...] = (),
) -> pd.DataFrame:
    if df.empty or column not in df.columns:
        return pd.DataFrame(columns=[column, "count"])
    ranked = (
        df[column]
        .fillna(label)
        .replace("", label)
        .value_counts()
        .rename_axis(column)
        .reset_index(name="count")
    )
    ranked["_sort_label"] = ranked[column].astype(str).str.casefold()
    ranked = ranked.sort_values(
        ["count", "_sort_label"],
        ascending=[False, True],
        kind="stable",
    )

    if top_n is not None and len(ranked) > top_n:
        if top_n < 2 or other_label is None:
            raise ValueError(
                "Truncated count tables require at least two rows and an Other label"
            )
        pinned_mask = ranked[column].astype(str).isin(pinned_labels)
        pinned = ranked.loc[pinned_mask].copy()
        available_slots = top_n - 1 - len(pinned)
        if available_slots < 0:
            raise ValueError("Pinned labels exceed the available count-table rows")
        unpinned = ranked.loc[~pinned_mask]
        retained = pd.concat(
            [pinned, unpinned.head(available_slots)],
            ignore_index=True,
        )
        remainder = unpinned.iloc[available_slots:]
        aggregate = pd.DataFrame(
            [
                {
                    column: other_label.format(count=len(remainder)),
                    "count": int(remainder["count"].sum()),
                }
            ]
        )
        aggregate["_sort_label"] = aggregate[column].astype(str).str.casefold()
        ranked = pd.concat([retained, aggregate], ignore_index=True)

    return (
        ranked.sort_values(
            ["count", "_sort_label"],
            ascending=[True, False],
            kind="stable",
        )
        .drop(columns="_sort_label")
        .reset_index(drop=True)
    )


def _status_mix(df: pd.DataFrame) -> pd.DataFrame:
    """Count open statuses plus one explicit Completed End-step category."""

    columns = ["status", "count"]
    if df.empty:
        return pd.DataFrame(columns=columns)

    status_values = (
        df["status"].copy()
        if "status" in df.columns
        else pd.Series(pd.NA, index=df.index, dtype="object")
    )
    terminal = (
        df["is_terminal"].fillna(False).astype(bool)
        if "is_terminal" in df.columns
        else pd.Series(False, index=df.index, dtype=bool)
    )
    status_values.loc[terminal] = "Completed"
    status_frame = pd.DataFrame({"status": status_values}, index=df.index)
    return _ranked_count(
        status_frame,
        "status",
        top_n=12,
        label=COMMON.no_status,
        other_label=COMMON.other_statuses_template,
        pinned_labels=("Completed",),
    )


def _median_by(
    df: pd.DataFrame,
    group_col: str,
    value_col: str,
    *,
    label: str = COMMON.missing_value,
    minimum_completeness: float = 0.95,
    valid_count_col: str = "valid_count",
    total_count_col: str = "total_count",
) -> pd.DataFrame:
    if df.empty or group_col not in df.columns or value_col not in df.columns:
        return pd.DataFrame(
            columns=[
                group_col,
                value_col,
                valid_count_col,
                total_count_col,
            ]
        )
    metric = df.copy()
    metric[group_col] = metric[group_col].fillna(label).replace("", label)
    metric["_duration_value"] = pd.to_numeric(metric[value_col], errors="coerce")
    metric["_valid_duration"] = metric["_duration_value"].notna() & metric[
        "_duration_value"
    ].ge(0)
    metric.loc[~metric["_valid_duration"], "_duration_value"] = pd.NA
    grouped = (
        metric.groupby(group_col, dropna=False)
        .agg(
            **{
                value_col: ("_duration_value", "median"),
                valid_count_col: ("_valid_duration", "sum"),
                total_count_col: ("_valid_duration", "size"),
            }
        )
        .reset_index()
    )
    grouped[valid_count_col] = grouped[valid_count_col].astype(int)
    grouped[total_count_col] = grouped[total_count_col].astype(int)
    complete = grouped[total_count_col].gt(0) & (
        grouped[valid_count_col] / grouped[total_count_col]
    ).ge(minimum_completeness)
    grouped.loc[~complete, value_col] = pd.NA
    grouped[value_col] = grouped[value_col].astype("Float64")
    return grouped.sort_values(
        value_col, ascending=True, na_position="last"
    ).reset_index(drop=True)


def _member_key(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).split()).casefold()


def _team_member_counts(
    df: pd.DataFrame, team_members: tuple[str, ...]
) -> pd.DataFrame:
    """Count every case, grouping non-roster and missing submitters explicitly."""

    member_lookup = {_member_key(member): member for member in team_members}
    counts = {member: 0 for member in team_members}
    counts.setdefault(OTHER_SUBMITTERS, 0)
    owners = df.get("owner", pd.Series(None, index=df.index, dtype=object))
    for value, count in owners.value_counts(dropna=False).items():
        member = _submitter_group(value, member_lookup)
        counts[member] = counts.get(member, 0) + int(count)
    return (
        pd.DataFrame(
            [{"owner": member, "count": count} for member, count in counts.items()]
        )
        .sort_values(["count", "owner"], ascending=[True, True])
        .reset_index(drop=True)
    )


def _submitter_group(value: object, member_lookup: dict[str, str]) -> str:
    key = _member_key(value)
    if not key:
        return MISSING_SUBMITTER
    return member_lookup.get(key, OTHER_SUBMITTERS)


def _submitted_by_date_activity(
    df: pd.DataFrame,
    team_members: tuple[str, ...],
    generated_at: pd.Timestamp,
) -> pd.DataFrame:
    if df.empty or "submitted_at" not in df.columns:
        return pd.DataFrame(columns=["owner", "submitted_date", "count"])

    metric = df.dropna(subset=["submitted_at"]).copy()
    if metric.empty:
        return pd.DataFrame(columns=["owner", "submitted_date", "count"])

    member_lookup = {_member_key(member): member for member in team_members}
    metric["owner"] = metric.get(
        "owner", pd.Series(None, index=metric.index, dtype=object)
    ).map(
        lambda value: _submitter_group(value, member_lookup)
    )

    submitted_at = dashboard_time_series(metric["submitted_at"])
    generated_timestamp = dashboard_timestamp(generated_at)
    eligible = submitted_at.notna() & (submitted_at <= generated_timestamp)
    metric = metric.loc[eligible].copy()
    if metric.empty:
        return pd.DataFrame(columns=["owner", "submitted_date", "count"])

    metric["submitted_date"] = submitted_at.loc[eligible].dt.date
    counts = (
        metric.groupby(["owner", "submitted_date"], dropna=False).size().rename("count")
    )
    dates = sorted(metric["submitted_date"].unique())
    members = list(dict.fromkeys((*team_members, OTHER_SUBMITTERS)))
    if metric["owner"].eq(MISSING_SUBMITTER).any() and MISSING_SUBMITTER not in members:
        members.append(MISSING_SUBMITTER)
    complete_index = pd.MultiIndex.from_product(
        [members, dates], names=["owner", "submitted_date"]
    )
    return (
        counts.reindex(complete_index, fill_value=0)
        .reset_index()
        .sort_values(["submitted_date", "owner"])
        .reset_index(drop=True)
    )


def _daily_closures(df: pd.DataFrame, generated_at: pd.Timestamp) -> pd.DataFrame:
    columns = ["closed_date", "closed_count", "rolling_7_day_avg"]
    if df.empty or "last_activity_at" not in df.columns:
        return pd.DataFrame(columns=columns)

    metric = df.dropna(subset=["last_activity_at"]).copy()
    if metric.empty:
        return pd.DataFrame(columns=columns)

    metric["closed_date"] = (
        dashboard_time_series(metric["last_activity_at"])
        .dt.tz_localize(None)
        .dt.normalize()
    )
    generated_date = dashboard_timestamp(generated_at).tz_localize(None).normalize()
    metric = metric[
        metric["closed_date"].notna() & (metric["closed_date"] < generated_date)
    ].copy()
    if metric.empty:
        return pd.DataFrame(columns=columns)

    counts = (
        metric.groupby("closed_date", dropna=False)
        .size()
        .rename("closed_count")
        .reset_index()
        .sort_values("closed_date")
    )

    end_date = generated_date - pd.Timedelta(days=1)
    calendar = pd.DataFrame(
        {"closed_date": pd.date_range(counts["closed_date"].min(), end_date, freq="D")}
    )
    table = calendar.merge(counts, on="closed_date", how="left")
    table["closed_count"] = table["closed_count"].fillna(0).astype(int)
    table["rolling_7_day_avg"] = (
        table["closed_count"].rolling(window=7, min_periods=7).mean()
    )
    return table[columns]


def _closed_by_month(
    df: pd.DataFrame,
    generated_at: pd.Timestamp,
    *,
    minimum_completeness: float = 0.95,
) -> pd.DataFrame:
    columns = [
        "closed_month",
        "closed_month_label",
        "closed_count",
        "median_completion_days",
        "completion_valid_count",
        "completion_total_count",
    ]
    if df.empty or "last_activity_at" not in df.columns:
        return pd.DataFrame(columns=columns)

    metric = df.dropna(subset=["last_activity_at"]).copy()
    if metric.empty:
        return pd.DataFrame(columns=columns)

    closed_at = dashboard_time_series(metric["last_activity_at"])
    generated_timestamp = dashboard_timestamp(generated_at)
    eligible = closed_at.notna() & (closed_at <= generated_timestamp)
    metric = metric.loc[eligible].copy()
    if metric.empty:
        return pd.DataFrame(columns=columns)

    metric["closed_month_start"] = (
        closed_at.loc[eligible].dt.tz_localize(None).dt.to_period("M").dt.to_timestamp()
    )
    metric["completion_days"] = _completion_days(metric)
    metric["_valid_completion"] = metric["completion_days"].notna() & metric[
        "completion_days"
    ].ge(0)
    metric.loc[~metric["_valid_completion"], "completion_days"] = pd.NA
    observed = (
        metric.groupby("closed_month_start", dropna=False)
        .agg(
            closed_count=("_valid_completion", "size"),
            median_completion_days=("completion_days", "median"),
            completion_valid_count=("_valid_completion", "sum"),
        )
        .reset_index()
        .sort_values("closed_month_start")
        .reset_index(drop=True)
    )
    observed["completion_total_count"] = observed["closed_count"]
    calendar = pd.DataFrame(
        {
            "closed_month_start": pd.date_range(
                observed["closed_month_start"].min(),
                observed["closed_month_start"].max(),
                freq="MS",
            )
        }
    )
    table = calendar.merge(observed, on="closed_month_start", how="left")
    table["closed_count"] = table["closed_count"].fillna(0).astype(int)
    table["completion_valid_count"] = (
        table["completion_valid_count"].fillna(0).astype(int)
    )
    table["completion_total_count"] = (
        table["completion_total_count"].fillna(0).astype(int)
    )
    complete = table["completion_total_count"].gt(0) & (
        table["completion_valid_count"] / table["completion_total_count"]
    ).ge(minimum_completeness)
    table.loc[~complete, "median_completion_days"] = pd.NA

    generated_month = generated_timestamp.tz_localize(None)
    generated_month_start = generated_month.to_period("M").to_timestamp()
    table["closed_month"] = table["closed_month_start"].dt.strftime("%Y-%m")
    table["closed_month_label"] = table["closed_month_start"].dt.strftime("%b %Y")
    table.loc[
        table["closed_month_start"] == generated_month_start,
        "closed_month_label",
    ] += COMMON.month_to_date_suffix
    table["median_completion_days"] = table["median_completion_days"].astype("Float64")
    return table[columns]


def _has_text(value: object) -> bool:
    if value is None or pd.isna(value):
        return False
    return str(value).strip() != ""


def add_exception_reasons(
    df: pd.DataFrame,
    config: DashboardConfig,
    *,
    valid_idle_mask: pd.Series,
) -> pd.DataFrame:
    """Attach exception reason text for problem-row reporting."""

    if df.empty:
        out = df.copy()
        out["exception_reasons"] = pd.Series(dtype=str)
        return out

    reasons: list[list[str]] = []
    completion_days = _completion_days(df)
    for (_, row), completion_days_value, valid_idle in zip(
        df.iterrows(),
        completion_days.tolist(),
        valid_idle_mask.tolist(),
    ):
        row_reasons: list[str] = []
        age_days = pd.to_numeric(row.get("age_days"), errors="coerce")
        idle_days = pd.to_numeric(row.get("idle_days"), errors="coerce")
        if pd.notna(age_days) and float(age_days) < 0:
            row_reasons.append(EXCEPTION_REASON_TEXT["submitted_after_report"])
        if pd.notna(idle_days) and float(idle_days) < 0:
            row_reasons.append(EXCEPTION_REASON_TEXT["activity_after_report"])
        if pd.notna(completion_days_value) and float(completion_days_value) < 0:
            row_reasons.append(EXCEPTION_REASON_TEXT["activity_before_submission"])

        if not row.get("is_terminal", False):
            if pd.isna(row.get("last_activity_at")):
                row_reasons.append(EXCEPTION_REASON_TEXT["missing_activity"])
            if (
                valid_idle
                and pd.notna(idle_days)
                and float(idle_days) >= config.stale_idle_days
            ):
                row_reasons.append(
                    EXCEPTION_REASON_TEXT["idle_at_least_days"].format(
                        days=config.stale_idle_days
                    )
                )
            if pd.notna(age_days) and float(age_days) >= config.old_age_days:
                row_reasons.append(
                    EXCEPTION_REASON_TEXT["age_at_least_days"].format(
                        days=config.old_age_days
                    )
                )
            if pd.isna(row.get("submitted_at")):
                row_reasons.append(EXCEPTION_REASON_TEXT["missing_submission"])
            if not _has_text(row.get("owner")):
                row_reasons.append(EXCEPTION_REASON_TEXT["missing_owner"])
            if not _has_text(row.get("status")):
                row_reasons.append(EXCEPTION_REASON_TEXT["missing_status"])
            if not _has_text(row.get("step_name")):
                row_reasons.append(EXCEPTION_REASON_TEXT["missing_step"])
        reasons.append(row_reasons)

    out = df.copy()
    out["exception_reasons"] = ["; ".join(values) for values in reasons]
    return out[out["exception_reasons"].str.len() > 0].copy()


def _exception_counts(exceptions: pd.DataFrame) -> pd.DataFrame:
    if exceptions.empty:
        return pd.DataFrame(columns=["reason", "count"])
    counter: Counter[str] = Counter()
    for value in exceptions["exception_reasons"].dropna():
        for reason in str(value).split("; "):
            if reason:
                counter[reason] += 1
    return pd.DataFrame(counter.items(), columns=["reason", "count"]).sort_values(
        "count", ascending=True
    )


def build_analytics(
    df: pd.DataFrame,
    *,
    config: DashboardConfig,
    generated_at: pd.Timestamp,
) -> AnalyticsBundle:
    """Build all current-state metrics and chart-ready tables."""

    in_the_works = (
        df[~df["is_terminal"]].copy()
        if not df.empty
        else pd.DataFrame(columns=df.columns)
    )
    if "submitted_at" in in_the_works.columns:
        submitted_at = pd.to_datetime(
            in_the_works["submitted_at"], errors="coerce", utc=True
        )
        cutoff = pd.Timestamp(generated_at)
        if cutoff.tzinfo is None:
            cutoff = cutoff.tz_localize("UTC")
        else:
            cutoff = cutoff.tz_convert("UTC")
        cutoff -= pd.Timedelta(days=config.backlog_age_days)
        backlog = in_the_works[submitted_at.notna() & (submitted_at < cutoff)].copy()
    else:
        backlog = in_the_works[
            in_the_works["age_days"].notna()
            & (in_the_works["age_days"] > config.backlog_age_days)
        ].copy()
    fully_processed = (
        df[df["is_terminal"]].copy()
        if not df.empty
        else pd.DataFrame(columns=df.columns)
    )
    reached_end_today = (
        int(_is_today(fully_processed["last_activity_at"], generated_at).sum())
        if not fully_processed.empty
        else 0
    )
    full_valid_idle_mask = _valid_idle_mask(df, generated_at)
    exceptions = add_exception_reasons(
        df,
        config,
        valid_idle_mask=full_valid_idle_mask,
    )

    valid_age_mask = _valid_duration_mask(in_the_works, "age_days")
    valid_age_values = _duration_values(in_the_works, "age_days").loc[valid_age_mask]
    age_total_count = int(len(in_the_works))
    age_valid_count = int(valid_age_mask.sum())
    age_completeness = age_valid_count / age_total_count if age_total_count else None
    candidate_median_age = (
        valid_age_values.median() if not valid_age_values.empty else None
    )
    median_age = (
        candidate_median_age
        if age_completeness is not None
        and age_completeness >= config.minimum_wait_completeness
        and pd.notna(candidate_median_age)
        else None
    )
    idle_total_count = int(len(in_the_works))
    valid_idle_mask = full_valid_idle_mask.loc[in_the_works.index]
    valid_idle_values = _duration_values(in_the_works, "idle_days").loc[valid_idle_mask]
    idle_valid_count = int(valid_idle_mask.sum())
    idle_completeness = (
        idle_valid_count / idle_total_count if idle_total_count else None
    )
    candidate_median_idle = (
        valid_idle_values.median() if not valid_idle_values.empty else None
    )
    median_idle = (
        candidate_median_idle
        if idle_completeness is not None
        and idle_completeness >= config.minimum_idle_completeness
        and pd.notna(candidate_median_idle)
        else None
    )
    oldest_age = valid_age_values.max() if not valid_age_values.empty else None
    submitted_by_workload = _team_member_counts(df, config.team_members)
    submitted_by_date_activity = _submitted_by_date_activity(
        df, config.team_members, generated_at
    )
    daily_closures = _daily_closures(fully_processed, generated_at)
    closed_by_month = _closed_by_month(
        fully_processed,
        generated_at,
        minimum_completeness=config.minimum_completion_completeness,
    )
    wait_value, wait_warning = _median_kpi_display(
        candidate_median_age,
        valid_count=age_valid_count,
        total_count=age_total_count,
        minimum_completeness=config.minimum_wait_completeness,
    )
    idle_value, idle_warning = _median_kpi_display(
        candidate_median_idle,
        valid_count=idle_valid_count,
        total_count=idle_total_count,
        minimum_completeness=config.minimum_idle_completeness,
    )

    kpis = [
        _build_kpi(
            "total_records",
            _fmt_count(len(df)),
        ),
        _build_kpi(
            "in_the_works",
            _fmt_count(len(in_the_works)),
        ),
        _build_kpi(
            "cases_closed_today",
            _fmt_count(reached_end_today),
        ),
        _build_kpi(
            "total_cases_closed",
            _fmt_count(len(fully_processed)),
        ),
        _build_kpi(
            "typical_wait_time",
            wait_value,
            valid_count=age_valid_count,
            total_count=age_total_count,
            minimum_completeness=_fmt_percentage(config.minimum_wait_completeness),
            warning_caption=wait_warning,
        ),
        _build_kpi(
            "typical_idle_time",
            idle_value,
            valid_count=idle_valid_count,
            total_count=idle_total_count,
            minimum_completeness=_fmt_percentage(config.minimum_idle_completeness),
            warning_caption=idle_warning,
        ),
        _build_kpi(
            "notable_observations",
            _fmt_count(len(exceptions)),
        ),
    ]

    chart_tables = {
        "in_the_works_by_step": _ranked_count(
            in_the_works, "step_name", label=COMMON.no_step
        ),
        "status_mix": _status_mix(df),
        "evaluation_type_summary": _evaluation_type_summary(
            df,
            in_the_works=in_the_works,
            backlog=backlog,
            fully_processed=fully_processed,
            minimum_wait_completeness=config.minimum_wait_completeness,
            minimum_completion_completeness=(
                config.minimum_completion_completeness
            ),
        ),
        "aging_by_step": _median_by(
            in_the_works,
            "step_name",
            "age_days",
            label=COMMON.no_step,
            minimum_completeness=config.minimum_wait_completeness,
            valid_count_col="age_valid_count",
            total_count_col="age_total_count",
        ),
        "workflow_aging_matrix": _workflow_aging_matrix(in_the_works),
        "age_idle_action_matrix": _age_idle_action_matrix(
            in_the_works,
            config=config,
            generated_at=generated_at,
            valid_idle_mask=valid_idle_mask,
        ),
        "owner_workload": _team_member_counts(in_the_works, config.team_members),
        "submitted_by_workload": submitted_by_workload,
        "submitted_by_date_activity": submitted_by_date_activity,
        "daily_closures": daily_closures,
        "closed_by_month": closed_by_month,
        "exception_counts": _exception_counts(exceptions),
    }

    snapshot_metrics = {
        "total_records": int(len(df)),
        "in_the_works_count": int(len(in_the_works)),
        "backlog_count": int(len(backlog)),
        "terminal_count": int(len(fully_processed)),
        "completed_today_count": reached_end_today,
        "fully_processed_count": int(len(fully_processed)),
        "reached_end_today_count": reached_end_today,
        "median_age_days": None if pd.isna(median_age) else float(median_age),
        "age_valid_count": age_valid_count,
        "age_total_count": age_total_count,
        "median_idle_days": (None if pd.isna(median_idle) else float(median_idle)),
        "idle_valid_count": idle_valid_count,
        "idle_total_count": idle_total_count,
        "oldest_age_days": None if pd.isna(oldest_age) else float(oldest_age),
        "exception_count": int(len(exceptions)),
    }

    return AnalyticsBundle(
        dashboard_title=config.dashboard_title,
        team_members=config.team_members,
        generated_at=generated_at,
        kpis=kpis,
        in_the_works=in_the_works,
        backlog=backlog,
        exceptions=exceptions,
        exception_counts=chart_tables["exception_counts"],
        chart_tables=chart_tables,
        snapshot_metrics=snapshot_metrics,
        presentation=PresentationContext(
            backlog_age_days=config.backlog_age_days,
            old_age_days=config.old_age_days,
            stale_idle_days=config.stale_idle_days,
        ),
    )
