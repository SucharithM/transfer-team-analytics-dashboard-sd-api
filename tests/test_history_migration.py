import sqlite3
from dataclasses import replace

import pandas as pd
import pytest

from workflow_dashboard import __version__
from workflow_dashboard import history as history_module
from workflow_dashboard.analytics import build_analytics
from workflow_dashboard.config import DashboardConfig
from workflow_dashboard.history import (
    HISTORY_SCHEMA_VERSION,
    METRIC_DEFINITION_VERSION,
    HistorySchemaError,
    build_metric_definition,
    connect_history,
    load_history,
    store_snapshot,
)

from .test_analytics_cohorts import GENERATED_AT, sample_cases


@pytest.mark.parametrize("operation", ["store", "load", "store_failure", "load_failure"])
def test_history_connections_close_on_success_and_failure(monkeypatch, tmp_path, operation):
    db_path = tmp_path / "history.sqlite"
    analytics = _analytics()
    definition = _definition()
    store_snapshot(db_path, analytics, definition, source="fixture")
    connections = []
    original_connect = history_module.connect_history

    def track_connection(path):
        connection = original_connect(path)
        connections.append(connection)
        return connection

    monkeypatch.setattr(history_module, "connect_history", track_connection)

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic failure")

    if operation == "store_failure":
        monkeypatch.setattr(history_module, "_store_metric_definition", fail)
    elif operation == "load_failure":
        monkeypatch.setattr(history_module.pd, "read_sql_query", fail)

    def perform():
        if operation.startswith("store"):
            store_snapshot(db_path, analytics, definition, source="fixture")
        else:
            load_history(db_path, source="fixture", definition_hash=definition.definition_hash)

    if operation.endswith("failure"):
        with pytest.raises(sqlite3.OperationalError):
            perform()
    else:
        perform()
    assert len(connections) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].execute("SELECT 1")


def _records_with_workflows(*workflow_names: str | None) -> pd.DataFrame:
    return pd.DataFrame({"workflow_name": workflow_names})


def _analytics(config: DashboardConfig | None = None):
    config = config or DashboardConfig()
    return build_analytics(
        sample_cases(),
        config=config,
        generated_at=GENERATED_AT,
    )


def _definition(
    config: DashboardConfig | None = None,
    *,
    source: str = "fixture",
    records: pd.DataFrame | None = None,
):
    config = config or DashboardConfig()
    return build_metric_definition(
        config,
        records if records is not None else _records_with_workflows("Workflow A"),
        source=source,
    )


