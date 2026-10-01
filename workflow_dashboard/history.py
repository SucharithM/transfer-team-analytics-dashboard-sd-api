"""SQLite history storage for definition-aware trend reporting."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from . import __version__
from .analytics import AnalyticsBundle
from .config import DashboardConfig
from .time_utils import (
    DASHBOARD_TIMEZONE,
    dashboard_time_series,
    dashboard_timestamp,
)


HISTORY_SCHEMA_VERSION = 4
METRIC_DEFINITION_VERSION = 9

SNAPSHOT_COLUMNS = [
    "run_id",
    "generated_at",
    "snapshot_date",
    "source",
    "definition_hash",
    "metric_definition_version",
    "app_version",
    "pagination_validated",
    "total_records",
    "in_the_works_count",
    "backlog_count",
    "terminal_count",
    "completed_today_count",
    "fully_processed_count",
    "reached_end_today_count",
    "median_age_days",
    "age_valid_count",
    "age_total_count",
    "median_idle_days",
    "idle_valid_count",
    "idle_total_count",
    "oldest_age_days",
    "exception_count",
]

MONTHLY_COMPLETION_HISTORY_COLUMNS = [
    "run_id",
    "generated_at",
    "snapshot_date",
    "source",
    "definition_hash",
    "metric_definition_version",
    "app_version",
    "closed_month",
    "closed_count",
    "median_completion_days",
    "completion_valid_count",
    "completion_total_count",
]

OWNER_HISTORY_COLUMNS = [
    "run_id",
    "generated_at",
    "snapshot_date",
    "source",
    "definition_hash",
    "metric_definition_version",
    "app_version",
    "owner",
    "in_the_works_count",
]


class HistorySchemaError(RuntimeError):
    """Raised when a history database cannot be used without losing semantics."""


@dataclass(frozen=True)
class MetricDefinition:
    """Immutable, canonical description of one run's metric semantics."""

    metric_definition_version: int
    definition_json: str
    definition_hash: str

    @property
    def values(self) -> dict[str, Any]:
        """Return the human-readable definition values."""

        return json.loads(self.definition_json)


def _sorted_unique(values: Iterable[Any]) -> list[str]:
    return sorted({str(value) for value in values})


def _workflow_population(normalized_records: pd.DataFrame) -> tuple[list[str], bool]:
    if "workflow_name" not in normalized_records.columns:
        return [], bool(len(normalized_records))

    workflow_names: set[str] = set()
    includes_unnamed = False
    for value in normalized_records["workflow_name"]:
        if value is None or pd.isna(value):
            includes_unnamed = True
            continue
        name = str(value).strip()
        if name:
            workflow_names.add(name)
        else:
            includes_unnamed = True
    return sorted(workflow_names), includes_unnamed


