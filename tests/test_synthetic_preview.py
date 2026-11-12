import json
import sqlite3
from zipfile import ZipFile
from pathlib import Path

import pandas as pd
import pytest

from tools.synthetic_preview import generate_records, historical_population, main, preview
from workflow_dashboard.analytics import build_analytics
from workflow_dashboard.config import DashboardConfig
from workflow_dashboard.normalization import normalize_records

AS_OF = pd.Timestamp('2026-11-12T17:00:00Z')


def test_records_repeatability_and_coverage():
    rows = generate_records(5000, 42, AS_OF)
    assert rows == generate_records(5000, 42, AS_OF)
    assert rows != generate_records(5000, 43, AS_OF)
    assert len({r['packageID'] for r in rows}) == len(rows) == 5000
    frame = normalize_records(rows, DashboardConfig(), generated_at=AS_OF)
    assert frame.submitted_at.le(frame.last_activity_at).all()
    assert frame.last_activity_at.le(AS_OF).all()
    analytics = build_analytics(frame, config=DashboardConfig(), generated_at=AS_OF)
    assert analytics.chart_tables['age_idle_action_matrix'].action_bucket.nunique() == 4
    assert analytics.chart_tables['workflow_aging_matrix'].query('count > 0').aging_band.nunique() == 6
    assert analytics.chart_tables['closed_by_month'].shape[0] >= 6
    # Regressions for the two fixed idle bands and isolated completion-date spikes.
    open_cases = frame.loc[~frame.is_terminal]
    assert open_cases.idle_days.round(2).nunique() > 100
    assert open_cases.idle_days.quantile(0.95) > 5
    assert open_cases.age_days.median() < 30
    daily = analytics.chart_tables['daily_closures']
    weekdays = daily.loc[daily.closed_date.dt.day_of_week < 5, 'closed_count']
    assert weekdays.gt(0).mean() > 0.95
    assert daily.closed_count.max() < frame.is_terminal.sum() * 0.04
    assert daily.closed_count.nunique() > 20
    earlier = historical_population(frame, AS_OF - pd.Timedelta(days=29), report_at=AS_OF, seed=42)
    assert earlier.loc[~earlier.is_terminal, 'age_days'].median() < open_cases.age_days.median() - 3
    edge = normalize_records(generate_records(200, 42, AS_OF, 'edge'), DashboardConfig(), generated_at=AS_OF)
    stressed = build_analytics(edge, config=DashboardConfig(), generated_at=AS_OF)
    assert stressed.snapshot_metrics['median_age_days'] is None
    assert stressed.snapshot_metrics['median_idle_days'] is None


def test_history_uses_case_dates_and_reconciles_arrivals_and_closures():
    config = DashboardConfig()
    rows = generate_records(4, 42, AS_OF)
    for row, submitted_days, closed_days in zip(rows, (5, 5, 2, 0.25), (3, 0.5, None, None)):
        row['submissionDate'] = (AS_OF - pd.Timedelta(days=submitted_days)).isoformat()
        row['stepName'] = 'End' if closed_days is not None else 'Transcript Evaluator'
        row['lastActivityDate'] = (AS_OF - pd.Timedelta(days=closed_days or submitted_days)).isoformat()
    original = normalize_records(rows, config, generated_at=AS_OF)
    unchanged = original.copy(deep=True)
    at = AS_OF - pd.Timedelta(days=1)
    past = historical_population(original, at, report_at=AS_OF, seed=42)
    assert len(past) == 3
    assert past.is_terminal.tolist() == [True, False, False]
    assert past.submitted_at.equals(original.submitted_at.iloc[:3])
    assert past.submitted_at.le(past.last_activity_at).all()
    assert past.last_activity_at.le(at).all()
    assert past.last_activity_at.le(original.last_activity_at.loc[past.index]).all()
    assert past.age_days.tolist() == [4, 4, 1]
    assert past.loc[1, 'status'] == 'InProgress'
    arrivals = original.submitted_at.gt(at).sum()
    closures = (original.is_terminal & original.last_activity_at.gt(at)).sum()
    assert (~original.is_terminal).sum() == (~past.is_terminal).sum() + arrivals - closures
    pd.testing.assert_frame_equal(original, unchanged)


@pytest.mark.parametrize('args', [ ['--records', '-1'], ['--records', 'bad'], ['--as-of', '2026-11-12'], ['--as-of', 'bad'] ])
def test_invalid_arguments_create_nothing(tmp_path, args):
    with pytest.raises(SystemExit):
        main(args + ['--output-dir', str(tmp_path / 'absent')])
    assert not (tmp_path / 'absent').exists()


