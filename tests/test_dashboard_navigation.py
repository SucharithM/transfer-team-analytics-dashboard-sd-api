"""Offline browser coverage for section navigation and compact charts."""

import os
from dataclasses import replace
from pathlib import Path

import pytest
import pandas as pd
from playwright.sync_api import expect

from workflow_dashboard import dashboard_content as content
from workflow_dashboard.dashboard_html import render_dashboard
from .test_age_idle_action_matrix import _case, _analytics

# Reuse the existing opt-in Chrome/Edge setup and synthetic report generator.
from .test_dashboard_pdf import _open, _report, browser, page  # noqa: F401


def test_navigation_preserves_report_headings_and_components(tmp_path):
    markup = _report(tmp_path / "report.html").read_text(encoding="utf-8")
    for section in content.SECTION_CONTENT.values():
        assert f'>{section.title}</h2>' in markup
    for chart in content.CHART_CONTENT.values():
        title = chart.formatted(content.PresentationContext()).title
        assert f'<h2>{title}</h2>' in markup
    assert markup.count(' data-tab-panel="sections"') == 7
    assert markup.count(' data-tab-panel="operations"') == 2
    assert markup.count(' data-tab-panel="staff"') == 2
    assert markup.count('class="plotly-graph-div') == 15
    assert markup.count('<dialog ') == 1
    for obsolete in ('Hide guide', 'legend-toggle', 'guide-ready', 'is-collapsed', 'setGuideExpanded'):
        assert obsolete not in markup
    assert "Up to 100" not in markup


@pytest.mark.parametrize('width', [3440, 2560, 1680, 1440, 1401, 1280, 1024, 720, 390])
@pytest.mark.parametrize('scenario', ['sample', 'empty', 'stress'])
def test_overview_metrics_are_readable_and_responsive(page, tmp_path, width, scenario):
    page.set_viewport_size({'width': width, 'height': 1000})
    _open(page, _report(tmp_path / 'layout.html', scenario))
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    expect(page.locator('.kpi-grid .kpi')).to_have_count(8)
    assert page.locator('.sidebar-label, .snapshot-context').count() == 0
    if width > 900:
        sidebar = page.locator('.dashboard-sidebar').bounding_box()
        assert sidebar['x'] == pytest.approx(0, abs=1)
        assert sidebar['width'] == 208
        assert page.locator('#overview-panel').bounding_box()['x'] == 240
    assert page.locator('.kpi-grid').evaluate(
        'grid => getComputedStyle(grid).gridTemplateColumns.split(" ").length'
    ) == (4 if width >= 1280 else 2 if width > 520 else 1)
    assert page.locator('.kpi').evaluate_all('''cards => cards.every(card =>
      card.scrollWidth <= card.clientWidth && card.querySelector('strong').getBoundingClientRect().height > 0)''')
    expect(page.locator('.dashboard-sidebar .authorship-credit')).to_have_text(
        'Developed by Sucharith Madhusoodana')
    expect(page.locator('.dashboard-header .authorship-credit')).to_be_hidden()
    assert page.locator('.overview-charts .js-plotly-plot').count() == 2
    assert page.locator('#plot-overview-backlog').count() == 0
    actions = page.locator('.overview-actions').bounding_box()
    charts = page.locator('.overview-charts').bounding_box()
    assert actions['width'] == pytest.approx(charts['width'], abs=1)
    page.wait_for_function('''() => [...document.querySelectorAll('.overview-charts .js-plotly-plot')]
      .every(plot => Math.abs(plot._fullLayout.width - plot.clientWidth) < 2)''')
    if os.environ.get('DASHBOARD_PDF_ARTIFACT_DIR') and (scenario == 'sample' or width in (1440, 390)):
        page.screenshot(path=str(Path(os.environ['DASHBOARD_PDF_ARTIFACT_DIR']) / f'dashy-{scenario}-{width}.png'), full_page=True)
    sidebar_link = page.locator('[data-tab-list="sections"] a').first
    assert sidebar_link.bounding_box()['height'] >= 44
    assert sidebar_link.evaluate('link => getComputedStyle(link).alignItems') == 'center'
    page.locator('#tab-operations-panel').click()
    link = page.locator('[data-tab-list="operations"] a').first
    assert link.evaluate(
        'link => getComputedStyle(link).alignItems'
    ) in ('flex-end', 'flow-end')
    assert link.bounding_box()['height'] == 34
    assert link.evaluate('''link => {
      const text = document.createRange();
      text.selectNodeContents(link);
      return text.getBoundingClientRect().top - link.getBoundingClientRect().top;
    }''') <= 12
    assert page.locator('.dashboard-tabs').evaluate(
        'shell => getComputedStyle(shell).marginTop'
    ) == '0px'
    artifact_dir = os.environ.get('DASHBOARD_PDF_ARTIFACT_DIR')
    if artifact_dir and scenario == 'sample':
        page.locator('#tab-overview-panel').click()
        page.locator('.kpi-grid').screenshot(path=str(Path(artifact_dir) / f'overview-{width}.png'))
        page.locator('[data-tab-list="sections"]').screenshot(path=str(Path(artifact_dir) / f'tabs-{width}.png'))


