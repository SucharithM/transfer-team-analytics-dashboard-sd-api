"""Normalize raw API records into a canonical workflow-monitoring schema."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import pandas as pd

from .config import DashboardConfig
from .time_utils import parse_source_time_series


CANONICAL_COLUMNS = [
    "record_id",
    "item_label",
    "workflow_name",
    "step_name",
    "status",
    "owner",
    "submitted_at",
    "last_activity_at",
    "task_id",
    "locked_by",
    "is_terminal",
    "age_days",
    "idle_days",
    "source_payload",
]

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "record_id": ("record_id", "packageID", "packageId", "package_id", "id", "caseId", "caseID", "requestId"),
    "item_label": ("item_label", "packageName", "package_name", "itemName", "item_name", "title", "name", "description"),
    "workflow_name": ("workflow_name", "workflowName", "processName", "process_name", "workflow"),
    "step_name": ("step_name", "stepName", "currentStep", "current_step", "stage", "queue"),
    "status": ("status", "state", "statusName", "status_name"),
    "owner": ("submittedBy", "submitted_by", "submitter", "createdBy", "created_by"),
    "submitted_at": ("submitted_at", "submissionDate", "submission_date", "submittedDate", "submitted_date", "createdAt", "created_at"),
    "last_activity_at": ("last_activity_at", "lastActivityDate", "last_activity_date", "updatedAt", "updated_at", "modifiedAt", "modified_at"),
    "task_id": ("task_id", "taskID", "taskId"),
    "locked_by": ("locked_by", "lockedByName", "lockedBy", "locked_by_name"),
}


def _first_present(record: dict[str, Any], aliases: Iterable[str], lowered: dict[str, str]) -> Any:
    for alias in aliases:
        if alias in record:
            return record[alias]
        actual = lowered.get(alias.lower())
        if actual is not None:
            return record[actual]
    return None


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in {"", "none", "null", "nan"}:
        return None
    return text


class WorkflowPopulationError(RuntimeError):
    """Raised when a run cannot identify one unambiguous workflow population."""

    def __init__(self, message: str, *, workflows: tuple[str, ...] = ()):
        super().__init__(message)
        self.workflows = workflows


def _workflow_population(df: pd.DataFrame) -> tuple[dict[str, str], bool]:
    """Return case-folded workflow identities and whether unnamed rows exist."""

    workflow_names: dict[str, str] = {}
    includes_unnamed = False
    if "workflow_name" not in df.columns:
        return workflow_names, bool(len(df))

    for value in df["workflow_name"]:
        if value is None or pd.isna(value):
            includes_unnamed = True
            continue
        name = str(value).strip()
        if not name:
            includes_unnamed = True
            continue
        identity = name.casefold()
        current = workflow_names.get(identity)
        if current is None or name < current:
            workflow_names[identity] = name
    return workflow_names, includes_unnamed


def _population_description(
    workflow_names: dict[str, str], includes_unnamed: bool
) -> str:
    discovered = sorted(workflow_names.values(), key=str.casefold)
    if includes_unnamed:
        discovered.append("<unnamed>")
    return ", ".join(discovered) if discovered else "none"


def select_workflow_population(
    df: pd.DataFrame, config: DashboardConfig
) -> pd.DataFrame:
    """Select one workflow or reject an ambiguous analytics population."""

    workflow_names, includes_unnamed = _workflow_population(df)
    configured_filter = (config.workflow_filter or "").strip()

    if configured_filter:
        target = configured_filter.casefold()
        if "workflow_name" not in df.columns:
            matching = pd.Series(False, index=df.index, dtype=bool)
        else:
            matching = df["workflow_name"].map(
                lambda value: (
                    False
                    if value is None or pd.isna(value)
                    else str(value).strip().casefold() == target
                )
            )
        selected = df.loc[matching].copy().reset_index(drop=True)
        if selected.empty:
            discovered = _population_description(
                workflow_names, includes_unnamed
            )
            raise WorkflowPopulationError(
                f"WORKFLOW_FILTER {configured_filter!r} matched no records; "
                f"discovered workflows: {discovered}",
                workflows=tuple(sorted(workflow_names.values(), key=str.casefold)),
            )
        return selected

    if df.empty:
        return df.copy().reset_index(drop=True)

    discovered = _population_description(workflow_names, includes_unnamed)
    if len(workflow_names) != 1 or includes_unnamed:
        raise WorkflowPopulationError(
            "WORKFLOW_FILTER is required unless every record has the same "
            f"named workflow; discovered workflows: {discovered}",
            workflows=tuple(sorted(workflow_names.values(), key=str.casefold)),
        )
    return df.copy().reset_index(drop=True)


def normalize_records(
    records: list[dict[str, Any]],
    config: DashboardConfig,
    *,
    generated_at: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Convert arbitrary API records to the canonical dashboard schema."""

    generated_at = generated_at or pd.Timestamp.now(tz="UTC")
    normalized: list[dict[str, Any]] = []

    for index, record in enumerate(records, start=1):
        row: dict[str, Any] = {}
        lowered = {key.lower(): key for key in record}
        for field, aliases in FIELD_ALIASES.items():
            row[field] = _clean_text(_first_present(record, aliases, lowered))
        if row["record_id"] is None:
            row["record_id"] = f"row-{index}"
        row["is_terminal"] = (row["step_name"] or "").lower() in config.terminal_steps
        row["source_payload"] = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
        normalized.append(row)

    df = pd.DataFrame(normalized, columns=[column for column in CANONICAL_COLUMNS if column not in {"age_days", "idle_days"}])
    if df.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    df["submitted_at"] = parse_source_time_series(df["submitted_at"])
    df["last_activity_at"] = parse_source_time_series(df["last_activity_at"])
    df["age_days"] = (generated_at - df["submitted_at"]).dt.total_seconds() / 86400
    df["idle_days"] = (generated_at - df["last_activity_at"]).dt.total_seconds() / 86400
    df.loc[df["submitted_at"].isna(), "age_days"] = pd.NA
    df.loc[df["last_activity_at"].isna(), "idle_days"] = pd.NA
    return df[CANONICAL_COLUMNS]
