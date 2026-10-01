"""Command failures must stay actionable without publishing private diagnostics."""

import argparse
import json
from types import SimpleNamespace

import pytest
import requests

from workflow_dashboard import __main__ as cli
from workflow_dashboard.api_client import (
    ApiConfigurationError,
    PaginationIntegrityError,
)
from workflow_dashboard.config import DashboardConfig
from workflow_dashboard.history import HistorySchemaError
from workflow_dashboard.normalization import WorkflowPopulationError


@pytest.mark.parametrize("command", [cli.inspect_command, cli.run_command])
@pytest.mark.parametrize(
    "error",
    [
        ApiConfigurationError("synthetic-private-endpoint"),
        PaginationIntegrityError("synthetic-private-package-id"),
        WorkflowPopulationError("synthetic-private-workflow"),
        HistorySchemaError("synthetic-private-database-path"),
        requests.ConnectionError("synthetic-private-host"),
        requests.exceptions.JSONDecodeError("synthetic-private-response", "", 0),
        ValueError("synthetic-private-config-value"),
        PermissionError("synthetic-private-file-path"),
        RuntimeError("synthetic-private-class-name"),
    ],
)
def test_command_failures_do_not_expose_exception_details(
    monkeypatch, tmp_path, capsys, command, error
):
    def fail_config(**kwargs):
        raise error

    monkeypatch.setattr(cli, "load_config", fail_config)
    args = argparse.Namespace(
        source="fixture",
        output_dir=tmp_path / "outputs",
        fixture_path=None,
        history_db=tmp_path / "history.sqlite",
    )
    assert command(args) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out)["error"]
    assert "synthetic-private" not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err
    assert not args.output_dir.exists()
    assert not args.history_db.exists()


@pytest.mark.parametrize(
    "status,expected",
    [(401, "session expired"), (403, "cannot access"), (500, "Cannot reach")],
)
def test_http_failures_report_safe_remediation(status, expected, capsys):
    error = requests.HTTPError(
        "synthetic-private-request", response=SimpleNamespace(status_code=status)
    )
    assert cli._report_error(error) == 2
    output = capsys.readouterr().out
    assert expected in output
    assert "synthetic-private" not in output


def test_source_and_publication_failures_are_sanitized(monkeypatch, tmp_path, capsys):
    config = DashboardConfig(
        output_dir=tmp_path / "outputs", history_db_path=tmp_path / "history.sqlite"
    )
    monkeypatch.setattr(cli, "load_config", lambda **kwargs: config)
    args = argparse.Namespace(
        source="fixture",
        output_dir=config.output_dir,
        fixture_path=None,
        history_db=config.history_db_path,
    )

    def fail_fetch(*args):
        raise requests.ConnectionError("synthetic-private-request")

    monkeypatch.setattr(cli, "records_from_source", fail_fetch)
    assert cli.run_command(args) == 2
    assert "synthetic-private" not in capsys.readouterr().out

    monkeypatch.setattr(cli, "records_from_source", lambda *args: ([], {}, None))

    def fail_generation(*args, **kwargs):
        raise OSError("synthetic-private-output-path")

    monkeypatch.setattr(cli, "generate_dashboard", fail_generation)
    assert cli.run_command(args) == 2
    assert "synthetic-private" not in capsys.readouterr().out
    assert not config.output_dir.exists()
