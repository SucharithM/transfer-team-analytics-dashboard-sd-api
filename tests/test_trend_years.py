"""Year filtering preserves metric semantics and offline chart behavior."""

from dataclasses import replace
import os
from pathlib import Path

import pandas as pd
import pytest
from playwright.sync_api import expect

from workflow_dashboard.analytics import _closed_by_month, _daily_closures
from workflow_dashboard.dashboard_html import (
    _closed_by_month_trend, _daily_closures_chart, _empty_figure,
    _line_chart, _recent_closures_chart, _trend_controls, _trend_views,
    render_dashboard,
)
from .test_analytics_cohorts import build_sample_analytics, sample_cases
from .test_dashboard_pdf import _open, browser, page  # noqa: F401


AS_OF = pd.Timestamp('2027-01-06T16:00:00Z')


def _data():
    dates = pd.date_range('2026-12-20', '2027-01-05', freq='D', tz='UTC') + pd.Timedelta(hours=16)
    cases = pd.DataFrame({'last_activity_at': dates, 'submitted_at': dates - pd.Timedelta(days=5)})
    history = pd.DataFrame({
        'generated_at': dates, 'backlog_count': range(17),
        'median_age_days': [2.55] * 17,
    })
    return _daily_closures(cases, AS_OF), _closed_by_month(cases, AS_OF), history


def _report(path):
    daily, monthly, history = _data()
    analytics = build_sample_analytics()
    analytics = replace(analytics, generated_at=AS_OF, chart_tables={
        **analytics.chart_tables, 'daily_closures': daily, 'closed_by_month': monthly,
    })
    return render_dashboard(df=sample_cases(), analytics=analytics, history=history,
                            owner_history=pd.DataFrame(), output_path=path)


def test_year_views_keep_rolling_context_hover_and_month_labels():
    daily, monthly, history = _data()
    views = _trend_views(_daily_closures_chart(daily), 'daily_closures')
    assert list(views) == ['all', '2027', '2026']
    assert list(views['2027'].data[1].y) == [1.0] * 5
    assert list(views['2027'].data[1].customdata) == ['1.0'] * 5
    assert all(pd.Timestamp(x).year == 2027 for x in views['2027'].data[0].x)
    months = _trend_views(_closed_by_month_trend(monthly), 'closed_by_month')
    assert list(months['2027'].layout.xaxis.ticktext) == ['Jan 27 (MTD)']
    assert list(months['2027'].data[0].text) == ['5']
    assert monthly.closed_month_label.tolist() == ['Dec 2026', 'Jan 2027 (MTD)']
    assert '%Y' in months['2027'].data[0].hovertemplate
    age = _trend_views(_line_chart(history, 'median_age_days', 'Age', 'Days', one_decimal=True), 'age_trend')
    assert age['all'].layout.xaxis.tickformat == '%b %-d\n%Y'
    assert age['2027'].layout.xaxis.tickformat == '%b %-d'
    assert age['2027'].data[0].customdata[0][1] == '2.6'


def test_empty_single_year_and_single_point_views():
    empty = _trend_views(_empty_figure('Empty'), 'backlog_trend')
    assert list(empty) == ['all']
    assert empty['all'].layout.height == 360
    assert _trend_controls(empty, 'backlog_trend') == ''
    history = pd.DataFrame({'generated_at': ['2027-01-01T04:30:00Z'], 'backlog_count': [4]})
    views = _trend_views(_line_chart(history, 'backlog_count', 'Backlog', 'Cases'), 'backlog_trend')
    assert list(views) == ['all', '2026']  # Eastern December 31
    controls = _trend_controls(views, 'backlog_trend')
    assert '2026' in controls and '<button' not in controls
    assert list(views['2026'].layout.xaxis.tickvals) == [pd.Timestamp('2026-12-31')]
    assert len(views['2026'].layout.xaxis.range) == 2
    recent = _recent_closures_chart(_data()[0], AS_OF)
    assert recent.layout.xaxis.tickformat == '%b %-d'
    assert '%Y' in recent.data[0].hovertemplate


