"""Regression checks for clipped help and involuntary tab scrolling."""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect

from .test_dashboard_pdf import _open, _prepare, _report, browser, page  # noqa: F401


def _settled(page):
    page.wait_for_function("""() => {
      const shell = document.querySelector('.dashboard-tabs');
      return !shell.style.minHeight && Array.from(document.querySelectorAll('.tab-panels'))
        .every(host => !host.style.height) && [...document.querySelectorAll('.js-plotly-plot')]
        .filter(plot => plot.getClientRects().length)
        .every(plot => Math.abs(plot._fullLayout.width - plot.clientWidth) < 2);
    }""")


@pytest.mark.parametrize('width', [1440, 2560])
def test_scrollbar_space_is_only_used_when_the_section_needs_scrolling(page, tmp_path, width):
    page.set_viewport_size({'width': width, 'height': 900})
    _open(page, _report(tmp_path / 'scrollbar.html'))
    for section, scrolling in [('staff-panel', False), ('trends-panel', True),
                               ('staff-panel', False)]:
        page.locator('#tab-' + section).click()
        _settled(page)
        assert page.evaluate('document.documentElement.scrollHeight > innerHeight') == scrolling
        if scrolling:
            page.evaluate("window.scrollTo({top: document.documentElement.scrollHeight, behavior: 'instant'})")
            assert page.evaluate('scrollY') > 0
        else:
            assert page.evaluate('document.documentElement.clientWidth === innerWidth')
            assert page.locator('.university-masthead').bounding_box()['width'] == width
        page.wait_for_function("""() => [...document.querySelectorAll('.js-plotly-plot')]
          .filter(plot => plot.getClientRects().length)
          .every(plot => Math.abs(plot._fullLayout.width - plot.clientWidth) < 2)""")
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        artifact_dir = os.environ.get('DASHBOARD_PDF_ARTIFACT_DIR')
        if artifact_dir:
            page.screenshot(path=str(Path(artifact_dir) / f'scrollbar-{section}-{width}.png'))


@pytest.mark.parametrize("width", [1440, 720, 390])
def test_process_guide_modal_is_available_from_every_section(page, tmp_path, width):
    page.set_viewport_size({"width": width, "height": 700 if width == 390 else 900})
    _open(page, _report(tmp_path / "report.html"))
    trigger = page.get_by_role('button', name='Process guide', exact=True)
    guide = page.get_by_role('dialog', name='Transcript Evaluation Workflow Legend')
    assert page.locator('#overview-panel dialog').count() == 0
    assert not trigger.get_attribute('aria-expanded')
    for tab in ('overview-panel', 'operations-panel', 'aging-panel', 'risk-panel',
                'evaluation-types-panel', 'trends-panel', 'staff-panel',
                'staff-date-panel', 'exceptions-panel'):
        page.locator('#tab-' + tab).click()
        _settled(page)
        trigger.scroll_into_view_if_needed()
        before = page.evaluate('({hash: location.hash, y: scrollY})')
        height = page.locator('#' + tab).bounding_box()['height']
        trigger.click()
        expect(guide).to_be_visible()
        expect(guide.get_by_role('button', name='Close', exact=True)).to_be_focused()
        expect(guide.locator('.legend-item')).to_have_count(6)
        expect(page.locator('#tab-' + tab)).to_have_attribute('aria-selected', 'true')
        if width > 900:
            assert page.locator('.dashboard-sidebar').bounding_box()['y'] == pytest.approx(76, abs=1)
        assert guide.evaluate('''dialog => {
          const rect = dialog.getBoundingClientRect();
          return rect.left >= 15 && rect.top >= 15 && rect.right <= innerWidth - 15
            && rect.bottom <= innerHeight - 15;
        }''')
        if width == 390:
            assert guide.evaluate('dialog => dialog.scrollHeight > dialog.clientHeight')
            guide.evaluate('dialog => dialog.scrollTop = dialog.scrollHeight')
            expect(guide.locator('.legend-item').last).to_be_in_viewport()
        artifact_dir = os.environ.get('DASHBOARD_PDF_ARTIFACT_DIR')
        if artifact_dir and tab == 'operations-panel':
            page.screenshot(path=str(Path(artifact_dir) / f'guide-modal-{width}.png'))
        if tab == 'exceptions-panel':
            guide.get_by_role('button', name='Close', exact=True).click()
        else:
            page.keyboard.press('Escape')
        expect(guide).to_be_hidden()
        expect(trigger).to_be_focused()
        assert page.evaluate('({hash: location.hash, y: scrollY})') == before
        assert page.locator('#' + tab).bounding_box()['height'] == height
        assert page.locator('.js-plotly-plot:visible').evaluate_all('''plots => plots.every(plot =>
          Math.abs(plot._fullLayout.width - plot.clientWidth) < 2)''')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('width,height', [(1440, 900), (1024, 600)])