def test_compact_tabs_keep_large_touch_targets(browser, tmp_path):
    with browser.new_context(has_touch=True, is_mobile=True,
                             viewport={'width': 390, 'height': 700}, offline=True) as context:
        page = context.new_page()
        _open(page, _report(tmp_path / 'touch-tabs.html'))
        page.locator('#tab-operations-panel').click()
        for group in ['sections', 'operations']:
            link = page.locator(f'[data-tab-list="{group}"] a').first
            assert link.bounding_box()['height'] >= 44


def test_navigation_keyboard_and_remembered_drilldown(page, tmp_path):
    _open(page, _report(tmp_path / "report.html"))
    expect(page.locator('#overview-panel')).to_be_visible()
    expect(page.locator('#case-metrics-panel')).to_be_hidden()
    expect(page.locator('#trends-panel')).to_be_hidden()
    primary = page.get_by_role('tablist', name='Dashboard sections')
    expect(primary.get_by_role('tab')).to_have_count(7)
    expect(primary).to_have_attribute('aria-orientation', 'vertical')
    assert primary.get_by_role('tab').all_text_contents() == [
        'Dashboard Overview', 'Operational Workload', 'Risk Overview',
        'Evaluation Types', 'Trends', 'Submission Activity', 'Observations',
    ]
    primary.get_by_role('tab', name='Dashboard Overview', exact=True).focus()
    page.keyboard.press('ArrowDown')
    expect(page.locator('#tab-operations-panel')).to_be_focused()
    page.keyboard.press('End')
    expect(page.locator('#tab-exceptions-panel')).to_be_focused()
    expect(page.locator('#overview-panel')).to_be_visible()
    page.keyboard.press('Space')
    expect(page.locator('#exceptions-panel')).to_be_visible()
    page.keyboard.press('Home')
    page.keyboard.press('Enter')
    expect(page.locator('#overview-panel')).to_be_visible()
    page.locator('#tab-operations-panel').click()
    expect(page.locator('#overview-panel')).to_be_hidden()
    expect(page.locator('#workflow-guide')).to_be_hidden()
    page.locator('#tab-case-metrics-panel').focus()
    page.keyboard.press('ArrowLeft')
    expect(page.locator('#tab-aging-panel')).to_be_focused()
    page.keyboard.press('Enter')
    expect(page.locator('#aging-panel')).to_be_visible()
    page.locator('#tab-risk-panel').click()
    expect(page.locator('#risk-panel')).to_be_visible()
    page.locator('[data-action-bucket]:not([disabled])').first.click()
    selected = page.locator('#age-idle-action-rows').inner_text()
    assert selected
    page.locator('#tab-staff-panel').click()
    expect(page.locator('#staff-volume-panel')).to_be_visible()
    page.locator('#tab-staff-date-panel').click()
    expect(page.locator('#staff-date-panel')).to_be_visible()
    expect(page.locator('#staff-volume-panel')).to_be_hidden()
    page.locator('#tab-risk-panel').click()
    expect(page.locator('#risk-panel')).to_be_visible()
    assert page.locator('#age-idle-action-rows').inner_text() == selected
    page.locator('#tab-staff-panel').click()
    expect(page.locator('#staff-date-panel')).to_be_visible()
    expect(page.locator('#tab-staff-date-panel')).to_have_attribute('aria-selected', 'true')


