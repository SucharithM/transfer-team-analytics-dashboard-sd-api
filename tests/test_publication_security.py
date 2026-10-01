"""Regression checks for publication cleanup and untrusted export values."""
import csv
import io
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from openpyxl import load_workbook

from workflow_dashboard.api_client import ApiConfigurationError, ApiCredentialDisclosureError, WorkflowApiClient, inspect_payload, records_from_source
from workflow_dashboard.browser_auth import bearer_from_request, browser_fetch, BrowserAuthError
from workflow_dashboard.config import DashboardConfig, load_config
from workflow_dashboard.excel_export import export_workbook
from workflow_dashboard.generation import _csv_ready
from workflow_dashboard.desktop import desktop_config
from .test_analytics_cohorts import build_sample_analytics, sample_cases
from .test_outputs import _history_frames


@pytest.mark.parametrize("value", ["=1+1", "+1+1", "-1+1", "@SUM(A1)", "  =1+1", "\ttext", "\rtext", "\ntext", "\ufeff=1+1"])
def test_csv_formula_prefixes_are_neutralized_without_changing_numbers(value):
    result = _csv_ready(pd.DataFrame({"label": [value], "age_days": [-2.5]}))
    row = next(csv.DictReader(io.StringIO(result.to_csv(index=False))))
    assert row["label"] == "'" + value
    assert row["age_days"] == "-2.5"


def test_csv_plain_text_and_missing_values_are_preserved():
    original = pd.DataFrame({"label": ["Demo Student 001", "O'Example", None], "age_days": [1.25, 2.5, -3.0]})
    assert _csv_ready(original).equals(original)


def test_saved_workbook_contains_literal_source_values_and_title(tmp_path):
    df = sample_cases()
    df.loc[df.index[0], "item_label"] = '=HYPERLINK("https://example.test","example")'
    analytics = replace(build_sample_analytics(), dashboard_title="=1+1")
    history, owners = _history_frames(analytics)
    path = export_workbook(df=df, analytics=analytics, history=history, owner_history=owners, output_path=tmp_path / "audit.xlsx")
    workbook = load_workbook(path, data_only=False)
    assert workbook.worksheets[0]["A1"].value == "=1+1"
    assert workbook.worksheets[0]["A1"].data_type == "s"
    values = [cell for sheet in workbook for row in sheet for cell in row]
    assert any(cell.value == df.loc[df.index[0], "item_label"] and cell.data_type == "s" for cell in values)
    assert not any(cell.data_type == "f" for cell in values)
    workbook.close()


def test_inspection_never_includes_record_values():
    summary = inspect_payload({"total": 1, "records": [{"packageID": "synthetic-private-id", "packageName": "synthetic-private-name", "token": "synthetic-private-secret"}]}, source="api")
    output = json.dumps(summary)
    assert "synthetic-private" not in output
    assert "sample_record" not in summary
    assert summary["record_keys"] == ["packageID", "packageName", "token"]


def test_configured_endpoint_is_matched_exactly():
    endpoint = "https://configured.example.test/flow/api/user-dashboard/packages"
    request = SimpleNamespace(method="GET", url=endpoint + "?offset=0", header_value=lambda name: "Bearer synthetic-test-token")
    assert bearer_from_request(request, api_url=endpoint) == "synthetic-test-token"
    assert bearer_from_request(request) is None
    request.url = endpoint.replace("configured.example.test", "configured.example.test.evil.test")
    assert bearer_from_request(request, api_url=endpoint) is None


@pytest.mark.parametrize("endpoint", ["http://configured.example.test/packages", "https://user:pass@configured.example.test/packages", "https://configured.example.test:444/packages", "https://configured.example.test/packages?token=synthetic-secret", "https://configured.example.test/packages#fragment"])
def test_insecure_endpoints_are_rejected_before_network_or_browser(monkeypatch, endpoint):
    monkeypatch.setattr("requests.get", lambda *a, **kw: pytest.fail("No network request should occur"))
    config = DashboardConfig(api_url=endpoint, api_token="synthetic-test-token")
    with pytest.raises(ApiConfigurationError):
        WorkflowApiClient(config).fetch_page()
    with pytest.raises(BrowserAuthError):
        browser_fetch(config)