def test_sidebar_fills_viewport_with_utilities_at_bottom_while_scrolling(page, tmp_path, width, height):
    page.set_viewport_size({'width': width, 'height': height})
    _open(page, _report(tmp_path / 'sidebar.html'))
    sidebar = page.locator('.dashboard-sidebar')
    timestamp = sidebar.locator('.sidebar-generated-at')
    expect(timestamp).to_have_text(page.locator('.generated-at').inner_text())
    assert timestamp.evaluate('p => parseFloat(getComputedStyle(p).fontSize)') <= 12
    for section in ('overview-panel', 'trends-panel', 'overview-panel'):
        page.locator('#tab-' + section).click()
        _settled(page)
        page.evaluate("window.scrollTo({top: document.documentElement.scrollHeight, behavior: 'instant'})")
        bounds = sidebar.bounding_box()
        assert bounds['y'] == pytest.approx(76, abs=1)
        assert bounds['height'] == height - 76
        button = sidebar.locator('#save-pdf').bounding_box()
        guide = sidebar.locator('#show-workflow-guide').bounding_box()
        generated = timestamp.bounding_box()
        credit = sidebar.locator('.authorship-credit')
        expect(credit).to_be_in_viewport()
        assert credit.locator('strong').evaluate('e => getComputedStyle(e).fontSize === getComputedStyle(e).getPropertyValue("--font-size-md").trim()')
        assert credit.evaluate('''e => {
          const probe = document.createElement('span');
          probe.style.color = 'var(--muted)';
          e.append(probe);
          const matches = getComputedStyle(e).color === getComputedStyle(probe).color;
          probe.remove();
          return matches;
        }''')
        assert guide['y'] + guide['height'] < credit.bounding_box()['y']
        assert credit.bounding_box()['y'] + credit.bounding_box()['height'] < generated['y']
        assert button['y'] + button['height'] < guide['y']
        assert guide['y'] + guide['height'] < generated['y']
        assert 0 <= height - generated['y'] - generated['height'] <= 24
        assert sidebar.locator('[data-tab-list="sections"]').bounding_box()['y'] >= 0


def test_print_closes_the_modal_and_includes_the_complete_guide(page, tmp_path):
    _open(page, _report(tmp_path / 'report.html'))
    page.locator('#tab-staff-panel').click()
    page.locator('#tab-staff-date-panel').click()
    _settled(page)
    page.locator('#show-workflow-guide').click()
    expect(page.locator('#workflow-guide')).to_be_visible()
    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
    expect(page.locator('#workflow-guide')).to_be_hidden()
    _prepare(page)
    page.emulate_media(media='print')
    expect(page.locator('.legend-item:visible')).to_have_count(6)
    expect(page.locator('#close-workflow-guide')).to_be_hidden()
    expect(page.locator('.dashboard-sidebar')).to_be_hidden()
    page.evaluate("window.dispatchEvent(new Event('afterprint'))")
    page.emulate_media(media='screen')
    expect(page.locator('#workflow-guide')).to_be_hidden()
    expect(page.locator('#staff-date-panel')).to_be_visible()


def _assert_framed(page, tip):
    expect(tip).to_be_visible()
    expect(tip).to_have_css("opacity", "1")
    page.wait_for_function("""id => {
      const tip = document.getElementById(id);
      const r = tip.getBoundingClientRect();
      return r.left >= 11 && r.top >= 11 && r.right <= innerWidth - 11 && r.bottom <= innerHeight - 11;
    }""", arg=tip.get_attribute("id"))
    assert tip.evaluate("""tip => {
      const r = tip.getBoundingClientRect();
      return tip.contains(document.elementFromPoint(r.left + r.width / 2, r.bottom - 4));
    }""")


