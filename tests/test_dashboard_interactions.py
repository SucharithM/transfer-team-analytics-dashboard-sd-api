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
        .every(host => !host.style.height);
    }""")


@pytest.mark.parametrize("width", [1440, 720, 390])
def test_process_guide_reflows_without_gaps_or_chart_distortion(page, tmp_path, width):
    page.set_viewport_size({"width": width, "height": 900})
    _open(page, _report(tmp_path / "report.html"))
    toggle = page.locator(".legend-toggle")
    expect(toggle).to_have_accessible_name("Show guide")
    guide = page.locator(".legend-card")
    content = page.locator("#workflow-legend-content")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(content).to_be_hidden()
    collapsed = guide.bounding_box()["height"]
    tabs_top = page.locator(".dashboard-tabs").evaluate("shell => shell.offsetTop")
    assert collapsed < (150 if width == 390 else 110)
    assert toggle.bounding_box()["height"] >= 44
    toggle.focus()
    toggle.press("Enter")
    expect(toggle).to_have_attribute("aria-expanded", "true")
    page.wait_for_function("() => !document.querySelector('.legend-card').getAnimations({subtree: true}).length")
    expanded = guide.bounding_box()["height"]
    assert expanded > collapsed + 120
    expect(page.locator(".legend-item:visible")).to_have_count(6)
    assert content.evaluate("el => el.scrollHeight <= el.clientHeight + 1")
    assert page.locator(".dashboard-tabs").evaluate("shell => shell.offsetTop") - tabs_top == pytest.approx(expanded - collapsed, abs=1)
    artifact_dir = os.environ.get("DASHBOARD_PDF_ARTIFACT_DIR")
    if artifact_dir:
        guide.screenshot(path=str(Path(artifact_dir) / f"guide-expanded-{width}.png"))
    # Sample the actual layout while closing, including space reclaimed above the tabs.
    heights = toggle.evaluate("""button => new Promise(resolve => {
      button.click();
      const guide = button.closest('.legend-card');
      const heights = [];
      const sample = () => {
        heights.push(guide.getBoundingClientRect().height);
        if (guide.getAnimations({subtree: true}).length) requestAnimationFrame(sample);
        else resolve(heights);
      };
      requestAnimationFrame(sample);
    })""")
    assert any(collapsed + 1 < height < expanded - 1 for height in heights)
    assert all(a >= b - 1 for a, b in zip(heights, heights[1:]))
    assert guide.bounding_box()["height"] == pytest.approx(collapsed, abs=1)
    assert page.locator(".dashboard-tabs").evaluate("shell => shell.offsetTop") == pytest.approx(tabs_top, abs=1)
    expect(toggle).to_be_focused()
    expect(content).to_be_hidden()
    for tab in ("aging-panel", "risk-panel", "trends-panel", "staff-panel", "staff-date-panel", "exceptions-panel"):
        page.locator("#tab-" + tab).click()
        _settled(page)
        assert page.locator(".js-plotly-plot:visible").evaluate_all("""plots => plots.every(plot =>
          Math.abs(plot._fullLayout.width - plot.clientWidth) < 2)""")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if artifact_dir:
        guide.screenshot(path=str(Path(artifact_dir) / f"guide-collapsed-{width}.png"))


def test_process_guide_handles_reversal_resize_reduced_motion_and_print(page, tmp_path):
    _open(page, _report(tmp_path / "report.html"))
    toggle = page.locator(".legend-toggle")
    toggle.evaluate("""async button => {
      button.click();
      await new Promise(requestAnimationFrame);
      button.click();
      await new Promise(requestAnimationFrame);
      button.click();
    }""")
    page.set_viewport_size({"width": 390, "height": 700})
    page.wait_for_function("() => !document.querySelector('.legend-card').getAnimations({subtree: true}).length")
    expect(toggle).to_have_attribute("aria-expanded", "true")
    assert page.locator("#workflow-legend-content").evaluate("el => el.scrollHeight <= el.clientHeight + 1")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.emulate_media(reduced_motion="reduce")
    toggle.press("Space")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(page.locator("#workflow-legend-content")).to_be_hidden()
    assert page.locator(".legend-card").evaluate("el => !el.getAnimations({subtree: true}).length")
    page.emulate_media(reduced_motion="no-preference")
    # Both browser printing and Save as PDF must finish an in-flight guide animation.
    toggle.evaluate("button => button.click()")
    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
    assert page.locator(".legend-card").evaluate("el => !el.getAnimations({subtree: true}).length")
    toggle.evaluate("button => button.click()")
    _prepare(page)
    page.emulate_media(media="print")
    expect(toggle).to_be_hidden()
    expect(page.locator(".legend-item:visible")).to_have_count(6)
    page.evaluate("window.dispatchEvent(new Event('afterprint'))")
    page.emulate_media(media="screen")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(page.locator("#workflow-legend-content")).to_be_hidden()


def test_guide_resize_with_visible_scrollbars_and_reduced_motion(page, tmp_path):
    page.set_viewport_size({"width": 1440, "height": 2000})
    page.emulate_media(reduced_motion="reduce")
    _open(page, _report(tmp_path / "scrollbars.html"))
    page.add_style_tag(content="::-webkit-scrollbar { width: 17px; }")
    page.locator("#tab-staff-panel").click()
    _settled(page)
    toggle = page.locator(".legend-toggle")
    shell = page.locator(".dashboard-shell")
    closed_height = shell.bounding_box()["height"]
    toggle.evaluate("button => button.click()")
    open_height = shell.bounding_box()["height"]
    toggle.evaluate("button => button.click()")
    page.set_viewport_size({"width": 1440, "height": int((closed_height + open_height) / 2)})
    plot_fits = """() => {
      const plot = document.getElementById('plot-submitted-by-workload');
      return Math.abs(plot._fullLayout.width - plot.clientWidth) < 1;
    }"""
    page.wait_for_function(plot_fits)
    for expanded in (True, False):
        toggle.evaluate("button => button.click()")
        expect(toggle).to_have_attribute("aria-expanded", str(expanded).lower())
        page.wait_for_function("width => document.documentElement.clientWidth === width",
                               arg=1423 if expanded else 1440)
        page.wait_for_function(plot_fits)


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
    page.set_viewport_size({"width": 1440, "height": 600})
    _open(page, _report(tmp_path / "report.html"))
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
    page.evaluate("window.scrollTo({top: document.documentElement.scrollHeight, behavior: 'instant'})")
    expect(tip).to_be_hidden()


@pytest.mark.parametrize("width", [1440, 390])
def test_chart_table_and_long_tooltips_escape_card_clipping(page, tmp_path, width):
    page.set_viewport_size({"width": width, "height": 700})
    _open(page, _report(tmp_path / "report.html"))
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
    page.locator("#tab-operations-panel").click()
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
    assert page.locator('[data-tab-panel="sections"]:visible').count() == 5
    expect(page.locator("#dashboard-tooltip-layer")).to_be_hidden()
    page.evaluate("window.dispatchEvent(new Event('afterprint'))")
    page.emulate_media(media="screen")
    expect(page.locator("#trends-panel")).to_be_visible()