@pytest.mark.parametrize('width', [1440, 1051, 1050, 390])
def test_independent_year_controls_uniform_layout_and_dates(page, tmp_path, width):
    page.set_viewport_size({'width': width, 'height': 1000})
    _open(page, _report(tmp_path / 'years.html'))
    page.locator('#tab-trends-panel').click()
    page.wait_for_function('''() => {
      const plots = [...document.querySelectorAll('.trend-grid .js-plotly-plot')];
      return !document.querySelector('.dashboard-tabs').style.minHeight &&
        plots.every(p => Math.abs(p._fullLayout.width - p.clientWidth) < 2);
    }''')
    plots = page.locator('.trend-grid .js-plotly-plot')
    assert plots.count() == 5
    assert plots.evaluate_all('''plots => plots.every(p =>
      p._fullLayout.height === (p.id === 'plot-daily-closures' ? 420 : 360))''')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    heights = plots.evaluate_all('plots => plots.map(p => p._fullLayout._size.h)')
    assert max(heights) - min(heights) < 1
    for key in ('recent-closures', 'backlog-trend', 'age-trend'):
        gap = page.locator('#plot-' + key).evaluate('''plot => {
          const card = plot.closest('.chart-container');
          const heading = card.querySelector('.trend-year-controls') ||
            card.querySelector('.completion-date-note') || card.querySelector('.card-heading');
          return plot.getBoundingClientRect().top + plot._fullLayout._size.t -
            heading.getBoundingClientRect().bottom;
        }''')
        assert 0 <= gap <= 56
    artifact_dir = os.environ.get('DASHBOARD_PDF_ARTIFACT_DIR')
    if artifact_dir:
        Path(artifact_dir).mkdir(parents=True, exist_ok=True)
        page.locator('#trends-panel').screenshot(path=str(Path(artifact_dir) / f'years-{width}.png'))
    assert page.locator('.trend-grid [data-trend-year][aria-pressed="true"]').all_text_contents() == ['2027'] * 4
    group = page.locator('[aria-label="Year for Backlog Trend — Open Cases Over 7 Days Old"]')
    group.get_by_role('button', name='All years', exact=True).focus()
    page.keyboard.press('Enter')
    expect(group.get_by_role('button', name='All years', exact=True)).to_have_attribute('aria-pressed', 'true')
    assert page.locator('#plot-backlog-trend').evaluate('p => p.data[0].x.length') == 17
    labels = page.locator('#plot-backlog-trend .xtick').all_text_contents()
    assert sum('2026' in label for label in labels) == 1
    assert sum('2027' in label for label in labels) == 1
    assert page.locator('#plot-age-trend').evaluate('p => p.data[0].x.length') == 5
    group.get_by_role('button', name='2026', exact=True).click()
    expect(group.get_by_role('button', name='2026', exact=True)).to_have_attribute('aria-pressed', 'true')
    assert all('2026' not in label for label in page.locator('#plot-backlog-trend .xtick').all_text_contents())
    page.locator('#tab-operations-panel').click()
    disabled = page.locator('.action-group-button:disabled')
    assert disabled.count() > 0
    assert disabled.evaluate_all('buttons => buttons.every(b => getComputedStyle(b).borderTopColor === getComputedStyle(b).borderRightColor)')
    page.locator('#tab-trends-panel').click()
    expect(group.get_by_role('button', name='2026', exact=True)).to_have_attribute('aria-pressed', 'true')
    assert not any('2027' in label or '2026' in label for label in page.locator('#plot-recent-closures .xtick').all_text_contents())


def test_pdf_preserves_period_and_waits_for_year_update(page, tmp_path):
    _open(page, _report(tmp_path / 'years.html'))
    page.locator('#tab-trends-panel').click()
    group = page.locator('[aria-label="Year for Cases Completed by Month"]')
    page.evaluate('''() => {
      const react = Plotly.react;
      Plotly.react = async (...args) => {
        await new Promise(resolve => { window.releaseYearUpdate = resolve; });
        Plotly.react = react;
        return react(...args);
      };
    }''')
    group.get_by_role('button', name='2026', exact=True).click()
    page.locator('#save-pdf').click()
    assert page.evaluate('window.printCalls') == 0
    assert page.locator('.pdf-chart').count() == 0
    page.evaluate('window.releaseYearUpdate()')
    page.wait_for_function('() => window.printCalls === 1')
    expect(group.get_by_role('button', name='2026', exact=True)).to_have_attribute('aria-pressed', 'true')
    page.emulate_media(media='print')
    expect(group.get_by_role('button', name='2026', exact=True)).to_be_visible()
    expect(group.get_by_role('button', name='2027', exact=True)).to_be_hidden()
    page.evaluate("window.dispatchEvent(new Event('afterprint'))")
    page.emulate_media(media='screen')
    expect(group.get_by_role('button', name='2027', exact=True)).to_be_visible()
    assert page.locator('#plot-closed-by-month').evaluate('p => p.layout.xaxis.ticktext') == ['Dec 26']