def _create_legacy_history(db_path) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE snapshot_metrics (
                run_id TEXT PRIMARY KEY,
                generated_at TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,
                source TEXT NOT NULL,
                process_name TEXT NOT NULL
            )
            """
        )


def test_definition_hash_is_canonical_and_ignores_unrelated_config(tmp_path) -> None:
    config = DashboardConfig(
        api_url="https://example.test/workflows",
        api_token="secret-one",
        status_filters=("NeedsReview", "Completed"),
        team_members=("Person B", "Person A"),
        terminal_steps=("end", "cancelled"),
        fixture_path=tmp_path / "first.json",
        workflow_filter=" Workflow A ",
    )
    reordered = replace(
        config,
        api_token="secret-two",
        api_take=500,
        status_filters=tuple(reversed(config.status_filters)),
        team_members=tuple(reversed(config.team_members)),
        terminal_steps=tuple(reversed(config.terminal_steps)),
        workflow_filter="workflow a",
        dashboard_title="Different title",
        output_dir=tmp_path / "other-output",
        fixture_path=tmp_path / "unused-for-api.json",
        request_timeout_seconds=99,
        terminal_statuses=("unused",),
    )
    records = _records_with_workflows("Workflow B", None, "Workflow A")
    reordered_records = records.iloc[::-1].reset_index(drop=True)

    first = _definition(config, source="api", records=records)
    second = _definition(reordered, source="api", records=reordered_records)

    assert first.definition_hash == second.definition_hash
    assert first.definition_json == second.definition_json
    assert first.values["population"]["workflow_names"] == [
        "Workflow A",
        "Workflow B",
    ]
    assert first.values["population"]["includes_unnamed_workflow"] is True
    assert first.values["population"]["workflow_filter"] == "workflow a"
    assert "secret-one" not in first.definition_json
    assert "api_take" not in first.definition_json
    assert "terminal_statuses" not in first.definition_json


@pytest.mark.parametrize(
    "changed_config",
    [
        DashboardConfig(api_url="https://different.test/workflows"),
        DashboardConfig(status_filters=("Other",)),
        DashboardConfig(backlog_age_days=14.0),
        DashboardConfig(terminal_steps=("finish",)),
        DashboardConfig(team_members=("Different, Person",)),
        DashboardConfig(stale_idle_days=4),
        DashboardConfig(old_age_days=15),
        DashboardConfig(minimum_wait_completeness=1.0),
        DashboardConfig(minimum_idle_completeness=1.0),
        DashboardConfig(minimum_completion_completeness=1.0),
        DashboardConfig(workflow_filter="Workflow A"),
    ],
)
def test_relevant_config_changes_definition_hash(changed_config) -> None:
    baseline = _definition(DashboardConfig(), source="api")
    changed = _definition(changed_config, source="api")

    assert changed.definition_hash != baseline.definition_hash


def test_population_filter_and_metric_version_changes_definition_hash() -> None:
    config = DashboardConfig()
    baseline = _definition(config, records=_records_with_workflows("Workflow A"))
    changed_workflow = _definition(
        config, records=_records_with_workflows("Workflow B")
    )
    changed_filter = build_metric_definition(
        DashboardConfig(workflow_filter="Workflow A"),
        _records_with_workflows("Workflow A"),
        source="fixture",
    )
    changed_version = build_metric_definition(
        config,
        _records_with_workflows("Workflow A"),
        source="fixture",
        metric_definition_version=METRIC_DEFINITION_VERSION + 1,
    )

    assert len(
        {
            baseline.definition_hash,
            changed_workflow.definition_hash,
            changed_filter.definition_hash,
            changed_version.definition_hash,
        }
    ) == 4


def test_fixture_definition_ignores_api_status_filters(tmp_path) -> None:
    fixture_path = tmp_path / "records.json"
    baseline = _definition(
        DashboardConfig(fixture_path=fixture_path), source="fixture"
    )
    changed = _definition(
        DashboardConfig(
            fixture_path=fixture_path,
            status_filters=("CompletelyDifferent",),
        ),
        source="fixture",
    )

    assert changed.definition_hash == baseline.definition_hash


def test_unversioned_legacy_history_is_rejected(tmp_path) -> None:
    db_path = tmp_path / "history.sqlite"
    _create_legacy_history(db_path)

    with pytest.raises(HistorySchemaError, match="Archive or remove"):
        connect_history(db_path)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM snapshot_metrics"
        ).fetchone()[0] == 0


def test_new_snapshot_round_trips_definition_and_all_roster_members(
    tmp_path,
) -> None:
    db_path = tmp_path / "history.sqlite"
    analytics = _analytics()
    definition = _definition()

    first_run = store_snapshot(
        db_path, analytics, definition, source="fixture"
    )
    second_run = store_snapshot(
        db_path, analytics, definition, source="fixture"
    )
    snapshots, owners, monthly_completion = load_history(
        db_path,
        source="fixture",
        definition_hash=definition.definition_hash,
    )

    assert set(snapshots["run_id"]) == {first_run, second_run}
    assert set(snapshots["definition_hash"]) == {definition.definition_hash}
    assert set(snapshots["metric_definition_version"]) == {
        METRIC_DEFINITION_VERSION
    }
    assert set(snapshots["app_version"]) == {__version__}
    assert set(snapshots["idle_valid_count"]) == {5}
    assert set(snapshots["idle_total_count"]) == {5}
    assert set(snapshots["age_valid_count"]) == {4}
    assert set(snapshots["age_total_count"]) == {5}
    assert set(owners["run_id"]) == {first_run, second_run}
    assert set(owners["definition_hash"]) == {definition.definition_hash}
    assert len(owners) == 2 * (len(analytics.team_members) + 1)
    assert set(monthly_completion["run_id"]) == {first_run, second_run}
    assert set(monthly_completion["completion_valid_count"]) == {1}
    assert set(monthly_completion["completion_total_count"]) == {1}

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == (
            HISTORY_SCHEMA_VERSION
        )
        assert HISTORY_SCHEMA_VERSION == 4
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT COUNT(*) FROM metric_definitions"
        ).fetchone()[0] == 1
        stored_json = connection.execute(
            "SELECT definition_json FROM metric_definitions"
        ).fetchone()[0]
        snapshot_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(snapshot_metrics)")
        }
        monthly_table_count = connection.execute(
            "SELECT COUNT(*) FROM monthly_completion_history"
        ).fetchone()[0]
    assert stored_json == definition.definition_json
    assert "process_name" not in snapshot_columns
    assert {"age_valid_count", "age_total_count"}.issubset(snapshot_columns)
    assert monthly_table_count == 2


def test_backlog_threshold_change_splits_identical_dataset(tmp_path) -> None:
    db_path = tmp_path / "history.sqlite"
    seven_day_config = DashboardConfig(backlog_age_days=7.0)
    fourteen_day_config = DashboardConfig(backlog_age_days=14.0)
    records = _records_with_workflows("Workflow A")
    seven_day_definition = _definition(
        seven_day_config, records=records
    )
    fourteen_day_definition = _definition(
        fourteen_day_config, records=records
    )

    seven_day_run = store_snapshot(
        db_path,
        _analytics(seven_day_config),
        seven_day_definition,
        source="fixture",
    )
    fourteen_day_run = store_snapshot(
        db_path,
        _analytics(fourteen_day_config),
        fourteen_day_definition,
        source="fixture",
    )

    seven_day_history, _, _ = load_history(
        db_path,
        source="fixture",
        definition_hash=seven_day_definition.definition_hash,
    )
    fourteen_day_history, _, _ = load_history(
        db_path,
        source="fixture",
        definition_hash=fourteen_day_definition.definition_hash,
    )

    assert set(seven_day_history["run_id"]) == {seven_day_run}
    assert seven_day_history.iloc[0]["backlog_count"] == 2
    assert set(fourteen_day_history["run_id"]) == {fourteen_day_run}
    assert fourteen_day_history.iloc[0]["backlog_count"] == 0


def test_api_history_still_requires_pagination_validation(tmp_path) -> None:
    db_path = tmp_path / "history.sqlite"
    definition = _definition(source="api")
    analytics = _analytics()

    store_snapshot(
        db_path,
        analytics,
        definition,
        source="api",
        pagination_validated=False,
    )
    valid_run = store_snapshot(
        db_path,
        analytics,
        definition,
        source="api",
        pagination_validated=True,
    )
    snapshots, owners, monthly_completion = load_history(
        db_path,
        source="api",
        definition_hash=definition.definition_hash,
    )

    assert set(snapshots["run_id"]) == {valid_run}
    assert set(owners["run_id"]) == {valid_run}
    assert set(monthly_completion["run_id"]) == {valid_run}
