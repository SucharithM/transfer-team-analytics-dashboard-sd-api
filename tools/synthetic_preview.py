"""Generate isolated, fictional dashboards for developer UI testing."""
from __future__ import annotations

import argparse
import json
import math
import random
import tempfile
from pathlib import Path

import pandas as pd

from workflow_dashboard.analytics import build_analytics
from workflow_dashboard.api_client import records_from_source
from workflow_dashboard.config import DashboardConfig, DEFAULT_TEAM_MEMBERS
from workflow_dashboard.dashboard_content import WORKFLOW_STEP_ORDER
from workflow_dashboard.generation import generate_dashboard
from workflow_dashboard.history import build_metric_definition, store_snapshot
from workflow_dashboard.normalization import normalize_records
from workflow_dashboard.time_utils import dashboard_timestamp


def _activity_interval(seed, record_id):
    rng = random.Random(f"{seed}:{record_id}:activity")
    return rng.lognormvariate(math.log(12 if rng.random() < 0.25 else 2), 0.8)


def generate_records(count, seed, as_of, scenario="mixed"):
    """Return seeded cases with weekday intake, varied processing, and activity cadences."""
    if count < 0 or scenario not in ("mixed", "edge", "empty"):
        raise ValueError("Invalid record count or scenario")
    if scenario == "empty":
        return []
    rng = random.Random(seed)
    rows = []
    local = dashboard_timestamp(as_of)
    dates = list(pd.date_range(f"{local.year - 2}-01-01", local.date(), freq="D").date)[::-1]
    weights = [
        (0.7 + 0.3 * math.sin(day / 16) + math.exp(-((day - 24) / 20) ** 2))
        * (0.12 if date.weekday() >= 5 else 1)
        * (1 if day < 210 else 0.08)
        for day, date in enumerate(dates)
    ]
    for i in range(count):
        date = rng.choices(dates, weights=weights)[0]
        midnight = pd.Timestamp(date).tz_localize("America/New_York")
        submitted = midnight + pd.Timedelta(hours=rng.uniform(8, 17))
        if submitted > local:
            submitted = midnight + (local - midnight) * rng.random()
        submitted = submitted.tz_convert("UTC")
        age = (as_of - submitted).total_seconds() / 86400
        duration = rng.lognormvariate(math.log(10), 0.85)
        if rng.random() < 0.08:
            duration += rng.uniform(45, 150)
        # A recent intake surge and slower processing create a connected backlog trend.
        duration *= 1 + math.exp(-((age - 18) / 18) ** 2)
        closure = dashboard_timestamp(submitted + pd.Timedelta(days=duration))
        closure_date = closure.date()
        if closure_date.weekday() >= 5:
            closure_date += pd.Timedelta(days=7 - closure_date.weekday())
        closure = pd.Timestamp(closure_date).tz_localize("America/New_York") + pd.Timedelta(hours=rng.uniform(8, 17))
        closure = max(closure.tz_convert("UTC"), submitted + pd.Timedelta(minutes=30))
        completed = closure <= as_of
        record_id = f"synthetic-package-{i:07}"
        interval = _activity_interval(seed, record_id)
        activity = closure if completed else submitted + pd.Timedelta(days=interval * math.floor(age / interval))
        step = rng.choice(WORKFLOW_STEP_ORDER)
        owner = rng.choices((*DEFAULT_TEAM_MEMBERS, "Synthetic External Staff", None), weights=(40, 20, 15, 10, 8, 5, 2))[0]
        row = dict(packageID=record_id,
                   packageName=f"{rng.choice(('No-Rule', 'International', 'Transfer Credit'))} Transcript Evaluation | Synthetic Student {i:07} | Fictional Institution {i % 9}",
                   workflowName="Synthetic Transcript Evaluation", stepName="End" if completed else step,
                   status="Completed" if completed else rng.choice(("NeedsReview", "InProgress")),
                   submittedBy=owner, submissionDate=submitted.isoformat(), lastActivityDate=activity.isoformat(),
                   taskID=None if completed else f"synthetic-task-{i:07}", lockedByName=None,
                   lockedByCurrentUser=False, submitterCount=1)
        if scenario == "edge":
            row['packageName'] = f"Synthetic Évaluation & <Example> {'Long label ' * 14} | Synthetic Student {i} | Fictional University"
            if not completed:
                row['stepName'] = step if i % 3 else f"Synthetic Additional Queue {i % 18} — {'Long description ' * 5}"
                row['status'] = f"Synthetic Status {i % 12}"
            fault = i % 10
            if fault == 0:
                row['submissionDate'] = None
            elif fault == 1:
                row['lastActivityDate'] = None
            elif fault == 2:
                row['submissionDate'] = (as_of + pd.Timedelta(days=2)).isoformat()
            elif fault == 3:
                row['lastActivityDate'] = (as_of + pd.Timedelta(days=1)).isoformat()
            elif fault == 4:
                row['lastActivityDate'] = (submitted - pd.Timedelta(days=1)).isoformat()
            elif fault == 5:
                row['stepName'] = None
                row['status'] = None
                row['submittedBy'] = None
            elif fault == 6:
                row['submissionDate'] = (as_of - pd.Timedelta(days=1500)).isoformat()
        rows.append(row)
    return rows


