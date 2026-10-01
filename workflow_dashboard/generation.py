"""Shared, credential-free dashboard generation and atomic publication."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Iterable

import pandas as pd

from .analytics import build_analytics
from .config import DashboardConfig
from .dashboard_html import render_dashboard
from .excel_export import export_workbook
from .history import (
    build_metric_definition,
    load_history,
    prepare_snapshot,
    store_prepared_snapshot,
)
from .normalization import (
    normalize_records,
    select_workflow_population,
)
from .time_utils import dashboard_timestamp


def _csv_ready(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for column in ("submitted_at", "last_activity_at"):
        if column in out.columns:
            out[column] = out[column].dt.strftime("%Y-%m-%dT%H:%M:%SZ").fillna("")
    for column in out.columns:
        out[column] = out[column].map(_csv_safe_value)
    return out


def _csv_safe_value(value):
    """Keep source text from being evaluated when a CSV is opened in a spreadsheet."""
    if isinstance(value, str):
        normalized = value.lstrip(" \t\r\n\ufeff")
        if normalized.startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
            return "'" + value
    return value


def _run_output_paths(
    output_dir: Path, generated_at: pd.Timestamp, dashboard_title: str
) -> tuple[Path, Path, Path]:
    """Build collision-resistant, dated output paths for one run."""

    local = dashboard_timestamp(generated_at)
    run_dir = output_dir / local.strftime("%Y-%m-%d_%A")
    timestamp = local.strftime("%Y-%m-%d_%H-%M-%S-%f_%Z")
    dashboard_slug = re.sub(
        r"[^a-z0-9]+", "_", dashboard_title.casefold()
    ).strip("_") or "workflow_dashboard"
    return (
        run_dir / f"normalized_records_{timestamp}.csv",
        run_dir / f"{dashboard_slug}_{timestamp}.html",
        run_dir / f"{dashboard_slug}_{timestamp}.xlsx",
    )


def _cleanup_run_files(paths: Iterable[Path]) -> list[OSError]:
    """Best-effort cleanup for files created by the current run only."""

    errors: list[OSError] = []
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            errors.append(exc)
    return errors


def _publish_artifacts(
    staged_artifacts: list[tuple[Path, Path]],
) -> tuple[Path, ...]:
    """Atomically move a complete staged artifact set to final file paths."""

    existing = [final for _, final in staged_artifacts if final.exists()]
    if existing:
        raise FileExistsError(f"Refusing to overwrite output artifact: {existing[0]}")

    published: list[Path] = []
    try:
        for staged, final in staged_artifacts:
            os.replace(staged, final)
            published.append(final)
    except Exception as exc:
        for cleanup_error in _cleanup_run_files(reversed(published)):
            exc.add_note(
                f"Could not remove partially published artifact: {cleanup_error}"
            )
        raise
    return tuple(published)


def _validate_staged_artifacts(paths: Iterable[Path]) -> None:
    """Reject a writer that returns without producing a usable artifact."""

    for path in paths:
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(
                f"Artifact writer did not produce a non-empty file: {path}"
            )


def generate_dashboard(config: DashboardConfig, records, fetch_meta, *, source="api", generated_at=None):
    """Generate files only from an already-completed fetch, with no authentication."""
    if config.api_token is not None or any(k.casefold() in ("authorization", "cookie") for k in config.headers):
        raise ValueError("Dashboard generation requires credential-free configuration")
    generated_at = generated_at if generated_at is not None else pd.Timestamp.now(tz="UTC")
    normalized_records = normalize_records(records, config, generated_at=generated_at)
    df = select_workflow_population(normalized_records, config)

    metric_definition = build_metric_definition(
        config,
        df,
        source=source,
    )
    analytics = build_analytics(
        df, config=config, generated_at=generated_at
    )
    prepared_snapshot = prepare_snapshot(
        analytics,
        metric_definition,
        source=source,
        pagination_validated=bool(fetch_meta["pagination_validated"]),
    )

    csv_path, html_path, xlsx_path = _run_output_paths(
        config.output_dir, generated_at, config.dashboard_title
    )
    output_parent = html_path.parent
    output_parent.mkdir(parents=True, exist_ok=True)

    history, owner_history, monthly_completion_history = load_history(
        config.history_db_path,
        source=source,
        definition_hash=metric_definition.definition_hash,
    )
    (
        current_history,
        current_owner_history,
        current_monthly_completion_history,
    ) = prepared_snapshot.history_frames()
    if source != "api" or prepared_snapshot.pagination_validated:
        history = pd.concat([history, current_history], ignore_index=True)
        owner_history = pd.concat(
            [owner_history, current_owner_history], ignore_index=True
        )
        monthly_completion_history = pd.concat(
            [
                monthly_completion_history,
                current_monthly_completion_history,
            ],
            ignore_index=True,
        )

    published: tuple[Path, ...] = ()
    try:
        with tempfile.TemporaryDirectory(
            prefix=".workflow-run-", dir=output_parent
        ) as staging_dir:
            staging_root = Path(staging_dir)
            staged_csv = staging_root / csv_path.name
            staged_html = staging_root / html_path.name
            staged_xlsx = staging_root / xlsx_path.name

            _csv_ready(df).to_csv(staged_csv, index=False)
            render_dashboard(
                df=df,
                analytics=analytics,
                history=history,
                owner_history=owner_history,
                output_path=staged_html,
            )
            export_workbook(
                df=df,
                analytics=analytics,
                history=history,
                owner_history=owner_history,
                monthly_completion_history=monthly_completion_history,
                output_path=staged_xlsx,
            )
            _validate_staged_artifacts((staged_csv, staged_html, staged_xlsx))
            published = _publish_artifacts(
                [
                    (staged_csv, csv_path),
                    (staged_html, html_path),
                    (staged_xlsx, xlsx_path),
                ]
            )

        store_prepared_snapshot(config.history_db_path, prepared_snapshot)
    except Exception as exc:
        for cleanup_error in _cleanup_run_files(reversed(published)):
            exc.add_note(f"Could not remove published artifact: {cleanup_error}")
        raise

    result = {
        "run_id": prepared_snapshot.run_id,
        "definition_hash": metric_definition.definition_hash,
        "metric_definition_version": (
            metric_definition.metric_definition_version
        ),
        "app_version": prepared_snapshot.app_version,
        "source": source,
        "fetch": fetch_meta,
        "records": len(df),
        "outputs": {
            "html": str(html_path),
            "excel": str(xlsx_path),
            "csv": str(csv_path),
            "history_db": str(config.history_db_path),
        },
    }
    return result