def test_isolated_volume_preview(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    sentinel = 'SENTINEL_PRIVATE_CONFIG'
    (tmp_path / '.env').write_text('WORKFLOW_DASHBOARD_TITLE=' + sentinel)
    for key in ('WORKFLOW_DASHBOARD_TITLE', 'WORKFLOW_API_TOKEN', 'WORKFLOW_API_URL', 'WORKFLOW_TEAM_MEMBERS', 'WORKFLOW_HISTORY_DB'):
        monkeypatch.setenv(key, sentinel)
    def forbidden(*a, **kw):
        pytest.fail('Unexpected configuration, network, or browser access')
    monkeypatch.setattr('workflow_dashboard.config.load_config', forbidden)
    monkeypatch.setattr('requests.sessions.Session.request', forbidden)
    monkeypatch.setattr('workflow_dashboard.browser_auth.browser_fetch', forbidden)
    result = preview(records=5000, as_of=AS_OF, output_dir=tmp_path / 'previews')
    assert result['records'] == 5000
    for key in ('html', 'excel', 'csv', 'history_db'):
        path = Path(result['outputs'][key])
        assert path.stat().st_size > 0
        assert sentinel.encode() not in path.read_bytes()
        if key == 'excel':
            with ZipFile(path) as archive:
                assert all(sentinel.encode() not in archive.read(name) for name in archive.namelist())
    with sqlite3.connect(result['outputs']['history_db']) as db:
        assert db.execute('SELECT count(*), count(distinct snapshot_date), count(distinct definition_hash), count(distinct backlog_count) FROM snapshot_metrics').fetchone()[:3] == (30, 30, 1)
        assert db.execute('SELECT count(distinct backlog_count) FROM snapshot_metrics').fetchone()[0] > 1
        times = [pd.Timestamp(row[0]).tz_convert('America/New_York') for row in db.execute('SELECT generated_at FROM snapshot_metrics')]
        assert all(stamp.hour == 12 for stamp in times)
    again = preview(records=0, as_of=AS_OF, output_dir=tmp_path / 'previews')
    assert again['outputs']['history_db'] != result['outputs']['history_db']
    with sqlite3.connect(again['outputs']['history_db']) as db:
        assert db.execute('SELECT count(*) FROM snapshot_metrics').fetchone()[0] == 1
    assert generate_records(100, 42, AS_OF, 'empty') == []


# Reuse the project's opt-in, offline browser setup.
from .test_dashboard_pdf import browser, page, _open  # noqa: E402,F401
from .test_dashboard_interactions import _settled  # noqa: E402


@pytest.mark.parametrize('scenario', ['mixed', 'edge'])
def test_large_preview_browser(page, tmp_path, scenario):
    import os
    import time
    started = time.perf_counter()
    destination = Path(os.environ.get('DASHBOARD_PDF_ARTIFACT_DIR', tmp_path)) / scenario
    result = preview(records=10000, scenario=scenario, as_of=AS_OF, output_dir=destination)
    path = Path(result['outputs']['html'])
    print(f'{scenario}: {time.perf_counter() - started:.1f}s generation, {path.stat().st_size:,} HTML bytes; {path}')
    _open(page, path)
    assert page.locator('#plot-backlog-trend').evaluate('(node) => node.data[0].x.length') == 30
    for width in (1440, 390):
        page.set_viewport_size({'width': width, 'height': 900})
        for tab in ('case-metrics-panel', 'aging-panel', 'risk-panel', 'evaluation-types-panel', 'trends-panel', 'staff-panel', 'staff-date-panel', 'exceptions-panel'):
            if tab in ('case-metrics-panel', 'aging-panel', 'risk-panel'):
                page.locator('#tab-operations-panel').evaluate('(node) => node.click()')
            elif tab == 'staff-date-panel':
                page.locator('#tab-staff-panel').evaluate('(node) => node.click()')
            page.locator('#tab-' + tab).evaluate('(node) => node.click()')
            page.wait_for_function('(id) => !document.getElementById(id).hidden', arg=tab)
            assert page.locator('#' + tab).is_visible()
            _settled(page)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (scenario, tab, width)
        page.screenshot(path=str(destination / f'{scenario}-observations-{width}.png'), full_page=True)
        page.locator('#tab-trends-panel').evaluate('(node) => node.click()')
        _settled(page)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (scenario, 'trends', width)
        page.screenshot(path=str(destination / f'{scenario}-trends-{width}.png'), full_page=True)
        page.locator('#tab-operations-panel').evaluate('(node) => node.click()')
        page.locator('#tab-risk-panel').evaluate('(node) => node.click()')
        page.locator('[data-action-bucket]:not([disabled])').first.click()
        assert page.locator('#age-idle-action-rows').inner_text().strip()
        _settled(page)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (scenario, 'drilldown', width)
        page.screenshot(path=str(destination / f'{scenario}-{width}.png'), full_page=True)