def build_metric_definition(
    config: DashboardConfig,
    normalized_records: pd.DataFrame,
    *,
    source: str,
    metric_definition_version: int = METRIC_DEFINITION_VERSION,
) -> MetricDefinition:
    """Build a deterministic definition for the population and formulas in a run."""

    workflow_names, includes_unnamed = _workflow_population(normalized_records)
    if source == "api":
        source_identity = config.api_url
    elif source == "fixture":
        source_identity = str(config.fixture_path.expanduser().resolve())
    else:
        source_identity = source

    population: dict[str, Any] = {
        "source": source,
        "source_identity": source_identity,
        "workflow_filter": (
            (config.workflow_filter or "").strip().casefold() or None
        ),
        "workflow_names": workflow_names,
        "includes_unnamed_workflow": includes_unnamed,
    }
    if source == "api":
        population["status_filters"] = _sorted_unique(config.status_filters)

    definition = {
        "metric_definition_version": int(metric_definition_version),
        "population": population,
        "metrics": {
            "backlog_age_days": float(config.backlog_age_days),
            "terminal_steps": _sorted_unique(config.terminal_steps),
            "team_members": _sorted_unique(config.team_members),
            "submitter_grouping": "roster_plus_others_and_not_recorded",
            "stale_idle_days": int(config.stale_idle_days),
            "old_age_days": int(config.old_age_days),
            "minimum_wait_completeness": float(
                config.minimum_wait_completeness
            ),
            "minimum_idle_completeness": float(
                config.minimum_idle_completeness
            ),
            "minimum_completion_completeness": float(
                config.minimum_completion_completeness
            ),
            "dashboard_timezone": DASHBOARD_TIMEZONE,
        },
    }
    definition_json = json.dumps(
        definition,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    definition_hash = hashlib.sha256(definition_json.encode("utf-8")).hexdigest()
    return MetricDefinition(
        metric_definition_version=int(metric_definition_version),
        definition_json=definition_json,
        definition_hash=definition_hash,
    )


@dataclass(frozen=True)
class PreparedSnapshot:
    """One run's history rows, prepared without modifying SQLite."""

    run_id: str
    generated_at: pd.Timestamp
    snapshot_date: date
    source: str
    metric_definition: MetricDefinition
    app_version: str
    pagination_validated: bool
    metrics: dict[str, Any]
    owner_counts: tuple[tuple[str, int], ...]
    monthly_completion: tuple[
        tuple[str, int, float | None, int, int], ...
    ]

    def history_frames(
        self,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Return render-ready frames for the candidate snapshot."""

        definition_columns = {
            "definition_hash": self.metric_definition.definition_hash,
            "metric_definition_version": (
                self.metric_definition.metric_definition_version
            ),
            "app_version": self.app_version,
        }
        snapshot = pd.DataFrame(
            [
                {
                    "run_id": self.run_id,
                    "generated_at": self.generated_at,
                    "snapshot_date": self.snapshot_date,
                    "source": self.source,
                    **definition_columns,
                    "pagination_validated": self.pagination_validated,
                    **self.metrics,
                }
            ],
            columns=SNAPSHOT_COLUMNS,
        )
        owners = pd.DataFrame(
            [
                {
                    "run_id": self.run_id,
                    "generated_at": self.generated_at,
                    "snapshot_date": self.snapshot_date,
                    "source": self.source,
                    **definition_columns,
                    "owner": owner,
                    "in_the_works_count": count,
                }
                for owner, count in self.owner_counts
            ],
            columns=OWNER_HISTORY_COLUMNS,
        )
        monthly_completion = pd.DataFrame(
            [
                {
                    "run_id": self.run_id,
                    "generated_at": self.generated_at,
                    "snapshot_date": self.snapshot_date,
                    "source": self.source,
                    **definition_columns,
                    "closed_month": closed_month,
                    "closed_count": closed_count,
                    "median_completion_days": median_completion_days,
                    "completion_valid_count": completion_valid_count,
                    "completion_total_count": completion_total_count,
                }
                for (
                    closed_month,
                    closed_count,
                    median_completion_days,
                    completion_valid_count,
                    completion_total_count,
                ) in self.monthly_completion
            ],
            columns=MONTHLY_COMPLETION_HISTORY_COLUMNS,
        )
        return snapshot, owners, monthly_completion


def prepare_snapshot(
    analytics: AnalyticsBundle,
    metric_definition: MetricDefinition,
    *,
    source: str,
    pagination_validated: bool = False,
) -> PreparedSnapshot:
    """Build one snapshot in memory without changing the history database."""

    owner_counts = analytics.chart_tables["owner_workload"]
    monthly_completion = analytics.chart_tables["closed_by_month"]
    return PreparedSnapshot(
        run_id=str(uuid.uuid4()),
        generated_at=analytics.generated_at,
        snapshot_date=dashboard_timestamp(analytics.generated_at).date(),
        source=source,
        metric_definition=metric_definition,
        app_version=__version__,
        pagination_validated=pagination_validated,
        metrics=dict(analytics.snapshot_metrics),
        owner_counts=tuple(
            (str(row["owner"]), int(row["count"]))
            for _, row in owner_counts.iterrows()
        ),
        monthly_completion=tuple(
            (
                str(row["closed_month"]),
                int(row["closed_count"]),
                (
                    None
                    if pd.isna(row["median_completion_days"])
                    else float(row["median_completion_days"])
                ),
                int(row["completion_valid_count"]),
                int(row["completion_total_count"]),
            )
            for _, row in monthly_completion.iterrows()
        ),
    )


def _create_history_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE metric_definitions (
            definition_hash TEXT PRIMARY KEY,
            metric_definition_version INTEGER NOT NULL,
            definition_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE snapshot_metrics (
            run_id TEXT PRIMARY KEY,
            generated_at TEXT NOT NULL,
            snapshot_date TEXT NOT NULL,
            source TEXT NOT NULL,
            definition_hash TEXT NOT NULL,
            app_version TEXT NOT NULL,
            pagination_validated INTEGER NOT NULL DEFAULT 0,
            total_records INTEGER NOT NULL,
            in_the_works_count INTEGER NOT NULL,
            backlog_count INTEGER NOT NULL,
            terminal_count INTEGER NOT NULL,
            completed_today_count INTEGER NOT NULL,
            fully_processed_count INTEGER NOT NULL,
            reached_end_today_count INTEGER NOT NULL,
            median_age_days REAL,
            age_valid_count INTEGER NOT NULL,
            age_total_count INTEGER NOT NULL,
            median_idle_days REAL,
            idle_valid_count INTEGER NOT NULL,
            idle_total_count INTEGER NOT NULL,
            oldest_age_days REAL,
            exception_count INTEGER NOT NULL,
            FOREIGN KEY (definition_hash)
                REFERENCES metric_definitions(definition_hash)
        );

        CREATE INDEX snapshot_series_idx
        ON snapshot_metrics (
            source, definition_hash, generated_at
        );

        CREATE TABLE owner_workload_history (
            run_id TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            snapshot_date TEXT NOT NULL,
            source TEXT NOT NULL,
            owner TEXT NOT NULL,
            in_the_works_count INTEGER NOT NULL,
            PRIMARY KEY (run_id, owner),
            FOREIGN KEY (run_id) REFERENCES snapshot_metrics(run_id)
                ON DELETE CASCADE
        );

        CREATE TABLE monthly_completion_history (
            run_id TEXT NOT NULL,
            closed_month TEXT NOT NULL,
            closed_count INTEGER NOT NULL,
            median_completion_days REAL,
            completion_valid_count INTEGER NOT NULL,
            completion_total_count INTEGER NOT NULL,
            PRIMARY KEY (run_id, closed_month),
            FOREIGN KEY (run_id) REFERENCES snapshot_metrics(run_id)
                ON DELETE CASCADE
        );

        """
    )
    connection.execute(f"PRAGMA user_version = {HISTORY_SCHEMA_VERSION}")


def connect_history(db_path: Path) -> sqlite3.Connection:
    """Open a compatible history database or initialize a new strict schema."""

    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    schema_version = connection.execute("PRAGMA user_version").fetchone()[0]

    if not tables:
        with connection:
            _create_history_schema(connection)
        return connection

    if schema_version == 0:
        connection.close()
        raise HistorySchemaError(
            f"History database {db_path} uses an unsupported unversioned "
            "schema. Archive or remove it before running this version."
        )
    if schema_version != HISTORY_SCHEMA_VERSION:
        connection.close()
        raise HistorySchemaError(
            f"History database {db_path} has schema version {schema_version}; "
            f"this application requires version {HISTORY_SCHEMA_VERSION}. "
            "Archive or remove the database before running this version."
        )
    required_tables = {
        "metric_definitions",
        "snapshot_metrics",
        "owner_workload_history",
        "monthly_completion_history",
    }
    if not required_tables.issubset(tables):
        connection.close()
        raise HistorySchemaError(
            f"History database {db_path} declares schema version "
            f"{schema_version} but is missing required tables."
        )
    return connection


def store_snapshot(
    db_path: Path,
    analytics: AnalyticsBundle,
    metric_definition: MetricDefinition,
    *,
    source: str,
    pagination_validated: bool = False,
) -> str:
    """Persist one run-level snapshot and owner workload rows."""

    prepared = prepare_snapshot(
        analytics,
        metric_definition,
        source=source,
        pagination_validated=pagination_validated,
    )
    store_prepared_snapshot(db_path, prepared)
    return prepared.run_id


def _store_metric_definition(
    connection: sqlite3.Connection, prepared: PreparedSnapshot
) -> None:
    definition = prepared.metric_definition
    connection.execute(
        """
        INSERT INTO metric_definitions (
            definition_hash, metric_definition_version,
            definition_json, created_at
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(definition_hash) DO NOTHING
        """,
        (
            definition.definition_hash,
            definition.metric_definition_version,
            definition.definition_json,
            prepared.generated_at.isoformat(),
        ),
    )
    stored = connection.execute(
        """
        SELECT metric_definition_version, definition_json
        FROM metric_definitions
        WHERE definition_hash = ?
        """,
        (definition.definition_hash,),
    ).fetchone()
    expected = (
        definition.metric_definition_version,
        definition.definition_json,
    )
    if stored != expected:
        raise HistorySchemaError(
            "Stored metric definition does not match its definition hash."
        )


def store_prepared_snapshot(
    db_path: Path, prepared: PreparedSnapshot
) -> None:
    """Atomically persist the definition, snapshot, and owner rows."""

    # SQLite's transaction context does not close the connection.
    with closing(connect_history(db_path)) as connection, connection:
        _store_metric_definition(connection, prepared)
        connection.execute(
            """
            INSERT INTO snapshot_metrics (
                run_id, generated_at, snapshot_date, source, definition_hash,
                app_version, pagination_validated,
                total_records, in_the_works_count, backlog_count,
                terminal_count, completed_today_count,
                fully_processed_count, reached_end_today_count,
                median_age_days, age_valid_count, age_total_count,
                median_idle_days, idle_valid_count, idle_total_count,
                oldest_age_days, exception_count
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?
            )
            """,
            (
                prepared.run_id,
                prepared.generated_at.isoformat(),
                prepared.snapshot_date.isoformat(),
                prepared.source,
                prepared.metric_definition.definition_hash,
                prepared.app_version,
                int(prepared.pagination_validated),
                prepared.metrics["total_records"],
                prepared.metrics["in_the_works_count"],
                prepared.metrics["backlog_count"],
                prepared.metrics["terminal_count"],
                prepared.metrics["completed_today_count"],
                prepared.metrics["fully_processed_count"],
                prepared.metrics["reached_end_today_count"],
                prepared.metrics["median_age_days"],
                prepared.metrics["age_valid_count"],
                prepared.metrics["age_total_count"],
                prepared.metrics["median_idle_days"],
                prepared.metrics["idle_valid_count"],
                prepared.metrics["idle_total_count"],
                prepared.metrics["oldest_age_days"],
                prepared.metrics["exception_count"],
            ),
        )

        connection.executemany(
            """
            INSERT INTO owner_workload_history (
                run_id, generated_at, snapshot_date, source, owner,
                in_the_works_count
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    prepared.run_id,
                    prepared.generated_at.isoformat(),
                    prepared.snapshot_date.isoformat(),
                    prepared.source,
                    owner,
                    count,
                )
                for owner, count in prepared.owner_counts
            ],
        )
        connection.executemany(
            """
            INSERT INTO monthly_completion_history (
                run_id, closed_month, closed_count, median_completion_days,
                completion_valid_count, completion_total_count
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    prepared.run_id,
                    closed_month,
                    closed_count,
                    median_completion_days,
                    completion_valid_count,
                    completion_total_count,
                )
                for (
                    closed_month,
                    closed_count,
                    median_completion_days,
                    completion_valid_count,
                    completion_total_count,
                ) in prepared.monthly_completion
            ],
        )


