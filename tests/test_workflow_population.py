import pandas as pd
import pytest

from workflow_dashboard.config import DashboardConfig, load_config
from workflow_dashboard.normalization import (
    WorkflowPopulationError,
    select_workflow_population,
)


def _records(*workflow_names: str | None) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "record_id": [f"record-{index}" for index in range(len(workflow_names))],
            "workflow_name": workflow_names,
        }
    )


def test_configured_filter_selects_one_workflow_and_excludes_unnamed() -> None:
    records = _records("Workflow A", " workflow a ", "Workflow B", None)

    selected = select_workflow_population(
        records, DashboardConfig(workflow_filter="WORKFLOW A")
    )

    assert selected["record_id"].tolist() == ["record-0", "record-1"]
    assert selected.index.tolist() == [0, 1]


def test_configured_filter_that_matches_nothing_reports_discovered_names() -> None:
    records = _records("Workflow A", "Workflow B", None)

    with pytest.raises(
        WorkflowPopulationError,
        match=r"matched no records.*Workflow A, Workflow B, <unnamed>",
    ):
        select_workflow_population(
            records, DashboardConfig(workflow_filter="Workflow C")
        )


def test_unconfigured_single_named_workflow_is_accepted_case_insensitively() -> None:
    records = _records("Workflow A", "workflow a")

    selected = select_workflow_population(records, DashboardConfig())

    assert selected.equals(records)


@pytest.mark.parametrize(
    "records",
    [
        _records("Workflow A", "Workflow B"),
        _records("Workflow A", None),
        _records(None, None),
    ],
    ids=("multiple", "partially-unnamed", "wholly-unnamed"),
)
def test_unconfigured_ambiguous_population_is_rejected(records) -> None:
    with pytest.raises(WorkflowPopulationError, match="WORKFLOW_FILTER is required"):
        select_workflow_population(records, DashboardConfig())


def test_empty_source_is_allowed_only_without_a_filter() -> None:
    empty = _records()

    assert select_workflow_population(empty, DashboardConfig()).empty
    with pytest.raises(WorkflowPopulationError, match="matched no records"):
        select_workflow_population(
            empty, DashboardConfig(workflow_filter="Workflow A")
        )


def test_workflow_filter_environment_configuration(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WORKFLOW_FILTER", "Workflow A")

    config = load_config(env_file=tmp_path / "missing.env")

    assert config.workflow_filter == "Workflow A"
