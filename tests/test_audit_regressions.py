"""Regression cases from the repository audit."""
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

from workflow_dashboard.config import DashboardConfig
from workflow_dashboard.desktop import desktop_config
from workflow_dashboard.dashboard_html import _donut_chart
from workflow_dashboard.generation import generate_dashboard
from workflow_dashboard.history import build_metric_definition, load_history, store_snapshot
from .test_analytics_cohorts import build_sample_analytics


def test_decimal_donut_keeps_raw_values_and_shared_display_strings():
    fig = _donut_chart(pd.DataFrame({'step': ['Review'], 'age_days': [23.15]}),
                       'step', 'age_days', 'Age', one_decimal=True, value_suffix='d')
    assert list(fig.data[0].values) == [23.15]
    assert list(fig.data[0].text) == ['23.2d']
    assert '%{text}' in fig.data[0].texttemplate
    assert '%{text}' in fig.data[0].hovertemplate


def test_case_only_workflow_changes_keep_saved_history(tmp_path):
    config = DashboardConfig(workflow_filter='Example')
    first = build_metric_definition(config, pd.DataFrame({'workflow_name': ['Example']}), source='api')
    second = build_metric_definition(config, pd.DataFrame({'workflow_name': [' EXAMPLE ', 'example']}), source='api')
    assert first.definition_hash == second.definition_hash
    db = tmp_path / 'history.sqlite'
    run = store_snapshot(db, build_sample_analytics(), first, source='api', pagination_validated=True)
    history, _, _ = load_history(db, source='api', definition_hash=second.definition_hash)
    assert list(history.run_id) == [run]


def test_unusable_date_and_control_text_still_generate_all_outputs(tmp_path):
    config = DashboardConfig(output_dir=tmp_path / 'reports', history_db_path=tmp_path / 'history.sqlite',
                             dashboard_title='Dashboard\x0bTitle')
    record = {'packageID': 'one', 'workflowName': 'Example', 'stepName': 'Review',
              'packageName': 'Evaluation\x0bName | Demo Person | Demo School',
              'submissionDate': '0001-01-01T00:00:00', 'lastActivityDate': '2026-11-01T12:00:00Z'}
    result = generate_dashboard(config, [record], {'pagination_validated': True},
                                generated_at=pd.Timestamp('2026-11-03T18:00:00Z'))
    assert all(Path(result['outputs'][kind]).is_file() for kind in ('html', 'excel', 'csv'))
    csv = pd.read_csv(result['outputs']['csv'])
    assert pd.isna(csv.loc[0, 'submitted_at'])
    assert csv.loc[0, 'item_label'] == record['packageName']
    workbook = load_workbook(result['outputs']['excel'])
    try:
        assert workbook['Summary']['A1'].value == 'DashboardTitle'
        rows = list(workbook['Normalized Records'].values)
        assert rows[1][rows[0].index('item_label')] == 'EvaluationName | Demo Person | Demo School'
    finally:
        workbook.close()


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf'), True, '7'])
def test_invalid_backlog_threshold_is_rejected(value):
    with pytest.raises(ValueError, match='backlog_age_days'):
        DashboardConfig(backlog_age_days=value)


def test_desktop_rejects_invalid_backlog_before_signin(tmp_path):
    settings = tmp_path / 'settings.toml'
    settings.write_text('workflow_filter="Example"\nbacklog_age_days=-1\n')
    with pytest.raises(ValueError, match='backlog_age_days'):
        desktop_config(settings)
    assert replace(DashboardConfig(), backlog_age_days=0).backlog_age_days == 0
