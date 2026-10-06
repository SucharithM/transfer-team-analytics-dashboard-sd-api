"""Browser checks are opt-in: DASHBOARD_PDF_BROWSER=chrome (or msedge)."""

import os
from pathlib import Path

import pandas as pd
import pytest
from playwright.sync_api import expect, sync_playwright

from workflow_dashboard.analytics import build_analytics
from workflow_dashboard.config import DashboardConfig
from workflow_dashboard.dashboard_content import PAGE
from workflow_dashboard.dashboard_html import render_dashboard

from .test_analytics_cohorts import GENERATED_AT, sample_cases
from .test_outputs import _history_frames


def _report(path, scenario="sample"):
    cases = sample_cases()
    if scenario == "empty":
        cases = cases.iloc[:0]
    elif scenario == "stress":
        cases = pd.concat([cases.iloc[[0]]] * 120, ignore_index=True)
        cases["record_id"] = [f"synthetic-{i:03}" for i in range(len(cases))]
        cases["item_label"] = "Synthetic long label for a transcript evaluation case"
        cases["step_name"] = (
            "Transcript Evaluator - Pending Additional Synthetic Documentation"
        )
        cases["age_days"] = 30.0
        cases["idle_days"] = 8.0
        cases["submitted_at"] = GENERATED_AT - pd.Timedelta(days=30)
        cases["last_activity_at"] = GENERATED_AT - pd.Timedelta(days=8)
    analytics = build_analytics(
        cases, config=DashboardConfig(), generated_at=GENERATED_AT
    )
    history, owners = _history_frames(analytics)
    return render_dashboard(
        df=cases,
        analytics=analytics,
        history=history,
        owner_history=owners,
        output_path=path,
    )


def test_pdf_action_is_embedded_without_creating_a_pdf(tmp_path):
    markup = _report(tmp_path / "report.html").read_text(encoding="utf-8")
    assert PAGE.save_pdf in markup
    assert PAGE.save_pdf_hint in markup
    assert 'aria-describedby="pdf-export-hint"' in markup
    assert 'role="status" aria-live="polite"' in markup
    assert set(path.suffix for path in tmp_path.iterdir()) == {".html"}


@pytest.fixture
def browser():
    channel = os.environ.get("DASHBOARD_PDF_BROWSER")
    if not channel:
        pytest.skip(
            "Set DASHBOARD_PDF_BROWSER=chrome or msedge to run real browser checks"
        )
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(channel=channel)
        yield instance
        instance.close()


@pytest.fixture
def page(browser):
    context = browser.new_context(
        viewport={"width": 1440, "height": 1000}, offline=True
    )
    value = context.new_page()
    errors = []
    value.on("pageerror", lambda error: errors.append(str(error)))
    value.add_init_script(
        "window.printCalls = 0; window.print = () => { window.printCalls++; };"
    )
    yield value
    assert not errors
    context.close()


def _open(page, path):
    page.goto(path.as_uri())
    page.wait_for_function(
        "Array.from(document.querySelectorAll('.chart-container .js-plotly-plot')).every(p => p.dataset.pdfReady === 'true')"
    )


def _prepare(page):
    before = page.evaluate("window.printCalls")
    page.locator("#save-pdf").click()
    page.wait_for_function("count => window.printCalls === count", arg=before + 1)
    assert page.locator("#save-pdf").is_disabled()
    assert (
        page.locator(".pdf-chart").count()
        == page.locator(".chart-container .js-plotly-plot").count()
    )
    for image in page.locator(".pdf-chart").all():
        assert image.get_attribute("alt") == image.evaluate(
            'image => image.closest(".chart-container").getAttribute("aria-label")'
        )
    for title in (
        "Current Open Cases",
        "Progress and Aging of Open Cases",
        "Open Cases Risk and Action Overview",
    ):
        assert page.locator(f'.pdf-chart[alt="{title}"]').count() == 1