def historical_population(normalized, at, *, report_at, seed):
    """Reconstruct cohort membership and periodic activity without shifting case dates."""
    submitted = normalized["submitted_at"]
    activity = normalized["last_activity_at"]
    valid = submitted.notna() & activity.notna() & submitted.le(activity) & activity.le(report_at)
    frame = normalized.loc[~valid | submitted.le(at)].copy()
    valid = valid.loc[frame.index]
    closed = frame["is_terminal"] & frame["last_activity_at"].le(at)
    reopening = valid & frame["is_terminal"] & ~closed
    # shortcut: interim workflow steps are approximate; use event logs for transition testing.
    frame.loc[reopening, "step_name"] = WORKFLOW_STEP_ORDER[-1]
    frame.loc[reopening, "status"] = "InProgress"
    frame.loc[reopening, "is_terminal"] = False
    active = valid & ~closed
    intervals = frame.loc[active, "record_id"].map(lambda identity: _activity_interval(seed, identity))
    elapsed = (at - frame.loc[active, "submitted_at"]).dt.total_seconds() / 86400
    updates = frame.loc[active, "submitted_at"] + pd.to_timedelta(
        (elapsed // intervals) * intervals, unit="D"
    )
    last_activity = frame.loc[active, "last_activity_at"]
    updates = updates.where(updates.le(last_activity), last_activity)
    frame["last_activity_at"] = frame["last_activity_at"].where(~active, updates)
    # Preserve deliberately broken timing in the edge preset at each report time.
    for column in ("submitted_at", "last_activity_at"):
        frame.loc[~valid, column] += at - report_at
    frame["age_days"] = (at - frame["submitted_at"]).dt.total_seconds() / 86400
    frame["idle_days"] = (at - frame["last_activity_at"]).dt.total_seconds() / 86400
    return frame


def preview(*, records=5000, scenario="mixed", seed=42, as_of=None, output_dir=Path("outputs/synthetic-preview")):
    as_of = _timestamp(as_of) if as_of is not None else pd.Timestamp.now(tz="UTC").floor("min")
    rows = generate_records(records, seed, as_of, scenario)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=f"{scenario}-", dir=output_dir))
    fixture = root / "synthetic_response.json"
    fixture.write_text(json.dumps({"Item1": len(rows), "Item2": rows}, ensure_ascii=False), encoding="utf-8")
    config = DashboardConfig(dashboard_title="SYNTHETIC — Developer UI Preview", output_dir=root,
                             fixture_path=fixture, history_db_path=root / "history.sqlite")
    rows, meta, _ = records_from_source("fixture", config)
    if rows:
        normalized = normalize_records(rows, config, generated_at=as_of)
        definition = build_metric_definition(config, normalized, source="fixture")
        local_date = dashboard_timestamp(as_of).date()
        recent_dates = pd.date_range(
            local_date - pd.Timedelta(days=29), periods=29, freq="D"
        )
        older_dates = pd.date_range(
            f"{local_date.year - 2}-01-01", recent_dates[0] - pd.Timedelta(days=1), freq="MS"
        )
        for date in older_dates.union(recent_dates).date:
            historical_at = pd.Timestamp(f"{date}T12:00:00", tz="America/New_York")
            historical_at = historical_at.tz_convert("UTC")
            frame = historical_population(normalized, historical_at, report_at=as_of, seed=seed)
            analytics = build_analytics(frame, config=config, generated_at=historical_at)
            store_snapshot(config.history_db_path, analytics, definition, source="fixture")
    result = generate_dashboard(config, rows, meta, source="fixture", generated_at=as_of)
    result.update(scenario=scenario, seed=seed, as_of=as_of.isoformat(), fixture=str(fixture))
    return result


def _timestamp(value):
    try:
        stamp = pd.Timestamp(value)
        if pd.isna(stamp) or stamp.tzinfo is None:
            raise ValueError("Timestamp requires a timezone")
        return stamp.tz_convert("UTC")
    except (ValueError, TypeError, OverflowError) as exc:
        raise argparse.ArgumentTypeError("--as-of requires a timezone-aware ISO timestamp") from exc


def _count(value):
    value = int(value)
    if value < 0:
        raise argparse.ArgumentTypeError("--records must be nonnegative")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=_count, default=5000)
    parser.add_argument("--scenario", choices=("mixed", "edge", "empty"), default="mixed")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--as-of", type=_timestamp)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/synthetic-preview"))
    args = parser.parse_args(argv)
    print(json.dumps(preview(**vars(args)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