def test_deep_links_history_and_view_list(page, tmp_path):
    path = _report(tmp_path / 'report.html')
    _open(page, path)
    page.locator('#tab-risk-panel').click()
    page.locator('#tab-staff-panel').click()
    page.locator('#tab-staff-date-panel').click()
    page.go_back()
    expect(page.locator('#staff-volume-panel')).to_be_visible()
    page.go_back()
    expect(page.locator('#risk-panel')).to_be_visible()
    page.go_back()
    expect(page.locator('#overview-panel')).to_be_visible()
    page.go_forward()
    expect(page.locator('#risk-panel')).to_be_visible()
    page.goto(path.as_uri() + '#staff-date-panel')
    expect(page.locator('#staff-date-panel')).to_be_visible()
    page.reload()
    expect(page.locator('#staff-date-panel')).to_be_visible()
    page.locator('#tab-overview-panel').click()
    page.locator('.kpi-link').click()
    expect(page.locator('#exceptions-panel')).to_be_visible()
    expect(page.locator('#problem-rows-table')).to_be_focused()
    assert page.evaluate('location.hash') == '#problem-rows-table'


def test_age_donut_rounding_matches_legend_and_kpi(page, tmp_path):
    cases = pd.DataFrame([_case("rounding", age_days=23.15, idle_days=1.25)])
    analytics = _analytics(cases.to_dict("records"))
    path = render_dashboard(df=cases, analytics=analytics, history=pd.DataFrame(),
                            owner_history=pd.DataFrame(), output_path=tmp_path / "rounding.html")
    _open(page, path)
    page.locator('#tab-operations-panel').click()
    page.locator('#tab-aging-panel').click()
    expect(page.locator('#plot-aging-by-step .slicetext').first).to_have_text('23.2 days')
    expect(page.locator('[aria-controls="plot-aging-by-step"] strong')).to_have_text('23.2 days')
    assert next(k.value for k in analytics.kpis if k.key == "typical_wait_time") == "23.2 days"


def test_drilldown_rounding_matches_chart_and_kpi(page, tmp_path):
    cases = pd.DataFrame([_case("rounding", age_days=2.55, idle_days=1.25)])
    analytics = _analytics(cases.to_dict("records"))
    path = render_dashboard(df=cases, analytics=analytics, history=pd.DataFrame(),
                            owner_history=pd.DataFrame(), output_path=tmp_path / "rounding.html")
    _open(page, path)
    assert next(k.value for k in analytics.kpis if k.key == "typical_wait_time") == "2.6 days"
    page.locator('#tab-risk-panel').click()
    page.locator('[data-action-bucket="young_active"]').click()
    cells = page.locator('#age-idle-action-rows td')
    expect(cells.nth(2)).to_have_text("2.6 days")
    expect(cells.nth(3)).to_have_text("1.3 days")
    assert page.locator('#plot-age-idle-action-matrix').evaluate(
        'plot => plot.data[0].customdata[0][2]'
    ) == "2.6"