def load_history(
    db_path: Path,
    *,
    source: str,
    definition_hash: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load trend tables scoped to one exact metric definition."""

    if not db_path.exists():
        return (
            pd.DataFrame(columns=SNAPSHOT_COLUMNS),
            pd.DataFrame(columns=OWNER_HISTORY_COLUMNS),
            pd.DataFrame(columns=MONTHLY_COMPLETION_HISTORY_COLUMNS),
        )

    with closing(connect_history(db_path)) as connection, connection:
        snapshots = pd.read_sql_query(
            """
            SELECT
                snapshots.run_id,
                snapshots.generated_at,
                snapshots.snapshot_date,
                snapshots.source,
                snapshots.definition_hash,
                definitions.metric_definition_version,
                snapshots.app_version,
                snapshots.pagination_validated,
                snapshots.total_records,
                snapshots.in_the_works_count,
                snapshots.backlog_count,
                snapshots.terminal_count,
                snapshots.completed_today_count,
                snapshots.fully_processed_count,
                snapshots.reached_end_today_count,
                snapshots.median_age_days,
                snapshots.age_valid_count,
                snapshots.age_total_count,
                snapshots.median_idle_days,
                snapshots.idle_valid_count,
                snapshots.idle_total_count,
                snapshots.oldest_age_days,
                snapshots.exception_count
            FROM snapshot_metrics AS snapshots
            INNER JOIN metric_definitions AS definitions
                ON definitions.definition_hash = snapshots.definition_hash
            WHERE snapshots.source = ?
                AND snapshots.definition_hash = ?
                AND (
                    snapshots.source <> 'api'
                    OR snapshots.pagination_validated = 1
                )
            ORDER BY snapshots.generated_at
            """,
            connection,
            params=(source, definition_hash),
        )
        monthly_completion = pd.read_sql_query(
            """
            SELECT
                monthly.run_id,
                snapshots.generated_at,
                snapshots.snapshot_date,
                snapshots.source,
                snapshots.definition_hash,
                definitions.metric_definition_version,
                snapshots.app_version,
                monthly.closed_month,
                monthly.closed_count,
                monthly.median_completion_days,
                monthly.completion_valid_count,
                monthly.completion_total_count
            FROM monthly_completion_history AS monthly
            INNER JOIN snapshot_metrics AS snapshots
                ON snapshots.run_id = monthly.run_id
            INNER JOIN metric_definitions AS definitions
                ON definitions.definition_hash = snapshots.definition_hash
            WHERE snapshots.source = ?
                AND snapshots.definition_hash = ?
                AND (
                    snapshots.source <> 'api'
                    OR snapshots.pagination_validated = 1
                )
            ORDER BY snapshots.generated_at, monthly.closed_month
            """,
            connection,
            params=(source, definition_hash),
        )
        owners = pd.read_sql_query(
            """
            SELECT
                owner_history.run_id,
                owner_history.generated_at,
                owner_history.snapshot_date,
                owner_history.source,
                snapshots.definition_hash,
                definitions.metric_definition_version,
                snapshots.app_version,
                owner_history.owner,
                owner_history.in_the_works_count
            FROM owner_workload_history AS owner_history
            INNER JOIN snapshot_metrics AS snapshots
                ON snapshots.run_id = owner_history.run_id
            INNER JOIN metric_definitions AS definitions
                ON definitions.definition_hash = snapshots.definition_hash
            WHERE snapshots.source = ?
                AND snapshots.definition_hash = ?
                AND (
                    snapshots.source <> 'api'
                    OR snapshots.pagination_validated = 1
                )
            ORDER BY owner_history.generated_at, owner_history.owner
            """,
            connection,
            params=(source, definition_hash),
        )

    if not snapshots.empty:
        snapshots["generated_at"] = pd.to_datetime(
            snapshots["generated_at"], errors="coerce", utc=True
        )
        snapshots["snapshot_date"] = dashboard_time_series(
            snapshots["generated_at"]
        ).dt.date
    if not owners.empty:
        owners["generated_at"] = pd.to_datetime(
            owners["generated_at"], errors="coerce", utc=True
        )
        owners["snapshot_date"] = dashboard_time_series(
            owners["generated_at"]
        ).dt.date
    if not monthly_completion.empty:
        monthly_completion["generated_at"] = pd.to_datetime(
            monthly_completion["generated_at"], errors="coerce", utc=True
        )
        monthly_completion["snapshot_date"] = dashboard_time_series(
            monthly_completion["generated_at"]
        ).dt.date
    return snapshots, owners, monthly_completion