@pytest.mark.parametrize("width,height", [(1440, 900), (1024, 720), (390, 700)])
def test_kpi_tooltips_fit_edges_and_overlay_the_tabs(page, tmp_path, width, height):
    page.set_viewport_size({"width": width, "height": height})
    _open(page, _report(tmp_path / "report.html"))
    for trigger in page.locator(".kpi .info-button").all():
        trigger.scroll_into_view_if_needed()
        trigger.focus()
        tip = page.locator("#" + trigger.get_attribute("aria-describedby"))
        _assert_framed(page, tip)
        assert tip.evaluate("tip => tip.parentElement.id") == "dashboard-tooltip-layer"
        trigger.press("Escape")
        expect(tip).to_be_hidden()
    # Reproduce the median-age help overlapping the navigation in the screenshot.
    trigger = page.locator(".kpi .info-button").nth(4)
    trigger.evaluate("button => button.blur()")
    trigger.scroll_into_view_if_needed()
    trigger.focus()
    tip = page.locator("#" + trigger.get_attribute("aria-describedby"))
    _assert_framed(page, tip)
    artifact_dir = os.environ.get("DASHBOARD_PDF_ARTIFACT_DIR")
    if artifact_dir:
        Path(artifact_dir).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(artifact_dir) / f"tooltip-{width}.png"))


def test_tooltips_flip_track_scroll_and_stay_hoverable(page, tmp_path):
    page.set_viewport_size({"width": 1440, "height": 400})
    _open(page, _report(tmp_path / "report.html"))
    # Allow this geometry check to place a card against either viewport edge.
    page.add_style_tag(content='#overview-panel { min-height: 1200px; }')
    trigger = page.locator(".kpi .info-button").first
    tip = page.locator("#" + trigger.get_attribute("aria-describedby"))
    trigger.evaluate("""button => window.scrollTo({
      top: scrollY + button.getBoundingClientRect().top - innerHeight + 45, behavior: 'instant'
    })""")
    trigger.hover()
    _assert_framed(page, tip)
    expect(tip).to_have_attribute("data-placement", "top")
    tip.hover()
    expect(tip).to_be_visible()
    page.mouse.move(2, 2)
    expect(tip).to_be_hidden()
    trigger.evaluate("""button => window.scrollTo({
      top: scrollY + button.getBoundingClientRect().top - 30, behavior: 'instant'
    })""")
    trigger.focus()
    _assert_framed(page, tip)
    expect(tip).to_have_attribute("data-placement", "bottom")
    page.evaluate("window.scrollBy({top: -80, behavior: 'instant'})")
    page.wait_for_function("""id => {
      const trigger = document.querySelector('.kpi .info-button');
      return Math.abs(document.getElementById(id).getBoundingClientRect().top - trigger.getBoundingClientRect().bottom - 8) < 1;
    }""", arg=tip.get_attribute("id"))
    page.locator('#tab-trends-panel').click()
    expect(tip).to_be_hidden()


@pytest.mark.parametrize("width", [1440, 390])
def test_chart_table_and_long_tooltips_escape_card_clipping(page, tmp_path, width):
    page.set_viewport_size({"width": width, "height": 700})
    _open(page, _report(tmp_path / "report.html"))
    page.locator('#tab-operations-panel').click()
    for tab in ("case-metrics-panel", "aging-panel", "risk-panel", "evaluation-types-panel",
                "trends-panel", "staff-panel", "staff-date-panel", "exceptions-panel"):
        page.locator("#tab-" + tab).click()
        _settled(page)
        for trigger in page.locator("#" + tab + " .info-button:visible").all():
            trigger.scroll_into_view_if_needed()
            trigger.focus()
            _assert_framed(page, page.locator("#" + trigger.get_attribute("aria-describedby")))
    tip = page.locator("#problem-rows-table-help")
    tip.evaluate("tip => tip.textContent = tip.textContent.repeat(80)")
    page.set_viewport_size({"width": 390, "height": 500})
    page.locator('[aria-describedby="problem-rows-table-help"]').scroll_into_view_if_needed()
    page.locator('[aria-describedby="problem-rows-table-help"]').evaluate("button => button.blur()")
    page.locator('[aria-describedby="problem-rows-table-help"]').focus()
    _assert_framed(page, tip)
    assert tip.evaluate("tip => tip.scrollHeight > tip.clientHeight")
    assert tip.evaluate("tip => getComputedStyle(tip).overflowY") == "auto"
    tip.evaluate("tip => tip.scrollTop = tip.scrollHeight")
    page.wait_for_function("""id => document.getElementById(id).scrollTop > 0""", arg=tip.get_attribute("id"))
    page.locator("#tab-operations-panel").focus()
    page.keyboard.press("Enter")
    expect(tip).to_be_hidden()