@pytest.mark.parametrize('fail_export', [False, True])
def test_export_locks_year_controls_until_print_finishes_or_fails(page, tmp_path, fail_export):
    _open(page, _report(tmp_path / 'export-years.html'))
    page.locator('#tab-trends-panel').click()
    page.evaluate('''fail => {
      const toImage = Plotly.toImage;
      Plotly.toImage = async (plot, ...args) => {
        const image = await toImage(plot, ...args);
        if (plot.id === 'plot-closed-by-month') {
          window.capturedMonthYears = plot.data[0].x.map(x => String(x).slice(0, 4));
          await new Promise(resolve => { window.releaseMonthlyImage = resolve; });
          if (fail) throw new Error('Synthetic image failure');
        }
        return image;
      };
    }''', fail_export)
    page.locator('#save-pdf').click()
    page.wait_for_function("() => typeof window.releaseMonthlyImage === 'function'")
    group = page.locator('[aria-label="Year for Cases Completed by Month"]')
    year = group.get_by_role('button', name='2026', exact=True)
    expect(year).to_be_disabled()
    expect(page.locator('[data-trend-year]:enabled')).to_have_count(0)
    year.evaluate('button => button.click()')
    expect(group.get_by_role('button', name='2027', exact=True)).to_have_attribute('aria-pressed', 'true')
    assert page.evaluate('window.capturedMonthYears') == ['2027']
    page.evaluate('window.releaseMonthlyImage()')
    if fail_export:
        expect(page.locator('#pdf-export-status')).to_have_class('pdf-export-status is-error')
        assert page.evaluate('window.printCalls') == 0
    else:
        page.wait_for_function('() => window.printCalls === 1')
        expect(year).to_be_disabled()
        page.evaluate("window.dispatchEvent(new Event('afterprint'))")
    expect(year).to_be_enabled()
    expect(page.locator('[data-trend-year]:disabled')).to_have_count(0)
    year.click()
    expect(year).to_have_attribute('aria-pressed', 'true')
    assert page.locator('#plot-closed-by-month').evaluate('plot => plot.layout.xaxis.ticktext') == ['Dec 26']


@pytest.mark.parametrize('width', [1440, 390])
def test_monthly_labels_clear_the_title_and_fit_after_year_changes(page, tmp_path, width):
    stamp = pd.Timestamp('2026-12-16T16:00:00Z')
    dates = pd.date_range('2025-01-01', '2026-12-01', freq='MS', tz='UTC') + pd.Timedelta(hours=16)
    cases = pd.DataFrame({'last_activity_at': dates, 'submitted_at': dates - pd.Timedelta(days=1)})
    analytics = build_sample_analytics()
    analytics = replace(analytics, generated_at=stamp, chart_tables={
        **analytics.chart_tables, 'closed_by_month': _closed_by_month(cases, stamp),
    })
    path = render_dashboard(df=sample_cases(), analytics=analytics, history=pd.DataFrame(),
                            owner_history=pd.DataFrame(), output_path=tmp_path / 'monthly-labels.html')
    page.set_viewport_size({'width': width, 'height': 1000})
    _open(page, path)
    page.locator('#tab-trends-panel').click()
    group = page.locator('[aria-label="Year for Cases Completed by Month"]')
    plot = page.locator('#plot-closed-by-month')
    for year in ('2026', '2025', 'All years'):
        group.get_by_role('button', name=year, exact=True).click()
        expect(group.get_by_role('button', name=year, exact=True)).to_have_attribute('aria-pressed', 'true')
        page.wait_for_function("() => !document.querySelector('.dashboard-tabs').style.minHeight")
        errors = plot.evaluate('''plot => {
          const title = plot.querySelector('.xtitle').getBoundingClientRect();
          const bounds = plot.getBoundingClientRect();
          const errors = [];
          if (title.bottom > bounds.bottom + 1) errors.push('Axis title clipped');
          for (const tick of plot.querySelectorAll('.xtick text')) {
            const rect = tick.getBoundingClientRect();
            if (!rect.width || !rect.height) continue;
            if (rect.left < title.right && rect.right > title.left && rect.top < title.bottom && rect.bottom > title.top)
              errors.push(tick.textContent + ': overlaps title');
            if (rect.bottom > bounds.bottom + 1 || rect.left < bounds.left - 1 || rect.right > bounds.right + 1)
              errors.push(tick.textContent + ': clipped');
          }
          return errors;
        }''')
        assert not errors, (year, errors)
    artifact_dir = os.environ.get('DASHBOARD_PDF_ARTIFACT_DIR')
    if artifact_dir:
        plot.screenshot(path=str(Path(artifact_dir) / f'monthly-labels-{width}.png'))