@pytest.mark.parametrize('width', [1440, 1280, 1024, 720, 390])
def test_compact_layout_and_plot_resize(page, tmp_path, width):
    page.set_viewport_size({'width': width, 'height': 900})
    _open(page, _report(tmp_path / 'report.html'))
    page.locator('#tab-operations-panel').click()
    columns = 1
    assert page.locator('.case-metrics-grid').evaluate(
        'grid => getComputedStyle(grid).gridTemplateColumns.split(" ").length'
    ) == columns
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.locator('#tab-aging-panel').click()
    expect(page.locator('#plot-workflow-aging-matrix')).to_be_visible()
    if width >= 1280:
        tops = page.locator('.aging-grid .chart-container').evaluate_all(
            'cards => cards.map(card => card.getBoundingClientRect().top)'
        )
        assert tops[1] > tops[0] + 380
    artifact_dir = os.environ.get('DASHBOARD_PDF_ARTIFACT_DIR')
    if artifact_dir:
        Path(artifact_dir).mkdir(parents=True, exist_ok=True)
        page.locator('#aging-panel').screenshot(path=str(Path(artifact_dir) / f'aging-{width}.png'))
    page.locator('#tab-staff-panel').click()
    page.locator('#tab-staff-date-panel').click()
    plot = page.locator('#plot-submitted-by-date-activity')
    expect(plot).to_be_visible()
    page.wait_for_function("""() => {
      const plot = document.getElementById('plot-submitted-by-date-activity');
      return Math.abs(plot._fullLayout.width - plot.clientWidth) < 2;
    }""")
    assert plot.evaluate('plot => plot._fullLayout.height') == 285
    page.locator('#tab-operations-panel').click()
    page.locator('#tab-case-metrics-panel').click()
    if width >= 1280:
        assert page.locator('.case-metrics-grid').bounding_box()['height'] > 1000
    if artifact_dir:
        page.locator('#case-metrics-panel').screenshot(path=str(Path(artifact_dir) / f'metrics-{width}.png'))
    page.locator('#tab-trends-panel').click()
    if width > 900:
        page.evaluate("window.scrollTo({top: document.querySelector('.dashboard-tabs').offsetTop + 150, behavior: 'instant'})")
        page.wait_for_function("() => Math.abs(document.querySelector('.dashboard-sidebar').getBoundingClientRect().top - 76) < 2")


def test_all_observations_scroll_and_print_without_changing_selection(page, tmp_path):
    _open(page, _report(tmp_path / 'stress.html', 'stress'))
    page.locator('.kpi-link').click()
    expect(page.locator('#problem-rows-table tbody tr')).to_have_count(120)
    expect(page.locator('.table-summary')).to_have_text('Showing 120 of 120 case observations.')
    scroll = page.locator('#problem-rows-table .table-scroll')
    assert scroll.bounding_box()['height'] <= 420
    assert scroll.evaluate('table => table.scrollHeight > table.clientHeight')
    scroll.evaluate('table => table.scrollTop = table.scrollHeight')
    assert scroll.evaluate('table => table.scrollTop > 0')
    page.emulate_media(media='print')
    assert page.locator('[data-tab-panel="sections"]:visible').count() == 7
    assert page.locator('[data-tab-panel="operations"]:visible').count() == 2
    assert page.locator('[data-tab-panel="staff"]:visible').count() == 2
    expect(page.locator('.dashboard-tabbar').first).to_be_hidden()
    expect(page.locator('#age-idle-action-drilldown')).to_be_hidden()
    assert scroll.evaluate('table => table.clientHeight >= table.scrollHeight - 1')
    page.emulate_media(media='screen')
    expect(page.locator('#exceptions-panel')).to_be_visible()
    expect(page.locator('#operations-panel')).to_be_hidden()


def test_report_content_remains_readable_without_javascript(browser, tmp_path):
    path = _report(tmp_path / 'report.html')
    with browser.new_context(java_script_enabled=False, offline=True) as context:
        value = context.new_page()
        value.goto(path.as_uri())
        assert value.locator('[data-tab-panel="sections"]:visible').count() == 7
        expect(value.locator('.dashboard-tabbar').first).to_be_hidden()
        expect(value.locator('#problem-rows-table')).to_be_visible()
        expect(value.locator('#workflow-guide')).to_be_hidden()
        value.emulate_media(media='print')
        expect(value.locator('.legend-item:visible')).to_have_count(6)