def test_touch_tooltip_toggle_and_outside_dismissal(browser, tmp_path):
    path = _report(tmp_path / "report.html")
    with browser.new_context(has_touch=True, is_mobile=True, offline=True,
                             viewport={"width": 390, "height": 700}) as context:
        value = context.new_page()
        _open(value, path)
        trigger = value.locator(".kpi .info-button").first
        tip = value.locator("#" + trigger.get_attribute("aria-describedby"))
        trigger.tap()
        _assert_framed(value, tip)
        trigger.tap()
        expect(tip).to_be_hidden()
        trigger.tap()
        expect(tip).to_be_visible()
        value.touchscreen.tap(3, 3)
        expect(tip).to_be_hidden()


@pytest.mark.parametrize("width", [1440, 390])
def test_normal_tab_switches_do_not_move_the_page(page, tmp_path, width):
    page.set_viewport_size({"width": width, "height": 900})
    _open(page, _report(tmp_path / "report.html"))
    page.evaluate("window.scrollTo({top: document.querySelector('.dashboard-tabs').offsetTop - 300, behavior: 'instant'})")
    for tab in ("trends-panel", "exceptions-panel", "operations-panel", "aging-panel", "case-metrics-panel"):
        before = page.evaluate("({y: scrollY, top: document.querySelector('[data-tab-list=sections]').getBoundingClientRect().top})")
        # Dispatch a genuine activation without Playwright scrolling a horizontally hidden tab.
        page.locator("#tab-" + tab).evaluate("link => link.click()")
        samples = page.evaluate("""id => new Promise(resolve => {
          const values = [];
          const sample = () => {
            values.push({y: scrollY, top: document.querySelector('[data-tab-list=sections]').getBoundingClientRect().top,
              opacity: Number(getComputedStyle(document.getElementById(id)).opacity)});
            if (!document.querySelector('.dashboard-tabs').style.minHeight && values.length > 2) resolve(values);
            else requestAnimationFrame(sample);
          };
          sample();
        })""", tab)
        final_max = page.evaluate('Math.max(0, document.documentElement.scrollHeight - innerHeight)')
        expected_y = min(before["y"], final_max)
        assert abs(page.evaluate('scrollY') - expected_y) < 2
        assert all(expected_y - 2 <= sample["y"] <= before["y"] + 2 for sample in samples)
        if before["y"] <= final_max:
            assert max(abs(sample["top"] - before["top"]) for sample in samples) < 2
        assert any(0 < sample["opacity"] < 1 for sample in samples)
        expect(page.locator("#tab-" + tab)).to_be_focused()


def test_deep_switch_aligns_once_and_rapid_clicks_settle_on_latest(page, tmp_path):
    _open(page, _report(tmp_path / "report.html"))
    page.locator("#tab-trends-panel").click()
    _settled(page)
    page.evaluate("window.scrollTo({top: document.querySelector('.dashboard-tabs').offsetTop + 250, behavior: 'instant'})")
    old_y = page.evaluate("scrollY")
    page.locator("#tab-exceptions-panel").click()
    samples = page.evaluate("""() => new Promise(resolve => {
      const values = [];
      const sample = () => {
        values.push({y: scrollY, top: document.querySelector('[data-tab-list=sections]').getBoundingClientRect().top});
        if (!document.querySelector('.dashboard-tabs').style.minHeight && values.length > 2) resolve(values);
        else requestAnimationFrame(sample);
      };
      sample();
    })""")
    assert page.evaluate("scrollY") < old_y - 100
    assert len({round(sample["y"]) for sample in samples}) > 3
    final_max = page.evaluate('Math.max(0, document.documentElement.scrollHeight - innerHeight)')
    assert page.evaluate('scrollY') <= final_max + 1
    assert all(samples[index + 1]["y"] <= samples[index]["y"] + 2 for index in range(len(samples) - 1))
    assert page.locator('#exceptions-panel').bounding_box()['y'] >= 0
    page.evaluate("""() => {
      ['operations-panel', 'risk-panel', 'staff-panel', 'staff-date-panel', 'operations-panel', 'aging-panel']
        .forEach((id, index) => setTimeout(() => document.getElementById('tab-' + id).click(), index * 25));
    }""")
    expect(page.locator("#tab-aging-panel")).to_have_attribute("aria-selected", "true")
    _settled(page)
    expect(page.locator("#aging-panel")).to_be_visible()
    expect(page.locator("#risk-panel")).to_be_hidden()
    expect(page.locator("#staff-panel")).to_be_hidden()
    assert page.evaluate("document.getAnimations().length") == 0
    assert page.locator("#plot-workflow-aging-matrix").evaluate("plot => Math.abs(plot._fullLayout.width - plot.clientWidth)") < 2