def test_private_roster_is_only_loaded_from_explicit_local_configuration(tmp_path):
    env = tmp_path / ".env"
    env.write_text('WORKFLOW_TEAM_MEMBERS=["Synthetic, Local Staff"]\n')
    assert load_config(env_file=env).team_members == ("Synthetic, Local Staff",)
    assert DashboardConfig().team_members[0] == "Staff Member A"


def test_published_fixture_is_explicitly_synthetic():
    path = Path(__file__).resolve().parents[1] / "data/sample_api_response.json"
    fixture = json.loads(path.read_text())
    assert fixture["Item1"] == len(fixture["Item2"]) == 15
    for row in fixture["Item2"]:
        assert row["packageID"].startswith("demo-package-")
        assert "Demo Student " in row["packageName"]
        assert "Example Institution " in row["packageName"]
        assert row["submittedBy"].startswith("Staff Member ")
        assert row["taskID"] is None or row["taskID"].startswith("demo-task-")


def test_explicit_private_desktop_profile_preserves_history_namespace(tmp_path):
    settings = tmp_path / "settings.toml"
    local_data = tmp_path / "previous-app-data"
    settings.write_text('workflow_filter = "Synthetic Workflow"\napi_url = "https://configured.example.test/packages"\n'
                        + 'data_directory = ' + json.dumps(str(local_data)) + '\nteam_members = ["Synthetic Local Staff"]\n')
    config = desktop_config(settings)
    assert config.history_db_path == local_data / "history/workflow_history.sqlite"
    assert config.team_members == ("Synthetic Local Staff",)
    assert config.api_token is None


@pytest.mark.parametrize("payload", [
    {"records": [{"packageID": "demo", "debug": "synthetic-test-token"}], "total": 1},
    {"records": [], "total": 0, "debug": {"nested": ["synthetic-test-token"]}},
    {"records": [], "total": 0, "synthetic-test-token": "echo in key"},
])
def test_api_rejects_credential_echoes_before_inspection_or_export(monkeypatch, payload):
    response = SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                               json=lambda: payload, close=lambda: closed.append(True))
    closed = []
    monkeypatch.setattr("requests.get", lambda *args, **kwargs: response)
    client = WorkflowApiClient(DashboardConfig(api_token="synthetic-test-token"))

    with pytest.raises(ApiCredentialDisclosureError) as error:
        client.fetch_page()
    assert "synthetic-test-token" not in str(error.value)
    assert closed == [True]


@pytest.mark.parametrize("fails", [False, True])
def test_legacy_source_releases_client_credentials_on_success_and_failure(monkeypatch, fails):
    closed = []

    def fetch(self):
        if fails:
            raise ApiConfigurationError("synthetic failure")
        return [], {}

    original_close = WorkflowApiClient.close
    monkeypatch.setattr(WorkflowApiClient, "fetch_all_records", fetch)

    def tracked_close(self):
        original_close(self)
        closed.append(self._bearer_token)

    monkeypatch.setattr(WorkflowApiClient, "close", tracked_close)
    config = DashboardConfig(api_token="synthetic-test-token")
    if fails:
        with pytest.raises(ApiConfigurationError):
            records_from_source("api", config)
    else:
        assert records_from_source("api", config) == ([], {}, {"records": []})
    assert closed == [None]


def test_configuration_repr_excludes_credentials_in_custom_headers():
    config = DashboardConfig(api_token="synthetic-private-bearer",
                             headers={"Authorization": "Bearer synthetic-private-header",
                                      "Cookie": "synthetic-private-cookie"})
    assert "synthetic-private" not in repr(config)