def test_failed_enhancement_restores_the_readable_report(page, tmp_path):
    path = _report(tmp_path / 'report.html')
    page.add_init_script("""window.ResizeObserver = class {
      constructor() { window.navigationFailureReached = true; throw new Error('synthetic failure'); }
    };""")
    page.goto(path.as_uri())
    page.wait_for_function('() => window.navigationFailureReached === true')
    assert page.locator('[data-tab-panel="sections"]:visible').count() == 7
    expect(page.locator('.dashboard-tabbar').first).to_be_hidden()
    expect(page.locator('#operations-panel')).to_have_attribute('aria-labelledby', 'operations-title')
    page.locator('.kpi-link').click()
    assert page.locator('[data-tab-panel="sections"]:visible').count() == 7


@pytest.mark.parametrize('width', [1440, 1280, 1024, 720, 390])
def test_readable_chart_categories_and_risk_frame(page, tmp_path, width):
    page.set_viewport_size({'width': width, 'height': 900})
    _open(page, _report(tmp_path / 'report.html'))
    page.locator('#tab-operations-panel').click()
    for panel, plot_id in [('case-metrics-panel', 'plot-in-the-works-by-step'),
                           ('aging-panel', 'plot-aging-by-step')]:
        page.locator('#tab-' + panel).click()
        plot = page.locator('#' + plot_id)
        card = plot.locator('xpath=ancestor::div[contains(@class,"chart-container")][1]')
        rows = card.locator('.category-toggle')
        assert rows.count() > 0
        assert plot.evaluate('p => p._fullLayout.showlegend') is False
        bounds = plot.locator('.pielayer').bounding_box()
        assert bounds['width'] >= (240 if width == 390 else 340)
        assert card.locator('.chart-category-list').evaluate('e => e.scrollHeight <= e.clientHeight')
        rows.first.scroll_into_view_if_needed()
        rows.first.focus()
        rows.first.press('Enter')
        expect(rows.first).to_have_attribute('aria-pressed', 'false')
        page.wait_for_function('id => document.getElementById(id).layout.hiddenlabels.length === 1', arg=plot_id)
        rows.first.press('Space')
        expect(rows.first).to_have_attribute('aria-pressed', 'true')
        page.wait_for_function('id => document.getElementById(id).layout.hiddenlabels.length === 0', arg=plot_id)
    page.locator('#tab-risk-panel').click()
    risk = page.locator('#plot-age-idle-action-matrix')
    assert risk.evaluate('p => p._fullLayout.height') == 620
    assert risk.evaluate('p => p._fullLayout.showlegend') is False
    assert risk.evaluate('p => p.layout.annotations.length') == 3
    legend = page.locator('.action-matrix-card .chart-category-list')
    assert legend.bounding_box()['y'] >= risk.bounding_box()['y'] + risk.bounding_box()['height']
    button = legend.locator('button').first
    button.click()
    page.wait_for_function("() => document.getElementById('plot-age-idle-action-matrix').data[0].visible === 'legendonly'")
    button.click()
    page.wait_for_function("() => document.getElementById('plot-age-idle-action-matrix').data[0].visible === true")
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    artifact_dir = os.environ.get('DASHBOARD_PDF_ARTIFACT_DIR')
    if artifact_dir:
        page.wait_for_function("() => !document.querySelector('.dashboard-tabs').style.minHeight")
        page.mouse.move(0, 0)
        page.locator('.action-matrix-card').screenshot(
            path=str(Path(artifact_dir) / f'risk-{width}.png'),
            style='.dashboard-tabbar { position: static !important; }')


def test_footer_tracks_content_and_returns_to_top(page, tmp_path):
    _open(page, _report(tmp_path / 'report.html'))
    for panel in ['staff-panel', 'exceptions-panel', 'operations-panel']:
        page.locator('#tab-' + panel).click()
        page.wait_for_function("() => !document.querySelector('.dashboard-tabs').style.minHeight")
        gap = page.evaluate("""() => document.querySelector('.page-footer').getBoundingClientRect().top
          - document.querySelector('[data-tab-panel="sections"]:not([hidden])').getBoundingClientRect().bottom""")
        assert gap == pytest.approx(24, abs=1)
        assert page.locator('.dashboard-tabs').evaluate("e => getComputedStyle(e).minHeight") == '0px'
    page.locator('.jump-to-top').click()
    page.wait_for_function('() => scrollY < 2')