def test_reduced_motion_and_print_finish_pending_transitions(page, tmp_path):
    page.emulate_media(reduced_motion="reduce")
    _open(page, _report(tmp_path / "report.html"))
    page.locator("#tab-staff-panel").click()
    page.locator("#tab-staff-date-panel").click()
    _settled(page)
    assert page.evaluate("document.getAnimations().length") == 0
    page.emulate_media(reduced_motion="no-preference")
    page.locator("#tab-trends-panel").click()
    _prepare(page)
    assert page.locator(".tab-panels[style*=height]").count() == 0
    page.emulate_media(media="print")
    assert page.locator('[data-tab-panel="sections"]:visible').count() == 7
    expect(page.locator("#dashboard-tooltip-layer")).to_be_hidden()
    page.evaluate("window.dispatchEvent(new Event('afterprint'))")
    page.emulate_media(media="screen")
    expect(page.locator("#trends-panel")).to_be_visible()


@pytest.mark.parametrize('width', [1440, 390])
@pytest.mark.parametrize('backlog,idle,expected', [(7, 3, ['a', 'b']), (9, 4, ['b'])])
def test_overview_risk_action_opens_matching_list_and_restores_history(page, tmp_path, width, backlog, idle, expected):
    import pandas as pd
    from workflow_dashboard.config import DashboardConfig
    from workflow_dashboard.dashboard_html import render_dashboard
    from .test_age_idle_action_matrix import _case, _analytics

    cases = [
        _case('a', age_days=8, idle_days=3),
        _case('b', age_days=10, idle_days=4),
        _case('c', age_days=8, idle_days=2),
        _case('missing', age_days=None, idle_days=4),
    ]
    analytics = _analytics(cases, DashboardConfig(backlog_age_days=backlog, stale_idle_days=idle))
    path = render_dashboard(df=pd.DataFrame(cases), analytics=analytics, history=pd.DataFrame(),
                            owner_history=pd.DataFrame(), output_path=tmp_path / 'actions.html')
    page.set_viewport_size({'width': width, 'height': 900})
    _open(page, path)
    action = page.locator('.overview-action-risk')
    expect(action.locator('.action-count')).to_have_text(str(len(expected)))
    action.focus()
    page.keyboard.press('Enter')

    def assert_list():
        expect(page.locator('#risk-panel')).to_be_visible()
        _settled(page)
        expect(page.locator('#action-group-backlog_stale')).to_have_attribute('aria-pressed', 'true')
        assert sorted(page.locator('#age-idle-action-rows td:first-child').all_text_contents()) == expected
        heading = page.locator('#age-idle-action-drilldown-title')
        expect(heading).to_be_focused()
        expect(heading).to_be_in_viewport()
        assert heading.bounding_box()['y'] >= (76 if width > 900 else 0)

    assert_list()
    page.go_back()
    expect(page.locator('#overview-panel')).to_be_visible()
    page.go_forward()
    assert_list()
    page.locator('#age-idle-action-clear').click()
    expect(page.locator('#age-idle-action-drilldown')).to_be_hidden()
    page.reload()
    assert_list()
    page.locator('#tab-overview-panel').click()
    _settled(page)
    page.locator('.overview-action[href="#problem-rows-table"]').click()
    expect(page.locator('#exceptions-panel')).to_be_visible()
    expect(page.locator('#problem-rows-table')).to_be_focused()


def test_empty_overview_actions_do_not_offer_unavailable_risk_cases(page, tmp_path):
    _open(page, _report(tmp_path / 'empty-actions.html', 'empty'))
    risk = page.locator('.overview-action-risk')
    expect(risk).to_have_attribute('aria-disabled', 'true')
    assert risk.get_attribute('href') is None
    expect(risk.locator('.action-count')).to_have_text('0')
    page.locator('.overview-action[href="#problem-rows-table"]').click()
    expect(page.locator('#exceptions-panel')).to_be_visible()
    expect(page.locator('#problem-rows-table .empty-table')).to_be_visible()