@pytest.mark.parametrize("width", [1440, 1024, 720, 390])
def test_header_layout_and_tooltip(page, tmp_path, width):
    page.set_viewport_size({"width": width, "height": 1000})
    _open(page, _report(tmp_path / "report.html"))
    button = page.get_by_role("button", name=PAGE.save_pdf)
    hint = page.locator("#pdf-export-hint")
    expect(hint).to_be_hidden()
    header_height = page.locator(".dashboard-header").bounding_box()["height"]
    assert page.locator(".dashboard-header").evaluate("""header => {
      const title = header.querySelector('h1').getBoundingClientRect();
      const brand = header.querySelector('.header-top').getBoundingClientRect();
      return title.top >= brand.bottom && title.width >= header.clientWidth - 60;
    }""")
    for selector in (".header-top", "h1", ".header-utility-row", "#save-pdf"):
        bounds = page.locator(f".dashboard-header {selector}").bounding_box()
        assert bounds["x"] >= 0
        assert bounds["x"] + bounds["width"] <= width
    assert page.locator(".dashboard-header").evaluate(
        "header => header.scrollWidth <= header.clientWidth"
    )
    assert page.locator(".dashboard-header > p").all_text_contents() == list(
        PAGE.intro_paragraphs
    )
    button.hover()
    expect(hint).to_be_visible()
    hint.hover()
    expect(hint).to_be_visible()
    assert page.locator(".dashboard-header").bounding_box()["height"] == header_height
    assert hint.bounding_box()["x"] >= 0
    assert hint.bounding_box()["x"] + hint.bounding_box()["width"] <= width
    page.mouse.move(0, 0)
    expect(hint).to_be_hidden()
    button.focus()
    expect(hint).to_be_visible()
    button.press("Escape")
    expect(hint).to_be_hidden()
    page.locator(".info-button").first.focus()
    button.focus()
    expect(hint).to_be_visible()
    artifact_dir = os.environ.get("DASHBOARD_PDF_ARTIFACT_DIR")
    if artifact_dir:
        page.mouse.move(0, 0)
        button.evaluate("button => button.blur()")
        page.locator(".dashboard-header").screenshot(
            path=str(Path(artifact_dir) / f"header-{width}.png")
        )


def test_keyboard_loading_feedback_and_print_restore(page, tmp_path):
    _open(page, _report(tmp_path / "report.html"))
    button = page.locator("#save-pdf")
    width = button.bounding_box()["width"]
    # Hold preparation until the loading state can be inspected deterministically.
    page.evaluate("""() => {
      const original = Plotly.toImage;
      Plotly.toImage = async (...args) => {
        await new Promise(resolve => { window.releasePdfPreparation = resolve; });
        Plotly.toImage = original;
        return original(...args);
      };
    }""")
    button.focus()
    button.press("Enter")
    expect(button).to_be_disabled()
    expect(button).to_have_attribute("aria-busy", "true")
    expect(button).to_have_text(PAGE.preparing_pdf)
    expect(page.locator(".pdf-spinner")).to_be_visible()
    expect(page.locator(".pdf-printer-icon")).to_be_hidden()
    expect(page.locator("#pdf-export-hint")).to_be_hidden()
    assert button.bounding_box()["width"] == width
    assert page.evaluate("window.printCalls") == 0
    page.emulate_media(reduced_motion="reduce")
    assert (
        page.locator(".pdf-spinner").evaluate(
            "spinner => getComputedStyle(spinner).animationName"
        )
        == "none"
    )
    page.wait_for_function("typeof window.releasePdfPreparation === 'function'")
    page.evaluate("window.releasePdfPreparation()")
    page.wait_for_function("window.printCalls === 1")
    page.evaluate("window.dispatchEvent(new Event('afterprint'))")
    expect(button).to_be_enabled()
    expect(button).to_have_text(PAGE.save_pdf)
    expect(button).to_be_focused()
    expect(page.locator(".pdf-spinner")).to_be_hidden()
    expect(page.locator(".pdf-printer-icon")).to_be_visible()
    assert not button.get_attribute("aria-busy")
    button.press("Space")
    page.wait_for_function("window.printCalls === 2")
    page.evaluate("window.dispatchEvent(new Event('afterprint'))")
    expect(button).to_have_text(PAGE.save_pdf)
    page.emulate_media(media="print")
    expect(page.locator(".pdf-export")).to_be_hidden()