@pytest.mark.parametrize("width", [1440, 1024, 720, 390])
def test_observation_headers_chips_and_contained_scroll(page, tmp_path, width):
    cases = pd.DataFrame([
        _case(str(i), age_days=30, idle_days=8, status=status,
              step_name=("Long workflow name pending additional documentation " * 3
                         if i % 2 else "W" * 180), item_label="X" * 180)
        for i, status in enumerate(["In Progress", "InProgress", "Needs Review",
                                    "NeedsReview", "Completed", "Unknown"])
    ])
    analytics = _analytics(cases.to_dict("records"))
    # Completed rows are still observations when supplied by the report's analytics.
    analytics = replace(analytics, exceptions=cases.assign(exception_reasons="Review these observations"))
    path = render_dashboard(df=cases, analytics=analytics, history=pd.DataFrame(),
                            owner_history=pd.DataFrame(), output_path=tmp_path / "observations.html")
    page.set_viewport_size({"width": width, "height": 900})
    _open(page, path)
    page.locator('#tab-exceptions-panel').click()
    table = page.locator('#problem-rows-table table')
    assert table.locator('tbody tr').count() == 6
    assert table.locator('th').evaluate_all("""headers => headers.every(h => {
      const r = document.createRange(); r.selectNodeContents(h);
      return r.getClientRects().length === 1 && h.scrollWidth <= h.clientWidth;
    })""")
    assert table.locator('col').evaluate_all(
        'cols => cols.map(c => c.getBoundingClientRect().width)'
    ) == [260, 140, 260, 320, 160, 180, 150, 200, 200, 200]
    assert table.locator('.observation-chip').count() == 12
    assert table.locator('.observation-chip').evaluate_all("""chips => chips.every(c =>
      c.scrollWidth <= c.clientWidth && c.getBoundingClientRect().right <=
      c.closest('td').getBoundingClientRect().right &&
      getComputedStyle(c).fontSize === '12px' &&
      getComputedStyle(c).borderRadius === '8px')""")
    assert table.locator('td').evaluate_all('cells => cells.every(c => c.scrollWidth <= c.clientWidth)')
    scroll = page.locator('#problem-rows-table .table-scroll')
    assert scroll.evaluate('s => s.scrollWidth > s.clientWidth')
    scroll.evaluate('s => s.scrollLeft = s.scrollWidth')
    assert scroll.evaluate('s => s.scrollLeft > 0')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    scroll.evaluate('s => s.scrollLeft = 0')
    artifact_dir = os.environ.get('DASHBOARD_PDF_ARTIFACT_DIR')
    if artifact_dir:
        page.locator('#problem-rows-table').screenshot(
            path=str(Path(artifact_dir) / f'observations-{width}.png'))
        scroll.evaluate('s => s.scrollLeft = 660')
        page.locator('#problem-rows-table').screenshot(
            path=str(Path(artifact_dir) / f'observations-workflow-{width}.png'))
        scroll.evaluate('s => s.scrollLeft = 980')
        page.locator('#problem-rows-table').screenshot(
            path=str(Path(artifact_dir) / f'observations-status-{width}.png'))
    page.emulate_media(media='print')
    page.set_viewport_size({'width': 980, 'height': 740})
    assert table.evaluate('t => t.scrollWidth <= t.clientWidth + 1')
    assert table.locator('th[data-field="status"], th[data-field="owner"]').evaluate_all(
        """headers => headers.every(h => {
          const r = document.createRange(); r.selectNodeContents(h);
          return r.getClientRects().length === 1 && h.scrollWidth <= h.clientWidth;
        })""")
    assert table.locator('.workflow-chip').evaluate_all('chips => chips.every(c => c.scrollWidth <= c.clientWidth)')

    assert table.locator('.status-review > span').first.evaluate("""label => {
      return ['Needs', 'Review'].every(word => {
        const start = label.firstChild.textContent.indexOf(word);
        const r = document.createRange();
        r.setStart(label.firstChild, start); r.setEnd(label.firstChild, start + word.length);
        return r.getClientRects().length === 1;
      });
    }""")