def test_touch_action_target(browser, tmp_path):
    with browser.new_context(
        has_touch=True, is_mobile=True, viewport={"width": 390, "height": 900}
    ) as context:
        touch_page = context.new_page()
        _open(touch_page, _report(tmp_path / "touch-report.html"))
        assert touch_page.locator("#save-pdf").bounding_box()["height"] >= 44


@pytest.mark.parametrize("scenario", ["sample", "empty", "stress"])
def test_offline_pdf_layout_and_restore(page, tmp_path, scenario):
    artifact_dir = Path(os.environ.get("DASHBOARD_PDF_ARTIFACT_DIR", str(tmp_path)))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    _open(page, _report(artifact_dir / f"{scenario}.html", scenario))
    if scenario != "empty":
        page.locator("[data-action-bucket]:not([disabled])").first.click()
        selected = page.locator("#age-idle-action-rows").inner_text()
        assert selected
    _prepare(page)
    page.emulate_media(media="print")
    # Exercise landscape's actual printable width, including formerly scrolling tables.
    page.set_viewport_size({"width": 980, "height": 740})
    assert page.locator("#save-pdf").is_hidden()
    assert page.locator(".js-plotly-plot").first.is_hidden()
    assert page.locator(".pdf-chart").first.is_visible()
    assert page.evaluate(
        """() => Array.from(document.querySelectorAll('.data-table')).every(
        t => t.scrollWidth <= t.clientWidth + 1)"""
    )
    if scenario == "stress":
        assert page.locator("#problem-rows-table tbody tr").count() == 100
        assert page.locator("#age-idle-action-rows tr").count() == 120
    pdf = page.pdf(
        path=str(artifact_dir / f"{scenario}.pdf"),
        prefer_css_page_size=True,
        print_background=True,
    )
    assert pdf.startswith(b"%PDF")
    page.evaluate("window.dispatchEvent(new Event('afterprint'))")
    page.emulate_media(media="screen")
    assert page.locator("#save-pdf").is_enabled()
    expect(page.locator("#save-pdf")).to_have_text(PAGE.save_pdf)
    expect(page.locator("#pdf-export-status")).to_be_empty()
    expect(page.locator(".pdf-spinner")).to_be_hidden()
    assert page.locator(".pdf-chart").count() == 0
    assert page.locator(".js-plotly-plot").first.is_visible()
    if scenario != "empty":
        assert page.locator("#age-idle-action-rows").inner_text() == selected
        page.locator("#age-idle-action-clear").click()
        assert page.locator("#age-idle-action-drilldown").is_hidden()
    _prepare(page)
    page.evaluate("window.dispatchEvent(new Event('afterprint'))")
    assert page.locator("#save-pdf").is_enabled()


def test_preparation_failure_and_duplicate_clicks(page, tmp_path):
    _open(page, _report(tmp_path / "report.html"))
    page.evaluate("""() => {
      const original = Plotly.toImage;
      let attempts = 0;
      Plotly.toImage = (...args) => ++attempts === 2
        ? Promise.reject(new Error('synthetic failure')) : original(...args);
    }""")
    page.locator("#save-pdf").click()
    page.wait_for_function(
        "document.getElementById('pdf-export-status').textContent.includes('Please try again')"
    )
    assert page.evaluate("window.printCalls") == 0
    assert page.locator("#save-pdf").is_enabled()
    expect(page.locator("#save-pdf")).to_have_text(PAGE.save_pdf)
    expect(page.locator("#pdf-export-status")).to_have_text(PAGE.pdf_error)
    expect(page.locator("#save-pdf")).to_be_focused()
    expect(page.locator(".pdf-spinner")).to_be_hidden()
    assert page.locator(".pdf-chart").count() == 0
    # Two events in the same turn simulate a fast duplicate action, even bypassing disabled UI.
    page.evaluate("""() => {
      const button = document.getElementById('save-pdf');
      button.dispatchEvent(new Event('click'));
      button.dispatchEvent(new Event('click'));
    }""")
    page.wait_for_function("window.printCalls === 1")
    assert page.locator(".pdf-chart").count() == 13
    page.evaluate("window.dispatchEvent(new Event('afterprint'))")
    assert page.locator("#save-pdf").is_enabled()
    expect(page.locator("#pdf-export-status")).to_be_empty()
